#!/usr/bin/env python3
"""Cancel and interrupt live Texture children through the durable supervisor.

The crash case expires its local test lease after proving process-group absence.
This is controlled local recovery evidence, not a reboot or hosted-isolation test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import capabilities, execution
from studio_runtime.store import Store
from studio_runtime.worker import Worker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',required=True,type=Path)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--material',type=Path)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--phase',choices=('material','texture'),default='texture')
    args=parser.parse_args();root=args.output.resolve();root.mkdir()
    engine=args.engine.resolve(strict=True)
    assert bool(args.material)==bool(args.bundle),'material engine and bundle must be supplied together'
    material=args.material.resolve(strict=True) if args.material else None
    assert args.phase!='material' or material,'material phase requires a bundle'
    watched=material if args.phase=='material' else engine
    os.environ['PATH']=str(engine.parent)+(':'+str(material.parent) if material else '')+':/usr/bin:/bin'
    runtime=Path(__file__).resolve().parents[1]/'runtime';records=[]
    with zipfile.ZipFile(args.source) as archive:members={name:archive.read(name) for name in archive.namelist()}
    project=json.loads(members['project.json'])
    for item in project['texture_sets']:item['resolution']=1024
    members['project.json']=json.dumps(project).encode()
    source=root/'source.tcraft'
    with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in members.items():archive.writestr(name,data)
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.worker import Worker;Worker(Store(sys.argv[2])).run_one()"
    try:
        for action in ('cancel','crash'):
            state=root/action;store=Store(state);project_id=store.create_project('local','Texture recovery')['id']
            asset=store.import_asset('local',project_id,source)['id']
            job=store.submit('local',project_id,'texture.import',{'asset':asset},action+'-import');baseline=None
            if material:
                Worker(store).run_one();initial=store.get_job('local',job['id']);assert initial['state']=='succeeded',initial
                baseline=initial['result_revision'];bundle_asset=store.import_asset('local',project_id,args.bundle)['id']
                # Digest is taken from the exact exported source revision.
                exported=root/(action+'-baseline');store.checkout('local',baseline,exported)
                digest=hashlib.sha256((exported/'native/document.tcraft').read_bytes()).hexdigest()
                job=store.submit('local',project_id,'texture.material',{'asset':bundle_asset,'expected_sha256':digest,'texture_set':0,'height_mode':'unsigned'},action,baseline)
            group=None;child=None
            with (root/(action+'.log')).open('wb') as log:
                worker=subprocess.Popen([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],stdout=log,stderr=log)
                try:
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline and worker.poll() is None:
                        with store.connect() as db:
                            row=db.execute('SELECT e.process_group FROM attempt_executions e JOIN jobs j ON e.token=j.token WHERE j.id=?',(job['id'],)).fetchone()
                        if row and row['process_group']:
                            group=row['process_group']
                            status=subprocess.run(['/bin/ps','-axo','pid=,pgid=,command='],capture_output=True,text=True,check=True)
                            for line in status.stdout.splitlines():
                                columns=line.strip().split(None,2)
                                if len(columns)==3 and columns[1]==str(group) and columns[2].startswith(str(watched)+' '+('maps ' if args.phase=='material' else '')):
                                    candidate=int(columns[0])
                                    try:
                                        if os.getpgid(candidate)==group:child=candidate
                                    except ProcessLookupError:pass
                        if child:break
                        time.sleep(.01)
                    assert child and group and worker.poll() is None,'no confirmed live native '+watched.name+' child'
                    if action=='cancel':
                        store.cancel('local',job['id']);worker.wait(timeout=20)
                        result=store.get_job('local',job['id']);assert result['state']=='cancelled',result
                    else:
                        worker.kill();worker.wait(timeout=5)
                    assert execution.wait_group_absent(group,timeout=10),'native process group did not terminate'
                    assert store.get_project('local',project_id)['head']==baseline
                    record={'action':action,'live_native_pid':child,'registered_group':group,'group_absent':True,'no_revision_published':True,'preserved_head':baseline,'native_engine':watched.name,'phase':args.phase}
                    if action=='crash':
                        with store.transaction() as db:db.execute('UPDATE jobs SET lease_until=? WHERE id=?',(time.time()-1,job['id']))
                        assert store.recover('local')==1
                        assert store.get_job('local',job['id'])['state']=='interrupted'
                        assert Worker(store).run_one() is False,'interrupted work replayed automatically'
                        store.retry('local',job['id'],'explicit-retry',capabilities.RETRY_SAFE)
                        Worker(store).run_one();result=store.get_job('local',job['id'])
                        assert result['state']=='succeeded' and result['attempt']==2,result
                        record.update(lease_expiry='controlled local test',automatic_replay=False,explicit_retry_succeeded=True)
                    records.append(record)
                finally:
                    if worker.poll() is None:worker.kill();worker.wait(timeout=5)
                    if group:assert execution.wait_group_absent(group,timeout=10),'attempt cleanup remains uncertain'
        evidence={'passed':True,'records':records,'real_native_children':True,'operation':'texture.material' if material else 'texture.import','phase':args.phase,'reboot_qualified':False,'hosted_isolation_qualified':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'passed':False,'records':records,'error':str(error)},indent=2)+'\n');raise


if __name__=='__main__':main()
