"""Static operand and caller-scope contracts for admitted Material functions.

This checks reachable instructions, including both branches and loop bodies.
It deliberately does not certify numeric domains, concrete Value variants,
ordered user-variable flow, callee semantics or whole-job execution budgets.
An editable function may contain disconnected drafts outside its result tree.
"""
from .material_container import require
from .material_function_catalog import INPUTS
from .material_references import FIXED_TYPES, VALUE_CODES, node_types
from . import material_procedural as proc

INTEGER = {16: 1, 32: 2, 64: 3, 128: 4}
FLOAT = {256: 1, 512: 2, 1024: 3, 2048: 4}
NUMERIC = INTEGER | FLOAT
SYSTEM = {
    '$normalformat': 16, '$tiling': 16, '$pixelratio': 16, '$uvtile': 32,
    '$physicalsize': 1024, '$size': 512, '$sizelog2': 512, '$time': 256,
    '$pos': 512, '$depth': 256, '$depthpow2': 256, '$number': 256,
}
INTEGER_OPS = set('add sub mul div mod neg abs min max'.split())
ARITHMETIC = INTEGER_OPS | set('mulscalar floor ceil sqrt exp log log2 pow pow2 sin cos tan lerp rand dot atan2 cartesian'.split())


def available(name, scope):
    if name == '$pos': return scope in ('pixel', 'fx_map')
    if name in ('$depth', '$depthpow2', '$number'): return scope == 'fx_map'
    return True


def inspect_function(resolved, scope, *, defer_scope=False):
    """Inspect one resolved body in its actual caller scope without execution.

Callers must also inspect reachable callees in this same scope. A successful
report is a static prerequisite, never permission to run a document.
The flow checker may defer system availability to its control-path analysis.
"""
    require(scope in ('node', 'pixel', 'fx_map'), 'unknown function caller scope')
    model = resolved['model']; calls = resolved['calls']
    nodes = {node['id']: node for node in model['nodes']}
    require(len(nodes) == len(model['nodes']) <= proc.MAX_NODES, 'invalid semantic node inventory')
    require(model['output'] in nodes, 'executable function requires a result')
    topology = proc.order(nodes, {key: node['inputs'] for key, node in nodes.items()})
    types = node_types(model, calls)
    require(types == resolved['types'], 'resolved function type inventory changed')
    reachable = set(); pending = [model['output']]
    while pending:
        identity = pending.pop()
        if identity in reachable: continue
        reachable.add(identity)
        pending.extend(source for source in nodes[identity]['inputs'] if source is not None)
    reads = []; writes = []; predicates = []; domains = []; invoked = []
    for identity in topology:
        if identity not in reachable: continue
        node = nodes[identity]; op = node['op']; code = types[identity]
        sources = node['inputs']; args = [types.get(source) for source in sources]
        value = node.get('value'); expected = None
        def need(condition, message):
            require(condition, f'Material function node {identity} ({op}): {message}')
        if op == 'instance':
            need(identity in calls, 'call has not been resolved')
            call = calls[identity]
            need(len(args) == len(call['inputs']), 'call arity differs')
            for source, arg, port in zip(sources, args, call['inputs']):
                need(source is None or arg == port['type_code'], 'call argument type differs')
                if source is None: need(port['identifier'] in call['default_specs'], 'missing call default')
            expected = call['output_type']; invoked.append(identity)
        else:
            need(op in INPUTS, 'unknown intrinsic operation')
            need(len(args) == len(INPUTS[op]) and None not in args, 'requires connected inputs')
            if op.startswith('const_'):
                need(value is not None and VALUE_CODES.get(value['t']) == FIXED_TYPES[op], 'constant type differs')
                expected = FIXED_TYPES[op]
            elif op.startswith('get_') or op == 'isdefined':
                need(value is not None and value['t'] == 'text', 'variable name must be text')
                name = value['v']; expected = FIXED_TYPES[op]
                if op == 'isdefined':
                    predicates.append({'node': identity, 'name': name,
                                       'system_available': available(name, scope) if name in SYSTEM else None})
                elif name in SYSTEM:
                    need(defer_scope or available(name, scope), 'system variable is unavailable in caller scope')
                    need(expected == SYSTEM[name], 'system variable getter has the wrong type')
                else: reads.append({'node': identity, 'name': name, 'type': expected})
            elif op == 'set':
                need(value is not None and value['t'] == 'text' and value['v'] and not value['v'].startswith('$'),
                     'use a nonempty user variable name')
                expected = args[0]; writes.append({'node': identity, 'name': value['v'], 'type': expected})
            elif op in ('and', 'or', 'not'):
                need(all(arg == 4 for arg in args), 'logical operands must be Boolean'); expected = 4
            elif op in ('eq', 'noteq'):
                need(args[0] == args[1], 'equality operands must have matching types'); expected = 4
            elif op in ('gt', 'gteq', 'lr', 'lreq'):
                need(args[0] in (16, 256) and args[0] == args[1], 'comparison requires matching numeric scalars'); expected = 4
            elif op in ('ifelse', 'while'):
                condition, left, right = (args[0], args[1], args[2]) if op == 'ifelse' else (args[1], args[0], args[2])
                need(condition == 4, 'control condition must be Boolean')
                need(left == right, 'all control results must have matching types'); expected = left
                if op == 'while': domains.append({'node': identity, 'reason': 'loop termination and iteration budget'})
            elif op in ('sequence', 'passthrough'):
                expected = args[-1]
            elif op in ('samplecol', 'samplelum'):
                need(args == [512], 'sample position must be Float2')
                need(value is not None and value['t'] == 'int2' and value['v'][0] >= 0, 'invalid image sample setting')
                expected = FIXED_TYPES[op]
            elif 'swizzle' in op or 'vector' in op or op.startswith('to'):
                integer = op.startswith('i') or op.startswith('toint')
                family = INTEGER if integer else FLOAT
                expected = FIXED_TYPES[op]; count = family[expected]
                if 'swizzle' in op:
                    need(args[0] in family, 'swizzle input has the wrong numeric family')
                    need(value is not None, 'missing swizzle setting')
                    indices = value['v'] if isinstance(value['v'], list) else [value['v']]
                    need(len(indices) == count and all(0 <= index < family[args[0]] for index in indices), 'swizzle component is outside its input')
                elif 'vector' in op:
                    need(all(arg in family for arg in args), 'vector inputs have the wrong numeric family')
                    need(sum(family[arg] for arg in args) == count, 'vector input dimensions do not sum to its result')
                else:
                    source_family = FLOAT if integer else INTEGER
                    need(args[0] in source_family and source_family[args[0]] == count, 'cast requires opposite numeric family and equal dimensions')
                    if integer: domains.append({'node': identity, 'reason': 'finite Float to Integer range'})
            elif op in ARITHMETIC:
                need(args[0] in NUMERIC, 'arithmetic requires numeric operands')
                family = INTEGER if args[0] in INTEGER else FLOAT
                need(family is FLOAT or op in INTEGER_OPS, 'operation requires floating-point operands')
                need(all(arg in family for arg in args), 'arithmetic operands have different numeric families')
                if len(args) > 1:
                    need(args[1] == args[0] or (op == 'mulscalar' and args[1] == 256), 'arithmetic operand dimensions differ')
                if len(args) > 2: need(args[2] in (256, args[0]), 'interpolation factor must be scalar or match its operands')
                if op == 'atan2': need(args == [512], 'arc tangent requires Float2')
                if op == 'cartesian': need(args == [256, 256], 'Cartesian requires scalar radius and angle')
                expected = FIXED_TYPES.get(op, args[0])
                domains.append({'node': identity, 'reason': 'numeric domain, overflow and finite result'})
            else: need(False, 'intrinsic semantic contract is missing')
        need(code == expected, 'declared result type differs from its operand contract')
    return {'scope': scope, 'reachable_nodes': len(reachable), 'draft_nodes': len(nodes) - len(reachable),
            'result_type': types[model['output']], 'reads': reads, 'writes': writes, 'predicates': predicates,
            'calls': invoked, 'numeric_obligations': domains,
            'requires_scope_flow_validation': defer_scope,
            'requires_variable_flow_validation': bool(reads or writes or any(p['system_available'] is None for p in predicates)),
            'requires_callee_semantics': bool(invoked), 'concrete_values_qualified': False,
            'engine_admission_complete': False}
