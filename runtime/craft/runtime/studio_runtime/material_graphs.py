"""Outer SBS schemas and exact graph topology before complete execution admission.

No filesystem dependency resolution or native execution occurs here. Interface
resolution, cross-graph types, full native values and job work remain separate.
"""
import re
import math

from .material_container import require
from .material_resources import children, fields, scalar, uid, identifier
from . import material_procedural as proc
from .material_node_catalog import FILTERS, DEFINITIONS
from .material_values import color, exposed_default

MAX_GRAPHS = 256
MAX_NODES = 16384
MAX_PORTS = 4096
MAX_ARRAY_CELLS = 4096
BASE_TYPES = {'outputsize':'int2','format':'int','randomseed':'int','tiling':'int','pixelsize':'float2','pixelratio':'int'}
VALUE_TYPES = {4:'bool',16:'int',32:'int2',64:'int3',128:'int4',256:'float',512:'float2',1024:'float3',2048:'float4',16384:'text'}
ATTRIBUTES = {'label','category','description','author','authorURL','tags','group','userdata'}
USAGES = ('baseColor normal roughness metallic height ambientOcclusion emissive opacity specular any diffuse glossiness specularLevel specularEdgeColor anisotropyLevel anisotropyAngle IOR scattering scatteringColor scatteringDistance scatteringDistanceScale transmissive translucency absorptionColor absorptionDistance coatOpacity coatColor coatRoughness coatSpecularLevel coatNormal coatIOR sheenOpacity sheenColor sheenRoughness reflection displacement ambient mask blendingmask bump user0 user1 user2 user3 user4 user5 user6 user7').split()


def parameter_list(element):
    result = {}
    for entry in proc.entries(element,'parameter'):
        record = fields(entry,('name','relativeTo','paramValue'))
        name = scalar(record['name']); require(name not in result,'duplicate node parameter')
        mode = scalar(record['relativeTo']); require(mode in ('0','1','2'),'unknown parameter inheritance')
        body = proc.single(record['paramValue'])
        value = {'t':'function','v':proc.function(body)} if body['tag']=='dynamicValue' else proc.constant(body)
        result[name] = {'mode':mode,'value':value}
    return result


def base_parameters(parameters, graph=False):
    result = {}
    for name,record in parameters.items():
        if name not in BASE_TYPES: continue
        require(not graph or name in ('randomseed','pixelratio','tiling'),'graph base field would be ignored')
        value = record['value']; mode = record['mode']
        if graph:
            require(value['t']!='function','dynamic graph base field would be ignored')
            if name=='randomseed':require(mode=='0','graph seed inheritance would be ignored')
        if value['t']!='function':
            require(value['t']==BASE_TYPES[name],'base parameter native type differs')
            v=value['v']
            if name=='outputsize':require(all(-12<=n<=13 for n in v),'node size would be clamped')
            if name=='format':require(0<=v<=3,'unknown output format')
            if name=='tiling':require(0<=v<=3,'unknown tiling mode')
            if name=='pixelratio':require(v in (0,1),'unknown pixel ratio')
            if name=='pixelsize':require(all(0<n<=8192 for n in v),'pixel size exceeds native range')
        result[name]=record
    return result


def attributes(element, function=False):
    record=fields(element,(),ATTRIBUTES | ({'physicalSize'} if not function else set()))
    result={key:proc.text_value(value) for key,value in record.items() if key!='physicalSize'}
    if 'physicalSize' in record:
        size=proc.vector(scalar(record['physicalSize']),3);require(min(size)>=0,'negative physical size')
        result['physicalSize']=size
    return result


def usage(element):
    values=proc.entries(element,'usage');require(len(values)==1,'usage count would be truncated')
    record=fields(values[0],('components','name'));require(scalar(record['components'])=='RGBA','usage components would be ignored')
    name=scalar(record['name']);require(name in USAGES,'usage name would be recovered')
    return name


def options(element):
    result={}
    for entry in proc.entries(element,'option'):
        record=fields(entry,('name','value'));name=proc.text_value(record['name'])
        require(name not in result,'duplicate option');result[name]=proc.text_value(record['value'])
    return result


def widget(element, value, connectable):
    record=fields(element,('name','options'));name=scalar(record['name']);opts=options(record['options'])
    if connectable:
        require(name=='' and not opts,'connectable input widget would be ignored');return {'name':name,'options':opts}
    require(name in ('slider','inputfield','color','dropdownlist','buttons','text'),'unknown exposed editor')
    require(set(opts)<= {'min','max','clamp','step','valueInterpretation','parameters'} and {'min','max','clamp'}<=set(opts),'exposed widget options missing or ignored')
    require(proc.f32(opts['min'])<=proc.f32(opts['max']),'exposed range is reversed')
    require(opts['clamp'] in ('0','1'),'exposed clamp would be recovered')
    if 'step' in opts:require(proc.f32(opts['step'])>0,'exposed step would be discarded')
    if 'valueInterpretation' in opts:require(opts['valueInterpretation']=='color' and value['t']=='float4','ignored color interpretation')
    if 'parameters' in opts:
        require(name=='dropdownlist' and value['t']=='int','dropdown requires integer value')
        parts=opts['parameters'].split(';');require(len(parts)>=3 and len(parts)%2==1,'invalid dropdown list')
        require(proc.integer(parts[0],0,2**31-1)==value['v'],'dropdown current value differs')
        require(all(proc.integer(parts[i],0,2**31-1)==(i-1)//2 for i in range(1,len(parts),2)),'dropdown indices would be discarded')
        require(value['v']<(len(parts)-1)//2,'dropdown value is outside choices')
    elif name=='dropdownlist':require(False,'dropdown without choices would be recovered')
    if value['t']=='bool':allowed={'buttons'}
    elif value['t']=='text':allowed={'text'}
    elif name=='dropdownlist':allowed={'dropdownlist'}
    elif 'valueInterpretation' in opts:allowed={'color','inputfield'}
    else:allowed={'slider','inputfield'} | ({'color'} if value['t'] in ('float3','float4') else set())
    require(name in allowed,'editor would be discarded for its value type')
    return {'name':name,'options':opts}


def inputs(element, identities):
    result={};names=set()
    for entry in proc.entries(element,'paraminput'):
        require(len(result)<MAX_PORTS,'graph input budget exceeded')
        record=fields(entry,('identifier','uid','type','defaultValue','defaultWidget'),('isConnectable','attributes','group','usages'))
        identity=claim(record['uid'],identities);name=identifier(scalar(record['identifier']))
        require(name not in names,'duplicate graph input name');names.add(name)
        code=proc.integer(scalar(record['type']),0,2**32-1);require(code in proc.TYPE_CODES|{1,2},'unknown graph input type')
        connectable='isConnectable' in record
        if connectable:require(scalar(record['isConnectable'])=='1','noncanonical input connectability')
        require(connectable or code not in (1,2),'image input must be explicitly connectable')
        value=proc.constant(proc.single(record['defaultValue']))
        expected='float4' if code in (1,2) else VALUE_TYPES[code]
        require(value['t']==expected,'graph input default would be converted')
        w=widget(record['defaultWidget'],value,connectable)
        usage_name=None
        if connectable:
            require('attributes' not in record and 'group' not in record and 'usages' in record,'connectable metadata would be ignored')
            usage_name=usage(record['usages'])
        else:
            require('usages' not in record and 'attributes' in record,'exposed metadata is missing or ignored')
            attrs=fields(record['attributes'],('label','description'))
            for item in attrs.values():proc.text_value(item)
            if 'group' in record:proc.text_value(record['group'])
        result[identity]={'name':name,'type':code,'connectable':connectable,'value':value,'widget':w,'usage':usage_name}
        exposed_default(result[identity])  # Refuse nonfinite displayed-color conversion before native parsing.
    return result


def claim(element, identities):
    identity=uid(element);require(identity not in identities,'duplicate graph UID');identities.add(identity);return identity


def outputs(element, identities):
    result={};names=set()
    for entry in proc.entries(element,'graphoutput'):
        require(len(result)<MAX_PORTS,'graph output budget exceeded')
        record=fields(entry,('identifier','uid','attributes','usages','group','channels'))
        identity=claim(record['uid'],identities);name=identifier(scalar(record['identifier']))
        require(name not in names,'duplicate graph output name');names.add(name)
        attrs=fields(record['attributes'],('label',));label=proc.text_value(attrs['label'])
        # Maintained Dobe reader restores custom labels. Empty serialized labels
        # still require explicit conversion to the native identifier fallback.
        require(bool(label),'empty output label would be replaced by its identifier')
        require(scalar(record['group'])=='Material','output group would be discarded')
        code=proc.integer(scalar(record['channels']),0,2**32-1);require(code in proc.TYPE_CODES|{1,2},'unknown output type')
        result[identity]={'name':name,'label':label,'type':code,'usage':usage(record['usages'])}
    return result


def reference(text):
    match=re.fullmatch(r'pkg:///([^?]+)(?:\?dependency=([0-9]+))?',text)
    require(match is not None,'reference requires an admitted package identity')
    path=match[1]
    for part in path.split('/'):identifier(part)
    dependency=proc.integer(match[2],0,2**64-1) if match[2] is not None else None
    return {'path':path,'dependency':dependency}


def arrays(element, definition, identities):
    result={}
    for entry in proc.entries(element,'paramsArray'):
        record=fields(entry,('name','uid','paramsArrayCells'));name=scalar(record['name']);claim(record['uid'],identities)
        require(name not in result,'duplicate parameter array')
        require((definition=='curve' and name=='curveluminance') or (definition=='gradient_map' and name=='gradientrgba'),'array would be ignored or converted')
        cells=proc.entries(record['paramsArrayCells'],'paramsArrayCell');require(0<len(cells)<=MAX_ARRAY_CELLS,'array would be empty or truncated')
        values=[];last=(-float('inf'),-1)
        for cell in cells:
            cell=fields(cell,('uid','parameters'));claim(cell['uid'],identities);params=parameter_list(cell['parameters'])
            expected={'position':'float2','left':'float2','right':'float2','isLeftBroken':'bool','isRightBroken':'bool','isLocked':'bool'} if definition=='curve' else {'position':'float','midpoint':'float','value':'float4'}
            require(set(params)==set(expected),'array cell has missing or ignored parameters')
            require(all(params[k]['mode']=='0' and params[k]['value']['t']==v for k,v in expected.items()),'array cell has an ignored type or inheritance')
            v={k:r['value']['v'] for k,r in params.items()}
            if definition=='curve':
                require(v['isLeftBroken'] and v['isRightBroken'] and not v['isLocked'],'curve flags would be overwritten');pos=v['position'][0]
            else:pos=v['position']
            ordered=(pos,math.copysign(1,pos))
            require(ordered>=last,'array ordering would change on native import');last=ordered;values.append(v)
        result[name]=values
    return result


def filter_parameters(name, parameters):
    contract=FILTERS[name];definition=contract['definition'];known=DEFINITIONS[definition]['parameters']
    extra={'bitmap':{'bitmapresourcepath':'text'},'svg':{'vectorresourcepath':'text'},'grayscaleconversion':{'channelsweights':'float4'}}.get(name,{})
    require(set(parameters)<=set(BASE_TYPES)|set(contract['parameters'])|set(extra),'filter has ignored or unsupported parameters')
    base_parameters(parameters)
    refs=[]
    for key,record in parameters.items():
        if key in BASE_TYPES:continue
        require(record['mode']=='0','filter parameter inheritance would be ignored');value=record['value']
        if key in extra:
            require(value['t']==extra[key],'special parameter requires explicit native value type')
            if key.endswith('resourcepath'):refs.append(reference(value['v']))
            continue
        spec=known[contract['parameters'][key]];kind=spec['default']['t']
        if value['t']=='function':continue
        require(kind!='function','processor body must be a function')
        require(value['t']==('int' if kind=='enum' else 'float4' if kind=='color' else kind),'filter value would undergo implicit type conversion')
        if kind=='enum':require(0<=value['v']<spec['options'],'enum value would be clamped')
        if kind=='color':color(value)
    return refs


def graph(element):
    function=element['tag']=='function';require(function or element['tag']=='graph','unexpected graph element')
    required=('identifier','uid','attributes','paraminputs','type','paramValue') if function else ('identifier','uid','graphtype','attributes','paraminputs','graphOutputs','compNodes','baseParameters','GUIObjects','options','root')
    root=fields(element,required);identities=set();claim(root['uid'],identities)
    name=identifier(scalar(root['identifier']));attrs=attributes(root['attributes'],function)
    ports=inputs(root['paraminputs'],identities)
    result={'name':name,'attributes':attrs,'inputs':ports,'nodes':{},'connections':[],'references':[],'engine_admission_complete':False}
    if function:
        require(all(not port['connectable'] for port in ports.values()),'standalone function connectable input requires further native qualification')
        code=proc.integer(scalar(root['type']),0,2**32-1);require(code in proc.TYPE_CODES,'standalone function type requires explicit conversion')
        body=proc.single(root['paramValue']);result['function']=proc.function(body);result['function_type']=code
        return result
    require(scalar(root['graphtype'])=='material','graph type would be ignored')
    outs=outputs(root['graphOutputs'],identities);result['outputs']=outs
    base=parameter_list(root['baseParameters']);require(set(base)<=set(BASE_TYPES),'unknown graph base parameter');result['base']=base_parameters(base,True)
    proc.annotations(root['GUIObjects']);opts=options(root['options']);require('defaultParentSize' in opts,'missing explicit parent size')
    size=re.fullmatch(r'([0-9]+)x([0-9]+)',opts.pop('defaultParentSize'));require(size is not None,'invalid parent size')
    dimensions=[proc.integer(v,4,13) for v in size.groups()];result['size']=dimensions
    previews={};linear=set();names={port['name'] for port in ports.values() if port['connectable'] and port['type'] in (1,2)}
    for key,value in opts.items():
        if key.startswith('materialcraft.previewImage.'):
            port=key[len('materialcraft.previewImage.'):];require(port in names,'preview input is absent or not image typed')
            previews[port]=identifier(value)
        elif key.startswith('materialcraft.previewLinear.'):
            port=key[len('materialcraft.previewLinear.'):];require(port in names and value=='1','invalid linear preview option');linear.add(port)
        else:require(False,'unknown graph option would be dropped')
    require(linear<=previews.keys(),'linear preview lacks an image binding');result['previews']=previews
    rootouts=fields(root['root'],('rootOutputs',));references=[]
    for entry in proc.entries(rootouts['rootOutputs'],'rootOutput'):
        record=fields(entry,('output','format','usertag'));identity=uid(record['output'])
        require(identity in outs and identity not in references,'root output missing or duplicate');references.append(identity)
        require(scalar(record['format'])=='0' and scalar(record['usertag'])=='','root output fields would be ignored')
    require(set(references)==set(outs),'root output inventory differs')
    nodes={};input_bridges=set();output_bridges=set();pending=[]
    for entry in proc.entries(root['compNodes'],'compNode'):
        require(len(nodes)<MAX_NODES,'graph node budget exceeded')
        record=fields(entry,('uid','GUILayout','compImplementation'),('compOutputs','connections','inputValues'))
        identity=claim(record['uid'],identities);pos=proc.position(record['GUILayout'])
        implementation=proc.single(record['compImplementation']);kind=implementation['tag'];output_ports={};input_ports={};typed={}
        if 'compOutputs' in record:
            for entry in proc.entries(record['compOutputs'],'compOutput'):
                require(len(output_ports)<MAX_PORTS,'node output budget exceeded')
                port=fields(entry,('uid','comptype'));pid=claim(port['uid'],identities)
                code=proc.integer(scalar(port['comptype']),0,2**32-1);require(code in proc.TYPE_CODES|{1,2},'invalid node output type');output_ports[pid]=code
        if 'inputValues' in record:
            for entry in proc.entries(record['inputValues'],'compInputValue'):
                require(len(typed)<64,'typed input list would be truncated')
                port=fields(entry,('identifier','type'));label=identifier(scalar(port['identifier']))
                require(label not in typed,'duplicate typed input');code=proc.integer(scalar(port['type']),0,2**32-1)
                require(code in proc.TYPE_CODES,'invalid typed input');typed[label]=code
        node={'position':pos,'outputs':{},'inputs':{},'input_values':typed,'native_id':len(nodes)+1,'parameters':{},'kind':kind}
        if kind=='compOutputBridge':
            impl=fields(implementation,('output',));target=uid(impl['output'])
            require(target in outs and target not in output_bridges,'output bridge is missing or duplicated');output_bridges.add(target)
            require(not output_ports and not typed,'output bridge has ignored ports');definition='output';input_ports={'inputNodeOutput':'input'};node['bridge']=target
        elif kind=='compInputBridge':
            impl=fields(implementation,('entry','parameters'));target=uid(impl['entry'])
            require(target in ports and ports[target]['connectable'] and target not in input_bridges,'input bridge is missing, duplicate or exposed-only');input_bridges.add(target)
            code=ports[target]['type'];definition='input_color' if code==1 else 'input_grayscale' if code==2 else 'input_value'
            params=parameter_list(impl['parameters']);require(set(params)<=set(BASE_TYPES),'ignored input bridge parameter');base_parameters(params);node['parameters']=params;node['bridge']=target
            require(not typed and len(output_ports)==1,'input bridge ports differ from native contract')
            node['outputs']={key:'output' for key in output_ports}
        elif kind=='compFilter':
            impl=fields(implementation,('filter','parameters'),('paramsArrays','paramsGraphs'))
            filter_name=scalar(impl['filter']);require(filter_name in FILTERS,'unqualified filter');definition=FILTERS[filter_name]['definition']
            params=parameter_list(impl['parameters']);node['parameters']=params;node['resources']=filter_parameters(filter_name,params)
            input_ports=dict(FILTERS[filter_name]['inputs']);require(len(output_ports)==1,'filter outputs would be aliased or missing')
            node['outputs']={key:'output' for key in output_ports}
            if 'paramsArrays' in impl:node['arrays']=arrays(impl['paramsArrays'],definition,identities)
            if 'paramsGraphs' in impl:
                require(definition=='fx_map','pattern graph would be ignored');body=proc.single(impl['paramsGraphs']);node['pattern']=proc.pattern(body)
        elif kind=='compInstance':
            impl=fields(implementation,('path','parameters','outputBridgings'));definition='graph_instance'
            ref=reference(scalar(impl['path']));node['reference']=ref;result['references'].append(ref)
            params=parameter_list(impl['parameters']);base_parameters(params)
            require(all(r['mode']=='0' for k,r in params.items() if k not in BASE_TYPES),'instance parameter inheritance would be ignored');node['parameters']=params
            names=set()
            for entry in proc.entries(impl['outputBridgings'],'outputBridging'):
                port=fields(entry,('uid','identifier'));pid=uid(port['uid']);label=identifier(scalar(port['identifier']))
                require(pid in output_ports and pid not in node['outputs'] and label not in names,'instance output bridge differs or duplicates')
                names.add(label);node['outputs'][pid]=label
            require(set(node['outputs'])==set(output_ports),'instance outputs lack bridges')
        else:require(False,'unsupported node implementation')
        node['definition']=definition;node['output_types']=dict(output_ports)
        for label in typed:
            require(label not in input_ports and label not in input_ports.values(),'typed input shadows a native connector');input_ports[label]=label
        node['inputs']=input_ports
        if 'connections' in record:
            seen=set()
            for entry in proc.entries(record['connections'],'connection'):
                wire=fields(entry,('identifier','connRef','connRefOutput'));label=identifier(scalar(wire['identifier']));port=input_ports.get(label)
                if port is None and definition in ('pixel_processor','value_processor','fx_map'):
                    index=0 if label=='input' else proc.integer(label[6:],0,255) if label.startswith('input:') else None
                    if index is not None:port=('pattern' if definition=='fx_map' else 'input')+str(index)
                if port is None and definition=='graph_instance':port=label
                require(port is not None and port not in seen,'connection input is missing or duplicates a native port');seen.add(port)
                pending.append({'from':uid(wire['connRef']),'output':uid(wire['connRefOutput']),'to':identity,'to_port':port})
        nodes[identity]=node
    require(output_bridges==set(outs),'graph output has no node bridge')
    require(input_bridges=={key for key,p in ports.items() if p['connectable']},'connectable graph input has no node bridge')
    edges={key:[] for key in nodes};wires=[]
    for wire in pending:
        source=nodes.get(wire['from']);require(source is not None and wire['output'] in source['outputs'],'wire source/output would be recovered or dropped')
        edges[wire['to']].append(wire['from'])
        wires.append({'from':source['native_id'],'fromPort':source['outputs'][wire['output']], 'to':nodes[wire['to']]['native_id'],'toPort':wire['to_port']})
    proc.order(nodes,edges);result['nodes']=nodes;result['connections']=wires;return result


def inspect(profile, resource_profile):
    # Resource/package admission supplies unique graph identities and owned XML.
    records=[(path,name,item) for path,pkg in resource_profile['packages'].items() for name,item in pkg['graphs'].items()]
    require(len(records)<=MAX_GRAPHS,'aggregate graph budget exceeded')
    count=sum(e['tag']=='compNode' for parsed in profile['xml'].values() for e in parsed['elements'])
    require(count<=MAX_NODES,'aggregate image node budget exceeded')
    procedural=proc.inspect(profile);result={}
    for path,name,item in records:result[(path,name)]=graph(item['element'])
    return {'graphs':result,'procedural':procedural,'image_nodes':count,'engine_admission_complete':False}


def check_native(report, package, native):
    """Compare graph identities, definitions, explicit topology and saved positions.

This does not compare all parameter values and is not preservation proof.
"""
    require(type(native) is dict and type(native.get('graphs')) is list,'native graph inventory is malformed')
    expected={name:r for (path,name),r in report['graphs'].items() if path==package};seen=set()
    for observed in native['graphs']:
        require(type(observed) is dict and type(observed.get('name')) is str,'native graph identity is malformed')
        folder=observed.get('folder','');require(type(folder) is str,'native graph folder is malformed');name=(folder+'/' if folder else '')+observed['name']
        require(name in expected and name not in seen,'native graph missing or duplicate');seen.add(name);graph_=expected[name]
        if 'function' in graph_:
            function=graph_['function']
            require(not function['requires_call_resolution'],'standalone function comparison requires resolved calls')
            require(observed.get('function')==function['model'] and observed.get('functionType')==graph_['function_type'],'standalone function model differs');continue
        require(observed.get('size')==graph_['size'],'native parent size differs')
        nodes=observed.get('nodes');require(type(nodes) is list and len(nodes)==len(graph_['nodes']),'native node count differs')
        for expected_node,observed_node in zip(graph_['nodes'].values(),nodes):
            require(type(observed_node) is dict and type(observed_node.get('id')) is int and observed_node.get('id')==expected_node['native_id'] and observed_node.get('def')==expected_node['definition'],'native node identity/definition differs')
            pos=[proc.f32(str(value-offset)) for value,offset in zip(expected_node['position'],(50,40))]
            require(observed_node.get('pos')==pos,'native node position differs')
            if expected_node['definition']=='output':
                output=graph_['outputs'][expected_node['bridge']]
                expected_label=output['label'] if output['label']!=output['name'] else ''
                require(observed_node.get('label','')==expected_label,'native output label differs')
        wires=observed.get('connections');require(type(wires) is list,'native wires are malformed')
        require(all(type(w) is dict and set(w)=={'from','to','fromPort','toPort'} and type(w['from']) is int and type(w['to']) is int and type(w['fromPort']) is str and type(w['toPort']) is str for w in wires),'native wire record is malformed')
        require(wires==graph_['connections'],'native wire topology differs')
    require(seen==set(expected),'native graph inventory is incomplete')
    return {'native_outer_graph_topology_equal':True,'engine_admission_complete':False}
