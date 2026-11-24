"""Qualify editable Animate movies through a sealed package's public CLI.

Run with bundled Python: animate_acceptance.py PACKAGE NEW_OUTPUT [--resume].
Native work uses durable jobs in private state, with recorded resumable requests.
No editor, network, installed service or external generative model is used.
"""
import argparse
import zipfile
import copy
import fcntl
import sys
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
package = args.package.resolve(strict=True)
sys.path.insert(0, str(package / 'lib/dobe/runtime'))
from PIL import Image
import struct
import math
import base64
import wave
import io
import xml.etree.ElementTree as ET
out = args.output.absolute()
out.mkdir(parents=True, exist_ok=args.resume, mode=0o700)
lock = (out / 'fixture.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
for folder in ('home', 'sources'):
    (out / folder).mkdir(exist_ok=args.resume, mode=0o700)
cli = package / 'bin/a-dope-cli'
state = out / 'state'
env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
logs = json.loads((out / 'commands.json').read_text()) if args.resume else []
jobs = json.loads((out / 'jobs.json').read_text()) if args.resume and (out / 'jobs.json').exists() else []
cases = []


def save(name, value):
    (out / name).write_text(json.dumps(value, indent=2) + '\n')


def check(value, label):
    assert value, label
    cases.append(label)
    save('cases.json', cases)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def immutable(path, data):
    if path.exists():
        assert path.read_bytes() == data, 'fixture input changed: ' + str(path)
    else:
        path.write_bytes(data)


def run(label, arguments, expected=0, fresh=False):
    arguments = list(map(str, arguments))
    files = {p: digest(p) for p in arguments if Path(p).is_file()}
    prior = next((r for r in logs if r['label'] == label), None)
    if prior and not fresh:
        assert (prior['args'], prior['files'], prior['exit']) == (arguments, files, expected), label
        return json.loads(prior['stdout']) if prior['stdout'].strip() else None
    start = time.monotonic()
    process = subprocess.run(arguments, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    logs.append({'label': label, 'args': arguments, 'files': files, 'exit': process.returncode,
                 'seconds': time.monotonic() - start, 'stdout': process.stdout, 'stderr': process.stderr})
    save('commands.json', logs)
    assert process.returncode == expected, (label, process.returncode, process.stderr)
    return json.loads(process.stdout) if process.stdout.strip() else None


def call(label, *arguments, fresh=False):
    return run(label, [cli, '--state', state, *arguments], fresh=fresh)


def verify_checkout(directory):
    receipt = json.loads((directory / 'project.json').read_text())
    for item in receipt['files']:
        p = directory / item['path']
        assert p.stat().st_size == item['bytes'] and digest(p) == item['sha256'], item['path']
    return receipt


def job(label, project, operation, parameters, source=None, success=True):
    request = out / (label + '-request.json')
    immutable(request, (json.dumps(parameters, sort_keys=True) + '\n').encode())
    old = next((j for j in jobs if j['label'] == label), None)
    if old:
        assert (old['project'], old['operation'], old['parameters'], old['source']) == (project, operation, parameters, source), label
    arguments = ['submit', project, operation, '--parameters', request, '--key', label]
    if source:
        arguments += ['--source', source]
    submitted = call(label + ' submit', *arguments)
    if not old:
        old = {'label': label, 'project': project, 'operation': operation, 'parameters': parameters,
               'source': source, 'stateDirectory': str(state), 'id': submitted['id']}
        jobs.append(old)
        save('jobs.json', jobs)
    if 'result' not in old:
        observed = call(label + ' admitted state', 'job', submitted['id'], fresh=True)
        if observed['state'] == 'queued':
            call(label + ' worker', 'worker', '--once')
        elif observed['state'] not in ('succeeded', 'failed'):
            raise RuntimeError('Reconcile admitted job before resuming: ' + json.dumps(observed))
        old['result'] = call(label + ' result', 'job', submitted['id'], fresh=True)
        save('jobs.json', jobs)
    result = old['result']
    assert result['state'] == ('succeeded' if success else 'failed'), result
    if not success:
        check(result.get('result_revision') is None, label + ' publishes no revision')
        return result
    destination = out / label
    call(label + ' checkout', 'checkout', result['result_revision'], destination)
    receipt = verify_checkout(destination)
    v = receipt['validation']
    check(v['passed'] and v['native_state_equal'] and v['native_cold_reopen']
          and v['source_bytes_unchanged'] and v['selected_preview_pixels_equal']
          and not v['interactive_playback_verified'] and not v['visual_approval'],
          label + ' preserves complete native state and selected pixels after cold reopen')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def refuse(label,owner,operation,params,revision,contains=None):
    completed=any(j['label']==label and 'result' in j for j in jobs)
    head=call(label+' before','project',owner)['head'];result=job(label,owner,operation,params,revision,success=False)
    check(call(label+' after','project',owner,fresh=not completed)['head']==head,label+' leaves project head unchanged at refusal')
    if contains:check(contains in result['error']['message'],label+' reports expected refusal')
def admission(label,owner,operation,params,revision,contains):
    path=out/(label+'-request.json');immutable(path,(json.dumps(params,sort_keys=True)+'\n').encode())
    command=[cli,'--state',state,'submit',owner,operation,'--parameters',path,'--key',label]
    if revision:command+=['--source',revision]
    run(label+' refusal',command,expected=1)
    check(contains in next(c for c in logs if c['label']==label+' refusal')['stderr'],label+' refuses before durable admission')
def asset(label,owner,data,extension):
    path=out/'sources'/(label+'.'+extension);immutable(path,data)
    return call(label+' asset','import-asset',owner,path)['id']
def read(directory,name):return json.loads((directory/name).read_text())
def native(directory):return directory/'native/document.anicraft'
def model(directory):return read(directory,'native/document.anicraft')
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def expanded(value):
    result=copy.deepcopy(value);paths=result.pop('paths')
    timelines=[s['timeline'] for s in result['document']['scenes']]+[s['timeline'] for s in result['document']['library']]
    for timeline in timelines:
        for layer in timeline['layers']:
            for key in layer['keyframes']:
                for item in key.get('elements',[]):
                    kind=item['kind']
                    if isinstance(kind,dict):
                        for tag,field in [('Shape','path'),('Text','outline')]:
                            if tag in kind and type(kind[tag][field]) is int:kind[tag][field]=paths[kind[tag][field]]
    return result

def target(value,selector):
    timeline=value['document']['scenes'][selector['scene']]['timeline']
    layer=next(x for x in timeline['layers'] if x['id']==selector['layer'])
    key=next(x for x in layer['keyframes'] if x['start']==selector['frame'])
    return next(x for x in key['elements'] if x['id']==selector['element'])
def select(directory,name,frame=0,scene=0):
    return next(x['selector'] for x in read(directory,'native/objects.json') if x['type']=='element' and x['name']==name and x['selector'].get('scene')==scene and x['selector']['frame']==frame)
def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
def stable(before,after):
    for name in ['native/source.anicraft','recipes/create.json']:
        if (before/name).exists():check((before/name).read_bytes()==(after/name).read_bytes(),after.name+' retains exact '+name)
def unchanged(before,after):
    check(canonical(expanded(model(before)))==canonical(expanded(model(after))),after.name+' preserves complete expanded native document');stable(before,after)
def precise(before,after,edits):
    expected=expanded(model(before));actual=expanded(model(after))
    for edit in edits:
        item=target(expected,edit['selector']);observed=target(actual,edit['selector'])
        if edit['action']=='translate':
            item['transform']['m'][4]=f32(item['transform']['m'][4]+edit['dx']);item['transform']['m'][5]=f32(item['transform']['m'][5]+edit['dy'])
        elif edit['action']=='fill':
            color=edit['color'];item['kind']['Shape']['fill']=None if color is None else {'Solid':{**{k:f32(int(color[i:i+2],16)/255) for k,i in zip('rgb',(1,3,5))},'a':1.}}
            if color is not None:
                wanted=item['kind']['Shape']['fill']['Solid'];saved=observed['kind']['Shape']['fill']['Solid']
                check(set(saved)==set(wanted) and all(type(saved[k]) is float and struct.pack('<f',saved[k])==struct.pack('<f',wanted[k]) for k in wanted),after.name+' requested paint preserves exact native f32 values')
                measurements.setdefault('paintSerialization',[]).append({'revision':after.name,'expected':wanted,'serialized':saved})
                item['kind']['Shape']['fill']=copy.deepcopy(observed['kind']['Shape']['fill'])
        else:
            assert item['kind']['Text']['text']==edit['expected'];item['kind']['Text']['text']=edit['text']
            for key in ['outline','box_width','box_height']:item['kind']['Text'][key]=observed['kind']['Text'][key]
    check(canonical(expected)==canonical(actual),after.name+' complete independent state prediction permits only requested fields and native-derived text layout')
    stable(before,after)

def export(label,owner,revision,directory,output):
    r,d=job(label,owner,'animate.export',{'output':output,'frames':frames},revision);unchanged(directory,d)
    report=read(d,'exports/inspection.json')['export'];check(report['native_state_equal'] and report['cold_export_equal'],label+' export reproduces encoded bytes and format evidence after cold save')
    measurements.setdefault('exports',{})[label]=report
    return r,d

def frame(directory,index):
    with Image.open(directory/'exports/render'/('frame_'+str(index+1).zfill(5)+'.png')) as im:return im.convert('RGBA').copy()
def color_box(image,kind):
    rgb=image.convert('RGB');pixels=rgb.get_flattened_data()
    mask=Image.frombytes('L',image.size,bytes(255 if ((r>180 and g<150 and b<150) if kind=='warm' else (r<70 and g>80 and b>100)) else 0 for r,g,b in pixels))
    return mask.getbbox()
def sequence_oracle(directory,revised=False):
    expected_names={'frame_'+str(i+1).zfill(5)+'.png' for i in range(48)}
    check({p.name for p in (directory/'exports/render').iterdir()}==expected_names,directory.name+' exact 48-frame sequence inventory')
    boxes=[];untouched=[]
    for i in range(48):
        im=frame(directory,i);assert im.size==(640,360)
        if i<24:
            box=color_box(im,'cool' if revised and i==0 else 'warm')
            if revised and i not in (0,23):continue # Fill interpolation is not inferred from the endpoint colors.
            x=(72 if revised else 48)+(496-(72 if revised else 48))*i/23
            y=(160 if revised else 176)+(16*i/23 if revised else 0)
            want=(x,y,x+64,y+64)
            assert box and all(abs(a-b)<=1.5 for a,b in zip(box,want)),(i,box,want)
            boxes.append({'frame':i,'observed':box,'expected':want})
        else:
            box=color_box(im,'cool');assert box and all(abs(a-b)<=1.5 for a,b in zip(box,(288,176,352,240))),(i,box)
            untouched.append(hashlib.sha256(im.tobytes()).hexdigest())
    check(len(set(untouched))==1,directory.name+' second scene is pixel-stable over every frame')
    check(True,directory.name+' independently verifies linear motion or selected revised poses and scene boundaries')
    measurements.setdefault('geometry',{})[directory.name]=boxes

def wav_samples(directory,bits,expected):
    data=(directory/'exports/render/soundtrack.wav').read_bytes();rate=48000;count=96000;block=2*(bits//8)
    header=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',36+count*block,b'WAVE',b'fmt ',16,3 if bits==32 else 1,2,rate,rate*block,block,bits,b'data',count*block)
    assert data[:44]==header and len(data)==44+count*block
    body=data[44:];maximum=0.
    for i in range(count):
        want=expected[i] if i<len(expected) else 0.
        for channel in range(2):
            at=(i*2+channel)*(bits//8);chunk=body[at:at+bits//8]
            actual=struct.unpack('<f',chunk)[0] if bits==32 else int.from_bytes(chunk,'little',signed=True)/(2**(bits-1))
            maximum=max(maximum,abs(actual-want))
    check(maximum<=(1e-6 if bits==32 else 2/(2**(bits-1))),directory.name+' independently verifies every stereo sample, tone then silence, and exact two-second endpoint')
    measurements.setdefault('pcm',{})[directory.name]={'bits':bits,'rate':rate,'frames':count,'maximumAbsoluteError':maximum}

verification=run('verify payload before',[package/'bin/a-dope-guard','verify'],fresh=True)
check(verification['verified'],'complete sealed package verifies before Animate acceptance');save('verification-before.json',verification)
frames=[0,6,12,18,23,24,47];measurements={}
def rectangle(x,y=176,fill='#e5533d'):return {'name':'Mark','type':'rectangle','x':x,'y':y,'width':64,'height':64,'fill':fill}
def title(text):return {'name':'Title','type':'text','x':48,'y':56,'text':text,'font':'Inter','size':36,'color':'#23302e'}
creation={'stage':{'width':640,'height':360,'fps':24,'background':'#f3f1eb'},'scenes':[
 {'name':'Motion','layers':[{'name':'Title','keyframes':[{'start':0,'duration':24,'objects':[title('A dope CLI')]}]},
 {'name':'Mark','keyframes':[{'start':0,'duration':23,'tween':'classic','easing':'Linear','objects':[rectangle(48)]},{'start':23,'duration':1,'objects':[rectangle(496)]}]}]},
 {'name':'Hold','layers':[{'name':'Title','keyframes':[{'start':0,'duration':24,'objects':[title('Editable motion.')]}]},
 {'name':'Mark','keyframes':[{'start':0,'duration':24,'objects':[{'name':'Circle','type':'ellipse','x':288,'y':176,'width':64,'height':64,'fill':'#167d8d'}]}]}]}], 'frames':frames}
owner=call('animation project','create-project','ATELIER / 06 editable motion')['id'];r0,d0=job('original',owner,'animate.create',creation)
rseq,dseq=export('original-sequence',owner,r0,d0,{'format':'png_sequence'});sequence_oracle(dseq)
shape=select(d0,'Mark');text=select(d0,'Title');end=select(d0,'Mark',23)
check(shape['element']==end['element'] and shape!=end,'native identity continues across distinct stored occurrences')
edits=[{'selector':shape,'action':'translate','dx':24,'dy':-16},{'selector':shape,'action':'fill','color':'#167d8d'},
 {'selector':text,'action':'replace_text','expected':'A dope CLI','text':'Made to move.'}]
r1,d1=job('revised',owner,'animate.edit',{'edits':edits,'frames':frames},rseq);precise(dseq,d1,edits)
check(target(expanded(model(d1)),end)==target(expanded(model(d0)),end),'editing first occurrence preserves final stored pose with the same element ID')
check(read(d1,'exports/inspection.json')['revision']['previews']['untargeted_preview_frames']==[24,47],'both selected frames in untargeted scene retain exact preview pixels')
rrev,drev=export('revised-sequence',owner,r1,d1,{'format':'png_sequence'});sequence_oracle(drev,revised=True)
check(all(frame(drev,i).tobytes()==frame(dseq,i).tobytes() for i in range(24,48)),'all twenty-four untargeted scene frames remain pixel-identical')
refuse('stale-text',owner,'animate.edit',{'edits':[edits[2]],'frames':frames},rrev,'expected source text')
refuse('interior-key',owner,'animate.edit',{'edits':[{'selector':{**shape,'frame':6},'action':'translate','dx':1,'dy':0}]},rrev,'exact keyframe')
refuse('atomic-invalid',owner,'animate.edit',{'edits':[{'selector':shape,'action':'translate','dx':4,'dy':0},edits[2]],'frames':frames},rrev)
ri,di=job('inspected',owner,'animate.inspect',{'frames':frames},rrev);unchanged(drev,di)
state=out/'portable-state';moved=call('portable import','import-project',di,'Portable motion')
restore=[{'selector':shape,'action':'translate','dx':-24,'dy':16},{'selector':shape,'action':'fill','color':'#e5533d'},
 {'selector':text,'action':'replace_text','expected':'Made to move.','text':'A dope CLI'}]
rr,dr=job('restored',moved['project']['id'],'animate.edit',{'edits':restore,'frames':frames},moved['revision']['id']);precise(di,dr,restore)
rrs,drs=export('restored-sequence',moved['project']['id'],rr,dr,{'format':'png_sequence'});sequence_oracle(drs)
check(canonical(expanded(model(drs)))==canonical(expanded(model(d0))) and all(frame(drs,i).tobytes()==frame(dseq,i).tobytes() for i in range(48)),'portable reversal restores complete native meaning and all forty-eight rendered frames')
state=out/'state'

# Import an exact original one-second PCM source in a separate, explicit native document.
values=[int(math.sin(2*math.pi*440*i/48000)*8192) for i in range(48000)]
audio=io.BytesIO()
with wave.open(audio,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(struct.pack('<'+'h'*len(values),*values))
sound_source=model(d0);doc=sound_source['document'];sound_id=doc['next_id'];layer_id=sound_id+1;doc['next_id']=layer_id+1
sound={'id':sound_id,'name':'Original 440 Hz qualification cue','format':'wav','rate':48000,'channels':1,'frames':48000,'data':base64.b64encode(audio.getvalue()).decode()}
doc['sounds']=[sound];doc['scenes'][0]['timeline']['layers'].append({'id':layer_id,'name':'Cue','keyframes':[{'start':0,'duration':24,'elements':[],'sound':{'sound':sound_id,'sync':'stream','repeat':1,'loop':False,'effect':'none'}}]})
data=(json.dumps(sound_source,separators=(',',':'))+'\n').encode();sound_owner=call('sound project','create-project','Native movie with owned cue')['id'];a=asset('owned-sound-movie',sound_owner,data,'anicraft')
rn,dn=job('native-imported',sound_owner,'animate.import',{'asset':a,'frames':frames})
check((dn/'native/source.anicraft').read_bytes()==data and model(dn)['document']['sounds'][0]['data']==sound['data'],'native import preserves exact original source and embedded sound bytes')
current,current_directory=rn,dn
for bits in [16,24,32]:
    current,current_directory=export('wav-'+str(bits),sound_owner,current,current_directory,{'format':'wav','rate':48000,'bits':bits});wav_samples(current_directory,bits,[x/32768 for x in values])
for label,output in [('gif',{'format':'gif','loop':True}),('sprites',{'format':'sprite_sheet','scale':.5,'columns':6,'padding':2,'background':True}),
 ('svg',{'format':'svg','frame':12}),('lottie',{'format':'lottie','background':True}),('html',{'format':'html','title':'Motion <study> & source','sound':True,'fit':True}),
 ('movie',{'format':'mp4','audio':True,'matte':'#f3f1eb'})]:
    current,current_directory=export(label,sound_owner,current,current_directory,output)
    if label=='gif':
        with Image.open(current_directory/'exports/render/movie.gif') as im:
            assert im.n_frames==48 and im.size==(640,360) and im.info['loop']==0;durations=[]
            for i in range(48):im.seek(i);durations.append(im.info['duration'])
        check(durations==[10*(math.floor((i+1)*100/24+.5)-math.floor(i*100/24+.5)) for i in range(48)] and sum(durations)==2000,'GIF independently preserves 48 frames and exact accumulated two-second timing with explicit centisecond quantization')
    if label=='sprites':
        atlas=read(current_directory,'exports/render/atlas.json');assert len(atlas['frames'])==48 and atlas['meta']['frameRate']==24
        with Image.open(current_directory/'exports/render/atlas.png') as im:
            assert im.size==(1930,1454)
            for i in range(48):
                cell=atlas['frames']['atlas_'+str(i+1).zfill(4)]['frame'];assert cell=={'x':i%6*322,'y':i//6*182,'w':320,'h':180}
        check(True,'sprite atlas independently verifies every cell, padding, frame identity and native rate')
    if label=='lottie':
        lottie=read(current_directory,'exports/render/animation.json');check((lottie['w'],lottie['h'],lottie['fr'],lottie['ip'],lottie['op'])==(640,360,24,0,48),'Lottie stage and held-frame range match the two-scene movie')
    if label=='html':
        page=(current_directory/'exports/render/animation.html').read_text();check('Motion &lt;study&gt; &amp; source' in page and '<script src=' not in page,'HTML escapes its title and retains a self-contained player; browser fidelity remains unclaimed')

# A separate portable source supports independent atlas pixels without rewinding another project.
half=call('atlas reference project','import-project',dn,'Independent half-size frame reference')
rhalf,dhalf=export('half-sequence',half['project']['id'],half['revision']['id'],dn,{'format':'png_sequence','scale':.5})
with Image.open(out/'sprites/exports/render/atlas.png') as im:
    atlas_pixels=im.convert('RGBA')
    for i in range(48):
        x=i%6*322;y=i//6*182
        check(atlas_pixels.crop((x,y,x+320,y+180)).tobytes()==frame(dhalf,i).tobytes(),'sprite cell '+str(i)+' equals independently exported half-size frame pixels')
    alpha=atlas_pixels.getchannel('A')
    assert all(alpha.crop((col*322+320,0,col*322+322,1454)).getbbox() is None for col in range(5))
    assert all(alpha.crop((0,row*182+180,1930,row*182+182)).getbbox() is None for row in range(7))
check(True,'every sprite padding pixel remains transparent')
export('revised-movie',owner,ri,di,{'format':'mp4','audio':False,'matte':'#f3f1eb'})

# Portable movie re-encoding uses independent state and the same embedded source.
state=out/'portable-state';movie_project=call('portable movie import','import-project',current_directory,'Portable sound movie')
rpm,dpm=export('portable-movie',movie_project['project']['id'],movie_project['revision']['id'],current_directory,{'format':'mp4','audio':True,'matte':'#f3f1eb'})
check((dpm/'exports/render/movie.mp4').read_bytes()==(current_directory/'exports/render/movie.mp4').read_bytes(),'portable native movie re-encoding reproduces exact MP4 bytes')
state=out/'state'
refuse('out-of-range',sound_owner,'animate.export',{'output':{'format':'png_sequence','to':48}},current,'frame')
admission('duplicate-frames',owner,'animate.inspect',{'frames':[0,0]},ri,'distinct')
admission('arbitrary-command',owner,'animate.inspect',{'command':'serve'},ri,'unsupported')
admission('unsupported-codec',owner,'animate.export',{'output':{'format':'mp4','codec':'other'}},ri,'unknown')
admission('cross-project-source',owner,'animate.import',{'asset':a},None,'asset')

# Native playback remains separate from protocol discovery and static evidence.
def mcp(label,method,params):
    message=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n'
    p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=message,text=True,capture_output=True,env=env,timeout=30);assert p.returncode==0,(label,p.stderr)
    response=json.loads(p.stdout);assert 'error' not in response,response;save(label+'.json',response);return response['result']
tools=mcp('mcp-discovery','tools/list',{})['tools'];ops=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
check(len(tools)==18 and set('animate.'+x for x in ('create','import','inspect','edit','export'))<=set(ops),'same eighteen-tool MCP exposes all five Animate operations')
req={'name':'dope_get_job','arguments':{'job':jobs[0]['id']}};first=mcp('mcp-first','tools/call',req);second=mcp('mcp-reconnected','tools/call',req)
check(first==second and json.loads(first['content'][0]['text'])['state']=='succeeded','reconnecting MCP clients retrieve same durable result')
groups=[]
for directory in (out/'state',out/'portable-state'):
    with sqlite3.connect('file:'+str(directory/'studio.sqlite3')+'?mode=ro',uri=True) as db:
        check(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],directory.name+' database integrity passes')
        groups += [r[0] for r in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
for group in groups:
    try:os.killpg(group,0)
    except ProcessLookupError:pass
    else:raise AssertionError('native execution group remains: '+str(group))
check(len(groups)==len(jobs),'all native groups are accounted for and absent')
for record in jobs:
    if 'checkout' in record:verify_checkout(Path(record['checkout']))
check(True,'all successful native checkout receipts remain exact')
check(run('verify payload after',[package/'bin/a-dope-guard','verify'],fresh=True)==verification,'complete sealed payload remains unchanged')
save('context.json',{'creation':creation,'edits':edits,'restore':restore,'frames':frames,'measurements':measurements,'audio':{'frequency':440,'inputRate':48000,'inputFrames':48000,'inputChannels':1,'inputBits':16,'sha256':hashlib.sha256(audio.getvalue()).hexdigest()}})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'durableJobs':len(jobs),'admissionRefusals':4,
 'successfulJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'groups':groups,'allNativeGroupsAbsent':True,'verification':verification,
 'ownerVisualApproval':False,'browserPlayerFidelityVerified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'durableJobs':len(jobs)}))
