"""Resolve Material references only within admitted immutable package snapshots.

Resolution does not grant native/file access. Full value semantics, runtime
handoff and whole-job budgets remain required for engine execution.
"""
import copy

from .material_container import require
from . import material_procedural as proc
from .material_graphs import BASE_TYPES, VALUE_TYPES

MAX_CALL_DEPTH = 8
MAX_EXPANDED_FUNCTION_NODES = 4096
MAX_EXPANDED_IMAGE_NODES = 16384
VALUE_CODES = {value:code for code,value in VALUE_TYPES.items()}
FIXED_TYPES = {
    4: 'const_bool get_bool and or not eq noteq gt gteq lr lreq isdefined',
    16384: 'const_string get_string',
    16: 'get_integer1 const_int1 toint1 iswizzle1',
    32: 'get_integer2 const_int2 toint2 iswizzle2 ivector2',
    64: 'get_integer3 const_int3 toint3 iswizzle3 ivector3',
    128: 'get_integer4 const_int4 toint4 iswizzle4 ivector4',
    256: 'get_float1 const_float1 tofloat swizzle1 samplelum atan2 dot',
    512: 'get_float2 const_float2 tofloat2 swizzle2 vector2 cartesian',
    1024: 'get_float3 const_float3 tofloat3 swizzle3 vector3',
    2048: 'get_float4 const_float4 tofloat4 swizzle4 vector4 samplecol',
}
FIXED_TYPES = {name:code for code,names in FIXED_TYPES.items() for name in names.split()}


def node_types(model, calls):
    """Pinned native type inference; this is not full operand/scope validation."""
    nodes={node['id']:node for node in model['nodes']}
    topology=proc.order(nodes,{key:node['inputs'] for key,node in nodes.items()});types={}
    for identity in topology:
        node=nodes[identity];op=node['op'];inputs=[types.get(source,256) for source in node['inputs']]
        if identity in calls:inferred=calls[identity]['output_type']
        elif op in FIXED_TYPES:inferred=FIXED_TYPES[op]
        elif op in ('ifelse','sequence'):inferred=inputs[1]
        elif op=='while':inferred=inputs[2]
        elif op=='set':inferred=inputs[0]
        elif 'value' in node:inferred=VALUE_CODES[node['value']['t']]
        else:inferred=inputs[0] if inputs else 256
        types[identity]=node['type_code'] or inferred
    return types


def inspect(container_profile, resource_profile, graph_profile):
    packages=resource_profile['packages'];graphs=graph_profile['graphs'];procedural=graph_profile['procedural']
    bodies=procedural['functions'];owners={};standalone={};function_calls={};image_calls={};resource_refs=[];previews=[]

    def package_target(owner, dependency):
        if dependency is None:return owner
        identity=proc.integer(dependency,0,2**64-1) if type(dependency) is str else dependency
        require(identity in packages[owner]['dependencies'],'reference names an undeclared package dependency')
        target=packages[owner]['dependencies'][identity]['member']
        require(target in packages,'reference package is not admitted')
        return target

    def graph_target(owner, ref, function):
        package=package_target(owner,ref.get('dependency'));path=ref.get('path',ref.get('graph'))
        key=(package,path)
        if key not in graphs and function:
            # Native function calls accept a unique leaf name. Image instance
            # parsing requires the exact saved path before evaluation starts.
            candidates=[k for k,g in graphs.items() if k[0]==package and g['name']==path]
            require(len(candidates)==1,'function graph reference is missing or ambiguous');key=candidates[0]
        require(key in graphs,'graph reference is missing from the admitted package')
        require(('function' in graphs[key])==function,'graph reference has the wrong graph kind')
        return key

    # Each embedded body has exactly one package graph owner. This includes
    # functions in node base parameters and in FX-Map parameters.
    indices={path:{id(element):i for i,element in enumerate(parsed['elements'])} for path,parsed in container_profile['xml'].items()}
    for key,graph in graphs.items():
        path,name=key;root=packages[path]['graphs'][name]['element'];pending=[root]
        while pending:
            element=pending.pop();identity=(path,indices[path][id(element)])
            if element['tag']=='dynamicValue':
                require(identity not in owners,'procedural body has ambiguous ownership');owners[identity]=key
                if 'function' in graph:
                    require(key not in standalone,'standalone function has multiple bodies');standalone[key]=identity
            pending.extend(child for child in element['content'] if 'tag' in child)
    require(set(owners)==set(bodies),'procedural body is outside an admitted graph')

    function_edges={key:[] for key in standalone};image_edges={key:[] for key,g in graphs.items() if 'function' not in g}
    for body_key,body in bodies.items():
        owner=owners[body_key];calls=[]
        for ref in body['references']:
            target=graph_target(owner[0],ref,True);callee=graphs[target]
            ports=[{'identifier':p['name'],'type_code':p['type']} for p in callee['inputs'].values()]
            require(ref['inputs']==ports,'function instance interface would be reordered, added or dropped')
            require(target in standalone,'function target lacks its unique body')
            calls.append({'node':ref['node'],'target':target,'body':standalone[target],'inputs':ports,
                          'default_specs':{p['name']:copy.deepcopy(p) for p in callee['inputs'].values()}})
            if owner in function_edges:function_edges[owner].append(target)
        function_calls[body_key]=calls
    function_order=proc.order(function_edges,function_edges)

    # Resolve function graphs bottom-up. No bodies are recursively copied into
    # callers: expansion counts saturate before materializing a call tree.
    resolved_bodies={};function_depth={};function_size={};function_types={}
    def resolve_body(body_key):
        if body_key in resolved_bodies:return resolved_bodies[body_key]
        report=bodies[body_key];model=copy.deepcopy(report['model']);nodes={n['id']:n for n in model['nodes']}
        calls={};expanded=report['nodes'];depth=0;external=False
        reference_by_node={r['node']:r for r in report['references']}
        for call in function_calls[body_key]:
            target=call['target'];require(target in function_types,'function resolution order is incomplete')
            code=function_types[target];require(code in proc.TYPE_CODES,'called function has no typed result');node=nodes[call['node']]
            require(node['type_code']==code,'cached function result type would change on native resolution')
            expanded=min(MAX_EXPANDED_FUNCTION_NODES+1,expanded+function_size[target]);depth=max(depth,1+function_depth[target])
            external |= target[0]!=body_key[0] or resolved_bodies[standalone[target]]['requires_external_handoff']
            # The native serialized instance retains the literal reference name,
            # while defaults and resolved bodies are runtime-only fields.
            ref=reference_by_node[call['node']]
            dependency=package_target(body_key[0],ref['dependency'])
            package='' if dependency==body_key[0] else packages[body_key[0]]['dependencies'][int(ref['dependency'])]['reference']
            node.pop('reference');node.pop('interface')
            node['instance']={'package':package,'graph':ref['graph'],'inputs':copy.deepcopy(call['inputs']),
                              'outputs':[{'identifier':'output','type_code':code}]}
            calls[call['node']]={**call,'output_type':code}
        require(depth<=MAX_CALL_DEPTH,'function call depth exceeds the native limit')
        require(expanded<=MAX_EXPANDED_FUNCTION_NODES,'expanded function nodes exceed the native limit')
        types=node_types(model,calls)
        for identity,call in calls.items():
            node=nodes[identity]
            for port,source in zip(call['inputs'],node['inputs']):
                require(source is None or types[source]==port['type_code'],'function call input type differs from its source interface')
        output=model['output'];result_type=types.get(output)
        result={'model':model,'calls':calls,'types':types,'output_type':result_type,'expanded_nodes':expanded,
                'call_depth':depth,'requires_external_handoff':external,'engine_admission_complete':False}
        resolved_bodies[body_key]=result;return result
    for key in function_order:
        resolved=resolve_body(standalone[key])
        require(resolved['output_type'] is None or resolved['output_type']==graphs[key]['function_type'],'standalone declared/result types disagree')
        function_depth[key]=resolved['call_depth'];function_size[key]=resolved['expanded_nodes'];function_types[key]=resolved['output_type']
    for key in bodies:resolve_body(key)

    for key,graph in graphs.items():
        path,name=key
        for label,resource_name in graph.get('previews',{}).items():
            require(resource_name in packages[path]['resources'],'preview names a missing resource')
            previews.append({'graph':key,'input':label,'resource':(path,resource_name)})
        calls=[]
        for node_id,node in graph['nodes'].items():
            for ref in node.get('resources',[]):
                target=package_target(path,ref['dependency'])
                # Native bitmap/SVG parsing ignores the dependency component.
                # Admitting a different package here would bind unrelated bytes.
                require(target==path,'cross-package bitmap references need an explicit managed conversion')
                matches=[label for label,r in packages[path]['resources'].items() if ((r['folder']+'/') if r['folder'] else '')+label==ref['path']]
                require(len(matches)==1,'bitmap reference has no exact admitted resource path')
                resource_refs.append({'graph':key,'node':node_id,'resource':(path,matches[0])})
            if node['definition']!='graph_instance':continue
            target=graph_target(path,node['reference'],False);callee=graphs[target]
            require(callee['outputs'],'image instance target has no outputs')
            expected_outputs=[callee['outputs'][n['bridge']]['name'] for n in callee['nodes'].values() if n['definition']=='output']
            require(list(node['outputs'].values())==expected_outputs,'image instance output interface differs from its source')
            declared={p['name']:p for p in callee['inputs'].values()};connected={callee['inputs'][n['bridge']]['name']:callee['inputs'][n['bridge']] for n in callee['nodes'].values() if n['definition'] in ('input_color','input_grayscale','input_value')}
            output_types={p['name']:p['type'] for p in callee['outputs'].values()}
            require(all(node['output_types'][pid]==output_types[label] for pid,label in node['outputs'].items()),'cached image output types differ from source declarations')
            require(set(node['input_values'])<=set(connected),'image instance has undeclared typed inputs')
            require(all(node['input_values'][p]==connected[p]['type'] for p in node['input_values']),'image instance typed input metadata differs')
            allowed=set(BASE_TYPES)|{name for name,p in declared.items() if not p['connectable']}
            require(set(node['parameters'])<=allowed,'image instance override has no exposed source parameter')
            for wire in graph['connections']:
                if wire['to']==node['native_id']:require(wire['toPort'] in connected,'image instance wire has no declared source input')
            calls.append({'node':node_id,'target':target,'inputs':connected,'outputs':callee['outputs'],
                          'overrides':{k:v for k,v in node['parameters'].items() if k not in BASE_TYPES},
                          'requires_external_handoff':target[0]!=path})
            image_edges[key].append(target)
        image_calls[key]=calls
    image_order=proc.order(image_edges,image_edges);image_depth={};image_size={}
    for key in image_order:
        targets=image_edges[key];depth=max((1+image_depth[t] for t in targets),default=0)
        count=len(graphs[key]['nodes'])
        for target in targets:count=min(MAX_EXPANDED_IMAGE_NODES+1,count+image_size[target])
        require(depth<=MAX_CALL_DEPTH,'image graph call depth exceeds the native limit')
        require(count<=MAX_EXPANDED_IMAGE_NODES,'expanded image graph nodes exceed the budget')
        image_depth[key]=depth;image_size[key]=count
    return {'functions':resolved_bodies,'function_graph_types':function_types,'image_calls':image_calls,
            'image_call_depth':image_depth,'expanded_image_nodes':image_size,'resources':resource_refs,'previews':previews,
            'requires_external_handoff':any(r['requires_external_handoff'] for r in resolved_bodies.values()) or
                any(c['requires_external_handoff'] for calls in image_calls.values() for c in calls),
            'engine_admission_complete':False}
