"""Portable editable Slides projects with immutable sources and exact edit replay.

This module does not execute engines or publish durable revisions. Engine pins
must later bind to verified installation receipts before any native execution.
"""
import io
import json
import os
from pathlib import Path
import re
import zipfile

from . import slides_source as source, slides_revision as revision, write_container
from .slides_source import require

MAX_HISTORY=32
MAX_EDITS=128
MAX_REPLAY=256<<20
MAX_MIGRATIONS=8
MAX_CHAIN_BYTES=256<<20
# Typed image edits retain their exact encoded bytes in history. Keep that
# history bounded while admitting photographs larger than the old text-only cap.
MAX_MANIFEST=16<<20
# Explicit maintained transitions. A project cannot authorize its own new engine.
MIGRATION_EDGES = {('0.18.1', '7cc73ab1895ed2e30c8afbcada20c70b9ea0a440',
                    'b0b00bd22f2ca0725f75d59b5933e7dbdde100f03e31863a9c4d9ec986bdd959',
                    'f285703d5731103bc587b44712e8c35fbe8e8f516d7914fcb06cb69517269667'),
                   ('0.18.1', '7cc73ab1895ed2e30c8afbcada20c70b9ea0a440',
                    'f285703d5731103bc587b44712e8c35fbe8e8f516d7914fcb06cb69517269667',
                    '60614491e1c2f2194cfc1078d415cec9eaf9a4b4b8d1935875434ede7ec086ef')}


def migration_edge(before, after):
    before=pin(before);after=pin(after)
    require(before['version']==after['version'] and before['source_revision']==after['source_revision']
            and (before['version'],before['source_revision'],before['source_lock_sha256'],after['source_lock_sha256']) in MIGRATION_EDGES,
            'portable migration does not name a qualified maintained transition')



def record(data):return {'sha256':source.sha(data),'bytes':len(data)}


def pin(value):
    require(type(value) is dict and set(value)=={'product','version','source_revision','source_lock_sha256'},'engine pin fields differ')
    require(value['product']=='dobe-slides' and type(value['version']) is str and re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',value['version']) is not None,'engine product/version invalid')
    for name,size in (('source_revision',40),('source_lock_sha256',64)):
        require(type(value[name]) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}',value[name]) is not None,'engine digest invalid')
    return dict(value)


def pack(manifest,members):
    require('project.json' not in members,'project manifest collides with payload')
    metadata=revision.encoded(manifest);require(len(metadata)<=MAX_MANIFEST,'project manifest exceeds byte budget')
    require(sum(map(len,members.values()))+len(metadata)<=source.MAX_SOURCE,'project payload exceeds byte budget')
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as archive:
        for name,data in sorted({**members,'project.json':metadata}.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o100600<<16
            archive.writestr(info,data)
    data=result.getvalue();require(len(data)<=source.MAX_SOURCE,'project archive exceeds byte budget');return data


def inspect_bytes(data):
    return _inspect_bytes(data,0,{'archives':0,'expanded':0,'replay':0})


def _inspect_bytes(data,depth,budget):
    require(depth<=MAX_MIGRATIONS,'portable migration chain exceeds depth budget')
    require(type(data) is bytes and 0<len(data)<=source.MAX_SOURCE,'portable archive exceeds byte budget')
    budget['archives']+=len(data)
    require(budget['archives']<=MAX_CHAIN_BYTES,'portable migration archives exceed aggregate byte budget')
    try:members,directories,_=write_container.archive_members(data)
    except ValueError as error:raise ValueError('Slides portable archive refused: '+str(error)) from error
    require(not directories and 'project.json' in members and len(members['project.json'])<=MAX_MANIFEST,'portable manifest/directory inventory invalid')
    require(sum(map(len,members.values()))<=source.MAX_SOURCE,'portable expanded payload exceeds byte budget')
    budget['expanded']+=sum(map(len,members.values()))
    require(budget['expanded']<=MAX_CHAIN_BYTES,'portable migration expansion exceeds aggregate byte budget')
    manifest=source.strict_json(members['project.json'])
    require(type(manifest) is dict and type(manifest.get('version')) is int and manifest['version'] in (1,2),'portable format/version invalid')
    migrated=manifest['version']==2
    fields={'format','version','engine','source_format','members','history'}|({'migration'} if migrated else set())
    require(set(manifest)==fields and manifest['format']=='dobe-slides-project','portable manifest fields differ')
    pin(manifest['engine']);kind=manifest['source_format'];require(kind in ('json','deckcraft'),'portable source format unsupported')
    original='original.'+kind;names={original,'baseline.json','document.json'}|({'predecessor.dobeslides'} if migrated else set())
    require(set(members)==names|{'project.json'} and type(manifest['members']) is dict and set(manifest['members'])==names,'portable member inventory differs')
    for name in names:
        item=manifest['members'][name]
        require(type(item) is dict and set(item)=={'bytes','sha256'} and type(item['bytes']) is int
                and type(item['sha256']) is str and re.fullmatch('[0-9a-f]{64}',item['sha256']) is not None and item==record(members[name]),'portable member hash/size differs')
    original_profile=source.inspect_bytes(members[original],kind)
    baseline=members['baseline.json'];expected=members[original] if kind=='json' else revision.encoded(original_profile['document'])
    require(baseline==expected,'portable baseline differs from exact original or independent native reconstruction')
    source.inspect_bytes(baseline,'json')
    history=manifest['history'];require(type(history) is list and len(history)<=MAX_HISTORY,'portable history exceeds budget')
    replay=baseline;bytes_replayed=len(replay);edit_count=0
    budget['replay']+=len(replay);require(budget['replay']<=MAX_REPLAY,'portable migration replay exceeds aggregate byte budget')
    for entry in history:
        require(type(entry) is dict and set(entry)=={'before','after','edits'} and type(entry['edits']) is list,'portable history entry invalid')
        edit_count+=len(entry['edits']);require(edit_count<=MAX_EDITS,'portable edit history exceeds aggregate budget')
        require(entry['before']==source.sha(replay),'portable history predecessor differs')
        replay=revision.revise_bytes(replay,entry['before'],entry['edits'])['data']
        require(entry['after']==source.sha(replay),'portable history result differs')
        bytes_replayed+=len(replay);require(bytes_replayed<=MAX_REPLAY,'portable replay exceeds byte budget')
        budget['replay']+=len(replay);require(budget['replay']<=MAX_REPLAY,'portable migration replay exceeds aggregate byte budget')
    require(replay==members['document.json'],'portable current model differs from exact typed replay')
    predecessor=None
    if migrated:
        transition=manifest['migration']
        require(type(transition) is dict and set(transition)=={'from_engine','to_engine','predecessor_sha256','revision_count','current_sha256'},
                'portable migration fields differ')
        predecessor=_inspect_bytes(members['predecessor.dobeslides'],depth+1,budget)
        bytes_replayed+=predecessor['replayed_bytes'];require(bytes_replayed<=MAX_REPLAY,'portable migration replay exceeds aggregate byte budget')
        old=predecessor['manifest'];migration_edge(old['engine'],manifest['engine'])
        require(transition['from_engine']==old['engine'] and transition['to_engine']==manifest['engine']
                and transition['predecessor_sha256']==predecessor['sha256']
                and type(transition['revision_count']) is int and transition['revision_count']==len(old['history'])
                and transition['current_sha256']==predecessor['current_sha256'], 'portable migration differs from exact predecessor')
        require(kind==old['source_format'] and members[original]==predecessor['members'][original]
                and baseline==predecessor['members']['baseline.json'], 'portable migration replaced original source or baseline')
        require(revision.canonical(history[:len(old['history'])])==revision.canonical(old['history']) and len(history)>=len(old['history']),
                'portable migration replaced predecessor edit history')
    current=source.inspect_bytes(replay,'json')
    return {'manifest':manifest,'members':members,'source':original_profile,'current':current,'sha256':source.sha(data),
            'source_sha256':source.sha(members[original]),'current_sha256':source.sha(replay),'revision_count':len(history),
            'replayed_edits':edit_count,'replayed_bytes':bytes_replayed,'pending_qualification':sorted(set(current['pending_qualification'])|set(original_profile['pending_qualification'])),
            'migration':manifest.get('migration'),'predecessor':predecessor,
            'migration_count':0 if predecessor is None else predecessor['migration_count']+1,
            'engine_admission_complete':False}


def create(data,kind,*,engine):
    inspected=source.inspect_bytes(data,kind);baseline=data if kind=='json' else revision.encoded(inspected['document'])
    members={'original.'+kind:data,'baseline.json':baseline,'document.json':baseline}
    manifest={'format':'dobe-slides-project','version':1,'engine':pin(engine),'source_format':kind,'members':{name:record(value) for name,value in members.items()},'history':[]}
    result=pack(manifest,members);inspect_bytes(result);return result



def migrate(data,expected_sha256,*,engine):
    """Retain the exact old package and history; native verification remains required."""
    require(type(data) is bytes and type(expected_sha256) is str and source.sha(data)==expected_sha256,
            'portable migration hash is stale')
    before=inspect_bytes(data);old=before['manifest'];target=pin(engine)
    require(before['migration_count']<MAX_MIGRATIONS,'portable migration chain exceeds depth budget')
    migration_edge(old['engine'],target)
    members={name:value for name,value in before['members'].items() if name!='project.json'}
    members['predecessor.dobeslides']=data
    manifest={**old,'version':2,'engine':target,'members':{name:record(value) for name,value in members.items()},
              'migration':{'from_engine':old['engine'],'to_engine':target,'predecessor_sha256':before['sha256'],
                           'revision_count':len(old['history']),'current_sha256':before['current_sha256']}}
    result=pack(manifest,members);after=inspect_bytes(result)
    require(after['current_sha256']==before['current_sha256'],'portable migration changed the authored model')
    return result


def revise(data,expected_sha256,edits):
    require(type(data) is bytes and type(expected_sha256) is str and source.sha(data)==expected_sha256,'portable revision hash is stale')
    checked=inspect_bytes(data);manifest=checked['manifest'];require(len(manifest['history'])<MAX_HISTORY,'portable history exceeds budget')
    current=checked['members']['document.json'];change=revision.revise_bytes(current,source.sha(current),edits)
    members={name:value for name,value in checked['members'].items() if name!='project.json'};members['document.json']=change['data']
    manifest['members']['document.json']=record(change['data']);manifest['history'].append({'before':source.sha(current),'after':source.sha(change['data']),'edits':change['edits']})
    result=pack(manifest,members);after=inspect_bytes(result)
    require(after['members']['original.'+manifest['source_format']]==checked['members']['original.'+manifest['source_format']]
            and after['members']['baseline.json']==checked['members']['baseline.json'],'portable revision replaced original or baseline')
    return result


def require_engine(checked,installed_pin):
    require(checked['manifest']['engine']==pin(installed_pin),'portable source needs its pinned engine and source lock')


def checkout(root,destination,data,*,cancelled=lambda:False):
    checked=inspect_bytes(data);root=Path(root).resolve(strict=True);destination=Path(destination).absolute()
    try:relative=destination.relative_to(root)
    except ValueError as error:raise ValueError('Slides checkout must stay inside its owned attempt') from error
    require(relative.parts and '..' not in relative.parts,'checkout needs an attempt descendant')
    path=root
    for part in relative.parts:
        path/=part;require(not path.is_symlink(),'checkout cannot follow symbolic links')
    require(destination.parent.is_dir() and not destination.exists() and not cancelled(),'checkout needs a fresh destination and active attempt')
    destination.mkdir(mode=0o700);created=[]
    try:
        for name,value in checked['members'].items():
            require(not cancelled(),'checkout cancelled');path=destination/name
            with path.open('xb') as stream:created.append(path);stream.write(value);stream.flush();os.fsync(stream.fileno())
            require(write_container.read_bytes(path)==value,'checkout bytes differ from owned source')
        require(not cancelled(),'checkout cancelled')
    except BaseException:
        for path in reversed(created):path.unlink()
        destination.rmdir();raise
    return {'directory':str(destination),'project_sha256':checked['sha256'],'current_sha256':checked['current_sha256'],
            'source_sha256':checked['source_sha256'],'engine':checked['manifest']['engine'],'revision_count':checked['revision_count'],
            'engine_admission_complete':False,'pending_qualification':checked['pending_qualification']}
