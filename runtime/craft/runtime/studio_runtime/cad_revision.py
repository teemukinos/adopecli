"""Typed optimistic CAD edits with exact preservation of unrelated source data.

Edits are replayable model changes, not native solve or execution permission.
Changing a parameter expression leaves geometry untouched until a verified solve.
"""
import copy
import json
import math
import re

from . import cad_source as source
from .cad_source import require

KINDS = {'geometry.set', 'text.replace', 'entity.properties', 'parameter.expression', 'panel.solid', 'panel.solve'}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def encoded(value): return (canonical(value)+'\n').encode('ascii')


def finite(value, *, positive=False):
    require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e12
            and (not positive or value > 0), 'edit scalar exceeds finite range')
    return float(value)


def point(value):
    require(type(value) is dict and set(value) == {'x', 'y', 'z'}, 'point must own three coordinates')
    return {key: finite(value[key]) for key in ('x', 'y', 'z')}


def plain(value, limit, *, empty=True):
    require(type(value) is str and (empty or bool(value.strip())) and len(value.encode('utf-8')) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'edit text must be bounded plain text')
    return value


def locate(document, path):
    node = document
    for component in path.split('/')[1:]:
        key = component.replace('~1', '/').replace('~0', '~')
        node = node[int(key)] if type(node) is list else node[key]
    return node


def revise_bytes(data, expected_sha256, edits):
    require(type(data) is bytes and type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256)
            and source.sha(data) == expected_sha256, 'revision source hash is stale or invalid')
    try: request = encoded(edits)
    except (TypeError, ValueError, RecursionError) as error: raise ValueError('CAD edits require finite JSON') from error
    require(len(request) <= 1 << 20, 'edit request exceeds byte budget')
    edits = source.strict_json(request)
    require(type(edits) is list and 1 <= len(edits) <= 128, 'revision needs one to 128 edits')
    before = source.inspect_bytes(data, 'json'); original = before['document']
    from . import cad_history
    compound = [edit for edit in edits if type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in cad_history.KINDS]
    if compound:
        require(len(edits)==1, 'panel history must be a separate atomic revision')
        change=cad_history.apply(original,edits[0]);output=encoded(change['document'])
        require(canonical(change['document'])!=canonical(original), 'revision changes nothing')
        after=source.inspect_bytes(output,'json')
        require(before['inventory']['resources']==after['inventory']['resources'] and before['inventory']['external_references']==after['inventory']['external_references'],
                'panel history changed resource ownership')
        return {'data':output,'document':change['document'],'source_sha256':expected_sha256,'revision_sha256':source.sha(output),'edits':edits,
                'changed_paths':change['changed_paths'],'solve_required':edits[0]['kind']=='panel.solve',
                'pending_qualification':sorted(set(after['pending_qualification'])|{'native-recipe-replay'}
                    |({'native-solid-regeneration'} if edits[0]['kind']=='panel.solve' and edits[0]['mesh_handle'] is not None else set())),
                'measurements':change['measurements'],'engine_admission_complete':False}
    owners = {entity['handle']: (path, entity) for path, entity in before['inventory']['entities']}
    bound = []; selected = set(); solve_required = False
    for edit in edits:
        require(type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in KINDS, 'edit kind invalid')
        kind = edit['kind']
        if kind == 'parameter.expression':
            require(set(edit) == {'kind', 'name', 'expected', 'value'}, 'parameter edit fields differ')
            name = plain(edit['name'], 256, empty=False)
            require(type(original['parametric']) is dict, 'parametric settings invalid')
            rows = source.sequence(original['parametric'].get('parameters'), 'parameters', 256)
            found = [(index, row) for index, row in enumerate(rows) if type(row) is dict and row.get('name') == name]
            require(len(found) == 1, 'parameter identity missing or ambiguous')
            index, row = found[0]; path = f'/parametric/parameters/{index}'
            require(type(edit['expected']) is str and row.get('expr') == edit['expected'], 'parameter expression changed')
            value = plain(edit['value'], 1024, empty=False); require(value.isascii(), 'parameter expression must be ASCII')
            replacement = {'expr': value}; solve_required = True
        else:
            require(type(edit.get('handle')) is int and edit['handle'] in owners, 'edit handle is not an owned entity')
            path, entity = owners[edit['handle']]
            if kind == 'geometry.set':
                require(set(edit) == {'kind', 'handle', 'expected', 'set'}, 'geometry edit fields differ')
                geometry = entity['kind']; shape = geometry['type']
                require(shape in ('line', 'circle'), 'geometry type needs a separate typed edit')
                required = {'type', 'a', 'b'} if shape == 'line' else {'type', 'center', 'radius'}
                require(required <= set(geometry), 'geometry omits required native fields')
                for key in required-{'type'}:
                    if key == 'radius': finite(geometry[key], positive=True)
                    else: point(geometry[key])
                require(canonical(geometry) == canonical(edit['expected']), 'geometry changed since inspection')
                patch = edit['set']; allowed = {'a', 'b'} if shape == 'line' else {'center', 'radius'}
                require(type(patch) is dict and patch and set(patch) <= allowed, 'geometry patch fields differ')
                replacement = {key: finite(value, positive=True) if key == 'radius' else point(value) for key, value in patch.items()}
                path += '/kind'; solve_required = bool(original['constraints']) or solve_required
            elif kind == 'text.replace':
                require(set(edit) == {'kind', 'handle', 'expected', 'value'}, 'text edit fields differ')
                geometry = entity['kind']; require(geometry['type'] == 'text', 'text edit needs a native single-line text entity')
                require(type(edit['expected']) is str and geometry.get('value') == edit['expected'], 'text changed since inspection')
                replacement = {'value': plain(edit['value'], 1 << 20)}; path += '/kind'
            else:
                require(set(edit) == {'kind', 'handle', 'expected', 'set'}, 'property edit fields differ')
                common = entity.get('common'); patch = edit['set']
                require(type(common) is dict and type(patch) is dict and patch
                        and set(patch) <= {'layer', 'visible', 'ltscale', 'thickness'}, 'property patch fields differ')
                require(type(edit['expected']) is dict and set(edit['expected']) == set(patch)
                        and set(patch) <= set(common) and canonical(edit['expected']) == canonical({k: common[k] for k in patch}),
                        'entity properties changed since inspection')
                replacement = {}
                for key, value in patch.items():
                    if key == 'visible': require(type(value) is bool, 'visibility must be boolean'); replacement[key] = value
                    elif key == 'layer':
                        plain(value, 256, empty=False)
                        layers = source.sequence(original['layers'], 'layers', 100_000)
                        require(sum(type(row) is dict and row.get('name') == value for row in layers) == 1, 'target layer missing or ambiguous')
                        replacement[key] = value
                    else: replacement[key] = finite(value, positive=key == 'ltscale')
                path += '/common'
        require(path not in selected, 'edits compete for the same native owner')
        selected.add(path); bound.append((path, replacement))
    result = copy.deepcopy(original)
    for path, replacement in bound: locate(result, path).update(replacement)
    require(canonical(result) != canonical(original), 'revision changes nothing')
    output = encoded(result); after = source.inspect_bytes(output, 'json')
    require(before['inventory']['resources'] == after['inventory']['resources']
            and before['inventory']['external_references'] == after['inventory']['external_references'], 'revision changed source resource ownership')
    pending = set(after['pending_qualification'])
    if solve_required:
        pending.add('native-constraint-solve')
        if 'polyfaceMesh' in before['inventory']['entity_kinds']: pending.add('native-solid-regeneration')
    return {'data': output, 'document': result, 'source_sha256': expected_sha256, 'revision_sha256': source.sha(output),
            'edits': edits, 'changed_paths': sorted(selected), 'solve_required': solve_required,
            'pending_qualification': sorted(pending), 'engine_admission_complete': False}
