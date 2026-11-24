"""Structured SBS authoring and scoped structural revisions without native saves.

Trees use explicit tags, string attributes and ordered children. The complete
Material schema/model inspectors, not this serializer, decide admissibility.
Every structural edit is tied to an immutable source digest and subtree digest.
"""
import hashlib
import io
import json
import re
from pathlib import Path
import shutil
import zipfile
from xml.sax.saxutils import quoteattr

from . import material_container as container, material_document as document
from .material_container import require
from .material_resources import children

MAX_OPERATIONS = 128


def tree(element):
    """Expose an admitted element as an editable typed tree, without whitespace."""
    result = {'tag':element['tag'],'attributes':dict(element['attributes']),'children':[]}
    pending = [(element,result)]
    while pending:
        source,target = pending.pop()
        # Native admitted content has no significant XML text. Scalar strings
        # live in attributes, including text and embedded resource encodings.
        for child in source['content']:
            if 'tag' not in child:
                require('text' in child and not child['text'].strip(), 'source tree has unsupported non-element content'); continue
            item = {'tag':child['tag'],'attributes':dict(child['attributes']),'children':[]}
            target['children'].append(item); pending.append((child,item))
    return result


def encode(value):
    chunks = []; total = 0; count = 0; pending = [('node',value,1)]
    def append(text):
        nonlocal total
        data = text.encode('utf-8'); total += len(data)
        require(total<=container.MAX_XML, 'authored XML exceeds its byte budget'); chunks.append(data)
    while pending:
        kind,item,depth = pending.pop()
        if kind=='close': append('</'+item+'>'); continue
        count += 1; require(count<=container.MAX_XML_NODES and depth<=container.MAX_XML_DEPTH, 'authored XML exceeds its structural budget')
        require(type(item) is dict and set(item)=={'tag','attributes','children'}, 'authored element has unexpected fields')
        tag = item['tag']; attrs = item['attributes']; nodes = item['children']
        require(type(tag) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_.-]{0,255}',tag) is not None, 'authored element name is invalid')
        require(type(attrs) is dict and len(attrs)<=container.MAX_ATTRIBUTES and type(nodes) is list and len(nodes)<=container.MAX_XML_NODES, 'authored attributes or children are invalid')
        append('<'+tag)
        for name,text in attrs.items():
            require(type(name) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_.-]{0,255}',name) is not None and name!='xmlns'
                    and type(text) is str, 'authored XML attribute is invalid')
            require(len(text.encode('utf-8'))<=container.MAX_XML, 'authored XML attribute exceeds its budget')
            append(' '+name+'='+quoteattr(text))
        if not nodes: append('/>')
        else:
            append('>'); pending.append(('close',tag,depth))
            pending.extend(('node',child,depth+1) for child in reversed(nodes))
    return b''.join(chunks)


def archive(members,directories=()):
    require(type(members) is dict and len(members)+len(directories)<=4096, 'authored archive has too many entries')
    stream = io.BytesIO(); total = 0
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as output:
        for name,payload in [(name,b'') for name in directories]+list(members.items()):
            require(type(name) is str and type(payload) is bytes, 'authored archive entries require names and bytes')
            total += len(payload); require(total<=container.MAX_SOURCE, 'authored archive exceeds its payload budget')
            entry = zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0)); entry.create_system = 3
            entry.external_attr = (0o40700 if name.endswith('/') else 0o100600)<<16
            container._name(entry); output.writestr(entry,payload)
            require(stream.tell()<=container.MAX_SOURCE, 'authored archive exceeds its byte budget')
    data = stream.getvalue(); require(len(data)<=container.MAX_SOURCE, 'authored archive exceeds its byte budget')
    observed = container.inspect_bytes(data)
    require(observed['members']==members and observed['directories']==list(directories), 'authored archive changed its requested entries')
    return data


def create(documents, assets=None):
    """Author a complete portable package from typed SBS trees and owned bytes."""
    assets = {} if assets is None else assets
    require(type(documents) is dict and documents and type(assets) is dict and not documents.keys() & assets.keys(), 'authored source inventory is invalid')
    require(all(type(name) is str and name.lower().endswith('.sbs') for name in documents), 'authored documents must have SBS names')
    require(all(type(name) is str and not name.lower().endswith('.sbs') for name in assets), 'binary assets cannot shadow source documents')
    require(len(documents)+len(assets)<=4096, 'authored archive has too many entries')
    members = {}; total = 0
    for name,value in list(documents.items())+list(assets.items()):
        data = encode(value) if name in documents else value
        require(type(data) is bytes, 'authored asset must contain bytes')
        total += len(data); require(total<=container.MAX_SOURCE, 'authored inventory exceeds its payload budget')
        members[name] = data
    data = archive(members); profile = document.inspect_bytes(data)
    return data, {'source_sha256':profile['container']['source_sha256'],'documents':list(documents),'assets':list(assets),
                  'source_authored':True,'native_verified':False,'engine_admission_complete':False}


def selectors(profile):
    """Return hash-bound element identities for all admitted source documents."""
    result = {}
    for package,parsed in profile['container']['xml'].items():
        data = profile['container']['members'][package]; indices = {id(e):i for i,e in enumerate(parsed['elements'])}
        parents = {indices[id(child)]:indices[id(parent)] for parent in parsed['elements'] for child in parent['content'] if 'tag' in child}
        result[package] = [{'element':i,'tag':e['tag'],'parent':parents.get(i),'sha256':hashlib.sha256(memoryview(data)[a:b]).hexdigest()}
                           for i,(e,(a,b)) in enumerate(zip(parsed['elements'],parsed['spans']))]
    return result


def revise(data, expected_sha256, operations):
    require(type(operations) is list and 1<=len(operations)<=MAX_OPERATIONS, 'structural revision needs 1 to 128 operations')
    require(type(expected_sha256) is str and hashlib.sha256(data).hexdigest()==expected_sha256, 'structural revision source digest is stale')
    before = document.inspect_bytes(data); snapshot = before['container']; updated = dict(snapshot['members'])
    patches = {}; collapsed = {}; member_targets = set(); changes = []; hashes = {}; payload_bytes = 0
    indices = {p:{id(e):i for i,e in enumerate(parsed['elements'])} for p,parsed in snapshot['xml'].items()}
    for order,operation in enumerate(operations):
        require(type(operation) is dict and type(operation.get('kind')) is str, 'structural operation is malformed')
        kind = operation['kind']
        if kind.startswith('asset.'):
            fields = {'kind','member'} | ({'expected_sha256'} if kind!='asset.add' else set()) | ({'data'} if kind!='asset.remove' else set())
            require(kind in ('asset.add','asset.replace','asset.remove') and set(operation)==fields, 'structural asset operation is invalid')
            name = operation['member']; require(type(name) is str and not name.lower().endswith('.sbs') and name not in member_targets, 'asset target is invalid or repeated')
            member_targets.add(name)
            if kind=='asset.add': require(name not in updated, 'added asset already exists')
            else: require(name in updated and hashlib.sha256(updated[name]).hexdigest()==operation['expected_sha256'], 'asset precondition is stale')
            if kind=='asset.remove': updated.pop(name)
            else:
                require(type(operation['data']) is bytes and len(operation['data'])<=container.MAX_EMBEDDED, 'asset bytes exceed their budget')
                payload_bytes += len(operation['data']); require(payload_bytes<=container.MAX_SOURCE, 'structural payloads exceed their budget')
                updated[name] = operation['data']
            changes.append({'kind':kind,'member':name,'sha256':hashlib.sha256(updated[name]).hexdigest() if name in updated else None}); continue
        fields = {'kind','package','element','expected_sha256'} | ({'value'} if kind!='remove' else set()) | ({'before'} if kind=='insert' else set())
        require(kind in ('replace','remove','insert') and set(operation)==fields, 'structural element operation is invalid')
        package = operation['package']; index = operation['element']
        require(type(package) is str and package in snapshot['xml'] and type(index) is int and 0<=index<len(snapshot['xml'][package]['elements']), 'structural element identity is absent')
        parsed = snapshot['xml'][package]; element = parsed['elements'][index]; start,end = parsed['spans'][index]; original = snapshot['members'][package]
        identity = (package,index)
        if identity not in hashes: hashes[identity] = hashlib.sha256(memoryview(original)[start:end]).hexdigest()
        require(hashes[identity]==operation['expected_sha256'], 'structural element precondition is stale')
        payload = encode(operation['value']) if kind!='remove' else b''
        payload_bytes += len(payload); require(payload_bytes<=container.MAX_SOURCE, 'structural payloads exceed their budget')
        if kind=='insert':
            require(not element['attributes'], 'structural insertion requires a container element')
            child_ids = {indices[package][id(c)] for c in children(element)}; anchor = operation['before']
            require(anchor is None or type(anchor) is int and anchor in child_ids, 'insertion anchor is not a direct child')
            # Container opening tags have no attributes. Existing whitespace is
            # retained when an empty element is expanded to paired tags.
            opening = original.find(b'>',start)+1
            if original[start:opening].endswith(b'/>'):
                require(anchor is None, 'empty container has no insertion anchor')
                collapsed.setdefault((package,index),(start,end,opening,[]))[3].append(payload)
            else:
                point = parsed['spans'][anchor][0] if anchor is not None else original.rfind(b'</',start,end)
                require(start<point<end, 'container insertion position is invalid')
                patches.setdefault(package,[]).append((point,point,order,payload))
        else: patches.setdefault(package,[]).append((start,end,order,payload))
        changes.append({'kind':kind,'package':package,'element':index,'old_sha256':operation['expected_sha256'],
                        'authored_sha256':hashlib.sha256(payload).hexdigest() if kind!='remove' else None})
    for (package,index),(start,end,opening,insertions) in collapsed.items():
        original = snapshot['members'][package]; tag = snapshot['xml'][package]['elements'][index]['tag']
        replacement = original[start:opening-2]+b'>'+b''.join(insertions)+('</'+tag+'>').encode()
        patches.setdefault(package,[]).append((start,end,-1,replacement))
    for package,edits in patches.items():
        position = 0; chunks = []; original = snapshot['members'][package]
        for start,end,_,payload in sorted(edits):
            require(start>=position, 'structural edit ranges overlap')
            chunks.extend((original[position:start],payload)); position = end
        chunks.append(original[position:])
        require(sum(map(len,chunks))<=container.MAX_XML, 'revised source document exceeds its byte budget')
        updated[package] = b''.join(chunks)
    result = archive(updated,snapshot['directories']) if snapshot['format']=='mcraft' or set(updated)!=set(snapshot['members']) else updated[snapshot['root']]
    after = document.inspect_bytes(result)
    require(after['container']['members']==updated, 'structural revision changed predicted members')
    return result, {'source_sha256':snapshot['source_sha256'],'revised_sha256':after['container']['source_sha256'],
                    'container_conversion':'none' if after['container']['format']==snapshot['format'] else 'lossless-sbs-wrapper',
                    'changes':changes,'unrequested_source_bytes_preserved':True,'native_verified':False,'engine_admission_complete':False}


def prepare(root, data, destination, executable, report, *, source=None, **options):
    """Verify authored bytes in an exclusive staging file, then retain evidence."""
    require(type(report) is dict and report.get('revised_sha256',report.get('source_sha256'))==hashlib.sha256(data).hexdigest(), 'authored bytes do not match their report')
    root = Path(root).resolve(strict=True); destination = document.owned(root,destination)
    require(not destination.exists(), 'authored destination already exists')
    if source is not None:
        source = document.owned(root,source)
        require(hashlib.sha256(container.read_bytes(source)).hexdigest()==report['source_sha256'], 'authored source changed before preparation')
    staging = destination.with_name(destination.name+'.source-input'); created = False; prepared = None
    try:
        with staging.open('xb') as stream:
            created = True; stream.write(data)
        prepared = document.prepare(root,staging,destination,executable,**options)
        if source is not None: require(hashlib.sha256(container.read_bytes(source)).hexdigest()==report['source_sha256'], 'authored source changed during verification')
        result = {**report,'engine_admission_complete':False,'native_verified':True,'native_cold_reopen':prepared['native_cold_reopen'],'document_sha256':prepared['document_sha256']}
        (destination/'exports/authoring.json').write_text(json.dumps(result,sort_keys=True,allow_nan=False)+'\n')
        return result
    except BaseException:
        if prepared is not None and destination.exists(): shutil.rmtree(destination)
        raise
    finally:
        if created: staging.unlink()
