"""Exercise completed-job crash recovery through an isolated native package.

Uses disposable image work and a synthetic final review. Makes no provider calls.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();package=args.package.resolve(strict=True)
    args.output.mkdir(parents=True,exist_ok=False)
    resources=package/'lib/dobe';sys.path.insert(0,str(resources/'runtime'))
    os.environ['STUDIO_BUNDLE_RESOURCES']=str(resources)
    os.environ['PATH']=os.pathsep.join(str(p) for p in (resources/'engines').glob('*/bin'))+os.pathsep+os.environ['PATH']
    from studio_runtime.store import Store
    from studio_runtime.agent_store import Journal
    from studio_runtime.agent import Coordinator,specification
    store=Store(args.output/'state');journal=Journal(store)
    project=store.create_project('local','Synthetic restart probe')['id']
    run=journal.create(project,specification('Synthetic image restart probe.','image'),1)['id']
    owner=journal.claim(run)
    parameters={'width':320,'height':240,'background':'#FFFFFF','layers':[
        {'name':'title','type':'text','x':20,'y':80,'text':'Restart probe','font':'Inter','size':24,'color':'#222222'}]}
    journal.step(run,owner,1,{'operation':'image.create','parameters':parameters,'source_revision':None})
    job=store.submit('local',project,'image.create',parameters,'agent-'+run+'-1',None,7200)
    # Simulate loss of the coordinator after native publication but before the
    # step-to-job link is saved. The durable Store idempotency key is sufficient.
    journal.release(run,owner)
    with (args.output/'worker.log').open('w') as log:
        worker=subprocess.Popen([str(package/'bin/a-dope-cli'),'--state',str(store.root),'worker'],stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+120
            while job['state'] in ('queued','running','validating'):
                if time.monotonic()>deadline or worker.poll() is not None:raise RuntimeError('Native restart fixture did not settle')
                time.sleep(.2);job=store.get_job('local',job['id'])
        finally:
            worker.terminate();worker.wait(timeout=20)
    assert job['state']=='succeeded',job
    revision=job['result_revision'];original=store.get_revision('local',revision)
    class SyntheticReview:
        calls=0
        def count(self,request):return 1,'synthetic-count'
        def generate(self,request):
            self.calls+=1
            return {'status':'completed','usage':{'input_tokens':0,'output_tokens':0},'output':[{'type':'message','content':[
                {'type':'output_text','text':json.dumps({'action':'accept','checks':{'brief':True},'findings':['Synthetic review for restart testing only.'],'limitations':[]})}]}]},'synthetic-review'
    transport=SyntheticReview();coordinator=Coordinator(store,transport=transport)
    result=coordinator.run(run)
    assert result['state']=='completed',result['context']
    again=coordinator.run(run)
    with store.connect() as db:
        jobs=db.execute('SELECT count(*) FROM jobs WHERE project=?',(project,)).fetchone()[0]
        revisions=db.execute('SELECT count(*) FROM revisions WHERE project=?',(project,)).fetchone()[0]
    assert result['state']==again['state']=='completed',result['context']
    assert jobs==revisions==1 and transport.calls==1
    assert result['context']['revision']==revision and store.get_revision('local',revision)==original
    report={'passed':True,'provider_network_requests':0,'review':'synthetic, not creative qualification',
            'run':run,'project':project,'job':job['id'],'revision':revision,'job_count':jobs,'revision_count':revisions,
            'synthetic_review_calls':transport.calls,'completed_resume_added_calls':0,'artifact_manifest_unchanged':True,
            'native_validation':original.get('validation'), 'package':str(package)}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
