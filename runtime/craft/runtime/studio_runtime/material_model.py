"""Predict the complete serialized native package from admitted immutable SBS.

This composes schema, reference, literal and base reports. It compares editable
state, not cooked output, resource bytes, numeric safety or execution budgets.
"""
from collections import deque
import copy
import math

from .material_container import require
from .material_resources import children, scalar
from . import material_procedural as proc, material_base as base, material_values as values
from .material_graphs import BASE_TYPES
from .material_node_catalog import FILTERS, DEFINITIONS

VALUE_TYPES = dict(zip((4,16,32,64,128,256,512,1024,2048,16384),
                      ('Boolean','Integer','Integer2','Integer3','Integer4','Float','Float2','Float3','Float4','String')))
EDITORS = {'slider':'slider','inputfield':'input','color':'color','dropdownlist':'dropdown','buttons':'toggle','text':'text'}


def members(element):
    # Only called on fields already checked by the schema inspectors.
    return {child['tag']: child for child in children(element)}


def canvas(entries, start=1):
    result = {'frames': [], 'comments': [], 'pins': []}
    for identity, element in enumerate(entries, start):
        record = members(element); layout = members(record['GUILayout'])
        pos = proc.vector(scalar(layout['gpos']), 3)[:2]; text = proc.text_value(record['GUIName'])
        if scalar(record['type']) == 'PIN':
            result['pins'].append({'id': identity, 'name': text, 'pos': pos}); continue
        size = proc.vector(scalar(layout['size']), 2)
        if scalar(record['isFrameVisible']) == '1':
            rgba = values.color({'t':'float4', 'v':proc.vector(scalar(record['frameColor']),4)})['v']
            frame = {'id':identity, 'title':proc.text_value(record['title']),
                     'title_visible':scalar(record['isTitleVisible']) == '1', 'rect':pos+size, 'color':rgba}
            if text: frame['description'] = text
            result['frames'].append(frame)
        else: result['comments'].append({'id':identity, 'text':text, 'pos':pos, 'size':size})
    return result


def exposed(port, element):
    record = members(element); attrs = members(record['attributes']); opts = port['widget']['options']
    default = values.exposed_default(port)
    result = {'id':port['name'], 'label':proc.text_value(attrs['label']) or port['name'], 'default':default,
              'clamp':opts['clamp']=='1', 'min':proc.f32(opts['min']), 'max':proc.f32(opts['max'])}
    for key, value in [('group',proc.text_value(record['group']) if 'group' in record else ''),
                       ('description',proc.text_value(attrs['description']))]:
        if value: result[key] = value
    if 'step' in opts: result['step'] = proc.f32(opts['step'])
    if 'parameters' in opts: result['options'] = opts['parameters'].split(';')[2::2]
    natural = {'bool':'toggle', 'text':'text', 'enum':'dropdown', 'color':'color'}.get(default['t'],'slider')
    editor = EDITORS[port['widget']['name']]
    if editor != natural: result['editor'] = editor
    return result


def inspect(snapshot, resources, graphs, references):
    """Build all package models without reading paths or invoking an engine."""
    indices = {path:{id(e):index for index,e in enumerate(parsed['elements'])} for path,parsed in snapshot['xml'].items()}
    image_calls = {key:{call['node']:call for call in calls} for key,calls in references['image_calls'].items()}
    functions = {}; patterns = {}; literal = values.inspect(graphs,references)['graphs']
    def key(path, element): return (path,indices[path][id(element)])
    for identity, report in references['functions'].items():
        model = copy.deepcopy(report['model'])
        entries = graphs['procedural']['functions'][identity]['annotations_xml']
        if entries: model['annotations'] = canvas(entries)
        functions[identity] = model
    for identity, report in graphs['procedural']['patterns'].items():
        path,index = identity; element = snapshot['xml'][path]['elements'][index]; record = members(element)
        model = copy.deepcopy(report['model']); data = {}
        for entry in children(record['paramsGraphDatas']):
            cell = members(entry); parameters = {}
            for parameter in children(cell['parameters']):
                item = members(parameter); body = proc.single(item['paramValue'])
                if body['tag'] == 'dynamicValue': parameters[scalar(item['name'])] = functions[key(path,body)]
            data[int(scalar(cell['uid']))] = parameters
        for source,node in zip(children(record['paramsGraphNodes']),model['nodes']):
            for name,body in data[int(scalar(members(source)['data']))].items():
                node['parameters'][name] = {'t':'function','v':copy.deepcopy(body)}
        if report['annotations_xml']: model['annotations'] = canvas(report['annotations_xml'])
        patterns[identity] = model

    def graph_model(path, full_name, element):
        graph = graphs['graphs'][(path,full_name)]; root = members(element); attrs = graph['attributes']
        result = {'name':graph['name'], 'function':None, 'functionType':0, 'nodes':[], 'connections':copy.deepcopy(graph['connections']),
                  'frames':[], 'comments':[], 'pins':[], 'size':graph.get('size',[10,10]), 'format':'u16', 'seed':0,
                  'pixelRatio':0, 'pixelRatioMode':'relativeToInput', 'tiling':[True,True], 'tilingMode':'relativeToInput',
                  'physicalSize':copy.deepcopy(attrs.get('physicalSize',[0.,0.,0.])), 'exposed':[], 'inputs':{}, 'nextId':1,
                  'attributes':{native:attrs.get(source,'') for source,native in [('label','label'),('category','category'),
                      ('description','description'),('author','author'),('authorURL','authorUrl'),('tags','tags'),('group','group'),('userdata','userData')]}}
        folder = full_name.rpartition('/')[0]
        if folder: result['folder'] = folder
        for source,port in zip(children(root['paraminputs']),graph['inputs'].values()):
            if not port['connectable']: result['exposed'].append(exposed(port,source))
        if 'function' in graph:
            body = proc.single(root['paramValue']); model = copy.deepcopy(functions[key(path,body)])
            model.pop('annotations',None); result['function'] = model; result['functionType'] = graph['function_type']
            entries = graph['function']['annotations_xml']; result.update(canvas(entries)); result['nextId'] = 1+len(entries)
            return result
        literal_base = base.model(graph['base'])['literal']
        for field in ('seed','pixelRatio','pixelRatioMode','tiling','tilingMode'): result[field] = literal_base[field]
        if graph['previews']: result['inputImages'] = copy.deepcopy(graph['previews'])
        opts = {scalar(members(o)['name']):scalar(members(o)['value']) for o in children(root['options'])}
        linear = sorted(name[len('materialcraft.previewLinear.'):] for name in opts if name.startswith('materialcraft.previewLinear.'))
        if linear: result['inputImagesLinear'] = linear
        for source,(source_id,node) in zip(children(root['compNodes']),graph['nodes'].items()):
            position = [proc.f32(str(v-offset)) for v,offset in zip(node['position'],(50,40))]
            native = {'id':node['native_id'], 'def':node['definition'], 'pos':position, 'base':base.model(node['parameters'])['literal']}
            params = copy.deepcopy(literal[(path,full_name)]['nodes'][node['native_id']]['values']); dynamic = {}; base_functions = {}
            implementation = proc.single(members(source)['compImplementation']); record = members(implementation)
            if node['definition'] == 'output':
                output = graph['outputs'][node['bridge']]
                if output['label'] != output['name']: native['label'] = output['label']
            if 'parameters' in record:
                mapping = FILTERS[scalar(record['filter'])]['parameters'] if 'filter' in record else {}
                for parameter in children(record['parameters']):
                    fields = members(parameter); body = proc.single(fields['paramValue']); name = scalar(fields['name'])
                    if body['tag'] != 'dynamicValue': continue
                    model = copy.deepcopy(functions[key(path,body)])
                    if name in BASE_TYPES: base_functions[name] = model
                    else:
                        target = mapping.get(name,name)
                        spec = DEFINITIONS.get(node['definition'],{}).get('parameters',{}).get(target)
                        if spec is not None and spec['default']['t']=='function': params[target] = {'t':'function','v':model}
                        else: dynamic[target] = model
            if 'paramsGraphs' in record: params['pattern'] = {'t':'patternGraph','v':copy.deepcopy(patterns[key(path,proc.single(record['paramsGraphs']))])}
            if node['definition'] == 'graph_instance':
                call = image_calls[(path,full_name)][source_id]; ref = node['reference']; dependency = ref['dependency']
                package = '' if call['target'][0] == path else resources['packages'][path]['dependencies'][dependency]['reference']
                native['instance'] = {'package':package, 'graph':ref['path'],
                    'inputs':[{'identifier':p['name'],'type_code':p['type']} for p in call['inputs'].values()],
                    'outputs':[{'identifier':name,'type_code':node['output_types'][uid]} for uid,name in node['outputs'].items()]}
            if base_functions: native['base']['functions'] = base_functions
            if params: native['params'] = params
            if dynamic: native['functions'] = dynamic
            if node['input_values']: native['inputValues'] = {name:VALUE_TYPES[code] for name,code in node['input_values'].items()}
            result['nodes'].append(native)
        entries = proc.annotations(root['GUIObjects']); result.update(canvas(entries,len(result['nodes'])+1))
        result['nextId'] = len(result['nodes'])+len(entries)+1
        return result

    packages = {}
    for path,package in resources['packages'].items():
        predicted = {'name':package['name'], 'graphs':[], 'folders':[], 'resources':[], 'version':1}
        descriptions = {}; pending = deque([('',members(snapshot['xml'][path]['root'])['content'])])
        while pending:
            folder,content = pending.popleft()
            for item in children(content):
                fields = members(item); name = scalar(fields['identifier']); full = folder+'/'+name if folder else name
                if item['tag'] == 'group':
                    predicted['folders'].append(full); pending.append((full,fields['content']))
                    if package['folders'][full]: descriptions[full] = package['folders'][full]
                elif item['tag'] == 'resource':
                    resource = package['resources'][name]; predicted['resources'].append({k:resource[k] for k in ('name','folder','file')})
                else: predicted['graphs'].append(graph_model(path,full,item))
        if descriptions: predicted['folder_descriptions'] = descriptions
        packages[path] = predicted
    return {'packages':packages, 'serialized_native_model_complete':True, 'resource_bytes_compared':False,
            'requires_external_handoff':references['requires_external_handoff'], 'engine_admission_complete':False}


def check_native(report, package, observed):
    """Exact field/type/order comparison, with a bounded diagnostic location.

No unknown fields or serializer defaults are stripped. Float sign matters.
Resource payloads are not serialized in this model and require separate proof.
"""
    require(package in report['packages'], 'native comparison names an absent package')
    pending = [(report['packages'][package], observed, '$')]
    while pending:
        expected,actual,location = pending.pop()
        require(type(actual) is type(expected), 'native model type differs at '+location)
        if type(expected) is dict:
            require(expected.keys()==actual.keys(), 'native model fields differ at '+location)
            pending.extend((v,actual[k],(location+'.'+k)[:512]) for k,v in expected.items())
        elif type(expected) is list:
            require(len(expected)==len(actual), 'native model list length differs at '+location)
            pending.extend((v,actual[i],(location+'['+str(i)+']')[:512]) for i,v in enumerate(expected))
        else:
            equal = expected==actual
            if type(expected) is float: equal = equal and math.isfinite(actual) and math.copysign(1,expected)==math.copysign(1,actual)
            require(equal, 'native model value differs at '+location)
    return {'serialized_native_model_equal':True, 'resource_bytes_compared':False, 'engine_admission_complete':False}
