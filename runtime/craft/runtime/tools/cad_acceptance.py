"""Qualify all nine CAD operations through a sealed package's public CLI.

Run with bundled Python: cad_acceptance.py PACKAGE NEW_OUTPUT --predecessor OBSERVED_ARCHIVE [--resume].
Original drawing recipes and refusal inputs are generated locally. No network, editor windows or service installation. Completed jobs are
reused on resume; admitted nonterminal work is never replayed automatically.
"""
import argparse
import io
import zipfile
import copy
import fcntl
import sys
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import math
from collections import Counter

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--resume', action='store_true')
parser.add_argument('--predecessor', type=Path, required=True)
args = parser.parse_args()
package = args.package.resolve(strict=True)
sys.path.insert(0, str(package / 'lib/dobe/runtime'))
from studio_runtime import cad_admission, cad_parametric, cad_project
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
    check(v['native_cold_reopen'] and v['native_model_equal'] and v['initial_source_preserved']
          and v['source_backed'] and v['profile_admission_complete']
          and not v['general_admission_complete'] and not v['visual_approval'] and not v['general_manufacturing_qualified'],
          label + ' preserves source and complete native model through cold history replay')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def model(directory):return json.loads((directory/'native/document.json').read_text())
def portable(directory):return directory/'native/project.dobecad'
def request(directory,**params):return {'expected_sha256':digest(portable(directory)),**params}
def validation(directory):return json.loads((directory/'project.json').read_text())['validation']
def stable_source(before,after):
    for name in ('native/original.json','native/baseline.json','recipes/origin-cad-operation.json','recipes/cad-production.json'):
        if (before/name).exists():assert (after/name).read_bytes()==(before/name).read_bytes(),name

def sketch(document,width,height):
    corners=[(0.,0.,0.),(width,0.,0.),(width,height,0.),(0.,height,0.)];maximum=0.
    for i,entity in enumerate(document['model'][:4]):
        assert entity['kind']['type']=='line'
        for endpoint,target in [('a',corners[i]),('b',corners[(i+1)%4])]:
            actual=entity['kind'][endpoint];assert set(actual)=={'x','y','z'}
            for axis,want in zip('xyz',target):maximum=max(maximum,abs(actual[axis]-want))
    assert maximum<=1e-6,maximum
    assert document['model'][0]['kind']['a']=={'x':0.,'y':0.,'z':0.}
    return maximum

def mesh(document):return next(e for e in document['model'] if e['kind']['type']=='polyfaceMesh')
def parameter_edits(document,width,height):
    return [{'kind':'parameter.expression','name':name,'expected':next(p['expr'] for p in document['parametric']['parameters'] if p['name']==name),'value':str(amount)}
            for name,amount in [('width',width),('height',height)]]

def check_parameter_change(before,after,edits):
    expected=copy.deepcopy(before)
    for edit in edits:next(p for p in expected['parametric']['parameters'] if p['name']==edit['name'])['expr']=edit['value']
    assert after==expected

def check_solve(before,after,width,height):
    error=sketch(after,width,height);expected=copy.deepcopy(before)
    for i in range(4):
        expected['model'][i]['kind']['a']=after['model'][i]['kind']['a']
        expected['model'][i]['kind']['b']=after['model'][i]['kind']['b']
    assert after==expected,'native solve changes unrelated state'
    return error

def check_solid(before,after,width,height,depth):
    expected=copy.deepcopy(before);selected=mesh(expected);prior=mesh(before)
    vertices=[{'x':float(x),'y':float(y),'z':float(z)} for x,y,z in [(0,0,0),(width,0,0),(width,height,0),(0,height,0),(0,0,depth),(width,0,depth),(width,height,depth),(0,height,depth)]]
    selected['kind']['vertices']=vertices
    next(p for p in expected['parametric']['parameters'] if p['name']=='depth')['expr']=str(depth)
    assert after==expected and mesh(after)['handle']==prior['handle'],'solid revision changes unrelated state or handle'

def measured_obj(directory,width,height,depth):
    data=(directory/'exports/panel.obj').read_bytes();lines=data.decode('ascii').splitlines()
    assert lines[0]=='# Dobe panel mesh; coordinates in millimetres'
    vertices=[];faces=[]
    for line in lines[2:]:
        parts=line.split()
        if parts[0]=='v':assert len(parts)==4;vertices.append(tuple(map(float,parts[1:])))
        elif parts[0]=='f':assert len(parts)==5;faces.append(tuple(int(p)-1 for p in parts[1:]))
        else:raise AssertionError('unsupported OBJ record')
    assert len(vertices)==8 and len(faces)==6 and len(set(vertices))==8
    assert set(vertices)=={(float(x),float(y),float(z)) for x in (0,width) for y in (0,height) for z in (0,depth)}
    edges=Counter();area=volume=0.
    def sub(a,b):return tuple(x-y for x,y in zip(a,b))
    def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    for face in faces:
        assert len(set(face))==4 and all(0<=i<8 for i in face)
        for i in range(4):edges[(face[i],face[(i+1)%4])]+=1
        a,b,c,d=[vertices[i] for i in face]
        normal=cross(sub(b,a),sub(c,a));center=tuple(sum(vertices[i][j] for i in face)/4 for j in range(3))
        assert dot(normal,sub(center,(width/2,height/2,depth/2)))>0,'inward face'
        for x,y,z in [(a,b,c),(a,c,d)]:
            area+=math.sqrt(dot(cross(sub(y,x),sub(z,x)),cross(sub(y,x),sub(z,x))))/2
            volume+=dot(x,cross(y,z))/6
    assert len(edges)==24 and all(count==1 and edges[(b,a)]==1 for (a,b),count in edges.items())
    assert 8-12+6==2 and math.isclose(volume,width*height*depth,rel_tol=1e-12,abs_tol=1e-9)
    assert math.isclose(area,2*(width*height+width*depth+height*depth),rel_tol=1e-12,abs_tol=1e-9)
    native=mesh(model(directory));assert vertices==[tuple(v[k] for k in 'xyz') for v in native['kind']['vertices']]
    assert faces==[tuple(i-1 for i in f) for f in native['kind']['faces']]
    check(True,directory.name+' independently verifies actual OBJ vertices, outward closed topology, units, volume and surface area')
    return {'dimensions_mm':[width,height,depth],'volume_mm3':volume,'surface_area_mm2':area,'vertices':8,'edges':12,'faces':6,'sourceMeshHandle':native['handle'],'sha256':digest(directory/'exports/panel.obj')}

def export(label,owner,revision,directory,width,height,depth):
    r,d=job(label,owner,'cad.export',request(directory,format='obj'),revision)
    check(portable(d).read_bytes()==portable(directory).read_bytes() and validation(d)['geometry_delivery_verified'],label+' preserves exact portable source and verifies geometry delivery')
    measurements[label]=measured_obj(d,width,height,depth)
    return r,d

def refuse(label,owner,operation,params,revision,contains=None):
    head=call(label+' before','project',owner)['head'];result=job(label,owner,operation,params,revision,success=False)
    check(call(label+' after','project',owner,fresh=True)['head']==head,label+' leaves project head unchanged')
    if contains:check(contains in result['error']['message'],label+' reports expected refusal')

def admission(label,owner,operation,params,revision,contains):
    path=out/(label+'-request.json');immutable(path,(json.dumps(params,sort_keys=True)+'\n').encode())
    command=[cli,'--state',state,'submit',owner,operation,'--parameters',path,'--key',label]
    if revision:command+=['--source',revision]
    run(label+' refusal',command,expected=1)
    check(contains in next(c for c in logs if c['label']==label+' refusal')['stderr'],label+' is refused before durable admission')

def asset(label,owner,data,extension):
    path=out/'sources'/(label+'.'+extension);immutable(path,data)
    return call(label+' asset','import-asset',owner,path)['id']

verification=run('verify payload before',[package/'bin/a-dope-guard','verify'],fresh=True)
check(verification['verified'],'complete sealed package verifies before CAD acceptance');save('verification-before.json',verification)
predecessor=args.predecessor.resolve(strict=True);prior_bytes=predecessor.read_bytes()
check(digest(predecessor)=='bb7675ba05e2c3c4bdc824c83110d250ab67745a57d546a58143e8123f1912d0','predecessor bytes match retained actual build4 observation binding')
measurements={};errors={};creation={'recipe':'rectangular_panel_solid','version':1,'width':120,'height':80,'depth':12}
owner=call('panel project','create-project','ATELIER / 03 material panel')['id']
r0,d0=job('original',owner,'cad.create',creation);original=model(d0);errors['original']=sketch(original,120,80)
check(validation(d0)['native_solid_regeneration_verified'],'creation replays native solid generation from retained sketch')
r0obj,d0obj=export('original-obj',owner,r0,d0,120,80,12)
edits=parameter_edits(original,150,90)
r1,d1=job('parameter-revision',owner,'cad.edit',request(d0obj,edits=edits),r0obj)
check_parameter_change(original,model(d1),edits);stable_source(d0,d1)
check(not validation(d1)['native_constraint_solve_verified'] and not validation(d1)['native_solid_regeneration_verified'],'parameter edits preserve exact geometry and invalidate solve and extrusion claims')
refuse('unsolved-export',owner,'cad.export',request(d1,format='obj'),r1,'solved sketch')
r2,d2=job('solved',owner,'cad.solve',request(d1),r1);errors['revised']=check_solve(model(d1),model(d2),150,90)
check(mesh(model(d2))==mesh(original) and validation(d2)['native_constraint_solve_verified'] and not validation(d2)['native_solid_regeneration_verified'],'native solving moves only constrained sketch and keeps old mesh pending regeneration')
refuse('stale-mesh-export',owner,'cad.export',request(d2,format='obj'),r2)
r3,d3=job('regenerated',owner,'cad.solid',request(d2,depth=20),r2);check_solid(model(d2),model(d3),150,90,20);stable_source(d0,d3)
check(validation(d3)['native_solid_regeneration_verified'],'native extrusion changes exact dimensions while preserving mesh handle and unrelated state')
r3obj,d3obj=export('revised-obj',owner,r3,d3,150,90,20)
rrepeat,drepeat=export('repeated-obj',owner,r3obj,d3obj,150,90,20)
check((drepeat/'exports/panel.obj').read_bytes()==(d3obj/'exports/panel.obj').read_bytes(),'cold native OBJ exports are byte-identical')
ri,di=job('inspected',owner,'cad.inspect',{},rrepeat);rb,db=job('bundled',owner,'cad.bundle',{},ri)
check(portable(db).read_bytes()==portable(d3).read_bytes()==(db/'exports/drawing.dobecad').read_bytes(),'inspect and bundle retain exact editable archive and history')

state=out/'portable-state';moved=call('portable import','import-project',db,'Portable material panel')
check(not moved['revision']['validation'].get('native_model_equal',False),'whole-project import claims integrity only before native reopening')
rp,dp=job('portable-thinner',moved['project']['id'],'cad.solid',request(db,depth=8),moved['revision']['id']);check_solid(model(db),model(dp),150,90,8);stable_source(d0,dp)
rpobj,dpobj=export('portable-obj',moved['project']['id'],rp,dp,150,90,8)
restore=parameter_edits(model(dp),120,80)
rr,dr=job('restore-parameters',moved['project']['id'],'cad.edit',request(dpobj,edits=restore),rpobj)
rrs,drs=job('restore-solve',moved['project']['id'],'cad.solve',request(dr),rr);errors['restored']=check_solve(model(dr),model(drs),120,80)
rrsolid,drsolid=job('restore-solid',moved['project']['id'],'cad.solid',request(drs,depth=12),rrs)
rrout,drout=export('restored-obj',moved['project']['id'],rrsolid,drsolid,120,80,12)
check((drout/'exports/panel.obj').read_bytes()==(d0obj/'exports/panel.obj').read_bytes(),'portable restoration returns byte-identical original mesh delivery')
state=out/'state'
for kind,data in [('dobecad',portable(db).read_bytes()),('json',(d0/'native/original.json').read_bytes())]:
    recipient=call(kind+' project','create-project','CAD '+kind+' import')['id'];uploaded=asset(kind,recipient,data,kind)
    r,d=job(kind+'-import',recipient,'cad.import',{'asset':uploaded,'format':kind})
    check(portable(d).read_bytes()==data if kind=='dobecad' else (d/'native/original.json').read_bytes()==data,kind+' import retains exact original bytes')
    check(model(d)==(model(db) if kind=='dobecad' else json.loads(data)),kind+' native import preserves the complete model')

migration_owner=call('migration project','create-project','Observed predecessor migration')['id'];oldasset=asset('predecessor',migration_owner,prior_bytes,'dobecad')
refuse('old-pin-import',migration_owner,'cad.import',{'asset':oldasset,'format':'dobecad'},None)
rm,dm=job('migrated',migration_owner,'cad.migrate',{'asset':oldasset,'expected_sha256':digest(predecessor)})
prior=cad_project.inspect_bytes(prior_bytes);transition=cad_project.inspect_bytes(portable(dm).read_bytes())
check((dm/'native/predecessor.dobecad').read_bytes()==prior_bytes and model(dm)==prior['current']['document'] and transition['manifest']['history']==prior['manifest']['history'] and validation(dm)['engine_migration_verified'],'migration preserves exact observed predecessor, complete model and history prefix')
rm2,dm2=job('migrated-solid',migration_owner,'cad.solid',request(dm,depth=12),rm)
rmobj,dmobj=export('migrated-obj',migration_owner,rm2,dm2,120,80,12)
check((dmobj/'exports/panel.obj').read_bytes()==(d0obj/'exports/panel.obj').read_bytes(),'migrated predecessor supports new native solid production with equal OBJ')
refuse('repeat-migration',migration_owner,'cad.migrate',request(dm2),rmobj)

# Unconstrained authored geometry exercises all four primitive edit kinds.
primitive=cad_admission.base();common=copy.deepcopy(original['model'][0]['common'])
primitive['model']=[{'handle':256+i,'common':copy.deepcopy(common),'kind':kind} for i,kind in enumerate([
 {'type':'line','a':{'x':-5.,'y':2.,'z':0.},'b':{'x':125.,'y':2.,'z':0.}},
 {'type':'circle','center':{'x':40.,'y':20.,'z':0.},'radius':15.},
 {'type':'text','insert':{'x':0.,'y':60.,'z':0.},'alignPt':None,'height':5.,'value':'Panel Ø 30 — retained text','rotation':0.,'widthFactor':1.,'oblique':0.,'style':'Standard','halign':'left','valign':'baseline'}])]
primitive['handseed']=259;plain=call('primitive project','create-project','Editable drafting geometry')['id']
rplain,dplain=job('primitives',plain,'cad.create',{'document':primitive})
primitive_edits=[{'kind':'geometry.set','handle':257,'expected':primitive['model'][1]['kind'],'set':{'radius':20}},
 {'kind':'text.replace','handle':258,'expected':primitive['model'][2]['kind']['value'],'value':'Panel Ø 40 — revised text'},
 {'kind':'entity.properties','handle':256,'expected':{'layer':'0','visible':True,'ltscale':1.,'thickness':0.},'set':{'layer':'Defpoints','visible':False,'ltscale':2,'thickness':3}}]
rplain2,dplain2=job('primitive-revision',plain,'cad.edit',request(dplain,edits=primitive_edits),rplain)
predicted=copy.deepcopy(primitive);predicted['model'][0]['common'].update(layer='Defpoints',visible=False,ltscale=2.,thickness=3.);predicted['model'][1]['kind']['radius']=20.;predicted['model'][2]['kind']['value']='Panel Ø 40 — revised text'
check(model(dplain2)==predicted,'typed geometry, Unicode text and entity-property revisions preserve complete unrelated drawing state')
refuse('nonparametric-solve',plain,'cad.solve',request(dplain2),rplain2,'constrained panel')
refuse('stale-hash',owner,'cad.solid',{'expected_sha256':'0'*64,'depth':20},rb,'portable hash is stale')
refuse('stale-parameter',owner,'cad.edit',request(db,edits=edits),rb)
bad_edits=[{'kind':'parameter.expression','name':'width','expected':'150','value':'160'}, {'kind':'parameter.expression','name':'height','expected':'wrong','value':'100'}]
refuse('atomic-invalid',owner,'cad.edit',request(db,edits=bad_edits),rb)
admission('invalid-depth',owner,'cad.solid',request(db,depth=0),rb,'between 0.1')
admission('unsupported-dxf',owner,'cad.import',{'asset':oldasset,'format':'dxf'},None,'json or dobecad')
admission('cross-project',owner,'cad.import',{'asset':oldasset,'format':'dobecad'},None,'asset')

# Small and large supported sizes exercise geometry limits without arbitrary units.
for label,width,height,depth in [('small',.1,.2,.3),('large',10000,9000,8000)]:
    other=call(label+' project','create-project',label+' panel')['id']
    r,d=job(label,other,'cad.create',{'recipe':'rectangular_panel_solid','version':1,'width':width,'height':height,'depth':depth})
    export(label+'-obj',other,r,d,width,height,depth)

def mcp(label,method,params):
    message=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n'
    p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=message,text=True,capture_output=True,env=env,timeout=30);assert p.returncode==0,(label,p.stderr)
    response=json.loads(p.stdout);assert 'error' not in response,response;save(label+'.json',response);return response['result']
tools=mcp('mcp-discovery','tools/list',{})['tools'];ops=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
check(len(tools)==18 and set('cad.'+x for x in ('create','import','inspect','edit','solve','solid','export','bundle','migrate'))<=set(ops),'same eighteen-tool MCP exposes all nine CAD operations')
req={'name':'dope_get_job','arguments':{'job':jobs[0]['id']}};first=mcp('mcp-first','tools/call',req);second=mcp('mcp-reconnected','tools/call',req)
check(first==second and json.loads(first['content'][0]['text'])['state']=='succeeded','reconnecting MCP clients retrieve the same durable CLI result')
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
check(predecessor.read_bytes()==prior_bytes,'observed predecessor bytes remain unchanged')
check(run('verify payload after',[package/'bin/a-dope-guard','verify'],fresh=True)==verification,'complete sealed payload remains unchanged')
save('context.json',{'creation':creation,'edits':edits,'restore':restore,'primitiveEdits':primitive_edits,'measurements':measurements,'endpointErrors_mm':errors})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'durableJobs':len(jobs),'admissionRefusals':3,
 'successfulJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'groups':groups,'allNativeGroupsAbsent':True,'verification':verification,
 'ownerVisualApproval':False,'generalManufacturingQualified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'durableJobs':len(jobs)}))
