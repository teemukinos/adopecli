"""Exercise real Blender cancellation and controlled local worker recovery."""
import json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio_runtime.store import Store
from studio_runtime import execution,capabilities
package=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve();root.mkdir();cli=package/'bin/dobe';records=[]
doc=json.loads((Path(__file__).resolve().parents[1]/'fixtures/construction/ring.json').read_text())
for action in ('cancel','crash'):
    state=root/action;store=Store(state);project=store.create_project('local','Construction recovery')['id']
    job=store.submit('local',project,'construct.create',{'document':doc},action)
    group=None;child=None
    with (root/(action+'.log')).open('wb') as log:
        worker=subprocess.Popen([cli,'--state',state,'worker','--once'],stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+60
            while time.monotonic()<deadline and worker.poll() is None:
                with store.connect() as db:row=db.execute('SELECT e.process_group FROM attempt_executions e JOIN jobs j ON e.token=j.token WHERE j.id=?',(job['id'],)).fetchone()
                if row and row['process_group']:
                    group=row['process_group']
                    output=subprocess.check_output(['/bin/ps','-axo','pid=,pgid=,command='],text=True)
                    for line in output.splitlines():
                        values=line.strip().split(None,2)
                        if len(values)==3 and values[1]==str(group) and values[2].startswith('/Applications/Blender.app/Contents/MacOS/Blender '):
                            child=int(values[0]);break
                if child:break
                time.sleep(.03)
            assert child and group and worker.poll() is None,'No live native construction child observed'
            if action=='cancel':store.cancel('local',job['id']);worker.wait(timeout=25);assert store.get_job('local',job['id'])['state']=='cancelled'
            else:worker.kill();worker.wait(timeout=5)
            assert execution.wait_group_absent(group,timeout=15),'Native process group remains'
            assert store.get_project('local',project)['head'] is None
            record={'action':action,'native_pid':child,'registered_group':group,'group_absent':True,'no_revision_published':True}
            if action=='crash':
                with store.transaction() as db:db.execute('UPDATE jobs SET lease_until=? WHERE id=?',(time.time()-1,job['id']))
                assert store.recover('local')==1;assert store.get_job('local',job['id'])['state']=='interrupted'
                subprocess.run([cli,'--state',state,'worker','--once'],stdout=log,stderr=log,check=True);assert store.get_project('local',project)['head'] is None
                store.retry('local',job['id'],'explicit-retry',capabilities.RETRY_SAFE)
                subprocess.run([cli,'--state',state,'worker','--once'],stdout=log,stderr=log,check=True)
                result=store.get_job('local',job['id']);assert result['state']=='succeeded' and result['attempt']==2,result
                record.update(controlled_lease_expiry=True,automatic_replay=False,explicit_retry_succeeded=True)
            records.append(record)
        finally:
            if worker.poll() is None:worker.kill();worker.wait(timeout=5)
            if group:assert execution.wait_group_absent(group,timeout=15)
result={'passed':True,'records':records,'reboot_qualified':False,'hosted_isolation_qualified':False};(root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
