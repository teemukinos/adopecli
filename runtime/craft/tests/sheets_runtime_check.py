#!/usr/bin/env python3
"""Exercise Sheets through separate CLI/MCP clients, real workers and native code."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--staged',action='store_true'); args=parser.parse_args()
    out=args.output.resolve(); resources=out/'fixture/DobeCLI/lib/dobe'; runtime=resources/'runtime'
    sha=lambda data:hashlib.sha256(data).hexdigest()
    if not args.staged:
        out.mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1]/'runtime/studio_runtime',runtime/'studio_runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(args.engine.resolve().parent.parent,resources/'engines/sheets')
        data=(resources/'engines/sheets/engine.json').read_bytes(); meta=json.loads(data)
        manifest={'schema_version':1,'product':'dobe','distribution':'dobe-cli','platform':'macos-arm64','release_signed':False,
            'qualification':'test-layout-only-not-installed','components':[{'name':'dobe-sheets','version':meta['version'],
            'source_lock_sha256':meta['source_lock_sha256'],'engine_manifest_sha256':sha(data)}],'files':{}}
        for path in resources.rglob('*'):
            if path.is_file(): manifest['files'][path.relative_to(resources.parent.parent).as_posix()]={'bytes':path.stat().st_size,'sha256':sha(path.read_bytes())}
        (resources/'bundle.json').write_text(json.dumps(manifest,sort_keys=True)+'\n')
        raise SystemExit(subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--staged','--engine',str(args.engine.resolve()),'--output',str(out)],timeout=300).returncode)
    sys.path.insert(0,str(runtime))
    from studio_runtime import sheets, sheets_source as source, sheets_project as project
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    from studio_runtime import execution
    state=out/'state'; store=Store(state); checks=[]; refusals=[]; jobs=[]
    os.environ['PATH']='/usr/bin:/bin'; os.environ['STUDIO_BUNDLE_RESOURCES']=str(out/'untrusted')
    def check(label,condition):
        if not condition: raise AssertionError(label)
        checks.append(label)
    def refused(label,action):
        try: action()
        except ValueError as error: refusals.append({'case':label,'error':str(error)})
        else: raise AssertionError('accepted '+label)
    def request(method,params):
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n').encode(),capture_output=True,timeout=30)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        value=json.loads(result.stdout)
        if 'error' in value: raise AssertionError(value)
        return value['result']
    def call(name,params):
        value=request('tools/call',{'name':'dope_'+name,'arguments':params})
        if value.get('isError'): raise ValueError(value['content'][0]['text'])
        return json.loads(value['content'][0]['text'])
    def cli(*arguments):
        code="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),'--state',str(state),*map(str,arguments)],capture_output=True,timeout=30)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout)
    def job(owner,operation,params,key,previous=None,success=True):
        arguments={'project':owner,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous: arguments['source_revision']=previous['id']
        submitted=call('submit_job',arguments)
        check(key+' idempotent after client exit',call('submit_job',arguments)['id']==submitted['id'])
        Worker(store).run_one(); actual=call('get_job',{'job':submitted['id']}); jobs.append(actual)
        check(key+' durable outcome '+str(actual.get('error')),actual['state']==('succeeded' if success else 'failed'))
        if not success:
            check(key+' no partial publication',actual['result_revision'] is None and store.get_project('local',owner)['head']==(previous['id'] if previous else None)); return actual
        result=call('get_revision',{'revision':actual['result_revision']}); validation=result['validation']
        check(key+' native model and admission verified',validation['native_model_equal'] and validation['profile_admission_complete']
              and not validation['general_admission_complete'])
        return result
    def checkout(name,rev):
        path=out/name; call('export_project',{'revision':rev['id'],'destination':str(path)}); return path
    def asset(owner,data,name):
        path=out/name; path.write_bytes(data); return store.import_asset('local',owner,path)['id']
    def portable(folder): return (folder/'native/project.dobesheets').read_bytes()
    try:
        tools=request('tools/list',{})['tools'];operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        check('same fifteen-tool MCP registers all seven Sheets operations',len(tools)==15 and set(sheets.OPERATIONS)<=set(operations))
        scope=cli('capabilities')['applications']['sheets']
        check('capability scope is explicit and not installed qualification',scope['available'] and not scope['installed_qualification'] and not scope['direct_xlsx_import_qualified'])
        owner=call('create_project',{'name':'Studio production budget'})['id']
        params={'recipe':'production_budget','version':1,'title':'Campaign assets','currency':'EUR','tax_rate':.24,
                'items':[{'name':'Product images','quantity':10,'unit_price':12.5},{'name':'Motion exports','quantity':4,'unit_price':20}]}
        first=job(owner,'sheets.create',params,'create');initial=checkout('created',first);original=portable(initial);inspected=project.inspect_bytes(original)
        check('recipe creates calculated editable native history',inspected['revision_count']==1 and first['validation']['native_calculation_verified'])
        before_model=inspected['profiles']['document.json']['document']
        changes={'expected_sha256':sha(original),'edits':[{'sheet':0,'cell':'B3','value':12}]}
        parameter_file=out/'edit.json';parameter_file.write_text(json.dumps(changes))
        submitted=cli('submit',owner,'sheets.edit','--parameters',parameter_file,'--key','quantity','--source',first['id'])
        Worker(store).run_one();actual=cli('job',submitted['id']);jobs.append(actual);check('CLI edit survives client exit',actual['state']=='succeeded')
        second=cli('revision',actual['result_revision']);changed=checkout('changed',second);edited=portable(changed)
        current=project.inspect_bytes(edited)
        check('precise quantity revision preserves source and recipe',current['members']['original.json']==inspected['members']['original.json'] and
              current['profiles']['document.json']['document']['sheets'][1]==before_model['sheets'][1] and
              (changed/'recipes/sheets-production.json').read_bytes()==(initial/'recipes/sheets-production.json').read_bytes())
        third=job(owner,'sheets.calculate',{'expected_sha256':sha(edited)},'calculate',second);calculated=checkout('calculated',third);final=portable(calculated)
        fourth=job(owner,'sheets.export',{'expected_sha256':sha(final),'format':'csv'},'csv',third);csvfolder=checkout('csv',fourth)
        import csv,io
        values=list(csv.reader(io.StringIO((csvfolder/'exports/workbook.csv').read_text())))
        check('independent CSV reader sees total 285.2',values[7][3]=='285.2' and fourth['validation']['delivery_verified'])
        fifth=job(owner,'sheets.export',{'expected_sha256':sha(final),'format':'html'},'html',fourth);htmlfolder=checkout('html',fifth)
        check('native HTML carries formatted revised total',b'285.20' in (htmlfolder/'exports/workbook.html').read_bytes())
        sixth=job(owner,'sheets.inspect',{},'inspect',fifth);seventh=job(owner,'sheets.bundle',{},'bundle',sixth);bundle=checkout('bundle',seventh)
        check('portable bundle keeps exact history and original',(bundle/'exports/workbook.dobesheets').read_bytes()==final and portable(bundle)==final and portable(initial)==original)
        check('only declared artifacts publish',not any(f['path'].startswith(('.sheets-attempt-','inputs/')) for f in seventh['files']))
        for kind,data in [('dobesheets',final),('json',inspected['members']['document.json'])]:
            recipient=call('create_project',{'name':'Sheets '+kind+' transfer'})['id'];uploaded=asset(recipient,data,'import.'+kind)
            imported=job(recipient,'sheets.import',{'asset':uploaded,'format':kind},'import-'+kind);folder=checkout('imported-'+kind,imported)
            check(kind+' retains exact original',portable(folder)==data if kind=='dobesheets' else (folder/'native/original.json').read_bytes()==data)
            if kind=='dobesheets':
                revised=job(recipient,'sheets.edit',{'expected_sha256':sha(data),'edits':[{'sheet':1,'cell':'B2','value':.25}]},'transfer-tax',imported)
                check('portable transfer remains editable',revised['parent']==imported['id'] and revised['validation']['native_calculation_verified'])
        moved=store.import_project('local',bundle,'Whole Sheets project');job(moved['project']['id'],'sheets.inspect',{},'whole-transfer',moved['revision'])
        failed=job(owner,'sheets.edit',{'expected_sha256':sha(final),'edits':[{'sheet':0,'cell':'B3','value':99},{'sheet':0,'cell':'D3','formula':'WEBSERVICE("https://invalid.example")'}]},'unsupported-formula',seventh,False)
        check('native formula refusal explains failure','outside the supported profile' in failed['error']['message'])
        job(owner,'sheets.calculate',{'expected_sha256':'0'*64},'stale-hash',seventh,False)
        refused('create unknown model',lambda:sheets.validate('sheets.create',{'document':{'unknown':True}},None))
        refused('arbitrary native script',lambda:sheets.validate('sheets.edit',{'expected_sha256':sha(final),'edits':[{'sheet':0,'cell':'A1','script':'x'}]},'source'))
        refused('rounded integer input',lambda:sheets.validate('sheets.edit',{'expected_sha256':sha(final),'edits':[{'sheet':0,'cell':'B3','value':2**53+1}]},'source'))
        # Hashes are internally consistent; the real worker must still replay.
        forged=project.inspect_bytes(final);manifest=copy.deepcopy(forged['manifest']);members={k:v for k,v in forged['members'].items() if k!='project.json'}
        step=manifest['history'][-1];model=source.strict_json(members[step['state']]);model['sheets'][0]['cells']['bands']['0']['rows']['7']['3']['value']={'t':'Number','v':1.0}
        fake=source.encoded(model);members[step['state']]=fake;members['document.json']=fake;step['after']=sha(fake);manifest['current']=sha(fake)
        for name in (step['state'],'document.json'):manifest['members'][name]=project.record(fake)
        tampered=project.pack(manifest,members);recipient=call('create_project',{'name':'Forged cache'})['id'];uploaded=asset(recipient,tampered,'forged.dobesheets')
        forged_job=job(recipient,'sheets.import',{'asset':uploaded,'format':'dobesheets'},'forged-import',success=False)
        check('forged cache rejected by native replay','native history replay differs' in forged_job['error']['message'])
        other=call('create_project',{'name':'Different owner'})['id']
        refused('cross-project asset',lambda:call('submit_job',{'project':other,'operation':'sheets.import','parameters':{'asset':uploaded,'format':'dobesheets'},'idempotency_key':'cross-asset'}))
        with store.connect() as db:execution_rows=[dict(r) for r in db.execute('SELECT * FROM attempt_executions').fetchall()]
        check('all actual registered process groups are gone',bool(execution_rows) and all(execution.group_absent(r['process_group']) for r in execution_rows))
        report={'passed':True,'checks':len(checks),'refusals':len(refusals),'jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),'intentional_failures':sum(j['state']=='failed' for j in jobs),
                'operations':list(sheets.OPERATIONS),'installed_qualified':False,'linux_qualified':False,'actual_native_children':True,'all_groups_absent':True}
        (out/'evidence.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    finally:
        (out/'checks.json').write_text(json.dumps(checks,indent=2)+'\n');(out/'refusals.json').write_text(json.dumps(refusals,indent=2)+'\n');(out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
