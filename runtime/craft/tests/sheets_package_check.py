#!/usr/bin/env python3
"""Installed CLI/MCP Sheets operations, version rollback and native process cleanup.

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
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':'sheets-'+str(len(jobs))}
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
        # A user browsing an unpacked CLI package can create these metadata
        # files. They must remain outside the authenticated installed payload.
        metadata_paths = []
        for folder in (args.package.resolve(),args.package.resolve()/'lib',args.package.resolve()/'lib/dobe'):
            path=folder/'.DS_Store'
            if not path.exists():
                with path.open('xb') as stream:stream.write(b'\x00\x00\x00\x01Bud1'+bytes(6140))
            metadata_paths.append(path)
        local('install','--allow-unsigned',exe=old);installed=True
        local('install','--allow-unsigned')
        assert not list((installation/'current').resolve().rglob('.DS_Store')), 'Finder metadata entered installed payload'
        checks.append('Finder metadata is accepted only as excluded nonexecutable data; installed payload contains none')
        caps=runtime('capabilities');assert len(caps['applications'])==16 and all(a['available'] for a in caps['applications'].values())
        assert caps['applications']['sheets']['qualification']=='cells-and-formulas-v1'
        tools=exchange('tools/list',{})['tools'];assert len(tools)==15
        operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        assert len([name for name in operations if name.startswith('sheets.')])==7
        checks.append('sixteen engines and seven Sheets operations use the same fifteen MCP tools without developer PATH')
        owner=tool('create_project',{'name':'Installed production budget'})['id']
        params={'recipe':'production_budget','version':1,'title':'Campaign assets','currency':'EUR','tax_rate':.24,
                'items':[{'name':'Product images','quantity':10,'unit_price':12.5},{'name':'Motion exports','quantity':4,'unit_price':20}]}
        created=settle(submit(owner,'sheets.create',params));initial=checkout('created',created)
        original=(initial/'native/original.json').read_bytes();production=(initial/'recipes/sheets-production.json').read_bytes()
        original_portable=(initial/'native/project.dobesheets').read_bytes()
        inspected=settle(submit(owner,'sheets.inspect',{},created['id']))
        parameters={'expected_sha256':sha(initial/'native/project.dobesheets'),'edits':[{'sheet':0,'cell':'B3','value':12}]}
        parameter_file=root/'edit.json';parameter_file.write_text(json.dumps(parameters))
        changed=runtime('submit',owner,'sheets.edit','--parameters',parameter_file,'--key','installed-cli-edit','--source',inspected['id']);jobs.append(changed);changed=settle(changed)
        edited=checkout('edited',changed)
        assert changed['validation']['native_calculation_verified'] and changed['validation']['native_history_replayed']
        calculated=settle(submit(owner,'sheets.calculate',{'expected_sha256':sha(edited/'native/project.dobesheets')},changed['id']))
        native=checkout('calculated',calculated);final=native/'native/project.dobesheets'
        delivered=settle(submit(owner,'sheets.export',{'expected_sha256':sha(final),'format':'csv'},calculated['id']));csv_folder=checkout('csv',delivered)
        import csv,io
        rows=list(csv.reader(io.StringIO((csv_folder/'exports/workbook.csv').read_text())))
        assert rows[7][3]=='285.2' and delivered['validation']['delivery_verified']
        previewed=settle(submit(owner,'sheets.export',{'expected_sha256':sha(final),'format':'html'},delivered['id']));html_folder=checkout('html',previewed)
        assert b'285.20' in (html_folder/'exports/workbook.html').read_bytes()
        bundled=settle(submit(owner,'sheets.bundle',{},previewed['id']));portable=checkout('bundle',bundled)
        assert (portable/'exports/workbook.dobesheets').read_bytes()==final.read_bytes()
        assert (portable/'native/original.json').read_bytes()==original and (portable/'recipes/sheets-production.json').read_bytes()==production
        other=tool('create_project',{'name':'Installed Sheets transfer'})['id'];asset=runtime('import-asset',other,portable/'exports/workbook.dobesheets')['id']
        imported=settle(submit(other,'sheets.import',{'asset':asset,'format':'dobesheets'}));returned=checkout('returned',imported)
        assert (returned/'native/project.dobesheets').read_bytes()==final.read_bytes()
        transferred=settle(submit(other,'sheets.edit',{'expected_sha256':sha(final),'edits':[{'sheet':1,'cell':'B2','value':.25}]},imported['id']))
        assert transferred['validation']['native_calculation_verified']
        copied=runtime('import-project',portable,'Whole Sheets project');whole=settle(submit(copied['project']['id'],'sheets.inspect',{},copied['revision']['id']))
        assert (checkout('whole-transfer',whole)/'recipes/sheets-production.json').read_bytes()==production
        bad=settle(submit(owner,'sheets.edit',{'expected_sha256':sha(final),'edits':[{'sheet':0,'cell':'B3','value':99},{'sheet':0,'cell':'D3','formula':'WEBSERVICE("https://invalid.example")'}]},bundled['id']),'failed')
        assert bad['result_revision'] is None and runtime('project',owner)['head']==bundled['id']
        checks.append('all seven installed operations pass; precise revisions recalculate totals; independent CSV, styled HTML, portable re-edit and whole-project transfer preserve originals')
        local('stop');pending=submit(owner,'sheets.inspect',{},bundled['id'])
        local('rollback');assert local('status')['version']=='0.1.0-dev.49'
        for _ in range(4):assert runtime('job',pending['id'])['state']=='queued';time.sleep(.25)
        assert runtime('revision',bundled['id'])==bundled
        local('install','--allow-unsigned');resumed=settle(pending)
        checks.append('rollback preserves unsupported queued Sheets work and revisions; reinstall completes the same job')
        cancelled=submit(owner,'sheets.inspect',{},resumed['id']);live=live_export(cancelled,'sheets','encode')
        tool('cancel_job',{'job':cancelled['id']});settle(cancelled,'cancelled');assert absent(live['group'])
        assert runtime('project',owner)['head']==resumed['id']
        crashed=submit(owner,'sheets.export',{'expected_sha256':sha(final),'format':'csv'},resumed['id']);crash=live_export(crashed,'sheets','encode')
        os.kill(crash['supervisor_pid'],signal.SIGKILL);assert absent(crash['group'])
        settle(crashed,'interrupted');assert runtime('project',owner)['head']==resumed['id']
        local('stop')
        proof=runtime('reconcile-attempt',crashed['id'],'--attempt','1');assert proof['evidence']['eligible'],proof
        reconciled=runtime('reconcile-attempt',crashed['id'],'--attempt','1','--apply');assert reconciled['reconciled'] and not reconciled['result_published']
        runtime('retry',crashed['id'],'--key','explicit-installed-retry');local('start');retried=settle(crashed)
        recovered=checkout('recovered',retried)
        assert (recovered/'native/original.json').read_bytes()==original and (recovered/'native/project.dobesheets').read_bytes()==final.read_bytes()
        assert retried['validation']['delivery_verified'] and retried['validation']['native_calculation_verified']
        assert (recovered/'exports/workbook.csv').read_bytes()==(csv_folder/'exports/workbook.csv').read_bytes()
        checks.append('real Sheets cancellation and supervisor death stop native groups without publication; natural lease expiry, explicit reconciliation and retry produce identical CSV and portable history')
        assert runtime('revision',created['id'])==created and (initial/'native/project.dobesheets').read_bytes()==original_portable
        with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            groups=[row[0] for row in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
            job_states=[dict(zip(('state','count'),row)) for row in db.execute('SELECT state,count(*) FROM jobs GROUP BY state')]
        assert len(groups)==len(jobs)+1 and all(absent(group) for group in groups)
        local('uninstall');installed=False;status=local('status');assert not status['installed'] and not status['service_loaded']
        evidence={'passed':True,'checks':checks,'jobs':jobs,'applications':16,'public_tools':15,'sheets_operations':7,
                  'cancelled_native':live,'crashed_native':crash,'reconciliation':reconciled,'service_removed':True,'all_registered_groups_absent':groups,
                  'persisted_job_state_counts':job_states,'scope':'unsigned development Mac; no clean-machine, reboot, Linux/Cloud, pinned-font raster or full spreadsheet compatibility claim','remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'jobs':len(jobs),'service_removed':True}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'checks':checks,'jobs':jobs,'error':str(error)},indent=2)+'\n');raise
    finally:
        if installed:
            result=subprocess.run([str(new),'local','--root',str(installation),'uninstall'],env=env,capture_output=True,text=True,timeout=120)
            (root/'cleanup.json').write_text(json.dumps({'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')


if __name__=='__main__':main()
