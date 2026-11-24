"""Local installed-CLI acceptance. No remote services or generated media.

Run with Python 3.13, an explicitly built package directory, and a fresh evidence
folder. Records every command result. The worker starts after submitting clients
exit, proving that native work is owned by the existing durable runtime.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

package=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=False)
state=out/'state';cli=package/'bin/dobe';fixtures=Path(__file__).resolve().parents[1]/'fixtures/construction';events=[]
env={**os.environ,'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'}
def record(kind,value):
    events.append({'kind':kind,'value':value});(out/'events.json').write_text(json.dumps(events,indent=2)+'\n');return value
def command(*args):
    p=subprocess.run([str(cli),'--state',str(state),*map(str,args)],capture_output=True,text=True,env=env)
    record('command',{'args':list(map(str,args)),'code':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    if p.returncode:raise RuntimeError(p.stderr[-2000:])
    return json.loads(p.stdout) if p.stdout.strip() else None
def mcp(name,args):
    msg={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':args}}
    p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=json.dumps(msg)+'\n',capture_output=True,text=True,env=env,check=True)
    r=json.loads(p.stdout)['result'];record('mcp',{'name':name,'result':r})
    if r.get('isError'):raise RuntimeError(r)
    return json.loads(r['content'][0]['text'])
def job(project,operation,params,key,source=None,use_mcp=False):
    path=out/(key+'.json');path.write_text(json.dumps(params,indent=2)+'\n')
    if use_mcp:
        args={'project':project,'operation':operation,'parameters':params,'idempotency_key':key,'timeout_seconds':3600}
        if source:args['source_revision']=source
        submitted=mcp('submit_job',args)
    else:submitted=command('submit',project,operation,'--parameters',path,'--key',key,'--timeout',3600,*(['--source',source] if source else []))
    command('worker','--once');result=command('job',submitted['id']);record('settled',result)
    if result['state']!='succeeded':raise RuntimeError(json.dumps(result))
    return result['result_revision']
def fixture(name):return json.loads((fixtures/(name+'.json')).read_text())
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def edit(doc,cid,path,value):
    target=next(n for n in doc['components'] if n['id']==cid)
    for token in path:target=target[token]
    return {'document_sha256':digest(doc),'edits':[{'component':cid,'action':'set','path':path,'before':target,'value':value}]}
command('limits','--wall-seconds',3600,'--cpu-seconds',7200,'--memory-mib',8192,'--attempt-mib',8192)
image=fixture('image');p=command('create-project','Constructed layered image')['id'];first=job(p,'construct.create',{'document':image},'image-create')
revised=job(p,'construct.edit',edit(image,'poster',['parameters','layers',1,'text'],'Constructed. Editable.'),'image-edit',first)
checked=job(p,'construct.verify',{},'image-cold-reopen',revised);command('checkout',checked,out/'image')
imported=command('import-project',out/'image','Portable construction image');record('imported',imported)
portable=job(imported['project']['id'],'construct.verify',{},'image-portable-reopen',imported['revision']['id'])
# Different components share only explicitly named, hash-verified artifacts.
video=fixture('image');video['components'].append({'id':'edit','engine':'video','inputs':{'0'*32:{'component':'poster','artifact':'exports/document.png'}},'parameters':{'width':640,'height':360,'fps':24,'clips':[{'name':'poster','start':0,'frames':48,'asset':'0'*32},{'name':'ending','start':48,'frames':24,'color':'#090B0E'}],'titles':[{'name':'caption','text':'Built from native layers','start':48,'frames':24,'x':60,'y':160,'size':28,'color':'#F4F3EA'}]}})
(fixtures/'video.json').write_text(json.dumps(video,indent=2)+'\n')
p=command('create-project','Constructed video assembly')['id'];v1=job(p,'construct.create',{'document':video},'video-create')
v2=job(p,'construct.edit',edit(video,'edit',['parameters','titles',0,'text'],'Revised in native timeline'),'video-edit',v1);command('checkout',v2,out/'video-before-refresh')
video['components'][1]['parameters']['titles'][0]['text']='Revised in native timeline'
v3=job(p,'construct.edit',edit(video,'poster',['parameters','layers',1,'text'],'Native layers, revised.'),'video-dependency-refresh',v2);command('checkout',v3,out/'video')
before=json.loads((out/'video-before-refresh/construction/manifest.json').read_text())['components']['edit'];after=json.loads((out/'video/construction/manifest.json').read_text())['components']['edit']
assert before['files']['native/document.fcproj']==after['files']['native/document.fcproj']
assert before['files']['exports/frame-0.png']!=after['files']['exports/frame-0.png']
record('dependency_refresh',{'native_timeline_unchanged':True,'actual_frame_changed':True})
interactive=fixture('interactive');p=mcp('create_project',{'name':'Constructed interactive animation'})['id'];assert mcp('plan_construction',{'document':interactive})==command('construct','plan','--spec',fixtures/'interactive.json')
r1=job(p,'construct.create',{'document':interactive},'interactive-create',use_mcp=True)
r2=job(p,'construct.edit',edit(interactive,'control',['parameters','objects',1,'text'],'Constructed control'),'interactive-edit',r1,True)
r3=job(p,'construct.verify',{},'interactive-cold-reopen',r2,True);command('checkout',r3,out/'interactive')
record('passed',True)
print(json.dumps({'passed':True,'evidence':str(out)}))
