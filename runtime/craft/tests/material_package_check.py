#!/usr/bin/env python3
"""Installed CLI/MCP Material operations, version rollback and live CPU cleanup.

Uses a new isolated installation and its launchd supervisor. No developer PATH,
remote provider or GUI is used. Packages and all job evidence remain on disk.
"""
import argparse
import hashlib
import zipfile
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
    parser.add_argument('--archive',required=True,type=Path,help='Owned three-package Material fixture with a Parent graph')
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
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':'material-'+str(len(jobs))}
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
                jobs[jobs.index(job)]=state
                return runtime('revision',state['result_revision']) if state.get('result_revision') else state
            time.sleep(.2)
    def live_preview(job):
        while True:
            with sqlite3.connect((installation/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                row=db.execute('SELECT e.process_group FROM attempt_executions e JOIN jobs j ON j.token=e.token WHERE j.id=?',(job['id'],)).fetchone()
            if row and row[0]:
                lines=subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,pgid=,command='],text=True).splitlines()
                for line in lines:
                    parts=line.strip().split(None,3)
                    if len(parts)==4 and parts[2]==str(row[0]) and Path(parts[3].split()[0]).name=='dobe-material' and ' preview ' in parts[3]:
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
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def checkout(label,rev):
        target=root/label;runtime('checkout',rev['id'],target);return target
    def exported_maps(path):
        report=json.loads((path/'exports/maps.json').read_text())
        return {m['usage']:(path/'exports/maps'/m['file']).read_bytes() for m in report['maps']}
    try:
        local('install','--allow-unsigned',exe=old);installed=True
        local('install','--allow-unsigned')
        caps=runtime('capabilities');assert len(caps['applications'])==12 and all(v['available'] for v in caps['applications'].values())
        assert caps['applications']['material']['archived_dependencies_available'] and caps['applications']['material']['portable_material_version']==2
        tools=exchange('tools/list',{})['tools'];assert len(tools)==15
        operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        assert len([name for name in operations if name.startswith('material.')])==8
        assert len([name for name in operations if name.startswith('texture.')])==8
        checks.append('twelve bundled applications and eight Material operations through the existing fifteen MCP tools without developer PATH')
        project=tool('create_project',{'name':'Installed procedural material'})['id']
        params={'recipe':'ceramic_tiles','version':1,'resolution':64,'controls':{'repeat':4,'color_r':.25}}
        first=settle(submit(project,'material.create',params));initial=checkout('created',first)
        inspected=settle(submit(project,'material.inspect',{},first['id']))
        cooked=settle(submit(project,'material.cook',{'graph':'Surface'},inspected['id']))
        maps={'graph':'Surface','format':'png','depth':16}
        exported=settle(submit(project,'material.export',maps,cooked['id']));before=checkout('before',exported)
        edit={'expected_sha256':sha(before/'native/document.mcraft'),'edits':[{'kind':'input.default','package':'package.sbs','graph':'Surface','name':'color_r','expected':{'t':'float','v':.25},'value':{'t':'float','v':.75}}]}
        specification=root/'edit.json';specification.write_text(json.dumps(edit))
        edited=runtime('submit',project,'material.edit','--parameters',specification,'--key','installed-cli-edit','--source',exported['id']);jobs.append(edited);edited=settle(edited)
        after_export=settle(submit(project,'material.export',maps,edited['id']));after=checkout('after',after_export)
        old_maps=exported_maps(before);new_maps=exported_maps(after)
        assert set(old_maps)==set(new_maps) and len(old_maps)==6 and old_maps['baseColor']!=new_maps['baseColor']
        assert all(old_maps[k]==new_maps[k] for k in old_maps if k!='baseColor')
        assert (initial/'native/original.input').read_bytes()==(after/'native/original.input').read_bytes()
        assert (initial/'recipes/origin-material-operation.json').read_bytes()==(after/'recipes/origin-material-operation.json').read_bytes()
        preview={'graph':'Surface','view':'3d','width':64,'height':48}
        rendered=settle(submit(project,'material.preview',preview,after_export['id']));preview_files=checkout('preview',rendered)
        assert (preview_files/'exports/preview/preview.png').is_file()
        bundled=settle(submit(project,'material.bundle',{'graph':'Surface'},rendered['id']));portable=checkout('bundle',bundled)
        other=tool('create_project',{'name':'Installed bundle source'})['id']
        asset=runtime('import-asset',other,portable/'exports/material.mcmat')['id']
        imported=settle(submit(other,'material.import',{'asset':asset,'format':'mcmat'}));returned=checkout('bundle-returned',imported)
        assert (returned/'native/document.mcraft').read_bytes()==(portable/'native/document.mcraft').read_bytes()
        assert (returned/'native/original.input').read_bytes()==(portable/'exports/material.mcmat').read_bytes()
        checks.append('all eight installed Material operations succeed; precise CLI recolor preserves five maps, original source and recipe; bundle import retains exact editable source')
        archived=tool('create_project',{'name':'Installed archived dependencies'})['id']
        asset=runtime('import-asset',archived,args.archive.resolve())['id']
        archived_rev=settle(submit(archived,'material.import',{'asset':asset}));archive_files=checkout('archive',archived_rev)
        report=json.loads((archive_files/'exports/inspection.json').read_text());assert report['immutable_archive_dependencies']==2 and len(report['native_packages_compared'])==3
        assert (archive_files/'native/document.mcraft').read_bytes()==args.archive.read_bytes()
        archived_rev=settle(submit(archived,'material.export',{'graph':'Parent','format':'png','depth':8},archived_rev['id']))
        archived_rev=settle(submit(archived,'material.bundle',{'graph':'Parent'},archived_rev['id']));archive_bundle=checkout('archive-bundle',archived_rev)
        copied=runtime('import-project',archive_bundle,'Portable dependencies')
        settle(submit(copied['project']['id'],'material.inspect',{},copied['revision']['id']))
        checks.append('installed archive import independently compares three immutable packages, exports and bundles them, and reopens a portable project')
        texture=tool('create_project',{'name':'Installed linked texture'})['id']
        texture_rev=settle(submit(texture,'texture.create',{'name':'Enclosure','mesh':'plane','resolution':128,'layers':[{'name':'Undercoat','sources':{'BaseColor':{'Uniform':[.25,.25,.25]}}}]}))
        texture_before=checkout('texture-before',texture_rev)
        asset=runtime('import-asset',texture,archive_bundle/'exports/material.mcmat')['id']
        params={'asset':asset,'expected_sha256':sha(texture_before/'native/document.tcraft'),'texture_set':0}
        texture_rev=settle(submit(texture,'texture.material',params,texture_rev['id']));texture_after=checkout('texture-after',texture_rev)
        report=json.loads((texture_after/'exports/inspection.json').read_text())['material_handoff']
        assert report['bounded_source_cook_verified'] and not report['legacy_v1_reader_used']
        assert (texture_after/'native/source.tcraft').read_bytes()==(texture_before/'native/source.tcraft').read_bytes()
        with zipfile.ZipFile(texture_after/'native/document.tcraft') as z:
            assert args.archive.read_bytes() in [z.read(name) for name in z.namelist() if not name.endswith('/')]
        checks.append('installed Material-to-Texture handoff verifies dependency maps and retains the exact three-package source without touching original Texture')
        local('stop');pending=submit(project,'material.preview',preview,bundled['id'])
        local('rollback');assert local('status')['version']=='0.1.0-dev.44'
        for _ in range(4):assert runtime('job',pending['id'])['state']=='queued';time.sleep(.25)
        assert runtime('revision',bundled['id'])==bundled
        local('install','--allow-unsigned');resumed=settle(pending)
        checks.append('rollback retains an unsupported Material job and all revisions; reinstall resumes the same queued request')
        heavy={'graph':'Surface','view':'3d','width':1024,'height':1024,'supersample':2,'ao_rays':8}
        cancelled=submit(project,'material.preview',heavy,resumed['id']);live=live_preview(cancelled)
        tool('cancel_job',{'job':cancelled['id']});settle(cancelled,'cancelled');assert absent(live['group'])
        assert runtime('project',project)['head']==resumed['id']
        crashed=submit(project,'material.preview',heavy,resumed['id']);crash=live_preview(crashed)
        os.kill(crash['supervisor_pid'],signal.SIGKILL);assert absent(crash['group'])
        settle(crashed,'interrupted');assert runtime('project',project)['head']==resumed['id']
        local('stop')
        proof=runtime('reconcile-attempt',crashed['id'],'--attempt','1');assert proof['evidence']['eligible'],proof
        reconciled=runtime('reconcile-attempt',crashed['id'],'--attempt','1','--apply');assert reconciled['reconciled'] and not reconciled['result_published']
        local('start');settle(submit(project,'material.inspect',{},resumed['id']))
        checks.append('actual installed Material preview cancellation and supervisor death remove registered native groups without publication; explicit reconciliation resumes work')
        assert runtime('revision',first['id'])==first
        local('uninstall');installed=False;status=local('status');assert not status['installed'] and not status['service_loaded']
        evidence={'passed':True,'checks':checks,'jobs':jobs,'applications':12,'public_tools':15,'material_operations':8,'texture_operations':8,
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
