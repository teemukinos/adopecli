"""Explicit Interface edit contracts and complete native-state comparison.

Only declared content changes and dependency-scoped layout geometry may differ.
Native layout remains authoritative for derived dimensions; every such change
is reported, and publication still requires cold readback and shaping checks.
"""
import copy

from . import interface_document as document, interface_project as project, interface_scene as scene, video


def validate(edits):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 128:
        raise ValueError('Interface revision requires 1 to 128 named edits')
    names = set()
    for edit in edits:
        if not isinstance(edit, dict) or not video.named(edit.get('name')) or edit['name'] in names:
            raise ValueError('Interface edits require unique named targets')
        names.add(edit['name'])
        action = edit.get('action')
        if action == 'replace_text':
            if (set(edit) != {'name', 'action', 'expected', 'text'}
                    or not scene.text(edit['expected'], 16_384, True) or not scene.text(edit['text'], 16_384, True)):
                raise ValueError('Interface text replacement requires exact expected and replacement text')
        elif action == 'fill':
            if (set(edit) != {'name', 'action', 'expected', 'color'}
                    or any(not isinstance(edit[k], str) or not video.COLOR.fullmatch(edit[k]) for k in ('expected', 'color'))):
                raise ValueError('Interface fill revision requires expected and replacement #rrggbb colors')
        elif action == 'move':
            if set(edit) != {'name', 'action', 'dx', 'dy'} or not all(document.number(edit[k], -8192, 8192) for k in ('dx', 'dy')):
                raise ValueError('Interface move requires bounded dx and dy')
        else:
            raise ValueError('Interface edits support replace_text, fill and move')


def ancestors(nodes, node_id):
    current = nodes[str(node_id)]
    while current.get('parent') is not None:
        current = nodes[str(current['parent'])]
        yield current


def descendants(nodes, node_id):
    pending = [node_id]; found = set()
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current); pending.extend(nodes[str(current)].get('children', []))
    return found


def propagated(nodes, node_id, group):
    affected = {node_id}
    while True:
        added = {node['id'] for node in nodes.values() if node.get('source') in affected
                 and group not in node.get('overrides', [])
                 and not (group == 'position' and nodes[str(node['source'])]['type'] == 'component')}
        if added <= affected:
            return affected
        affected.update(added)


def geometry_scope(nodes, affected):
    result = set(affected)
    while True:
        expanded = set(result)
        for node_id in result:
            node = nodes[str(node_id)]
            for parent in [node, *ancestors(nodes, node_id)]:
                if parent.get('layout') or parent['type'] in ('group', 'booleanOp'):
                    expanded.update(descendants(nodes, parent['id']))
        expanded.update(node['id'] for node in nodes.values() if node.get('source') in expanded)
        if expanded == result:
            return result
        result = expanded


def plain_fill(node, color):
    paints = node.get('fills', [])
    expected = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1]
    if len(paints) != 1:
        return False
    paint = paints[0]
    return (set(paint) == {'type', 'color', 'opacity', 'visible', 'blend'} and paint['type'] == 'solid'
            and paint['opacity'] == 1 and paint['visible'] is True and paint['blend'] == 'normal'
            and isinstance(paint['color'], dict) and set(paint['color']) == {'r', 'g', 'b', 'a'}
            and all(document.number(paint['color'][key], 0, 1) and abs(paint['color'][key] - value) <= 1e-7
                    for key, value in zip(('r', 'g', 'b', 'a'), expected)))


def plan(profile, mapping, edit):
    validate([edit]); project.check_mapping(mapping, profile)
    record = mapping.get(edit['name'])
    if record is None:
        raise ValueError('unknown Interface edit target')
    nodes = profile['nodes']; node_id = record['id']; target = nodes[str(node_id)]
    if any(node.get('locked', False) for node in [target, *ancestors(nodes, node_id)]):
        raise ValueError('Interface edit target or ancestor is locked')
    action = edit['action']; group = {'replace_text': 'characters', 'fill': 'fills', 'move': 'position'}[action]
    affected = propagated(nodes, node_id, group)
    expected = copy.deepcopy(profile['document']); expected_nodes = expected['nodes']
    if action == 'replace_text':
        if target['type'] != 'text' or target['characters'] != edit['expected']:
            raise ValueError('Interface replacement does not match the expected source text')
        for identity in affected:
            node = expected_nodes[str(identity)]
            if node['type'] != 'text' or node.get('runs') or node.get('paragraphs'):
                raise ValueError('Interface whole-text replacement requires plain text; styled ranges need a separate contract')
            node['characters'] = edit['text']
        props = {'characters': edit['text']}
    elif action == 'fill':
        if not plain_fill(target, edit['expected']):
            raise ValueError('Interface fill does not match the expected plain solid paint')
        for identity in affected:
            node = nodes[str(identity)]
            if (node.get('bound') or node.get('styles') or node.get('runs')
                    or node.get('style', {}).get('fills') is not None):
                raise ValueError('Interface fill edits of bound or character paints require a separate contract')
        props = {'fill': edit['color']}
    else:
        parent = nodes.get(str(target.get('parent')), {})
        if parent.get('layout') and not target.get('child_layout', {}).get('absolute', False):
            raise ValueError('Interface flow children move through layout settings, not absolute coordinates')
        if parent.get('type') in ('group', 'booleanOp'):
            raise ValueError('Interface group-relative movement requires a separate transform contract')
        for identity in affected:
            node = expected_nodes[str(identity)]
            transform = list(node.get('transform', document.IDENTITY))
            transform[4] += edit['dx']; transform[5] += edit['dy']
            if transform == document.IDENTITY:
                node.pop('transform', None)
            else:
                node['transform'] = transform
        transform = expected_nodes[str(node_id)].get('transform', document.IDENTITY)
        props = {'x': transform[4], 'y': transform[5]}
    # Direct text replacement marks characters even outside an instance. Other
    # override groups are recorded only for a layer linked to a component source.
    linked = target.get('source') is not None
    own_instance = target['type'] == 'instance' and not any(n['type'] == 'instance' for n in ancestors(nodes, node_id))
    overrides = set(target.get('overrides', []))
    if action == 'replace_text' or linked and action == 'fill':
        overrides.add(group)
    elif linked and not own_instance and (edit.get('dx', 0) != 0 or edit.get('dy', 0) != 0):
        overrides.add(group)
    if linked:
        source = nodes[str(target['source'])]
        changed_to_main = (action == 'replace_text' and edit['text'] != target['characters'] and edit['text'] == source.get('characters')
                           or action == 'fill' and not plain_fill(target, edit['color']) and plain_fill(source, edit['color']))
        if changed_to_main:
            overrides.discard(group)
    if overrides:
        expected_nodes[str(node_id)]['overrides'] = sorted(overrides)
    else:
        expected_nodes[str(node_id)].pop('overrides', None)
    # Absolute moves preserve all dimensions and child-local geometry. Only text
    # replacement admits remeasurement/reflow; moving flow children is refused.
    geometry = geometry_scope(nodes, affected) if action == 'replace_text' else set()
    return {'target': node_id, 'action': action, 'affected': affected, 'geometry': geometry,
            'expected': expected, 'props': props, 'color': edit.get('color')}


def verify(before, after, contract):
    expected = copy.deepcopy(contract['expected']); changes = []
    if set(before['nodes']) != set(after['nodes']) or before['assets'] != after['assets']:
        raise ValueError('Interface revision changed node identities or embedded artwork')
    for key, actual in after['nodes'].items():
        node_id = actual['id']; wanted = expected['nodes'][key]; old = before['nodes'][key]
        if contract['action'] == 'fill' and node_id in contract['affected']:
            if not plain_fill(actual, contract['color']):
                raise ValueError('Interface revision did not apply the requested solid fill')
            # Only canonical float32 color representation is taken from readback;
            # every paint property and color value has been checked above.
            wanted['fills'] = copy.deepcopy(actual['fills'])
        if node_id in contract['geometry']:
            fields = []
            sizing = old.get('child_layout', {})
            resize = old.get('auto_resize', 'widthAndHeight') if old['type'] == 'text' else None
            follows = old['type'] in ('group', 'booleanOp')
            if follows or resize == 'widthAndHeight' or sizing.get('sizing_h', 'fixed') in ('hug', 'fill'):
                fields.append('width')
            if follows or resize in ('widthAndHeight', 'height') or sizing.get('sizing_v', 'fixed') in ('hug', 'fill'):
                fields.append('height')
            if resize == 'widthAndHeight' and node_id not in contract['affected']:
                # Untouched content-sized text has the same content and font.
                # Reflow may move it, but cannot excuse a changed intrinsic size.
                fields = [field for field in fields if field not in ('width', 'height')]
            parent = before['nodes'].get(str(old.get('parent')), {})
            if (parent.get('layout') or parent.get('type') in ('group', 'booleanOp')
                    or resize == 'widthAndHeight' and old.get('align_h') in ('right', 'center')):
                fields.append('transform')
            if contract['action'] == 'move' and node_id in contract['affected'] and 'transform' in fields:
                fields.remove('transform')
            for field in fields:
                if field == 'transform' and actual.get(field, document.IDENTITY)[:4] != old.get(field, document.IDENTITY)[:4]:
                    raise ValueError('Interface derived layout unexpectedly changed rotation or scale')
                if actual.get(field) != wanted.get(field):
                    changes.append({'id': node_id, 'field': field, 'before': wanted.get(field), 'after': actual.get(field)})
                if field in actual:
                    wanted[field] = copy.deepcopy(actual[field])
                else:
                    wanted.pop(field, None)
    document.require_state(after, expected, before['assets'])
    return {'target': contract['target'], 'action': contract['action'],
            'content_targets': sorted(contract['affected']), 'derived_geometry': changes,
            'complete_native_fields_verified': True, 'embedded_assets_unchanged': True}


def apply(process, profile, mapping, edits, directory):
    validate(edits); project.check_mapping(mapping, profile)
    reports = []; current = profile
    for index, edit in enumerate(edits):
        contract = plan(current, mapping, edit)
        process.tool('set_properties', ids=[contract['target']], props=contract['props'])
        saved = process.save(directory / ('edit-' + str(index) + '.figcraft'), title=profile['document']['name'])
        reports.append(verify(current, saved, contract)); current = saved
    return current, reports
