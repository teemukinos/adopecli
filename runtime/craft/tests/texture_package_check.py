#!/usr/bin/env python3
"""Installed CLI/MCP Texture operations, version rollback and live CPU cleanup.

Uses a new isolated installation and its launchd supervisor. No developer PATH,
remote provider or GUI is used. Packages and all job evidence remain on disk.
"""
import argparse
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
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':'texture-'+str(len(jobs))}
        if source:arguments['source_revision']=source
        job=tool('submit_job',arguments);assert tool('submit_job',arguments)['id']==job['id'];jobs.append(job);return job
    def settle(job,expected='succeeded'):
        # Poll the same persisted job until its authoritative terminal state.
        # A slow observation is not permission to restart or discard execution.
        while True:
            state=runtime('job',job['id'])
            if state['state'] not in ('queued','running','validating'):
                assert state['state']==expected,state
                jobs[jobs.index(job)]=state
                return runtime('revision',state['result_revision']) if state.get('result_revision') else state
            time.sleep(.2)
    def live_render(job):
        while True:
            with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                row=db.execute('SELECT e.process_group FROM attempt_executions e JOIN jobs j ON j.token=e.token WHERE j.id=?',(job['id'],)).fetchone()
            if row and row[0]:
                lines=subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,pgid=,command='],text=True).splitlines()
                for line in lines:
                    parts=line.strip().split(None,3)
                    if len(parts)==4 and parts[2]==str(row[0]) and Path(parts[3].split()[0]).name=='dobe-texture' and ' render ' in parts[3]:
                        pid=int(parts[0]);assert os.getpgid(pid)==row[0]
                        os.kill(pid,signal.SIGSTOP)  # Stop only the native child; the parent-death watcher must keep running.
                        supervisor=int(subprocess.check_output(['/bin/ps','-o','ppid=','-p',str(row[0])],text=True).strip())
                        return {'native_pid':pid,'group':row[0],'supervisor_pid':supervisor}
            state=runtime('job',job['id']);assert state['state'] in ('queued','running','validating'),state
            time.sleep(.03)
    def absent(group):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:os.killpg(group,0)
            except ProcessLookupError:return True
            except PermissionError:pass
            time.sleep(.05)
        raise AssertionError('native process-group absence remains unproven')
    try:
        local('install','--allow-unsigned',exe=old);installed=True
        local('install','--allow-unsigned')
        caps=runtime('capabilities');assert len(caps['applications'])==11 and all(v['available'] for v in caps['applications'].values())
        assert caps['applications']['texture']['cpu_preview_available'] and caps['applications']['texture']['baking_available']
        tools=exchange('tools/list',{})['tools'];assert len(tools)==15
        operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        assert len([name for name in operations if name.startswith('texture.')])==7
        checks.append('eleven bundled applications and seven typed Texture operations through the existing fifteen MCP tools')
        project=tool('create_project',{'name':'Installed material'})['id']
        scene={'name':'Painted enclosure','mesh':'plane','resolution':128,'layers':[{'name':'Blue','sources':{'BaseColor':{'Uniform':[0,0,1]},'Roughness':{'Uniform':[.25,.25,.25]}}}]}
        first=settle(submit(project,'texture.create',scene));runtime('checkout',first['id'],root/'created')
        edit={'edits':[{'layer':1,'property':'source','channel':'Roughness','expected':{'Uniform':[.25,.25,.25]},'value':{'Uniform':[.75,.75,.75]}}]}
        second=settle(submit(project,'texture.edit',edit,first['id']))
        inspected=settle(submit(project,'texture.inspect',{},second['id']))
        exported=settle(submit(project,'texture.export',{},inspected['id']))
        render={'render':{'width':64,'height':64,'samples':2,'bounces':2}}
        rendered=settle(submit(project,'texture.render',render,exported['id']))
        bake={'bake':{'texture_sets':[0],'resolution':16,'maps':['normal','ambientOcclusion'],'rays':1,'use_low_as_high':True}}
        baked=settle(submit(project,'texture.bake',bake,rendered['id']));runtime('checkout',baked['id'],root/'baked')
        assert (root/'created/native/source.tcraft').read_bytes()==(root/'baked/native/source.tcraft').read_bytes()
        assert json.loads((root/'baked/exports/inspection.json').read_text())['bake']['repeated_bake_equal']
        imported_project=tool('create_project',{'name':'Imported material'})['id']
        asset=runtime('import-asset',imported_project,root/'baked/native/document.tcraft')['id']
        imported=settle(submit(imported_project,'texture.import',{'asset':asset}))
        checks.append('all seven installed operations finish as durable jobs with preserved original source and native cold checks')
        local('stop');pending=submit(project,'texture.render',render,baked['id'])
        local('rollback');assert local('status')['version']=='0.1.0-dev.43'
        for _ in range(4):assert runtime('job',pending['id'])['state']=='queued';time.sleep(.25)
        assert runtime('revision',baked['id'])==baked
        local('install','--allow-unsigned');resumed=settle(pending)
        portable=runtime('import-project',root/'baked','Portable baked material')
        settle(submit(portable['project']['id'],'texture.render',render,portable['revision']['id']))
        checks.append('rollback retains an unsupported Texture job; reinstall resumes it and portable sources reopen')
        heavy={'render':{'width':512,'height':512,'samples':128,'bounces':4}}
        cancelled=submit(project,'texture.render',heavy,resumed['id']);live=live_render(cancelled)
        tool('cancel_job',{'job':cancelled['id']});settle(cancelled,'cancelled');assert absent(live['group'])
        assert runtime('project',project)['head']==resumed['id']
        crashed=submit(project,'texture.render',heavy,resumed['id']);crash=live_render(crashed)
        os.kill(crash['supervisor_pid'],signal.SIGKILL);assert absent(crash['group'])
        settle(crashed,'interrupted');assert runtime('project',project)['head']==resumed['id']
        local('stop')
        proof=runtime('reconcile-attempt',crashed['id'],'--attempt','1');assert proof['evidence']['eligible'],proof
        reconciled=runtime('reconcile-attempt',crashed['id'],'--attempt','1','--apply');assert reconciled['reconciled'] and not reconciled['result_published']
        local('start');settle(submit(project,'texture.inspect',{},resumed['id']))
        checks.append('actual installed CPU renderer cancellation and supervisor death remove their registered groups without publishing')
        assert runtime('revision',first['id'])==first
        local('uninstall');installed=False;status=local('status');assert not status['installed'] and not status['service_loaded']
        evidence={'passed':True,'checks':checks,'jobs':jobs,'applications':11,'public_tools':15,'texture_operations':7,
                  'cancelled_native':live,'crashed_native':crash,'reconciliation':reconciled,'service_removed':True,
                  'scope':'unsigned development Mac; no clean-machine, reboot, Linux/Cloud or general visual-fidelity claim','remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'jobs':len(jobs),'service_removed':True}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'checks':checks,'jobs':jobs,'error':str(error)},indent=2)+'\n');raise
    finally:
        if installed:
            result=subprocess.run([str(new),'local','--root',str(installation),'uninstall'],env=env,capture_output=True,text=True,timeout=120)
            (root/'cleanup.json').write_text(json.dumps({'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})+'\n')


if __name__=='__main__':main()
