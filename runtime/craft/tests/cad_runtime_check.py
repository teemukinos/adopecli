#!/usr/bin/env python3
"""Exercise CAD through separate CLI/MCP clients, real workers and native code."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--staged',action='store_true'); args=parser.parse_args()
    out=args.output.resolve(); resources=out/'fixture/DobeCLI/lib/dobe'; runtime=resources/'runtime'
    sha=lambda data:hashlib.sha256(data).hexdigest()
    if not args.staged:
        out.mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1]/'runtime/studio_runtime',runtime/'studio_runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(args.engine.resolve().parent.parent,resources/'engines/cad')
        data=(resources/'engines/cad/engine.json').read_bytes(); meta=json.loads(data)
        manifest={'schema_version':1,'product':'dobe','distribution':'dobe-cli','platform':'macos-arm64','release_signed':False,
            'qualification':'test-layout-only-not-installed','components':[{'name':'dobe-cad','version':meta['version'],
            'source_lock_sha256':meta['source_lock_sha256'],'engine_manifest_sha256':sha(data)}],'files':{}}
        for path in resources.rglob('*'):
            if path.is_file(): manifest['files'][path.relative_to(resources.parent.parent).as_posix()]={'bytes':path.stat().st_size,'sha256':sha(path.read_bytes())}
        (resources/'bundle.json').write_text(json.dumps(manifest,sort_keys=True)+'\n')
        raise SystemExit(subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--staged','--engine',str(args.engine.resolve()),'--output',str(out)],timeout=300).returncode)
    sys.path.insert(0,str(runtime))
    from studio_runtime import cad, cad_admission as admission, cad_project as project, cad_revision as revision, cad_parametric as panel, cad_solid as solid
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    from studio_runtime import execution
    state=out/'state'; store=Store(state); checks=[]; refusals=[]; jobs=[]
    os.environ['PATH']='/usr/bin:/bin'; os.environ['STUDIO_BUNDLE_RESOURCES']=str(out/'untrusted')
    def check(label,condition):
        if not condition: raise AssertionError(label)
        checks.append(label)
    def refused(label,action):
        try: action()
        except ValueError as error: refusals.append({'case':label,'error':str(error)})
        else: raise AssertionError('accepted '+label)
    def request(method,params):
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n').encode(),capture_output=True,timeout=30)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        value=json.loads(result.stdout)
        if 'error' in value: raise AssertionError(value)
        return value['result']
    def call(name,params):
        value=request('tools/call',{'name':'dope_'+name,'arguments':params})
        if value.get('isError'): raise ValueError(value['content'][0]['text'])
        return json.loads(value['content'][0]['text'])
    def cli(*arguments):
        code="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),'--state',str(state),*map(str,arguments)],capture_output=True,timeout=30)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout)
    def job(owner,operation,params,key,previous=None,success=True):
        arguments={'project':owner,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous: arguments['source_revision']=previous['id']
        submitted=call('submit_job',arguments)
        check(key+' idempotent after client exit',call('submit_job',arguments)['id']==submitted['id'])
        Worker(store).run_one(); actual=call('get_job',{'job':submitted['id']}); jobs.append(actual)
        check(key+' durable outcome '+str(actual.get('error')),actual['state']==('succeeded' if success else 'failed'))
        if not success:
            check(key+' no partial publication',actual['result_revision'] is None and store.get_project('local',owner)['head']==(previous['id'] if previous else None)); return actual
        result=call('get_revision',{'revision':actual['result_revision']}); validation=result['validation']
        check(key+' native model and admission verified',validation['native_model_equal'] and validation['profile_admission_complete']
              and not validation['general_admission_complete'] and not validation['general_manufacturing_qualified'])
        return result
    def checkout(name,rev):
        path=out/name; call('export_project',{'revision':rev['id'],'destination':str(path)}); return path
    def asset(owner,data,name):
        path=out/name; path.write_bytes(data); return store.import_asset('local',owner,path)['id']
    def portable(folder): return (folder/'native/project.dobecad').read_bytes()
    try:
        tools=request('tools/list',{})['tools']; operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        check('same MCP endpoint exposes all nine CAD operations',set(cad.OPERATIONS)<=set(operations))
        capabilities=cli('capabilities')['applications']['cad']
        check('capabilities expose exact scope and no installed claim',capabilities['available'] and not capabilities['installed_qualification'] and capabilities['export_formats']==['dobecad','obj'])
        owner=call('create_project',{'name':'Parametric solid'})['id']
        first=job(owner,'cad.create',{'recipe':solid.RECIPE,'version':1,'width':120,'height':80,'depth':12},'create')
        initial=checkout('created',first); original=portable(initial); checked=project.inspect_bytes(original)
        check('creation retains sketch plus actual native solid history',checked['revision_count']==1 and first['validation']['native_solid_regeneration_verified'])
        edit={'expected_sha256':sha(original),'edits':[{'kind':'parameter.expression','name':name,'expected':old,'value':value}
              for name,old,value in (('width','120','150'),('height','80','90'))]}
        path=out/'edit.json'; path.write_text(json.dumps(edit)); submitted=cli('submit',owner,'cad.edit','--parameters',path,'--key','parameters','--source',first['id'])
        Worker(store).run_one(); actual=cli('job',submitted['id']); jobs.append(actual); check('CLI submission continues after client exit',actual['state']=='succeeded')
        second=cli('revision',actual['result_revision']); parameters=checkout('parameters',second); parameter_bytes=portable(parameters)
        check('parameter edits preserve original geometry and require solve',project.inspect_bytes(parameter_bytes)['current']['document']['model']==checked['current']['document']['model']
              and not second['validation']['native_constraint_solve_verified'] and not second['validation']['native_solid_regeneration_verified'])
        job(owner,'cad.export',{'format':'obj','expected_sha256':sha(parameter_bytes)},'unsolved-export',second,False)
        third=job(owner,'cad.solve',{'expected_sha256':sha(parameter_bytes)},'solve',second); solved=checkout('solved',third); solved_bytes=portable(solved)
        check('native solve moves sketch but preserves old mesh',third['validation']['native_constraint_solve_verified'] and not third['validation']['native_solid_regeneration_verified']
              and project.inspect_bytes(solved_bytes)['current']['document']['model'][-1]==checked['current']['document']['model'][-1])
        job(owner,'cad.export',{'format':'obj','expected_sha256':sha(solved_bytes)},'stale-mesh-export',third,False)
        fourth=job(owner,'cad.solid',{'expected_sha256':sha(solved_bytes),'depth':20},'solid',third); generated=checkout('generated',fourth); final=portable(generated)
        delivered=job(owner,'cad.export',{'format':'obj','expected_sha256':sha(final)},'obj',fourth); folder=checkout('delivery',delivered)
        measurement=solid.inspect_obj((folder/'exports/panel.obj').read_bytes(),width=150,height=90,depth=20)
        check('delivered native OBJ has revised independent dimensions and volume',measurement['measurements']['volume_mm3']==270000
              and measurement['measurements']['surface_area_mm2']==36600 and delivered['validation']['geometry_delivery_verified'])
        inspected=job(owner,'cad.inspect',{},'inspect',delivered); bundled=job(owner,'cad.bundle',{},'bundle',inspected); bundle=checkout('bundle',bundled)
        check('editable portable delivery and original remain byte-exact',(bundle/'exports/drawing.dobecad').read_bytes()==final
              and (bundle/'native/original.json').read_bytes()==checked['members']['original.json'] and portable(initial)==original)
        check('original recipe remains caller-owned and unchanged',(bundle/'recipes/cad-production.json').read_bytes()==(initial/'recipes/cad-production.json').read_bytes())
        check('scratch and input artifacts never publish',not any(f['path'].startswith(('.cad-attempt-','inputs/')) for f in bundled['files']))
        for kind,data in (('dobecad',final),('json',checked['members']['original.json'])):
            recipient=call('create_project',{'name':'CAD '+kind+' transfer'})['id']; uploaded=asset(recipient,data,'import.'+kind)
            imported=job(recipient,'cad.import',{'asset':uploaded,'format':kind},'import-'+kind); imported_folder=checkout('imported-'+kind,imported)
            check(kind+' exact original transfer',portable(imported_folder)==data if kind=='dobecad' else (imported_folder/'native/original.json').read_bytes()==data)
            if kind=='dobecad':
                next_revision=job(recipient,'cad.solid',{'expected_sha256':sha(data),'depth':25},'transferred-revision',imported)
                check('transferred solid remains editable',next_revision['parent']==imported['id'])
        moved=store.import_project('local',bundle,'Whole CAD project'); job(moved['project']['id'],'cad.inspect',{},'whole-transfer',moved['revision'])
        job(owner,'cad.edit',edit,'stale-revision',bundled,False)
        # Actual retained build4 provenance edge; this fixture owns defaults only.
        old_pin={**cad.binding.PIN,'source_lock_sha256':'46620256f0d0de9e29a4275df32af29f2809885efa8631243ce4a7ff821d60d9'}
        legacy=project.create(checked['members']['original.json'],'json',engine=old_pin)
        recipient=call('create_project',{'name':'Explicit CAD migration'})['id']; uploaded=asset(recipient,legacy,'legacy.dobecad')
        job(recipient,'cad.import',{'asset':uploaded,'format':'dobecad'},'old-pin-refused',success=False)
        migrated=job(recipient,'cad.migrate',{'asset':uploaded,'expected_sha256':sha(legacy)},'migration'); migrated_folder=checkout('migrated',migrated)
        migrated_bytes=portable(migrated_folder); transition=project.inspect_bytes(migrated_bytes)
        check('durable migration retains exact predecessor and original',transition['members']['predecessor.dobecad']==legacy
              and transition['members']['original.json']==checked['members']['original.json'] and migrated['validation']['engine_migration_verified'])
        job(recipient,'cad.migrate',{'expected_sha256':sha(migrated_bytes)},'nested-migration',migrated,False)
        job(recipient,'cad.solid',{'expected_sha256':sha(migrated_bytes),'depth':8},'migrated-production',migrated)
        # Native line/circle/text authoring is also supported, independently of
        # the constrained-panel recipe. Exercise every admitted geometry kind.
        primitive=admission.base(); common=panel.create(primitive,1,1)['document']['model'][0]['common']
        primitive['model']=[{'handle':256+i,'common':copy.deepcopy(common),'kind':kind} for i,kind in enumerate([
            {'type':'line','a':panel.point(-5,2),'b':panel.point(125,2)},
            {'type':'circle','center':panel.point(40,20),'radius':15.0},
            {'type':'text','insert':panel.point(0,60),'alignPt':None,'height':5.0,'value':'Panel Ø 30 — retained text',
             'rotation':0.0,'widthFactor':1.0,'oblique':0.0,'style':'Standard','halign':'left','valign':'baseline'}])]
        primitive['handseed']=259; plain_owner=call('create_project',{'name':'Editable drafting primitives'})['id']
        plain=job(plain_owner,'cad.create',{'document':primitive},'primitives'); plain_folder=checkout('primitives',plain); plain_bytes=portable(plain_folder)
        changes=[{'kind':'geometry.set','handle':257,'expected':primitive['model'][1]['kind'],'set':{'radius':20}},
                 {'kind':'text.replace','handle':258,'expected':primitive['model'][2]['kind']['value'],'value':'Panel Ø 40 — revised text'},
                 {'kind':'entity.properties','handle':256,'expected':{'layer':'0','visible':True,'ltscale':1.0,'thickness':0.0},
                  'set':{'layer':'Defpoints','visible':False,'ltscale':2,'thickness':3}}]
        revised=job(plain_owner,'cad.edit',{'expected_sha256':sha(plain_bytes),'edits':changes},'primitive-revision',plain)
        revised_folder=checkout('primitive-revision',revised); exact=copy.deepcopy(primitive)
        exact['model'][0]['common'].update(layer='Defpoints',visible=False,ltscale=2.0,thickness=3.0)
        exact['model'][1]['kind']['radius']=20.0; exact['model'][2]['kind']['value']='Panel Ø 40 — revised text'
        check('native primitive revision preserves exact unrelated state and Unicode',revision.canonical(project.inspect_bytes(portable(revised_folder))['current']['document'])==revision.canonical(exact))
        job(plain_owner,'cad.solve',{'expected_sha256':sha(portable(revised_folder))},'nonparametric-solve-refused',revised,False)
        sketch_owner=call('create_project',{'name':'Already solved sketch'})['id']
        sketch_created=job(sketch_owner,'cad.create',{'recipe':panel.RECIPE,'version':1,'width':120,'height':80},'sketch-create')
        sketch_folder=checkout('sketch-create',sketch_created); sketch_data=portable(sketch_folder)
        noop=job(sketch_owner,'cad.solve',{'expected_sha256':sha(sketch_data)},'already-solved',sketch_created); noop_folder=checkout('already-solved',noop)
        check('already solved sketch records actual native verification without inventing edits',portable(noop_folder)==sketch_data and noop['validation']['native_constraint_solve_verified'])
        # A model rejected only in an intermediate state must not reach native
        # code even when the final value returns to an admitted value.
        source_model=checked['members']['original.json']; sketch=project.create(source_model,'json',engine=cad.binding.PIN); handle=checked['current']['document']['model'][0]['handle']
        bad_history=sketch
        for before,after in ((1.0,1e5),(1e5,1.0)):
            bad_history=project.revise(bad_history,sha(bad_history),[{'kind':'entity.properties','handle':handle,'expected':{'ltscale':before},'set':{'ltscale':after}}])
        admission.inspect(project.inspect_bytes(bad_history)['members']['document.json'])
        refused('unsafe intermediate state cannot hide behind restored current model',lambda:admission.inspect_project(project.inspect_bytes(bad_history)))
        bad_model=json.loads(source_model); bad_model['portable_fonts']=True
        bad_owner=call('create_project',{'name':'Unadmitted source'})['id']; bad_asset=asset(bad_owner,revision.encoded(bad_model),'bad.json')
        job(bad_owner,'cad.import',{'asset':bad_asset,'format':'json'},'unadmitted',success=False)
        refused('cross-project asset',lambda:call('submit_job',{'project':owner,'operation':'cad.import','parameters':{'asset':bad_asset,'format':'json'},'idempotency_key':'foreign'}))
        for label,data,kind in (('unadmitted source',revision.encoded(bad_model),'json'),('unadmitted intermediate',bad_history,'dobecad')):
            attempt=out/label.replace(' ','-'); attempt.mkdir(); input_path=attempt/cad.assets('cad.import',{'asset':bad_asset})[bad_asset]
            input_path.parent.mkdir(); input_path.write_bytes(data)
            with patch.object(cad.cad_engine,'Engine',side_effect=AssertionError('native execution before admission')):
                refused(label+' before any native probe',lambda:cad.execute(attempt,'cad.import',{'asset':bad_asset,'format':kind}))
            check(label+' no native or temporary output',not (attempt/'native').exists() and not list(attempt.glob('.cad-attempt-*')))
        for label,mutate in [
            ('unknown root',lambda d:d.update(future=True)),('integer coordinate',lambda d:d['model'][0]['kind']['b'].update(x=120)),
            ('boolean coordinate',lambda d:d['model'][0]['kind']['b'].update(x=True)),('coordinate bound',lambda d:d['model'][0]['kind']['b'].update(x=1e7)),
            ('unknown entity property',lambda d:d['model'][0]['common'].update(future=True)),('unknown geometry field',lambda d:d['model'][0]['kind'].update(future=True)),
            ('unowned layer',lambda d:d['model'][0]['common'].update(layer='Missing')),('boolean visibility',lambda d:d['model'][0]['common'].update(visible=1)),
            ('system font',lambda d:d['text_styles'][0].update(font='/tmp/font.ttf')),('unowned raster',lambda d:d['rasters'].update(image={'width':1,'height':1,'rgba':[0,0,0,255],'opaque':True})),
            ('paper entity',lambda d:d['layouts'][0]['entities'].append({**copy.deepcopy(d['model'][0]),'handle':1})),
            ('parameter expression',lambda d:d['parametric']['parameters'][0].update(expr='1+2')),('parameter underflow',lambda d:d['parametric']['parameters'][0].update(expr='1e-300')),
            ('unknown constraint field',lambda d:d['constraints'][0].update(future=True)),('changed fixed origin',lambda d:d['model'][0]['kind']['a'].update(x=.01)),
            ('note text budget',lambda d:d.update(read_notes=['x'*4096]*25)),('header numeric type',lambda d:d['header']['vars'].update(INSUNITS=4.0))]:
            value=json.loads(source_model); mutate(value); refused(label,lambda value=value:admission.inspect(revision.encoded(value)))
        for label,op,params,src in [('caller executable','cad.inspect',{'engine':'/tmp/engine'},'source'),('unsupported DXF','cad.import',{'asset':bad_asset,'format':'dxf'},None),
            ('raw path','cad.import',{'asset':'/tmp/model','format':'json'},None),('boolean recipe version','cad.create',{'recipe':panel.RECIPE,'version':True,'width':120,'height':80},None),
            ('caller solve geometry','cad.edit',{'expected_sha256':sha(final),'edits':[{'kind':'panel.solve'}]},'source'),('missing source','cad.solve',{'expected_sha256':sha(final)},None)]:
            refused(label,lambda op=op,params=params,src=src:cad.validate(op,params,src))
        receipt=resources/'bundle.json'; original_receipt=receipt.read_bytes(); broken=json.loads(original_receipt)
        broken['files']['lib/dobe/engines/cad/bin/dobe-cad']['sha256']='0'*64; receipt.write_text(json.dumps(broken))
        try: job(owner,'cad.inspect',{},'damaged-receipt',bundled,False)
        finally: receipt.write_bytes(original_receipt)
        job(owner,'cad.inspect',{},'restored-receipt',bundled)
        # Persist every registered execution and prove terminal groups are gone.
        with store.transaction() as db:
            attempts=[dict(r) for r in db.execute('SELECT a.*,e.process_group FROM attempts a JOIN attempt_executions e ON a.token=e.token')]
        (out/'attempts.json').write_text(json.dumps(attempts,indent=2)+'\n')
        check('all durable attempts terminal with process groups absent',len(attempts)==len(jobs) and all(a['finished'] is not None
              and execution.wait_group_absent(a['process_group']) for a in attempts))
        check('native pack binary remains exact',sha(args.engine.read_bytes())==sha((resources/'engines/cad/bin/dobe-cad').read_bytes()))
        evidence={'passed':True,'checks':checks,'refusals':refusals,'durable_jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),
            'operations':list(cad.OPERATIONS),'public_tools':len(tools),'admission_before_native':True,'all_history_states_admitted':True,
            'obj_delivery_independently_measured':True,'explicit_source_pin_migration_qualified':True,'process_groups_gone':True,
            'distribution_layout_fixture':True,'installed_qualification':False,'general_admission_complete':False,'remote_actions':False,'goal_complete':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n'); print(json.dumps({'checks':len(checks),'refusals':len(refusals),'jobs':len(jobs),'succeeded':evidence['succeeded']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals},indent=2)+'\n'); raise
    finally: (out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__': main()
