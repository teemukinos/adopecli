"""Optimistic typed Material scalar edits with exact unrequested source bytes.

All selectors resolve against one immutable source revision. Only the selected
XML scalar elements are replaced; every other byte and archive member survives.
Complete readmission and fresh native snapshots qualify the resulting document.
"""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import zipfile
from xml.sax.saxutils import quoteattr

from . import material_document as document, material_procedural as proc
from .material_container import require
from .material_resources import children, scalar
from .material_model import members

KINDS = {'node.parameter','graph.base','input.default','graph.attribute','graph.size','node.position','output.label',
         'function.constant','pattern.parameter','array.cell'}
TAGS = {'bool':'constantValueBool','text':'constantValueString','int':'constantValueInt32','float':'constantValueFloat1',
        **{kind+str(n):'constantValue'+kind.title()+str(n) for kind in ('int','float') for n in (2,3,4)}}


def equal(a,b): return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)


def literal(value):
    require(type(value) is dict and set(value)=={'t','v'} and type(value['t']) is str and value['t'] in TAGS, 'revision value needs an explicit native scalar type')
    kind = value['t']; data = value['v']
    if kind == 'text': require(type(data) is str, 'revision text must be a string'); text = data
    elif kind == 'bool': require(type(data) is bool, 'revision Boolean must be Boolean'); text = '1' if data else '0'
    else:
        count = int(kind[-1]) if kind[-1].isdigit() else 1
        require(count==1 or type(data) is list and len(data)==count, 'revision vector arity differs')
        parts = [data] if count==1 else data
        require(all(type(v) is int if kind.startswith('int') else type(v) in (int,float) and math.isfinite(v) for v in parts), 'revision numeric components have invalid types')
        text = ' '.join(map(str,parts))
    require(len(text.encode('utf-8'))<=proc.MAX_STRING_BYTES, 'revision value exceeds its byte budget')
    element = {'tag':TAGS[kind],'attributes':{'v':text},'content':[]}
    return element,proc.constant(element)


def entry(holder, name, key='name'):
    result = [e for e in children(holder) if scalar(members(e)[key])==name]
    require(len(result)==1, 'revision target is absent or ambiguous'); return result[0]


def by_id(holder, identity):
    require(type(identity) is str and len(identity)<=20 and re.fullmatch(r'0|[1-9][0-9]*',identity) is not None and int(identity)<2**64, 'revision identity must be a canonical decimal string')
    return entry(holder,identity,'uid')


def target(profile, edit):
    package = edit['package']; name = edit['graph']; kind = edit['kind']
    require((package,name) in profile['graphs']['graphs'], 'revision graph is absent')
    graph = profile['resources']['packages'][package]['graphs'][name]['element']; root = members(graph)
    if kind=='input.default':
        port = members(entry(root['paraminputs'],edit['name'],'identifier')); return proc.single(port['defaultValue'])
    if kind=='output.label': return members(members(entry(root['graphOutputs'],edit['name'],'identifier'))['attributes'])['label']
    if kind=='graph.attribute':
        require(edit['name'] in {'label','category','description','author','authorURL','tags','group','userdata'}, 'revision attribute is unqualified')
        attrs = members(root['attributes']); require(edit['name'] in attrs, 'revision attribute is absent; author it explicitly first'); return attrs[edit['name']]
    if kind=='graph.size': return members(entry(root['options'],'defaultParentSize'))['value']
    if kind=='graph.base': return proc.single(members(entry(root['baseParameters'],edit['name']))['paramValue'])
    if kind=='function.constant':
        index = edit['body']; require(type(index) is int and (package,index) in profile['graphs']['procedural']['functions'], 'revision function body is absent')
        parsed = profile['container']['xml'][package]; body = parsed['elements'][index]
        indices = {id(e):i for i,e in enumerate(parsed['elements'])}; begin,end = parsed['spans'][indices[id(graph)]]
        low,high = parsed['spans'][index]; require(begin<=low<high<=end, 'revision body is outside its named graph')
        node = members(by_id(members(body)['paramNodes'],edit['node']))
        require(scalar(node['function']).startswith('const_'), 'revision function node is not a constant')
        data = children(node['funcDatas']); require(len(data)==1, 'revision function constant is ambiguous')
        return proc.single(members(data[0])['constantValue'])
    node = members(by_id(root['compNodes'],edit['node']))
    if kind=='node.position': return members(node['GUILayout'])['gpos']
    implementation = members(proc.single(node['compImplementation']))
    if kind=='node.parameter': return proc.single(members(entry(implementation['parameters'],edit['name']))['paramValue'])
    if kind=='array.cell':
        array = members(entry(implementation['paramsArrays'],edit['array']))
        cell = members(by_id(array['paramsArrayCells'],edit['cell']))
        return proc.single(members(entry(cell['parameters'],edit['name']))['paramValue'])
    pattern = members(proc.single(implementation['paramsGraphs']))
    node = members(by_id(pattern['paramsGraphNodes'],edit['pattern_node']))
    data = members(by_id(pattern['paramsGraphDatas'],scalar(node['data'])))
    return proc.single(members(entry(data['parameters'],edit['name']))['paramValue'])


def validate(edits):
    require(type(edits) is list and 1<=len(edits)<=128, 'revision needs 1 to 128 edits')
    for edit in edits:
        require(type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in KINDS, 'revision edit kind is unknown')
        extra = {'node.parameter':{'node','name'},'graph.base':{'name'},'input.default':{'name'},'graph.attribute':{'name'},
                 'graph.size':set(),'node.position':{'node'},'output.label':{'name'},'function.constant':{'body','node'},
                 'pattern.parameter':{'node','pattern_node','name'},'array.cell':{'node','array','cell','name'}}[edit['kind']]
        require(set(edit)=={'kind','package','graph','expected','value'}|extra, 'revision fields differ from the typed operation')
        require(all(type(edit[k]) is str for k in ('package','graph')), 'revision package and graph must be strings')
        require(all(type(edit[k]) is str and len(edit[k].encode('utf-8'))<=proc.MAX_STRING_BYTES for k in extra-{'body'}), 'revision selectors must be bounded strings')
        if 'body' in extra: require(type(edit['body']) is int and 0<=edit['body']<document.container.MAX_XML_NODES, 'revision body index is invalid')
        literal(edit['expected']); literal(edit['value'])
    require(len(json.dumps(edits,ensure_ascii=True,allow_nan=False).encode())<=1<<20, 'revision request exceeds its byte budget')


def semantic(element,kind):
    if kind in ('graph.attribute','output.label'): return {'t':'text','v':scalar(element)}
    if kind=='node.position': return {'t':'float2','v':[proc.f32(str(v-offset)) for v,offset in zip(proc.vector(scalar(element),3),(50,40))]}
    if kind=='graph.size': return {'t':'int2','v':[int(v) for v in scalar(element).split('x')]}
    require(element['tag'] in TAGS.values(), 'revision requires a literal; edit a procedural constant explicitly')
    return proc.constant(element)


def encode(element,value,kind):
    replacement,normalized = literal(value)
    if kind in ('graph.attribute','output.label'):
        require(value['t']=='text', 'revision label/attribute requires text'); text = value['v']
    elif kind=='node.position':
        require(value['t']=='float2', 'revision node position requires Float2'); text = ' '.join(str(proc.f32(str(v+offset))) for v,offset in zip(normalized['v'],(50,40)))+' 0'
    elif kind=='graph.size':
        require(value['t']=='int2', 'revision graph size requires Int2 log2 dimensions'); text = 'x'.join(map(str,value['v']))
    else:
        require(element['tag']==replacement['tag'], 'revision cannot silently change the native value type'); text = replacement['attributes']['v']
    # Character references preserve attribute tabs/newlines; the bounded XML
    # parser rejects forbidden XML characters during complete readmission.
    return ('<'+element['tag']+' v='+quoteattr(text)+'/>').encode('utf-8'),normalized


def revise_bytes(data, expected_sha256, edits):
    validate(edits)
    require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}',expected_sha256) is not None
            and hashlib.sha256(data).hexdigest()==expected_sha256, 'revision source digest is stale')
    before = document.inspect_bytes(data); snapshot = before['container']; patches = {}; changes = []
    indices = {path:{id(e):i for i,e in enumerate(parsed['elements'])} for path,parsed in snapshot['xml'].items()}
    for edit in edits:
        try: element = target(before,edit)
        except (KeyError,TypeError) as error: raise ValueError('Material revision selector does not match the source schema') from error
        _,expected = literal(edit['expected']); current = semantic(element,edit['kind'])
        require(equal(current,expected), 'revision expected value differs from its source')
        payload,normalized = encode(element,edit['value'],edit['kind']); package = edit['package']
        span = snapshot['xml'][package]['spans'][indices[package][id(element)]]
        patches.setdefault(package,[]).append((*span,payload))
        derived = []
        if edit['kind']=='input.default':
            graph_xml = before['resources']['packages'][package]['graphs'][edit['graph']]['element']
            port = members(entry(members(graph_xml)['paraminputs'],edit['name'],'identifier'))
            widget = members(port['defaultWidget'])
            if scalar(widget['name'])=='dropdownlist':
                option = members(entry(widget['options'],'parameters'))['value']; old = scalar(option)
                new = str(normalized['v'])+';'+old.split(';',1)[1]
                low,high = snapshot['xml'][package]['spans'][indices[package][id(option)]]
                patches[package].append((low,high,('<value v='+quoteattr(new)+'/>').encode('utf-8')))
                derived.append({'field':'dropdown-current','before':old,'value':new})
        changes.append({'derived_source_updates':derived,'selector':{k:v for k,v in edit.items() if k not in ('value','expected')},'before':current,
                        'requested':copy.deepcopy(edit['value']),'source_value':normalized})
    updated = dict(snapshot['members'])
    for package,replacements in patches.items():
        position = 0; chunks = []; original = snapshot['members'][package]
        for start,end,payload in sorted(replacements):
            require(start>=position, 'revision targets overlap or repeat')
            chunks.extend((original[position:start],payload)); position = end
        chunks.append(original[position:]); updated[package] = b''.join(chunks)
    if snapshot['format']=='sbs': result = updated[snapshot['root']]
    else:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as archive:
            for name,payload in [(name,b'') for name in snapshot['directories']]+list(updated.items()):
                item = zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0)); item.create_system = 3
                item.external_attr = (0o40700 if name.endswith('/') else 0o100600)<<16
                archive.writestr(item,payload)
        result = stream.getvalue()
    after = document.inspect_bytes(result)
    require(after['container']['members']==updated, 'revision container changed predicted members')
    for edit,change in zip(edits,changes):
        # Constant-body indices remain stable: each edit replaces one scalar
        # element with one scalar element, so all original selectors still work.
        observed = semantic(target(after,edit),edit['kind'])
        require(equal(observed,change['source_value']), 'revision requested source value differs after readmission')
    return result, {'source_sha256':snapshot['source_sha256'],'revised_sha256':after['container']['source_sha256'],
                    'edits':changes,'unrequested_source_bytes_preserved':True,'resource_bytes_preserved':True,
                    'native_verified':False,'engine_admission_complete':False}


def prepare(root,source,destination,executable,expected_sha256,edits,**options):
    root = Path(root).resolve(strict=True); source = document.owned(root,source); destination = document.owned(root,destination)
    original = document.container.read_bytes(source); revised,report = revise_bytes(original,expected_sha256,edits)
    require(not destination.exists(), 'revision destination already exists')
    staging = destination.with_name(destination.name+'.revision-input')
    # Exclusive creation protects existing attempts. No request chooses another
    # file to overwrite, and the original document remains immutable.
    prepared = None; created = False
    try:
        with staging.open('xb') as stream:
            created = True; stream.write(revised)
        prepared = document.prepare(root,staging,destination,executable,**options)
        require(document.container.read_bytes(source)==original, 'revision source changed during native verification')
        report.update(native_verified=True,native_cold_reopen=prepared['native_cold_reopen'],document_sha256=prepared['document_sha256'])
        (destination/'exports/revision.json').write_text(json.dumps(report,sort_keys=True,allow_nan=False)+'\n')
        return report
    except BaseException:
        if prepared is not None and destination.exists(): shutil.rmtree(destination)
        raise
    finally:
        if created: staging.unlink()
