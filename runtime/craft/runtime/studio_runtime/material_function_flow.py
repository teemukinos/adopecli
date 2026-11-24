"""Bounded, ordered abstract variable flow through resolved Material functions.

Values carry types and known Boolean conditions, not numeric results. Branches
merge environments; calls inherit caller variables but isolate their writes.
No filesystem/native execution occurs and this is not execution admission.
"""
from .material_container import require
from . import material_function_semantics as semantics

MAX_VISITS = 100000
MAX_ENVIRONMENT_CELLS = 2000000
MAX_VARIABLES = 4096
UNDEFINED = frozenset({None})


def inspect(functions, entry, scope, variables=None):
    """Check an entry body using definite caller variable type declarations.

Diagnostics describe reachable reads that are not proven valid. Numeric domains,
termination and parameter-context values remain separate obligations. Unknown
conditions explore both paths without assuming successful execution proves a
condition, and `and`/`or` evaluate both operands as the native program does.
"""
    require(entry in functions, 'function flow entry is absent')
    require(len(functions) <= semantics.proc.MAX_BODIES, 'function flow body budget exceeded')
    variables = {} if variables is None else variables
    require(all(type(name) is str and type(code) is int and code in semantics.proc.TYPE_CODES for name, code in variables.items()), 'invalid caller variable types')
    computed = {'$pos', '$size', '$sizelog2'}
    require(all(name not in semantics.SYSTEM or name in computed or code == semantics.SYSTEM[name] for name, code in variables.items()), 'caller system variable has the wrong type')
    initial = {name: frozenset({code}) for name, code in variables.items()}
    require(len(initial) <= MAX_VARIABLES, 'function flow variable budget exceeded')
    checked = {}; diagnostics = set(); visits = 0; cells = 0; calls = 0; unbounded = False

    def prepare(key):
        if key not in checked:
            require(key in functions, 'function flow callee is absent')
            report = functions[key]
            semantics.inspect_function(report, scope, defer_scope=True)
            checked[key] = {node['id']: node for node in report['model']['nodes']}
        return checked[key]

    def copied(environment):
        nonlocal cells
        cells += len(environment)
        require(cells <= MAX_ENVIRONMENT_CELLS, 'function flow environment-copy budget exceeded')
        return dict(environment)

    def joined(left, right):
        nonlocal cells
        names = left.keys() | right.keys()
        require(len(names) <= MAX_VARIABLES, 'function flow variable budget exceeded')
        result = copied(left)
        cells += len(names) - len(left)
        require(cells <= MAX_ENVIRONMENT_CELLS, 'function flow environment-copy budget exceeded')
        for name in names: result[name] = left.get(name, UNDEFINED) | right.get(name, UNDEFINED)
        return result

    def refined(environment, predicate, truth):
        result = copied(environment)
        if predicate is not None:
            name, positive = predicate
            binding = result.get(name, UNDEFINED)
            result[name] = binding - {None} if truth == positive else UNDEFINED
        return result

    def evaluate(key, identity, environment, depth):
        nonlocal visits, calls, unbounded
        visits += 1
        require(visits <= MAX_VISITS, 'function flow visit budget exceeded')
        require(depth <= 8, 'function flow call depth exceeds native limit')
        node = prepare(key)[identity]; report = functions[key]; op = node['op']; sources = node['inputs']
        code = report['types'][identity]
        # Abstract result: (native type code, known Boolean or None, immediate
        # isdefined predicate). Predicates are never stored in user variables.
        unknown = (code, None, None)
        if op == 'ifelse':
            condition, environment = yield key, sources[0], environment, depth
            if condition[1] is not None:
                return (yield key, sources[1 if condition[1] else 2], environment, depth)
            left, left_env = yield key, sources[1], refined(environment, condition[2], True), depth
            right, right_env = yield key, sources[2], refined(environment, condition[2], False), depth
            truth = left[1] if left[1] == right[1] else None
            return (code, truth, None), joined(left_env, right_env)
        if op == 'sequence':
            _, environment = yield key, sources[0], environment, depth
            return (yield key, sources[1], environment, depth)
        if op == 'while':
            last, environment = yield key, sources[0], environment, depth
            maximum = node['value']['v']; iteration = 0; exits = None
            unbounded |= maximum < 0
            while True:
                head = copied(environment)
                condition, environment = yield key, sources[1], environment, depth
                # Native loops exit on TRUE, and always evaluate the condition
                # even when the iteration limit is zero or has been reached.
                if maximum >= 0 and iteration >= maximum:
                    exits = environment if exits is None else joined(exits, environment)
                    return unknown, exits
                if condition[1] is not False:
                    exit_env = refined(environment, condition[2], True)
                    exits = exit_env if exits is None else joined(exits, exit_env)
                if condition[1] is True: return unknown, exits
                last, environment = yield key, sources[2], refined(environment, condition[2], False), depth
                iteration += 1
                if maximum < 0:
                    environment = joined(head, environment)
                    if environment == head:
                        # Stable abstract state proves type flow only. A native
                        # loop may still exhaust its finite execution budget.
                        return unknown, environment if exits is None else exits
        arguments = []
        for source in sources:
            if source is not None:
                argument, environment = yield key, source, environment, depth
                arguments.append(argument)
        if op == 'instance':
            call = report['calls'][identity]; calls += 1
            callee = copied(environment)
            for port in call['inputs']: callee[port['identifier']] = frozenset({port['type_code']})
            require(len(callee) <= MAX_VARIABLES, 'function flow variable budget exceeded')
            target = call['body']; prepare(target)
            value, _ = yield target, functions[target]['model']['output'], callee, depth + 1
            # The native call clones its caller environment; its assignments do
            # not leak back. Argument side effects have already happened above.
            return (code, value[1], None), environment
        if op.startswith('const_'):
            return (code, node['value']['v'] if code == 4 else None, None), environment
        if op.startswith('get_'):
            name = node['value']['v']
            if name in semantics.SYSTEM:
                binding = frozenset({semantics.SYSTEM[name]}) if semantics.available(name, scope) else UNDEFINED
            else: binding = environment.get(name, UNDEFINED)
            if binding != frozenset({code}): diagnostics.add((key, identity, name, 'undefined or incompatible variable'))
            return unknown, environment
        if op == 'set':
            environment = copied(environment); environment[node['value']['v']] = frozenset({arguments[0][0]})
            require(len(environment) <= MAX_VARIABLES, 'function flow variable budget exceeded')
            return (code, arguments[0][1], None), environment
        if op == 'isdefined':
            name = node['value']['v']
            if name in semantics.SYSTEM: return (4, semantics.available(name, scope), None), environment
            binding = environment.get(name, UNDEFINED)
            truth = False if binding == UNDEFINED else True if None not in binding else None
            return (4, truth, (name, True)), environment
        if op == 'not':
            arg = arguments[0]; predicate = (arg[2][0], not arg[2][1]) if arg[2] else None
            return (4, None if arg[1] is None else not arg[1], predicate), environment
        if op in ('and', 'or'):
            truths = [arg[1] for arg in arguments]
            truth = (False if False in truths else True if truths == [True, True] else None) if op == 'and' else (True if True in truths else False if truths == [False, False] else None)
            return (4, truth, None), environment
        if op == 'passthrough': return arguments[0], environment
        return unknown, environment

    # Native compilation follows both control branches before evaluation. A
    # never-selected call must still have a compilable source; scope-dependent
    # getters remain deferred because their availability depends on execution.
    edges = {}; pending = [entry]
    while pending:
        key = pending.pop()
        if key in edges: continue
        nodes = prepare(key); live = set(); work = [functions[key]['model']['output']]; targets = []
        while work:
            identity = work.pop()
            if identity in live: continue
            live.add(identity); node = nodes[identity]
            work.extend(source for source in node['inputs'] if source is not None)
            if node['op'] == 'instance': targets.append(functions[key]['calls'][identity]['body'])
        edges[key] = targets; pending.extend(targets)
    depths = {}; expanded = {}
    for key in semantics.proc.order(edges, edges):
        depths[key] = max((1 + depths[target] for target in edges[key]), default=0)
        expanded[key] = len(checked[key]) + sum(expanded[target] for target in edges[key])
        require(depths[key] <= 8 and expanded[key] <= 4096, 'function flow compile expansion exceeds native limits')
    # A generator trampoline avoids Python recursion on 4,096-node chains and
    # keeps argument evaluation in the native left-to-right order.
    stack = [evaluate(entry, functions[entry]['model']['output'], initial, 0)]
    result = None
    while stack:
        try:
            request = stack[-1].send(result); result = None
            stack.append(evaluate(*request))
        except StopIteration as finished:
            stack.pop(); result = finished.value
    _, environment = result
    ordered = sorted(diagnostics, key=lambda item: (repr(item[0]), item[1], item[2], item[3]))
    return {'variable_flow_proven': not ordered, 'diagnostics': [dict(body=key, node=identity, name=name, reason=reason) for key, identity, name, reason in ordered],
            'final_variables': {name: {'types': sorted(code for code in binding if code is not None), 'may_be_undefined': None in binding} for name, binding in sorted(environment.items())},
            'body_count': len(checked), 'call_visits': calls, 'node_visits': visits, 'environment_cells_copied': cells,
            'has_unbounded_loop': unbounded, 'numeric_values_qualified': False, 'engine_admission_complete': False}
