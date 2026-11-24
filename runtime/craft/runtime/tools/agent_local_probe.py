#!/usr/bin/env python3
"""Local engine probes. These fixtures are not benchmark creative inputs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave
import math
import struct


def main():
    p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--workflow');a=p.parse_args()
    package=a.package.resolve();resources=package/'lib/dobe';a.output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(resources/'runtime'))
    os.environ['STUDIO_BUNDLE_RESOURCES']=str(resources)
    os.environ['PATH']=os.pathsep.join(str(x) for x in (resources/'engines').glob('*/bin'))+os.pathsep+os.environ['PATH']
    from studio_runtime.store import Store
    from studio_runtime import agent_catalog, production_schema, construction_schema
    store=Store(a.output/'state');reports={}
    worker=subprocess.Popen([str(package/'bin/a-dope-cli'),'--state',str(store.root),'worker'],stdout=(a.output/'worker.log').open('w'),stderr=subprocess.STDOUT)
    def execute(project,op,params,source=None):
        from studio_runtime.capabilities import validate
        validate(op,params,source)
        job=store.submit('local',project,op,params,op+'-'+str(time.time_ns()),source,300)
        start=time.monotonic()
        while time.monotonic()-start<360:
            job=store.get_job('local',job['id'])
            if job['state'] not in ('queued','running','validating'):break
            if worker.poll() is not None:raise RuntimeError('Probe worker exited')
            time.sleep(.2)
        return job
    try:
        for workflow in agent_catalog.WORKFLOWS:
            reports[workflow]={'availability':agent_catalog.availability(workflow)}
        fixtures=Path(__file__).resolve().parents[1]/'fixtures/construction'
        inputs={
          'image':('image.create',{'width':320,'height':240,'background':'#FFF8EB','layers':[{'name':'probe','type':'text','x':20,'y':50,'text':'Local probe','font':'Inter','size':24,'color':'#222222'}]}),
          'video':('video.create',{'width':320,'height':240,'fps':30,'clips':[{'name':'probe','start':0,'frames':30,'color':'#334455'}],'titles':[{'name':'title','text':'Local probe','start':0,'frames':30,'x':20,'y':40,'size':24,'color':'#FFFFFF'}]}),
          'animation':('construct.create',{'document':json.loads((fixtures/'interactive.json').read_text())}),
          'document':('write.create',{'recipe':'production_brief','version':1,'title':'Local probe','sections':[{'heading':'Validation','paragraphs':['Editable local source.']}]}),
          '3d':('production.create',{'document':{'schema_version':1,'profile':'product-scene-v1','policy':{'network':'offline','media_generation':'disabled'},'render':{'width':64,'height':64,'samples':1,'seed':19},'camera':{'location':[1,-2,1],'target':[0,0,0],'lens':50,'fstop':8},'world':{'color':'#FFFFFF','strength':.5},'materials':[{'id':'plain','color':'#AA4422','roughness':.5,'metallic':0,'transmission':0,'ior':1.5}],'objects':[{'id':'box','kind':'box','material':'plain','location':[0,0,0],'rotation':[0,0,0],'size':[.5,.5,.5],'bevel':.01},{'id':'label','kind':'text','material':'plain','location':[0,-.3,0],'rotation':[90,0,0],'text':'A','size':.1,'extrude':0}],'lights':[{'id':'key','location':[1,-2,2],'target':[0,0,0],'color':'#FFFFFF','power':300,'size':2,'size_y':2}]}})}
        for workflow,(op,params) in inputs.items():
            if a.workflow and workflow!=a.workflow:continue
            try:
                project=store.create_project('local',workflow+' local probe')['id']
                if workflow=='video':
                    audio=a.output/'probe.wav'
                    with wave.open(str(audio),'wb') as stream:
                        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(48000)
                        stream.writeframes(b''.join(struct.pack('<h',round(2000*math.sin(2*math.pi*220*i/48000))) for i in range(48000*6)))
                    asset=store.import_asset('local',project,audio)
                    params={**params,'clips':[{'name':'card'+str(i),'start':i*60,'frames':60,'color':color} for i,color in enumerate(('#334455','#553344','#445533'))],
                            'titles':[{'name':'title'+str(i),'text':'Probe '+str(i),'start':i*60,'frames':60,'x':20,'y':40,'size':24,'color':'#FFFFFF'} for i in range(3)],
                            'audio':[{'name':'audio','asset':asset['id'],'start':0,'frames':180,'gain_db':-12}]}
                job=execute(project,op,params)
                reports[workflow]['creation']=job
                if job['state']=='succeeded' and workflow in ('image','video','animation','document'):
                    revision=store.get_revision('local',job['result_revision'])
                    if workflow=='image':
                        edits={'edits':[{'name':'probe','text':'Edited local probe'}]};edit_operation='image.edit'
                    elif workflow=='video':
                        edits={'edits':[{'type':'text','name':'title0','text':'Edited probe'}]};edit_operation='video.edit'
                    elif workflow=='animation':
                        edits={'document_sha256':construction_schema.digest(params['document']),
                               'edits':[{'component':'control','action':'set','path':['parameters','objects',1,'text'],
                                         'before':'A dobe cli','value':'Edited probe'}]};edit_operation='construct.edit'
                    else:
                        native=next(f for f in revision['files'] if f['path']=='native/project.dobewrite')
                        edits={'expected_sha256':native['sha256'],
                               'edits':[{'kind':'text.replace','path':'/body/0','start':0,'end':11,
                                         'expected':'Local probe','value':'Edited local probe'}]};edit_operation='write.edit'
                    reports[workflow]['native_edit']=execute(project,edit_operation,edits,job['result_revision'])
                    edited=reports[workflow]['native_edit']
                    if edited['state']=='succeeded':
                        reports[workflow]['edit_validation']=store.get_revision('local',edited['result_revision'])['validation']
                        job=edited
                if job['state']=='succeeded' and workflow=='document':
                    reports[workflow]['export']=execute(project,'write.export',{'format':'png','scale':1},job['result_revision'])
                if job['state']=='succeeded' and workflow=='3d':
                    d=params['document'];edits=[{'collection':'objects','id':'box','field':'location','before':[0,0,0],'value':[.1,0,0]}, {'collection':'camera','id':'camera','field':'lens','before':50,'value':55},{'collection':'objects','id':'label','field':'text','before':'A','value':'B'}]
                    reports[workflow]['native_edit']=execute(project,'production.edit',{'recipe_sha256':production_schema.digest(d),'edits':edits},job['result_revision'])
                    reports[workflow]['multi_view']=execute(project,'production.inspect',{},reports[workflow]['native_edit']['result_revision'])
            except Exception as exc:reports[workflow]['error']={'type':type(exc).__name__,'message':str(exc)}
            (a.output/'report.json').write_text(json.dumps(reports,indent=2)+'\n')
    finally:
        worker.terminate();worker.wait(timeout=20)
    print(json.dumps({name:{k:v.get('state',v) if isinstance(v,dict) else v for k,v in result.items()} for name,result in reports.items()},indent=2))

if __name__=='__main__':main()
