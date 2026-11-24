"""Qualify complete native Audio preservation and an editable campaign cue.

Run with a sealed package's Python: audio_acceptance.py PACKAGE NEW_OUTPUT.
Only private states, original procedural WAVs and native headless tools are used.
No network, services, editor windows or model APIs. --resume reuses recorded
completed commands; a previously admitted nonterminal job requires explicit
reconciliation and is never replayed automatically.
"""
import argparse
import array
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import sqlite3
import struct
import subprocess
import sys
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('package',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--resume',action='store_true')
args=parser.parse_args();package=args.package.resolve(strict=True);out=args.output.absolute()
out.mkdir(parents=True,exist_ok=args.resume,mode=0o700)
lock=(out/'fixture.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
(out/'home').mkdir(exist_ok=args.resume,mode=0o700);(out/'sources').mkdir(exist_ok=args.resume)
cli=package/'bin/a-dope-cli';state=out/'state';env={'HOME':str(out/'home'),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'}
logs=json.loads((out/'commands.json').read_text()) if args.resume else []
jobs=json.loads((out/'jobs.json').read_text()) if args.resume and (out/'jobs.json').exists() else []
cases=[]
def save(name,value):(out/name).write_text(json.dumps(value,indent=2)+'\n')
def check(value,label):assert value,label;cases.append(label);save('cases.json',cases)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def immutable(path,data):
 if path.exists():assert path.read_bytes()==data,'existing fixture input changed: '+str(path)
 else:path.write_bytes(data)
def run(label,arguments,expected=0,fresh=False):
 arguments=list(map(str,arguments));fingerprints={p:digest(p) for p in arguments if Path(p).is_file()}
 prior=next((r for r in logs if r['label']==label),None)
 if prior and not fresh:
  assert prior['args']==arguments and prior['files']==fingerprints and prior['exit']==expected,label
  return json.loads(prior['stdout']) if prior['stdout'].strip() else None
 start=time.monotonic();p=subprocess.run(arguments,stdin=subprocess.DEVNULL,env=env,capture_output=True,text=True,timeout=600)
 logs.append({'label':label,'args':arguments,'files':fingerprints,'exit':p.returncode,'seconds':time.monotonic()-start,'stdout':p.stdout,'stderr':p.stderr});save('commands.json',logs)
 assert p.returncode==expected,(label,p.returncode,p.stderr)
 return json.loads(p.stdout) if p.stdout.strip() else None
def call(label,*arguments,expected=0,fresh=False):return run(label,[cli,'--state',state,*arguments],expected,fresh)
def verify_checkout(directory):
 receipt=json.loads((directory/'project.json').read_text())
 for item in receipt['files']:
  data=(directory/item['path']).read_bytes();assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],item
 return receipt

def job(label,project,operation,parameters,source=None,success=True):
 request=out/(label+'-request.json');immutable(request,(json.dumps(parameters,sort_keys=True)+'\n').encode())
 old=next((j for j in jobs if j['label']==label),None)
 if old:assert (old['project'],old['operation'],old['parameters'],old['source'])==(project,operation,parameters,source),label
 arguments=['submit',project,operation,'--parameters',request,'--key',label]
 if source:arguments+=['--source',source]
 submitted=call(label+' submit',*arguments)
 if not old:
  old={'label':label,'project':project,'operation':operation,'parameters':parameters,'source':source,'stateDirectory':str(state),'id':submitted['id']};jobs.append(old);save('jobs.json',jobs)
 if 'result' not in old:
  observed=call(label+' admitted state','job',submitted['id'],fresh=True)
  if observed['state']=='queued':call(label+' worker','worker','--once')
  elif observed['state'] not in ('succeeded','failed'):raise RuntimeError('Reconcile admitted job before resuming: '+json.dumps(observed))
  old['result']=call(label+' result','job',submitted['id'],fresh=True);save('jobs.json',jobs)
 result=old['result'];assert result['state']==('succeeded' if success else 'failed'),result
 if not success:
  check(result.get('result_revision') is None,label+' publishes no revision');return result
 destination=out/label;call(label+' checkout','checkout',result['result_revision'],destination)
 receipt=verify_checkout(destination);check(receipt['validation']['native_cold_reopen'] and receipt['validation']['native_state_equal'],label+' preserves complete native state through cold reopening')
 old['checkout']=str(destination);save('jobs.json',jobs);return result['result_revision'],destination


def write_wave(path,rate,channels,bits,frames,value,float32=False,extensible=False):
 data=bytearray()
 for i in range(frames):
  values=value(i)
  for v in values:
   if float32:data.extend(struct.pack('<f',v))
   elif bits==8:data.append(round(v*128)+128)
   else:data.extend(round(v*(2**(bits-1))).to_bytes(bits//8,'little',signed=True))
 align=channels*bits//8;kind=3 if float32 else 1;fmt=struct.pack('<HHIIHH',kind,channels,rate,rate*align,align,bits)
 if extensible:fmt=struct.pack('<HHIIHHHHI',0xfffe,channels,rate,rate*align,align,bits,22,bits,4 if channels==1 else 3)+struct.pack('<IHH8s',kind,0,0x0010,bytes.fromhex('800000aa00389b71'))
 body=b'WAVEfmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(data))+data
 if len(data)%2:body+=b'\0'
 immutable(path,b'RIFF'+struct.pack('<I',len(body))+body)

def read_wave(path):
 raw=path.read_bytes();assert raw[:4]==b'RIFF' and raw[8:12]==b'WAVE' and int.from_bytes(raw[4:8],'little')==len(raw)-8
 cursor=12;fmt=None;pcm=None
 while cursor<len(raw):
  tag=raw[cursor:cursor+4];length=int.from_bytes(raw[cursor+4:cursor+8],'little');body=raw[cursor+8:cursor+8+length];assert len(body)==length
  if tag==b'fmt ':fmt=body
  if tag==b'data':assert pcm is None;pcm=body
  cursor+=8+length+(length%2)
 kind,channels,rate,byte_rate,align,bits=struct.unpack('<HHIIHH',fmt[:16])
 if kind==0xfffe:kind=int.from_bytes(fmt[24:26],'little')
 assert kind==3 and bits==32 and channels==2 and align==8 and byte_rate==rate*8
 values=array.array('f');values.frombytes(pcm)
 if sys.byteorder!='little':values.byteswap()
 assert all(math.isfinite(v) for v in values)
 return {'rate':rate,'frames':len(values)//2,'pcm':pcm,'samples':values,'peak':max(map(abs,values),default=0)}

def native(directory):return json.loads((directory/'native/document.scraft').read_text())
def tracks(model):return {t['name']:t for t in model['tracks']}
def clips(model):return {c['name']:c for t in model['tracks'] for c in t['playlists'][0]['clips']}
def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]
def source_hashes(directory):return {p.relative_to(directory).as_posix():digest(p) for p in (directory/'native/Audio Files').glob('*.wav')}
def altered_project(source,destination,change):
 if not destination.exists():shutil.copytree(source,destination)
 model=native(source);change(model);data=(json.dumps(model,sort_keys=True)+'\n').encode();p=destination/'native/document.scraft'
 p.write_bytes(data);receipt=json.loads((source/'project.json').read_text());record=next(r for r in receipt['files'] if r['path']=='native/document.scraft');record.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest());(destination/'project.json').write_text(json.dumps(receipt,indent=2)+'\n');verify_checkout(destination)
 return destination

verification=run('verify payload before',[package/'bin/a-dope-guard','verify'],fresh=True);save('verification-before.json',verification);check(verification['verified'],'sealed package verifies before Audio production')
# Owned procedural stems are source material; the native engine performs production.
rate=48000;frames=8*rate;rng=random.Random(971)
pulse=out/'sources/pulse.wav';motif=out/'sources/motif.wav';transition=out/'sources/transition.wav'
def pulse_value(i):
 t=i/rate;phase=t%0.5;envelope=(1-math.exp(-phase/0.008))*math.exp(-phase/0.16);v=0.32*envelope*(math.sin(2*math.pi*65.4064*t)+0.18*math.sin(2*math.pi*130.8128*t));return (v,v)
def motif_value(i):
 t=i/rate;note=min(int(t/0.5),3);u=t-note*0.5;frequency=(261.6256,329.6276,391.9954,523.2511)[note];v=0.32*(1-math.exp(-u/0.006))*math.exp(-u/0.20)*(math.sin(2*math.pi*frequency*u)+0.12*math.sin(2*math.pi*2*frequency*u));return(v,0.88*v)
def transition_value(i):
 t=i/rate;envelope=math.sin(math.pi*t/1.5)**2;noise=rng.uniform(-1,1);v=0.05*envelope*(noise+0.5*math.sin(2*math.pi*(350*t+300*t*t)));return(v,-0.65*v)
write_wave(pulse,rate,2,24,frames,pulse_value);write_wave(motif,rate,2,24,2*rate,motif_value);write_wave(transition,rate,2,24,3*rate//2,transition_value)
p=call('cue project','create-project','A dope CLI / Eight-second campaign cue')['id']
a={name:call(name+' source','import-asset',p,path)['id'] for name,path in [('pulse',pulse),('motif',motif),('transition',transition)]}
params={'sample_rate':rate,'frames':frames,'tracks':[
 {'name':'pulse','gain_db':-8,'clips':[{'name':'pulse-bed','asset':a['pulse'],'start':0,'frames':frames,'fade_in':9600,'fade_out':48000,'fade_shape':'linear'}]},
 {'name':'motif','gain_db':-5,'clips':[{'name':'cue-opening','asset':a['motif'],'start':48000,'frames':96000,'gain_db':-3,'fade_in':960,'fade_out':12000,'fade_shape':'equal_power'},
 {'name':'cue-return','asset':a['motif'],'start':192000,'frames':96000,'gain_db':-3,'fade_in':960,'fade_out':12000,'fade_shape':'equal_power'}]},
 {'name':'transition','gain_db':-8,'clips':[{'name':'transition-tail','asset':a['transition'],'start':288000,'frames':72000,'fade_in':12000,'fade_out':24000,'fade_shape':'s_curve'}]}]}
r,d=job('original',p,'audio.create',params);original=native(d);original_audio=read_wave(d/'exports/document.wav');original_sources=source_hashes(d)
check(original_audio['rate']==48000 and original_audio['frames']==frames and 0.05<original_audio['peak']<0.5,'original cue has exact eight-second stereo timing, finite samples and deliberate headroom')
check(set(tracks(original))=={'pulse','motif','transition'} and len(clips(original))==4,'native cue retains three named tracks and four independently editable clips')
edits=[{'type':'clip','name':'cue-return','start':204000,'source_in':6000,'frames':72000,'gain_db':-6,'fade_in':2400,'fade_out':18000,'fade_shape':'linear'},
 {'type':'track','name':'transition','gain_db':-11}]
r1,d1=job('revised',p,'audio.edit',{'edits':edits},r);revised=native(d1);revised_audio=read_wave(d1/'exports/document.wav');expected=copy.deepcopy(original);c=clips(expected)['cue-return'];c.update(start=204000,length=72000,gain_db=-6);c['content']['Audio']['offset']=6000;c['fade_in'].update(len=2400,shape='Linear');c['fade_out'].update(len=18000,shape='Linear');tracks(expected)['transition']['mixer']['volume_db']=-11
check(expected==revised,'revision changes only the requested clip position, source window, gain, fades and transition track gain')
check(source_hashes(d1)==original_sources,'revision preserves every packaged source byte')
check(original_audio['pcm'][:192000*8]==revised_audio['pcm'][:192000*8] and original_audio['pcm'][360000*8:]==revised_audio['pcm'][360000*8:],'PCM outside both changed time ranges stays byte-identical')
check(original_audio['pcm']!=revised_audio['pcm'] and revised_audio['frames']==frames,'revision changes audible samples while preserving total delivery duration')
# Standard native metadata must survive; an unknown top-level field must fail closed.
metadata_source=altered_project(d1,out/'metadata-project',lambda m:m.update(comments='Keep the approved arrangement and source credits.'))
mp=call('metadata import','import-project',metadata_source,'Cue with author note');mr,md=job('metadata-revision',mp['project']['id'],'audio.edit',{'edits':[{'type':'clip','name':'cue-opening','gain_db':-4.125}]},mp['revision']['id'])
metadata=native(md);expected=copy.deepcopy(revised);expected['comments']='Keep the approved arrangement and source credits.';clips(expected)['cue-opening']['gain_db']=f32(-4.125)
check(metadata==expected,'complete native metadata and every unrelated field survive a fractional-gain revision')
unknown=altered_project(d1,out/'unknown-field-project',lambda m:m.update(future_owner_annotation={'text':'Do not silently discard this source field.'}))
up=call('unknown field import','import-project',unknown,'Unsupported native annotation');uh=call('unknown head before','project',up['project']['id']);failed=job('unknown-session-field',up['project']['id'],'audio.edit',{'edits':[{'type':'clip','name':'cue-opening','gain_db':-3}]},up['revision']['id'],False)
check('reopen/save changed editable content' in json.dumps(failed),'native parser field loss is refused rather than reported as preserved content')
check(call('unknown head after','project',up['project']['id'])==uh,'unknown-field refusal leaves the imported source head and annotation intact')
# Fresh-state portable editing continues from the exact revised project.
state=out/'portable-state';ip=call('portable import','import-project',d1,'Portable campaign cue');pp=ip['project']['id'];pr=ip['revision']['id'];check(ip['revision']['validation']['scope']=='bundle_integrity' and not ip['revision']['validation']['native_cold_reopen'],'portable import claims integrity only before the native worker runs')
restore=[{'type':'clip','name':'cue-return','start':192000,'source_in':0,'frames':96000,'gain_db':-3,'fade_in':960,'fade_out':12000,'fade_shape':'equal_power'},{'type':'track','name':'transition','gain_db':-8}]
pr1,pd=job('portable-restore',pp,'audio.edit',{'edits':restore},pr)
check(native(pd)==original and read_wave(pd/'exports/document.wav')['pcm']==original_audio['pcm'],'portable revision restores the complete original session and exact original PCM')
head=call('negative head before','project',pp)
for label,changes,reason in [
 ('partial-batch',[{'type':'clip','name':'cue-opening','gain_db':-12},{'type':'clip','name':'absent','gain_db':-3}],'unknown clip'),
 ('overlap',[{'type':'clip','name':'cue-return','start':96000}],'overlaps'),
 ('source-overrun',[{'type':'clip','name':'cue-return','source_in':96000}],'exceeds its source'),
 ('oversized-fade',[{'type':'clip','name':'cue-return','fade_in':96001}],'fade must fit')]:
 result=job(label,pp,'audio.edit',{'edits':changes},pr1,False);check(reason in json.dumps(result),label+' explains the unsupported edit');check(call(label+' head after','project',pp)==head,label+' does not publish a partial edit')
# Numeric fixtures exercise the advertised WAV widths, source rates and channel counts.
state=out/'state';format_records=[]
for channels,extensible in ((1,False),(2,False),(1,True),(2,True)):
 for bits,floating in ((8,False),(16,False),(24,False),(32,False),(32,True)):
  label=('extensible-' if extensible else '')+('mono' if channels==1 else 'stereo')+'-'+('float32' if floating else 'pcm'+str(bits));fp=call(label+' project','create-project',label+' admission')['id'];specs=[]
  for index,sr in enumerate((44100,48000,96000)):
   path=out/'sources'/f'{label}-{sr}.wav';values=(0.25,) if channels==1 else (0.25,0.125);write_wave(path,sr,channels,bits,sr//10,lambda i,v=values:v,float32=floating,extensible=extensible);asset=call(label+' source '+str(sr),'import-asset',fp,path)['id'];specs.append({'name':'source-'+str(sr),'asset':asset,'start':index*4800,'source_in':480,'frames':2400})
  rr,dd=job(label,fp,'audio.create',{'sample_rate':48000,'frames':14400,'tracks':[{'name':'format-check','clips':specs}]});wav=read_wave(dd/'exports/document.wav');gain=10**(-3/20) if channels==1 else 1
  for index,sr in enumerate((44100,48000,96000)):
   center=(index*4800+1200)*2;expected_values=(0.25*gain,0.25*gain) if channels==1 else (0.25,0.125)
   check(max(abs(wav['samples'][center+k]-expected_values[k]) for k in (0,1))<2e-5,label+' '+str(sr)+' Hz retains expected channel levels after native resampling')
   check(all(v==0 for v in wav['samples'][(index*4800+2600)*2:(index*4800+4700)*2]),label+' '+str(sr)+' Hz respects sample-exact clip bounds and following silence')
  format_records.append({'label':label,'project':fp,'revision':rr,'checkout':str(dd),'pcmSHA256':hashlib.sha256(wav['pcm']).hexdigest()})
# All output session rates and fade curves have independent pointwise amplitude checks.
fade_records=[]
for sr in (44100,48000,96000):
 label='fade-'+str(sr);fp=call(label+' project','create-project',label+' curves')['id'];path=out/'sources'/f'constant-{sr}.wav';write_wave(path,sr,2,32,sr,lambda i:(0.25,0.125),float32=True);asset=call(label+' source','import-asset',fp,path)['id'];length=sr//5;fade=length//2;specs=[]
 for index,shape in enumerate(('linear','equal_power','s_curve')):specs.append({'name':shape,'asset':asset,'start':index*length,'frames':length,'gain_db':-3,'fade_in':fade,'fade_out':fade,'fade_shape':shape})
 rr,dd=job(label,fp,'audio.create',{'sample_rate':sr,'frames':3*length,'tracks':[{'name':'curves','gain_db':-6,'clips':specs}]});wav=read_wave(dd/'exports/document.wav');check(wav['rate']==sr and wav['frames']==3*length,label+' exports the exact requested session rate and sample count')
 curve_reports=[]
 for index,shape in enumerate(('linear','equal_power','s_curve')):
  # The pinned mixer interpolates gain across at most 31 sample intervals.
  # Bound its error against the ideal curve independently: L*h/2 at the
  # linear cusp, or max(|f''|)*h*h/8 for each smooth curved envelope.
  amplitude=0.25*10**(-9/20);span=31
  bound=amplitude*(span/(2*fade) if shape=='linear' else math.pi**2*span**2/((32 if shape=='equal_power' else 16)*fade**2))+2e-7
  error=0
  for relative in range(length):
   t=min(relative/fade,(length-relative)/fade,1);factor=t if shape=='linear' else math.sin(math.pi*t/2) if shape=='equal_power' else 0.5-0.5*math.cos(math.pi*t)
   expected_values=(amplitude*factor,amplitude*0.5*factor);actual=wav['samples'][(index*length+relative)*2:(index*length+relative)*2+2]
   error=max(error,max(abs(actual[k]-expected_values[k]) for k in (0,1)))
  check(error<=bound,label+' '+shape+' stays inside the derived interpolation bound at every sample')
  check(wav['samples'][index*length*2]==0 and wav['samples'][index*length*2+1]==0,label+' '+shape+' starts at exactly zero')
  curve_reports.append({'shape':shape,'samplesPerChannel':length,'maximumAbsoluteError':error,'derivedAbsoluteErrorBound':bound})
 fade_records.append({'label':label,'revision':rr,'checkout':str(dd),'curves':curve_reports})
# Float output must keep positive headroom instead of silently normalizing or clipping.
hp=call('headroom project','create-project','Float headroom')['id'];path=out/'sources/headroom.wav';write_wave(path,48000,2,32,4800,lambda i:(0.75,0.5),float32=True);ha=call('headroom source','import-asset',hp,path)['id'];hr,hd=job('headroom',hp,'audio.create',{'sample_rate':48000,'frames':4800,'tracks':[{'name':'headroom','gain_db':6,'clips':[{'name':'hot','asset':ha,'start':0,'frames':4800}]}]});hot=read_wave(hd/'exports/document.wav');check(abs(hot['samples'][2000]-0.75*10**(6/20))<2e-6 and hot['peak']>1,'float output retains requested above-unity headroom without clipping or normalization')
# Source originals and every native dependency remain independent portable bytes.
check(source_hashes(d)==original_sources and source_hashes(d1)==original_sources,'later work leaves both original and revised native source dependencies unchanged')
all_groups=[]
for directory in (out/'state',out/'portable-state'):
 with sqlite3.connect('file:'+str(directory/'studio.sqlite3')+'?mode=ro',uri=True) as db:
  check(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],directory.name+' database integrity passes')
  groups=[r[0] for r in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
 for group in groups:
  try:os.killpg(group,0)
  except ProcessLookupError:pass
  else:raise AssertionError('native group remains: '+str(group))
 all_groups+=groups
check(len(all_groups)==len(jobs),'every native job has a durable execution record and its process group is absent')
check(run('verify payload after',[package/'bin/a-dope-guard','verify'],fresh=True)==verification,'production and refusal cases leave the sealed payload unchanged')
for record in jobs:
 if 'checkout' in record:verify_checkout(Path(record['checkout']))
check(True,'all successful native outputs and portable receipts match every artifact hash')
save('context.json',{'original':str(d),'revised':str(d1),'portable':str(pd),'metadata':str(md),'parameters':params,'revisionParameters':{'edits':edits},'project':p,'originalRevision':r,'revisedRevision':r1,'formatFixtures':format_records,'fadeFixtures':fade_records,'originalPeak':original_audio['peak'],'revisedPeak':revised_audio['peak']})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'nativeJobs':len(jobs),'successfulNativeJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedNativeJobs':sum(j['result']['state']=='failed' for j in jobs),'groups':all_groups,'allNativeGroupsAbsent':True,'package':str(package),'verification':verification,'inputFormatCombinations':60,'outputSessionRates':[44100,48000,96000],'ownerListeningApproval':False,'wholeAudioQualified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'nativeJobs':len(jobs),'revised':str(d1)}))
