"""Structural Animate admission: identities, timelines and library dependencies.

Run after animate_format decoding. This layer does not qualify paint, transforms,
effects, scripts, motion curves, armature poses, media decoding or text shaping.
Those checks and complete native readback are still required before opening an
untrusted project in the production engine. No operation is registered here.
"""
from fractions import Fraction
import struct

from .animate_format import MAX_ID, number

MAX_SCENES = 64
MAX_SYMBOLS = 512
MAX_MEDIA = 256
MAX_FOLDERS = 512
MAX_LAYERS = 1024
MAX_KEYS = 8192
MAX_ELEMENTS = 32768
MAX_FRAMES = 1_000_000
MAX_EXPANDED_ELEMENTS = 32768
MAX_SYMBOL_DEPTH = 32


def fields(value, required, optional, label):
    if (not isinstance(value, dict) or not set(required) <= value.keys()
            or value.keys() - set(required) - set(optional)):
        raise ValueError('Animate ' + label + ' has missing or unknown fields')


def sequence(value, limit, label):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError('Animate ' + label + ' exceeds its item budget')
    return value


def identity(value):
    if type(value) is not int or not 1 <= value < MAX_ID:
        raise ValueError('Animate identity must be a positive allocatable native ID')
    return value


def label(value, *, scene=False, folder=False):
    if not isinstance(value, str) or len(value) > 1024:
        raise ValueError('Animate name must be bounded text')
    if scene and (not value.strip() or len(value.encode('utf-8')) > 256):
        raise ValueError('Animate scene name would be repaired by the native engine')
    if folder and (not value or value != value.strip() or '/' in value or len(value) > 256):
        raise ValueError('Animate library folder name would be repaired by the native engine')


def inspect_graph(document, paths):
    """Return complete native scene lengths and bounded dependency information.

    Expanded counts conservatively include hidden content and the heaviest
    keyframe on each layer. They bound element expansion only, not render memory,
    curve flattening, effects, morphing or nine-slice geometry.
    """
    paths = paths.fork()
    fields(document, ('stage', 'scenes', 'library', 'next_id'),
           ('bitmaps', 'sounds', 'library_tree', 'document_class', 'publish'), 'document')
    stage = document['stage']
    fields(stage, ('width', 'height', 'fps', 'background'), (), 'stage')
    if (any(type(stage[k]) is not int or not 1 <= stage[k] <= 8192 for k in ('width', 'height'))
            or stage['width'] * stage['height'] > 32_000_000 or not number(stage['fps'], 1, 240)):
        raise ValueError('Animate stage dimensions or frame rate exceed their budget')
    fields(stage['background'], ('r', 'g', 'b', 'a'), (), 'stage background')
    if not all(number(v, 0, 1) for v in stage['background'].values()):
        raise ValueError('Animate stage background would be repaired by the native engine')
    fps = struct.unpack('<f', struct.pack('<f', stage['fps']))[0]
    scenes = sequence(document['scenes'], MAX_SCENES, 'scenes')
    if not scenes:
        raise ValueError('Animate document must contain a scene')
    symbols = sequence(document['library'], MAX_SYMBOLS, 'symbols')
    ids = {}; assets = {'symbol': {}, 'bitmap': {}, 'sound': {}}
    counts = {'layers': 0, 'keyframes': 0, 'elements': 0}
    records = {}; path_slots = {}

    def register(value, kind, *, repeated=False):
        value = identity(value)
        if value in ids and not (repeated and ids[value] == kind):
            raise ValueError('Animate identities collide or repeat outside their native scope')
        ids[value] = kind
        return value

    for kind, rows in [('symbol', symbols), ('bitmap', document.get('bitmaps', [])),
                       ('sound', document.get('sounds', []))]:
        sequence(rows, MAX_SYMBOLS if kind == 'symbol' else MAX_MEDIA, kind + ' library')
        for item in rows:
            if not isinstance(item, dict) or 'id' not in item:
                raise ValueError('Animate library item has no native identity')
            assets[kind][register(item['id'], kind)] = item

    def reference(value, kind):
        if identity(value) not in assets[kind]:
            raise ValueError('Animate ' + kind + ' reference is missing')

    def timeline(value, owner):
        fields(value, ('layers',), (), 'timeline')
        layers = sequence(value['layers'], MAX_LAYERS, 'layers')
        counts['layers'] += len(layers)
        if counts['layers'] > MAX_LAYERS:
            raise ValueError('Animate document exceeds its layer budget')
        parents = {}; by_id = {}; peak_inputs = []; dependencies = set(); length = 1
        for index, layer in enumerate(layers):
            fields(layer, ('id', 'name', 'keyframes'),
                   ('kind', 'parent', 'visible', 'locked', 'outline', 'color', 'depth',
                    'volume', 'muted', 'armature'), 'layer')
            lid = register(layer['id'], 'layer'); label(layer['name'])
            kind = layer.get('kind', 'Normal')
            if kind not in ('Normal', 'Guide', 'Mask', 'Folder', 'Camera', 'Armature'):
                raise ValueError('Animate layer kind is invalid')
            for key in ('visible', 'locked', 'outline', 'muted'):
                if key in layer and type(layer[key]) is not bool:
                    raise ValueError('Animate layer flags must be booleans')
            parent = layer.get('parent')
            if kind == 'Camera' and (owner[0] != 'scene' or index != 0 or parent is not None):
                raise ValueError('Animate camera placement would be repaired by the native engine')
            if parent is not None:
                identity(parent)
                if parent not in by_id:
                    raise ValueError('Animate layer parent must precede its child in the same timeline')
                above = layers[index - 1]; parent_kind = by_id[parent].get('kind', 'Normal')
                if parent_kind == 'Folder':
                    holds = (above['id'] == parent or parent in parents[above['id']]) and len(parents[parent]) + 1 < 16
                elif parent_kind in ('Mask', 'Guide'):
                    holds = kind == 'Normal' and (above['id'] == parent or above.get('parent') == parent)
                else:
                    holds = False
                if not holds:
                    raise ValueError('Animate layer parent link would be repaired by the native engine')
            parents[lid] = (() if parent is None else (parent,) + parents[parent])
            if len(parents[lid]) > 16:
                raise ValueError('Animate layer nesting exceeds its budget')
            by_id[lid] = layer
            keys = sequence(layer['keyframes'], MAX_KEYS, 'keyframes')
            counts['keyframes'] += len(keys)
            if counts['keyframes'] > MAX_KEYS:
                raise ValueError('Animate document exceeds its keyframe budget')
            last_end = 0; layer_inputs = []; layer_elements = set()
            for ki, key in enumerate(keys):
                fields(key, ('start', 'duration'),
                       ('elements', 'tween', 'motion', 'hints', 'label', 'sound', 'script', 'pose'), 'keyframe')
                start, duration = key['start'], key['duration']
                if (type(start) is not int or type(duration) is not int or start < last_end
                        or duration < 1 or start + duration > MAX_FRAMES):
                    raise ValueError('Animate keyframes overlap, are unsorted or exceed their frame budget')
                last_end = start + duration; length = max(length, last_end)
                elements = sequence(key.get('elements', []), MAX_ELEMENTS, 'elements')
                counts['elements'] += len(elements)
                if counts['elements'] > MAX_ELEMENTS:
                    raise ValueError('Animate document exceeds its stored element budget')
                seen = set(); inputs = []
                for ei, element in enumerate(elements):
                    fields(element, ('id', 'kind'), ('name', 'transform', 'color'), 'element')
                    eid = register(element['id'], 'element', repeated=True)
                    if eid in seen:
                        raise ValueError('Animate keyframe repeats an element identity')
                    seen.add(eid); layer_elements.add(eid)
                    body = element['kind']; target = None
                    if body != 'Camera':
                        if not isinstance(body, dict) or len(body) != 1 or next(iter(body)) not in ('Shape', 'Text', 'Symbol'):
                            raise ValueError('Animate element kind is invalid')
                        tag = next(iter(body)); body = body[tag]
                        if not isinstance(body, dict):
                            raise ValueError('Animate element content must be an object')
                        if tag == 'Symbol':
                            target = body.get('symbol'); reference(target, 'symbol'); dependencies.add(target)
                        else:
                            field = 'path' if tag == 'Shape' else 'outline'
                            path_slots[(owner, lid, ki, ei)] = paths.resolve(body.get(field))
                            paint = body.get('fill') if tag == 'Shape' else None
                            if isinstance(paint, dict) and 'Bitmap' in paint:
                                bitmap = paint['Bitmap']
                                if not isinstance(bitmap, dict):
                                    raise ValueError('Animate bitmap paint must be an object')
                                reference(bitmap.get('bitmap'), 'bitmap')
                    inputs.append(target)
                motion = key.get('motion')
                if motion is not None:
                    if not isinstance(motion, dict) or key.get('tween') is not None:
                        raise ValueError('Animate motion and classic tweens cannot occupy the same span')
                    if identity(motion.get('target')) not in seen:
                        raise ValueError('Animate motion target is missing from its keyframe')
                sound = key.get('sound')
                if sound is not None:
                    if not isinstance(sound, dict):
                        raise ValueError('Animate frame sound must be an object')
                    reference(sound.get('sound'), 'sound')
                layer_inputs.append(inputs)
            armature = layer.get('armature')
            if armature is not None:
                if not isinstance(armature, dict):
                    raise ValueError('Animate armature must be an object')
                for bone in sequence(armature.get('bones'), 256, 'bones'):
                    if not isinstance(bone, dict):
                        raise ValueError('Animate bone must be an object')
                    register(bone.get('id'), 'bone')
                    if any(identity(bone.get(k)) not in layer_elements for k in ('parent', 'child')):
                        raise ValueError('Animate bone references a missing layer element')
            peak_inputs.append(layer_inputs)
        records[owner] = {'frames': length, 'layers': peak_inputs, 'dependencies': dependencies}

    for index, scene in enumerate(scenes):
        fields(scene, ('name', 'timeline'), (), 'scene'); label(scene['name'], scene=True)
        timeline(scene['timeline'], ('scene', index))
    for symbol in symbols:
        fields(symbol, ('id', 'name', 'timeline'), ('kind', 'linkage', 'scale_grid', 'scale_grid_kept'), 'symbol')
        label(symbol['name'])
        if symbol.get('kind', 'Graphic') not in ('Graphic', 'MovieClip', 'Button'):
            raise ValueError('Animate symbol kind is invalid')
        timeline(symbol['timeline'], ('symbol', symbol['id']))

    tree = document.get('library_tree', {})
    fields(tree, (), ('folders', 'placed'), 'library tree')
    folders = {}
    for folder in sequence(tree.get('folders', []), MAX_FOLDERS, 'library folders'):
        fields(folder, ('id', 'name'), ('parent',), 'library folder'); label(folder['name'], folder=True)
        folders[register(folder['id'], 'folder')] = folder.get('parent')
    for fid in folders:
        chain = set(); current = fid
        while current is not None:
            if identity(current) not in folders or current in chain or len(chain) >= 32:
                raise ValueError('Animate library folders are cyclic, missing or nested too deeply')
            chain.add(current); current = folders[current]
    placed = set()
    for item in sequence(tree.get('placed', []), MAX_SYMBOLS + 2 * MAX_MEDIA, 'library placements'):
        if not isinstance(item, dict) or len(item) != 2 or 'folder' not in item:
            raise ValueError('Animate library placement is invalid')
        kind = next(iter(item.keys() - {'folder'}))
        if kind not in assets:
            raise ValueError('Animate library placement kind is invalid')
        reference(item[kind], kind)
        if identity(item['folder']) not in folders or (kind, item[kind]) in placed:
            raise ValueError('Animate library placement is missing its folder or repeated')
        placed.add((kind, item[kind]))
    if identity(document['next_id']) <= max(ids, default=0):
        raise ValueError('Animate next ID would be repaired or would collide with stored content')
    paths.require_used()

    # Visit all symbols, including currently unused library items. Compute height
    # after descendants so a shared node first visited on a short path cannot
    # conceal a longer path that exceeds the native recursion limit.
    done = {}; active = set()
    for owner in records:
        pending = [(owner, False)]
        while pending:
            node, leave = pending.pop()
            if node in done:
                continue
            children = [('symbol', sid) for sid in records[node]['dependencies']]
            if not leave:
                if node in active:
                    raise ValueError('Animate symbols contain recursive dependencies')
                active.add(node); pending.append((node, True))
                pending.extend((child, False) for child in children)
                continue
            height = max((done[child]['depth'] for child in children), default=0) + (node[0] == 'symbol')
            if height > MAX_SYMBOL_DEPTH:
                raise ValueError('Animate symbols exceed the native expansion depth')
            expanded = sum(max((sum(1 + (done[('symbol', target)]['elements'] if target is not None else 0)
                                    for target in key) for key in layer), default=0)
                           for layer in records[node]['layers'])
            if expanded > MAX_EXPANDED_ELEMENTS:
                raise ValueError('Animate symbols exceed the expanded element budget')
            done[node] = {'depth': height, 'elements': expanded}; active.remove(node)
    lengths = [records[('scene', index)]['frames'] for index in range(len(scenes))]
    frames = sum(lengths)
    if frames > MAX_FRAMES:
        raise ValueError('Animate movie exceeds its total frame budget')
    seconds = Fraction(frames) / Fraction(fps)
    return {'frames': frames, 'scene_frames': lengths, 'fps': fps,
            'duration': {'numerator': seconds.numerator, 'denominator': seconds.denominator},
            'counts': counts, 'expansion': done, 'path_slots': path_slots,
            'symbols': assets['symbol'], 'bitmaps': assets['bitmap'], 'sounds': assets['sound']}
