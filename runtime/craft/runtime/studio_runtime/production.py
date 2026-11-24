"""Photographic 3D adapter using the existing durable Store and worker."""
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
from . import production_schema as schema
from .construction_support import binary, DATA, sha, write
from . import offline
from .construction import inventory

VERSION = '1.1'
OPERATIONS = tuple('production.' + name for name in ('create', 'edit', 'render', 'verify','inspect'))

def validate(operation, parameters, source_revision):
    schema.require(operation in OPERATIONS, 'Unsupported production operation')
    schema.require((operation == 'production.create') == (source_revision is None), 'Creation requires no source; production revisions require a source')
    if operation == 'production.create':
        schema.fields(parameters, ('document',)); schema.validate(parameters['document'])
    elif operation == 'production.edit':
        schema.fields(parameters, ('recipe_sha256','edits'))
        schema.require(isinstance(parameters['recipe_sha256'],str) and __import__('re').fullmatch('[a-f0-9]{64}',parameters['recipe_sha256']), 'Expected recipe hash')
        schema.require(isinstance(parameters['edits'],list) and 1 <= len(parameters['edits']) <= 64, 'Expected bounded edits')
        for edit in parameters['edits']:
            schema.validate_edit(edit)
    else: schema.fields(parameters, ())

def assets(operation, parameters): return {}

def plan(document):
    schema.validate(document)
    try: binary('blender'); available = True; reason = None
    except (ValueError, OSError) as e: available = False; reason = str(e)
    return {'route':'blender', 'profile':schema.PROFILE, 'recipe_sha256':schema.digest(document), 'ready':available, 'reason':reason, 'operations':list(OPERATIONS), 'policy':schema.POLICY, 'editable_native':True, 'device':'CPU', 'creative_status':'review_required', 'qualification':'bounded local 3D profile; visual acceptance is separate'}

def measured_run(root, argv, label):
    start = time.monotonic(); before = resource.getrusage(resource.RUSAGE_CHILDREN)
    log_path = root/'logs'/f'{label}.log'
    with log_path.open('wb') as log:
        process = subprocess.Popen(offline.command(argv), cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        try:
            while process.poll() is None:
                schema.require(time.monotonic()-start < 7200 and log_path.stat().st_size < 32<<20, 'Production exceeds time/log budget')
                time.sleep(.1)
            schema.require(process.returncode == 0, 'Production engine failed: '+log_path.read_text(errors='replace')[-1600:])
        finally:
            if process.poll() is None: process.kill(); process.wait()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {'step':label, 'wall_seconds':round(time.monotonic()-start,3), 'cpu_user_seconds':round(usage.ru_utime-before.ru_utime,3), 'cpu_system_seconds':round(usage.ru_stime-before.ru_stime,3), 'peak_child_rss_bytes':int(usage.ru_maxrss if sys.platform=='darwin' else usage.ru_maxrss*1024), 'rss_scope':'maximum child high-water mark in this adapter process; not aggregate concurrent memory', 'device':'CPU', 'gpu_seconds':0, 'energy_kwh':None, 'energy_measurement':'unavailable', 'network':'denied'}

def fingerprints():
    paths=[*Path(__file__).parent.glob('production*.py'),
           Path(__file__).with_name('construction_support.py'),Path(__file__).with_name('offline.py')]
    return {p.name:sha(p) for p in paths}

def execute(root, operation, parameters):
    validate(operation, parameters, None if operation == 'production.create' else 'source')
    adapter_hashes = fingerprints(); root = Path(root).resolve(); base = root/'production'
    if operation == 'production.create':
        base.mkdir(); document = parameters['document']
        for folder in ('native','exports','logs','fonts'): (base/folder).mkdir()
        for name in ('archivo-variable.ttf','archivo-OFL.txt'): shutil.copyfile(DATA/'fonts'/name,base/'fonts'/name)
    else:
        manifest = json.loads((base/'manifest.json').read_text())
        for path, facts in manifest['files'].items():
            target=base/path
            schema.require(target.resolve().is_relative_to(base) and not target.is_symlink() and sha(target)==facts['sha256'], 'Production artifact integrity differs')
        document = json.loads((base/'recipe.json').read_text())
        schema.require(schema.digest(document)==manifest['recipe_sha256'], 'Recipe integrity differs')
        if operation == 'production.edit':
            schema.require(parameters['recipe_sha256']==schema.digest(document),'Production recipe precondition failed')
            document = schema.revise(document, parameters['edits'])
    schema.validate(document); write(base/'recipe.json',document)
    mode='views' if operation=='production.inspect' else operation.split('.')[1]; script=Path(__file__).with_name('production_blender_engine.py')
    def invoke(mode, label):
        result_path = base/'engine-result.json'
        result_path.unlink(missing_ok=True)
        write(base/'call.json',{'mode':mode})
        measurement=measured_run(base,[binary('blender'),'-b','--factory-startup','--disable-autoexec','-t','8','--python-exit-code','1','-P',script,'--',base],label)
        result = json.loads(result_path.read_text())
        schema.require(isinstance(result, dict) and result.get('native_cold_reopen') is (mode not in ('create', 'edit')), 'Production result does not match the current invocation')
        if mode == 'verify':
            schema.require(result.get('reproduced_pixels') is True, 'Production verification did not reproduce the retained pixels')
        return measurement, result
    measurement,result=invoke(mode,mode); measures=[measurement]
    measurement,cold=invoke('inspect','cold-reopen'); measures.append(measurement)
    schema.require(cold['native_cold_reopen'],'Native scene was not reopened')
    schema.require(adapter_hashes==fingerprints(),'Production adapter changed during execution')
    write(base/'metrics.json',{'steps':measures,'paid_provider_requests':0,'model_requests':0,'output_reused':False})
    files=inventory(base); files.pop('manifest.json',None)
    manifest={'schema_version':1,'profile':schema.PROFILE,'recipe_sha256':schema.digest(document),'files':files,'adapters':adapter_hashes,'supporting_engines':json.loads((DATA/'support.json').read_text()),'policy':schema.POLICY,'result':result,'creative_status':'review_required'}
    write(base/'manifest.json',manifest)
    artifacts=[{'path':'production/'+p,'role':'native' if p.startswith('native/') or p=='recipe.json' else 'export' if p.startswith('exports/') else 'asset'} for p in inventory(base)]
    return {'artifacts':artifacts,'engine':{'name':'photographic-production','version':VERSION},'validation':{**result,'passed':True,'native_cold_reopen':True,'creative_status':'review_required'}}
