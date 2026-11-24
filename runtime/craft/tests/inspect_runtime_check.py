#!/usr/bin/env python3
"""Inspect through independent CLI/MCP clients, real workers and native replay."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--staged',action='store_true');args=parser.parse_args();out=args.output.resolve()
    resources=out/'fixture/DobeCLI/lib/dobe';runtime=resources/'runtime';sha=lambda data:hashlib.sha256(data).hexdigest()
    if not args.staged:
        out.mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1]/'runtime/studio_runtime',runtime/'studio_runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(args.engine.resolve().parent.parent,resources/'engines/inspect')
        data=(resources/'engines/inspect/engine.json').read_bytes();meta=json.loads(data)
        receipt={'schema_version':1,'product':'dobe','distribution':'dobe-cli','platform':'macos-arm64','release_signed':False,
                 'qualification':'test-layout-only-not-installed','components':[{'name':'dobe-inspect','version':meta['version'],
                 'source_lock_sha256':meta['source_lock_sha256'],'engine_manifest_sha256':sha(data)}],'files':{}}
        for path in resources.rglob('*'):
            if path.is_file():receipt['files'][path.relative_to(resources.parent.parent).as_posix()]={'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size}
        (resources/'bundle.json').write_text(json.dumps(receipt,sort_keys=True)+'\n')
        child=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--staged','--engine',str(args.engine.resolve()),'--output',str(out)])
        raise SystemExit(child.returncode)
    sys.path.insert(0,str(runtime))
    from studio_runtime import inspection, inspect_source as source, inspect_project as project, execution
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    state=out/'state';store=Store(state);checks=[];refusals=[];jobs=[]
    os.environ['PATH']='/usr/bin:/bin';os.environ['STUDIO_BUNDLE_RESOURCES']=str(out/'untrusted')
    def check(label,condition):assert condition,label;checks.append(label)
    def refused(label,fn):
        try:fn()
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def request(method,params):
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n').encode(),capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr;value=json.loads(result.stdout);assert 'error' not in value,value;return value['result']
    def call(name,params):
        result=request('tools/call',{'name':'dope_'+name,'arguments':params})
        if result.get('isError'):raise ValueError(result['content'][0]['text'])
        return json.loads(result['content'][0]['text'])
    def cli(*arguments):
        code="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),'--state',str(state),*map(str,arguments)],capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr;return json.loads(result.stdout)
    def job(owner,operation,params,key,previous=None,success=True):
        arguments={'project':owner,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:arguments['source_revision']=previous['id']
        submitted=call('submit_job',arguments);check(key+' idempotent after client exit',call('submit_job',arguments)['id']==submitted['id'])
        Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
        check(key+' durable outcome '+str(actual.get('error')),actual['state']==('succeeded' if success else 'failed'))
        if not success:
            check(key+' no partial publication',actual['result_revision'] is None and store.get_project('local',owner)['head']==(previous['id'] if previous else None));return actual
        result=call('get_revision',{'revision':actual['result_revision']})
        check(key+' native replay and consent scope',result['validation']['native_report_replayed'] and result['validation']['annotation_history_replayed']
              and result['validation']['carries_target_content'] and not result['validation']['input_executed']);return result
    def checkout(name,revision):
        path=out/name;call('export_project',{'revision':revision['id'],'destination':str(path)});return path
    def asset(owner,data,name):
        path=out/name;path.write_bytes(data);return store.import_asset('local',owner,path)['id']
    def current(folder):return (folder/'native/project.dobeinspect').read_bytes()
    original=b"export const answer=42; console.log('</pre><script>forged()</script>');\n"
    consent={'permission':'owned-or-authorized','input_sha256':sha(original)}
    def follow(data,**extra):return {**consent,'expected_sha256':sha(data),**extra}
    try:
        tools=request('tools/list',{})['tools'];ops=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        check('same fifteen tools register all six Inspect operations',len(tools)==15 and set(inspection.OPERATIONS)<=set(ops))
        scope=cli('capabilities')['applications']['inspect'];check('explicit capability permission and qualification',scope['available'] and scope['explicit_input_consent_required']
              and scope['project_scoped_assets_only'] and not scope['target_execution'] and not scope['installed_qualification'])
        owner=call('create_project',{'name':'Inspectable module'})['id'];uploaded=asset(owner,original,'input.js')
        first=job(owner,'inspect.analyze',{**consent,'asset':uploaded,'format':'javascript'},'analyze');initial=checkout('initial',first);portable=current(initial)
        check('exact original stored in native deliverable',(initial/'native/source.bin').read_bytes()==original)
        second=job(owner,'inspect.inspect',follow(portable),'inspect',first)
        edits=[{'kind':'upsert','id':'Export','pointer':'/evidence/result/facts/exports/esm/0','title':'Export contract','text':'Retain answer. <script>bad()</script>','status':'open','severity':'note'}]
        parameters=out/'annotations-request.json';parameters.write_text(json.dumps(follow(portable,edits=edits)))
        submitted=cli('submit',owner,'inspect.annotate','--parameters',parameters,'--key','cli-annotation','--source',second['id'])
        Worker(store).run_one();actual=cli('job',submitted['id']);jobs.append(actual);check('CLI annotation completes after client exit',actual['state']=='succeeded')
        revised=cli('revision',actual['result_revision']);changed=checkout('changed',revised);edited=current(changed);model=project.inspect_bytes(edited)
        check('precise annotation keeps source and native report',model['annotations'][0]['title']=='Export contract' and (changed/'native/source.bin').read_bytes()==original
              and (changed/'native/report.json').read_bytes()==(initial/'native/report.json').read_bytes())
        json_revision=job(owner,'inspect.export',follow(edited,format='json'),'json',revised);json_folder=checkout('json',json_revision)
        check('editable JSON separates analyst notes',json.loads((json_folder/'exports/findings.json').read_bytes())['analyst_annotations']==model['annotations'])
        html_revision=job(owner,'inspect.export',follow(edited,format='html'),'html',json_revision);html_folder=checkout('html',html_revision)
        markup=(html_folder/'exports/findings.html').read_bytes();check('HTML never renders target or analyst script',b'<script>' not in markup and b'&lt;script&gt;' in markup)
        bundled=job(owner,'inspect.bundle',follow(edited),'bundle',html_revision);bundle=checkout('bundle',bundled)
        check('portable delivery retains exact original and edit history',(bundle/'exports/findings.dobeinspect').read_bytes()==edited)
        recipient=call('create_project',{'name':'Portable inspection'})['id'];portable_asset=asset(recipient,edited,'transfer.dobeinspect')
        imported=job(recipient,'inspect.import',{**follow(edited),'asset':portable_asset},'portable-import');returned=checkout('returned',imported)
        check('portable import preserves complete project',current(returned)==edited)
        update=copy.deepcopy(edits);update[0].update(status='resolved',text='Verified export contract.')
        transferred=job(recipient,'inspect.annotate',follow(edited,edits=update),'portable-reedit',imported)
        check('portable project stays editable',project.inspect_bytes(current(checkout('reedited',transferred)))['annotations'][0]['status']=='resolved')
        moved=store.import_project('local',bundle,'Whole inspection');job(moved['project']['id'],'inspect.inspect',follow(edited),'whole-transfer',moved['revision'])
        job(owner,'inspect.inspect',dict(follow(edited),input_sha256='0'*64),'wrong-consent',bundled,False)
        job(owner,'inspect.annotate',dict(follow(edited,edits=edits),expected_sha256='0'*64),'stale-revision',bundled,False)
        bad=copy.deepcopy(edits);bad[0]['pointer']='/evidence/result/missing';job(owner,'inspect.annotate',follow(edited,edits=bad),'missing-finding',bundled,False)
        empty=call('create_project',{'name':'Incorrect input hash'})['id'];new_asset=asset(empty,original,'wrong-input.js')
        job(empty,'inspect.analyze',dict(consent,asset=new_asset,format='javascript',input_sha256='0'*64),'wrong-input',success=False)
        for label,params in [('missing consent',{'asset':uploaded,'format':'javascript','input_sha256':sha(original)}),
                             ('arbitrary path',dict(consent,asset='/etc/passwd',format='native')),('foreign project asset',dict(consent,asset=portable_asset,format='javascript'))]:
            refused(label,lambda params=params:call('submit_job',{'project':owner,'operation':'inspect.analyze','parameters':params,'idempotency_key':'refuse-'+label}))
        refused('archive does not grant consent',lambda:call('submit_job',{'project':recipient,'operation':'inspect.import',
                'parameters':{'asset':portable_asset,'expected_sha256':sha(edited),'input_sha256':sha(original)},'idempotency_key':'missing-import-consent'}))
        baseline=project.inspect_bytes(portable);manifest=copy.deepcopy(baseline['manifest']);members={k:v for k,v in baseline['members'].items() if k!='project.json'}
        fake=source.strict_json(members['report.json']);fake['evidence']['summary']='Forged display claim with unchanged canonical ID.'
        members['report.json']=source.encoded(fake);manifest['report']=sha(members['report.json']);manifest['members']['report.json']=project.record(members['report.json'])
        forged=project.pack(manifest,members);other=call('create_project',{'name':'Forged report'})['id'];fake_asset=asset(other,forged,'forged.dobeinspect')
        failure=job(other,'inspect.import',{**follow(forged),'asset':fake_asset},'forged-report',success=False)
        check('hash-consistent forgery fails native full-report replay','complete native report replay differs' in failure['error']['message'])
        # A report about an invalid module is still a useful, explicitly invalid inspection.
        wasm=b'\0asm\x01\0\0\0\x01\x7f';wasm_owner=call('create_project',{'name':'Invalid Wasm findings'})['id'];wasm_asset=asset(wasm_owner,wasm,'invalid.wasm')
        wasm_revision=job(wasm_owner,'inspect.analyze',{'asset':wasm_asset,'format':'wasm','permission':'owned-or-authorized','input_sha256':sha(wasm)},'invalid-wasm')
        check('invalid target remains invalid after durable success',not json.loads((checkout('wasm',wasm_revision)/'native/report.json').read_bytes())['evidence']['result']['validation']['valid'])
        with store.connect() as db:rows=[dict(r) for r in db.execute('SELECT * FROM attempt_executions')]
        check('every registered execution group has terminated',bool(rows) and all(execution.group_absent(r['process_group']) for r in rows))
        evidence={'passed':True,'checks':len(checks),'refusals':len(refusals),'jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),
                  'intentional_failures':sum(j['state']=='failed' for j in jobs),'operations':list(inspection.OPERATIONS),
                  'all_groups_absent':True,'actual_native_children':True,'installed_qualified':False,'linux_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))
    finally:
        for name,value in [('checks',checks),('refusals',refusals),('jobs',jobs)]: (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')


if __name__=='__main__':main()
