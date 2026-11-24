"""Composite editable production inside the existing durable Dobe job boundary."""
import copy
import json
import re
from pathlib import Path
import shutil
import time
from . import construction_schema as schema
from . import offline
from .construction_support import sha, write, run, binary

OPERATIONS=tuple('construct.'+v for v in ('create','edit','inspect','render','verify'))
VERSION='1.0'

def adapter_fingerprints():
    paths=[*Path(__file__).parent.glob('construction*.py'),Path(__file__).with_name('offline.py')]
    return {p.name:sha(p) for p in paths}

# Snapshot at import, before authoring/rendering. Refuse publication if trusted
# adapter files change while this process is executing.
ADAPTER_FILES=adapter_fingerprints()

def validate(operation,params,source_revision):
    schema.require(operation in OPERATIONS and isinstance(params,dict),'Unsupported construction operation')
    schema.require((operation=='construct.create')==(source_revision is None),'Construction creation requires a new project; other operations require a source revision')
    if operation=='construct.create':
        schema.require(set(params)=={'document'},'Creation requires document');schema.validate(params['document'])
    elif operation=='construct.edit':
        schema.require({'document_sha256','edits'}<=set(params)<={'document_sha256','edits','import_assets'} and isinstance(params['document_sha256'],str) and len(params['document_sha256'])==64 and isinstance(params['edits'],list),'Revision requires expected document hash and edits')
        imports=params.get('import_assets',[]);schema.require(isinstance(imports,list) and len(imports)<=64 and all(isinstance(a,str) and re.fullmatch('[a-f0-9]{32}',a) for a in imports),'Invalid imported asset IDs')
    elif operation=='construct.render':
        schema.require(set(params)=={'outputs'} and isinstance(params['outputs'],list) and 1<=len(params['outputs'])<=32,'Render requires outputs')
        seen=set()
        for o in params['outputs']:
            schema.require(isinstance(o,dict) and {'component','format'}<=set(o)<= {'component','format','frame'} and o['format'] in ('png','mp4','riv','native'),'Invalid render output')
            schema.require(o['component'] not in seen,'Only one output request per component per job');seen.add(o['component'])
            if 'frame' in o:schema.require(type(o['frame']) is int and 0<=o['frame']<36000,'Invalid output frame')
    else:schema.require(params=={},'Inspection/verification takes no parameters')

def assets(operation,params):
    if operation=='construct.edit':
        imports=params.get('import_assets',[])
        schema.require(isinstance(imports,list) and len(imports)<=64 and all(isinstance(a,str) and re.fullmatch('[a-f0-9]{32}',a) for a in imports),'Invalid imported asset IDs')
        return {a:'construction/assets/'+a for a in imports}
    if operation!='construct.create':return {}
    result={}
    for n in schema.validate(params['document']):
        a=schema.adapter(n['engine'])
        if a:items=a.assets(n['engine']+'.create',n['parameters']) if hasattr(a,'assets') else {}
        elif n['engine']=='blender':
            from .construction_blender import assets
            items=assets(n['parameters'])
        else:items={}
        for aid in items:
            if aid not in n.get('inputs',{}):result[aid]='construction/assets/'+aid
    return result

def plan(document):
    ordered=schema.validate(document);steps=[]
    for n in ordered:
        engine=n['engine'];available=False;reason=None
        try:
            if engine in ('blender','rive'):binary(engine);available=True
            else:
                from . import photo
                available=shutil.which((photo if engine=='image' else schema.adapter(engine)).engine()) is not None
        except (ValueError,OSError) as e:reason=str(e)
        supported=['create','edit','inspect','render','verify'] if engine in ('blender','rive','image','video') else ['create']
        steps.append({'supported_operations':supported,'id':n['id'],'engine':engine,'available':available,'reason':reason,'depends_on':sorted({v['component'] for v in n.get('inputs',{}).values()}),'native_editability':True})
    return {'schema_version':1,'document_sha256':schema.digest(document),'steps':steps,'policy':schema.POLICY,'ready':all(n['available'] for n in steps),'model_requests':0,'creative_status':'review_required','scope':'Native profile fields are validated; installed engine and output quality require real execution'}

def assert_owned(root,path):
    path=Path(path);base=Path(root).resolve()
    schema.require(path.resolve().is_relative_to(base),'Component path escaped attempt')
    for p in [path,*path.parents]:
        if p==base:break
        schema.require(not p.is_symlink(),'Component symlink refused')
    return path

def inventory(directory):
    files={}
    for p in sorted(directory.rglob('*')):
        assert_owned(directory,p)
        if p.is_file() and not p.name.endswith('.blend1'):
            files[str(p.relative_to(directory))]={'sha256':sha(p),'bytes':p.stat().st_size}
    return files

def native_edit(engine,before,after):
    """Lower only edits the maintained native adapter can preserve precisely."""
    if engine=='image':
        old={o['name']:o for o in before['layers']};new={o['name']:o for o in after['layers']}
        schema.require(set(old)==set(new) and {k:v for k,v in before.items() if k!='layers'}=={k:v for k,v in after.items() if k!='layers'},'Image structural revision not supported by this native profile; use Blender construction')
        edits=[]
        for name,o in new.items():
            changes={k:v for k,v in o.items() if old[name].get(k)!=v};schema.require(set(changes)<= {'text','font','size','color','opacity','visible','mask'},'Unsupported native image revision')
            if changes:edits.append({'name':name,**changes})
        return 'image.edit',{'edits':edits}
    if engine=='video':
        schema.require(set(before)==set(after),'Video structure differs');edits=[]
        for field in ('width','height','fps','audio'):schema.require(before.get(field)==after.get(field),'Unsupported video setting revision')
        for collection in ('clips','titles'):
            old={o['name']:o for o in before.get(collection,[])};new={o['name']:o for o in after.get(collection,[])};schema.require(set(old)==set(new),'Video structural edit requires a supported native operation')
            for name,o in new.items():
                diff={k for k in set(o)|set(old[name]) if o.get(k)!=old[name].get(k)}
                if not diff:continue
                if collection=='titles' and diff=={'text'}:edits.append({'type':'text','name':name,'text':o['text']})
                elif collection=='clips' and diff=={'frames'}:edits.append({'type':'trim','name':name,'edge':'out','delta_frames':o['frames']-old[name]['frames']})
                else:raise ValueError('Unsupported video revision; unchanged source is retained')
        return 'video.edit',{'edits':edits}
    raise ValueError('Precise revision not yet qualified for native profile '+engine+'; no reconstruction fallback')

def run_native(root,node,mode,previous=None,output=None):
    engine=node['engine'];p=node['parameters']
    if engine in ('blender','rive'):
        if engine=='blender':from . import construction_blender as native
        else:from . import construction_rive as native
        return native.execute(root,p,mode,previous,output)
    native=schema.adapter(engine)
    if mode=='create':operation=engine+'.create';params=p
    elif mode=='edit':operation,params=native_edit(engine,previous,p)
    elif mode in ('inspect','verify','render'):
        if engine in ('video','motion'):return native.qualify(root,json.loads((root/'native/objects.json').read_text()))
        if engine=='image':
            from . import photo
            layers=native.read_native(root/'native/document.pcraft')
            before=photo.pixel_hash(root/'exports/document.png')
            photo.run(['photocraft-cli','convert','--no-gpu',str(root/'native/document.pcraft'),str(root/'exports/document.png')])
            schema.require(photo.pixel_hash(root/'exports/document.png')==before,'Cold reopen changed image pixels')
            return {'native_cold_reopen':True,'layers':len(layers),'pixels_preserved':True}
        raise ValueError('Cold reopen is not yet qualified for profile '+engine)
    else:raise ValueError('Unsupported mode')
    native.validate(operation,params,None if mode=='create' else 'source')
    result=native.execute(root,operation,params)
    schema.require(result['validation'].get('passed'),'Native construction failed validation')
    return result['validation']

def execute(root,operation,params):
    validate(operation,params,None if operation=='construct.create' else 'source');root=Path(root).resolve();start=time.monotonic()
    # All code, including maintained engine wrappers, inherits this OS boundary.
    if not offline.inherited():
        binary('blender') if operation=='construct.create' and any(n['engine']=='blender' for n in params['document']['components']) else None
        import subprocess,sys
        request=root/'construction-call.json';write(request,{'operation':operation,'params':params})
        command=offline.command([sys.executable,'-I','-B',str(Path(__file__).with_name('construction_boot.py')),str(root)])
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=86400)
        schema.require(result.returncode==0,'Offline construction failed: '+result.stderr.decode(errors='replace')[-1500:])
        return json.loads((root/'construction-result.json').read_text())
    base=root/'construction';base.mkdir(exist_ok=True);sources=base/'components';sources.mkdir(exist_ok=True)
    manifest_path=base/'manifest.json';old_manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {'components':{}}
    if operation=='construct.create':document=copy.deepcopy(params['document']);old=None
    else:
        old=json.loads((base/'document.json').read_text());schema.require(schema.digest(old)==old_manifest['document_sha256'],'Construction document integrity differs')
        for cid,record in old_manifest['components'].items():
            for path,facts in record['files'].items():schema.require(sha(assert_owned(base,sources/cid/path))==facts['sha256'],'Retained component file changed')
        document=schema.revise(old,params['edits']) if operation=='construct.edit' else copy.deepcopy(old)
        if operation=='construct.edit':schema.require(schema.digest(old)==params['document_sha256'],'Construction revision precondition failed')
    ordered=schema.validate(document);old_nodes={n['id']:n for n in old['components']} if old else {};outputs={o['component']:o for o in params.get('outputs',[])}
    schema.require(set(outputs)<={n['id'] for n in ordered},'Unknown render component')
    records={};changed=set();events=[]
    for n in ordered:
        cid=n['id'];folder=sources/cid;previous=old_nodes.get(cid);mode=None
        dependency_changed=any(records[link['component']]['files'].get(link['artifact']) != old_manifest['components'].get(link['component'],{}).get('files',{}).get(link['artifact']) for link in n.get('inputs',{}).values())
        if previous is None:folder.mkdir();mode='create'
        elif previous!=n or dependency_changed:mode='edit'
        elif operation in ('construct.verify','construct.inspect'):mode='inspect' if n['engine'] in ('blender','rive') else 'verify'
        elif cid in outputs:mode='render'
        schema.require(previous is None or previous['engine']==n['engine'],'Changing a native engine requires a new component')
        a=schema.adapter(n['engine'])
        if a:inputs=a.assets(n['engine']+'.create',n['parameters']) if hasattr(a,'assets') else {}
        elif n['engine']=='blender':
            from .construction_blender import assets as inputs_for
            inputs=inputs_for(n['parameters'])
        else:inputs={}
        for aid,destination in inputs.items():
            link=n.get('inputs',{}).get(aid)
            if link:
                schema.require(link['artifact'] in records[link['component']]['files'],'Handoff references an unpublished component artifact')
                src=sources/link['component']/link['artifact']
            else:src=base/'assets'/aid
            schema.require(src.is_file(),'Construction asset missing: '+aid);dst=assert_owned(folder,folder/destination);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        if mode:
            if mode=='edit' and dependency_changed and n['engine'] not in ('blender','rive'):
                if n['engine'] in ('video','motion') and previous==n:mode='render'
                else:raise ValueError('Dependency changed; this native profile cannot precisely replace linked media with simultaneous structural edits')
            # Rendering uses native saved source. It cannot silently author a new document.
            output=outputs.get(cid)
            if output and output.get('frame',0)>=n['parameters'].get('frames',36000):raise ValueError('Output frame is outside document')
            if output and 'frame' in output:schema.require(n['engine']=='blender' and output['format']=='png','Frame selection requires a Blender PNG output')
            if output: schema.require(output['format'] in (('png','mp4','native') if n['engine']=='blender' else ('riv','native','png') if n['engine']=='rive' else ('native','mp4') if n['engine']=='video' else ('native','png')),'Output format not supported by profile')
            validation=run_native(folder,n,mode,previous['parameters'] if previous else None,output)
            changed.add(cid)
        else:validation=old_manifest['components'][cid]['validation']
        records[cid]={'engine':n['engine'],'parameters_sha256':schema.digest(n['parameters']),'files':inventory(folder),'validation':validation}
        events.append({'component':cid,'action':mode or 'reused','native_preserved':mode=='reused' or mode is None})
    # Removed components are absent from the new manifest; original revisions remain immutable.
    for cid in set(old_nodes)-set(records):shutil.rmtree(sources/cid)
    write(base/'document.json',document)
    schema.require(adapter_fingerprints()==ADAPTER_FILES,'Construction adapter changed during execution; retry with an immutable package')
    provenance=dict(ADAPTER_FILES)
    provenance['support.json']=sha(Path(__file__).with_name('construction_data')/'support.json')
    manifest={'supporting_engines':json.loads((Path(__file__).with_name('construction_data')/'support.json').read_text()),'adapter_files':provenance,'schema_version':1,'document_sha256':schema.digest(document),'policy':schema.POLICY,'components':records,'events':events,'engine':'construction','creative_status':'review_required','model_requests':0,'worker_seconds':round(time.monotonic()-start,3)}
    write(manifest_path,manifest)
    artifacts=[]
    for p in sorted(base.rglob('*')):
        assert_owned(base,p)
        if not p.is_file() or p.name.endswith('.blend1'):continue
        relative=str(p.relative_to(root));role='native' if '/native/' in relative or p.name=='document.json' else 'export' if '/exports/' in relative else 'asset'
        artifacts.append({'path':relative,'role':role})
    return {'artifacts':artifacts,'engine':{'name':'construction','version':VERSION},'validation':{'passed':True,'construction_integrity':True,'creative_status':'review_required','model_requests':0}}
