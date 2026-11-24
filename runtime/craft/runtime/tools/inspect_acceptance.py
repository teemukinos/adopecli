"""Qualify static artifacts and editable findings through a sealed package's public CLI.

Run with bundled Python: inspect_acceptance.py PACKAGE NEW_OUTPUT [--resume].
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
import struct
import math
import base64
import io
from html.parser import HTMLParser
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
    check(v['passed'] and v['native_cold_reopen'] and v['initial_source_preserved']
          and v['native_report_replayed'] and v['annotation_history_replayed']
          and v['input_executed'] is False and v['external_references_resolved'] is False
          and v['carries_target_content'] and not v['visual_approval'],
          label + ' replays complete native findings and typed annotations without executing input')
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
def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(data):return hashlib.sha256(data).hexdigest()
def portable(directory):return (directory/'native/project.dobeinspect').read_bytes()
def report(directory):return read(directory,'native/report.json')
def members(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None and len(set(z.namelist()))==len(z.namelist())
        return {n:z.read(n) for n in z.namelist()}
def packed(entries):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as z:
        for n,data in sorted(entries.items()):
            i=zipfile.ZipInfo(n,(1980,1,1,0,0,0));i.create_system=3;i.external_attr=0o100600<<16;z.writestr(i,data)
    return stream.getvalue()
def bound_note(edit,native_report,native_hash):
    return {**{k:v for k,v in edit.items() if k!='kind'},'input_sha256':native_report['input_sha256'],
            'report_sha256':native_hash,'evidence_id':native_report['evidence']['id']}
def inspect_oracle(directory,original,expected_notes=None):
    entries=members(portable(directory));manifest=json.loads(entries['project.json']);native_report=json.loads(entries['report.json'])
    assert entries['source.bin']==original and (directory/'native/source.bin').read_bytes()==original
    assert entries['report.json']==(directory/'native/report.json').read_bytes()
    assert native_report['input_sha256']==sha(original) and native_report['input_bytes']==len(original)
    assert native_report['input_executed'] is False and native_report['external_references_resolved'] is False
    assert native_report['evidence']['carries_target_content'] is True
    assert manifest['original']==sha(original) and manifest['report']==sha(entries['report.json'])
    assert set(entries)==set(manifest['members'])|{'project.json'}
    for n,item in manifest['members'].items():assert item=={'sha256':sha(entries[n]),'bytes':len(entries[n])}
    notes={};before=b'[]'
    for index,step in enumerate(manifest['history']):
        assert step['before']==sha(before) and step['state']=='notes-'+str(index+1).zfill(4)+'.json'
        for edit in step['edits']:
            if edit['kind']=='remove':del notes[edit['id']]
            else:
                current=native_report
                for token in edit['pointer'].split('/')[1:]:
                    token=token.replace('~1','/').replace('~0','~');current=current[int(token)] if isinstance(current,list) else current[token]
                notes[edit['id']]=bound_note(edit,native_report,sha(entries['report.json']))
        before=encoded([notes[k] for k in sorted(notes)])
        assert entries[step['state']]==before and step['after']==sha(before)
    assert entries['annotations.json']==before and manifest['current']==sha(before)
    if expected_notes is not None:assert json.loads(before)==expected_notes
    check(True,directory.name+' independently replays every annotation state and binds all immutable bytes')
    return entries,manifest

def preserve_native(before,after,original,notes=None):
    check((before/'native/report.json').read_bytes()==(after/'native/report.json').read_bytes(),after.name+' preserves complete native report bytes')
    check((before/'recipes/origin-inspect-operation.json').read_bytes()==(after/'recipes/origin-inspect-operation.json').read_bytes(),after.name+' preserves exact origin recipe')
    return inspect_oracle(after,original,notes)
def follow(directory,**extra):
    return {'permission':'owned-or-authorized','input_sha256':report(directory)['input_sha256'],'expected_sha256':sha(portable(directory)),**extra}
def export(label,owner,revision,directory,kind):
    r,d=job(label,owner,'inspect.export',follow(directory,format=kind),revision)
    check(portable(d)==portable(directory),label+' retains byte-identical portable project')
    return r,d

class StaticHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.text=[];self.policy=None
    def handle_starttag(self,tag,attrs):
        assert tag not in ('script','img','iframe','object','embed','link','base','form','audio','video')
        assert all(not k.lower().startswith('on') and k not in ('src','href','srcdoc','action') for k,v in attrs)
        values=dict(attrs)
        if tag=='meta' and values.get('http-equiv')=='Content-Security-Policy':self.policy=values['content']
    def handle_data(self,data):self.text.append(data)

verification=run('verify payload before',[package/'bin/a-dope-guard','verify'],fresh=True)
check(verification['verified'],'complete sealed package verifies before Inspect acceptance');save('verification-before.json',verification)
original=b"import value from 'https://invalid.example/never-fetch.js'; export const answer=42; console.log('</pre><script>forged()</script>');\n"
owner=call('inspection project','create-project','Static artifact / editable findings')['id'];uploaded=asset('owned-javascript',owner,original,'js')
consent={'permission':'owned-or-authorized','input_sha256':sha(original)}
r0,d0=job('original',owner,'inspect.analyze',{**consent,'asset':uploaded,'format':'javascript'});inspect_oracle(d0,original,[])
native=report(d0);facts=native['evidence']['result']['facts']
check(facts['mode']=='parsed' and facts['imports'][0]['specifier']=='https://invalid.example/never-fetch.js' and 'answer' in facts['exports']['esm'],'authored JavaScript import and export facts match without resolution')
edit={'kind':'upsert','id':'ExportAnswer','pointer':'/evidence/result/facts/exports/esm/0','title':'Public export','text':'Preserve answer. <img src=x onerror=forged()>','status':'open','severity':'note'}
note=bound_note(edit,native,sha((d0/'native/report.json').read_bytes()))
r1,d1=job('annotated',owner,'inspect.annotate',follow(d0,edits=[edit]),r0);preserve_native(d0,d1,original,[note])
second={**edit,'id':'ImportedName','pointer':'/evidence/result/facts/imports/0/specifier','title':'External name only','text':'Recorded as text; never fetched.','severity':'info'}
notes=sorted([note,bound_note(second,native,sha((d0/'native/report.json').read_bytes()))],key=lambda x:x['id'])
r2,d2=job('second-note',owner,'inspect.annotate',follow(d1,edits=[second]),r1);preserve_native(d1,d2,original,notes)
updated={**edit,'text':'Keep answer in the next revision. <script>untrusted()</script>','status':'resolved'}
expected=sorted([bound_note(updated,native,sha((d0/'native/report.json').read_bytes())),notes[1]],key=lambda x:x['id'])
r3,d3=job('resolved-note',owner,'inspect.annotate',follow(d2,edits=[updated]),r2);before,old_manifest=inspect_oracle(d2,original);after,new_manifest=preserve_native(d2,d3,original,expected)
check(all(after[n]==v for n,v in before.items() if n not in ('project.json','annotations.json')),'note revision preserves every previous source, report and history member')
ri,di=job('inspected',owner,'inspect.inspect',follow(d3),r3);preserve_native(d3,di,original,expected);check(portable(di)==portable(d3),'fresh inspection preserves exact native portable bytes')
rj,dj=export('json',owner,ri,di,'json');delivered=read(dj,'exports/findings.json')
check(delivered['native_report']==native and delivered['analyst_annotations']==expected and delivered['input_sha256']==sha(original),'JSON keeps complete native findings separate from exact analyst notes')
rh,dh=export('html',owner,rj,dj,'html');markup=(dh/'exports/findings.html').read_text();page=StaticHTML();page.feed(markup)
check(page.policy=="default-src 'none'; style-src 'unsafe-inline'" and '<script>' not in markup and '<img ' not in markup,'HTML has restrictive policy and no active target markup or external resources')
check(updated['text'] in ''.join(page.text) and second['text'] in ''.join(page.text),'HTML text parser recovers exact escaped analyst notes')
rb,db=job('bundle',owner,'inspect.bundle',follow(dh),rh);bundle=(db/'exports/findings.dobeinspect').read_bytes()
check(bundle==portable(d3),'standalone bundle is byte-identical with complete history')
other=call('portable native project','create-project','Transferred findings')['id'];a=asset('portable-findings',other,bundle,'dobeinspect')
rp,dp=job('native-imported',other,'inspect.import',{**follow(db),'asset':a});inspect_oracle(dp,original,expected);check(portable(dp)==bundle,'native archive import preserves exact complete portable bytes')
state=out/'portable-state';moved=call('whole-project import','import-project',db,'Independent findings state')
rr,dr=job('removed-note',moved['project']['id'],'inspect.annotate',follow(db,edits=[{'kind':'remove','id':'ExportAnswer'}]),moved['revision']['id']);preserve_native(db,dr,original,[expected[1]])
re, de=job('empty-notes',moved['project']['id'],'inspect.annotate',follow(dr,edits=[{'kind':'remove','id':'ImportedName'}]),rr);entries,manifest=preserve_native(dr,de,original,[])
check(len(manifest['history'])==5 and all(entries[n]==v for n,v in after.items() if n not in ('project.json','annotations.json')),'portable removal restores empty notes while preserving all original report and annotation history')
export('portable-json',moved['project']['id'],re,de,'json');state=out/'state'
refuse('wrong-consent',owner,'inspect.inspect',{**follow(db),'input_sha256':'0'*64},rb,'consent does not match')
refuse('stale-hash',owner,'inspect.annotate',{**follow(db,edits=[updated]),'expected_sha256':'0'*64},rb,'hash is stale')
refuse('missing-finding',owner,'inspect.annotate',follow(db,edits=[{**edit,'pointer':'/evidence/result/missing'}]),rb,'pointer missing')
refuse('missing-removal',owner,'inspect.annotate',follow(db,edits=[{'kind':'remove','id':'Absent'}]),rb,'removal target missing')
refuse('atomic-invalid',owner,'inspect.annotate',follow(db,edits=[{**edit,'id':'NewNote'},{'kind':'remove','id':'Absent'}]),rb,'removal target missing')
# Rewrite checksums independently; only actual native replay can reject a changed display summary.
for label,origin,mode,error in [('forged-report',d0,'report','complete native report replay differs'),('forged-history',d1,'notes','annotation history replay differs')]:
    changed=members(portable(origin));m=json.loads(changed['project.json'])
    if mode=='report':
        value=json.loads(changed['report.json']);value['evidence']['summary']='Forged display summary, unchanged evidence identity.';changed['report.json']=encoded(value);m['report']=sha(changed['report.json'])
    else:
        value=json.loads(changed['annotations.json']);value[0]['text']='Not produced by recorded edit.';data=encoded(value)
        changed['annotations.json']=data;changed['notes-0001.json']=data;m['current']=sha(data);m['history'][0]['after']=sha(data)
    m['members']={n:{'sha256':sha(data),'bytes':len(data)} for n,data in changed.items() if n!='project.json'};changed['project.json']=encoded(m);forged=packed(changed)
    target_owner=call(label+' project','create-project',label)['id'];supplied=asset(label,target_owner,forged,'dobeinspect')
    refuse(label,target_owner,'inspect.import',{**consent,'asset':supplied,'expected_sha256':sha(forged)},None,error)

admission('missing-consent',other,'inspect.analyze',{'asset':a,'format':'javascript','input_sha256':sha(original)},None,'fields')
admission('arbitrary-path',other,'inspect.analyze',{**consent,'asset':'/etc/passwd','format':'native'},None,'asset')
admission('foreign-asset',other,'inspect.analyze',{**consent,'asset':uploaded,'format':'javascript'},None,'asset')
admission('duplicate-edits',owner,'inspect.annotate',follow(db,edits=[updated,updated]),rb,'duplicate')
admission('unknown-action',owner,'inspect.annotate',follow(db,edits=[{**updated,'command':'execute'}]),rb,'fields')
admission('archive-without-consent',other,'inspect.import',{'asset':a,'expected_sha256':sha(bundle),'input_sha256':sha(original)},None,'fields')

# Construct foreign containers as inert bytes, as in the existing engine checks.
elf=bytearray(121);elf[:16]=b'\x7fELF\x02\x01\x01'+bytes(9)
struct.pack_into('<HHIQQQIHHHHHH',elf,16,2,62,1,0x400078,64,0,0,64,56,1,0,0,0)
struct.pack_into('<IIQQQQQQ',elf,64,1,5,0,0x400000,0x400000,121,121,0x1000);elf[120]=0xc3
pe=bytearray(1024);pe[:2]=b'MZ';struct.pack_into('<I',pe,0x3c,0x80);pe[0x80:0x84]=b'PE\0\0'
struct.pack_into('<HHIIIHH',pe,0x84,0x8664,1,0,0,0,240,0x22);optional=0x98;struct.pack_into('<H',pe,optional,0x20b)
struct.pack_into('<I',pe,optional+4,0x200);struct.pack_into('<II',pe,optional+16,0x1000,0x1000);struct.pack_into('<QII',pe,optional+24,0x140000000,0x1000,0x200)
struct.pack_into('<HH',pe,optional+40,6,0);struct.pack_into('<II',pe,optional+56,0x2000,0x200);struct.pack_into('<HH',pe,optional+68,3,0x8160)
struct.pack_into('<QQQQ',pe,optional+72,0x100000,0x1000,0x100000,0x1000);struct.pack_into('<I',pe,optional+108,16);section=optional+240;pe[section:section+8]=b'.text\0\0\0'
struct.pack_into('<IIIIIIHHI',pe,section+8,1,0x1000,0x200,0x200,0,0,0,0,0x60000020);pe[0x200]=0xc3
# Compile one owned Mach-O fixture; inspect it as data and never execute it.
c=out/'sources/owned.c';immutable(c,b'int studio_owned_answer(void) { return 42; }\nint main(void) { return studio_owned_answer(); }\n');binary=out/'sources/owned-native'
if not (out/'native-build.json').exists():
    assert not binary.exists();p=subprocess.run(['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)','/usr/bin/clang',str(c),'-o',str(binary)],stdin=subprocess.DEVNULL,capture_output=True,timeout=60);assert p.returncode==0,p.stderr
    nm=subprocess.run(['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)','/usr/bin/nm',str(binary)],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=20);assert nm.returncode==0,nm.stderr
    save('native-build.json',{'source':digest(c),'binary':digest(binary),'symbols':nm.stdout,'compilerStderr':p.stderr.decode(),'targetExecuted':False})
build=read(out,'native-build.json');assert build['source']==digest(c) and build['binary']==digest(binary) and 'studio_owned_answer' in build['symbols']
wasm=bytes.fromhex('0061736d010000000105016000017f03020100070a0106616e7377657200000a06010400412a0b')
fixtures=[('wasm','wasm',wasm),('invalid-wasm','wasm',b'\0asm\x01\0\0\0\x01\x7f'),('fallback-javascript','javascript',('('*300+'0'+')'*300).encode()),('mach-o','native',binary.read_bytes()),('elf','native',bytes(elf)),('pe','native',bytes(pe))]
for label,kind,data in fixtures:
    who=call(label+' project','create-project','Owned '+label)['id'];supplied=asset(label,who,data,'bin')
    r,d=job(label,who,'inspect.analyze',{'permission':'owned-or-authorized','input_sha256':sha(data),'asset':supplied,'format':kind});inspect_oracle(d,data,[]);observed=report(d);evidence=observed['evidence'];result=evidence['result']
    if label=='wasm':
        assert result['validation']['valid'] is True and result['exports'][0]['name']=='answer'
        canonical=copy.deepcopy(evidence);identity=canonical.pop('id');canonical.pop('summary');canonical.pop('carries_target_content');canonical['subject'].pop('name',None)
        check(identity=='ev_'+sha(encoded(canonical)),'Wasm evidence identity independently recomputes from complete canonical fields')
    elif label=='invalid-wasm':assert result['validation']['valid'] is False and any(x['code']=='wasm_invalid' for x in evidence['limitations'])
    elif label=='fallback-javascript':assert result['facts']['mode']=='lexer' and any(x['code']=='javascript_fallback' for x in evidence['limitations'])
    else:
        metadata=result['binary'];assert metadata['format']==label
        if label=='mach-o':assert any('studio_owned_answer' in x['name'] for x in metadata['symbols']) and evidence['confidence']=='inferred'
        else:assert metadata['bits']==64 and metadata['little_endian'] is True and metadata['arch_name']=='x86_64'
    check(True,label+' native facts match independent input construction and retain stated limitations')

# Fresh protocol clients retrieve durable results after the submitting client exits.
def mcp(label,method,params):
    message=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n'
    p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=message,text=True,capture_output=True,env=env,timeout=30);assert p.returncode==0,(label,p.stderr)
    response=json.loads(p.stdout);assert 'error' not in response,response;save(label+'.json',response);return response['result']
tools=mcp('mcp-discovery','tools/list',{})['tools'];ops=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
check(len(tools)==18 and set('inspect.'+x for x in ('analyze','import','inspect','annotate','export','bundle'))<=set(ops),'same eighteen-tool MCP exposes all six Inspect operations')
req={'name':'dope_get_job','arguments':{'job':jobs[0]['id']}};first=mcp('mcp-first','tools/call',req);reconnected=mcp('mcp-reconnected','tools/call',req)
check(first==reconnected and json.loads(first['content'][0]['text'])['state']=='succeeded','reconnecting MCP clients retrieve same durable findings')
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
save('context.json',{'firstAnnotation':edit,'secondAnnotation':second,'updatedAnnotation':updated,'nativeFixture':build,'inputSourceSHA256':sha(original),'scope':'inert owned inputs; no target execution or import resolution'})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'durableJobs':len(jobs),'admissionRefusals':6,
 'successfulJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'groups':groups,'allNativeGroupsAbsent':True,'verification':verification,
 'ownerVisualApproval':False,'browserFidelityVerified':False,'completeReleaseQualified':False,'network':False,'targetExecution':False})
print(json.dumps({'passed':True,'checks':len(cases),'durableJobs':len(jobs)}))
