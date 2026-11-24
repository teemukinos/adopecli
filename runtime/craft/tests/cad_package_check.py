#!/usr/bin/env python3
"""Installed CLI/MCP CAD operations, version rollback and native process cleanup.

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
    parser.add_argument('--legacy',required=True,type=Path,help='Retained build4 portable CAD project')
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
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':'cad-'+str(len(jobs))}
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
        caps=runtime('capabilities');assert len(caps['applications'])==15 and all(a['available'] for a in caps['applications'].values())
        assert caps['applications']['cad']['qualification']=='metric-drawing-panel-v1'
        assert caps['applications']['cad']['explicit_engine_migration_available']
        tools=exchange('tools/list',{})['tools'];assert len(tools)==15
        operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        assert len([name for name in operations if name.startswith('cad.')])==9
        checks.append('fifteen bundled engines and nine CAD operations use the same fifteen MCP tools without developer PATH')
        project=tool('create_project',{'name':'Installed parametric panel'})['id']
        created=settle(submit(project,'cad.create',{'recipe':'rectangular_panel_solid','version':1,'width':120,'height':80,'depth':12}))
        initial=checkout('created',created);original=(initial/'native/original.json').read_bytes()
        production=(initial/'recipes/cad-production.json').read_bytes();model=json.loads((initial/'native/document.json').read_bytes())
        handle=model['model'][-1]['handle']
        inspected=settle(submit(project,'cad.inspect',{},created['id']))
        edit={'expected_sha256':sha(initial/'native/project.dobecad'),'edits':[
            {'kind':'parameter.expression','name':'width','expected':'120','value':'150'},
            {'kind':'parameter.expression','name':'height','expected':'80','value':'90'}]}
        params=root/'edit.json';params.write_text(json.dumps(edit))
        changed=runtime('submit',project,'cad.edit','--parameters',params,'--key','installed-cli-edit','--source',inspected['id']);jobs.append(changed);changed=settle(changed)
        parameter_folder=checkout('parameters',changed)
        assert json.loads((parameter_folder/'native/document.json').read_bytes())['model']==model['model']
        assert not changed['validation']['native_constraint_solve_verified'] and not changed['validation']['native_solid_regeneration_verified']
        settle(submit(project,'cad.export',{'format':'obj','expected_sha256':sha(parameter_folder/'native/project.dobecad')},changed['id']),'failed')
        solved=settle(submit(project,'cad.solve',{'expected_sha256':sha(parameter_folder/'native/project.dobecad')},changed['id']))
        sketch=checkout('solved',solved);assert solved['validation']['native_constraint_solve_verified'] and not solved['validation']['native_solid_regeneration_verified']
        solid=settle(submit(project,'cad.solid',{'expected_sha256':sha(sketch/'native/project.dobecad'),'depth':20},solved['id']))
        regenerated=checkout('solid',solid);assert solid['validation']['native_solid_regeneration_verified']
        mesh=json.loads((regenerated/'native/document.json').read_bytes())['model'][-1]
        assert mesh['handle']==handle and mesh['kind']['vertices'][6]=={'x':150.0,'y':90.0,'z':20.0}
        exported=settle(submit(project,'cad.export',{'format':'obj','expected_sha256':sha(regenerated/'native/project.dobecad')},solid['id']))
        delivered=checkout('obj',exported);report=json.loads((delivered/'exports/inspection.json').read_bytes())
        assert report['delivery']['measurements']['volume_mm3']==270000 and report['delivery']['measurements']['surface_area_mm2']==36600
        assert report['delivery']['native_mesh_equal'] and exported['validation']['geometry_delivery_verified']
        assert (delivered/'exports/panel.obj').read_text().startswith('# Dobe panel mesh; coordinates in millimetres')
        assert (delivered/'native/original.json').read_bytes()==original and (delivered/'recipes/cad-production.json').read_bytes()==production
        bundled=settle(submit(project,'cad.bundle',{},exported['id']));portable=checkout('bundle',bundled)
        assert (portable/'exports/drawing.dobecad').read_bytes()==(portable/'native/project.dobecad').read_bytes()
        other=tool('create_project',{'name':'Installed portable CAD transfer'})['id'];asset=runtime('import-asset',other,portable/'exports/drawing.dobecad')['id']
        imported=settle(submit(other,'cad.import',{'asset':asset,'format':'dobecad'}));returned=checkout('returned',imported)
        assert (returned/'native/project.dobecad').read_bytes()==(portable/'native/project.dobecad').read_bytes()
        copied=runtime('import-project',portable,'Transferred panel');transfer=settle(submit(copied['project']['id'],'cad.inspect',{},copied['revision']['id']))
        assert (checkout('transferred',transfer)/'recipes/cad-production.json').read_bytes()==production
        legacy_bytes=args.legacy.read_bytes();legacy_owner=tool('create_project',{'name':'Installed CAD pin migration'})['id'];asset=runtime('import-asset',legacy_owner,args.legacy)['id']
        migrated=settle(submit(legacy_owner,'cad.migrate',{'asset':asset,'expected_sha256':hashlib.sha256(legacy_bytes).hexdigest()}))
        migrated_folder=checkout('migrated',migrated)
        assert (migrated_folder/'native/predecessor.dobecad').read_bytes()==legacy_bytes and migrated['validation']['engine_migration_verified']
        assert (migrated_folder/'native/original.json').stat().st_size>0
        checks.append('all nine installed operations pass; CLI parameters preserve geometry until native solve; solid revision retains its handle; measured OBJ, portable transfers and exact pin migration preserve originals')
        local('stop');pending=submit(project,'cad.inspect',{},bundled['id'])
        local('rollback');assert local('status')['version']=='0.1.0-dev.48'
        for _ in range(4):assert runtime('job',pending['id'])['state']=='queued';time.sleep(.25)
        assert runtime('revision',bundled['id'])==bundled
        local('install','--allow-unsigned');resumed=settle(pending)
        checks.append('rollback preserves queued unsupported CAD work and all revisions; reinstall completes the same job')
        cancelled=submit(project,'cad.inspect',{},resumed['id']);live=live_export(cancelled,'cad','encode')
        tool('cancel_job',{'job':cancelled['id']});settle(cancelled,'cancelled');assert absent(live['group'])
        assert runtime('project',project)['head']==resumed['id']
        crashed=submit(project,'cad.export',{'format':'obj','expected_sha256':sha(portable/'native/project.dobecad')},resumed['id']);crash=live_export(crashed,'cad','encode')
        os.kill(crash['supervisor_pid'],signal.SIGKILL);assert absent(crash['group'])
        settle(crashed,'interrupted');assert runtime('project',project)['head']==resumed['id']
        local('stop')
        proof=runtime('reconcile-attempt',crashed['id'],'--attempt','1');assert proof['evidence']['eligible'],proof
        reconciled=runtime('reconcile-attempt',crashed['id'],'--attempt','1','--apply');assert reconciled['reconciled'] and not reconciled['result_published']
        runtime('retry',crashed['id'],'--key','explicit-installed-retry');local('start');retried=settle(crashed)
        recovered=checkout('recovered',retried);assert (recovered/'native/original.json').read_bytes()==original
        assert retried['validation']['geometry_delivery_verified'] and retried['validation']['native_model_equal']
        assert (recovered/'exports/panel.obj').read_bytes()==(delivered/'exports/panel.obj').read_bytes()
        checks.append('real CAD cancellation and supervisor death remove native groups without publication; natural lease expiry, explicit reconciliation and retry produce identical OBJ')
        assert runtime('revision',created['id'])==created and args.legacy.read_bytes()==legacy_bytes
        with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            groups=[row[0] for row in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
        assert len(groups)==len(jobs)+1 and all(absent(group) for group in groups)
        local('uninstall');installed=False;status=local('status');assert not status['installed'] and not status['service_loaded']
        evidence={'passed':True,'checks':checks,'jobs':jobs,'applications':15,'public_tools':15,'cad_operations':9,
                  'cancelled_native':live,'crashed_native':crash,'reconciliation':reconciled,'service_removed':True,'all_registered_groups_absent':groups,
                  'scope':'unsigned development Mac; no clean-machine, reboot, Linux/Cloud or complete CAD/source fidelity claim','remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'jobs':len(jobs),'service_removed':True}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'checks':checks,'jobs':jobs,'error':str(error)},indent=2)+'\n');raise
    finally:
        if installed:
            result=subprocess.run([str(new),'local','--root',str(installation),'uninstall'],env=env,capture_output=True,text=True,timeout=120)
            (root/'cleanup.json').write_text(json.dumps({'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')


if __name__=='__main__':main()
