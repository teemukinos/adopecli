"""Refuse native packed image/font substitutions without altering valid artwork."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from PIL import Image

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('package',type=Path);parser.add_argument('output',type=Path);parser.add_argument('input',type=Path)
parser.add_argument('--expect-verification',type=Path,required=True)
parser.add_argument('--replacement-font',type=Path,required=True)
parser.add_argument('--expect-font-sha256',required=True)
parser.add_argument('--baseline-png',type=Path,required=True)
parser.add_argument('--expect-baseline-sha256',required=True)
parser.add_argument('--resume',action='store_true')
MUTATOR="import bpy,hashlib,json,sys\nfrom pathlib import Path\nrequest=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text());root=Path(request['root']);bpy.ops.wm.open_mainfile(filepath=str(root/'native/scene.blend'),load_ui=False,use_scripts=False);bpy.context.preferences.filepaths.save_version=0\n\ndef digest(b):return hashlib.sha256(b).hexdigest()\ndef observations():\n rows={}\n for obj in bpy.context.scene.objects:\n  if not obj.get('construction'):continue\n  source=json.loads(obj['construction'])\n  if source['kind']=='image':\n   image=obj.data.materials[0].node_tree.nodes['Image'].image;rows[obj.name]={'kind':'image','packed_sha256':digest(image.packed_file.data),'declared_sha256':digest((root/'assets'/source['asset']).read_bytes())}\n  if source['kind']=='text':\n   rows[obj.name]={'kind':'font','packed_sha256':digest(obj.data.font.packed_file.data),'declared_sha256':digest((root/'fonts/archivo-variable.ttf').read_bytes())}\n return rows\nbefore=observations()\nif request['variant']=='image':\n obj=bpy.data.objects['supplied_logo'];image=bpy.data.images.new('qualification-mismatch',width=8,height=8,alpha=True);image.generated_color=(1,0,1,1);image.filepath_raw=str(root/'synthetic-mismatch.png');image.file_format='PNG';image.save();image=bpy.data.images.load(str(root/'synthetic-mismatch.png'));image.pack();obj.data.materials[0].node_tree.nodes['Image'].image=image\nelif request['variant']=='font':\n font=bpy.data.fonts.load(request['replacement_font']);font.pack();bpy.data.objects['headline_one'].data.font=font\nelse:raise AssertionError('Unknown variant')\nbpy.ops.wm.save_as_mainfile(filepath=str(root/'native/scene.blend'));after=observations();Path(request['observation']).write_text(json.dumps({'variant':request['variant'],'before':before,'after':after,'declared_asset_and_font_unchanged':True},indent=2)+'\\n')\n"

a=parser.parse_args();package=a.package.resolve(strict=True);source=a.input.resolve(strict=True);out=a.output.absolute();out.mkdir(mode=0o700,exist_ok=a.resume);lock=(out/'fixture.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);(out/'home').mkdir(exist_ok=a.resume);state=out/'state';env={'HOME':str(out/'home'),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'}

def load(name,default):return json.loads((out/name).read_text()) if (out/name).exists() else default
cases=load('cases.json',[]);commands=load('commands.json',[]);jobs=load('jobs.json',[]);projects=load('projects.json',{})
def save(name,value):(out/name).write_text(json.dumps(value,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(value,label):
 if not value:raise AssertionError(label)
 if label not in cases:cases.append(label);save('cases.json',cases)
def run(label,args,timeout=180):
 args=list(map(str,args));p=subprocess.run(args,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout);commands.append({'label':label,'command':args,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr});save('commands.json',commands);check(p.returncode==0,label+' succeeds');return json.loads(p.stdout) if p.stdout.strip() else None

def cli(label,*args):return run(label,[package/'bin/a-dope-cli','--state',state,*args])
def receipt(folder):
 d=json.loads((folder/'project.json').read_text())
 for row in d['files']:
  p=folder/row['path'];check(p.is_file() and not p.is_symlink() and p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],'receipt '+folder.name+' '+row['path'])
 return d

def job(label,project,revision,operation,parameters,expected_error=None):
 path=out/(label+'-request.json');encoded=json.dumps(parameters,sort_keys=True)+'\n'
 if path.exists():check(path.read_text()==encoded,label+' request remains identical')
 else:path.write_text(encoded)
 row=next((x for x in jobs if x['label']==label),None)
 if row is None:
  admitted=cli(label+' submit','submit',project,operation,'--source',revision,'--parameters',path,'--key',label,'--timeout','180');row={'label':label,'id':admitted['id'],'project':project,'source_revision':revision,'operation':operation};jobs.append(row);save('jobs.json',jobs)
 observed=cli(label+' observe','job',row['id'])
 if observed['state']=='queued' and observed['attempt']==0:cli(label+' worker','worker','--once');observed=cli(label+' result','job',row['id'])
 check(observed['attempt']==1,label+' has exactly one explicit attempt')
 check(observed['state']==('failed' if expected_error else 'succeeded'),label+' reaches expected terminal state')
 if expected_error:
  check(observed['result_revision'] is None and expected_error in observed['error']['message'],label+' refuses exact native mismatch without result')
  check(cli(label+' original head','project',project)['head']==revision,label+' preserves imported project head')
 else:check(bool(observed['result_revision']),label+' publishes successful checked source')
 row['result']=observed;save('jobs.json',jobs);return row

verified=run('verify package',[package/'bin/a-dope-guard','verify']);check(verified['verified'] and verified==json.loads(a.expect_verification.read_text()),'exact independently authenticated package')
manifest=receipt(source);original={x['path']:x['sha256'] for x in manifest['files']};original['project.json']=sha(source/'project.json')
check(not (out/'input-hashes.json').exists() or load('input-hashes.json',{})==original,'input receipt remains unchanged');save('input-hashes.json',original)
check(sha(a.replacement_font)==a.expect_font_sha256,'explicit negative font bytes match');check(sha(a.baseline_png)==a.expect_baseline_sha256,'baseline PNG bytes match')
check(all((source/'construction/components/hero'/p).is_file() for p in ['native/scene.blend','fonts/archivo-variable.ttf']),'full campaign native inputs exist')
support=json.loads((package/'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text());blender=Path('/Applications/Blender.app/Contents/MacOS/Blender');check(sha(blender)==support['engines']['blender']['sha256'],'mutation probe uses pinned Blender')
cli('resource limits','limits','--wall-seconds','180','--cpu-seconds','600','--memory-mib','4096','--attempt-mib','1024')
mutator=out/'native-mutation.py'
if mutator.exists():check(mutator.read_text()==MUTATOR,'mutation helper remains unchanged')
else:mutator.write_text(MUTATOR)
for variant in ['original','image','font']:
 bundle=source
 if variant!='original':
  bundle=out/(variant+'-bundle')
  if not (out/(variant+'-ready.json')).exists():
   check(not bundle.exists(),variant+' partial mutation requires explicit inspection');subprocess.run(['/bin/cp','-cR',str(source),str(bundle)],check=True)
   req=out/(variant+'-mutation.json');req.write_text(json.dumps({'root':str(bundle/'construction/components/hero'),'variant':variant,'replacement_font':str(a.replacement_font.resolve()),'observation':str(out/(variant+'-packed-observation.json'))})+'\n')
   command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',str(blender),'-b','--factory-startup','--disable-autoexec','--python-exit-code','1','-P',str(mutator),'--',str(req)]
   p=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=90);(out/(variant+'-mutation.log')).write_text(p.stdout+p.stderr);check(p.returncode==0,variant+' native mutation succeeds')
   component=bundle/'construction/components/hero';cm=bundle/'construction/manifest.json';d=json.loads(cm.read_text());n='native/scene.blend';d['components']['hero']['files'][n]={'sha256':sha(component/n),'bytes':(component/n).stat().st_size};cm.write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
   d=json.loads((bundle/'project.json').read_text())
   for row in d['files']:f=bundle/row['path'];row.update(sha256=sha(f),bytes=f.stat().st_size)
   (bundle/'project.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\n');save(variant+'-ready.json',{'manifest_sha256':sha(bundle/'project.json')})
  check(sha(bundle/'project.json')==load(variant+'-ready.json',{})['manifest_sha256'],variant+' changed bundle retains exact receipt');receipt(bundle)
  observed=load(variant+'-packed-observation.json',{});check(all(x['packed_sha256']==x['declared_sha256'] for x in observed['before'].values()),variant+' mutation starts with exact packed dependencies')
  changed=[k for k,v in observed['after'].items() if v['packed_sha256']!=v['declared_sha256']];check(changed==(['supplied_logo'] if variant=='image' else ['headline_one']),variant+' changes only the selected packed dependency')
  for name,digest in original.items():
   if '/assets/' in name or '/fonts/' in name or name=='construction/document.json':check(sha(bundle/name)==digest,variant+' preserves declared input '+name)
 if variant not in projects:
  imported=cli(variant+' import','import-project',bundle,'Construction dependency '+variant);projects[variant]={'project':imported['project']['id'],'revision':imported['revision']['id']};save('projects.json',projects)
 p=projects[variant];error=None if variant=='original' else 'Native packed image differs from declared asset: supplied_logo' if variant=='image' else 'Native packed font differs from declared font: headline_one'
 checked=job('verify-'+variant,p['project'],p['revision'],'construct.verify',{},error)
 revision=p['revision'] if error else checked['result']['result_revision']
 rendered=job('render-'+variant,p['project'],revision,'construct.render',{'outputs':[{'component':'hero','format':'png','frame':0}]},error)
 if not error:
  checkout=out/'original-verified';
  if not checkout.exists():cli('checkout verified control','checkout',rendered['result']['result_revision'],checkout)
  receipt(checkout);inspection=json.loads((checkout/'construction/components/hero/native/inspection.json').read_text());check(inspection['native_dependency_bytes_verified'] and len(inspection['native_dependency_bindings'])==4,'correct source proves all four native dependency bindings')
  check(all(x['sha256']==x['declared_sha256'] for x in inspection['native_dependency_bindings'].values()),'every packed byte digest equals its declaration')
  before=json.loads((source/'construction/components/hero/native/inspection.json').read_text());check(before['objects']==inspection['objects'] and before['camera']==inspection['camera'],'all native object records and camera remain unchanged')
  image=checkout/'construction/components/hero/exports/still.png'
  with Image.open(image) as x,Image.open(a.baseline_png) as y:
   check(x.size==y.size==(1920,1080),'actual control keeps full campaign dimensions');check(x.convert('RGBA').tobytes()==y.convert('RGBA').tobytes(),'actual corrected control pixels exactly match original package')
  for name,digest in original.items():
   if '/assets/' in name or '/fonts/' in name or name=='construction/document.json':check(sha(checkout/name)==digest,'control retains exact declared source '+name)
for name,digest in original.items():check(sha(source/name)==digest,'original input unchanged '+name)
with sqlite3.connect((state/'studio.sqlite3').as_uri()+'?mode=rw',uri=True) as db:
 db.execute('PRAGMA query_only=ON');db.row_factory=sqlite3.Row;durable={t:[dict(x) for x in db.execute('SELECT * FROM '+t)] for t in ['jobs','attempts','attempt_executions','revisions']}
check(len(durable['jobs'])==9 and len(durable['attempts'])==6 and len(durable['revisions'])==5,'exact durable imports attempts and publication counts')
for row in durable['attempt_executions']:
 try:os.killpg(row['process_group'],0)
 except ProcessLookupError:row['group_absent']=True
 else:raise AssertionError('Recorded native group remains')
save('durable-state.json',durable);verified=run('verify package after qualification',[package/'bin/a-dope-guard','verify']);check(verified==json.loads(a.expect_verification.read_text()),'package unchanged after qualification');save('result.json',{'passed':True,'checks':len(cases),'native_jobs':6,'native_successes':2,'native_expected_failures':4,'separate_imports':3,'groups_absent':6,'actual_original_pixels_equal':True,'owner_approval':False,'full_release_qualified':False});print(json.dumps(load('result.json',{})))
