"""Explicit offline open-weight inference. Unprovisioned installations fail closed."""
import json
from pathlib import Path
import re
import shutil
import sys
from .production_schema import fields, require, number
from .construction_schema import digest, relative
from .construction_support import sha, write
from .construction import inventory
from .production import measured_run

VERSION = '1.0'
OPERATIONS = ('synthesis.generate', 'synthesis.edit')
POLICY = {'network':'offline', 'media_generation':'local-open-weights', 'compute':'local'}
MODEL = 'stabilityai/stable-diffusion-xl-base-1.0'
CONFIG = Path(__file__).with_name('production_data')/'synthesis-runtime.json'

def recipe(d):
    fields(d, ('schema_version','policy','model','prompt','negative_prompt','width','height','steps','seed','guidance'))
    require(type(d['schema_version']) is int and d['schema_version']==1 and d['policy']==POLICY and d['model']==MODEL, 'Explicit local open-weight policy and SDXL profile required')
    for key in ('prompt','negative_prompt'):
        require(isinstance(d[key],str) and len(d[key]) <= 4000 and '\0' not in d[key], 'Invalid synthesis prompt')
    require(d['prompt'].strip(), 'Prompt is empty')
    for k in ('width','height'): require(type(d[k]) is int and 512 <= d[k] <= 1024 and d[k]%64==0, 'SDXL dimensions must be multiples of 64, 512–1024')
    require(type(d['steps']) is int and 10 <= d['steps'] <= 50 and type(d['seed']) is int and 0 <= d['seed'] < 2**31,'Invalid inference steps/seed')
    number(d['guidance'],1,15)
    return d

def validate(operation, parameters, source_revision):
    require(operation in OPERATIONS and (operation=='synthesis.generate')==(source_revision is None), 'Generation requires no source; editing requires a synthesis revision')
    if operation=='synthesis.generate': fields(parameters,('document',));recipe(parameters['document'])
    else:
        fields(parameters,('image_sha256','mask_asset','prompt','negative_prompt','seed','strength'))
        require(isinstance(parameters['image_sha256'],str) and re.fullmatch('[a-f0-9]{64}',parameters['image_sha256']), 'Expected source image hash')
        require(isinstance(parameters['mask_asset'],str) and re.fullmatch('[a-f0-9]{32}',parameters['mask_asset']), 'Mask must be an imported project asset')
        for k in ('prompt','negative_prompt'):require(isinstance(parameters[k],str) and len(parameters[k])<=4000 and '\0' not in parameters[k], 'Invalid edit prompt')
        require(parameters['prompt'].strip() and type(parameters['seed']) is int and 0 <= parameters['seed'] < 2**31,'Invalid edit seed/prompt')
        number(parameters['strength'],.1,1)

def assets(operation, parameters):
    return {parameters['mask_asset']:'incoming-synthesis-mask'} if operation=='synthesis.edit' else {}

def provision():
    require(sys.platform=='darwin', 'GPU-host OS network isolation has not been qualified; this adapter currently admits macOS only')
    require(CONFIG.is_file(), 'SDXL is not provisioned: authorize and install the reviewed local runtime and model manifest first')
    c=json.loads(CONFIG.read_text())
    fields(c,('schema_version','python','python_sha256','weights','files','model','revision','license','device','versions'))
    require(type(c['schema_version']) is int and c['schema_version']==1 and c['model']==MODEL and c['license']=='openrail++', 'Unsupported synthesis provision')
    require(isinstance(c['revision'],str) and re.fullmatch('[a-f0-9]{40}',c['revision']), 'Pin the complete upstream model revision')
    require(c['device'] in ('cpu','mps'), 'This local host profile supports CPU/MPS; CUDA requires separate host qualification')
    python=Path(c['python']); weights=Path(c['weights'])
    require(python.is_absolute() and python.is_file() and sha(python)==c['python_sha256'], 'Synthesis interpreter differs from provision')
    require(weights.is_absolute() and weights.is_dir() and isinstance(c['files'],dict) and 1 <= len(c['files']) <= 256, 'Missing bounded weights manifest')
    require(set(c['versions'])=={'torch','diffusers','transformers','safetensors','accelerate','Pillow'}, 'Pin inference runtime versions')
    actual={str(p.relative_to(weights)) for p in weights.rglob('*') if p.is_file()}
    require(actual==set(c['files']) and 'model_index.json' in actual and 'LICENSE.md' in actual, 'Weights inventory differs or license/config missing')
    for name, expected in c['files'].items():
        relative(name); path=weights/name
        require(path.suffix in ('.json','.txt','.safetensors','.md') and not path.is_symlink() and path.resolve().is_relative_to(weights.resolve()), 'Only local safetensors, tokenizer/config and license files are admitted')
        require(isinstance(expected,str) and re.fullmatch('[a-f0-9]{64}',expected) and sha(path)==expected, 'Model file hash differs')
    return c

def plan(document):
    recipe(document)
    try: c=provision(); ready=True; reason=None
    except (ValueError,OSError,KeyError,TypeError) as e: c=None;ready=False;reason=str(e)
    return {'route':'synthesis','ready':ready,'reason':reason,'policy':POLICY,'model':MODEL,'device':c['device'] if c else None,'editable_native':False,'output':'raster PNG and reproducible recipe','qualification':'inference and visual quality unqualified','installed_qualification':False,'gpu_worker_qualified':False,'supabase_gpu_qualified':False,'paid_model_api_required':False}

def execute(root, operation, parameters):
    validate(operation,parameters,None if operation=='synthesis.generate' else 'source')
    c=provision(); provision_hash=digest(c); root=Path(root).resolve(); base=root/'synthesis'
    adapters={p.name:sha(p) for p in Path(__file__).parent.glob('synthesis*.py')}
    if operation=='synthesis.generate':
        base.mkdir()
        for folder in ('exports','inputs','logs'): (base/folder).mkdir()
        d=parameters['document']
    else:
        manifest=json.loads((base/'manifest.json').read_text())
        for name, facts in manifest['files'].items():
            relative(name); p=base/name
            require(p.resolve().is_relative_to(base) and not p.is_symlink() and sha(p)==facts['sha256'],'Synthesis source integrity differs')
        source=base/'exports/photograph.png'; require(sha(source)==parameters['image_sha256'],'Source image precondition failed')
        shutil.copyfile(source,base/'inputs/source.png'); shutil.copyfile(root/'incoming-synthesis-mask',base/'inputs/mask.png')
        d=json.loads((base/'recipe.json').read_text()); d.update({k:parameters[k] for k in ('prompt','negative_prompt','seed')});recipe(d)
    write(base/'recipe.json',d)
    write(base/'call.json',{'mode':operation.split('.')[1], 'provision':c, 'strength':parameters.get('strength')})
    measurement=measured_run(base,[c['python'],'-I','-B',Path(__file__).with_name('synthesis_engine.py'),base],'inference')
    measurement['device']=c['device']; measurement['gpu_seconds']=0 if c['device']=='cpu' else None
    require(digest(provision())==provision_hash,'Synthesis provision changed during inference')
    require(adapters=={p.name:sha(p) for p in Path(__file__).parent.glob('synthesis*.py')},'Synthesis adapter changed during inference')
    result=json.loads((base/'engine-result.json').read_text())
    # GPU timing is measured by the runner; wall time is not called GPU usage.
    write(base/'metrics.json',{'process':measurement,'inference':result,'paid_provider_requests':0,'model_requests':1,'output_reused':False})
    files=inventory(base);files.pop('manifest.json',None)
    write(base/'manifest.json',{'schema_version':1,'files':files,'recipe_sha256':digest(d),'model':MODEL,'model_revision':c['revision'],'model_files':c['files'],'license':c['license'],'versions':c['versions'],'adapters':adapters,'policy':POLICY,'creative_status':'review_required','native_editability':False})
    return {'artifacts':[{'path':'synthesis/'+name,'role':'recipe' if name=='recipe.json' else 'export' if name.startswith('exports/') else 'asset'} for name in inventory(base)], 'engine':{'name':'open-weight-synthesis','version':VERSION},'validation':{'passed':True,'raster_only':True,'creative_status':'review_required',**result}}
