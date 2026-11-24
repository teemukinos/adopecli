"""Strict procedural SBS structure and conservative work accounting.

This is a prerequisite, not permission to launch the native engine. Outer image
nodes, call resolution, type/scope semantics and whole-job work remain separate.
Original XML/member bytes are owned by material_container, never normalized here.
"""
import math
import re
import struct

from .material_resources import children, fields, scalar, uid, identifier
from .material_container import require
from .material_function_catalog import INPUTS

MAX_NODES = 4096
MAX_TOTAL_NODES = 16384
MAX_BODIES = 256
MAX_STRING_BYTES = 65536
FUNCTION_STEPS = 100000
PATTERN_VISITS = 65536
TYPE_CODES = {4, 16, 32, 64, 128, 256, 512, 1024, 2048, 16384}
PATTERN_PORTS = {'paramset': ('output0', 'output1', 'output2', 'output3'),
                 'markov2': ('output0', 'output1'), 'addnode': ('output0', 'output1'),
                 'passthrough': ('output',)}
COMMON = {'randomseed': ('int',), 'randominherited': ('bool',)}
PATTERN_PARAMETERS = {
    'passthrough': {},
    'markov2': {**COMMON, 'switch': ('bool',)},
    'addnode': {**COMMON, 'numberadded': ('int',)},
    'paramset': {**COMMON, 'patterntype': ('int',), 'opacity': ('float', 'float4'),
                'branchoffset': ('float2',), 'frameoffset': ('float2',),
                'patternsize': ('float2',), 'patternrotation': ('float',),
                'patternsuppl': ('float',), 'blendingmode': ('int',),
                'imagefiltering': ('int',), 'imagepremul': ('bool',), 'imageindex': ('int',)},
}


def integer(text, low, high):
    require(re.fullmatch(r'-?(0|[1-9][0-9]*)', text) is not None and len(text) <= 20,
            'integer is malformed or noncanonical')
    result = int(text)
    require(low <= result <= high, 'integer exceeds its native range')
    return result


def f32(text):
    require(re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', text) is not None,
            'float is malformed or nonfinite')
    try:
        value = struct.unpack('<f', struct.pack('<f', float(text)))[0]
    except (ValueError, OverflowError, struct.error):
        raise ValueError('Material float exceeds finite binary32') from None
    require(math.isfinite(value), 'float exceeds finite binary32')
    return value


def vector(text, count):
    parts = text.split()
    require(len(parts) == count, 'vector arity differs from its native type')
    return [f32(part) for part in parts]


def node_id(element):
    value = uid(element)
    require(value <= 2**32-1, 'procedural node ID exceeds native u32')
    return value


def text_value(element):
    value = scalar(element)
    require(len(value.encode('utf-8')) <= MAX_STRING_BYTES, 'procedural text exceeds its budget')
    return value


def entries(element, tag):
    result = children(element)
    require(all(item['tag'] == tag for item in result), 'unexpected child in '+element['tag'])
    return result


def constant(element):
    tag = element['tag']; text = text_value(element)
    if tag == 'constantValueString': return {'t': 'text', 'v': text}
    if tag == 'constantValueBool':
        require(text in ('0', '1'), 'boolean requires canonical zero or one')
        return {'t': 'bool', 'v': text == '1'}
    if tag == 'constantValueInt32': return {'t': 'int', 'v': integer(text, -2**31, 2**31-1)}
    match = re.fullmatch(r'constantValue(Float[1-4]|Int[2-4])', tag)
    require(match is not None, 'unknown constant type: '+tag)
    name = match[1]; count = int(name[-1]); parts = text.split()
    require(len(parts) == count, 'constant vector arity differs from its tag')
    values = [f32(p) if name.startswith('Float') else integer(p, -2**31, 2**31-1) for p in parts]
    return {'t': ('float' if name.startswith('Float') else 'int') + (str(count) if count > 1 else ''),
            'v': values if count > 1 else values[0]}


def single(element):
    values = children(element)
    require(len(values) == 1, 'value requires exactly one body')
    return values[0]


def position(element):
    layout = fields(element, ('gpos',))
    values = vector(scalar(layout['gpos']), 3)
    require(values[2] == 0, 'procedural node Z coordinate would be dropped')
    return values[:2]


def annotations(element):
    """Validate all three native canvas forms; retain source fields for later comparison."""
    result = []; seen = set()
    for entry in entries(element, 'GUIObject'):
        record = fields(entry, ('type', 'GUILayout', 'GUIName', 'uid'),
                        ('title', 'frameColor', 'isTitleVisible', 'isFrameVisible'))
        identity = uid(record['uid']); require(identity not in seen, 'duplicate canvas UID'); seen.add(identity)
        kind = scalar(record['type']); layout = fields(record['GUILayout'], ('gpos',), ('size',))
        xyz = vector(scalar(layout['gpos']), 3); text_value(record['GUIName'])
        if kind == 'PIN':
            require(set(record) == {'type','GUILayout','GUIName','uid'} and 'size' not in layout and xyz[2] == 0,
                    'pin has fields that native loading would drop')
        else:
            require(kind == 'COMMENT' and 'size' in layout and 'isFrameVisible' in record, 'unsupported canvas form')
            size = vector(scalar(layout['size']), 2); require(min(size) >= 8, 'canvas size would be clamped')
            visible = scalar(record['isFrameVisible']); require(visible in ('0','1'), 'invalid frame visibility')
            if visible == '1':
                require(set(record) == {'type','GUILayout','GUIName','uid','title','frameColor','isTitleVisible','isFrameVisible'} and xyz[2] == -100,
                        'frame fields are incomplete or noncanonical')
                text_value(record['title']); color = vector(scalar(record['frameColor']), 4)
                require(all(0 <= c <= 1 for c in color), 'frame color requires a qualified conversion range')
                require(scalar(record['isTitleVisible']) in ('0','1'), 'invalid title visibility')
            else:
                require(set(record) == {'type','GUILayout','GUIName','uid','isFrameVisible'} and xyz[2] == 0,
                        'comment has fields that native loading would drop')
        result.append(entry)
    return result


def order(nodes, edges):
    """Iterative postorder checks every node, including unreachable components."""
    complete = set(); active = set(); result = []
    for root in nodes:
        pending = [(root, False)]
        while pending:
            identity, visited = pending.pop()
            if identity in complete: continue
            require(identity in nodes, 'procedural connection references a missing node')
            if visited:
                active.remove(identity); complete.add(identity); result.append(identity); continue
            require(identity not in active, 'procedural graph contains a cycle')
            active.add(identity); pending.append((identity, True))
            pending.extend((child, False) for child in reversed(edges[identity]) if child is not None)
    return result


def connections(element, ports):
    result = dict.fromkeys(ports)
    seen = set()
    for item in entries(element, 'connection'):
        record = fields(item, ('identifier','connRef')); name = scalar(record['identifier'])
        require(name in result and name not in seen, 'unknown or duplicate procedural input port')
        seen.add(name); result[name] = node_id(record['connRef'])
    return list(result.values())


def function(element):
    require(element['tag'] == 'dynamicValue', 'expected dynamicValue')
    root = fields(element, ('paramNodes',), ('rootnode','GUIObjects'))
    items = entries(root['paramNodes'], 'paramNode'); require(len(items) <= MAX_NODES, 'function node budget exceeded')
    nodes = {}; references = []; missing = False
    for item in items:
        record = fields(item, ('uid','function','type','GUILayout','connections'), ('funcDatas','materialcraftInterface'))
        identity = node_id(record['uid']); require(identity not in nodes, 'duplicate function node ID')
        op = scalar(record['function']); require(op in INPUTS or op == 'instance', 'unqualified function operation: '+op)
        code = integer(scalar(record['type']), 0, 2**32-1); require(code in TYPE_CODES or code == 0, 'invalid function type code')
        value = None
        if 'funcDatas' in record:
            data = entries(record['funcDatas'], 'funcData'); require(len(data) == 1, 'function data would be skipped or recovered')
            data = fields(data[0], ('name','constantValue'))
            require(scalar(data['name']) == op, 'function data name differs from operation')
            value = constant(single(data['constantValue']))
        node = {'id': identity, 'op': op, 'type_code': code, 'pos': position(record['GUILayout'])}
        if op == 'instance':
            require(value is not None and value['t'] == 'text', 'function instance requires an explicit reference')
            require('materialcraftInterface' in record, 'function instance requires its explicit interface')
            match = re.fullmatch(r'pkg:///([^?]+)(?:\?dependency=([0-9]+))?', value['v'])
            require(match is not None, 'function instance requires an admitted package reference')
            path = match[1]; require(all(identifier(part) for part in path.split('/')), 'invalid function reference path')
            ports = []; names = set()
            for entry in entries(record['materialcraftInterface'], 'input'):
                port = fields(entry, ('identifier','type')); name = identifier(scalar(port['identifier']))
                require(name not in names, 'duplicate function instance interface'); names.add(name)
                port_type = integer(scalar(port['type']), 0, 2**32-1); require(port_type in TYPE_CODES, 'invalid instance input type')
                ports.append({'identifier': name, 'type_code': port_type})
            require(len(ports) <= MAX_NODES, 'function instance port budget exceeded')
            node['inputs'] = connections(record['connections'], [p['identifier'] for p in ports])
            references.append({'node': identity, 'graph': path, 'dependency': match[2], 'inputs': ports, 'type_code': code})
            # The instance model depends on admitted package resolution/defaults.
            node['reference'] = value['v']; node['interface'] = ports
        else:
            require('materialcraftInterface' not in record, 'intrinsic function has unused instance interface')
            node['inputs'] = connections(record['connections'], INPUTS[op])
            # Native defaults must not silently fill missing serialized data.
            expected = ('text' if op.startswith('get_') or op in ('set','isdefined','const_string') else
                        'bool' if op == 'const_bool' else
                        ('float'+op[-1]).replace('float1','float') if op.startswith('const_float') else
                        ('int'+op[-1]).replace('int1','int') if op.startswith('const_int') else
                        ('int'+op[-1]).replace('int1','int') if 'swizzle' in op else
                        'int2' if op in ('samplecol','samplelum') else 'int' if op == 'while' else None)
            if expected is not None:
                require(value is not None and value['t'] == expected, 'function data is missing or has the wrong native type')
            if value is not None: node['value'] = value
        missing |= any(child is None for child in node['inputs']); nodes[identity] = node
    output = node_id(root['rootnode']) if 'rootnode' in root else None
    require(output is None or output in nodes, 'missing function result')
    require(output is None or nodes[output]['op'] != 'passthrough', 'native loader would drop a Dot result')
    topology = order(nodes, {key: node['inputs'] for key,node in nodes.items()})
    costs = {}; unresolved = bool(references)
    for identity in topology:
        node = nodes[identity]; args = [costs.get(child, 0) for child in node['inputs']]; op = node['op']
        if op == 'instance': cost = FUNCTION_STEPS+1
        elif op == 'ifelse': cost = 2 + args[0] + max(args[1:])
        elif op == 'while':
            maximum = node['value']['v']
            cost = FUNCTION_STEPS+1 if maximum < 0 else 2+args[0]+(maximum+1)*(1+args[1])+maximum*(1+args[2])
        else: cost = 2 + sum(args)
        costs[identity] = min(cost, FUNCTION_STEPS+1)
    bound = costs.get(output, 0)
    canvas = annotations(root['GUIObjects']) if 'GUIObjects' in root else []
    return {'model': {'nodes': list(nodes.values()), 'output': output}, 'annotations_xml': canvas,
            'references': references, 'nodes': len(nodes), 'steps_bound': min(bound, FUNCTION_STEPS),
            'may_exhaust_native_budget': bound > FUNCTION_STEPS, 'complete_connections': not missing,
            'requires_call_resolution': unresolved, 'engine_admission_complete': False}


def pattern(element):
    require(element['tag'] == 'paramsGraph', 'expected paramsGraph')
    root = fields(element, ('name','uid','paramsGraphDatas','paramsGraphNodes'), ('rootnode','GUIObjects'))
    require(scalar(root['name']) == '', 'pattern graph name would be dropped'); uid(root['uid'])
    data = {}; functions = []; used = set(); nodes = {}
    for item in entries(root['paramsGraphDatas'], 'paramsGraphData'):
        require(len(data) < MAX_NODES, 'pattern data budget exceeded')
        record = fields(item, ('uid','type','parameters')); identity = uid(record['uid'])
        require(identity not in data, 'duplicate pattern data ID'); kind = scalar(record['type'])
        require(kind in PATTERN_PORTS, 'unknown pattern data type'); values = {}
        for entry in entries(record['parameters'], 'parameter'):
            parameter = fields(entry, ('name','paramValue'), ('relativeTo',))
            name = scalar(parameter['name']); require(name in PATTERN_PARAMETERS[kind] and name not in values, 'unknown or duplicate pattern parameter')
            body = single(parameter['paramValue'])
            if body['tag'] == 'dynamicValue':
                require('relativeTo' not in parameter, 'dynamic pattern parameter has ignored relative mode')
                report = function(body); functions.append(report); value = {'t':'function','v':report['model']}
            else:
                require('relativeTo' in parameter and scalar(parameter['relativeTo']) == '0', 'pattern constant requires absolute mode')
                value = constant(body); require(value['t'] in PATTERN_PARAMETERS[kind][name], 'pattern parameter type differs from its contract')
                if name == 'numberadded': require(0 <= value['v'] <= 10000, 'pattern iteration count exceeds native limit')
            values[name] = value
        require(set(values) == set(PATTERN_PARAMETERS[kind]), 'missing pattern defaults require explicit conversion')
        data[identity] = (kind, values)
    for item in entries(root['paramsGraphNodes'], 'paramsGraphNode'):
        require(len(nodes) < MAX_NODES, 'pattern node budget exceeded')
        record = fields(item, ('uid','type','data','GUILayout','connections')); identity = node_id(record['uid'])
        require(identity not in nodes, 'duplicate pattern node ID'); kind = scalar(record['type']); ref = uid(record['data'])
        require(ref in data and ref not in used and data[ref][0] == kind, 'pattern data missing, reused or type differs')
        used.add(ref); require(kind in PATTERN_PORTS, 'unknown pattern node kind')
        nodes[identity] = {'id':identity, 'kind':kind, 'parameters':data[ref][1], 'position':position(record['GUILayout']),
                           'children':connections(record['connections'], PATTERN_PORTS[kind])}
    require(used == set(data), 'unreferenced pattern data would be dropped')
    output = node_id(root['rootnode']) if 'rootnode' in root else None
    require(output is None or output in nodes, 'missing pattern root')
    topology = order(nodes, {key:node['children'] for key,node in nodes.items()})
    costs = {}; stamps = {}; dynamic_iterations = False
    for identity in topology:
        node = nodes[identity]; args = [costs.get(child,0) for child in node['children']]
        paints = [stamps.get(child,0) for child in node['children']]; kind = node['kind']
        if kind == 'addnode':
            count = node['parameters']['numberadded']; dynamic = count['t'] == 'function'; dynamic_iterations |= dynamic
            maximum = 10000 if dynamic else count['v']
            visits = 1+args[0]+maximum*args[1]; paint = paints[0]+maximum*paints[1]
        elif kind == 'markov2':
            switch = node['parameters']['switch']; slots = [int(switch['v'])] if switch['t'] == 'bool' else [0,1]
            visits = 1+max(args[s] for s in slots); paint = max(paints[s] for s in slots)
        else:
            visits = 1+sum(args); paint = (1 if kind == 'paramset' else 0)+sum(paints)
        costs[identity] = min(visits,PATTERN_VISITS+1); stamps[identity] = min(paint,PATTERN_VISITS+1)
    visits = costs.get(output,0)
    canvas = annotations(root['GUIObjects']) if 'GUIObjects' in root else []
    return {'model': {'nodes':list(nodes.values()), 'root':output}, 'annotations_xml':canvas,
            'nodes':len(nodes), 'functions':functions, 'visits_bound':min(visits,PATTERN_VISITS),
            'stamps_bound':min(stamps.get(output,0),PATTERN_VISITS), 'dynamic_iterations':dynamic_iterations,
            'may_exhaust_native_budget':visits>PATTERN_VISITS, 'engine_admission_complete':False}


def inspect(profile):
    """Inventory every embedded body, including disconnected/unused content."""
    # Count globally before constructing any normalized model, including bodies
    # nested in pattern parameters. XML itself was already allocation-bounded.
    elements = [element for parsed in profile['xml'].values() for element in parsed['elements']]
    require(sum(e['tag'] in ('dynamicValue','paramsGraph') for e in elements) <= MAX_BODIES,
            'procedural body count exceeds budget')
    require(sum(e['tag'] in ('paramNode','paramsGraphNode') for e in elements) <= MAX_TOTAL_NODES,
            'aggregate procedural nodes exceed budget')
    functions = {}; patterns = {}; total = 0
    for path, parsed in profile['xml'].items():
        for index, element in enumerate(parsed['elements']):
            tag = element['tag']
            if tag == 'paramsGraphs':
                values = entries(element, 'paramsGraph')
                require(len(values) == 1, 'native reader requires one pattern graph per holder')
            if tag not in ('dynamicValue','paramsGraph'): continue
            require(len(functions)+len(patterns) < MAX_BODIES, 'procedural body count exceeds budget')
            report = function(element) if tag == 'dynamicValue' else pattern(element)
            total += report['nodes']; require(total <= MAX_TOTAL_NODES, 'aggregate procedural nodes exceed budget')
            # XML identity is an unambiguous tuple, not a concatenated string.
            (functions if tag == 'dynamicValue' else patterns)[(path,index)] = report
    return {'functions':functions, 'patterns':patterns, 'nodes':total, 'engine_admission_complete':False}
