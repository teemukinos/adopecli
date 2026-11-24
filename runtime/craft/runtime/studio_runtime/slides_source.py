"""Exact Slides source ownership and independently reconstructed native models.

No native process, font, image decoder or URL is opened here. Successful inspection
is not execution permission: complete semantics and native preservation checks are
separate requirements. Original container bytes remain authoritative.
"""
import copy
import hashlib
import json
import math
import re

from . import animate_format, write_container

MAX_SOURCE = 128 << 20
MAX_JSON = 32 << 20
MAX_BINARY = 16 << 20
MAX_SHAPES = 100_000
MAX_PARTS = 4096
MIMETYPE = b'application/vnd.storyteller.deckcraft+zip'


def require(value, message):
    if not value: raise ValueError('Slides '+message)


def sha(data): return hashlib.sha256(data).hexdigest()


def strict_json(data):
    require(type(data) is bytes and 0 < len(data) <= MAX_JSON, 'JSON exceeds byte budget')
    try: animate_format._preflight(data, 2_000_000)
    except ValueError as error: raise ValueError('Slides JSON preflight failed: '+str(error)) from error
    def pairs(items):
        result = {}
        for key,value in items:
            require(key not in result, 'JSON contains duplicate keys'); result[key] = value
        return result
    def integer(token):
        require(len(token.lstrip('-')) <= 20 and -2**63 <= int(token) < 2**64, 'JSON integer exceeds native range')
        return int(token)
    def floating(token):
        value = float(token); require(math.isfinite(value), 'JSON number must be finite binary64'); return value
    def constant(_): raise ValueError('Slides JSON number must be finite')
    try: value = json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_int=integer,parse_float=floating,parse_constant=constant)
    except (UnicodeError,json.JSONDecodeError,RecursionError) as error: raise ValueError('Slides JSON is malformed') from error
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict: pending.extend(item); pending.extend(item.values())
        elif type(item) is list: pending.extend(item)
        elif type(item) is str: require(not any(0xd800 <= ord(c) <= 0xdfff for c in item), 'JSON contains invalid Unicode')
    return value


def identity(value, label):
    require(type(value) is int and 0 <= value < 2**32, label+' must be a native u32 identity'); return value


def sequence(value, label, maximum):
    require(type(value) is list and len(value) <= maximum, label+' exceeds its list budget'); return value


def native_shape_owners(document):
    """Visit exactly the stories that the native chart-sidecar reader visits."""
    for index,slide in enumerate(document['slides']): yield '/slides/'+str(index),slide
    for index,master in enumerate(document['masters']):
        path='/masters/'+str(index);yield path,master
        for i,layout in enumerate(master['layouts']): yield path+'/layouts/'+str(i),layout
    for field in ('notesMaster','handoutMaster'):
        master=document[field]
        if master is None: continue
        yield '/'+field,master
        for i,layout in enumerate(master['layouts']): yield '/'+field+'/layouts/'+str(i),layout


def structure(document):
    require(type(document) is dict, 'model must be an object')
    required={'slideSize','notesSize','slides','masters','notesMaster','handoutMaster','sections','customShows','show','headerFooter','props',
              'defaultTextStyle','media','firstSlideNumber','nextId','embeddedFonts'}
    require(required <= set(document), 'model omits required native fields')
    for name in ('slideSize','notesSize'):
        size=document[name];require(type(size) is dict and set(size)=={'width','height'}, name+' fields differ')
        require(all(type(v) in (int,float) and math.isfinite(v) and 72 <= v <= 4032 for v in size.values()), name+' would require native size repair')
    slides=sequence(document['slides'],'slides',256);masters=sequence(document['masters'],'masters',256)
    require(masters, 'model would require a replacement master')
    layout_ids=set();master_ids=set();slide_ids=set();maximum=0
    for master in masters:
        require(type(master) is dict, 'master must be an object');i=identity(master.get('id'),'master')
        require(i not in master_ids,'duplicate master identity');master_ids.add(i);maximum=max(maximum,i)
        for layout in sequence(master.get('layouts'),'layouts',256):
            require(type(layout) is dict,'layout must be an object');i=identity(layout.get('id'),'layout')
            require(i not in layout_ids,'duplicate layout identity');layout_ids.add(i);maximum=max(maximum,i)
    for name in ('notesMaster','handoutMaster'):
        master=document[name]
        if master is not None:
            require(type(master) is dict,'auxiliary master must be an object');maximum=max(maximum,identity(master.get('id'),'auxiliary master'))
            for layout in sequence(master.get('layouts'),'auxiliary layouts',256):
                require(type(layout) is dict,'auxiliary layout must be an object');maximum=max(maximum,identity(layout.get('id'),'auxiliary layout'))
    for slide in slides:
        require(type(slide) is dict,'slide must be an object');i=identity(slide.get('id'),'slide')
        require(i not in slide_ids,'duplicate slide identity');slide_ids.add(i);maximum=max(maximum,i)
        require(identity(slide.get('layout'),'slide layout') in layout_ids,'slide would require native layout replacement')
    shapes=[];chart_parts=[];kinds=set()
    for path,owner in native_shape_owners(document):
        ids=set();pending=[(owner.get('shapes'),path+'/shapes',0)]
        while pending:
            children,base,depth=pending.pop();require(depth<=16,'group depth exceeds budget')
            for index,shape in enumerate(sequence(children,'shapes',MAX_SHAPES)):
                require(type(shape) is dict,'shape must be an object');i=identity(shape.get('id'),'shape')
                require(i not in ids,'duplicate shape identity within its owning story');ids.add(i);maximum=max(maximum,i)
                location=base+'/'+str(index);shapes.append((location,shape));require(len(shapes)<=MAX_SHAPES,'aggregate shape budget exceeded')
                kind=shape.get('kind');require(type(kind) is dict and type(kind.get('type')) is str,'shape kind must be explicit');kinds.add(kind['type'])
                if kind['type']=='group':pending.append((kind.get('children'),location+'/kind/children',depth+1))
                if kind['type']=='chart' and 'kept' in kind:
                    kept=kind['kept'];require(type(kept) is dict,'chart kept parts must be an object')
                    for n,part in enumerate(sequence(kept.get('parts',[]),'chart parts',MAX_PARTS)):
                        require(type(part) is dict,'chart part must be an object');chart_parts.append((location+'/kind/kept/parts/'+str(n),part))
                        require(len(chart_parts)<=MAX_PARTS,'aggregate chart part budget exceeded')
    media_ids=set()
    for media in sequence(document['media'],'media',MAX_PARTS):
        require(type(media) is dict,'media item must be an object');i=identity(media.get('id'),'media')
        require(i not in media_ids,'duplicate media identity');media_ids.add(i);maximum=max(maximum,i)
    require(identity(document['nextId'],'nextId')>=maximum,'nextId would require native identity repair')
    return {'shapes':shapes,'chart_parts':chart_parts,'shape_kinds':sorted(kinds),'unknown_fields':sorted(set(document)-required-{'tableStyles','tags','keptParts','guides','rawExt'})}


def inspect_bytes(data, kind):
    require(type(data) is bytes and 0 < len(data) <= MAX_SOURCE, 'source exceeds byte budget')
    require(kind in ('json','deckcraft'), 'source format must be explicit json or deckcraft')
    members={};directories=[];manifest=None
    if kind=='json':document=strict_json(data)
    else:
        try:members,directories,_=write_container.archive_members(data)
        except ValueError as error:raise ValueError('Slides source archive refused: '+str(error)) from error
        require(members.get('mimetype')==MIMETYPE,'native MIME identity differs')
        require('presentation.json' in members,'native presentation manifest is missing')
        manifest=strict_json(members['presentation.json'])
        require(type(manifest) is dict and set(manifest)=={'format','version','generator','presentation'},'native manifest fields differ')
        require(manifest['format']=='deckcraft' and type(manifest['version']) is int and manifest['version']==1,'native format/version unsupported')
        require(type(manifest['generator']) is str and len(manifest['generator'].encode())<=1024,'native generator is invalid')
        document=copy.deepcopy(manifest['presentation'])
    inventory=structure(document);owned={'mimetype','presentation.json'} if kind=='deckcraft' else set();binary=0;resources=[]
    for media in document['media']:
        require({'id','name','contentType','link'}<=set(media),'media metadata is incomplete')
        require(type(media['name']) is str and type(media['contentType']) is str,'media name/type must be strings')
        require(media['link'] is None or type(media['link']) is str,'media link must be a string or null')
        entry='media/'+str(media['id'])
        if kind=='deckcraft':
            require('dataHex' not in media,'native manifest cannot override an observed media payload')
            require(entry in members or media['link'] is not None,'native media payload is missing')
            payload=members.get(entry,b'')
            if entry in members:owned.add(entry)
            media['dataHex']=payload.hex()
        else:
            encoded=media.get('dataHex');require(type(encoded) is str and len(encoded)<=MAX_BINARY*2 and len(encoded)%2==0
                and re.fullmatch('[0-9a-f]*',encoded) is not None,'media bytes require bounded canonical dataHex')
            payload=bytes.fromhex(encoded)
        binary+=len(payload);require(binary<=MAX_BINARY,'binary resources exceed aggregate byte budget')
        resources.append({'kind':'media','id':media['id'],'sha256':sha(payload),'bytes':len(payload),'external_link':media['link']})
    for path,part in inventory['chart_parts']:
        require(type(part.get('name')) is str and type(part.get('contentType')) is str,'chart part metadata is incomplete')
        if 'nativeEntry' in part:
            require(kind=='deckcraft','model cannot contain unresolved native chart references')
            entry=part['nativeEntry'];require(type(entry) is str and re.fullmatch(r'chart-parts/(0|[1-9][0-9]*)',entry) is not None,'chart member reference is not canonical')
            require(entry in members and entry not in owned,'chart member is missing or has multiple owners')
            require(part.get('bytes',[])==[],'chart part has both inline and archive payloads')
            owned.add(entry);payload=members[entry];part.pop('nativeEntry')
            if payload:part['bytes']=list(payload)
            else:part.pop('bytes',None)
        else:
            values=part.get('bytes',[]);sequence(values,'inline chart bytes',MAX_BINARY)
            require(all(type(v) is int and 0<=v<=255 for v in values),'inline chart bytes are invalid');payload=bytes(values)
        binary+=len(payload);require(binary<=MAX_BINARY,'binary resources exceed aggregate byte budget')
        resources.append({'kind':'chart','path':path,'sha256':sha(payload),'bytes':len(payload),'name':part['name']})
    if kind=='deckcraft':require(set(members)==owned,'archive contains unowned payload members')
    pending=['complete-model-semantics','native-full-model-comparison','source-format-fidelity','resource-and-font-admission','rendered-fidelity']
    if any(r.get('external_link') is not None for r in resources):pending.append('external-media-link-policy')
    if inventory['chart_parts']:pending.append('chart-relationship-and-payload-semantics')
    if inventory['unknown_fields']:pending.append('unknown-model-fields')
    return {'format':kind,'source_bytes':data,'source_sha256':sha(data),'source_size':len(data),'manifest':manifest,
            'members':members,'directories':directories,'document':document,'resources':resources,'binary_bytes':binary,
            'shape_count':len(inventory['shapes']),'shape_kinds':inventory['shape_kinds'],'unknown_model_fields':inventory['unknown_fields'],
            'pending_qualification':sorted(pending),'engine_admission_complete':False}


def read_source(path, kind):
    try:data=write_container.read_bytes(path)
    except ValueError as error:raise ValueError('Slides source cannot be read: '+str(error)) from error
    return inspect_bytes(data,kind)


def check_preservation(checked, data):
    require(type(data) is bytes and data==checked['source_bytes'],'original source bytes changed')
