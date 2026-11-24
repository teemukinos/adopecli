#!/usr/bin/env python3
"""Installed CLI/MCP Inspect operations, version rollback and native process cleanup.

Uses a new isolated installation and its launchd supervisor. No developer PATH,
remote provider or GUI is used. Packages and all job evidence remain on disk.
"""
import argparse
import hashlib
import ctypes
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time
import io
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True,type=Path);parser.add_argument('--previous',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
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
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':'inspect-'+str(len(jobs))}
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
        caps=runtime('capabilities');assert len(caps['applications'])==17 and all(a['available'] for a in caps['applications'].values())
        assert caps['applications']['inspect']['qualification']=='static-artifact-v1'
        assert caps['applications']['inspect']['explicit_input_consent_required']
        tools=exchange('tools/list',{})['tools'];assert len(tools)==15
        operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        assert len([name for name in operations if name.startswith('inspect.')])==6
        checks.append('seventeen engines and six Inspect operations use the same fifteen MCP tools without developer PATH')
        owner=tool('create_project',{'name':'Installed inspectable module'})['id']
        source=root/'input.js';source.write_bytes(b"export const answer=42; console.log('</pre><script>forged()</script>');\n")
        original=source.read_bytes();input_hash=sha(source);asset=runtime('import-asset',owner,source)['id']
        consent={'permission':'owned-or-authorized','input_sha256':input_hash}
        def follow(portable,**extra):return {**consent,'expected_sha256':sha(portable),**extra}
        denied=exchange('tools/call',{'name':'dope_submit_job','arguments':{'project':owner,'operation':'inspect.analyze',
                        'parameters':{'asset':asset,'format':'javascript','input_sha256':input_hash},'idempotency_key':'no-consent'}})
        assert denied.get('isError')
        with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            assert db.execute("SELECT count(*) FROM jobs WHERE idempotency_key='no-consent'").fetchone()[0]==0
        checks.append('missing explicit permission is refused before durable job admission')
        created=settle(submit(owner,'inspect.analyze',{**consent,'asset':asset,'format':'javascript'}));initial=checkout('created',created)
        initial_portable=initial/'native/project.dobeinspect';initial_bytes=initial_portable.read_bytes();native_report=(initial/'native/report.json').read_bytes()
        assert (initial/'native/source.bin').read_bytes()==original
        inspected=settle(submit(owner,'inspect.inspect',follow(initial_portable),created['id']))
        edits=[{'kind':'upsert','id':'Export','pointer':'/evidence/result/facts/exports/esm/0','title':'Export contract',
                'text':'Keep answer. <script>untrusted()</script>','status':'open','severity':'note'}]
        request=root/'edit.json';request.write_text(json.dumps(follow(initial_portable,edits=edits)))
        changed=runtime('submit',owner,'inspect.annotate','--parameters',request,'--key','installed-cli-annotation','--source',inspected['id']);jobs.append(changed);changed=settle(changed)
        edited=checkout('edited',changed);final=edited/'native/project.dobeinspect';final_bytes=final.read_bytes()
        assert (edited/'native/source.bin').read_bytes()==original and (edited/'native/report.json').read_bytes()==native_report
        assert json.loads((edited/'native/annotations.json').read_bytes())[0]['title']=='Export contract'
        exported=settle(submit(owner,'inspect.export',follow(final,format='json'),changed['id']));json_folder=checkout('json',exported)
        json_bytes=(json_folder/'exports/findings.json').read_bytes()
        assert json.loads(json_bytes)['analyst_annotations'][0]['input_sha256']==input_hash
        previewed=settle(submit(owner,'inspect.export',follow(final,format='html'),exported['id']));html_folder=checkout('html',previewed)
        html=(html_folder/'exports/findings.html').read_bytes();assert b'<script>' not in html and b'&lt;script&gt;' in html and b'Analyst annotations' in html
        bundled=settle(submit(owner,'inspect.bundle',follow(final),previewed['id']));portable=checkout('bundle',bundled)
        assert (portable/'exports/findings.dobeinspect').read_bytes()==final_bytes
        other=tool('create_project',{'name':'Installed portable inspection'})['id'];uploaded=runtime('import-asset',other,portable/'exports/findings.dobeinspect')['id']
        imported=settle(submit(other,'inspect.import',{**follow(final),'asset':uploaded}));returned=checkout('returned',imported)
        assert (returned/'native/project.dobeinspect').read_bytes()==final_bytes
        updates=[dict(edits[0],status='resolved',text='Export contract reviewed.')]
        transferred=settle(submit(other,'inspect.annotate',follow(final,edits=updates),imported['id']))
        assert json.loads((checkout('reedited',transferred)/'native/annotations.json').read_bytes())[0]['status']=='resolved'
        copied=runtime('import-project',portable,'Whole inspection project');settle(submit(copied['project']['id'],'inspect.inspect',follow(final),copied['revision']['id']))
        checks.append('all six installed operations pass; precise annotations, escaped HTML, JSON, portable re-edit and whole-project transfer retain exact native findings and originals')
        # Inspect an owned native program and Wasm module as data. Neither is run.
        c=root/'fixture.c';c.write_bytes(b'int dobe_answer(void) { return 42; }\nint main(void) { return dobe_answer(); }\n')
        native=root/'owned-native';built=subprocess.run(['/usr/bin/clang',str(c),'-o',str(native)],env=env,capture_output=True,timeout=60);assert built.returncode==0,built.stderr
        wasm=root/'owned.wasm';wasm.write_bytes(bytes.fromhex('0061736d010000000105016000017f03020100070a0106616e7377657200000a06010400412a0b'))
        for kind,path in [('native',native),('wasm',wasm)]:
            target=tool('create_project',{'name':'Installed '+kind+' inspection'})['id'];supplied=runtime('import-asset',target,path)['id']
            revision=settle(submit(target,'inspect.analyze',{'asset':supplied,'format':kind,'permission':'owned-or-authorized','input_sha256':sha(path)}))
            folder=checkout(kind,revision);report=json.loads((folder/'native/report.json').read_bytes())
            assert (folder/'native/source.bin').read_bytes()==path.read_bytes() and report['input_executed'] is False
            if kind=='native':assert report['evidence']['result']['binary']['format']=='mach-o'
            else:assert report['evidence']['result']['validation']['valid'] and report['evidence']['result']['exports'][0]['name']=='answer'
        checks.append('installed native, JavaScript and WebAssembly analysis use real parsers and never execute target code')
        failed=settle(submit(owner,'inspect.inspect',dict(follow(final),input_sha256='0'*64),bundled['id']),'failed')
        assert failed['result_revision'] is None and runtime('project',owner)['head']==bundled['id']
        with zipfile.ZipFile(io.BytesIO(initial_bytes)) as archive:members={name:archive.read(name) for name in archive.namelist()}
        manifest=json.loads(members['project.json']);report=json.loads(members['report.json']);report['evidence']['summary']='Forged display claim with unchanged evidence ID.'
        members['report.json']=json.dumps(report,sort_keys=True,separators=(',',':')).encode();digest=hashlib.sha256(members['report.json']).hexdigest()
        manifest['report']=digest;manifest['members']['report.json']={'sha256':digest,'bytes':len(members['report.json'])};members['project.json']=json.dumps(manifest,sort_keys=True).encode()
        forged=root/'forged.dobeinspect'
        with zipfile.ZipFile(forged,'w',compression=zipfile.ZIP_STORED) as archive:
            for name,data in members.items():archive.writestr(name,data)
        forged_owner=tool('create_project',{'name':'Forged inspection'})['id'];forged_asset=runtime('import-asset',forged_owner,forged)['id']
        failure=settle(submit(forged_owner,'inspect.import',{**follow(forged),'asset':forged_asset}),'failed')
        assert failure['result_revision'] is None and 'complete native report replay differs' in failure['error']['message']
        checks.append('wrong consent and self-consistent forged reports fail without publishing a revision')
        local('stop');pending=submit(owner,'inspect.inspect',follow(final),bundled['id'])
        local('rollback');assert local('status')['version']=='0.1.0-dev.50'
        for _ in range(4):assert runtime('job',pending['id'])['state']=='queued';time.sleep(.25)
        assert runtime('revision',bundled['id'])==bundled
        local('install','--allow-unsigned');resumed=settle(pending)
        checks.append('rollback preserves unsupported queued Inspect work and revisions; reinstall completes the same job')
        cancelled=submit(owner,'inspect.inspect',follow(final),resumed['id']);live=live_export(cancelled,'inspect','inspect')
        tool('cancel_job',{'job':cancelled['id']});settle(cancelled,'cancelled');assert absent(live['group'])
        assert runtime('project',owner)['head']==resumed['id']
        crashed=submit(owner,'inspect.export',follow(final,format='json'),resumed['id']);crash=live_export(crashed,'inspect','inspect')
        os.kill(crash['supervisor_pid'],signal.SIGKILL);assert absent(crash['group'])
        settle(crashed,'interrupted');assert runtime('project',owner)['head']==resumed['id']
        local('stop');proof=runtime('reconcile-attempt',crashed['id'],'--attempt','1');assert proof['evidence']['eligible'],proof
        reconciled=runtime('reconcile-attempt',crashed['id'],'--attempt','1','--apply');assert reconciled['reconciled'] and not reconciled['result_published']
        runtime('retry',crashed['id'],'--key','explicit-installed-retry');local('start');retried=settle(crashed)
        recovered=checkout('recovered',retried)
        assert (recovered/'native/source.bin').read_bytes()==original and (recovered/'native/report.json').read_bytes()==native_report
        assert (recovered/'native/project.dobeinspect').read_bytes()==final_bytes and (recovered/'exports/findings.json').read_bytes()==json_bytes
        assert retried['validation']['native_report_replayed'] and retried['validation']['annotation_history_replayed']
        checks.append('real Inspect cancellation and supervisor death stop native groups without publication; natural lease expiry and explicit reconciliation/retry reproduce exact findings and annotation history')
        assert runtime('revision',created['id'])==created and initial_portable.read_bytes()==initial_bytes
        with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            groups=[row[0] for row in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
            job_states=[dict(zip(('state','count'),row)) for row in db.execute('SELECT state,count(*) FROM jobs GROUP BY state')]
        assert len(groups)==len(jobs)+1 and all(absent(group) for group in groups)
        local('uninstall');installed=False;status=local('status');assert not status['installed'] and not status['service_loaded']
        evidence={'passed':True,'checks':checks,'jobs':jobs,'applications':17,'public_tools':15,'inspect_operations':6,
                  'cancelled_native':live,'crashed_native':crash,'reconciliation':reconciled,'service_removed':True,'all_registered_groups_absent':groups,
                  'persisted_job_state_counts':job_states,'scope':'unsigned development Mac; no clean-machine, reboot, Linux/Cloud, cross-platform report migration or complete release claim','remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'jobs':len(jobs),'service_removed':True}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'checks':checks,'jobs':jobs,'error':str(error)},indent=2)+'\n');raise
    finally:
        if installed:
            result=subprocess.run([str(new),'local','--root',str(installation),'uninstall'],env=env,capture_output=True,text=True,timeout=120)
            (root/'cleanup.json').write_text(json.dumps({'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')


if __name__=='__main__':main()
