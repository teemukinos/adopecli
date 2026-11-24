"""Precise stored-field revisions with native text regeneration and cold proof.

Selectors address one stored occurrence. Translation also offsets its motion
position keys and path. Fill edits change documented native fields; text outlines
are produced by the maintained engine. No auto-key or imported script runs.
"""
import copy
import json
from pathlib import Path
import time

from . import animate_document as document, animate_format as format, animate_project as project
from . import animate_scene as scene, animate_semantics as semantics
from .animate_graph import fields
from .animate_native_probe import NativeInspector
from .animate_properties import f32
from .animate_unicode import trim


def selector(value):
    fields(value, ('layer', 'frame', 'element'), ('scene', 'symbol'), 'revision selector')
    if ('scene' in value) == ('symbol' in value):
        raise ValueError('Animate revision selector requires exactly one scene or symbol')
    for key in ('layer', 'element', 'symbol'):
        if key in value and (type(value[key]) is not int or not 1 <= value[key] < format.MAX_ID):
            raise ValueError('Animate revision selector requires exact positive native IDs')
    if type(value['frame']) is not int or not 0 <= value['frame'] < 1_000_000:
        raise ValueError('Animate revision selector requires a bounded keyframe start')
    if 'scene' in value and (type(value['scene']) is not int or not 0 <= value['scene'] < 64):
        raise ValueError('Animate revision selector requires a zero-based scene index')


def validate(edits):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 128:
        raise ValueError('Animate revision requires 1 to 128 typed edits')
    text_bytes = 0
    for edit in edits:
        fields(edit, ('selector', 'action'), ('dx', 'dy', 'color', 'expected', 'text'), 'revision edit')
        selector(edit['selector'])
        action = edit['action']
        if action == 'translate':
            fields(edit, ('selector', 'action', 'dx', 'dy'), (), 'translation edit')
            if any(not format.number(edit[key], -8192, 8192) for key in ('dx', 'dy')):
                raise ValueError('Animate translation exceeds its finite coordinate budget')
        elif action == 'fill':
            fields(edit, ('selector', 'action', 'color'), (), 'fill edit')
            if edit['color'] is not None:
                scene.color(edit['color'])
        elif action == 'replace_text':
            fields(edit, ('selector', 'action', 'expected', 'text'), (), 'text replacement')
            if (not scene.text(edit['expected'], 8192) or not scene.text(edit['text'], 8192)
                    or not trim(edit['text']) or len(edit['text'].encode('utf-8')) > 32768
                    or len(edit['expected'].encode('utf-8')) > 32768):
                raise ValueError('Animate text replacement requires bounded exact old and nonblank new text')
            text_bytes += len(edit['text'].encode('utf-8'))
        else:
            raise ValueError('Animate revision action must be translate, fill or replace_text')
    if text_bytes > 1 << 20:
        raise ValueError('Animate revision exceeds its aggregate replacement-text budget')


def keyframe(stored, selected):
    """Return the layer and exact key, never a containing tween frame."""
    if 'scene' in selected:
        if selected['scene'] >= len(stored['scenes']):
            raise ValueError('Animate revision scene does not exist')
        timeline = stored['scenes'][selected['scene']]['timeline']
    else:
        symbols = [item for item in stored['library'] if item['id'] == selected['symbol']]
        if len(symbols) != 1:
            raise ValueError('Animate revision symbol does not exist')
        timeline = symbols[0]['timeline']
    layers = [item for item in timeline['layers'] if item['id'] == selected['layer']]
    if len(layers) != 1:
        raise ValueError('Animate revision layer does not belong to its selected timeline')
    keys = [key for key in layers[0]['keyframes'] if key['start'] == selected['frame']]
    if len(keys) != 1:
        raise ValueError('Animate revision requires an existing exact keyframe start')
    return layers[0], keys[0]


def locate(stored, selected):
    _, key = keyframe(stored, selected)
    elements = [item for item in key.get('elements', []) if item['id'] == selected['element']]
    if len(elements) != 1:
        raise ValueError('Animate revision element does not exist in the selected keyframe')
    return elements[0]


def translate_motion(key, expected, identity, dx, dy):
    """Offset the selected object's entire position trajectory, preserving timing."""
    motion = key.get('motion')
    if motion is None or motion['target'] != identity:
        return {'position_keys': 0, 'path_commands': 0}
    keys = commands = 0
    for track, wanted in zip(motion.get('tracks', []), expected['motion']['tracks']):
        if track['property'] in ('x', 'y'):
            delta = dx if track['property'] == 'x' else dy
            for actual, desired in zip(track.get('keys', []), wanted['keys']):
                value = f32(f32(actual['value']) + delta)
                actual['value'] = value; desired['value'] = value; keys += 1
    if motion.get('path') is not None:
        parts = []
        for command, coordinates in format.native_path(motion['path']).commands:
            points = [f32(value + (dx if index % 2 == 0 else dy)) for index, value in enumerate(coordinates)]
            parts.append(command + ' '.join(str(value) for value in points)); commands += 1
        path = ''.join(parts); motion['path'] = path
        expected['motion']['path'] = format.native_path(path).digest
    return {'position_keys': keys, 'path_commands': commands}


def compact_paths(envelope):
    """Reindex only referenced table entries after a text outline is replaced."""
    old = envelope['paths']; paths = []; indices = {}; old_hashes = {}
    timelines = [s['timeline'] for s in envelope['document']['scenes']]
    timelines += [s['timeline'] for s in envelope['document']['library']]
    for timeline in timelines:
        for layer in timeline['layers']:
            for key in layer['keyframes']:
                for element in key.get('elements', []):
                    kind = element['kind']
                    if isinstance(kind, dict) and ('Shape' in kind or 'Text' in kind):
                        tag, field = ('Shape', 'path') if 'Shape' in kind else ('Text', 'outline')
                        value = kind[tag][field]
                        if type(value) is int:
                            index = value; value = old[index]
                            if index not in old_hashes:
                                old_hashes[index] = format.native_path(value).digest
                            identity = old_hashes[index]
                        else:
                            identity = format.native_path(value).digest
                        if identity not in indices:
                            indices[identity] = len(paths); paths.append(value)
                        kind[tag][field] = indices[identity]
    envelope['paths'] = paths


def affected_scenes(stored, edits):
    direct = {edit['selector']['scene'] for edit in edits if 'scene' in edit['selector']}
    symbols = {edit['selector']['symbol'] for edit in edits if 'symbol' in edit['selector']}
    def references(timeline):
        return {element['kind']['Symbol']['symbol'] for layer in timeline['layers']
                for key in layer['keyframes'] for element in key.get('elements', [])
                if isinstance(element['kind'], dict) and 'Symbol' in element['kind']}
    parents = {symbol['id']: references(symbol['timeline']) for symbol in stored['library']}
    changed = True
    while changed:
        previous = len(symbols)
        symbols.update(identity for identity, children in parents.items() if children & symbols)
        changed = len(symbols) != previous
    direct.update(index for index, item in enumerate(stored['scenes']) if references(item['timeline']) & symbols)
    return sorted(direct)


def replace_text(root, body, text, executable, inspector):
    """Use a native text prototype, then transfer only its derived layout fields."""
    params = {'name': 'Text', 'type': 'text', 'x': 0, 'y': 0, 'text': text,
              'font': body['font'], 'size': body['size'], 'color': '#000000',
              **{key: body.get(key, default) for key, default in
                 [('bold', False), ('italic', False), ('align', 'left'), ('letter_spacing', 0),
                  ('line_spacing', 0), ('width', None)]}}
    request = {'stage': {'width': 1, 'height': 1, 'fps': 24, 'background': '#ffffff'},
               'scenes': [{'name': 'Text layout', 'layers': [{'name': 'Text', 'keyframes': [
                   {'start': 0, 'duration': 1, 'objects': [params]}]}]}]}
    seconds = inspector.deadline - time.monotonic()
    if inspector.cancelled() or seconds <= 0:
        raise ValueError('Animate revision cancelled or timed out')
    source, report = scene.create(root, request, executable, cancelled=inspector.cancelled, seconds=min(seconds, 120))
    profile = document.read_native(source)
    generated = profile['envelope']['document']['scenes'][0]['timeline']['layers'][0]['keyframes'][0]['elements'][0]['kind']['Text']
    outline = generated['outline']
    if type(outline) is int:
        outline = profile['envelope']['paths'][outline]
    return {'text': text, 'outline': outline, 'box_width': generated['box_width'], 'box_height': generated['box_height']}, report['text']


def apply(root, source, edits, executable, *, cancelled=lambda: False, seconds=120):
    """Prepare a revised source; caller qualifies previews and publishes the job."""
    validate(edits)
    root = Path(root).absolute(); root.mkdir()
    inspector = NativeInspector(executable, root, cancelled=cancelled, seconds=seconds)
    original = document.read_native(source, inspect_sound=inspector)
    original['native_state'] = inspector.preservation(original['source_bytes'])
    original['native_semantics'] = inspector.reconciliation(original)
    envelope = copy.deepcopy(original['envelope'])
    expected = semantics.normalized(original); reports = []; layout_bytes = 0
    for index, edit in enumerate(edits):
        if cancelled() or time.monotonic() >= inspector.deadline:
            raise ValueError('Animate revision cancelled or timed out')
        target = locate(envelope['document'], edit['selector']); wanted = locate(expected, edit['selector'])
        action = edit['action']; derived = motion_report = None
        if action == 'translate':
            layer, key = keyframe(envelope['document'], edit['selector'])
            if layer.get('kind') == 'Armature':
                raise ValueError('Animate armature translation requires a dedicated pose revision')
            transform = list(wanted['transform']['m'])
            transform[4] = f32(transform[4] + f32(edit['dx']))
            transform[5] = f32(transform[5] + f32(edit['dy']))
            target['transform'] = {'m': transform}; wanted['transform'] = {'m': transform}
            _, expected_key = keyframe(expected, edit['selector'])
            motion_report = translate_motion(key, expected_key, edit['selector']['element'], f32(edit['dx']), f32(edit['dy']))
        elif action == 'fill':
            if not isinstance(target['kind'], dict) or 'Shape' not in target['kind']:
                raise ValueError('Animate fill revision requires a shape')
            fill = None if edit['color'] is None else {'Solid': scene.color(edit['color'])}
            target['kind']['Shape']['fill'] = fill
            wanted['kind']['Shape']['fill'] = None if fill is None else semantics.paint(fill)
        else:
            if not isinstance(target['kind'], dict) or 'Text' not in target['kind']:
                raise ValueError('Animate text replacement requires a text element')
            body = target['kind']['Text']
            if body['text'] != edit['expected']:
                raise ValueError('Animate text replacement does not match the expected source text')
            layout, derived = replace_text(root / ('text-' + str(index)), body, edit['text'], executable, inspector)
            layout_bytes += len(json.dumps(layout).encode())
            if layout_bytes > format.MAX_JSON:
                raise ValueError('Animate revision exceeds its aggregate native layout budget')
            body.update(layout)
            wanted['kind']['Text'].update(text=edit['text'], outline=format.native_path(layout['outline']).digest,
                box_width=f32(layout['box_width']), box_height=f32(layout['box_height']))
        reports.append({'edit': copy.deepcopy(edit), 'native_text': derived, 'motion_translation': motion_report})
    compact_paths(envelope)
    revised = document.inspect_bytes(json.dumps(envelope).encode(), inspect_sound=project.reuse_sounds(original))
    difference = semantics.difference(expected, semantics.normalized(revised))
    if difference is not None:
        raise ValueError('Animate revision changed an unrequested stored field at ' + difference)
    if format.read_bytes(source) != original['source_bytes']:
        raise ValueError('Animate revision changed its original source')
    if cancelled() or time.monotonic() >= inspector.deadline:
        raise ValueError('Animate revision cancelled or timed out')
    path = root / 'revised.anicraft'; path.write_bytes(revised['source_bytes'])
    return path, {'source_sha256': original['source_sha256'], 'edits': reports,
                  'semantic_sha256': semantics.digest(expected), 'unrequested_stored_fields_verified': True,
                  'affected_scenes': affected_scenes(envelope['document'], edits),
                  'scene_frames': original['graph']['scene_frames'], 'source_bytes_unchanged': True,
                  'scope': 'Selected occurrence and its position trajectory. Other keyframes, motion timing and non-position tracks remain unchanged.',
                  'publication_authorized': False}


def compare_previews(before, after, revision):
    boundaries = []; offset = 0
    for length in revision['scene_frames']:
        boundaries.append((offset, offset + length)); offset += length
    untouched = {index for index in range(len(boundaries))} - set(revision['affected_scenes'])
    expected = {row['frame']: row for row in before['previews']}
    actual = {row['frame']: row for row in after['previews']}
    if expected.keys() != actual.keys():
        raise ValueError('Animate revision preview selection changed')
    checked = []; changed = []
    for frame, row in expected.items():
        if any(boundaries[index][0] <= frame < boundaries[index][1] for index in untouched):
            if row != actual[frame]:
                raise ValueError('Animate revision changed a selected preview in an untargeted scene')
            checked.append(frame)
        if row['rgba_sha256'] != actual[frame]['rgba_sha256']:
            changed.append(frame)
    return {'untargeted_preview_frames': checked, 'untargeted_preview_pixels_verified': True,
            'changed_preview_frames': changed, 'scope': 'Selected static movie frames; affected scenes are conservative.'}


def verify_text(report, edits):
    """Recheck the final document's edited text, not only its layout prototypes."""
    targets = {json.dumps(edit['selector'], sort_keys=True) for edit in edits if edit['action'] == 'replace_text'}
    if not targets:
        return []
    native = report['source']['native_text']
    if native is None:
        raise ValueError('Animate text revision requires final native text inspection')
    found = {}
    for row in native['records']:
        identity = json.dumps(row['selector'], sort_keys=True)
        if identity in targets:
            if identity in found or not row['glyph_coverage_verified'] or not row['native_layout_reproduced']:
                raise ValueError('Animate revised text failed final glyph or layout qualification')
            found[identity] = row['selector']
    if found.keys() != targets:
        raise ValueError('Animate final text inspection omitted a revised occurrence')
    return [found[identity] for identity in sorted(found)]
