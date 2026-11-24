"""Portable exact inputs, native findings and replayable analyst annotations.

Container integrity is not proof of native execution or permission to inspect.
Every public operation requires fresh explicit input consent and native replay.
"""
import copy
import io
import re
import zipfile

from . import inspect_source as source, write_container
from .inspect_source import require

MAX_HISTORY=32
MAX_NOTES=256
MAX_EDITS=4096
MAX_MANIFEST=1<<20


def record(data):return {'sha256':source.sha(data),'bytes':len(data)}


def identifier(value):require(type(value) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}',value), 'annotation identifier invalid')


def changes(value):
    require(type(value) is list and 0<len(value)<=128, 'annotation edit count invalid');seen=set()
    for item in value:
        require(type(item) is dict and item.get('kind') in ('upsert','remove'), 'annotation operation invalid')
        source.fields(item,('kind','id','pointer','title','text','status','severity') if item['kind']=='upsert' else ('kind','id'),'annotation edit')
        identifier(item['id']);require(item['id'] not in seen, 'duplicate annotation edit');seen.add(item['id'])
        if item['kind']=='upsert':
            source.text(item['pointer'],1024,'finding pointer');source.text(item['title'],160,'annotation title');source.text(item['text'],4096,'annotation text')
            require(item['status'] in ('open','resolved') and item['severity'] in ('note','info','warning'), 'annotation status/severity invalid')
    return copy.deepcopy(value)


def apply(notes, edits, report, report_sha256):
    current={item['id']:copy.deepcopy(item) for item in notes}
    for item in changes(edits):
        identity=item['id']
        if item['kind']=='remove':require(identity in current, 'annotation removal target missing');del current[identity]
        else:
            source.pointer(report,item['pointer']);note={k:v for k,v in item.items() if k!='kind'}
            note.update(input_sha256=report['input_sha256'],report_sha256=report_sha256,evidence_id=report['evidence']['id']);current[identity]=note
    require(len(current)<=MAX_NOTES, 'annotation count exceeded')
    return [current[key] for key in sorted(current)]


def pack(manifest,members):
    require(type(members) is dict and 'project.json' not in members, 'portable manifest collision')
    metadata=source.encoded(manifest)
    require(len(metadata)<=MAX_MANIFEST and all(type(v) is bytes for v in members.values())
            and sum(map(len,members.values()))+len(metadata)<=source.MAX_ARCHIVE, 'portable aggregate byte budget exceeded')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as archive:
        for name,data in sorted({**members,'project.json':metadata}.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o100600<<16;archive.writestr(info,data)
    data=stream.getvalue();require(len(data)<=source.MAX_ARCHIVE, 'portable archive exceeds byte budget');return data


def inspect_bytes(data):
    require(type(data) is bytes and 22<=len(data)<=source.MAX_ARCHIVE, 'portable archive exceeds byte budget')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            rows=archive.infolist();require(4<=len(rows)<=MAX_HISTORY+4 and sum(r.file_size for r in rows)<=source.MAX_ARCHIVE, 'portable inventory exceeds budget')
        members,directories,_=write_container.archive_members(data)
    except (ValueError,OSError,zipfile.BadZipFile) as error:raise ValueError('Inspect portable archive refused: '+str(error)) from error
    require(not directories and 'project.json' in members and len(members['project.json'])<=MAX_MANIFEST, 'portable manifest/directory inventory invalid')
    manifest=source.strict_json(members['project.json']);source.fields(manifest,('format','version','engine','input_format','original','report','current','history','members'),'project')
    require(manifest['format']=='dobe-inspect-project' and type(manifest['version']) is int and manifest['version']==1, 'portable format/version invalid');source.pin(manifest['engine'])
    history=manifest['history'];require(type(history) is list and len(history)<=MAX_HISTORY, 'portable history exceeded')
    names={'source.bin','report.json','annotations.json'}|{f'notes-{i+1:04}.json' for i in range(len(history))}
    require(type(manifest['members']) is dict and set(manifest['members'])==names and set(members)==names|{'project.json'}, 'portable inventory differs')
    for name in names:
        source.fields(manifest['members'][name],('sha256','bytes'),'member record')
        require(source.encoded(manifest['members'][name])==source.encoded(record(members[name])), 'portable member hash/size differs')
    source.input_bytes(members['source.bin'],manifest['input_format'],manifest['original'])
    report=source.report_bytes(members['report.json'],members['source.bin'],manifest['input_format'])
    require(manifest['report']==source.sha(members['report.json']) and manifest['current']==source.sha(members['annotations.json']), 'portable root hashes differ')
    notes=[];before=source.encoded(notes);count=0
    for index,step in enumerate(history):
        source.fields(step,('before','after','state','edits'),'annotation history');edits=changes(step['edits']);count+=len(edits);require(count<=MAX_EDITS,'aggregate edits exceeded')
        name=f'notes-{index+1:04}.json';require(step['state']==name and step['before']==source.sha(before), 'annotation history chain differs')
        notes=apply(notes,edits,report,manifest['report']);before=source.encoded(notes)
        require(members[name]==before and step['after']==source.sha(before), 'annotation history replay differs')
    require(members['annotations.json']==before, 'annotations differ from complete history replay')
    return {'manifest':manifest,'members':members,'report':report,'annotations':notes,'sha256':source.sha(data),
            'source_sha256':manifest['original'],'report_sha256':manifest['report'],'revision_count':len(history),'native_replay_required':True}


def create(original,kind,report,*,engine):
    source.report_bytes(report,original,kind);members={'source.bin':original,'report.json':report,'annotations.json':b'[]'}
    manifest={'format':'dobe-inspect-project','version':1,'engine':source.pin(engine),'input_format':kind,
              'original':source.sha(original),'report':source.sha(report),'current':source.sha(b'[]'),'history':[],
              'members':{k:record(v) for k,v in members.items()}}
    data=pack(manifest,members);inspect_bytes(data);return data


def revise(data,expected_sha256,edits):
    require(source.sha(data)==expected_sha256, 'portable revision hash is stale');checked=inspect_bytes(data)
    manifest=copy.deepcopy(checked['manifest']);require(len(manifest['history'])<MAX_HISTORY,'portable history exceeded')
    edits=changes(edits);notes=apply(checked['annotations'],edits,checked['report'],manifest['report']);encoded=source.encoded(notes)
    name=f"notes-{len(manifest['history'])+1:04}.json";members={k:v for k,v in checked['members'].items() if k!='project.json'}
    members[name]=encoded;members['annotations.json']=encoded
    manifest['history'].append({'before':manifest['current'],'after':source.sha(encoded),'state':name,'edits':edits});manifest['current']=source.sha(encoded)
    manifest['members']={k:record(v) for k,v in members.items()};result=pack(manifest,members);inspect_bytes(result);return result
