#!/usr/bin/env python3
"""Cancel and interrupt live Material children through the durable supervisor.

The crash case expires its local test lease after proving process-group absence.
This is controlled local recovery evidence, not a reboot or hosted-isolation test.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import capabilities, execution, material_source, material_document
sys.path.insert(0,str(Path(__file__).resolve().parent))
from material_source_check import recipe, uniform
from studio_runtime.store import Store
from studio_runtime.worker import Worker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--operation',choices=('import','cook','export','preview'),default='import')
    parser.add_argument('--archived',action='store_true',help='Exercise an immutable archived image dependency')
    args=parser.parse_args();root=args.output.resolve();root.mkdir()
    engine=args.engine.resolve(strict=True);os.environ['PATH']=str(engine.parent)+':/usr/bin:/bin'
    runtime=Path(__file__).resolve().parents[1]/'runtime';records=[]
    tree=recipe();documents={'package.sbs':tree};graph_name='Original'
    if args.archived:
        from material_dependencies_check import parent, xml_recipe
        from studio_runtime import material_container
        import xml.etree.ElementTree as ET
        child_source=xml_recipe();parent_source=parent(child_source,'Original','deps/child.sbs')
        tree=material_source.tree(material_container.parse_xml(ET.tostring(parent_source,encoding='utf-8'))['root'])
        documents={'package.sbs':tree,'deps/child.sbs':recipe()};graph_name='Parent'
    graph=tree['children'][-1]['children'][0]
    nodes=next(item for item in graph['children'] if item['tag']=='compNodes')
    nodes['children'].extend(uniform(1000+i*2,1001+i*2,'0.2 0.4 0.8 1') for i in range(5000))
    source=root/'source.mcraft';data,_=material_source.create(documents);source.write_bytes(data)
    source_nodes=material_document.inspect_bytes(data)['graphs']['image_nodes']
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.worker import Worker;Worker(Store(sys.argv[2])).run_one()"
    try:
        for action in ('cancel','crash'):
            state=root/action;store=Store(state);project_id=store.create_project('local','Material recovery')['id']
            asset=store.import_asset('local',project_id,source)['id']
            baseline=None
            if args.operation in ('cook','export','preview'):
                initial=store.submit('local',project_id,'material.import',{'asset':asset},'initial-import');Worker(store).run_one()
                initial=store.get_job('local',initial['id']);assert initial['state']=='succeeded',initial
                baseline=initial['result_revision']
                params={'graph':graph_name} if args.operation=='cook' else {'graph':graph_name,'view':'3d','width':64,'height':48} if args.operation=='preview' else {'graph':graph_name,'format':'png','depth':16}
                job=store.submit('local',project_id,'material.'+args.operation,params,action,baseline)
            else:job=store.submit('local',project_id,'material.import',{'asset':asset},action)
            native_command='evaluate' if args.operation=='cook' else 'maps' if args.operation=='export' else 'preview' if args.operation=='preview' else 'snapshot'
            group=None;child=None
            with (root/(action+'.log')).open('wb') as log:
                worker=subprocess.Popen([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],stdout=log,stderr=log)
                try:
                    deadline=time.monotonic()+60
                    while time.monotonic()<deadline and worker.poll() is None:
                        with store.connect() as db:
                            row=db.execute('SELECT e.process_group FROM attempt_executions e JOIN jobs j ON e.token=j.token WHERE j.id=?',(job['id'],)).fetchone()
                        if row and row['process_group']:
                            group=row['process_group']
                            status=subprocess.run(['/bin/ps','-axo','pid=,pgid=,command='],capture_output=True,text=True,check=True)
                            for line in status.stdout.splitlines():
                                columns=line.strip().split(None,2)
                                if len(columns)==3 and columns[1]==str(group) and columns[2].startswith(str(engine)+' '+native_command+' '):
                                    candidate=int(columns[0])
                                    try:
                                        if os.getpgid(candidate)==group:child=candidate
                                    except ProcessLookupError:pass
                        if child:break
                        time.sleep(.01)
                    assert child and group and worker.poll() is None,'no confirmed live native Material '+native_command+' child'
                    if action=='cancel':
                        store.cancel('local',job['id']);worker.wait(timeout=20)
                        result=store.get_job('local',job['id']);assert result['state']=='cancelled',result
                    else:
                        worker.kill();worker.wait(timeout=5)
                    assert execution.wait_group_absent(group,timeout=10),'native process group did not terminate'
                    assert store.get_project('local',project_id)['head']==baseline
                    record={'action':action,'live_native_pid':child,'registered_group':group,'group_absent':True,'no_revision_published':True,'preserved_head':baseline}
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
        evidence={'passed':True,'records':records,'archived_dependency':args.archived,'real_native_children':True,'native_command':native_command,'source_sha256':hashlib.sha256(data).hexdigest(),'source_nodes':source_nodes,'reboot_qualified':False,'hosted_isolation_qualified':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'passed':False,'records':records,'archived_dependency':args.archived,'error':str(error)},indent=2)+'\n');raise


if __name__=='__main__':main()
