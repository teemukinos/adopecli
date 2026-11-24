"""Bounded static visual properties for native Animate documents.

Use after format and graph admission. These checks do not establish text shaping,
composed render costs, animated property curves, media validity or publication
fidelity. Input values are inspected, never repaired or rewritten.
"""
import math
import struct

from .animate_format import number
from .animate_graph import fields, identity, label, sequence, MAX_FRAMES

WHITE = {'r': 1, 'g': 1, 'b': 1, 'a': 1}
BLACK = {'r': 0, 'g': 0, 'b': 0, 'a': 1}
IDENTITY = {'m': [1, 0, 0, 1, 0, 0]}
MAX_TEXT_BYTES = 1 << 20


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def scalar(value, low, high, name):
    if not number(value, low, high):
        raise ValueError('Animate ' + name + ' is outside its finite numeric range')
    return f32(value)


def boolean(value, name):
    if type(value) is not bool:
        raise ValueError('Animate ' + name + ' must be a boolean')


def choice(value, choices, name):
    if not isinstance(value, str) or value not in choices:
        raise ValueError('Animate ' + name + ' is invalid')


def vector(value, count, low, high, name):
    if not isinstance(value, list) or len(value) != count:
        raise ValueError('Animate ' + name + ' has the wrong coordinate count')
    return [scalar(v, low, high, name) for v in value]


def rgba(value):
    fields(value, ('r', 'g', 'b', 'a'), (), 'color')
    return tuple(scalar(value[k], 0, 1, 'color channel') for k in ('r', 'g', 'b', 'a'))


def point(value):
    fields(value, ('x', 'y'), (), 'point')
    return [scalar(value[k], -1_000_000, 1_000_000, 'point coordinate') for k in ('x', 'y')]


def affine(value):
    fields(value, ('m',), (), 'transform')
    return vector(value['m'], 6, -1_000_000, 1_000_000, 'transform')


def stops(value, limit=64, *, rest=None):
    sequence(value, limit, 'gradient stops')
    if not value:
        raise ValueError('Animate gradient requires at least one stop')
    positions = []; colors = []
    for stop in value:
        fields(stop, ('offset', 'color'), (), 'gradient stop')
        positions.append(scalar(stop['offset'], 0, 1, 'gradient stop position'))
        colors.append(rgba(stop['color']))
    if positions != sorted(positions):
        raise ValueError('Animate gradient stops must be ordered')
    if rest is not None:
        near = [i for i, p in enumerate(positions) if abs(f32(p - rest)) < f32(.001)]
        if len(near) != 1 or positions[near[0]] != rest or colors[near[0]][3] != 0:
            raise ValueError('Animate gradient filter would repair its transparent rest stop')


def paint(value, bitmaps):
    if value is None:
        return
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError('Animate paint must contain one native paint kind')
    kind = next(iter(value)); body = value[kind]
    if kind == 'Solid':
        rgba(body)
    elif kind == 'Linear':
        fields(body, ('start', 'end', 'stops'), (), 'linear paint')
        point(body['start']); point(body['end']); stops(body['stops'])
    elif kind == 'Radial':
        fields(body, ('center', 'radius', 'stops'), (), 'radial paint')
        point(body['center']); scalar(body['radius'], .001, 1_000_000, 'gradient radius'); stops(body['stops'])
    elif kind == 'Bitmap':
        fields(body, ('bitmap',), ('repeat', 'matrix'), 'bitmap paint')
        if identity(body['bitmap']) not in bitmaps:
            raise ValueError('Animate bitmap paint references missing artwork')
        boolean(body.get('repeat', False), 'bitmap repeat')
        matrix = affine(body.get('matrix', IDENTITY))
        determinant = f32(f32(matrix[0] * matrix[3]) - f32(matrix[1] * matrix[2]))
        if abs(determinant) < f32(1e-12):
            raise ValueError('Animate bitmap paint transform cannot be inverted')
    else:
        raise ValueError('Animate paint kind is invalid')


def stroke(value):
    """Validate strokes and return their native local-space reach."""
    if value is None:
        return 0.0
    fields(value, ('color', 'width'), ('profile', 'style'), 'stroke')
    rgba(value['color']); width = scalar(value['width'], 0, 4096, 'stroke width')
    factor = 1.0; profile = value.get('profile')
    if profile is not None:
        sequence(profile, 64, 'stroke width points')
        prior = None; factors = []
        for p in profile:
            fields(p, ('t', 'left', 'right'), (), 'stroke width point')
            t = scalar(p['t'], 0, 1, 'stroke width position')
            if prior is not None and f32(t - prior) < f32(.001):
                raise ValueError('Animate stroke width points would be reordered or merged')
            prior = t
            factors.extend(scalar(p[k], 0, 16, 'stroke width factor') for k in ('left', 'right'))
        if not factors or all(abs(f32(v - 1)) < f32(.0001) for v in factors):
            raise ValueError('Animate uniform width profile would be discarded')
        factor = max(factors)
    style = value.get('style', {})
    fields(style, (), ('cap', 'join', 'miter_limit', 'dash'), 'stroke style')
    cap = style.get('cap', 'round'); join = style.get('join', 'round')
    choice(cap, ('butt', 'round', 'square'), 'stroke cap')
    choice(join, ('miter', 'round', 'bevel'), 'stroke join')
    miter = scalar(style.get('miter_limit', 3), 1, 100, 'stroke miter limit')
    dash = style.get('dash')
    if dash is not None:
        if not isinstance(dash, dict):
            raise ValueError('Animate stroke dash must be an object')
        if dash.get('kind') == 'dashed':
            fields(dash, ('kind', 'lengths'), ('offset',), 'dash pattern')
            lengths = sequence(dash['lengths'], 16, 'dash lengths')
            if not lengths or len(lengths) % 2:
                raise ValueError('Animate dash pattern must have an even nonzero length')
            lengths = [scalar(v, 0, 10000, 'dash length') for v in lengths]
            period = 0.0
            for v in lengths:
                period = f32(period + v)
            offset = scalar(dash.get('offset', 0), 0, 160000, 'dash offset')
            if period <= f32(.001) or sum(lengths[1::2]) <= 0 or offset >= period:
                raise ValueError('Animate dash pattern would become solid or wrap its offset')
        elif dash.get('kind') == 'dotted':
            fields(dash, ('kind', 'spacing'), (), 'dot pattern')
            scalar(dash['spacing'], 0, 10000, 'dot spacing'); cap = 'round'
        else:
            raise ValueError('Animate stroke dash kind is invalid')
    reach = max(miter if join == 'miter' else 1, f32(math.sqrt(2)) if cap == 'square' else 1)
    return f32(f32(f32(width * .5) * factor) * reach)


def color_effect(value):
    fields(value, (), ('alpha', 'tint', 'tint_amount', 'style', 'brightness', 'multiply', 'offset'), 'color effect')
    style = value.get('style')
    if style is not None:
        choice(style, ('none', 'brightness', 'tint', 'advanced', 'alpha'), 'color effect style')
    alpha = scalar(value.get('alpha', 1), -1 if style == 'advanced' else 0, 1, 'effect alpha')
    tint = value.get('tint', WHITE); rgba(tint)
    amount = scalar(value.get('tint_amount', 0), 0, 1, 'tint amount')
    if (('brightness' in value and style != 'brightness')
            or (('multiply' in value or 'offset' in value) and style != 'advanced')):
        raise ValueError('Animate color effect contains fields ignored by its selected style')
    if style == 'brightness':
        b = scalar(value.get('brightness'), -1, 1, 'brightness')
        if alpha != 1 or tint != (WHITE if b >= 0 else BLACK) or amount != abs(b):
            raise ValueError('Animate brightness legacy fields disagree with its selected style')
    elif style == 'advanced':
        mul = vector(value.get('multiply'), 4, -1, 1, 'advanced multipliers')
        vector(value.get('offset'), 4, -1, 1, 'advanced offsets')
        if alpha != mul[3] or tint != WHITE or amount != 0:
            raise ValueError('Animate advanced legacy fields disagree with its selected style')
    elif style == 'tint':
        if alpha != 1 or tint['a'] != 1:
            raise ValueError('Animate tint effect would discard its alpha fields')
    elif style in ('alpha', 'none'):
        if tint != WHITE or amount != 0 or (style == 'none' and alpha != 1):
            raise ValueError('Animate color effect would discard inactive legacy values')
    elif (amount == 0 and tint != WHITE) or (amount != 0 and tint['a'] != 1):
        raise ValueError('Animate legacy color effect would discard its tint values')


def easing(value):
    if isinstance(value, str):
        choice(value, ('Linear', 'QuadIn', 'QuadOut', 'QuadInOut', 'CubicIn', 'CubicOut', 'CubicInOut'), 'easing')
    elif isinstance(value, dict) and set(value) == {'Classic'}:
        scalar(value['Classic'], -100, 100, 'classic ease')
    elif isinstance(value, dict) and set(value) == {'CubicBezier'}:
        v = vector(value['CubicBezier'], 4, -16, 16, 'cubic easing')
        if not 0 <= v[0] <= 1 or not 0 <= v[2] <= 1:
            raise ValueError('Animate cubic easing horizontal controls would be clamped')
    else:
        raise ValueError('Animate easing kind is invalid')


def filters(value):
    sequence(value, 8, 'instance filters')
    blur = {'blur_x', 'blur_y', 'quality'}
    edge = blur | {'strength', 'angle', 'distance', 'side', 'knockout'}
    options = {'blur': blur, 'drop_shadow': blur | {'strength', 'angle', 'distance', 'color', 'inner', 'knockout', 'hide_object'},
               'glow': blur | {'strength', 'color', 'inner', 'knockout'},
               'bevel': edge | {'shadow_color', 'highlight_color'},
               'gradient_glow': edge | {'stops'}, 'gradient_bevel': edge | {'stops'},
               'adjust_color': {'brightness', 'contrast', 'saturation', 'hue'}}
    ranges = {'blur_x': (0, 255), 'blur_y': (0, 255), 'strength': (0, 10), 'distance': (-1000, 1000),
              'angle': (0, 360), 'brightness': (-100, 100), 'contrast': (-100, 100),
              'saturation': (-100, 100), 'hue': (-180, 180)}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get('type'), str) or item['type'] not in options:
            raise ValueError('Animate filter kind is invalid')
        kind = item['type']; fields(item, ('type',), options[kind], 'filter')
        for name, val in item.items():
            if name in ranges:
                v = scalar(val, *ranges[name], 'filter ' + name)
                if name == 'angle' and v >= 360:
                    raise ValueError('Animate filter angle would wrap')
            elif name == 'quality':
                if type(val) is not int or not 1 <= val <= 3:
                    raise ValueError('Animate filter quality is outside its pass budget')
            elif name in ('inner', 'knockout', 'hide_object'):
                boolean(val, 'filter ' + name)
            elif name in ('color', 'shadow_color', 'highlight_color'):
                rgba(val)
            elif name == 'side':
                choice(val, ('inner', 'outer', 'full'), 'filter side')
            elif name == 'stops':
                stops(val, 15, rest=0 if kind == 'gradient_glow' else .5)


def inspect_static(document, graph):
    """Validate static visual fields; return typography requests and stroke reach."""
    fonts = set(); text_bytes = 0; reaches = {}; filter_count = 0
    timelines = [(('scene', i), s['timeline']) for i, s in enumerate(document['scenes'])]
    timelines += [(('symbol', s['id']), s['timeline']) for s in document['library']]
    for owner, timeline in timelines:
        for layer in timeline['layers']:
            if 'color' in layer:
                rgba(layer['color'])
            scalar(layer.get('depth', 0), -500, 10000, 'layer depth')
            scalar(layer.get('volume', 1), 0, 1, 'layer volume')
            if layer.get('armature') is not None and layer.get('kind', 'Normal') != 'Armature':
                raise ValueError('Animate armature would be removed from a non-armature layer')
            for ki, key in enumerate(layer['keyframes']):
                label(key.get('label', ''))
                tween = key.get('tween')
                if tween is not None:
                    fields(tween, (), ('easing', 'kind', 'orient'), 'tween')
                    easing(tween.get('easing', 'Linear'))
                    choice(tween.get('kind', 'Classic'), ('Classic', 'Shape'), 'tween kind')
                    boolean(tween.get('orient', False), 'tween orientation')
                for hint in sequence(key.get('hints', []), 26, 'shape hints'):
                    fields(hint, ('start', 'end'), (), 'shape hint'); point(hint['start']); point(hint['end'])
                for ei, element in enumerate(key.get('elements', [])):
                    label(element.get('name', '')); affine(element.get('transform', IDENTITY))
                    color_effect(element.get('color', {}))
                    kind = element['kind']
                    if kind == 'Camera':
                        continue
                    tag = next(iter(kind)); body = kind[tag]
                    if tag == 'Shape':
                        fields(body, ('path',), ('fill', 'stroke', 'fill_rule', 'merge'), 'shape')
                        paint(body.get('fill'), graph['bitmaps'])
                        reaches[(owner, layer['id'], ki, ei)] = stroke(body.get('stroke'))
                        choice(body.get('fill_rule', 'NonZero'), ('NonZero', 'EvenOdd'), 'fill rule')
                        boolean(body.get('merge', False), 'shape merge')
                    elif tag == 'Text':
                        fields(body, ('text', 'font', 'size', 'color', 'outline', 'box_width', 'box_height'),
                               ('bold', 'italic', 'align', 'letter_spacing', 'line_spacing', 'width'), 'text block')
                        if not isinstance(body['text'], str) or not isinstance(body['font'], str):
                            raise ValueError('Animate text and font family must be strings')
                        text_bytes += len(body['text'].encode('utf-8'))
                        if text_bytes > MAX_TEXT_BYTES or not body['font'].strip() or len(body['font'].encode('utf-8')) > 256:
                            raise ValueError('Animate text or font name exceeds its budget')
                        for name in ('bold', 'italic'):
                            boolean(body.get(name, False), 'text ' + name)
                        scalar(body['size'], .1, 1024, 'font size'); rgba(body['color'])
                        choice(body.get('align', 'left'), ('left', 'center', 'right'), 'text alignment')
                        for name in ('letter_spacing', 'line_spacing'):
                            scalar(body.get(name, 0), -10000, 10000, name)
                        for name in ('box_width', 'box_height'):
                            scalar(body[name], 0, 1_000_000, 'text ' + name)
                        if body.get('width') is not None:
                            scalar(body['width'], .001, 1_000_000, 'text wrap width')
                        fonts.add((body['font'], body.get('bold', False), body.get('italic', False)))
                    else:
                        fields(body, ('symbol',), ('loop_mode', 'first_frame', 'blend', 'filters', 'events'), 'symbol instance')
                        choice(body.get('loop_mode', 'Loop'), ('Loop', 'PlayOnce', 'SingleFrame'), 'symbol loop mode')
                        first = body.get('first_frame', 0)
                        if type(first) is not int or not 0 <= first <= MAX_FRAMES:
                            raise ValueError('Animate symbol start frame exceeds its budget')
                        choice(body.get('blend', 'normal'), ('normal', 'layer', 'darken', 'multiply', 'lighten', 'screen',
                               'overlay', 'hardlight', 'add', 'subtract', 'difference', 'invert', 'alpha', 'erase'), 'blend mode')
                        current = body.get('filters', []); filters(current); filter_count += len(current)
                        if filter_count > 1024:
                            raise ValueError('Animate document exceeds its stored filter budget')
    for symbol in document['library']:
        for name in ('scale_grid', 'scale_grid_kept'):
            grid = symbol.get(name)
            if grid is not None:
                fields(grid, ('left', 'right', 'top', 'bottom'), (), 'nine-slice guides')
                vals = {k: scalar(v, -1_000_000, 1_000_000, 'nine-slice guide') for k, v in grid.items()}
                if vals['left'] > vals['right'] or vals['top'] > vals['bottom']:
                    raise ValueError('Animate nine-slice guides are reversed')
        if symbol.get('scale_grid') is not None and symbol.get('scale_grid_kept') is not None:
            raise ValueError('Animate inactive nine-slice guides would be discarded')
    return {'fonts': sorted(fonts), 'text_bytes': text_bytes, 'stroke_reach': reaches,
            'filters': filter_count, 'shaping_verified': False, 'render_budget_verified': False}
