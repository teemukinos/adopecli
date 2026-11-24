"""Qualify actual campaign render interruption, explicit retry and cancellation.

All mutations use the authenticated public CLI. SQLite queries are enforced query-only and
records process identities and publication counts. No lease or clock is changed.
Use separate stages; an existing live or failed stage is never silently rerun.
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import sqlite3
import subprocess
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('package',type=Path)
parser.add_argument('output',type=Path)
parser.add_argument('input',type=Path)
parser.add_argument('--expect-verification',type=Path,required=True)
parser.add_argument('--stage',choices=['interrupt','retry','compare','cancel','dependencies'],required=True)
parser.add_argument('--resume',action='store_true')
a=parser.parse_args();package=a.package.resolve(strict=True);source=a.input.resolve(strict=True);out=a.output.absolute();out.mkdir(mode=0o700,exist_ok=a.resume)
lock=(out/'fixture.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
(out/'home').mkdir(exist_ok=a.resume);state=out/'state';env={'HOME':str(out/'home'),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'}
cases=json.loads((out/'cases.json').read_text()) if (out/'cases.json').exists() else []
commands=json.loads((out/'commands.json').read_text()) if (out/'commands.json').exists() else []

def save(name,value):
 (out/name).write_text(json.dumps(value,indent=2)+'\n')

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def check(value,label):
 if not value:raise AssertionError(label)
 if label not in cases:cases.append(label);save('cases.json',cases)

def command(label,args,timeout=120):
 started=time.time();args=list(map(str,args));p=subprocess.run(args,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout)
 commands.append({'label':label,'command':args,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'seconds':time.time()-started});save('commands.json',commands)
 check(p.returncode==0,label+' command succeeds')
 return json.loads(p.stdout) if p.stdout.strip() else None

def cli(label,*args,timeout=120):
 return command(label,[package/'bin/a-dope-cli','--state',state,*args],timeout)

def rows(sql,parameters=()):
 with sqlite3.connect((state/'studio.sqlite3').as_uri()+'?mode=rw',uri=True) as db:
  db.execute('PRAGMA query_only=ON')
  db.row_factory=sqlite3.Row
  return [dict(x) for x in db.execute(sql,parameters)]

def snapshot(label):
 result={t:rows('SELECT * FROM '+t) for t in ['jobs','attempts','attempt_executions','attempt_reconciliations','revisions','retries','events']}
 save(label+'.json',result);return result

def absent(group,timeout=20):
 deadline=time.monotonic()+timeout
 while True:
  try:os.killpg(group,0)
  except OSError as e:
   if e.errno==errno.ESRCH:return True
  if time.monotonic()>=deadline:return False
  time.sleep(.1)

def receipt(folder):
 manifest=json.loads((folder/'project.json').read_text())
 for row in manifest['files']:
  p=folder/row['path'];check(p.is_file() and not p.is_symlink() and p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],'receipt '+str(folder.name)+' '+row['path'])
 return manifest

def submit(label,key):
 return cli(label,'submit',context['project'],'construct.render','--parameters',out/'render-request.json','--source',context['source_revision'],'--key',key,'--timeout','3600')

def start_worker(label):
 log=(out/(label+'.log')).open('wb');args=[str(package/'bin/a-dope-cli'),'--state',str(state),'worker','--once']
 proc=subprocess.Popen(args,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
 save(label+'-process.json',{'pid':proc.pid,'command':args,'started':time.time()})
 return proc,log

def finish_worker(label,proc,log):
 value=json.loads((out/(label+'-process.json')).read_text());value.update(exit=proc.returncode,completed=time.time());save(label+'-process.json',value);log.close()

def observe_frames(job,proc,label):
 deadline=time.monotonic()+180
 while proc.poll() is None and time.monotonic()<deadline:
  found=rows('SELECT j.state,j.lease_until,a.token,e.process_group FROM jobs j JOIN attempts a ON a.job=j.id AND a.number=j.attempt JOIN attempt_executions e ON e.token=a.token WHERE j.id=?',(job,))
  if found and found[0]['process_group']:
   row=found[0];group=row['process_group'];attempt=state/'attempts'/row['token'];frames=sorted((attempt/'construction/components'/context['component']/'frames').glob('*.png'))
   processes=[]
   for line in subprocess.check_output(['/bin/ps','-axo','pid=,pgid=,command='],text=True).splitlines():
    parts=line.strip().split(None,2)
    if len(parts)==3 and parts[1]==str(group) and parts[2].startswith('/Applications/Blender.app/Contents/MacOS/Blender '):processes.append({'pid':int(parts[0]),'group':group,'command':parts[2]})
   if len(frames)>=3 and processes and row['state']=='running':
    result={'job':job,'worker_pid':proc.pid,'group':group,'native_processes':processes,'frames_observed':len(frames),'first_frame_sha256':sha(frames[0]),'lease_until':row['lease_until'],'observed':time.time()};save(label+'-live.json',result);return result
  time.sleep(.15)
 raise AssertionError('No actual partial native render observed for '+label)

verified=command('verify package',[package/'bin/a-dope-guard','verify']);check(verified==json.loads(a.expect_verification.read_text()) and verified['verified'],'exact package authentication')
manifest=receipt(source);input_hashes={x['path']:x['sha256'] for x in manifest['files']};input_hashes['project.json']=sha(source/'project.json')
if (out/'input-hashes.json').exists():check(input_hashes==json.loads((out/'input-hashes.json').read_text()),'original input remains unchanged')
else:save('input-hashes.json',input_hashes)
if (out/'context.json').exists():context=json.loads((out/'context.json').read_text())
else:
 check(a.stage=='interrupt','new fixture starts with interruption')
 doc=json.loads((source/'construction/document.json').read_text());check(len(doc['components'])==1,'one source component');component=doc['components'][0];p=component['parameters'];check(component['engine']=='blender' and (p['width'],p['height'],p['fps'],p['frames'])==(1920,1080,24,288),'full original campaign scope')
 cli('resource limits','limits','--wall-seconds','3600','--cpu-seconds','14400','--memory-mib','8192','--attempt-mib','4096')
 imported=cli('import complete campaign','import-project',source,'Campaign recovery qualification');context={'project':imported['project']['id'],'source_revision':imported['revision']['id'],'component':component['id']};save('context.json',context);save('render-request.json',{'outputs':[{'component':component['id'],'format':'mp4'}]})

marker=out/(a.stage+'-complete.json')
if marker.exists():
 check(json.loads(marker.read_text())['passed'],'completed stage remains recorded')
 print(json.dumps({'stage':a.stage,'already_complete':True,'checks':len(cases)}));raise SystemExit(0)

if a.stage=='interrupt':
 if (out/'interruption-job.json').exists():
  job=json.loads((out/'interruption-job.json').read_text());observed=cli('observe existing unstarted submission','job',job['id']);check(observed['state']=='queued' and observed['attempt']==0,'only an authoritative never-started submission can continue')
 else:
  job=submit('submit interruption','campaign-recovery-render');save('interruption-job.json',job)
 replay=submit('replay queued submission','campaign-recovery-render');check(replay['id']==job['id'] and replay['attempt']==0,'queued submission replay preserves durable identity')
 proc,log=start_worker('interrupted-worker');group=None
 try:
  live=observe_frames(job['id'],proc,'interrupted');group=live['group'];check(proc.poll() is None,'owned supervisor still live before intentional crash');proc.kill();proc.wait(timeout=10);check(proc.returncode==-signal.SIGKILL,'owned supervisor killed by requested signal');check(absent(group),'crashed native process group becomes absent')
 finally:
  if proc.poll() is None:proc.terminate();proc.wait(timeout=30)
  finish_worker('interrupted-worker',proc,log)
 before=cli('observe crashed job','job',job['id']);check(before['attempt']==1 and before['result_revision'] is None,'crash publishes no result');save('before-recovery.json',before)
 check(cli('head after crash','project',context['project'])['head']==context['source_revision'],'crash retains original head')
 check(len(rows('SELECT id FROM revisions WHERE project=?',(context['project'],)))==1,'crash creates no revision')
 deadline=time.monotonic()+50
 while before['lease_until'] and time.time()<=before['lease_until']:
  check(time.monotonic()<deadline,'natural lease expiry is bounded');time.sleep(.2)
 cli('recover expired lease','recover');after=cli('observe interrupted state','job',job['id']);check(after['state']=='interrupted' and after['error']['code']=='lease_expired','natural lease expiry fences interrupted attempt')
 cli('idle worker cannot replay interruption','worker','--once');after=cli('observe no automatic replay','job',job['id']);check(after['state']=='interrupted' and after['attempt']==1 and after['result_revision'] is None,'idle worker does not automatically replay')
 preview=cli('preview stopped attempt reconciliation','reconcile-attempt',job['id'],'--attempt','1');check(preview['evidence']=={'eligible':True,'reason':'registered_group_absent'},'reconciliation independently proves native group absent')
 applied=cli('reconcile stopped attempt','reconcile-attempt',job['id'],'--attempt','1','--apply');check(applied['reconciled'] and not applied['result_published'] and not applied['artifacts_removed'],'explicit reconciliation preserves evidence without publishing')
 snapshot('interrupted-state');save(marker.name,{'passed':True,'job':job['id'],'group':group,'natural_lease_expiry':True,'automatic_replay':False,'checks':len(cases)})
elif a.stage=='retry':
 check((out/'interrupt-complete.json').exists(),'interruption proved before retry');job=json.loads((out/'interruption-job.json').read_text());now=cli('observe before explicit retry','job',job['id']);check(now['state']=='failed' and now['attempt']==1,'retry begins only from reconciled stopped attempt')
 first=cli('explicit retry','retry',job['id'],'--key','campaign-explicit-retry');second=cli('repeat explicit retry','retry',job['id'],'--key','campaign-explicit-retry');check(first==second and second['state']=='queued','duplicate retry request is idempotent')
 proc,log=start_worker('retried-worker')
 try:proc.wait(timeout=3650)
 finally:
  if proc.poll() is None:proc.terminate();proc.wait(timeout=30)
  finish_worker('retried-worker',proc,log)
 check(proc.returncode==0,'retry worker exits successfully');result=cli('retry result','job',job['id']);check(result['state']=='succeeded' and result['attempt']==2 and result['result_revision'],'explicit retry succeeds as attempt two');save('retry-result.json',result)
 replay=submit('replay successful submission','campaign-recovery-render');check(replay['id']==job['id'] and replay['result_revision']==result['result_revision'] and replay['attempt']==2,'successful submission replay creates no new attempt')
 repeat=cli('repeat successful retry key','retry',job['id'],'--key','campaign-explicit-retry');check(repeat['state']=='succeeded' and repeat['attempt']==2,'successful retry key creates no new attempt')
 check(len(rows('SELECT id FROM revisions WHERE project=?',(context['project'],)))==2,'exactly one new revision after retry')
 checkout=out/'recovered';cli('checkout recovered campaign','checkout',result['result_revision'],checkout);receipt(checkout)
 check((checkout/'construction/document.json').read_bytes()==(source/'construction/document.json').read_bytes(),'complete construction document unchanged')
 for name,digest in input_hashes.items():
  if '/assets/' in name or '/fonts/' in name:check(sha(checkout/name)==digest,'exact retained dependency '+name)
 before=json.loads((source/'construction/components'/context['component']/'native/inspection.json').read_text());after=json.loads((checkout/'construction/components'/context['component']/'native/inspection.json').read_text());check(before['objects']==after['objects'],'all native object records preserved')
 groups=rows('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL');check(all(absent(x['process_group']) for x in groups),'both retry history groups absent');snapshot('retried-state');save(marker.name,{'passed':True,'job':job['id'],'revision':result['result_revision'],'checkout':str(checkout),'checks':len(cases),'frame_comparison_pending':True})
elif a.stage=='compare':
 check((out/'retry-complete.json').exists(),'recovered campaign exists before full comparison')
 support=json.loads((package/'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text())
 binaries={}
 for name in ('ffmpeg','ffprobe'):
  binary=Path(shutil.which(name) or '')
  check(binary.is_file() and sha(binary)==support['engines'][name]['sha256'],'independent '+name+' uses pinned binary');binaries[name]=binary
 prefix=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)']
 records={};frame_lists={}
 for label,folder in [('original',source),('recovered',out/'recovered')]:
  receipt(folder);movie=folder/'construction/components'/context['component']/'exports/film.mp4'
  probe=command(label+' full stream probe',[*prefix,binaries['ffprobe'],'-v','error','-count_frames','-show_streams','-show_format','-of','json',movie]);save(label+'-probe.json',probe)
  check(len(probe['streams'])==1,label+' has exactly one silent video stream');v=probe['streams'][0]
  check((v['codec_type'],v['codec_name'],v['width'],v['height'],v['r_frame_rate'],int(v['nb_read_frames']))==('video','h264',1920,1080,'24/1',288),label+' retains full campaign format')
  check(abs(float(probe['format']['duration'])-12)<.001,label+' remains twelve seconds')
  args=list(map(str,[*prefix,binaries['ffmpeg'],'-nostdin','-v','error','-i',movie,'-map','0:v:0','-fps_mode','passthrough','-pix_fmt','rgb24','-f','framemd5','-']))
  p=subprocess.run(args,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=180);(out/(label+'-decode.log')).write_text(p.stderr);check(p.returncode==0,label+' independent full decoding succeeds');(out/(label+'-frames.md5')).write_text(p.stdout)
  frames=[]
  for line in p.stdout.splitlines():
   if line and not line.startswith('#'):
    values=[x.strip() for x in line.split(',')];check(len(values)==6 and int(values[4])==1920*1080*3,label+' decoded frame byte size matches');frames.append({'dts':int(values[1]),'pts':int(values[2]),'duration':int(values[3]),'bytes':int(values[4]),'md5':values[5]})
  check(len(frames)==288 and [x['pts'] for x in frames]==list(range(288)),label+' decodes every frame in timeline order');frame_lists[label]=frames
  records[label]={'path':str(movie),'bytes':movie.stat().st_size,'sha256':sha(movie),'decoded_frames':len(frames),'decoded_rgb_bytes':sum(x['bytes'] for x in frames)}
 differences=[i for i,(before,after) in enumerate(zip(frame_lists['original'],frame_lists['recovered'])) if before!=after]
 save('frame-comparison.json',{'passed':not differences,'records':records,'different_frame_indices':differences,'exact_rgb_frame_identity':not differences,'independent_binaries':{k:{'path':str(p),'sha256':sha(p)} for k,p in binaries.items()},'continuous_playback_observed':False,'owner_approval':False})
 check(not differences,'all 288 recovered frames exactly match original decoded RGB pixels')
 save(marker.name,{'passed':True,'frames_per_movie':288,'checks':len(cases)})
elif a.stage=='dependencies':
 check((out/'compare-complete.json').exists(),'complete recovered output precedes dependency refusal checks')
 folder=out/'damaged-inputs';folder.mkdir();before={t:rows('SELECT count(*) AS n FROM '+t)[0]['n'] for t in ['jobs','projects','revisions']};records=[]
 logo='construction/assets/281283b4ce204d9a8cd08a6285ddf859';font='construction/components/'+context['component']+'/fonts/archivo-variable.ttf'
 for label,path,action in [('missing-logo',logo,'remove'),('denied-font',font,'deny')]:
  check(path in input_hashes,'source contains dependency '+path)
  dest=folder/label;subprocess.run(['/bin/cp','-cR',str(source),str(dest)],check=True)
  for name,digest in input_hashes.items():check(sha(dest/name)==digest,label+' exact input copy '+name)
  target=dest/path;mode=target.stat().st_mode & 0o777
  if action=='remove':target.unlink()
  else:target.chmod(0)
  try:
   args=[str(package/'bin/a-dope-cli'),'--state',str(state),'import-project',str(dest),'Refused '+label]
   p=subprocess.run(args,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120)
   check(p.returncode!=0 and not p.stdout.strip(),label+' refuses import');error=json.loads(p.stderr)
   check(error['error']==('FileNotFoundError' if action=='remove' else 'PermissionError') and path in error['message'],label+' identifies exact missing or denied dependency')
   records.append({'label':label,'mutation':action,'path':path,'command':args,'exit':p.returncode,'error':error,'import_rejected':True})
  finally:
   if action=='deny':target.chmod(mode)
 after={t:rows('SELECT count(*) AS n FROM '+t)[0]['n'] for t in before};check(before==after,'dependency refusals admit no project job or revision')
 for name,digest in input_hashes.items():check(sha(source/name)==digest,'dependency checks preserve original '+name)
 save('dependency-refusals.json',{'passed':True,'cases':records,'before':before,'after':after,'scope':'bundle ingestion only; not native fallback or render-time dependency qualification'})
 save(marker.name,{'passed':True,'cases':len(records),'checks':len(cases)})
elif a.stage=='cancel':
 check((out/'retry-complete.json').exists(),'successful retry precedes independent cancellation')
 check(not (out/'cancellation-job.json').exists(),'no existing cancellation is replayed')
 # Use a separate project so the source revision and successful head stay intact.
 imported=cli('import cancellation campaign','import-project',source,'Campaign cancellation qualification');context={'project':imported['project']['id'],'source_revision':imported['revision']['id'],'component':context['component']};save('cancellation-context.json',context)
 job=submit('submit cancellation','campaign-cancel-render');save('cancellation-job.json',job);proc,log=start_worker('cancelled-worker');group=None
 try:
  live=observe_frames(job['id'],proc,'cancelled');group=live['group'];cli('request cancellation','cancel',job['id']);proc.wait(timeout=30);check(absent(group),'cancelled native group absent')
 finally:
  if proc.poll() is None:proc.terminate();proc.wait(timeout=30)
  finish_worker('cancelled-worker',proc,log)
 result=cli('cancellation result','job',job['id']);check(result['state']=='cancelled' and result['attempt']==1 and result['result_revision'] is None,'cancelled partial render publishes no result');check(cli('head after cancellation','project',context['project'])['head']==context['source_revision'],'cancellation preserves original head')
 replay=submit('replay cancelled submission','campaign-cancel-render');check(replay['id']==job['id'] and replay['state']=='cancelled' and replay['attempt']==1,'cancelled submission replay does not restart')
 check(len(rows('SELECT id FROM revisions WHERE project=?',(context['project'],)))==1,'cancelled campaign has only imported revision');snapshot('cancelled-state');save(marker.name,{'passed':True,'job':job['id'],'group':group,'checks':len(cases)})
verified=command('verify package after stage',[package/'bin/a-dope-guard','verify']);check(verified==json.loads(a.expect_verification.read_text()),'package remains authenticated after stage');print(json.dumps({'stage':a.stage,'passed':True,'checks':len(cases)}))
