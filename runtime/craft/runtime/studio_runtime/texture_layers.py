"""Pinned Texture layer/source/effect schema and conservative work admission.

Project/display/bake settings have separate contracts. Stored path paint and
linked-material values remain bounded inert metadata: this reader never grants
path replay, external alpha loading or linked-package execution authority.
"""
import math

from .texture_structure import require, integer, variant, CHANNELS

BLENDS = set('Normal Passthrough Disable Replace Multiply Divide InverseDivide Darken Lighten LinearDodge Subtract '
             'InverseSubtract Difference Exclusion SignedAddition Overlay Screen LinearBurn ColorBurn ColorDodge SoftLight '
             'HardLight VividLight LinearLight PinLight Tint Saturation Color Value NormalMapCombine NormalMapDetail NormalMapInverseDetail'.split())
PATTERNS = set('Clouds Perlin Noise Cells Grunge Scratches Checker Stripes Gradient Wood Bricks Tiles Weave Twill Leather '
               'Hammered Brushed Marble Voronoi Streaks Smudges Pores Chips'.split())
GENERATORS = set('EdgeWear Dirt ThinAreas Curvature AmbientOcclusion Position Direction'.split())
MAX_SAMPLE_WORK = 8_589_934_592
MAX_PATH_POINTS = 16_384


def fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
            'layer metadata has missing or unsupported fields')
    return value


def number(value, low=-65504, high=65504):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            'layer numeric parameter is outside its finite range')


def vector(value, size=3, low=-65504, high=65504):
    require(type(value) is list and len(value) == size, 'layer vector has the wrong dimension')
    for component in value:
        number(component, low, high)


def boolean(value):
    require(type(value) is bool, 'layer boolean parameter has the wrong type')


def text(value, maximum=4096):
    require(type(value) is str and len(value) <= maximum and '\x00' not in value, 'layer text exceeds its contract')


def choice(value, values):
    require(type(value) is str and value in values, 'layer enum parameter is unsupported')


def sequence(value, maximum):
    require(type(value) is list and len(value) <= maximum, 'layer list exceeds its budget')
    return value


def _schema(value, spec):
    fields(value, spec)
    for key, check in spec.items():
        check(value[key])


def unit(value):
    number(value, 0, 1)


def unsigned(value):
    require(integer(value, 0, 0xffffffff), 'layer seed is not a u32')


def positive(value):
    number(value, 1e-6, 65504)


def radius(value):
    number(value, 0, 8192)


def projection(value):
    specs = {
        'Uv': {'scale': lambda v: vector(v, 2), 'rotation': number, 'offset': lambda v: vector(v, 2)},
        'Triplanar': {'scale': positive, 'sharpness': positive, 'offset': vector},
        'Planar': {'scale': positive, 'axis': lambda v: require(integer(v, 0, 2), 'projection axis is invalid'), 'offset': vector},
        'Spherical': {'scale': positive},
        'Cylindrical': {'scale': positive, 'axis': lambda v: require(integer(v, 0, 2), 'projection axis is invalid')},
        'Decal': {'center': vector, 'normal': vector, 'up': vector, 'size': lambda v: vector(v, 2, 1e-6),
                  'rotation': number, 'offset': lambda v: vector(v, 2), 'depth': positive},
    }
    kind, body = variant(value, (), specs, 'projection'); _schema(body, specs[kind])
    if kind == 'Uv':
        require(all(abs(v) >= 1e-6 for v in body['scale']), 'projection scale is degenerate')
    if kind == 'Decal':
        n, u = body['normal'], body['up']
        cross = (n[1]*u[2]-n[2]*u[1], n[2]*u[0]-n[0]*u[2], n[0]*u[1]-n[1]*u[0])
        require(sum(c*c for c in cross) >= 1e-12, 'decal frame is degenerate')


FILTERS = {
    'Blur': {'radius': radius}, 'Sharpen': {'amount': number}, 'Threshold': {'level': unit},
    'Hsl': {'hue': number, 'saturation': lambda v: number(v, -1, 1), 'lightness': lambda v: number(v, -1, 1)},
    'ContrastLuminosity': {'contrast': lambda v: number(v, -1, 1), 'luminosity': lambda v: number(v, -1, 1)},
    'ColorBalance': {key: (lambda v: vector(v, 3, -1, 1)) for key in ('shadows', 'midtones', 'highlights')},
    'GradientMap': {'colors': lambda v: [vector(c) for c in sequence(v, 256)]},
    'Posterize': {'levels': lambda v: number(v, 2, 64)}, 'Clamp': {'min': number, 'max': number},
    'HistogramScan': {'position': unit, 'contrast': unit}, 'HistogramRange': {'range': unit, 'position': unit},
    'HistogramShift': {'offset': lambda v: number(v, -1, 1)},
    'Warp': {'intensity': radius, 'scale': lambda v: number(v, .01, 1000), 'seed': unsigned},
    'DirectionalBlur': {'radius': radius, 'angle': number},
    'SlopeBlur': {'radius': radius, 'scale': lambda v: number(v, .01, 1000), 'seed': unsigned},
    'HighPass': {'radius': radius}, 'EdgeDetect': {'width': radius},
    'DirectionalWarp': {'intensity': radius, 'angle': number, 'scale': lambda v: number(v, .01, 1000), 'seed': unsigned},
    'Bevel': {'width': radius}, 'Mosaic': {'size': lambda v: number(v, 1e-6, 8192)},
    'Glow': {'radius': radius, 'amount': number},
    'BakedLighting': {'azimuth': number, 'elevation': lambda v: number(v, -90, 90), 'light': number, 'ambient': number, 'occlusion': unit},
    'ReplaceColor': {'from': vector, 'to': vector, 'tolerance': unit, 'softness': unit},
}
POINT_FILTERS = ('Invert', 'Grayscale', 'NormalInvert')
NEIGHBOURHOOD = set('Blur Sharpen Warp DirectionalBlur SlopeBlur HighPass EdgeDetect DirectionalWarp Bevel Mosaic Glow'.split())


def inspect(structure):
    sample_factor = 1; anchors = anchor_reads = path_points = paths = linked = 0

    def source(value):
        nonlocal sample_factor, anchor_reads
        kind, body = variant(value, (), ('Uniform', 'Procedural', 'Image', 'Anchor'), 'fill source')
        if kind == 'Uniform':
            vector(body)
        elif kind == 'Procedural':
            fields(body, ('pattern', 'low', 'high')); vector(body['low']); vector(body['high'])
            _schema(body['pattern'], {'kind': lambda v: choice(v, PATTERNS), 'scale': lambda v: number(v, .01, 1000),
                                     'seed': unsigned, 'contrast': lambda v: number(v, 0, 1000),
                                     'balance': lambda v: number(v, -1, 1), 'invert': boolean})
            sample_factor = max(sample_factor, 256)
        elif kind == 'Image':
            fields(body, ('name',), ('normal_format',)); text(body['name'], 120)
            if 'normal_format' in body: choice(body['normal_format'], ('OpenGl', 'DirectX'))
            sample_factor = max(sample_factor, 4)
        else:
            fields(body, ('anchor', 'channel')); choice(body['channel'], CHANNELS)
            anchor_reads += 1

    def fill(value):
        nonlocal linked
        fields(value, ('sources', 'projection'), ('link',)); projection(value['projection'])
        for item in value['sources'].values(): source(item)
        link = value.get('link')
        if link is not None:
            fields(link, ('name', 'package', 'graph', 'params', 'size'), ('presets', 'inputs'))
            for key in ('name', 'package', 'graph'): text(link[key])
            require(integer(link['size'], 1, 8192), 'linked material map size is invalid')
            names = set()
            for param in sequence(link['params'], 1024):
                fields(param, ('id', 'label', 'value', 'default'), ('group', 'min', 'max', 'options'))
                for key in ('id', 'label'): text(param[key])
                require(param['id'] not in names, 'linked parameter IDs are duplicated'); names.add(param['id'])
                if 'group' in param: text(param['group'])
                for key in ('min', 'max'):
                    if key in param: number(param[key])
                require(param.get('min', 0) <= param.get('max', 1), 'linked parameter range is reversed')
                for option in sequence(param.get('options', []), 256): text(option)
            for preset in sequence(link.get('presets', []), 128):
                fields(preset, ('name', 'values')); text(preset['name'])
                require(type(preset['values']) is dict and set(preset['values']) <= names, 'linked preset references an absent parameter')
            for name in sequence(link.get('inputs', []), 256): text(name)
            linked += 1

    def effect(value, role):
        nonlocal sample_factor, anchors, paths, path_points
        fields(value, ('id', 'name', 'visible', 'kind', 'blend', 'opacity'))
        text(value['name']); boolean(value['visible']); choice(value['blend'], BLENDS); unit(value['opacity'])
        kind, body = variant(value['kind'], ('Paint', 'Anchor'),
                             ('Path', 'Fill', 'Generator', 'Levels', 'Filter', 'ColorSelection', 'Compare', 'Material'), 'effect kind')
        require(not (role == 'mask' and kind in ('Material', 'Anchor'))
                and not (role == 'content' and kind in ('Fill', 'Generator', 'ColorSelection', 'Compare')),
                'effect is in the wrong content or mask stack')
        if kind == 'Anchor': anchors += 1
        elif kind == 'Material': fill(body)
        elif kind == 'Fill':
            fields(body, ('source', 'projection')); source(body['source']); projection(body['projection'])
        elif kind == 'Levels':
            _schema(body, {key: number for key in ('in_low', 'in_high', 'gamma', 'out_low', 'out_high')})
            require(body['in_high'] > body['in_low'] and .001 <= body['gamma'] <= 1000, 'levels range or gamma is invalid')
        elif kind == 'Filter':
            name, params = variant(body, POINT_FILTERS, FILTERS, 'filter')
            if name in FILTERS: _schema(params, FILTERS[name])
            if name == 'Clamp': require(params['min'] <= params['max'], 'filter clamp range is reversed')
            if name == 'GradientMap': require(len(params['colors']) >= 2, 'gradient requires at least two colors')
            sample_factor = max(sample_factor, 256 if name in NEIGHBOURHOOD else 8)
        elif kind == 'Generator':
            fields(body, ('kind', 'level', 'softness', 'noise_amount', 'noise_scale', 'seed', 'direction', 'invert'), ('detail',))
            choice(body['kind'], GENERATORS)
            for key in ('level', 'softness', 'noise_amount'): unit(body[key])
            number(body['noise_scale'], .01, 1000); unsigned(body['seed']); vector(body['direction']); boolean(body['invert'])
            require(sum(c*c for c in body['direction']) >= 1e-12, 'generator direction is degenerate')
            if body.get('detail') is not None:
                _schema(body['detail'], {'mode': lambda v: choice(v, ('Edges', 'Cavities', 'Both', 'Raw')),
                                         'weights': lambda v: vector(v, 7, 0, 1)})
            sample_factor = max(sample_factor, 256)
        elif kind == 'ColorSelection':
            fields(body, ('colors', 'tolerance')); unit(body['tolerance'])
            for color in sequence(body['colors'], 256): vector(color, 3, 0, 1)
        elif kind == 'Compare':
            _schema(body, {'op': lambda v: choice(v, ('LesserThan', 'WithinTolerance', 'GreaterThan')), 'value': number, 'tolerance': unit})
        elif kind == 'Path':
            for path in sequence(body, 4096):
                fields(path, ('points', 'uv', 'closed', 'fill', 'viewport', 'paint'))
                points = sequence(path['points'], 4096); path_points += len(points); paths += 1
                require(path_points <= MAX_PATH_POINTS, 'aggregate path points exceed their budget')
                for point in points: vector(point)
                for key in ('uv', 'closed', 'fill'): boolean(path[key])
                vector(path['viewport'], 2, 1, 16384)
                require(type(path['paint']) is dict, 'stored path paint must be an inert JSON object')

    for layer in structure['layers'].values():
        fields(layer, ('id', 'name', 'visible', 'kind', 'channels'),
               ('mask', 'content_effects', 'color_tag', 'height_mask', 'geometry_mask'))
        text(layer['name']); boolean(layer['visible'])
        for blend in layer['channels'].values(): _schema(blend, {'mode': lambda v: choice(v, BLENDS), 'opacity': unit})
        if layer.get('color_tag') is not None: require(integer(layer['color_tag'], 0, 255), 'layer color tag is invalid')
        if 'height_mask' in layer:
            value = fields(layer['height_mask'], (), ('enabled', 'contrast', 'offset'))
            if 'enabled' in value: boolean(value['enabled'])
            if 'contrast' in value: number(value['contrast'], 0, 1000)
            if 'offset' in value: number(value['offset'], -1, 1)
        if layer.get('geometry_mask') is not None:
            for part in sequence(layer['geometry_mask'], 4096): text(part)
        kind, body = variant(layer['kind'], ('Paint',), ('Fill', 'Group', 'Instance'), 'layer kind')
        if kind == 'Fill': fill(body)
        elif kind == 'Group': fields(body, ('children', 'collapsed')); boolean(body['collapsed'])
        elif kind == 'Instance': fields(body, ('source',))
        for item in layer.get('content_effects', []): effect(item, 'content')
        if layer.get('mask') is not None:
            mask = fields(layer['mask'], ('enabled', 'background', 'effects'))
            boolean(mask['enabled']); choice(mask['background'], ('White', 'Black'))
            for item in mask['effects']: effect(item, 'mask')
    # Use the maximum source/filter factor for every expanded node and charge
    # every expanded node as a possible prefix reader when any source reads an
    # anchor. Counting only stored readers would undercharge repeated instances.
    # Anchor cuts may require additional partial evaluations. This intentionally
    # overestimates mixed stacks; it is not a time or peak-memory prediction.
    prefix_factor = (anchors + 1) * (1 + max(a['expanded_nodes'] for a in structure['atlases']) if anchor_reads else 1)
    work = structure['budgets']['render_work'] * sample_factor * prefix_factor
    require(work <= MAX_SAMPLE_WORK, 'layer sampling work exceeds its development budget')
    return {'sample_factor': sample_factor, 'sample_work': work, 'anchors': anchors, 'anchor_reads': anchor_reads,
            'anchor_prefix_factor': prefix_factor,
            'stored_paths': paths, 'path_points': path_points, 'linked_materials': linked,
            'path_replay_authorized': False, 'linked_cooking_authorized': False,
            'project_admission_complete': False}
