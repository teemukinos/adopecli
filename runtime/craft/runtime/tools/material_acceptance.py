"""Qualify Material production and precise portable revisions through a sealed CLI.

Run with bundled Python: material_acceptance.py PACKAGE NEW_OUTPUT [--resume].
Only public durable jobs run native engines. Private state, no network or editors.
Completed jobs and their recorded refusal observations are reused on resume.
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
    check(v['passed'] and v['native_model_equal'] and v['native_cold_reopen']
          and v['initial_source_preserved'] and v['source_members_equal'] and v['source_backed']
          and not v['engine_admission_complete'] and not v['visual_approval'],
          label + ' preserves exact source and complete native model through cold reopen')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def oracle(name,control,size):
    heights=[];shapes=[]
    for y in range(size):
        for x in range(size):
            u=(x+.5)/size;v=(y+.5)/size
            if name=='ceramic_tiles':
                a=(u*control['repeat'])%1;b=(v*control['repeat'])%1
                t=max(0,min(1,(min(a,1-a,b,1-b)-control['grout']/2)/control['bevel']))
                shape=t*t*(3-2*t)
            else:shape=(1+math.cos(u*control['repeat']*2*math.pi))/2
            shapes.append(shape);heights.append(shape*control['relief'])
    images={key:bytearray() for key in ('baseColor','roughness','metallic','height','normal','ambientOcclusion')}
    def q(value,srgb=False):
        if srgb:value=12.92*value if value<=.0031308 else 1.055*value**(1/2.4)-.055
        return int(max(0,min(1,value))*255+.5)
    for y in range(size):
        for x in range(size):
            i=y*size+x;shape=shapes[i]
            rgb=[.035+(control['color_'+c]-.035)*shape if name=='ceramic_tiles' else control['color_'+c] for c in 'rgb']
            images['baseColor'].extend([*(q(c,True) for c in rgb),255])
            rough0=.85 if name=='ceramic_tiles' else .5
            gray={'roughness':rough0+(control['roughness']-rough0)*shape,'height':heights[i],
                  'metallic':0 if name=='ceramic_tiles' else 1,'ambientOcclusion':.75+.25*shape}
            for key,value in gray.items():images[key].extend([q(value)]*3+[255])
            dx=(heights[y*size+(x+1)%size]-heights[y*size+(x-1)%size])/2
            dy=(heights[((y+1)%size)*size+x]-heights[((y-1)%size)*size+x])/2
            nx=-dx*size/32;ny=dy*size/32;length=math.sqrt(nx*nx+ny*ny+1)
            images['normal'].extend([q(nx/length*.5+.5),q(ny/length*.5+.5),q(1/length*.5+.5),255])
    return {key:bytes(value) for key,value in images.items()}


def read(directory,name):return json.loads((directory/name).read_text())
def source(directory):return directory/'native/document.mcraft'
def members(directory):
    with zipfile.ZipFile(source(directory)) as z:return {n:z.read(n) for n in z.namelist()}
def graph_xml(directory):return ET.fromstring(members(directory)['package.sbs'])
def xml_equal(a,b):return ET.tostring(a)==ET.tostring(b)
def stable(before,after):
    for name in ('native/original.input','native/origin.json','recipes/origin-material-operation.json','recipes/material-production.json'):
        if (before/name).exists():check((before/name).read_bytes()==(after/name).read_bytes(),after.name+' retains exact '+name)
def unchanged(before,after):
    check(source(before).read_bytes()==source(after).read_bytes(),after.name+' preserves exact current native source');stable(before,after)
def revision(directory,edits=None,operations=None):
    return {'expected_sha256':digest(source(directory)),**({'edits':edits} if edits is not None else {'operations':operations})}
def color_edit(old,new):
    return {'kind':'input.default','package':'package.sbs','graph':'Surface','name':'color_r','expected':{'t':'float','v':old},'value':{'t':'float','v':new}}
def precise_color(before,after,old,new):
    expected=graph_xml(before);port=next(p for p in expected.findall('.//graph/paraminputs/paraminput') if p.find('identifier').get('v')=='color_r')
    value=port.find('defaultValue/constantValueFloat1');assert float(value.get('v'))==old;value.set('v',str(new))
    check(xml_equal(expected,graph_xml(after)),after.name+' complete independent XML prediction changes only requested exposed scalar')
    check({k:v for k,v in members(before).items() if k!='package.sbs'}=={k:v for k,v in members(after).items() if k!='package.sbs'},after.name+' preserves every unrelated archive member')
    stable(before,after)
def map_pixels(directory):
    actual={};report=read(directory,'exports/maps.json')
    for item in report['maps']:
        with Image.open(directory/'exports/maps'/item['file']) as im:
            if im.mode in ('I','I;16','I;16B'):
                actual[item['usage']]=bytes(component for value in im.get_flattened_data() for component in (int(value/257+.5),)*3+(255,))
            else:actual[item['usage']]=im.convert('RGBA').tobytes()
    return actual

def analytic(directory,name,controls,size=256):
    expected=oracle(name,controls,size);actual=map_pixels(directory)
    check(set(actual)==set(expected),directory.name+' contains exactly six expected material channels')
    for channel in expected:
        error=max(abs(a-b) for a,b in zip(actual[channel],expected[channel]));check(len(actual[channel])==size*size*4 and error<=1,directory.name+' '+channel+' matches independent every-pixel expectation within one 8-bit step')
        measurements.setdefault('pixelErrors',{})[directory.name+'/'+channel]=error
    return actual

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
def export(label,owner,revision_id,directory,**options):
    r,d=job(label,owner,'material.export',{'graph':'Surface','format':'png','depth':8,**options},revision_id);unchanged(directory,d)
    evidence=read(d,'exports/maps.json');check(evidence['full_size'] and evidence['finite_outputs'] and evidence['complete_decoding'] and evidence['native_calls']==3,label+' uses bounded full-size cook and completely decoded maps')
    measurements.setdefault('exports',{})[label]={'format':evidence['format'],'depth':evidence['depth'],'bytes':evidence['bytes'],'texels':evidence['texels'],'usage':evidence['usage']}
    return r,d

def preview(label,owner,revision_id,directory):
    r,d=job(label,owner,'material.preview',look,revision_id);unchanged(directory,d);v=read(d,'exports/preview.json')
    check(v['finite_display_samples'] and v['full_size_cook'] and v['geometry']['displaced'] and len(v['selection'])==6,label+' native preview uses six channels and actual displaced geometry')
    with Image.open(d/'exports/preview/preview.png') as im:check(im.size==(768,768) and len(set(im.convert('RGB').get_flattened_data()))>100,label+' contains finite spatially varied 768-pixel inspection image')
    measurements.setdefault('previews',{})[label]=v
    return r,d

def pack(records):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(records.items()):z.writestr(zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0)),data,compress_type=zipfile.ZIP_DEFLATED)
    return b.getvalue()

verification=run('verify payload before',[package/'bin/a-dope-guard','verify'],fresh=True)
check(verification['verified'],'complete sealed package verifies before Material acceptance');save('verification-before.json',verification)
measurements={};controls={'repeat':4,'grout':.125,'bevel':.125,'color_r':.125,'color_g':.25,'color_b':.5,'roughness':.25,'relief':.25}
creation={'recipe':'ceramic_tiles','version':1,'resolution':256,'controls':controls}
look={'graph':'Surface','view':'3d','width':768,'height':768,'scene':'plane','environment':'studio','yaw':25,'pitch':35,'displacement':.08,'supersample':2,'transparency':False}
owner=call('ceramic project','create-project','ATELIER / 05 ceramic finish')['id'];r0,d0=job('ceramic-source',owner,'material.create',creation)
record=read(d0,'recipes/material-production.json');check(record['controls']==controls and record['source_sha256']==digest(d0/'native/original.input'),'creation records exact requested controls and original source hash')
rc,dc=job('ceramic-cook',owner,'material.cook',{'graph':'Surface'},r0);unchanged(d0,dc)
check(read(dc,'exports/cook.json')['finite_outputs'],'bounded native cook reports finite outputs')
r1,d1=export('ceramic-maps',owner,rc,dc);original_pixels=analytic(d1,'ceramic_tiles',controls)
rp,dp=preview('ceramic-preview',owner,r1,d1)
change=color_edit(.125,.75);r2,d2=job('ceramic-recolored',owner,'material.edit',revision(dp,edits=[change]),rp);precise_color(dp,d2,.125,.75)
r3,d3=export('recolored-maps',owner,r2,d2);changed_pixels=analytic(d3,'ceramic_tiles',{**controls,'color_r':.75})
check(changed_pixels['baseColor']!=original_pixels['baseColor'] and all(changed_pixels[k]==original_pixels[k] for k in original_pixels if k!='baseColor'),'color-only revision preserves every other decoded physical map exactly')
rp2,dp2=preview('recolored-preview',owner,r3,d3)
ri,di=job('inspected',owner,'material.inspect',{},rp2);unchanged(dp2,di)
rb,db=job('portable-material',owner,'material.bundle',{'graph':'Surface'},ri);unchanged(di,db)
rb2,db2=job('repeated-material',owner,'material.bundle',{'graph':'Surface'},rb)
check((db/'exports/material.mcmat').read_bytes()==(db2/'exports/material.mcmat').read_bytes(),'separate cold bundle jobs produce byte-identical version-2 portable material')
with zipfile.ZipFile(db/'exports/material.mcmat') as z:bundle_members={n:z.read(n) for n in z.namelist()}
manifest=json.loads(bundle_members['material.json'])
check(bundle_members['source.mcraft']==source(db).read_bytes() and manifest['version']==2 and len(manifest['maps'])==6,'portable material contains exact editable source and six PNG16 maps')
refuse('stale-digest',owner,'material.edit',{'expected_sha256':'0'*64,'edits':[color_edit(.75,.25)]},rb2)
refuse('stale-value',owner,'material.edit',revision(db2,edits=[change]),rb2)
refuse('atomic-invalid',owner,'material.edit',revision(db2,edits=[color_edit(.75,.5),{'kind':'input.default','package':'package.sbs','graph':'Surface','name':'color_g','expected':{'t':'float','v':.9},'value':{'t':'float','v':.5}}]),rb2)
refuse('missing-graph',owner,'material.cook',{'graph':'Absent'},rb2)

state=out/'portable-state';moved=call('portable project import','import-project',db2,'Portable ceramic graph')
rr,dr=job('portable-restored',moved['project']['id'],'material.edit',revision(db2,edits=[color_edit(.75,.125)]),moved['revision']['id']);precise_color(db2,dr,.75,.125)
rrm,drm=export('restored-maps',moved['project']['id'],rr,dr);analytic(drm,'ceramic_tiles',controls)
check(source(drm).read_bytes()==source(d0).read_bytes() and map_pixels(drm)==original_pixels,'portable reversal restores exact original archive and all six map pixels')
rrp,drp=preview('restored-preview',moved['project']['id'],rrm,drm)
check((drp/'exports/preview/preview.png').read_bytes()==(dp/'exports/preview/preview.png').read_bytes(),'independent portable cold preview reproduces original encoded PNG exactly')
state=out/'state'

# Native archive, bare SBS and version-2 material imports retain their own exact original bytes.
for label,data,fmt in [('archive',source(db).read_bytes(),'source'),('bare',members(db)['package.sbs'],'source'),('material',(db/'exports/material.mcmat').read_bytes(),'mcmat')]:
    recipient=call(label+' import project','create-project','Imported '+label)['id'];a=asset(label,recipient,data,'input')
    rn,dn=job(label+'-imported',recipient,'material.import',{'asset':a,'format':fmt})
    expected_members={'source.sbs':data} if label=='bare' else members(db)
    check((dn/'native/original.input').read_bytes()==data and members(dn)==expected_members,label+' import preserves exact original bytes and every expected editable member')
    if fmt=='mcmat':check(read(dn,'project.json')['validation']['bundle_import_verified'],'portable material import verifies a fresh source cook')

# A valid PNG16 with substituted pixels must not pass bundle verification.
forged=dict(bundle_members);rough=next(x['file'] for x in manifest['maps'] if x['usage']=='roughness')
buffer=io.BytesIO();Image.new('I;16',(256,256),0).save(buffer,format='PNG');forged[rough]=buffer.getvalue()
bad_owner=call('forged project','create-project','Rejected stale material maps')['id'];forged_asset=asset('forged-map',bad_owner,pack(forged),'mcmat')
refuse('forged-map-import',bad_owner,'material.import',{'asset':forged_asset,'format':'mcmat'},None,'bundle maps disagree with a fresh bounded source cook')

# Structural graph metadata edits use hash-bound source indices and independent complete XML predictions.
struct=call('structural project import','import-project',d0,'Structured ceramic graph');so=struct['project']['id'];sr=struct['revision']['id'];sd=d0
for action,text in [('insert','Surface study — Ää'),('replace','Revised surface study'),('remove',None)]:
    index=read(sd,'native/source-index.json')['packages']['package.sbs'];graph=next(x for x in index if x['tag']=='graph');attrs=next(x for x in index if x['tag']=='attributes' and x['parent']==graph['element'])
    target=attrs if action=='insert' else next(x for x in index if x['tag']=='author' and x['parent']==attrs['element'])
    operation={'kind':action,'package':'package.sbs','element':target['element'],'expected_sha256':target['sha256']}
    if action!='remove':operation['value']={'tag':'author','attributes':{'v':text},'children':[]}
    if action=='insert':operation['before']=None
    before=sd;expected=graph_xml(before);parent=expected.find('.//graph/attributes')
    if action=='insert':ET.SubElement(parent,'author',{'v':text})
    elif action=='replace':parent.find('author').set('v',text)
    else:parent.remove(parent.find('author'))
    sr,sd=job('structure-'+action,so,'material.edit',revision(before,operations=[operation]),sr)
    check(xml_equal(expected,graph_xml(sd)),'structural '+action+' changes exactly the independently predicted metadata element');stable(d0,sd)
check(source(sd).read_bytes()==source(d0).read_bytes(),'structural insert replacement and removal restore byte-identical source')

# All seven supported encodings and both PNG depths use the public bounded exporter.
formats=[('png',16),('jpg',8),('tga',8),('bmp',8),('webp',8),('exr',32),('hdr',32)]
codec=call('codec project import','import-project',d0,'Material encoding suite');cr=codec['revision']['id'];cd=d0
for fmt,depth in formats:
    cr,cd=export('format-'+fmt+str(depth),codec['project']['id'],cr,cd,format=fmt,depth=depth,discard_alpha=fmt in ('jpg','exr','hdr'))
    check(len(read(cd,'exports/maps.json')['maps'])==6,fmt+' preserves all six material channel identities')
    if fmt in ('png','tga','bmp','webp'):
        observed=map_pixels(cd);check(all(len(observed[k])==len(original_pixels[k]) and max(abs(a-b) for a,b in zip(observed[k],original_pixels[k]))<=1 for k in original_pixels),fmt+' complete decoded samples match PNG8 reference within one quantization step')

metal_controls={'repeat':8,'color_r':.25,'color_g':.5,'color_b':.75,'roughness':.25,'relief':.25}
metal_recipe={'recipe':'ribbed_metal','version':1,'resolution':256,'controls':metal_controls}
metal_owner=call('metal project','create-project','ATELIER / 05 ribbed metal')['id'];rm,dm=job('metal-source',metal_owner,'material.create',metal_recipe)
rmaps,dmaps=export('metal-maps',metal_owner,rm,dm);analytic(dmaps,'ribbed_metal',metal_controls)
rmp,dmp=preview('metal-preview',metal_owner,rmaps,dmaps)

# Final camera leaves margin around the full plane; pilot images remain evidence.
pilot_look=look;look={**look,'distance':4.2}
preview('ceramic-delivery',so,sr,sd)
preview('recolored-delivery',owner,rb2,db2)
preview('metal-delivery',metal_owner,rmp,dmp)

admission('unsupported-tiff',owner,'material.export',{'graph':'Surface','format':'tiff','depth':16},rb2,'unsupported')
admission('undersampled-recipe',owner,'material.create',{'recipe':'ceramic_tiles','version':1,'resolution':32,'controls':{'repeat':64}},None,'four pixels')
admission('cross-project-bundle',owner,'material.import',{'asset':forged_asset,'format':'mcmat'},None,'asset')
admission('arbitrary-command',owner,'material.inspect',{'command':'serve'},rb2,'no additional')

def mcp(label,method,params):
    message=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n'
    p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=message,text=True,capture_output=True,env=env,timeout=30);assert p.returncode==0,(label,p.stderr)
    response=json.loads(p.stdout);assert 'error' not in response,response;save(label+'.json',response);return response['result']
tools=mcp('mcp-discovery','tools/list',{})['tools'];ops=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
check(len(tools)==18 and set('material.'+x for x in ('create','import','inspect','edit','cook','export','preview','bundle'))<=set(ops),'same eighteen-tool MCP exposes all eight Material operations')
req={'name':'dope_get_job','arguments':{'job':jobs[0]['id']}};first=mcp('mcp-first','tools/call',req);second=mcp('mcp-reconnected','tools/call',req)
check(first==second and json.loads(first['content'][0]['text'])['state']=='succeeded','reconnecting MCP clients retrieve the same durable result')
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
save('context.json',{'creation':creation,'metalCreation':metal_recipe,'look':look,'pilotLook':pilot_look,'measurements':measurements})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'durableJobs':len(jobs),'admissionRefusals':4,
 'successfulJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'groups':groups,'allNativeGroupsAbsent':True,'verification':verification,
 'ownerVisualApproval':False,'generalPhotorealismQualified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'durableJobs':len(jobs)}))
