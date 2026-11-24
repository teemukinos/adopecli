"""Build the supplied-logo portrait film through the sealed public CLI."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,subprocess,time
from PIL import Image
p=argparse.ArgumentParser();p.add_argument('package',type=Path);p.add_argument('output',type=Path);p.add_argument('logo',type=Path);p.add_argument('--expect-verification',type=Path,required=True);p.add_argument('--stage',choices=['portal','visuals','audio','movie'],required=True);p.add_argument('--resume',action='store_true');args=p.parse_args()
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
verification=json.loads(run('verify package',[package/'bin/a-dope-guard','verify']));check(verification==json.loads(args.expect_verification.read_text()),'exact authenticated package matches');check(sha(args.logo)=='dcf3c923d8a9e9b4bc44e0bb82505553fd098b5e49434be6398a843ef21c186d','exact supplied campaign logo input')
cli('limits','limits','--wall-seconds','3600','--cpu-seconds','14400','--memory-mib','8192','--attempt-mib','4096')
project=cli('portal project','create-project','A dope CLI / Portal shot')['id'];asset=cli('portal logo','import-asset',project,args.logo)['id']
with Image.open(args.logo) as im:logo_width,logo_height=im.size
frames=120
logo={'name':'supplied-logo','type':'media','asset':asset,'format':'png','start':0,'frames':frames,'position':[540,240],'scale':[700/logo_width*100]*2}
def shape(name,w,h,color,position,kind='ellipse',animation=None):
 row={'name':name,'type':'shape','shape':kind,'width':w,'height':h,'color':color,'start':0,'frames':frames,'position':position}
 if animation:row['animation']=animation
 return row
def keys(values):return {'keys':[{'frame':f,'value':v} for f,v in values],'interpolation':'easyEase'}
layers=[]
for i,(w,h) in enumerate([(650,860),(490,660),(330,460)]):
 rotation=keys([(0,-12+12*i),(95,12-12*i),(119,12-12*i)])
 layers+=[shape(f'portal-{i}-rim',w,h,'#EEEDE3',[540,930],animation={'rotation':rotation}),shape(f'portal-{i}-void',w-16,h-16,'#080A0D',[540,930],animation={'rotation':rotation})]
layers.append(shape('traveler',130,130,'#DFFF00',[540,930],animation={'position':keys([(0,[540,690]),(24,[540,690]),(95,[540,1090]),(119,[540,1090])]),'scale':keys([(0,[45,45]),(95,[100,100]),(119,[100,100])])}));layers.append(logo)
parameters={'width':1080,'height':1920,'fps':24,'frames':frames,'background':'#080A0D','layers':layers}
revision,d=job('portal',project,'motion.create',parameters)
check(any(sha(p)==sha(args.logo) for p in (d/'assets').iterdir() if p.is_file()),'native portal retains exact supplied logo bytes')
probe=json.loads((d/'exports/probe.json').read_text());check((probe['width'],probe['height'],probe['frames'])==(1080,1920,120),'native portal full portrait timing')
for frame in [0,60,119]:
 with Image.open(d/f'exports/frame-{frame}.png') as im:check(im.size==(1080,1920),'portal actual frame size '+str(frame))
check(json.loads(run('verify package after portal',[package/'bin/a-dope-guard','verify'],fresh=True))==verification,'complete seal unchanged after portal')
save('portal-result.json',{'passed':True,'checks':len(cases),'native_jobs':len(jobs),'project':project,'revision':revision,'checkout':str(d),'logo_input_dimensions':[logo_width,logo_height],'full_film_complete':False,'owner_approval':False,'published':False});print(json.dumps({'stage':'portal','passed':True,'checks':len(cases),'checkout':str(d)}))

if args.stage in ['visuals','audio','movie']:
    rows=[]
    for label in ['staircase','orbit']:
        frames=120 if label=='staircase' else 168
        project=cli(label+' project','create-project','A dope CLI / '+label.title()+' shot')['id']
        asset=cli(label+' logo','import-asset',project,args.logo)['id']
        layers=[]
        if label=='staircase':
            for i in range(9):
                x,y=300+60*i,1140-55*i
                destination=[x,y-140] if i==4 else [x,y+35]
                layers.append(shape('step-'+str(i),210,34,'#DFFF00' if i==4 else '#EEEDE3',[x,y],kind='rect',animation={'position':keys([(0,[x,y]),(24,[x,y]),(95,destination),(119,destination)]),'rotation':keys([(0,-18),(95,-18),(119,-18)])}))
        else:
            for name,w,h,color in [('orbit-rim',590,590,'#EEEDE3'),('orbit-void',568,568,'#080A0D')]:
                layers.append(shape(name,w,h,color,[540,930],kind='rect',animation={'rotation':keys([(0,0),(24,0),(119,90),(167,90)])}))
            layers.append(shape('satellite',130,130,'#DFFF00',[540,620],animation={'position':keys([(0,[540,620]),(40,[850,930]),(80,[540,1240]),(119,[230,930]),(167,[230,930])])}))
        layers.append({'name':'supplied-logo','type':'media','asset':asset,'format':'png','start':0,'frames':frames,'position':[540,240],'scale':[700/logo_width*100]*2})
        spec={'width':1080,'height':1920,'fps':24,'frames':frames,'background':'#080A0D','layers':layers}
        revision,d=job(label,project,'motion.create',spec)
        check(any(sha(p)==sha(args.logo) for p in (d/'assets').iterdir() if p.is_file()),label+' retains exact supplied logo bytes')
        probe=json.loads((d/'exports/probe.json').read_text());check((probe['width'],probe['height'],probe['frames'])==(1080,1920,frames),label+' full portrait timing')
        for frame in [0,frames//2,frames-1]:
            with Image.open(d/f'exports/frame-{frame}.png') as im:check(im.size==(1080,1920),label+' actual frame size '+str(frame))
        rows.append({'label':label,'project':project,'revision':revision,'checkout':str(d),'frames':frames})
    check(json.loads(run('verify package after visuals',[package/'bin/a-dope-guard','verify'],fresh=True))==verification,'complete seal unchanged after visuals')
    save('visuals-result.json',{'passed':True,'checks':len(cases),'native_jobs':len(jobs),'shots':rows,'full_film_complete':False,'owner_approval':False})
    print(json.dumps({'stage':'visuals','passed':True,'checks':len(cases),'native_jobs':len(jobs)}))

if args.stage in ['audio','movie']:
    import math,struct,wave,array,shutil
    source_dir=out/'audio-sources';source_dir.mkdir(exist_ok=True)
    rate=48000;sample_count=17*rate
    for name in ['pulse','motif','air']:
        path=source_dir/(name+'.wav')
        if not path.exists():
            pcm=bytearray()
            for i in range(sample_count):
                t=i/rate
                if name=='pulse':
                    phase=t%0.625;envelope=(1-math.exp(-phase/.008))*math.exp(-phase/.15)
                    value=.22*envelope*(math.sin(2*math.pi*65.4064*t)+.15*math.sin(2*math.pi*130.8128*t))
                elif name=='motif':
                    beat=int(t/.625);u=t-beat*.625;frequency=[261.6256,311.127,391.9954,523.2511][(beat//2)%4]
                    envelope=(1-math.exp(-u/.012))*math.exp(-u/.22) if beat%2==0 else 0
                    value=.16*envelope*(math.sin(2*math.pi*frequency*u)+.15*math.sin(2*math.pi*2*frequency*u))
                else:
                    value=.025*math.sin(math.pi*min(t/2,1)) if t<1 else .025
                    value*=.5*(math.sin(2*math.pi*130.8128*t)+math.sin(2*math.pi*196*t))
                tail=min(1,max(0,(17-t)/3));value*=tail
                left=max(-32767,min(32767,round(value*32767)));right=round(left*(.9 if name=='motif' else 1))
                pcm.extend(struct.pack('<hh',left,right))
            with wave.open(str(path),'wb') as wav:wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm)
    project=cli('audio project','create-project','A dope CLI / Seventeen-second original bed')['id']
    tracks=[];source_hashes={}
    for name in ['pulse','motif','air']:
        path=source_dir/(name+'.wav');source_hashes[name]=sha(path);asset=cli('audio '+name,'import-asset',project,path)['id']
        tracks.append({'name':name,'gain_db':-6 if name!='air' else -9,'clips':[{'name':name+'-bed','asset':asset,'start':0,'frames':sample_count,'fade_in':12000,'fade_out':48000,'fade_shape':'linear'}]})
    revision,d=job('audio-bed',project,'audio.create',{'sample_rate':rate,'frames':sample_count,'tracks':tracks})
    support=json.loads((package/'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text());binary=Path(shutil.which('ffmpeg'));check(sha(binary)==support['engines']['ffmpeg']['sha256'],'independent audio decoder matches exact supporting pin')
    command=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',str(binary),'-nostdin','-v','error','-i',str(d/'exports/document.wav'),'-f','f32le','-acodec','pcm_f32le','pipe:1']
    decoded=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,timeout=60);assert decoded.returncode==0,decoded.stderr[-1000:]
    values=array.array('f');values.frombytes(decoded.stdout);check(len(values)==sample_count*2,'independent decoded stereo sample count equals seventeen seconds');check(all(math.isfinite(v) for v in values),'all decoded audio is finite');peak=max(abs(v) for v in values);rms=math.sqrt(sum(v*v for v in values)/len(values));check(.01<peak<.8 and rms>.003,'audio is non-silent with deliberate headroom')
    check(all(any(sha(p)==digest for p in (d/'assets').iterdir() if p.is_file()) for digest in source_hashes.values()),'all original procedural stem bytes retained')
    check(json.loads(run('verify package after audio',[package/'bin/a-dope-guard','verify'],fresh=True))==verification,'complete seal unchanged after audio')
    save('audio-result.json',{'passed':True,'checks':len(cases),'native_jobs':len(jobs),'project':project,'revision':revision,'checkout':str(d),'frames':sample_count,'rate':rate,'channels':2,'peak':peak,'rms':rms,'source_hashes':source_hashes,'listening_review':False,'owner_approval':False})
    print(json.dumps({'stage':'audio','passed':True,'checks':len(cases),'native_jobs':len(jobs),'peak':peak,'rms':rms}))

if args.stage == 'movie':
    import selectors
    project=cli('film project','create-project','A dope CLI / Three-shot branded film')['id']
    clips=[];input_hashes={}
    for index,label in enumerate(['portal','staircase','orbit']):
        row=next(x for x in jobs if x['label']==label);path=Path(row['checkout'])/'exports/document.mp4';input_hashes[label]=sha(path)
        asset=cli('film '+label,'import-asset',project,path)['id'];clip={'name':label,'asset':asset,'start':index*120,'frames':120}
        if index:clip['transition']=12
        clips.append(clip)
    path=Path(next(x for x in jobs if x['label']=='audio-bed')['checkout'])/'exports/document.wav';input_hashes['audio']=sha(path);asset=cli('film audio','import-asset',project,path)['id']
    captions=['Build the impossible.','Keep every part.','Change the ending.']
    params={'width':1080,'height':1920,'fps':24,'clips':clips,'audio':[{'name':'bed','asset':asset,'start':0,'frames':360,'gain_db':0}],
            'titles':[{'name':'caption-'+str(i),'text':text,'start':i*120,'frames':120,'x':96,'y':1550,'size':72,'color':'#EEEDE3'} for i,text in enumerate(captions)]}
    revision,d=job('original-film',project,'video.create',params)
    movie=d/'exports/document.mp4';ffprobe=Path(shutil.which('ffprobe'));check(sha(ffprobe)==support['engines']['ffprobe']['sha256'],'independent film probe matches exact supporting pin');prefix=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)']
    probe=json.loads(run('film independent probe',[*prefix,ffprobe,'-v','error','-count_frames','-show_streams','-show_format','-of','json',movie]))
    video=[x for x in probe['streams'] if x['codec_type']=='video'];audio=[x for x in probe['streams'] if x['codec_type']=='audio'];check(len(video)==len(audio)==1,'film contains one picture and one audio track');v=video[0];a=audio[0]
    check((v['codec_name'],v['width'],v['height'],v['r_frame_rate'],int(v['nb_read_frames']))==('h264',1080,1920,'24/1',360),'original film independently has 360 full portrait frames');check(abs(float(v['duration'])-15)<.001,'original film picture duration is fifteen seconds');check(a['sample_rate']=='48000' and a['channels']==2 and abs(float(a['duration'])-15)<1/24,'film has expected stereo audio presentation')
    command=[*prefix,binary,'-nostdin','-v','error','-i',movie,'-map','0:v:0','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1'];frames=[];deadline=time.monotonic()+360
    with (out/'original-film-decode.log').open('wb') as error:
        process=subprocess.Popen(list(map(str,command)),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=error);selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ);os.set_blocking(process.stdout.fileno(),False)
        def block(size):
            while time.monotonic()<deadline:
                if selector.select(min(1,max(0,deadline-time.monotonic()))):return os.read(process.stdout.fileno(),min(size,1<<20))
            raise TimeoutError('Full film decoding exceeded six minutes')
        try:
            for index in range(360):
                data=bytearray()
                while len(data)<1080*1920*3:
                    part=block(1080*1920*3-len(data));assert part,'Incomplete film frame '+str(index);data.extend(part)
                frames.append({'frame':index,'rgb_sha256':hashlib.sha256(data).hexdigest()})
                if index in [0,60,119,120,180,239,240,300,359]:Image.frombytes('RGB',(1080,1920),bytes(data)).save(out/f'film-frame-{index:03d}.png')
            check(not block(1),'original film has no extra decoded frames');check(process.wait(timeout=30)==0,'original film decoder exits successfully')
        finally:
            if process.poll() is None:process.kill();process.wait()
            process.stdout.close();selector.close()
    save('original-film-decoded-frames.json',frames)
    decoded=subprocess.run([*prefix,str(binary),'-nostdin','-v','error','-i',str(movie),'-map','0:a:0','-f','f32le','-acodec','pcm_f32le','pipe:1'],stdin=subprocess.DEVNULL,capture_output=True,timeout=60);assert decoded.returncode==0,decoded.stderr[-1000:];values=array.array('f');values.frombytes(decoded.stdout);count=len(values)//2;check(len(values)%2==0 and abs(count-15*48000)<=2048,'full film decoded audio length within AAC padding allowance');check(all(math.isfinite(v) for v in values),'all film audio samples finite');peak=max(abs(v) for v in values);rms=math.sqrt(sum(v*v for v in values)/len(values));check(.01<peak<.8 and rms>.003,'film decoded audio non-silent with headroom')
    check(all(any(sha(p)==digest for p in (d/'assets').iterdir() if p.is_file()) for digest in input_hashes.values()),'film retains all exact shot and audio inputs')
    check(json.loads(run('verify package after movie',[package/'bin/a-dope-guard','verify'],fresh=True))==verification,'complete seal unchanged after film')
    save('movie-result.json',{'passed':True,'checks':len(cases),'native_jobs':len(jobs),'project':project,'revision':revision,'checkout':str(d),'movie':str(movie),'sha256':sha(movie),'frames':360,'width':1080,'height':1920,'fps':24,'seconds':15,'audio_decoded_sample_frames':count,'audio_peak':peak,'audio_rms':rms,'input_hashes':input_hashes,'all_frames_decoded':True,'listening_review':False,'owner_approval':False,'ending_revision_complete':False,'published':False})
    print(json.dumps({'stage':'movie','passed':True,'checks':len(cases),'native_jobs':len(jobs),'frames_decoded':360}))
