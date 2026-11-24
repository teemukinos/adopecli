"""Bounded native motion tracks, canonical motion paths, armatures and poses.

This is one part of Animate admission. It does not qualify media, actions,
shaping or composed rendering costs, and does not register a runtime operation.
"""
import math

from .animate_format import native_path, MAX_TOTAL_COMMANDS
from .animate_graph import fields, sequence, identity, MAX_FRAMES
from .animate_properties import affine, boolean, easing, f32, point, scalar

PROPERTIES = ('x', 'y', 'scale_x', 'scale_y', 'rotation', 'skew', 'alpha', 'brightness',
              'tint', 'tint_red', 'tint_green', 'tint_blue', 'red_multiplier',
              'green_multiplier', 'blue_multiplier', 'alpha_multiplier', 'red_offset',
              'green_offset', 'blue_offset', 'alpha_offset')
MAX_TRACK_KEYS = 32768
MAX_MOTION_SEGMENTS = 4096
TAU = f32(math.tau)
MAX_ANGLE = f32(64 * TAU)


def frame(value):
    if type(value) is not int or not 0 <= value <= MAX_FRAMES:
        raise ValueError('Animate motion frame is outside its integer budget')
    return value


def native_range(value, low, high, name):
    # Native JSON uses shortest round-trip decimals. Compare the parsed f32,
    # not its slightly different decimal spelling, against native constants.
    value = scalar(value, -1_000_000, 1_000_000, name)
    if not low <= value <= high:
        raise ValueError('Animate ' + name + ' would be clamped')
    return value


def _distance(a, b):
    x, y = f32(a[0] - b[0]), f32(a[1] - b[1])
    return f32(math.sqrt(f32(f32(x*x) + f32(y*y))))


def _has_native_walk(commands):
    """Follow the native f32 sampling rule until positive walk length is proven.

    Coordinates and segment counts are already bounded, so the remaining
    nonnegative distances cannot overflow f32. Degenerate paths are checked in
    full. This proves only that native motion_path will retain the path.
    """
    current = commands[0][1]; distance = 0.0
    for _, coordinates in commands[1:]:
        controls = [current, coordinates[:2], coordinates[2:4], coordinates[4:]]
        poly = f32(f32(_distance(controls[0], controls[1]) + _distance(controls[1], controls[2]))
                   + _distance(controls[2], controls[3]))
        count = max(8, min(256, math.ceil(f32(poly / 2))))
        previous = current
        for j in range(1, count + 1):
            t = f32(j / count); u = f32(1 - t)
            weights = [f32(f32(u*u)*u), f32(f32(f32(3*u)*u)*t),
                       f32(f32(f32(3*u)*t)*t), f32(f32(t*t)*t)]
            sample = []
            for axis in range(2):
                terms = [f32(p[axis]*w) for p, w in zip(controls, weights)]
                sample.append(f32(f32(f32(terms[0]+terms[1])+terms[2])+terms[3]))
            distance = f32(distance + _distance(previous, sample)); previous = sample
            if distance > f32(.001):
                return True
        current = controls[3]
    return False


def motion(value, elements, budget):
    fields(value, ('target',), ('tracks', 'path', 'orient', 'pins'), 'motion tween')
    if identity(value['target']) not in elements:
        raise ValueError('Animate motion target would fall back to a different element')
    boolean(value.get('orient', False), 'motion orientation')
    tracks = sequence(value.get('tracks', []), 20, 'motion tracks')
    last_property = -1; positions = []
    for track in tracks:
        fields(track, ('property', 'keys'), (), 'motion track')
        name = track['property']
        if not isinstance(name, str) or name not in PROPERTIES or PROPERTIES.index(name) <= last_property:
            raise ValueError('Animate motion tracks would be reordered or deduplicated')
        last_property = PROPERTIES.index(name)
        keys = sequence(track['keys'], 10000, 'property keys')
        if not keys:
            raise ValueError('Animate empty motion track would be discarded')
        budget['keys'] += len(keys)
        if budget['keys'] > MAX_TRACK_KEYS:
            raise ValueError('Animate document exceeds its property-key budget')
        if name in ('x', 'y', 'scale_x', 'scale_y'):
            low, high = -1_000_000, 1_000_000
        elif name == 'rotation':
            low, high = -100000, 100000
        elif name == 'skew':
            low, high = -89, 89
        elif name in ('alpha', 'tint'):
            low, high = 0, 100
        elif name in ('tint_red', 'tint_green', 'tint_blue'):
            low, high = 0, 255
        elif name.endswith('_offset'):
            low, high = -255, 255
        else:
            low, high = -100, 100
        previous = -1
        for key in keys:
            fields(key, ('frame', 'value'), ('ease',), 'property key')
            at = frame(key['frame'])
            if at <= previous:
                raise ValueError('Animate property keys would be reordered or deduplicated')
            previous = at; scalar(key['value'], low, high, 'motion ' + name)
            easing(key.get('ease', 'Linear'))
            if name in ('x', 'y'):
                positions.append(at)
    path = value.get('path'); decoded = None
    if path is not None:
        decoded = native_path(path)
        commands = decoded.commands
        if (not 2 <= len(commands) <= 1001 or commands[0][0] != 'M'
                or any(command != 'C' for command, _ in commands[1:])):
            raise ValueError('Animate motion path would be converted, truncated or discarded')
        budget['segments'] += len(commands)-1; budget['commands'] += len(commands)
        if budget['segments'] > MAX_MOTION_SEGMENTS or budget['commands'] > MAX_TOTAL_COMMANDS:
            raise ValueError('Animate document exceeds its motion geometry budget')
        if not _has_native_walk(commands):
            raise ValueError('Animate motion path has no retained native walk')
    previous_frame = previous_anchor = -1
    for pin in sequence(value.get('pins', []), 1000, 'motion pins'):
        fields(pin, ('frame', 'anchor'), (), 'motion pin')
        at, anchor = frame(pin['frame']), frame(pin['anchor'])
        if (decoded is None or not positions or not min(positions) < at < max(positions)
                or not 0 < anchor < len(decoded.commands)-1
                or at <= previous_frame or anchor <= previous_anchor):
            raise ValueError('Animate motion pin would be ignored or removed')
        previous_frame, previous_anchor = at, anchor
    return decoded


def armature(value, elements, budget):
    fields(value, (), ('bones',), 'armature')
    bones = sequence(value.get('bones', []), 256, 'armature bones')
    budget['bones'] += len(bones)
    if budget['bones'] > 4096:
        raise ValueError('Animate document exceeds its bone budget')
    ids = set(); children = set()
    for bone in bones:
        fields(bone, ('id', 'parent', 'child', 'head', 'tail', 'rest'), ('name', 'limits', 'pinned'), 'bone')
        bid, parent, child = (identity(bone[k]) for k in ('id', 'parent', 'child'))
        if bid in ids or child in children or parent == child or parent not in elements or child not in elements:
            raise ValueError('Animate bone identity or target would be removed')
        ids.add(bid); children.add(child)
        name = bone.get('name', '')
        if not isinstance(name, str) or len(name.encode('utf-8')) > 256:
            raise ValueError('Animate bone name would be truncated')
        point(bone['head']); point(bone['tail']); matrix = affine(bone['rest'])
        determinant = f32(f32(matrix[0]*matrix[3])-f32(matrix[1]*matrix[2]))
        if abs(determinant) < f32(1e-12):
            raise ValueError('Animate bone rest transform cannot be inverted')
        boolean(bone.get('pinned', False), 'bone pin')
        limits = bone.get('limits')
        if limits is not None:
            fields(limits, ('min', 'max'), (), 'bone limits')
            lo = native_range(limits['min'], -TAU, TAU, 'bone limit')
            hi = native_range(limits['max'], -TAU, TAU, 'bone limit')
            if lo > hi:
                raise ValueError('Animate bone limits would be reordered')
    # Native sanitize groups ready bones by breadth, preserving source order
    # within each group. Merely placing every parent before its child is weaker.
    placed = {b['parent'] for b in bones} - children
    remaining = list(bones); ordered = []
    while remaining:
        ready = [b for b in remaining if b['parent'] in placed]
        if not ready:
            raise ValueError('Animate armature contains a cycle')
        remaining = [b for b in remaining if b['parent'] not in placed]
        ordered.extend(b['id'] for b in ready); placed.update(b['child'] for b in ready)
    if ordered != [b['id'] for b in bones]:
        raise ValueError('Animate bones would be reordered by native repair')
    return ids


def inspect_animation(document, graph):
    unique_paths = {id(path): path for path in graph['path_slots'].values()}
    budget = {'keys': 0, 'segments': 0, 'commands': sum(len(p.commands) for p in unique_paths.values()), 'bones': 0, 'poses': 0}
    motions = {}; dormant = 0; outside = 0
    timelines = [(('scene', i), s['timeline']) for i, s in enumerate(document['scenes'])]
    timelines += [(('symbol', s['id']), s['timeline']) for s in document['library']]
    for owner, timeline in timelines:
        for layer in timeline['layers']:
            elements = {e['id'] for k in layer['keyframes'] for e in k.get('elements', [])}
            bones = set(); active = layer.get('kind', 'Normal') == 'Armature'
            if layer.get('armature') is not None:
                if not active:
                    raise ValueError('Animate armature would be removed from this layer')
                bones = armature(layer['armature'], elements, budget)
            for index, key in enumerate(layer['keyframes']):
                if key.get('motion') is not None:
                    if key.get('tween') is not None:
                        raise ValueError('Animate motion would replace a classic tween')
                    motions[(owner, layer['id'], index)] = motion(key['motion'], {e['id'] for e in key.get('elements', [])}, budget)
                    outside += sum(k['frame'] >= key['duration'] for t in key['motion'].get('tracks', []) for k in t['keys'])
                seen = set()
                for pose in sequence(key.get('pose', []), 256, 'joint angles'):
                    fields(pose, ('bone', 'angle'), (), 'joint angle'); bid = identity(pose['bone'])
                    if bid in seen or (active and bid not in bones):
                        raise ValueError('Animate pose repeats or targets a missing active bone')
                    seen.add(bid); native_range(pose['angle'], -MAX_ANGLE, MAX_ANGLE, 'joint angle')
                    budget['poses'] += 1
                    if budget['poses'] > 32768:
                        raise ValueError('Animate document exceeds its pose budget')
                    if not active:
                        dormant += 1
    return {'budget': budget, 'motion_paths': motions, 'inactive_pose_angles': dormant,
            'property_keys_outside_span': outside, 'render_budget_verified': False}
