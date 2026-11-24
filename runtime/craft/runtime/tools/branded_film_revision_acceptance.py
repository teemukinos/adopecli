"""Build the supplied-logo portrait film through the sealed public CLI."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,subprocess,time
from PIL import Image
p=argparse.ArgumentParser();p.add_argument('package',type=Path);p.add_argument('output',type=Path);p.add_argument('logo',type=Path);p.add_argument('--expect-verification',type=Path,required=True);p.add_argument('--stage',choices=['ending','revision'],required=True);p.add_argument('--resume',action='store_true');args=p.parse_args()
package=args.package.resolve(strict=True);out=args.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=args.resume);(out/'home').mkdir(exist_ok=args.resume);lock=(out/'fixture.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
env={'HOME':str(out/'home'),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'};state=out/'state';commands=json.loads((out/'commands.json').read_text()) if args.resume else [];jobs=json.loads((out/'jobs.json').read_text()) if args.resume and (out/'jobs.json').exists() else [];cases=json.loads((out/'cases.json').read_text()) if args.resume and (out/'cases.json').exists() else []
def save(name,v):(out/name).write_text(json.dumps(v,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(v,label):
 assert v,label
 if label not in cases:cases.append(label);save('cases.json',cases)
def run(label,command,fresh=False):
 command=list(map(str,command));old=next((x for x in commands if x['label']==label),None)
 if old and not fresh:
  assert old['command']==command and old['exit']==0,label
  return old['stdout']
 start=time.time();p=subprocess.run(command,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=3700);commands.append({'label':label,'command':command,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'seconds':time.time()-start});save('commands.json',commands);assert p.returncode==0,(label,p.stderr[-1500:]);return p.stdout
def cli(label,*a,fresh=False):
 value=run(label,[package/'bin/a-dope-cli','--state',state,*a],fresh=fresh);return json.loads(value) if value.strip() else None
def receipt(folder):
 m=json.loads((folder/'project.json').read_text())
 for f in m['files']:
  p=folder/f['path'];assert p.is_file() and not p.is_symlink() and p.stat().st_size==f['bytes'] and sha(p)==f['sha256']
 return m
def job(label,project,operation,parameters,source=None):
 path=out/(label+'-request.json');encoded=json.dumps(parameters,sort_keys=True)+'\n'
 if path.exists():assert path.read_text()==encoded
 else:path.write_text(encoded)
 row=next((x for x in jobs if x['label']==label),None)
 if row is None:
  a=['submit',project,operation,'--parameters',path,'--key','branded-film-'+label,'--timeout','3600']
  if source:a+=['--source',source]
  admitted=cli(label+' submit',*a);row={'label':label,'id':admitted['id'],'operation':operation,'project':project,'source_revision':source};jobs.append(row);save('jobs.json',jobs)
 if 'result' not in row:
  observed=cli(label+' observed','job',row['id'],fresh=True)
  if observed['state']=='queued':cli(label+' worker','worker','--once',fresh=True)
  elif observed['state'] not in ['succeeded','failed','cancelled']:raise RuntimeError('Existing attempt requires observation, not replay: '+observed['state'])
  row['result']=cli(label+' result','job',row['id'],fresh=True);save('jobs.json',jobs)
 check(row['result']['state']=='succeeded',label+' native job succeeds');d=out/(label+'-checkout');cli(label+' checkout','checkout',row['result']['result_revision'],d);receipt(d);row['checkout']=str(d);save('jobs.json',jobs);return row['result']['result_revision'],d
import copy,shutil
verification=json.loads(run('verify package',[package/'bin/a-dope-guard','verify']));check(verification==json.loads(args.expect_verification.read_text()),'exact authenticated package matches')
def keys(values):return {'keys':[{'frame':f,'value':v} for f,v in values],'interpolation':'easyEase'}
source=next(x for x in jobs if x['label']=='orbit');before_dir=Path(source['checkout']);original_native=json.loads((before_dir/'native/document.ecproj').read_text());mapping=json.loads((before_dir/'native/objects.json').read_text())
edits=[]
for name in ['orbit-rim','orbit-void']:
 edits.append({'type':'property','name':name,'property':'rotation','animation':keys([(0,0),(24,0),(119,270),(167,270)])})
 edits.append({'type':'property','name':name,'property':'scale','animation':keys([(0,[100,100]),(24,[100,100]),(119,[35,120]),(167,[35,120])])})
edits.append({'type':'property','name':'satellite','property':'position','animation':keys([(0,[540,620]),(40,[850,930]),(80,[540,1240]),(119,[820,1280]),(167,[820,1280])])})
revision,ending=job('ending-revised',source['project'],'motion.edit',{'edits':edits},source['result']['result_revision'])
actual=json.loads((ending/'native/document.ecproj').read_text());check(json.loads((ending/'native/objects.json').read_text())==mapping,'ending retains complete layer identity mapping')
def property_node(document,name,prop):
 comp=next(v['kind'] for v in document['items'].values() if isinstance(v['kind'],dict) and 'layers' in v['kind'])
 layer=next(v for v in comp['layers'] if v['id']==mapping[name]['id']);transform=next(v for v in layer['props']['children'] if v['match']=='transform');return next(v for v in transform['children'] if v['match']==prop)
expected=copy.deepcopy(original_native)
for edit in edits:
 old=property_node(expected,edit['name'],edit['property']);new=property_node(actual,edit['name'],edit['property'])
 check({k:v for k,v in old.items() if k not in ['keys','value']}=={k:v for k,v in new.items() if k not in ['keys','value']},'ending retains property metadata '+edit['name']+'/'+edit['property'])
 desired=edit['animation']['keys'];observed=new['keys'];check(len(observed)==len(desired),'ending exact key count '+edit['name']+'/'+edit['property'])
 for a,b in zip(observed,desired):
  value=b['value']+[0 if edit['property']=='position' else 100] if isinstance(b['value'],list) else b['value']
  check(a['time']==b['frame']*10584000000 and a['value']['v']==value,'ending exact native key '+edit['name']+'/'+edit['property']+'/'+str(b['frame']))
 for k in ['keys','value']:
  if k in new:old[k]=copy.deepcopy(new[k])
  else:old.pop(k,None)
for k in ['activeComp','openComps']:expected.pop(k,None);actual.pop(k,None)
check(actual==expected,'entire ending native state changes only five requested property values and keys')
check(any(sha(p)==sha(args.logo) for p in (ending/'assets').iterdir() if p.is_file()),'ending revision preserves exact supplied logo bytes')
check(json.loads(run('verify package after ending',[package/'bin/a-dope-guard','verify'],fresh=True))==verification,'complete seal unchanged after ending')
save('ending-result.json',{'passed':True,'checks':len(cases),'native_jobs':len(jobs),'checkout':str(ending),'revision':revision,'five_precise_properties':True,'owner_approval':False});print(json.dumps({'stage':'ending','passed':True,'native_jobs':len(jobs),'checks':len(cases)}))
if args.stage == 'revision':
    import selectors,math,array
    from PIL import ImageChops,ImageStat
    original_film=json.loads((out/'movie-result.json').read_text());film_source=Path(original_film['checkout']);project=original_film['project'];replacement=ending/'exports/document.mp4';asset=cli('film replacement asset','import-asset',project,replacement)['id']
    edits=[{'type':'media','name':'orbit','asset':asset},{'type':'text','name':'caption-2','text':'Keep the strange.'}]+[{'type':'trim','name':name,'edge':'out','delta_frames':48} for name in ['orbit','caption-2','bed']]
    revised_revision,revised=job('revised-film',project,'video.edit',{'edits':edits},original_film['revision'])
    before=json.loads((film_source/'native/document.fcproj').read_text());after=json.loads((revised/'native/document.fcproj').read_text());mapping=json.loads((film_source/'native/objects.json').read_text());check(mapping==json.loads((revised/'native/objects.json').read_text()),'film revision retains all native clip identities')
    old_items=before['project']['items'];new_items=after['project']['items'];added=set(new_items)-set(old_items);check(len(added)==1 and not(set(old_items)-set(new_items)),'film adds only one replacement media item and retains old media');new_id=next(iter(added));media=new_items[new_id]['kind']['Media'];check(media['media']=={'File':{'path':'../assets/'+asset}},'new native picture uses only authorized replacement asset');check(sha(revised/'assets'/asset)==sha(replacement),'replacement picture bytes exact')
    expected=copy.deepcopy(before);expected['project']['items'][new_id]=copy.deepcopy(new_items[new_id]);check(int(new_id)==before['project']['next_id'] and after['project']['next_id']==int(new_id)+1,'film allocates exactly one native media identity');expected['project']['next_id']=int(new_id)+1;expected['project']['root']['children'].append({'Item':int(new_id)})
    sequence=next(v['kind']['Sequence'] for v in expected['project']['items'].values() if 'Sequence' in v['kind'])
    def clip(sequence,name):return next(i for tracks in ['video_tracks','audio_tracks'] for t in sequence[tracks] for i in t['items'] if i['id']==mapping[name]['clip'])
    clip(sequence,'orbit')['item']=int(new_id)
    for name in ['orbit','caption-2','bed']:clip(sequence,name)['duration']+=48*10584000000
    caption=clip(sequence,'caption-2');next(e for e in caption['effects'] if e['effect']=='graphic_text')['params']['text']['value']['Text']='Keep the strange.'
    observed_sequence=next(v['kind']['Sequence'] for v in after['project']['items'].values() if 'Sequence' in v['kind']);observed_caption=clip(observed_sequence,'caption-2');check(observed_caption['name'] in [caption['name'],'Keep the strange.'],'caption derived native name remains bounded');caption['name']=observed_caption['name']
    expected.pop('view',None);observed=copy.deepcopy(after);observed.pop('view',None);check(observed==expected,'entire native film changes only replacement item caption and three durations')
    for p in (film_source/'assets').iterdir():
        if p.is_file():check(sha(revised/'assets'/p.name)==sha(p),'retained prior film asset '+p.name)
    support=json.loads((package/'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text());binaries={n:Path(shutil.which(n)) for n in ['ffmpeg','ffprobe']}
    for n,b in binaries.items():check(sha(b)==support['engines'][n]['sha256'],'revision independent '+n+' matches pin')
    prefix=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)'];movie=revised/'exports/document.mp4';probe=json.loads(run('revised film probe',[*prefix,binaries['ffprobe'],'-v','error','-count_frames','-show_streams','-show_format','-of','json',movie]));v=[x for x in probe['streams'] if x['codec_type']=='video'];a=[x for x in probe['streams'] if x['codec_type']=='audio'];check(len(v)==len(a)==1,'revised film has exactly one picture and audio track');v=v[0];a=a[0];check((v['width'],v['height'],v['r_frame_rate'],int(v['nb_read_frames']))==(1080,1920,'24/1',408) and abs(float(v['duration'])-17)<.001,'revised film has exact seventeen-second full portrait timing');check(a['sample_rate']=='48000' and a['channels']==2 and abs(float(a['duration'])-17)<1/24,'revised stereo audio has seventeen-second presentation')
    earlier=json.loads((out/'original-film-decoded-frames.json').read_text());frames=[];held=None;deadline=time.monotonic()+360
    command=[*prefix,binaries['ffmpeg'],'-nostdin','-v','error','-i',movie,'-map','0:v:0','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    with (out/'revised-film-decode.log').open('wb') as error:
        process=subprocess.Popen(list(map(str,command)),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=error);selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ);os.set_blocking(process.stdout.fileno(),False)
        def block(size):
            while time.monotonic()<deadline:
                if selector.select(min(1,max(0,deadline-time.monotonic()))):return os.read(process.stdout.fileno(),min(size,1<<20))
            raise TimeoutError('Full revised decoding exceeded six minutes')
        try:
            for index in range(408):
                data=bytearray()
                while len(data)<1080*1920*3:
                    part=block(1080*1920*3-len(data));assert part,'Incomplete revised frame '+str(index);data.extend(part)
                digest=hashlib.sha256(data).hexdigest();im=Image.frombytes('RGB',(1080,1920),bytes(data));row={'frame':index,'rgb_sha256':digest}
                if index<234:check(digest==earlier[index]['rgb_sha256'],'earlier film pixels exact '+str(index))
                if index==359:held=im.copy()
                if index>=359:
                    mean=sum(ImageStat.Stat(ImageChops.difference(held,im)).mean)/3;check(mean<=1,'two-second final pose hold '+str(index));row['hold_mean_rgb_error']=mean
                if index==300:
                    with Image.open(out/'film-frame-300.png') as original:mean=sum(ImageStat.Stat(ImageChops.difference(original.convert('RGB'),im)).mean)/3
                    check(mean>1,'revised ending visibly differs from original');row['original_mean_rgb_difference']=mean
                if index in [0,180,234,240,300,359,407]:im.save(out/f'revised-film-frame-{index:03d}.png')
                frames.append(row)
            check(not block(1),'revised decoder has no extra frames');check(process.wait(timeout=30)==0,'revised decoder exits successfully')
        finally:
            if process.poll() is None:process.kill();process.wait()
            process.stdout.close();selector.close()
    save('revised-film-decoded-frames.json',frames)
    audio_values=[]
    for label,path in [('original',Path(original_film['movie'])),('revised',movie)]:
        decoded=subprocess.run([*prefix,str(binaries['ffmpeg']),'-nostdin','-v','error','-i',str(path),'-map','0:a:0','-f','f32le','-acodec','pcm_f32le','pipe:1'],stdin=subprocess.DEVNULL,capture_output=True,timeout=60);assert decoded.returncode==0,decoded.stderr[-1000:];values=array.array('f');values.frombytes(decoded.stdout);check(all(math.isfinite(v) for v in values),label+' audio entirely finite');audio_values.append(values)
    values=audio_values[1];count=len(values)//2;check(len(values)%2==0 and abs(count-17*48000)<=2048,'revised full decoded stereo duration matches within AAC allowance');peak=max(abs(v) for v in values);check(.01<peak<.8,'revised audio retains headroom');difference=max(abs(x-y) for x,y in zip(audio_values[0][:14*48000*2],values[:14*48000*2]));check(difference<1e-5,'first fourteen seconds of decoded audio preserved')
    for row in jobs:receipt(Path(row['checkout']))
    check(json.loads(run('verify package after revision',[package/'bin/a-dope-guard','verify'],fresh=True))==verification,'complete seal unchanged after revised film')
    save('revision-result.json',{'passed':True,'checks':len(cases),'native_jobs':len(jobs),'checkout':str(revised),'revision':revised_revision,'movie':str(movie),'sha256':sha(movie),'frames':408,'seconds':17,'earlier_exact_frames':234,'maximum_hold_mean_rgb_error':max(x.get('hold_mean_rgb_error',0) for x in frames),'decoded_audio_sample_frames':count,'audio_peak':peak,'earlier_audio_maximum_error':difference,'all_prior_receipts_unchanged':True,'owner_approval':False,'listening_review':False,'bounded_quote_established':False,'actual_billing_known':False,'published':False})
    print(json.dumps({'stage':'revision','passed':True,'checks':len(cases),'native_jobs':len(jobs),'frames_decoded':408}))
