#!/usr/bin/env python3
"""Qualify durable Slides CLI/MCP operations and pre-execution model admission."""
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
    for name in ('engine','recipe','native-source','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--legacy-project',type=Path);parser.add_argument('--pdf-engine',type=Path);parser.add_argument('--staged',action='store_true');args=parser.parse_args()
    out=args.output.resolve();resources=out/'fixture/DobeCLI/lib/dobe';runtime=resources/'runtime';sha=lambda b:hashlib.sha256(b).hexdigest()
    if not args.staged:
        out.mkdir(parents=True);shutil.copytree(Path(__file__).resolve().parents[1]/'runtime/studio_runtime',runtime/'studio_runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(args.engine.resolve().parent.parent,resources/'engines/slides');metadata_bytes=(resources/'engines/slides/engine.json').read_bytes();metadata=json.loads(metadata_bytes)
        manifest={'schema_version':1,'product':'dobe','distribution':'dobe-cli','platform':'macos-arm64','release_signed':False,
            'qualification':'test-layout-only-not-installed','components':[{'name':'dobe-slides','version':metadata['version'],
            'source_lock_sha256':metadata['source_lock_sha256'],'engine_manifest_sha256':sha(metadata_bytes)}],'files':{}}
        if args.pdf_engine:
            shutil.copytree(args.pdf_engine.resolve().parent.parent,resources/'engines/pdf')
            pdf_bytes=(resources/'engines/pdf/engine.json').read_bytes();pdf_meta=json.loads(pdf_bytes)
            manifest['components'].append({'name':'dobe-pdf','version':pdf_meta['version'],'source_lock_sha256':pdf_meta['source_lock_sha256'],'engine_manifest_sha256':sha(pdf_bytes)})
        for path in resources.rglob('*'):
            if path.is_file():manifest['files'][path.relative_to(resources.parent.parent).as_posix()]={'bytes':path.stat().st_size,'sha256':sha(path.read_bytes())}
        (resources/'bundle.json').write_text(json.dumps(manifest,sort_keys=True)+'\n')
        command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--staged']
        for key in ('engine','recipe','native_source','output'):command.extend(['--'+key.replace('_','-'),str(getattr(args,key).resolve())])
        if args.pdf_engine:command.extend(['--pdf-engine',str(args.pdf_engine.resolve())])
        if args.legacy_project:command.extend(['--legacy-project',str(args.legacy_project.resolve())])
        raise SystemExit(subprocess.run(command,timeout=300).returncode)
    sys.path.insert(0,str(runtime))
    from studio_runtime import slides,slides_admission as admission,slides_project as project,slides_revision as revision
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    state=out/'state';store=Store(state);checks=[];refusals=[];jobs=[];recipe=json.loads(args.recipe.read_bytes());compiled=slides.recipes.compile_recipe(recipe)
    model=compiled['document'];original_native=args.native_source.read_bytes();os.environ['PATH']='/usr/bin:/bin';os.environ['STUDIO_BUNDLE_RESOURCES']=str(out/'untrusted')
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def request(method,params):
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        r=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n').encode(),capture_output=True,timeout=30)
        if r.returncode:raise AssertionError(r.stderr.decode()[:1000])
        value=json.loads(r.stdout)
        if 'error' in value:raise AssertionError(value)
        return value['result']
    def call(name,params):
        value=request('tools/call',{'name':'dope_'+name,'arguments':params})
        if value.get('isError'):raise ValueError(value['content'][0]['text'])
        return json.loads(value['content'][0]['text'])
    def cli(*arguments):
        code="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
        r=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),'--state',str(state),*map(str,arguments)],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError(r.stderr.decode()[:1000])
        return json.loads(r.stdout)
    def job(identity,operation,params,key,previous=None,success=True):
        arguments={'project':identity,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:arguments['source_revision']=previous['id']
        submitted=call('submit_job',arguments);check(key+' idempotent across client exits',call('submit_job',arguments)['id']==submitted['id'])
        Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
        check(key+' durable outcome '+str(actual.get('error')),actual['state']==('succeeded' if success else 'failed'))
        if not success:
            check(key+' publishes no partial revision',actual['result_revision'] is None and store.get_project('local',identity)['head']==(previous['id'] if previous else None));return actual
        result=call('get_revision',{'revision':actual['result_revision']});v=result['validation']
        check(key+' binds admission and full native preservation',v['profile_admission_complete'] and v['native_model_equal'] and v['native_cold_reopen']
              and not v['general_admission_complete'] and v['render_qualified']==(operation=='slides.export'));return result
    def checkout(name,rev):
        path=out/name;call('export_project',{'revision':rev['id'],'destination':str(path)});return path
    def asset(identity,data,name):
        path=out/name;path.write_bytes(data);return store.import_asset('local',identity,path)['id']
    try:
        tools=request('tools/list',{})['tools'];operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        check('same product MCP exposes all registered Slides operations',set(slides.OPERATIONS)<=set(operations))
        capabilities=cli('capabilities')['applications']['slides'];check('capabilities state exact admitted scope and uninstalled qualification',capabilities['available']
            and capabilities['profile_admission_complete'] and not capabilities['general_admission_complete'] and capabilities['render_qualified'] and not capabilities['installed_qualification'])
        identity=call('create_project',{'name':'Slides proposal'})['id'];first=job(identity,'slides.create',recipe,'create')
        initial=checkout('created',first);portable=(initial/'native/project.dobeslides').read_bytes()
        check('recipe persists complete editable model and caller-owned provenance',project.inspect_bytes(portable)['current']['document']==model
              and json.loads((initial/'recipes/slides-production.json').read_bytes())['request']==compiled['request'])
        numeric=json.loads((initial/'exports/inspection.json').read_bytes())['pptx_precision']
        check('durable inspection discloses PPTX precision without rewriting source',numeric['source_model_sha256']==sha((initial/'native/document.json').read_bytes()) and numeric['change_count']==1 and numeric['changes'][0]['converted_value']==48.83 and not numeric['source_changed'] and not numeric['complete_semantic_projection'])
        path=compiled['selectors']['sections'][1]['paragraphs']['runs'][0];text=revision.locate(model,path)['text'];start=text.encode().index(b'launch line')
        edit={'expected_sha256':sha(portable),'edits':[{'kind':'text.replace','path':path,'start':start,'end':start+11,'expected':'launch line','value':'opening sentence'}]}
        params=out/'edit.json';params.write_text(json.dumps(edit));submitted=cli('submit',identity,'slides.edit','--parameters',params,'--key','edit','--source',first['id'])
        Worker(store).run_one();actual=cli('job',submitted['id']);jobs.append(actual);check('CLI revision survives submitting process exit',actual['state']=='succeeded')
        second=cli('revision',actual['result_revision']);edited=checkout('edited',second);prediction=copy.deepcopy(model);revision.locate(prediction,path)['text']=text.replace('launch line','opening sentence')
        check('exact paragraph revision preserves every other field',json.loads((edited/'native/document.json').read_bytes())==prediction)
        third=job(identity,'slides.inspect',{},'inspect',second);fourth=job(identity,'slides.bundle',{},'bundle',third);delivered=checkout('delivered',fourth)
        data=(delivered/'native/project.dobeslides').read_bytes();check('portable delivery remains editable and byte-exact',(delivered/'exports/presentation.dobeslides').read_bytes()==data)
        check('original and production configuration remain exact',(delivered/'native/original.json').read_bytes()==(initial/'native/original.json').read_bytes()
              and (delivered/'recipes/slides-production.json').read_bytes()==(initial/'recipes/slides-production.json').read_bytes())
        check('published first revision stays immutable',call('get_revision',{'revision':first['id']})==first)
        check('native scratch and inputs never publish',not any(f['path'].startswith(('.slides-attempt-','inputs/')) for f in fourth['files']))
        for kind,content in (('dobeslides',data),('json',compiled['data']),('deckcraft',original_native)):
            owner=call('create_project',{'name':'Import '+kind})['id'];uploaded=asset(owner,content,'import.'+kind)
            imported=job(owner,'slides.import',{'asset':uploaded,'format':kind},'import-'+kind);folder=checkout('imported-'+kind,imported)
            native=(folder/'native/project.dobeslides').read_bytes();read=project.inspect_bytes(native)
            check(kind+' input bytes remain authoritative',native==content if kind=='dobeslides' else read['members']['original.'+kind]==content)
            if kind=='dobeslides':
                current=read['current']['document'];run=revision.locate(current,path);old=run['text'];pos=old.encode().index(b'opening sentence')
                next_edit={'expected_sha256':sha(native),'edits':[{'kind':'text.replace','path':path,'start':pos,'end':pos+16,'expected':'opening sentence','value':'campaign line'}]}
                revised=job(owner,'slides.edit',next_edit,'portable-edit',imported);check('portable project is editable after transfer',revised['parent']==imported['id'])
        transfer=store.import_project('local',delivered,'Whole Slides project');job(transfer['project']['id'],'slides.inspect',{},'whole-transfer',transfer['revision'])
        job(identity,'slides.edit',edit,'stale',fourth,False)
        bad=copy.deepcopy(model);bad['slides'][0]['shapes'][2]['click']={'url':'https://example.invalid'}
        bad_owner=call('create_project',{'name':'Unsupported model'})['id'];bad_asset=asset(bad_owner,revision.encoded(bad),'unadmitted.json')
        job(bad_owner,'slides.import',{'asset':bad_asset,'format':'json'},'unadmitted',success=False)
        refused('cross-project source asset',lambda:call('submit_job',{'project':identity,'operation':'slides.import','parameters':{'asset':bad_asset,'format':'json'},'idempotency_key':'foreign'}))
        # A direct adapter attempt proves the admission refusal happens before
        # even constructing the native observer, not merely before publication.
        attempt=out/'pre-execution';attempt.mkdir();input_path=attempt/slides.assets('slides.import',{'asset':bad_asset})[bad_asset];input_path.parent.mkdir();input_path.write_bytes(revision.encoded(bad))
        with patch.object(slides.slides_engine,'Engine',side_effect=AssertionError('native execution before admission')):
            refused('unsupported source refused before any native process',lambda:slides.execute(attempt,'slides.import',{'asset':bad_asset,'format':'json'}))
        check('pre-execution refusal leaves no native output',not (attempt/'native').exists() and not list(attempt.glob('.slides-attempt-*')))
        for label,mutate in [('unknown model field',lambda d:d.update(futureField=1)),('altered master',lambda d:d['masters'][0].update(name='changed')),
            ('embedded font',lambda d:d['embeddedFonts'].append({})),('unowned resource',lambda d:d['media'].append({'id':999,'name':'x','contentType':'image/png','link':'https://example.invalid','dataHex':''})),
            ('custom shape path',lambda d:d['slides'][0]['shapes'][2].update(geom={'kind':'custom','path':'M0 0'})),
            ('table execution',lambda d:d['slides'][0]['shapes'][2].update(kind={'type':'table'})),
            ('shape effects',lambda d:d['slides'][0]['shapes'][2].update(effects={})),
            ('unknown system font',lambda d:d['slides'][0]['shapes'][2]['text']['paragraphs'][0]['runs'][0]['props'].update(font='System face')),
            ('native auto shrink',lambda d:d['slides'][0]['shapes'][2]['text']['body'].update(autofit={'kind':'shrink'})),
            ('text byte budget',lambda d:d['slides'][0]['shapes'][2]['text']['paragraphs'][0]['runs'][0].update(text='x'*100001)),
            ('boolean geometry',lambda d:d['slides'][0]['shapes'][2]['xfrm'].update(w=True)),
            ('boolean color channel',lambda d:d['slides'][0]['shapes'][0]['fill']['color']['base']['rgb'].update(r=True)),
            ('unsupported cached field',lambda d:d['slides'][0]['shapes'][2]['text']['paragraphs'][0]['runs'][0].update(kind={'kind':'field','field':'slidenum'}))]:
            bad_model=copy.deepcopy(model);mutate(bad_model);refused(label,lambda d=bad_model:admission.inspect(revision.encoded(d)))
        for label,op,params,src in [('caller engine path','slides.inspect',{'engine':'/tmp/engine'},'source'),('unsupported PPTX','slides.import',{'asset':bad_asset,'format':'pptx'},None),
            ('raw source path','slides.import',{'asset':'/tmp/source','format':'json'},None),('missing revision','slides.edit',edit,None),('creation over source','slides.create',recipe,'source')]:
            refused(label,lambda op=op,params=params,src=src:slides.validate(op,params,src))
        receipt=resources/'bundle.json';receipt_bytes=receipt.read_bytes();damaged=json.loads(receipt_bytes);damaged['files']['lib/dobe/engines/slides/bin/dobe-slides']['sha256']='0'*64;receipt.write_text(json.dumps(damaged))
        try:job(identity,'slides.inspect',{},'damaged-receipt',fourth,False)
        finally:receipt.write_bytes(receipt_bytes)
        job(identity,'slides.inspect',{},'restored-receipt',fourth)
        # Export is a durable revision with independently decoded outputs. Use
        # a separate imported project so earlier revision/head assertions remain
        # evidence for the original exact sequence.
        export_owner=call('create_project',{'name':'Slides delivery'})['id'];export_asset=asset(export_owner,data,'export-input.dobeslides')
        export_base=job(export_owner,'slides.import',{'asset':export_asset,'format':'dobeslides'},'export-import')
        png_revision=job(export_owner,'slides.export',{'format':'png','slides':[3,1],'scale':1.25},'png-export',export_base)
        png_folder=checkout('png-export',png_revision);delivery=json.loads((png_folder/'exports/delivery/delivery.json').read_bytes())
        check('PNG delivery preserves requested order and exact geometry',delivery['selected_slides']==[3,1] and delivery['effective_scale']==1.25
              and all(item['width']==1200 and item['height']==675 and item['cold_bytes_equal'] for item in delivery['outputs']))
        check('PNG delivery binds text owners, real font bytes and source',delivery['visible_plain_text_owners_equal'] and delivery['actual_font_bytes_verified']
              and delivery['text_layout_clear'] and (png_folder/'native/project.dobeslides').read_bytes()==data)
        if args.pdf_engine:
            pdf_revision=job(export_owner,'slides.export',{'format':'pdf'},'pdf-export',png_revision);pdf_folder=checkout('pdf-export',pdf_revision)
            pdf_report=json.loads((pdf_folder/'exports/delivery/delivery.json').read_bytes())
            check('PDF delivery independently verifies every page twice',len(pdf_report['independent_pdf_checks'])==2
                  and all(len(pass_['text_checks'])==5 for pass_ in pdf_report['independent_pdf_checks']) and pdf_report['complete_output_decode'] and pdf_report['font_embedding_checked'])
            check('PDF delivery leaves native originals unchanged',(pdf_folder/'native/project.dobeslides').read_bytes()==data)
            export_head=pdf_revision
        else:export_head=png_revision
        # Source authoring retains the requested text even when its eventual
        # export must fail: no truncation, auto-shrink or partial publication.
        overflow_model=copy.deepcopy(model);overflow_model['slides'][0]['shapes'][2]['text']['paragraphs'][0]['runs'][0]['text']='A very long title. '*100
        overflow_owner=call('create_project',{'name':'Overflow refusal'})['id'];overflow_source=job(overflow_owner,'slides.create',{'document':overflow_model},'overflow-source')
        job(overflow_owner,'slides.export',{'format':'png','slides':[1]},'overflow-export',overflow_source,False)
        missing_model=copy.deepcopy(model);missing_model['slides'][0]['shapes'][2]['text']['paragraphs'][0]['runs'][0]['text']='Missing \U0010ffff'
        missing_owner=call('create_project',{'name':'Missing glyph refusal'})['id'];missing_source=job(missing_owner,'slides.create',{'document':missing_model},'missing-source')
        job(missing_owner,'slides.export',{'format':'png','slides':[1]},'missing-export',missing_source,False)
        job(export_owner,'slides.export',{'format':'png','slides':[32]},'missing-slide',export_head,False)
        for label,params in [('null slide selection',{'format':'png','slides':None}),('boolean slide',{'format':'png','slides':[True]}),('repeated slide',{'format':'png','slides':[1,1]}),
            ('nonfinite scale',{'format':'png','scale':float('inf')}),('caller output path',{'format':'png','path':'/tmp/out.png'}),
            ('unqualified PPTX delivery',{'format':'pptx'}),('partial PDF',{'format':'pdf','slides':[1]})]:
            refused(label,lambda params=params:slides.validate('slides.export',params,'source'))
        check('failed delivery attempts publish no probes',not any('/probes/' in item['path'] for item in png_revision['files']))
        if args.legacy_project:
            legacy_bytes=(args.legacy_project/'native/project.dobeslides').read_bytes();legacy_checked=project.inspect_bytes(legacy_bytes)
            legacy=call('import_project',{'bundle':str(args.legacy_project),'name':'Legacy Slides migration'})
            owner=legacy['project']['id'];old_revision=legacy['revision']
            job(owner,'slides.inspect',{},'legacy-pin-refusal',old_revision,False)
            job(owner,'slides.migrate',{'expected_sha256':'0'*64},'stale-migration',old_revision,False)
            migrated=job(owner,'slides.migrate',{'expected_sha256':sha(legacy_bytes)},'legacy-migration',old_revision)
            folder=checkout('migrated',migrated);migrated_bytes=(folder/'native/project.dobeslides').read_bytes();checked=project.inspect_bytes(migrated_bytes)
            check('explicit migration preserves exact predecessor archive, model and full edit history',checked['manifest']['version']==2
                and checked['members']['predecessor.dobeslides']==legacy_bytes and checked['members']['document.json']==legacy_checked['members']['document.json']
                and checked['manifest']['history']==legacy_checked['manifest']['history'] and migrated['validation']['engine_migration_verified'])
            check('legacy revision and original production provenance remain immutable',call('get_revision',{'revision':old_revision['id']})==old_revision
                and (folder/'recipes/slides-production.json').read_bytes()==(args.legacy_project/'recipes/slides-production.json').read_bytes())
            inspected=job(owner,'slides.inspect',{},'migrated-inspection',migrated)
            selected=compiled['selectors']['sections'][1]['paragraphs']['runs'][0];before=revision.locate(checked['current']['document'],selected)['text'];pos=before.encode().index(b'opening sentence')
            changed=job(owner,'slides.edit',{'expected_sha256':sha(migrated_bytes),'edits':[{'kind':'text.replace','path':selected,'start':pos,'end':pos+16,'expected':'opening sentence','value':'approved message'}]},'migrated-edit',inspected)
            revised=checkout('migrated-revised',changed);edited_bytes=(revised/'native/project.dobeslides').read_bytes();edited_project=project.inspect_bytes(edited_bytes)
            check('post-migration edit extends original history and retains predecessor bytes',edited_project['revision_count']==legacy_checked['revision_count']+1
                and edited_project['members']['predecessor.dobeslides']==legacy_bytes and b'approved message' in edited_project['members']['document.json'])
            job(owner,'slides.migrate',{'expected_sha256':sha(edited_bytes)},'nested-migration',changed,False)
            recipient=call('create_project',{'name':'Legacy portable migration'})['id'];uploaded=asset(recipient,legacy_bytes,'legacy.dobeslides')
            imported=job(recipient,'slides.migrate',{'asset':uploaded,'expected_sha256':sha(legacy_bytes)},'asset-migration')
            imported_folder=checkout('asset-migrated',imported)
            check('owned-asset migration produces the same deterministic portable bytes',(imported_folder/'native/project.dobeslides').read_bytes()==migrated_bytes)
            moved=store.import_project('local',revised,'Migrated whole project transfer')
            job(moved['project']['id'],'slides.inspect',{},'migrated-transfer',moved['revision'])
            job(export_owner,'slides.migrate',{'expected_sha256':sha(data)},'same-engine-migration',export_head,False)
            forged=copy.deepcopy(checked['manifest']);payload={k:v for k,v in checked['members'].items() if k!='project.json'}
            for label,key,value in [('wrong migration predecessor','predecessor_sha256','0'*64),('wrong migration revision boundary','revision_count',999),('boolean migration boundary','revision_count',True),('wrong migration model','current_sha256','1'*64)]:
                altered=copy.deepcopy(forged);altered['migration'][key]=value
                refused(label,lambda altered=altered:project.inspect_bytes(project.pack(altered,payload)))
            altered=copy.deepcopy(forged);nested=dict(payload);nested['predecessor.dobeslides']=migrated_bytes;altered['members']['predecessor.dobeslides']=project.record(migrated_bytes)
            refused('nested portable migration envelope',lambda:project.inspect_bytes(project.pack(altered,nested)))
            bad_pin=copy.deepcopy(legacy_checked['manifest']);bad_pin['engine']['source_lock_sha256']='1'*64
            unsupported=project.pack(bad_pin,{k:v for k,v in legacy_checked['members'].items() if k!='project.json'})
            refused('unknown engine migration transition',lambda:project.migrate(unsupported,sha(unsupported),engine=slides.binding.PIN))
            with patch.object(project,'MAX_REPLAY',legacy_checked['replayed_bytes']*3//2):
                refused('migration aggregate replay budget',lambda:project.inspect_bytes(migrated_bytes))
            refused('caller selected migration engine',lambda:slides.validate('slides.migrate',{'expected_sha256':sha(legacy_bytes),'engine':bad_pin['engine']},'source'))
            refused('migration asset conflicts with source revision',lambda:slides.validate('slides.migrate',{'asset':uploaded,'expected_sha256':sha(legacy_bytes)},'source'))
            check('legacy fixture remains byte-exact after migration', (args.legacy_project/'native/project.dobeslides').read_bytes()==legacy_bytes)
        check('maintained native source and binary remain exact',args.native_source.read_bytes()==original_native and sha(args.engine.read_bytes())==sha((resources/'engines/slides/bin/dobe-slides').read_bytes()))
        evidence={'passed':True,'checks':checks,'refusals':refusals,'durable_jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),
            'operations':list(slides.OPERATIONS),'public_tools':len(tools),'admission_before_native':True,'distribution_layout_fixture':True,
            'installed_qualification':False,'explicit_source_pin_migration_qualified':bool(args.legacy_project),'png_delivery_qualified':True,'pdf_delivery_qualified':bool(args.pdf_engine),'general_admission_complete':False,'remote_actions':False,'goal_complete':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'checks':len(checks),'refusals':len(refusals),'jobs':len(jobs),'succeeded':evidence['succeeded']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals},indent=2)+'\n');raise
    finally:(out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
