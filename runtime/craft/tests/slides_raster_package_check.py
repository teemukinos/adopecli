#!/usr/bin/env python3
"""Installed owned pictures, precise revisions, migration chains and rollback.

Uses a new isolated installation and its launchd supervisor. No developer PATH,
remote provider or GUI is used. Packages and all job evidence remain on disk.
"""
import argparse
import hashlib
import ctypes
import copy
import json
import io
import os
from pathlib import Path
import random
import signal
import sqlite3
import subprocess
import sys
import time
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True,type=Path);parser.add_argument('--previous',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--prior',required=True,type=Path,help='Actual previously migrated portable project with a later authored edit')
    parser.add_argument('--reuse-from',type=Path,help='Prior failed fixture with a confirmed uninstalled service and retained releases')
    args=parser.parse_args();root=args.output.resolve();root.mkdir();installation=root/'installation'
    if args.reuse_from:
        prior_run=args.reuse_from.resolve();cleanup=json.loads((prior_run/'cleanup.json').read_bytes())
        assert (prior_run/'failure.json').is_file() and cleanup['exit_code']==0
        receipt=json.loads(cleanup['stdout']);installation=prior_run/'installation'
        assert receipt['uninstalled'] and receipt['projects_retained'] and receipt['data_location']==str(installation/'state')
    new=args.package.resolve()/'bin/dobe';old=args.previous.resolve()/'bin/dobe'
    env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin'};checks=[];jobs=[];installed=False
    previous_version=json.loads((args.previous/'lib/dobe/bundle.json').read_bytes())['version']
    def command(exe,*arguments):
        result=subprocess.run([str(exe),*map(str,arguments)],env=env,capture_output=True,text=True,timeout=120)
        assert result.returncode==0,(arguments,result.stdout,result.stderr)
        return json.loads(result.stdout)
    def local(*arguments,exe=new):return command(exe,'local','--root',installation,*arguments)
    def runtime(*arguments):return command(installation/'current/bin/dobe','--state',installation/'state',*arguments)
    def exchange(method,params):
        request=[{'jsonrpc':'2.0','id':0,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
                 {'jsonrpc':'2.0','id':1,'method':method,'params':params}]
        result=subprocess.run([str(installation/'current/bin/dobe'),'--state',str(installation/'state'),'mcp'],env=env,
                              input=''.join(json.dumps(row)+'\n' for row in request),capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        init,response=map(json.loads,result.stdout.splitlines())
        assert init['result']['serverInfo']['name']=='dobe-runtime' and 'error' not in response,response
        return response['result']
    def tool(name,arguments):
        result=exchange('tools/call',{'name':'dope_'+name,'arguments':arguments});assert not result.get('isError'),result
        return json.loads(result['content'][0]['text'])
    def submit(project,operation,params,source=None):
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':'slides-'+str(len(jobs))}
        if source:arguments['source_revision']=source
        job=tool('submit_job',arguments);assert tool('submit_job',arguments)['id']==job['id'];jobs.append(job);return job
    def settle(job,expected='succeeded'):
        # Poll the same persisted job until its authoritative terminal state.
        # A slow observation is not permission to restart or discard execution.
        while True:
            state=runtime('job',job['id'])
            (root/'progress.json').write_text(json.dumps({'job':job['id'],'operation':job['operation'],'state':state['state'],'completed_jobs':sum(j.get('state')=='succeeded' for j in jobs)})+'\n')
            if state['state'] not in ('queued','running','validating'):
                assert state['state']==expected,state
                jobs[next(i for i,item in enumerate(jobs) if item['id']==job['id'])]=state
                return runtime('revision',state['result_revision']) if state.get('result_revision') else state
            time.sleep(.2)
    library=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
    library.proc_listpids.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_int]
    library.proc_pidpath.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32]
    def live_export(job,component,native_command):
        executable=installation/'current/lib/dobe/engines'/component/('bin/dobe-'+component)
        executable=executable.resolve()
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                row=db.execute('SELECT e.process_group FROM attempt_executions e JOIN jobs j ON j.token=e.token WHERE j.id=?',(job['id'],)).fetchone()
            if row and row[0]:
                group=row[0];pids=(ctypes.c_int*256)();size=library.proc_listpids(2,group,pids,ctypes.sizeof(pids))
                assert 0<=size<ctypes.sizeof(pids)
                for pid in pids[:size//4]:
                    if pid<=1:continue
                    path=ctypes.create_string_buffer(4096)
                    if library.proc_pidpath(pid,path,len(path))<=0 or path.value.decode()!=str(executable):continue
                    try:
                        if os.getpgid(pid)!=group:continue
                        os.kill(pid,signal.SIGSTOP)
                        argv=subprocess.run(['/bin/ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout.strip()
                        if argv.startswith(str(executable)+' '+native_command+' '):
                            supervisor=int(subprocess.check_output(['/bin/ps','-o','ppid=','-p',str(group)],text=True).strip())
                            return {'native_pid':pid,'group':group,'supervisor_pid':supervisor,'executable':str(executable),'command':native_command}
                        os.kill(pid,signal.SIGCONT)
                    except ProcessLookupError:pass
            # Avoid invoking a fresh CLI every millisecond while observing a
            # short real native process. Read only the owned persisted status.
            with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                state=db.execute('SELECT state FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]
            assert state in ('queued','running','validating'),state
            time.sleep(.001)
        raise AssertionError('no confirmed live native export child')
    def absent(group):
        # macOS can report EPERM briefly during process teardown. Keep the
        # production positive-absence rule: wait for ESRCH, never accept EPERM.
        assert execution.wait_group_absent(group,timeout=20),'native group cleanup remains unproven'
        return True
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def checkout(label,revision):
        target=root/label;runtime('checkout',revision['id'],target);return target
    def pixel(path,point,expected):
        with Image.open(path) as image:actual=image.convert('RGB').getpixel(point)
        assert max(abs(a-b) for a,b in zip(actual,expected))<=3,(path,point,actual,expected)
    try:
        local('install','--allow-unsigned',exe=old);installed=True
        local('install','--allow-unsigned')
        caps=runtime('capabilities');assert len(caps['applications'])==17 and all(a['available'] for a in caps['applications'].values())
        assert caps['applications']['slides']['production_recipes'][0]['id']=='production_proposal'
        assert caps['applications']['slides']['explicit_engine_migration_available']
        assert caps['applications']['slides']['owned_picture_formats']==['png','jpeg']
        tools=exchange('tools/list',{})['tools'];assert len(tools)==15
        operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        assert len([name for name in operations if name.startswith('slides.')])==7
        checks.append('seventeen bundled engines and seven Slides operations use the same fifteen MCP tools without developer PATH')
        resources=installation/'current/lib/dobe';sys.path.insert(0,str(resources/'runtime'))
        from studio_runtime import slides,slides_revision as revision,slides_project,slides_engine,write_exports,write_binding,execution
        recipe={'recipe':'production_proposal','version':1,'title':'Picture study',
                'sections':[{'heading':'Owned assets','paragraphs':['Exact bytes. Editable placement.']}]}
        model=slides.recipes.compile_recipe(recipe)['document'];model['slides']=model['slides'][:1]
        project=tool('create_project',{'name':'Installed owned pictures'})['id']
        created=settle(submit(project,'slides.create',{'document':model}));initial=checkout('created',created)
        image=Image.frombytes('RGB',(1024,512),random.Random(42).randbytes(1024*512*3))
        image.paste((231,65,35),(0,0,512,64));image.paste((43,154,110),(512,0,1024,64))
        buffer=io.BytesIO();image.save(buffer,format='PNG');image_bytes=buffer.getvalue();assert len(image_bytes)>1<<20
        picture_source=root/'owned-large.png';picture_source.write_bytes(image_bytes)
        image_asset=runtime('import-asset',project,picture_source)['id']
        insertion={'kind':'picture.insert','path':'/slides/0','expected':hashlib.sha256(revision.encoded(model['slides'][0])).hexdigest(),
                   'value':{'image':{'asset':image_asset,'sha256':sha(picture_source),'name':'Owned large.png','contentType':'image/png'},
                            'transform':{'x':400.0,'y':180.0,'w':256.0,'h':128.0}}}
        added=settle(submit(project,'slides.edit',{'expected_sha256':sha(initial/'native/project.dobeslides'),'edits':[insertion]},created['id']))
        inserted=checkout('inserted',added);with_image=json.loads((inserted/'native/document.json').read_bytes())
        shape_path='/slides/0/shapes/'+str(len(with_image['slides'][0]['shapes'])-1)
        picture=revision.locate(with_image,shape_path);media=with_image['media'][0]
        assert bytes.fromhex(media['dataHex'])==image_bytes and added['validation']['native_model_equal']
        assert (inserted/'native/original.json').read_bytes()==(initial/'native/original.json').read_bytes()
        assert len(slides_project.inspect_bytes((inserted/'native/project.dobeslides').read_bytes())['members']['project.json'])>1<<20
        inspected=settle(submit(project,'slides.inspect',{},added['id']))
        png=settle(submit(project,'slides.export',{'format':'png'},inspected['id']));raster=checkout('png',png)
        pdf=settle(submit(project,'slides.export',{'format':'pdf'},png['id']));printed=checkout('pdf',pdf)
        for output in (raster,printed):
            delivery=json.loads((output/'exports/delivery/delivery.json').read_bytes())
            assert delivery['slide_count']==1 and delivery['actual_font_bytes_verified'] and delivery['text_layout_clear']
            assert delivery['pictures'][0]['source_sha256']==sha(picture_source)
        pixel(raster/'exports/delivery/slide-001.png',(432,188),(231,65,35))
        pixel(raster/'exports/delivery/slide-001.png',(624,188),(43,154,110))
        reader_root=root/'pdf-reader';reader_root.mkdir()
        native=slides_engine.Engine(root=reader_root,**slides.binding.resolve());pdf_path=reader_root/'presentation.pdf'
        pdf_path.write_bytes((printed/'exports/delivery/presentation.pdf').read_bytes())
        with write_exports.PDFReader(reader_root,write_binding.resolve_pdf()['executable'],native) as reader:
            document,_=reader.open(pdf_path);preview=reader_root/'preview.png';reader.render(document,1,preview)
        pixel(preview,(432,188),(231,65,35));pixel(preview,(624,188),(43,154,110))
        checks.append('installed MCP inserts a project-scoped image larger than one MiB; native PNG and independently rasterized PDF preserve both image regions')
        original=(initial/'native/original.json').read_bytes()
        buffer=io.BytesIO();Image.new('RGB',(64,32),(37,91,207)).save(buffer,format='JPEG');replacement_bytes=buffer.getvalue()
        edits=[{'kind':'picture.crop','path':shape_path,'expected':[0.0]*4,'value':[.5,0.0,0.0,0.0]},
               {'kind':'picture.replace','path':shape_path,'expected':{'media':media['id'],'sha256':sha(picture_source)},
                'value':{'name':'Owned replacement.jpeg','contentType':'image/jpeg','dataHex':replacement_bytes.hex()}},
               {'kind':'shape.transform','path':shape_path,'expected':picture['xfrm'],'value':{**picture['xfrm'],'x':480.0,'w':192.0}}]
        # Edits that share an owner are intentionally separate optimistic
        # revisions. The production API refuses competing changes in one batch.
        current=pdf;current_folder=printed
        for index,(label,edit) in enumerate(zip(('cropped','replaced','edited'),edits)):
            params=root/(label+'-edit.json')
            params.write_text(json.dumps({'expected_sha256':sha(current_folder/'native/project.dobeslides'),'edits':[edit]}))
            prior_model=(current_folder/'native/document.json').read_bytes()
            predicted=revision.revise_bytes(prior_model,hashlib.sha256(prior_model).hexdigest(),[edit])['document']
            changed=runtime('submit',project,'slides.edit','--parameters',params,'--key','installed-cli-edit-'+str(index),'--source',current['id'])
            jobs.append(changed);changed=settle(changed);edited=checkout(label,changed)
            assert json.loads((edited/'native/document.json').read_bytes())==predicted
            current=changed;current_folder=edited
        assert json.loads((edited/'native/document.json').read_bytes())==predicted
        assert (edited/'native/original.json').read_bytes()==original and predicted['media'][0]==media
        assert predicted['slides'][0]['shapes'][:-1]==with_image['slides'][0]['shapes'][:-1]
        assert bytes.fromhex(predicted['media'][1]['dataHex'])==replacement_bytes
        assert revision.locate(predicted,shape_path)['kind']['fill']['crop']==[.5,0.0,0.0,0.0]
        bundled=settle(submit(project,'slides.bundle',{},changed['id']));portable=checkout('bundle',bundled)
        other=tool('create_project',{'name':'Installed portable presentation'})['id'];asset=runtime('import-asset',other,portable/'exports/presentation.dobeslides')['id']
        imported=settle(submit(other,'slides.import',{'asset':asset,'format':'dobeslides'}));returned=checkout('returned',imported)
        assert (returned/'native/document.json').read_bytes()==(edited/'native/document.json').read_bytes()
        assert (returned/'native/original.json').read_bytes()==original
        rendered=settle(submit(other,'slides.export',{'format':'png'},imported['id']));delivered=checkout('returned-png',rendered)
        pixel(delivered/'exports/delivery/slide-001.png',(512,188),(37,91,207))
        copied=runtime('import-project',portable,'Transferred production proposal');transfer=settle(submit(copied['project']['id'],'slides.inspect',{},copied['revision']['id']))
        assert (checkout('transferred',transfer)/'native/document.json').read_bytes()==(edited/'native/document.json').read_bytes()
        checks.append('CLI crop, JPEG replacement and placement preserve every other shape and prior media; portable transfer renders the revised picture')
        legacy_bytes=args.prior.read_bytes();prior=slides_project.inspect_bytes(legacy_bytes)
        assert prior['migration_count']==1 and prior['revision_count']>prior['migration']['revision_count']
        legacy_owner=tool('create_project',{'name':'Installed source-pin migration chain'})['id']
        asset=runtime('import-asset',legacy_owner,args.prior)['id']
        migrated=settle(submit(legacy_owner,'slides.migrate',{'asset':asset,'expected_sha256':hashlib.sha256(legacy_bytes).hexdigest()}))
        migrated_folder=checkout('migrated',migrated)
        assert (migrated_folder/'native/predecessor.dobeslides').read_bytes()==legacy_bytes and migrated['validation']['engine_migration_verified']
        migration=slides_project.inspect_bytes((migrated_folder/'native/project.dobeslides').read_bytes())
        assert migration['migration_count']==2 and migration['manifest']['history']==prior['manifest']['history']
        assert migration['predecessor']['members']['predecessor.dobeslides']==prior['members']['predecessor.dobeslides']
        assert migration['members']['document.json']==prior['members']['document.json']
        checks.append('all seven installed operations pass; the second maintained migration retains exact nested predecessors and the edit between upgrades')
        local('stop');pending=submit(project,'slides.inspect',{},bundled['id'])
        local('rollback');assert local('status')['version']==previous_version
        # Confirm a real older supervisor remains running while it skips new work.
        rollback_status=local('status');assert rollback_status['service_loaded'] and rollback_status['worker_running']
        assert runtime('capabilities')['applications']['slides']['available']
        rollback_observations=[]
        for _ in range(4):
            observed=runtime('job',pending['id']);assert observed['state']=='queued' and observed['attempt']==0
            assert local('status')['worker_running']
            rollback_observations.append({'job':observed['id'],'state':observed['state'],'attempt':observed['attempt'],
                                          'operation':observed['operation'],'worker_running':True})
            time.sleep(.5)
        assert runtime('revision',bundled['id'])==bundled
        local('install','--allow-unsigned');resumed=settle(pending)
        checks.append('real rollback to an older Slides-capable service preserves the qualified queued job with zero attempts; reinstall completes that same job')
        heavy=copy.deepcopy(predicted);heavy['slideSize']={'width':2400.0,'height':1350.0}
        source=root/'large.json';source.write_text(json.dumps(heavy)+'\n')
        large=tool('create_project',{'name':'Installed Slides recovery'})['id'];asset=runtime('import-asset',large,source)['id']
        baseline=settle(submit(large,'slides.import',{'asset':asset,'format':'json'}))
        cancelled=submit(large,'slides.export',{'format':'png','slides':[1],'scale':2},baseline['id']);live=live_export(cancelled,'slides','render')
        (root/'cancel-native.json').write_text(json.dumps(live,indent=2)+'\n')
        tool('cancel_job',{'job':cancelled['id']});settle(cancelled,'cancelled');assert absent(live['group'])
        assert runtime('project',large)['head']==baseline['id']
        crashed=submit(project,'slides.export',{'format':'pdf'},resumed['id']);crash=live_export(crashed,'pdf','mcp')
        (root/'crash-native.json').write_text(json.dumps(crash,indent=2)+'\n')
        os.kill(crash['supervisor_pid'],signal.SIGKILL);assert absent(crash['group'])
        settle(crashed,'interrupted');assert runtime('project',project)['head']==resumed['id']
        local('stop')
        proof=runtime('reconcile-attempt',crashed['id'],'--attempt','1');assert proof['evidence']['eligible'],proof
        reconciled=runtime('reconcile-attempt',crashed['id'],'--attempt','1','--apply');assert reconciled['reconciled'] and not reconciled['result_published']
        runtime('retry',crashed['id'],'--key','explicit-installed-retry');local('start');retried=settle(crashed)
        recovered=checkout('recovered',retried);assert (recovered/'native/original.json').read_bytes()==original
        assert retried['validation']['render_qualified'] and retried['validation']['native_model_equal']
        checks.append('real PNG cancellation and PDF supervisor death remove native groups without publication; natural lease expiry, explicit reconciliation and retry succeed')
        assert runtime('revision',created['id'])==created and args.prior.read_bytes()==legacy_bytes
        assert picture_source.read_bytes()==image_bytes
        local('uninstall');installed=False;status=local('status');assert not status['installed'] and not status['service_loaded']
        evidence={'passed':True,'checks':checks,'jobs':jobs,'applications':17,'public_tools':15,'slides_operations':7,
                  'previous_version':previous_version,'owned_image_bytes':len(image_bytes),'migration_count':2,
                  'installation':str(installation),'reused_failed_fixture':str(args.reuse_from.resolve()) if args.reuse_from else None,
                  'rollback_status':rollback_status,'rollback_observations':rollback_observations,
                  'png':str(raster/'exports/delivery/slide-001.png'),'pdf_preview':str(preview),
                  'cancelled_native':live,'crashed_native':crash,'reconciliation':reconciled,'service_removed':True,
                  'scope':'unsigned development Mac; no clean-machine, reboot, Linux/Cloud or complete PPTX/source fidelity claim','remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'jobs':len(jobs),'service_removed':True}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'checks':checks,'jobs':jobs,'error':str(error)},indent=2)+'\n');raise
    finally:
        if installed:
            result=subprocess.run([str(new),'local','--root',str(installation),'uninstall'],env=env,capture_output=True,text=True,timeout=120)
            (root/'cleanup.json').write_text(json.dumps({'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')


if __name__=='__main__':main()
