"""Exact optimistic edits of owned Slides models, without native execution."""
import copy
import json
import math
import re

from . import slides_source as source
from .slides_source import require

KINDS={'text.replace','run.properties','shape.transform','slide.properties','picture.insert','picture.replace','picture.crop'}
RUN_FIELDS=('font fontEa fontCs fontSym size bold italic underline underlineColor strike baseline caps spacing kern fill outline highlight link hover '
            'lang altLang shadow innerShadow glow reflection softEdge noProof normalizeHeight').split()
EDITABLE_RUN={'font','fontEa','fontCs','fontSym','size','bold','italic','spacing','kern','baseline','noProof','normalizeHeight','lang','altLang','fill'}


def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=True,allow_nan=False,separators=(',',':'))


def encoded(value):return (canonical(value)+'\n').encode('ascii')


def locate(document,path):
    value=document
    for key in path.split('/')[1:]:value=value[int(key)] if type(value) is list else value[key]
    return value


def targets(document):
    profile=source.structure(document);shapes={path:shape for path,shape in profile['shapes']};bodies=[];runs={};text_bytes=0
    def add_body(path,value):
        require(len(bodies)<100_000,'aggregate text body budget exceeded');bodies.append((path,value))
    for path,shape in shapes.items():
        if shape.get('text') is not None:add_body(path+'/text',shape['text'])
        kind=shape['kind']
        if kind['type']=='table':
            for row_index,row in enumerate(source.sequence(kind.get('rows'),'table rows',1000)):
                require(type(row) is dict,'table row must be an object')
                for cell_index,cell in enumerate(source.sequence(row.get('cells'),'table cells',1000)):
                    require(type(cell) is dict,'table cell must be an object')
                    add_body(f'{path}/kind/rows/{row_index}/cells/{cell_index}/text',cell.get('text'))
    slides={f'/slides/{i}':slide for i,slide in enumerate(document['slides'])}
    for path,slide in slides.items():add_body(path+'/notes',slide.get('notes'))
    for path,body in bodies:
        require(type(body) is dict,'editable text body must be an object')
        for p,paragraph in enumerate(source.sequence(body.get('paragraphs'),'paragraphs',100_000)):
            require(type(paragraph) is dict,'paragraph must be an object')
            for r,run in enumerate(source.sequence(paragraph.get('runs'),'runs',100_000)):
                require(type(run) is dict and type(run.get('text')) is str,'text run must own explicit text')
                text_bytes+=len(run['text'].encode());require(text_bytes<=16<<20,'editable text exceeds aggregate budget')
                runs[f'{path}/paragraphs/{p}/runs/{r}']=run;require(len(runs)<=100_000,'aggregate run budget exceeded')
    return shapes,runs,slides


def plain(value,label,limit,empty=True):
    require(type(value) is str and (empty or bool(value.strip())) and len(value.encode())<=limit
            and not any(ord(c)<32 or ord(c)==127 or c=='\ufffc' for c in value),label+' must be bounded plain text')
    return value


def run_properties(before,values):
    require(before is None or type(before) is dict and set(before)==set(RUN_FIELDS),'run properties require complete known native fields')
    require(type(values) is dict and values and set(values)<=EDITABLE_RUN,'run property patch has unsupported fields')
    for key,value in values.items():
        if value is None:continue
        if key == 'fill':
            # Use the same bounded color profile as native execution admission.
            # Import lazily because admission also uses the revision vocabulary.
            from .slides_admission import fill
            fill(value)
        elif key in ('font','fontEa','fontCs','fontSym','lang','altLang'):plain(value,key,256,False)
        elif key in ('bold','italic','noProof','normalizeHeight'):require(type(value) is bool,key+' must be boolean')
        else:
            low,high={'size':(1,4000),'spacing':(-4000,4000),'kern':(0,4000),'baseline':(-1,1)}[key]
            require(type(value) in (int,float) and math.isfinite(value) and low<=value<=high,key+' exceeds finite range')
    result=dict.fromkeys(RUN_FIELDS) if before is None else copy.deepcopy(before)
    result.update({key:float(value) if key in ('size','spacing','kern','baseline') and value is not None else copy.deepcopy(value) for key,value in values.items()})
    return result if any(v is not None for v in result.values()) else None


def transform(value):
    if value is None:return None
    require(type(value) is dict and {'x','y','w','h'}<=set(value)<={'x','y','w','h','rot','flipH','flipV'},'transform fields differ')
    result={}
    for key,v in value.items():
        if key in ('flipH','flipV'):require(v is True,'omit inactive native flip properties');result[key]=v
        else:
            low,high=(-1e6,1e6) if key in ('x','y') else (0,360) if key=='rot' else (0,1e6)
            require(type(v) in (int,float) and math.isfinite(v) and low<=v<=high,'transform scalar exceeds bounds')
            if key=='rot':require(0<v<360,'omit zero rotation; native angles must be below 360')
            result[key]=float(v)
    return result


def revise_bytes(data,expected_sha256,edits):
    require(type(data) is bytes and type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}',expected_sha256) is not None
            and source.sha(data)==expected_sha256,'revision source hash is stale or invalid')
    try:request=encoded(edits)
    except (ValueError,TypeError,RecursionError) as error:raise ValueError('Slides edits require finite bounded JSON') from error
    require(len(request)<=8<<20,'edit request exceeds byte budget');edits=source.strict_json(request)
    require(type(edits) is list and 1<=len(edits)<=128,'revision needs one to 128 edits')
    checked=source.inspect_bytes(data,'json');original=checked['document'];shapes,runs,slides=targets(original);bound=[];owners={}
    for edit in edits:
        require(type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in KINDS and type(edit.get('path')) is str,'revision kind/path invalid')
        kind=edit['kind'];path=edit['path'];keys={'kind','path','expected'}|({'start','end','value'} if kind=='text.replace' else {'set'} if kind in ('run.properties','slide.properties') else {'value'})
        require(set(edit)==keys,'revision fields differ')
        if kind in ('text.replace','run.properties'):
            require(path in runs,'revision path is not an owned run');before=runs[path]
            require(before.get('kind',{'kind':'text'})=={'kind':'text'},'field, break and equation runs require a separate edit operation')
            if kind=='text.replace':
                raw=before['text'].encode();start=edit['start'];end=edit['end']
                require(type(start) is int and type(end) is int and 0<=start<end<=len(raw),'text range must be nonempty original UTF-8 offsets')
                try:selected=raw[start:end].decode();raw[:start].decode();raw[end:].decode()
                except UnicodeError as error:raise ValueError('Slides range splits UTF-8') from error
                require(type(edit['expected']) is str and selected==edit['expected'],'selected text differs from expectation')
                plain(selected,'selected text',1<<20);plain(edit['value'],'replacement',1<<20)
            else:
                require(canonical(before.get('props'))==canonical(edit['expected']),'run properties differ from expectation')
                edit={**edit,'result':run_properties(before.get('props'),edit['set'])}
        elif kind=='shape.transform':
            require(path in shapes,'transform path is not an owned shape')
            require(canonical(shapes[path].get('xfrm'))==canonical(edit['expected']),'shape transform differs from expectation')
            edit={**edit,'result':transform(edit['value'])}
        elif kind.startswith('picture.'):
            from . import slides_pictures as pictures
            if kind=='picture.insert':
                require(path in slides and edit['expected']==source.sha(encoded(slides[path])), 'picture insertion slide differs from expectation')
                require(type(edit['value']) is dict and set(edit['value'])=={'image','transform'}, 'picture insertion fields differ')
                pictures.supplied(edit['value']['image'],0);transform(edit['value']['transform'])
            else:
                require(path in shapes and shapes[path]['kind']['type']=='picture', 'picture path is not an owned picture')
                picture=shapes[path]['kind']['fill']
                if kind=='picture.replace':
                    media=next((item for item in original['media'] if item['id']==picture['media']),None)
                    require(media is not None and type(edit['expected']) is dict and set(edit['expected'])=={'media','sha256'}
                            and type(edit['expected']['media']) is int and edit['expected']=={'media':media['id'],'sha256':source.sha(bytes.fromhex(media['dataHex']))},
                            'picture replacement differs from expected owned bytes')
                    pictures.supplied(edit['value'],0)
                else:
                    require(canonical(picture['crop'])==canonical(edit['expected']), 'picture crop differs from expectation')
                    pictures.fill({**picture,'crop':edit['value']},{picture['media']:None})
        else:
            require(path in slides and type(edit['set']) is dict and edit['set'] and set(edit['set'])<={'name','hidden','showMasterShapes'},'slide property patch invalid')
            require(type(edit['expected']) is dict and set(edit['expected'])==set(edit['set'])
                    and canonical({k:slides[path].get(k) for k in edit['set']})==canonical(edit['expected']),'slide properties differ from expectation')
            for key,value in edit['set'].items():
                if key=='name':plain(value,'slide name',1024)
                else:require(type(value) is bool,'slide visibility property must be boolean')
        previous=owners.setdefault(path,[])
        require(not previous or kind=='text.replace' and all(e['kind']==kind and (edit['end']<=e['start'] or edit['start']>=e['end']) for e in previous),
                'edits overlap or compete for the same native owner')
        previous.append(edit);bound.append(edit)
    result=copy.deepcopy(original)
    for edit in sorted(bound,key=lambda e:(e['path'],-e.get('start',-1))):
        node=locate(result,edit['path']);kind=edit['kind']
        if kind=='text.replace':
            raw=node['text'].encode();node['text']=(raw[:edit['start']]+edit['value'].encode()+raw[edit['end']:]).decode()
        elif kind=='run.properties':
            if edit['result'] is None:node.pop('props',None)
            else:node['props']=edit['result']
        elif kind=='shape.transform':node['xfrm']=edit['result']
        elif kind=='picture.insert':pictures.insert(result,node,edit['value'])
        elif kind=='picture.replace':pictures.replace(result,node,edit['value'])
        elif kind=='picture.crop':node['kind']['fill']['crop']=[float(v) for v in edit['value']]
        else:node.update(edit['set'])
    require(canonical(result)!=canonical(original),'revision changes nothing')
    output=encoded(result);after=source.inspect_bytes(output,'json')
    if any(edit['kind'] in ('picture.insert','picture.replace') for edit in bound):
        require(after['resources'][:len(checked['resources'])]==checked['resources'], 'picture revision replaced an existing owned resource')
        pictures.inventory(result)
    else:require(after['resources']==checked['resources'],'revision changed source resource ownership')
    return {'data':output,'document':result,'source_sha256':expected_sha256,'revision_sha256':source.sha(output),'edits':edits,
            'changed_paths':sorted(owners),'pending_qualification':after['pending_qualification'],'engine_admission_complete':False}
