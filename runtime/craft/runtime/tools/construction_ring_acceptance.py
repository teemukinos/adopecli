"""Reproduce the exact ring fixture through an installed Dobe CLI.

Arguments: package-directory, fresh-evidence-directory. Runs all 528 frames.
The supplied package's external Blender/FFmpeg pins must match this Mac.
"""
import copy,hashlib,json,os,subprocess,sys
from pathlib import Path
package=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(parents=True)
cli=package/'bin/dobe';state=out/'state';records=[]
def command(*args):
    p=subprocess.run([cli,'--state',state,*map(str,args)],capture_output=True,text=True,env={**os.environ,'PATH':'/usr/bin:/bin'})
    records.append({'args':list(map(str,args)),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr});(out/'events.json').write_text(json.dumps(records,indent=2)+'\n')
    if p.returncode:raise RuntimeError(p.stderr[-2000:])
    return json.loads(p.stdout) if p.stdout.strip() else None
command('limits','--wall-seconds',7200,'--cpu-seconds',14400,'--memory-mib',8192,'--attempt-mib',8192)
project=command('create-project','Constructed ring fixture')['id'];revision=None
def job(op,params,key):
    global revision
    path=out/(key+'.json');path.write_text(json.dumps(params,indent=2)+'\n')
    item=command('submit',project,op,'--parameters',path,'--key',key,'--timeout',7200,*(['--source',revision] if revision else []))
    command('worker','--once');result=command('job',item['id'])
    if result['state']!='succeeded':raise RuntimeError(result)
    revision=result['result_revision']
doc=json.loads((Path(__file__).resolve().parents[1]/'fixtures/construction/ring.json').read_text())
job('construct.create',{'document':doc},'base-create')
job('construct.render',{'outputs':[{'component':'intro','format':'png','frame':216}]},'base-still')
job('construct.render',{'outputs':[{'component':'intro','format':'mp4'}]},'base-movie')
command('checkout',revision,out/'base')
job('construct.verify',{},'base-cold-reopen')
edits=[]
for path,before,value in [(['frames'],240,288),(['preview_frame'],216,264),(['objects',1,'color'],'#FF6A2B','#6EA8FF'),(['objects',2,'color'],'#FF6A2B','#6EA8FF'),(['objects',4,'text'],'Imagination. Executed.','Built to be revised.')]:
    edits.append({'component':'intro','action':'set','path':['parameters',*path],'before':before,'value':value})
expected=hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(',',':')).encode()).hexdigest()
job('construct.edit',{'document_sha256':expected,'edits':edits},'exact-revision')
job('construct.render',{'outputs':[{'component':'intro','format':'png','frame':264}]},'revised-still')
job('construct.render',{'outputs':[{'component':'intro','format':'mp4'}]},'revised-movie')
command('checkout',revision,out/'revised')
print(json.dumps({'passed':True,'evidence':str(out)}))
