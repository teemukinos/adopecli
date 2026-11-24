"""Finite native literal values and explicit SBS-to-native conversions.

The pinned engine uses the host powf ABI for its binary32 sRGB transfer. This
module uses that fixed math symbol, never a document-selected library or symbol.
Function/pattern bodies and effective cook-time clamps remain separate checks.
"""
import copy
import ctypes
import json
import math

from .material_container import require
from . import material_procedural as proc
from .material_node_catalog import DEFINITIONS, FILTERS

_POWER = None


def linear(value):
    global _POWER
    value = proc.f32(str(value))
    if value <= proc.f32('0.04045'):
        return proc.f32(str(value / proc.f32('12.92')))
    if _POWER is None:
        try:
            _POWER = ctypes.CDLL(None).powf
            _POWER.argtypes = (ctypes.c_float, ctypes.c_float)
            _POWER.restype = ctypes.c_float
        except (AttributeError, OSError) as error:
            raise ValueError('Material requires the qualified host powf ABI') from error
    shifted = proc.f32(str(value + proc.f32('0.055')))
    base = proc.f32(str(shifted / proc.f32('1.055')))
    result = _POWER(base, proc.f32('2.4'))
    require(math.isfinite(result), 'displayed color overflows finite native linear RGB')
    return result


def color(value):
    require(value['t'] == 'float4' and type(value['v']) is list and len(value['v']) == 4, 'color conversion requires Float4')
    return {'t': 'color', 'v': [linear(component) for component in value['v'][:3]] + [proc.f32(str(value['v'][3]))]}


def exposed_default(port):
    value = port['value']; widget = port['widget']; opts = widget['options']
    if port['type'] in (1, 2): return color(value)
    if not port['connectable']:
        if widget['name'] == 'dropdownlist': return {'t': 'enum', 'v': value['v']}
        if value['t'] == 'float4' and (widget['name'] == 'color' or opts.get('valueInterpretation') == 'color'): return color(value)
    return copy.deepcopy(value)


def node_literals(key, graph, node_id, references):
    from .material_graphs import BASE_TYPES, USAGES
    node = graph['nodes'][node_id]; definition = node['definition']; values = {}; bodies = set(); functions = set()
    if definition.startswith('input_'):
        port = graph['inputs'][node['bridge']]
        values = {'identifier': {'t': 'text', 'v': port['name']}, 'usage': {'t': 'enum', 'v': USAGES.index(port['usage'])},
                  'default': exposed_default(port)}
    elif definition == 'output':
        port = graph['outputs'][node['bridge']]
        values = {'identifier': {'t': 'text', 'v': port['name']}, 'usage': {'t': 'enum', 'v': USAGES.index(port['usage'])}}
    elif definition == 'graph_instance':
        call = next(call for call in references['image_calls'][key] if call['node'] == node_id)
        if call['target'][0] == key[0]: values['graph'] = {'t': 'text', 'v': node['reference']['path']}
        for name, record in node['parameters'].items():
            if name in BASE_TYPES: continue
            if record['value']['t'] == 'function': functions.add(name)
            else: values[name] = copy.deepcopy(record['value'])
    else:
        mappings = [spec for spec in FILTERS.values() if spec['definition'] == definition]
        require(len(mappings) == 1, 'native filter value mapping is ambiguous')
        mapping = mappings[0]['parameters']; specs = DEFINITIONS[definition]['parameters']
        for name, record in node['parameters'].items():
            if name in BASE_TYPES: continue
            value = record['value']
            if name in mapping:
                target = mapping[name]; kind = specs[target]['default']['t']
                if value['t'] == 'function':
                    (bodies if kind == 'function' else functions).add(target)
                else: values[target] = color(value) if kind == 'color' else {'t': 'enum', 'v': value['v']} if kind == 'enum' else copy.deepcopy(value)
            elif name in ('bitmapresourcepath', 'vectorresourcepath'):
                matches = [ref['resource'][1] for ref in references['resources'] if ref['graph'] == key and ref['node'] == node_id]
                require(len(matches) == 1, 'resource parameter lacks its unique resolved name')
                values['resource'] = {'t': 'text', 'v': matches[0]}
            elif name == 'channelsweights':
                values.update({channel: {'t': 'float', 'v': number} for channel, number in zip(('red', 'green', 'blue', 'alpha'), value['v'])})
            else: require(False, 'literal node parameter has no native mapping')
        for name, cells in node.get('arrays', {}).items():
            if name == 'curveluminance':
                values['curve'] = {'t': 'curve', 'v': {'points': [{'x': c['position'][0], 'y': c['position'][1], 'left': c['left'], 'right': c['right']} for c in cells]}}
            else:
                # These cells are already linear Float4 values. Applying the
                # displayed-color transfer here would change the gradient.
                values['gradient'] = {'t': 'gradient', 'v': {'keys': [{'pos': c['position'], 'color': c['value'], 'midpoint': c['midpoint']} for c in cells]}}
        if 'pattern' in node: bodies.add('pattern')
    return {'values': values, 'procedural_parameters': sorted(bodies), 'parameter_functions': sorted(functions), 'engine_admission_complete': False}


def inspect(graph_profile, references):
    return {'graphs': {key: {'defaults': {port['name']: exposed_default(port) for port in graph['inputs'].values() if not port['connectable']},
                             'nodes': {node['native_id']: node_literals(key, graph, identity, references) for identity, node in graph['nodes'].items()}}
                       for key, graph in graph_profile['graphs'].items()}, 'engine_admission_complete': False}


def check_native(report, package, native):
    expected = {key[1]: graph for key, graph in report['graphs'].items() if key[0] == package}; seen = set()
    def equal(left, right):
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    require(type(native) is dict and type(native.get('graphs')) is list, 'native literal package is malformed')
    for graph in native['graphs']:
        require(type(graph) is dict and type(graph.get('name')) is str and type(graph.get('folder', '')) is str, 'native literal graph is malformed')
        name = (graph.get('folder', '') + '/' if graph.get('folder') else '') + graph['name']
        require(name in expected and name not in seen, 'native literal graph identity differs'); seen.add(name); wanted = expected[name]
        exposed = graph.get('exposed')
        require(type(exposed) is list and all(type(p) is dict and type(p.get('id')) is str and 'default' in p for p in exposed), 'native exposed inputs are malformed')
        require(len(exposed) == len(wanted['defaults']) and len({p['id'] for p in exposed}) == len(exposed), 'native exposed input inventory differs')
        require(equal({p['id']: p['default'] for p in exposed}, wanted['defaults']), 'native exposed default values differ')
        nodes = graph.get('nodes'); require(type(nodes) is list and len(nodes) == len(wanted['nodes']), 'native literal node inventory differs'); node_ids = set()
        for node in nodes:
            require(type(node) is dict, 'native literal node is malformed')
            identity = node.get('id'); require(type(identity) is int and identity in wanted['nodes'] and identity not in node_ids, 'native literal node identity differs'); node_ids.add(identity)
            fields = wanted['nodes'][identity]; parameters = node.get('params', {}); omitted = set(fields['procedural_parameters'])
            require(type(parameters) is dict and type(node.get('functions', {})) is dict, 'native parameter maps are malformed')
            require(set(parameters) == set(fields['values']) | omitted, 'native literal parameter inventory differs')
            require(equal({k: v for k, v in parameters.items() if k not in omitted}, fields['values']), 'native literal parameter values differ')
            require(set(node.get('functions', {})) == set(fields['parameter_functions']), 'native parameter-function inventory differs')
    require(seen == set(expected), 'native literal graph inventory is incomplete')
    return {'native_literal_values_equal': True, 'procedural_bodies_compared': False, 'engine_admission_complete': False}
