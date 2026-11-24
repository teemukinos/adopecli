#!/usr/bin/env python3
"""Installed CLI/MCP Slides operations, version rollback and native process cleanup.

Uses a new isolated installation and its launchd supervisor. No developer PATH,
remote provider or GUI is used. Packages and all job evidence remain on disk.
"""
import argparse
import hashlib
import ctypes
import copy
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True,type=Path);parser.add_argument('--previous',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--request',required=True,type=Path,help='Production proposal recipe request')
    parser.add_argument('--legacy',required=True,type=Path,help='Actual build4 native-origin portable project')
    args=parser.parse_args();root=args.output.resolve();root.mkdir();installation=root/'installation'
    new=args.package.resolve()/'bin/dobe';old=args.previous.resolve()/'bin/dobe'
    env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin'};checks=[];jobs=[];installed=False
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
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:os.killpg(group,0)
            except ProcessLookupError:return True
            time.sleep(.05)
        raise AssertionError('native group cleanup remains unproven')
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def checkout(label,revision):
        target=root/label;runtime('checkout',revision['id'],target);return target
    try:
        local('install','--allow-unsigned',exe=old);installed=True
        local('install','--allow-unsigned')
        caps=runtime('capabilities');assert len(caps['applications'])==14 and all(a['available'] for a in caps['applications'].values())
        assert caps['applications']['slides']['production_recipes'][0]['id']=='production_proposal'
        assert caps['applications']['slides']['explicit_engine_migration_available']
        tools=exchange('tools/list',{})['tools'];assert len(tools)==15
        operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        assert len([name for name in operations if name.startswith('slides.')])==7
        checks.append('fourteen bundled engines and seven Slides operations use the same fifteen MCP tools without developer PATH')
        project=tool('create_project',{'name':'Installed production proposal'})['id'];request=json.loads(args.request.read_bytes())
        created=settle(submit(project,'slides.create',request));initial=checkout('created',created)
        inspected=settle(submit(project,'slides.inspect',{},created['id']))
        png=settle(submit(project,'slides.export',{'format':'png'},inspected['id']));raster=checkout('png',png)
        pdf=settle(submit(project,'slides.export',{'format':'pdf'},png['id']));printed=checkout('pdf',pdf)
        for output in (raster,printed):
            delivery=json.loads((output/'exports/delivery/delivery.json').read_bytes())
            assert delivery['slide_count']==5 and delivery['actual_font_bytes_verified'] and delivery['text_layout_clear']
        assert (raster/'exports/delivery/slide-001.png').stat().st_size>0
        assert (printed/'exports/delivery/presentation.pdf').stat().st_size>0
        original=(initial/'native/original.json').read_bytes();model=json.loads(original)
        production=(initial/'recipes/slides-production.json').read_bytes();selector=json.loads(production)['selectors']['sections'][1]['paragraphs']['runs'][0]
        def locate(document,path):
            value=document
            for key in path.split('/')[1:]:value=value[int(key)] if isinstance(value,list) else value[key]
            return value
        text=locate(model,selector)['text'];start=text.encode().index(b'launch line')
        edit={'expected_sha256':sha(printed/'native/project.dobeslides'),'edits':[{'kind':'text.replace','path':selector,'start':start,'end':start+11,'expected':'launch line','value':'opening sentence'}]}
        params=root/'edit.json';params.write_text(json.dumps(edit))
        changed=runtime('submit',project,'slides.edit','--parameters',params,'--key','installed-cli-edit','--source',pdf['id']);jobs.append(changed);changed=settle(changed)
        edited=checkout('edited',changed);predicted=copy.deepcopy(model);locate(predicted,selector)['text']=text.replace('launch line','opening sentence')
        assert json.loads((edited/'native/document.json').read_bytes())==predicted
        assert (edited/'native/original.json').read_bytes()==original and (edited/'recipes/slides-production.json').read_bytes()==production
        precision=json.loads((edited/'exports/inspection.json').read_bytes())['pptx_precision']
        assert precision['source_model_sha256']==sha(edited/'native/document.json') and precision['change_count']==1
        bundled=settle(submit(project,'slides.bundle',{},changed['id']));portable=checkout('bundle',bundled)
        other=tool('create_project',{'name':'Installed portable presentation'})['id'];asset=runtime('import-asset',other,portable/'exports/presentation.dobeslides')['id']
        imported=settle(submit(other,'slides.import',{'asset':asset,'format':'dobeslides'}));returned=checkout('returned',imported)
        assert (returned/'native/document.json').read_bytes()==(edited/'native/document.json').read_bytes()
        assert (returned/'native/original.json').read_bytes()==original
        copied=runtime('import-project',portable,'Transferred production proposal');transfer=settle(submit(copied['project']['id'],'slides.inspect',{},copied['revision']['id']))
        assert (checkout('transferred',transfer)/'recipes/slides-production.json').read_bytes()==production
        legacy_bytes=args.legacy.read_bytes();legacy_owner=tool('create_project',{'name':'Installed source-pin migration'})['id']
        asset=runtime('import-asset',legacy_owner,args.legacy)['id']
        migrated=settle(submit(legacy_owner,'slides.migrate',{'asset':asset,'expected_sha256':hashlib.sha256(legacy_bytes).hexdigest()}))
        migrated_folder=checkout('migrated',migrated)
        assert (migrated_folder/'native/predecessor.dobeslides').read_bytes()==legacy_bytes and migrated['validation']['engine_migration_verified']
        assert (migrated_folder/'native/original.deckcraft').stat().st_size>0
        checks.append('all seven installed operations pass, PNG/PDF check every page, CLI changes only selected text, portable transfer and explicit native-origin migration preserve exact originals')
        local('stop');pending=submit(project,'slides.inspect',{},bundled['id'])
        local('rollback');assert local('status')['version']=='0.1.0-dev.47'
        for _ in range(4):assert runtime('job',pending['id'])['state']=='queued';time.sleep(.25)
        assert runtime('revision',bundled['id'])==bundled
        local('install','--allow-unsigned');resumed=settle(pending)
        checks.append('rollback preserves queued unsupported Slides work and all revisions; reinstall completes the same job')
        heavy=copy.deepcopy(model);heavy['slideSize']={'width':2400.0,'height':1350.0}
        source=root/'large.json';source.write_text(json.dumps(heavy)+'\n')
        large=tool('create_project',{'name':'Installed Slides recovery'})['id'];asset=runtime('import-asset',large,source)['id']
        baseline=settle(submit(large,'slides.import',{'asset':asset,'format':'json'}))
        cancelled=submit(large,'slides.export',{'format':'png','slides':[1],'scale':2},baseline['id']);live=live_export(cancelled,'slides','render')
        tool('cancel_job',{'job':cancelled['id']});settle(cancelled,'cancelled');assert absent(live['group'])
        assert runtime('project',large)['head']==baseline['id']
        crashed=submit(project,'slides.export',{'format':'pdf'},resumed['id']);crash=live_export(crashed,'pdf','mcp')
        os.kill(crash['supervisor_pid'],signal.SIGKILL);assert absent(crash['group'])
        settle(crashed,'interrupted');assert runtime('project',project)['head']==resumed['id']
        local('stop')
        proof=runtime('reconcile-attempt',crashed['id'],'--attempt','1');assert proof['evidence']['eligible'],proof
        reconciled=runtime('reconcile-attempt',crashed['id'],'--attempt','1','--apply');assert reconciled['reconciled'] and not reconciled['result_published']
        runtime('retry',crashed['id'],'--key','explicit-installed-retry');local('start');retried=settle(crashed)
        recovered=checkout('recovered',retried);assert (recovered/'native/original.json').read_bytes()==original
        assert retried['validation']['render_qualified'] and retried['validation']['native_model_equal']
        checks.append('real PNG cancellation and PDF supervisor death remove native groups without publication; natural lease expiry, explicit reconciliation and retry succeed')
        assert runtime('revision',created['id'])==created and args.legacy.read_bytes()==legacy_bytes
        local('uninstall');installed=False;status=local('status');assert not status['installed'] and not status['service_loaded']
        evidence={'passed':True,'checks':checks,'jobs':jobs,'applications':14,'public_tools':15,'slides_operations':7,
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
