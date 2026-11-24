"""General typed 2D construction lowered to editable Blender objects and shaders."""
import json
import math
from pathlib import Path
import re
import shutil
from .construction_schema import require, NAME
from .construction_support import DATA, binary, run, sha, write

KINDS=('group','rectangle','ellipse','path','text','noise','gradient','glow','image')
COMMON={'id','kind','x','y','z','parent','rotation','scale','opacity','keys','color','mask'}
EXTRA={'group':set(),'rectangle':{'width','height'},'ellipse':{'width','height','stroke'},
       'path':{'points','closed','stroke'},'text':{'text','size','font'},'noise':{'width','height','color2','seed','noise_scale'},
       'gradient':{'width','height','color2'},'glow':{'radius','falloff'},'image':{'width','height','asset','image_extension'}}

def number(v,lo,hi):return type(v) in (int,float) and math.isfinite(v) and lo<=v<=hi

def validate(p):
    require(isinstance(p,dict) and {'width','height','fps','frames','objects'}<=set(p)<= {'width','height','fps','frames','objects','samples','preview_frame'},'Invalid Blender document fields')
    for k in ('width','height'):require(type(p[k]) is int and 16<=p[k]<=4096 and p[k]%2==0,'Even canvas dimensions 16–4096 required')
    require(p['fps'] in (24,25,30,50,60) and type(p['fps']) is int and type(p['frames']) is int and 1<=p['frames']<=36000,'Invalid frame rate/duration')
    require(type(p.get('samples',32)) is int and 1<=p.get('samples',32)<=128,'Invalid sample budget')
    require(type(p.get('preview_frame',0)) is int and 0<=p.get('preview_frame',0)<p['frames'],'Invalid look frame')
    objects=p['objects'];require(isinstance(objects,list) and 1<=len(objects)<=256,'Provide 1–256 editable objects')
    names=set();parents={}
    for o in objects:
        require(isinstance(o,dict) and o.get('kind') in KINDS and isinstance(o.get('id'),str) and NAME.fullmatch(o['id']) and o['id'] not in names,'Invalid object kind/ID')
        require(set(o)<=COMMON|EXTRA[o['kind']],'Unsupported Blender object property')
        names.add(o['id']);parents[o['id']]=o.get('parent')
        for k in ('x','y','z','rotation'):require(number(o.get(k,0),-100000,100000),'Invalid transform')
        require(number(o.get('scale',1),.001,100) and number(o.get('opacity',1),0,1),'Invalid scale/opacity')
        for k in ('color','color2'):
            if k in o:require(isinstance(o[k],str) and re.fullmatch('#[0-9A-Fa-f]{6}',o[k]),'Invalid color')
        for k in ('width','height','radius','size','stroke','noise_scale'):
            if k in o:require(number(o[k],.001,8192),'Invalid dimension')
        if o['kind'] in ('rectangle','ellipse','noise','gradient','image'):require({'width','height'}<=o.keys(),'Object dimensions required')
        if o['kind']=='glow':require(number(o.get('radius'),1,4096) and number(o.get('falloff',-18),-1000,-.001),'Invalid glow')
        if o['kind']=='noise':require(number(o.get('seed',1.29),-1000,1000),'Invalid noise seed')
        if o['kind']=='image':
            require(isinstance(o.get('asset'),str) and re.fullmatch('[a-f0-9]{32}',o['asset']),'Image requires imported asset ID')
            # Missing fields retain the historical sampling behavior. Correcting
            # an existing project requires an explicit, recorded revision.
            require(o.get('image_extension','repeat') in ('repeat','clip'),'Image extension must be repeat or clip')
        if o['kind']=='text':require(isinstance(o.get('text'),str) and 1<=len(o['text'])<=4000 and '\0' not in o['text'] and o.get('font','Archivo')=='Archivo' and number(o.get('size'),1,512),'Text requires Archivo and explicit size')
        if o['kind']=='path':
            pts=o.get('points');require(isinstance(pts,list) and 2<=len(pts)<=512 and all(isinstance(v,list) and len(v)==2 and all(number(x,-8192,8192) for x in v) for v in pts),'Invalid editable Bezier path')
            require(type(o.get('closed',False)) is bool,'closed must be boolean')
        if 'mask' in o:require(isinstance(o['mask'],list) and len(o['mask'])==4 and all(number(v,0,1) for v in o['mask']) and o['mask'][0]<o['mask'][2] and o['mask'][1]<o['mask'][3],'Mask must be normalized rectangle bounds')
        keys=o.get('keys',{});require(isinstance(keys,dict) and set(keys)<={'opacity','scale','x','y','rotation','seed'},'Unsupported keyed property')
        require(o['kind']!='group' or (not set(keys)&{'opacity','seed'} and o.get('opacity',1)==1 and 'mask' not in o),'Groups support transform keys; opacity/masks belong to painted children')
        for k,track in keys.items():
            require(isinstance(track,list) and 1<=len(track)<=200,'Invalid keyframes')
            previous=-1
            for key in track:
                require(isinstance(key,list) and len(key)==3 and type(key[0]) is int and previous<key[0]<36000 and key[2] in ('LINEAR','BEZIER','CONSTANT'),'Invalid frame/interpolation')
                lo,hi=(0,1) if k=='opacity' else (.001,100) if k=='scale' else (-100000,100000)
                require(number(key[1],lo,hi),'Invalid key value');previous=key[0]
            require(k!='seed' or o['kind']=='noise','Seed keys require noise')
    for name in parents:
        seen={name};parent=parents[name]
        while parent is not None:
            require(parent in names and parent not in seen,'Missing/cyclic parent');seen.add(parent);parent=parents[parent]

def assets(p):return {o['asset']:'assets/'+o['asset'] for o in p['objects'] if o['kind']=='image'}

def execute(root,p,mode='create',previous=None,output=None):
    validate(p);root=Path(root);(root/'native').mkdir(exist_ok=True);(root/'exports').mkdir(exist_ok=True)
    fonts=root/'fonts';fonts.mkdir(exist_ok=True)
    for name in ('archivo-variable.ttf','archivo-OFL.txt'):shutil.copyfile(DATA/'fonts'/name,fonts/name)
    if mode=='edit':
        for stale in ('film.mp4','probe.json','still.png','preview.png'):(root/'exports'/stale).unlink(missing_ok=True)
    write(root/'document.json',p)
    request={'root':str(root.resolve()),'mode':mode,'previous':previous,'output':output or {'format':'png','frame':p.get('preview_frame',0)}}
    write(root/'request-construction.json',request)
    script=Path(__file__).with_name('construction_blender_engine.py')
    def invoke(label,req):
        write(root/'request-construction.json',req)
        # A retained inspection cannot prove this invocation succeeded. Blender
        # otherwise exits zero after a Python exception unless configured here.
        inspection=root/'native/inspection.json'
        inspection.unlink(missing_ok=True)
        result=run(root,[binary('blender'),'-b','--factory-startup','--disable-autoexec','-t','8','--python-exit-code','1','-P',script,'--',root/'request-construction.json'],label)
        require(inspection.is_file(),'Native invocation did not produce a fresh inspection')
        return result
    trace=[invoke(mode,request)]
    trace.append(invoke('cold-reopen',{**request,'mode':'inspect'}))
    inventory=json.loads((root/'native/inspection.json').read_text());require(inventory['ids']==sorted(o['id'] for o in p['objects']),'Native object inventory differs')
    require(inventory.get('native_geometry_and_keys_verified'),'Native geometry/keys were not verified')
    require(inventory.get('native_dependency_bytes_verified'),'Native dependency bytes were not verified')
    require(inventory.get('native_static_opacity_verified'),'Native static opacity was not verified')
    require(inventory.get('native_image_sampling_verified'),'Native image sampling was not verified')
    require(inventory['frames']==p['frames'],'Native timeline length differs')
    for o in p['objects']:
        row=inventory['objects'][o['id']]
        require(row['construction']==o,'Native source parameters differ')
        if o['kind']=='text':require(row['text']==o['text'] and row['font_packed'],'Native editable text/font differs')
    if mode=='render' and output and output['format']=='mp4':
        trace.append(run(root,[binary('ffmpeg'),'-nostdin','-v','error','-y','-framerate',str(p['fps']),'-start_number','0','-i',root/'frames/%06d.png','-c:v','libx264','-threads','4','-pix_fmt','yuv420p','-an','-movflags','+faststart',root/'exports/film.mp4'],'encode'))
        probe=__import__('subprocess').run([binary('ffprobe'),'-v','error','-count_frames','-show_streams','-show_format','-of','json',root/'exports/film.mp4'],capture_output=True,check=True,text=True)
        data=json.loads(probe.stdout);streams=data['streams'];require(len(streams)==1 and streams[0]['codec_name']=='h264' and int(streams[0]['nb_read_frames'])==p['frames'] and streams[0]['pix_fmt']=='yuv420p' and streams[0]['r_frame_rate']==str(p['fps'])+'/1','Actual video differs from construction')
        require(abs(float(data['format']['duration'])-p['frames']/p['fps'])<.05,'Video duration differs');write(root/'exports/probe.json',data)
        shutil.rmtree(root/'frames')
    write(root/'trace.json',trace)
    return {'native_cold_reopen':True,'native_image_sampling_verified':True,'native_dependency_bytes_verified':True,'native_static_opacity_verified':True,'native_source_sha256':sha(root/'native/scene.blend'),'creative_status':'review_required'}
