"""Qualify Texture authoring, edits, CPU computation and Material handoff.

Run with bundled Python: texture_acceptance.py PACKAGE NEW_OUTPUT [--resume].
Uses only public CLI/MCP jobs in private state. Completed jobs are reused on resume;
nonterminal jobs require explicit reconciliation. No network, editors or services.
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
    if operation.startswith('texture.'):
        check(v['native_state_equal'] and v['native_cold_reopen'] and v['source_bytes_unchanged']
              and v['native_resource_geometry_agreement'] and not v['visual_approval'],
              label + ' preserves native state, resource geometry and source through cold reopen')
    else:
        check(v['passed'], label + ' passes Material native validation')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def report(directory):return json.loads((directory/'exports/inspection.json').read_text())
def members(directory):
    with zipfile.ZipFile(directory/'native/document.tcraft') as z:return {n:z.read(n) for n in z.namelist()}
def model(directory):return json.loads(members(directory)['project.json'])
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def maps(directory):return {p['file']:(directory/'exports/maps'/p['file']).read_bytes() for p in report(directory)['maps']}
def pixels(directory,channel):
    name=next(n for n in maps(directory) if channel in n)
    with Image.open(directory/'exports/maps'/name) as image:
        assert image.size==(128,128);return image.convert('RGB').tobytes()
def constant(directory,channel,value):
    check(pixels(directory,channel)==bytes(value)*128*128,directory.name+' '+channel+' matches independent all-pixel oracle')
def stable(before,after):
    for name in ('native/source.tcraft','recipes/create.json'):
        check((before/name).read_bytes()==(after/name).read_bytes(),after.name+' retains exact '+name)
def precise(before,after,changes):
    expected=copy.deepcopy(model(before))
    for change in changes:
        layer=expected['layers'][str(change['layer'])];prop=change['property']
        target=layer['kind']['Fill']['sources'] if prop=='source' else layer['channels'] if prop=='blend' else layer['kind']['Fill'] if prop=='projection' else layer
        key=change['channel'] if prop in ('source','blend') else prop
        assert target[key]==change['expected'];target[key]=change['value']
    check(canonical(model(after))==canonical(expected),after.name+' complete native document equals independent slot-only prediction')
    left=members(before);right=members(after)
    check({k:v for k,v in left.items() if k!='project.json'}=={k:v for k,v in right.items() if k!='project.json'},after.name+' every unrelated embedded byte stays exact')
    stable(before,after)
def edit(layer,prop,expected,value,channel=None):
    item={'layer':layer,'property':prop,'expected':expected,'value':value}
    if channel:item['channel']=channel
    return item

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
def preview(label,owner,revision,directory):
    r,d=job(label,owner,'texture.render',{'render':camera},revision);v=report(d)['preview']
    check(v['backend']=='CPU' and v['cold_preview_equal'] and len(v['native_command_seconds'])==2,label+' independently repeats encoded CPU preview after cold reopen')
    check(members(d)==members(directory),label+' preserves complete native document and resources')
    with Image.open(d/'exports/preview.png') as im:
        assert im.size==(camera['width'],camera['height']) and len(set(im.convert('RGB').get_flattened_data()))>100
    measurements[label]=v
    return r,d

verification=run('verify payload before',[package/'bin/a-dope-guard','verify'],fresh=True)
check(verification['verified'],'complete sealed package verifies before Texture acceptance');save('verification-before.json',verification)
measurements={};camera={'width':384,'height':384,'samples':8,'bounces':4,'yaw':25,'pitch':15}
creation={'name':'ATELIER / 04 layered finish','mesh':'plane','resolution':128,'layers':[
 {'name':'Base','sources':{'BaseColor':{'Uniform':[0,0,1]},'Roughness':{'Uniform':[.25,.25,.25]}}},
 {'name':'Finish','sources':{'BaseColor':{'Uniform':[1,0,0]}},'channels':{'BaseColor':{'mode':'Normal','opacity':.5}}}]}
owner=call('texture project','create-project',creation['name'])['id']
r0,d0=job('original',owner,'texture.create',creation);constant(d0,'baseColor',(188,0,188));constant(d0,'roughness',(64,64,64))
check(json.loads((d0/'recipes/create.json').read_text())==creation,'creation retains exact reusable recipe')
rough=edit(1,'source',{'Uniform':[.25]*3},{'Uniform':[.75]*3},'Roughness')
r1,d1=job('roughness',owner,'texture.edit',{'edits':[rough]},r0);precise(d0,d1,[rough]);constant(d1,'roughness',(191,191,191))
check(all(data==maps(d1)[name] for name,data in maps(d0).items() if 'roughness' not in name),'roughness-only revision preserves every other encoded map')
refuse('stale-edit',owner,'texture.edit',{'edits':[rough]},r1)
rename=edit(1,'name','Base','Body finish — Ää');r2,d2=job('renamed',owner,'texture.edit',{'edits':[rename]},r1);precise(d1,d2,[rename])
check(maps(d1)==maps(d2),'Unicode layer rename preserves every encoded map')
changes=[edit(2,'source',{'Uniform':[1,0,0]},{'Uniform':[0,1,0]},'BaseColor'),
 edit(2,'projection',model(d2)['layers']['2']['kind']['Fill']['projection'],{'Uv':{'scale':[2.,2.],'rotation':45.,'offset':[0.,0.]}}),
 edit(2,'blend',{'mode':'Normal','opacity':.5},{'mode':'Normal','opacity':1.},'BaseColor')]
refuse('green-finish',owner,'texture.edit',{'edits':changes},r2,'precondition differs')
changes[0]['expected']={'Uniform':[1.,0.,0.]};changes[0]['value']={'Uniform':[0.,1.,0.]}
r3,d3=job('green-finish-typed',owner,'texture.edit',{'edits':changes},r2);precise(d2,d3,changes);constant(d3,'baseColor',(0,255,0))
hide=edit(2,'visible',True,False);r4,d4=job('hidden-finish',owner,'texture.edit',{'edits':[hide]},r3);precise(d3,d4,[hide]);constant(d4,'baseColor',(0,0,255))
refuse('atomic-invalid',owner,'texture.edit',{'edits':[edit(1,'name','Body finish — Ää','Should not publish'),edit(2,'visible',True,False)]},r4)
ri,di=job('inspected',owner,'texture.inspect',{},r4);re,de=job('exported',owner,'texture.export',{},ri)
check(members(di)==members(d4)==members(de) and maps(de)==maps(d4),'inspection and explicit cold export preserve source and exact map bytes')

bake={'texture_sets':[0],'resolution':16,'maps':['normal','ambientOcclusion'],'rays':1,'use_low_as_high':True,'antialiasing':1}
rb,db=job('plane-bake',owner,'texture.bake',{'bake':bake},re);bm=members(db);proof=report(db)['bake'];measurements['plane-bake']=proof
check(proof['backend']=='CPU' and proof['repeated_bake_equal'] and proof['budget']['output_bytes']==4144 and proof['budget']['nominal_ray_work']==512,'plane bake has exact allocation and repeated CPU results')
for name,values in [('normal',(.5,.5,1.)),('ambientOcclusion',(1.,))]:
    payload=bm['baked/0_'+name+'.bin'];actual=struct.unpack('<'+'f'*((len(payload)-24)//4),payload[24:])
    check(all(abs(x-values[i%len(values)])<1e-5 for i,x in enumerate(actual)),name+' baked floats match independent plane geometry oracle')
rpart,dpart=job('partial-bake',owner,'texture.bake',{'bake':{**bake,'maps':['ambientOcclusion']}},rb)
check(members(dpart)['baked/0_normal.bin']==bm['baked/0_normal.bin'],'partial rebake retains exact unrequested normal payload')
refuse('partial-resize',owner,'texture.bake',{'bake':{**bake,'resolution':32,'maps':['ambientOcclusion']}},rpart)
refuse('missing-high-mesh',owner,'texture.bake',{'bake':{**bake,'use_low_as_high':False}},rpart)
refuse('missing-camera',owner,'texture.render',{'render':{**camera,'camera':'Absent'}},rpart)

# Reopen the whole editable project in independent private state and reverse every authored change.
state=out/'portable-state';moved=call('portable import','import-project',de,'Portable layered finish')
restore=[edit(2,'visible',False,True),edit(1,'name','Body finish — Ää','Base'),
 edit(1,'source',{'Uniform':[.75]*3},{'Uniform':[.25]*3},'Roughness')]
restore += [{**c,'expected':c['value'],'value':c['expected']} for c in changes]
rp,dp=job('portable-restored',moved['project']['id'],'texture.edit',{'edits':restore},moved['revision']['id']);precise(de,dp,restore)
check(canonical(model(dp))==canonical(model(d0)) and maps(dp)==maps(d0),'portable reversal restores complete original native model and all exact map bytes')
state=out/'state'
recipient=call('native import project','create-project','Native Texture import')['id'];uploaded=asset('native-texture',recipient,(db/'native/document.tcraft').read_bytes(),'tcraft')
rn,dn=job('native-imported',recipient,'texture.import',{'asset':uploaded})
check(members(dn)==members(db) and (dn/'native/source.tcraft').read_bytes()==(db/'native/document.tcraft').read_bytes(),'native import retains every baked member and exact source bytes')

# Real editable Material graph and version-2 bundle drive the eighth Texture operation.
material_recipe={'recipe':'ceramic_tiles','version':1,'resolution':128,'controls':{'repeat':4,'grout':.08,'bevel':.08,'color_r':.18,'color_g':.32,'color_b':.4,'roughness':.28,'relief':.12}}
material_owner=call('material project','create-project','Reusable ceramic surface')['id']
rm,dm=job('material-source',material_owner,'material.create',material_recipe)
rmb,dmb=job('material-bundle',material_owner,'material.bundle',{'graph':'Surface'},rm)
sphere={**creation,'name':'ATELIER / 04 ceramic surface','mesh':'sphere','layers':[{'name':'Substrate','sources':{'BaseColor':{'Uniform':[.18,.18,.18]},'Roughness':{'Uniform':[.5]*3}}}]}
sphere_owner=call('sphere project','create-project',sphere['name'])['id'];rs,ds=job('sphere',sphere_owner,'texture.create',sphere)
rsp,dsp=preview('sphere-preview',sphere_owner,rs,ds)
bundle_asset=asset('ceramic-material',sphere_owner,(dmb/'exports/material.mcmat').read_bytes(),'mcmat')
params={'asset':bundle_asset,'expected_sha256':digest(dsp/'native/document.tcraft'),'texture_set':0,'height_mode':'unsigned','name':'Ceramic tiles'}
rh,dh=job('ceramic-handoff',sphere_owner,'texture.material',params,rsp);h=report(dh)['material_handoff']
check(h['bounded_source_cook_verified'] and h['manifest_version']==2 and not h['ambient_recook_authorized'] and not h['legacy_v1_reader_used'],'managed handoff verifies fresh native Material cook without ambient or legacy reader')
check((dh/('assets/material-'+h['bundle_sha256']+'.mcmat')).read_bytes()==(dmb/'exports/material.mcmat').read_bytes(),'Texture retains exact project-owned version-2 Material bundle')
check((dm/'native/document.mcraft').read_bytes() in members(dh).values(),'Texture embeds exact editable Material graph source')
for name,data in members(ds).items():
    if name!='project.json':assert members(dh)[name]==data
check(canonical(model(dh)['layers']['1'])==canonical(model(ds)['layers']['1']),'linked handoff preserves every prior layer field')
stable(ds,dh)
rhp,dhp=preview('ceramic-preview',sphere_owner,rh,dh)
repeat={k:v for k,v in params.items() if k!='name'};repeat.update(expected_sha256=digest(dhp/'native/document.tcraft'),layer=h['layer'])
rh2,dh2=job('replace-same-material',sphere_owner,'texture.material',repeat,rhp)
check(members(dh2)==members(dh) and maps(dh2)==maps(dh) and report(dh2)['material_handoff']['new_resources']==[],'same linked material replacement reuses owned resources and preserves exact native document and maps')
refuse('stale-handoff',sphere_owner,'texture.material',{**repeat,'expected_sha256':'0'*64},rh2)
refuse('replace-ordinary-layer',sphere_owner,'texture.material',{**repeat,'expected_sha256':digest(dh2/'native/document.tcraft'),'layer':1},rh2)
state=out/'portable-state';linked=call('portable linked import','import-project',dh2,'Portable ceramic surface')
rl,dl=job('portable-linked-export',linked['project']['id'],'texture.export',{},linked['revision']['id'])
check(members(dl)==members(dh2) and maps(dl)==maps(dh2),'portable linked material exports exact maps without old project asset IDs')
state=out/'state'

# Final inspection images use a finer raster and more samples; keep pilot jobs as evidence.
camera={**camera,'width':768,'height':768,'samples':64}
refuse('sphere-delivery',sphere_owner,'texture.render',{'render':camera},rsp,'project head changed')
fork=call('explicit preview fork','import-project',dsp,'Explicit substrate preview fork')
preview('sphere-delivery-fork',fork['project']['id'],fork['revision']['id'],dsp)
preview('ceramic-delivery',sphere_owner,rh2,dh2)

admission('oversized-preview',owner,'texture.render',{'render':{'width':2048,'height':2048,'samples':256,'bounces':32}},rpart,'budget')
admission('unsupported-command',owner,'texture.export',{'command':'serve'},rpart,'unsupported')
admission('duplicate-edit',owner,'texture.edit',{'edits':[rough,rough]},rpart,'same property twice')

# Fresh protocol clients discover the same operations and retrieve durable public CLI work.
def mcp(label,method,params):
    message=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n'
    p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=message,text=True,capture_output=True,env=env,timeout=30);assert p.returncode==0,(label,p.stderr)
    response=json.loads(p.stdout);assert 'error' not in response,response;save(label+'.json',response);return response['result']
tools=mcp('mcp-discovery','tools/list',{})['tools'];ops=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
check(len(tools)==18 and set('texture.'+x for x in ('create','import','inspect','edit','export','render','bake','material'))<=set(ops),'same eighteen-tool MCP exposes all eight Texture operations')
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
save('context.json',{'creation':creation,'sphere':sphere,'materialRecipe':material_recipe,'camera':camera,'changes':changes,'restore':restore,'measurements':measurements})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'durableJobs':len(jobs),'admissionRefusals':3,
 'successfulJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'groups':groups,'allNativeGroupsAbsent':True,'verification':verification,
 'ownerVisualApproval':False,'generalPhotorealismQualified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'durableJobs':len(jobs)}))
