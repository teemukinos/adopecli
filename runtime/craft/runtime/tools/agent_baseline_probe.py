"""Exercise baseline reconstruction, follow-up export and asset scope locally.

Uses synthetic creative decisions and real native jobs. No provider requests.
"""
import argparse
import json
from pathlib import Path
import subprocess
import wave
from agent_benchmark import initialize, baseline_class


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();package=args.package.resolve(strict=True)
    args.output.mkdir(parents=True,exist_ok=False);initialize(package)
    from studio_runtime.store import Store
    from studio_runtime.agent_store import Journal
    from studio_runtime.agent import specification
    store=Store(args.output/'state');journal=Journal(store);reports={}
    class Synthetic:
        def __init__(self,decisions):self.decisions=iter(decisions);self.calls=0
        def count(self,request):return 0,'synthetic-count'
        def generate(self,request):
            self.calls+=1
            return {'status':'completed','usage':{'input_tokens':0,'output_tokens':0},'output':[{'type':'message','content':[
                {'type':'output_text','text':json.dumps(next(self.decisions))}]}]},'synthetic-review'
    with (args.output/'worker.log').open('w') as log:
        worker=subprocess.Popen([str(package/'bin/a-dope-cli'),'--state',str(store.root),'worker'],stdout=log,stderr=subprocess.STDOUT)
        try:
            for workflow in ('document','video'):
                project=store.create_project('local','Synthetic reconstruction '+workflow)['id']
                if workflow=='document':
                    operation='write.create'
                    parameters={'recipe':'production_brief','version':1,'title':'Reconstruction probe',
                                'sections':[{'heading':'Editable text','paragraphs':['First version.']}]}
                    corrected={**parameters,'title':'Corrected reconstruction'}
                else:
                    audio=args.output/'input.wav'
                    with wave.open(str(audio),'wb') as stream:
                        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(48000);stream.writeframes(b'\0\0'*48000)
                    asset=store.import_asset('local',project,audio)
                    operation='video.create'
                    parameters={'width':320,'height':240,'fps':30,
                                'clips':[{'name':'card','start':0,'frames':30,'color':'#223344'}],
                                'audio':[{'name':'audio','asset':asset['id'],'start':0,'frames':30,'gain_db':-12}],
                                'titles':[{'name':'title','text':'First','start':0,'frames':30,'x':20,'y':60,'size':24,'color':'#FFFFFF'}]}
                    corrected={**parameters,'titles':[{**parameters['titles'][0],'text':'Corrected'}]}
                decisions=[{'action':'submit','operation':operation,'parameters':p} for p in (parameters,corrected)]
                decisions.append({'action':'accept','checks':{'brief':True},'findings':['Synthetic lifecycle probe.'],'limitations':[]})
                run=journal.create(project,specification('Synthetic reconstruction lifecycle probe.',workflow),1)['id']
                transport=Synthetic(decisions);coordinator=baseline_class()(store,transport=transport,poll_seconds=.1)
                result=coordinator.run(run)
                assert result['state']=='completed',result['context'].get('failure',result['state'])
                active=result['context']['active_project'];revision=store.get_revision('local',result['context']['revision'])
                assert active!=project and revision['project']==active
                assert coordinator.run(run)['state']=='completed' and transport.calls==3
                expected=4 if workflow=='document' else 2
                assert len(result['steps'])==expected
                jobs=[store.get_job('local',step['job']) for step in result['steps']]
                assert all(job['state']=='succeeded' for job in jobs)
                assert jobs[-1]['project']==active
                with store.connect() as db:
                    copied=[dict(row) for row in db.execute('SELECT sha256,project FROM assets WHERE project IN (?,?)',(project,active))]
                if workflow=='video':
                    assert len(copied)==2 and copied[0]['sha256']==copied[1]['sha256']
                reports[workflow]={'passed':True,'run':run,'project':project,'reconstruction_project':active,
                                   'revision':revision['id'],'jobs':[job['id'] for job in jobs],
                                   'synthetic_calls':transport.calls,'assets':copied}
                (args.output/'report.json').write_text(json.dumps({'provider_requests':0,'workflows':reports},indent=2)+'\n')
        finally:
            worker.terminate();worker.wait(timeout=20)
    print(json.dumps({'provider_requests':0,'workflows':reports}))


if __name__=='__main__':main()
