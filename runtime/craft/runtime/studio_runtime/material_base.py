"""Predict admitted Material base parameters and inherited CPU image dimensions.

Dynamic values must come from a separately qualified function evaluator; native
output is not trusted as a pre-execution bound. This module does not authorize
execution, resolve image-instance call trees or estimate total raster work.
"""
import copy
import json
import math

from .material_container import require
from .material_graphs import BASE_TYPES, base_parameters
from .material_node_catalog import DEFINITIONS
from . import material_procedural as proc

MODES = {'0': 'absolute', '1': 'relativeToInput', '2': 'relativeToParent'}
FORMATS = ('u8', 'u16', 'f16', 'f32')
FIELDS = {'outputsize': 'size', 'format': 'format', 'randomseed': 'seed',
          'pixelsize': 'pixelSize', 'pixelratio': 'pixelRatio', 'tiling': 'tiling'}
GENERATORS = {'bitmap', 'svg', 'uniform', 'input_color', 'input_grayscale', 'text', 'fx_map'}
PRIMARY_INPUTS = {'blend': 'background'}
MIN_POSITIVE = 2.0 ** -126
UINT32 = 2 ** 32


def model(parameters):
    """Predict the native base record, retaining dynamic bodies separately."""
    base_parameters(parameters)
    result = {'sizeMode': 'relativeToInput', 'size': [0, 0], 'format': 'inherit', 'formatMode': 'absolute',
              'seed': 0, 'seedMode': 'relativeToInput', 'pixelSize': [1., 1.], 'pixelSizeMode': 'relativeToInput',
              'tiling': [True, True], 'tilingMode': 'relativeToInput', 'pixelRatio': 0, 'pixelRatioMode': 'relativeToInput'}
    functions = {}
    for name, record in parameters.items():
        if name not in FIELDS: continue
        field = FIELDS[name]; value = record['value']
        if value['t'] == 'function': functions[name] = value['v']
        else:
            data = copy.deepcopy(value['v'])
            if name == 'tiling': data = [bool(data & 1), bool(data & 2)]
            if name == 'format': data = FORMATS[data]
            result[field] = data
        # Setting inheritance converts the Inherit format sentinel to U16,
        # including a dynamic format with no serialized literal.
        if name == 'format' and result['format'] == 'inherit': result['format'] = 'u16'
        result[field + 'Mode'] = MODES[record['mode']]
    return {'literal': result, 'functions': functions, 'engine_admission_complete': False}


def inherit(mode, absolute, input_, parent):
    require(mode in MODES.values(), 'unknown base inheritance mode')
    if mode == 'absolute': return copy.deepcopy(absolute)
    return copy.deepcopy(input_ if mode == 'relativeToInput' and input_ is not None else parent)


def graph_parent(graph, parent=None):
    """Graph metadata supplies root defaults or inherits an instance context."""
    base = model(graph['base'])['literal']
    result = {'size': [2 ** n for n in graph['size']], 'seed': (base['seed'] * 0x9e3779b9) % UINT32,
              'format': 'u16', 'pixelSize': [1., 1.]}
    if parent is not None:
        for field in result: result[field] = copy.deepcopy(parent[field])
    for field in ('tiling', 'pixelRatio'):
        fallback = base[field] if parent is None else parent[field]
        result[field] = inherit(base[field + 'Mode'], base[field], None if parent is None else parent[field], fallback)
    return result


def resolve(parameters, input_, parent, evaluated=None):
    """Resolve all six base parameters, with explicit already-qualified values.

The caller must prove dynamic values in native seed/size/format/pixel-size/
pixel-ratio/tiling evaluation order and the corresponding changing context.
"""
    report = model(parameters); base = report['literal']; functions = report['functions']
    evaluated = {} if evaluated is None else evaluated
    require(set(evaluated) == set(functions), 'base functions require complete qualified evaluation')
    for name, value in evaluated.items():
        require(value['t'] == BASE_TYPES[name], 'base function returned the wrong value type')
        data = copy.deepcopy(value['v'])
        if name == 'outputsize':
            require(type(data) is list and len(data) == 2 and all(type(n) is int and -2**31 <= n < 2**31 for n in data), 'invalid dynamic output size')
            data = [max(-12, min(13, n)) for n in data]
        elif name == 'format':
            require(type(data) is int and 0 <= data <= 3, 'invalid dynamic output format'); data = FORMATS[data]
        elif name == 'tiling':
            require(type(data) is int and 0 <= data <= 3, 'invalid dynamic tiling'); data = [bool(data & 1), bool(data & 2)]
        elif name == 'pixelratio': require(type(data) is int and data in (0, 1), 'invalid dynamic pixel ratio')
        elif name == 'randomseed': require(type(data) is int and -2**31 <= data < 2**31, 'invalid dynamic random seed')
        else:
            require(type(data) is list and len(data) == 2 and all(type(n) in (int, float) and math.isfinite(n) and 0 < n <= 8192 for n in data), 'invalid dynamic pixel size')
            data = [proc.f32(str(n)) for n in data]
            require(all(n > 0 for n in data), 'dynamic pixel size underflows binary32')
        base[FIELDS[name]] = data
    def selected(field, absolute):
        mode = 'relativeToInput' if field == 'format' and base[field] == 'inherit' else base[field + 'Mode']
        return inherit(mode, absolute, None if input_ is None else input_[field], parent[field])
    size_base = selected('size', [1, 1]); pixels_base = selected('pixelSize', [1., 1.])
    return {'size': [max(16, min(8192, math.floor(size * 2.0 ** offset + .5))) for size, offset in zip(size_base, base['size'])],
            'seed': (selected('seed', 0) + base['seed']) % UINT32,
            'format': selected('format', base['format']),
            'tiling': selected('tiling', base['tiling']),
            'pixelRatio': selected('pixelRatio', base['pixelRatio']),
            'pixelSize': [max(MIN_POSITIVE, min(8192., proc.f32(str(a * b)))) for a, b in zip(pixels_base, base['pixelSize'])]}


def limited_size(size, maximum=None):
    if maximum is None: return list(size)
    require(type(maximum) is int and 0 <= maximum < UINT32, 'invalid native preview size limit')
    largest = max(size)
    if largest <= maximum: return list(size)
    scale = max(1, maximum) / largest
    return [max(1, math.floor(side * scale + .5)) for side in size]


def inspect_graph(graph, calls=(), parent=None, maximum=None, evaluated=None):
    """Predict one graph's bases and dimensions in native port order.

Image-instance inputs use already-resolved interfaces. Each called graph still
needs its own inspection with the instance base as its parent. The maximum only
limits raster dimensions; inherited bases and function contexts remain uncapped.
"""
    require('function' not in graph, 'standalone function has no image layout')
    evaluated = {} if evaluated is None else evaluated
    nodes = {node['native_id']: node for node in graph['nodes'].values()}
    require(set(evaluated) <= set(nodes), 'base evaluation names an absent node')
    wires = graph['connections']; incoming = {identity: {} for identity in nodes}
    for wire in wires: incoming[wire['to']][wire['toPort']] = wire['from']
    topology = proc.order(nodes, {key: list(ports.values()) for key, ports in incoming.items()})
    calls = {graph['nodes'][call['node']]['native_id']: call for call in calls}
    root = graph_parent(graph, parent); results = {}
    for identity in topology:
        node = nodes[identity]; definition = node['definition']; ports = incoming[identity]
        if definition == 'graph_instance':
            require(identity in calls, 'image instance requires a resolved interface')
            inputs = [p for p, spec in calls[identity]['inputs'].items() if spec['type'] in (1, 2)]
        else:
            require(definition in DEFINITIONS, 'unknown base-parameter node definition')
            inputs = list(DEFINITIONS[definition]['inputs'])
            if definition in ('pixel_processor', 'value_processor', 'fx_map'):
                prefix = 'pattern' if definition == 'fx_map' else 'input'
                indices = [int(p[len(prefix):]) for p in ports if p.startswith(prefix) and p[len(prefix):].isdigit()]
                count = min(256, max((index + 2 for index in indices if index < 256), default=1))
                inputs.extend(prefix + str(index) for index in range(1, count))
            require(not set(inputs) & set(node['input_values']), 'typed input duplicates an image port')
        primary = PRIMARY_INPUTS.get(definition)
        source = next((ports[p] for p in inputs if p in ports and (primary is None or p == primary)), None)
        input_ = copy.deepcopy(results[source]['base']) if source is not None else None
        if input_ is not None and definition in GENERATORS: input_['size'] = list(root['size'])
        base = resolve(node['parameters'], input_, root, evaluated.get(identity))
        results[identity] = {'base': base, 'raster_size': limited_size(base['size'], maximum), 'input_base_source': source}
    return {'parent': root, 'nodes': results, 'engine_admission_complete': False}


def check_native(report, observed):
    """Compare resolved bases only; actual image sizes require output-kind checks."""
    require(type(observed) is list and len(observed) == len(report['nodes']), 'native base inventory differs')
    seen = set()
    for node in observed:
        require(type(node) is dict and type(node.get('cooked')) is dict, 'native cooked base record is malformed')
        identity = node.get('id'); require(type(identity) is int and identity in report['nodes'] and identity not in seen, 'native base node identity differs')
        seen.add(identity)
        # Python considers True == 1. Native type tags must not disappear in a
        # dictionary comparison. This compares the small semantic records, not
        # normalized document bytes or serialized preservation evidence.
        actual = json.dumps(node['cooked'].get('base'), sort_keys=True, allow_nan=False)
        expected = json.dumps(report['nodes'][identity]['base'], sort_keys=True, allow_nan=False)
        require(actual == expected, 'native resolved base differs')
    return {'native_resolved_bases_equal': True, 'engine_admission_complete': False}
