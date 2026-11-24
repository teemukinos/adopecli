#!/usr/bin/env python3
"""Real Material jobs through public MCP/CLI, immutable lineage and portable edits."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material, material_document as document, material_source as source
from studio_runtime import capabilities
from studio_runtime.store import Store
from studio_runtime.worker import Worker
from material_source_check import recipe, scalar


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','resource','external','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];jobs=[]
    os.environ['PATH']=str(args.engine.resolve().parent)+':/usr/bin:/bin'
    state=out/'store';store=Store(state);runtime=Path(__file__).resolve().parents[1]/'runtime'
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
    def check(label,ok=True):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def request(method,params):
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n').encode(),capture_output=True,timeout=30)
        if result.returncode:raise AssertionError(result.stderr.decode()[:2000])
        response=json.loads(result.stdout)
        if 'error' in response:raise AssertionError(response)
        return response['result']
    def call(name,arguments):
        result=request('tools/call',{'name':'dope_'+name,'arguments':arguments})
        if result.get('isError'):raise ValueError(result['content'][0]['text'])
        return json.loads(result['content'][0]['text'])
    def cli(*arguments):
        program="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
        result=subprocess.run([sys.executable,'-I','-B','-c',program,str(runtime),'--state',str(state),*map(str,arguments)],capture_output=True,timeout=30)
        if result.returncode:raise AssertionError(result.stderr.decode()[:2000])
        return json.loads(result.stdout)
    def refused(label,action):
        try:action()
        except ValueError:check(label)
        else:raise AssertionError('accepted '+label)
    def job(project,operation,params,key,previous=None,*,success=True):
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:arguments['source_revision']=previous['id']
        first=call('submit_job',arguments);check(key+' idempotency after client exit',call('submit_job',arguments)['id']==first['id'])
        Worker(store).run_one();actual=call('get_job',{'job':first['id']});jobs.append(actual)
        check(key+' durable state',actual['state']==('succeeded' if success else 'failed'))
        if not success:
            check(key+' no failed revision publication',actual['result_revision'] is None and store.get_project('local',project)['head']==(previous['id'] if previous else None));return actual
        result=call('get_revision',{'revision':actual['result_revision']})
        check(key+' qualification scope explicit',result['validation']['native_cold_reopen'] and not result['validation']['cook_performed'] and not result['validation']['render_qualified'])
        return result
    def checkout(label,rev):
        path=out/label;call('export_project',{'revision':rev['id'],'destination':str(path)})
        return path
    def current(path):return (path/'native/document.mcraft').read_bytes()
    def structural(data,tag,value):
        profile=document.inspect_bytes(data);package=profile['container']['root'];items=source.selectors(profile)[package]
        target=next(item for item in items if item['tag']==tag)
        return {'expected_sha256':hashlib.sha256(data).hexdigest(),'operations':[{'kind':'insert','package':package,'element':target['element'],'expected_sha256':target['sha256'],'before':None,'value':value}]}
    try:
        tools=request('tools/list',{})['tools'];public=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        check('same product MCP exposes eight typed Material operations',set(material.OPERATIONS)<=set(public))
        cap=cli('capabilities')['applications']['material']
        check('CLI advertises installed source engine with bounded cooking and no packaging claim',cap['available'] and cap['creation_available'] and cap['cooking_available'] and not cap['installed_qualification'])
        project=call('create_project',{'name':'Material authoring'})['id'];creation={'documents':{'package.sbs':recipe()}}
        first=job(project,'material.create',creation,'create');initial=checkout('created',first);initial_bytes=current(initial)
        check('original authored source retained exactly',(initial/'native/original.input').read_bytes()==initial_bytes)
        request_path=out/'scalar.json';change={'expected_sha256':hashlib.sha256(initial_bytes).hexdigest(),'edits':[{'kind':'node.parameter','package':'package.sbs','graph':'Original','node':'3','name':'outputcolor','expected':{'t':'float4','v':[1.,0.,0.,1.]},'value':{'t':'float4','v':[0.,0.,1.,1.]}}]}
        request_path.write_text(json.dumps(change));submitted=cli('submit',project,'material.edit','--parameters',request_path,'--key','scalar','--source',first['id'])
        Worker(store).run_one();scalar_job=cli('job',submitted['id']);jobs.append(scalar_job);check('CLI edit publishes durable revision',scalar_job['state']=='succeeded')
        second=cli('revision',scalar_job['result_revision']);blue=checkout('blue',second)
        observed=json.loads((blue/'native/model.json').read_text())
        check('CLI edit changes native color exactly',observed['graphs'][0]['nodes'][0]['params']['color']=={'t':'color','v':[0.,0.,1.,1.]})
        third=job(project,'material.edit',structural(current(blue),'attributes',scalar('label','Original finish')),'structure',second)
        fourth=job(project,'material.inspect',{},'inspect',third);final=checkout('inspected',fourth)
        check('initial bytes survive scalar structural and inspection revisions',(final/'native/original.input').read_bytes()==initial_bytes)
        check('initial recipe remains unchanged',(final/'recipes/origin-material-operation.json').read_bytes()==(initial/'recipes/origin-material-operation.json').read_bytes())
        check('original committed revision stays immutable',call('get_revision',{'revision':first['id']})==first)
        check('updated label retained in complete native model',json.loads((final/'native/model.json').read_text())['graphs'][0]['attributes']['label']=='Original finish')
        check('initial lineage digest retained',json.loads((final/'native/origin.json').read_text())['source_sha256']==hashlib.sha256(initial_bytes).hexdigest())
        check('temporary inputs and obsolete change reports absent from manifest',not any(f['path'].startswith('inputs/') or f['path']=='exports/authoring.json' for f in fourth['files']))
        imported=store.import_project('local',final,'Portable material');portable_project=imported['project']['id'];portable=imported['revision']
        reopened=job(portable_project,'material.inspect',{},'portable-inspect',portable)
        portable_path=checkout('portable',reopened)
        check('portable native source and original retained',current(portable_path)==current(final) and (portable_path/'native/original.input').read_bytes()==initial_bytes)
        edited=job(portable_project,'material.edit',structural(current(portable_path),'attributes',scalar('description','Portable edit')),'portable-edit',reopened)
        check('portable revision remains editable',edited['engine']['name']=='materialcraft')
        job(project,'material.edit',change,'stale-source',fourth,success=False)
        # Imported bare source survives the deterministic archive wrapper and
        # later edits as its original exact byte sequence.
        bare=document.inspect_bytes(initial_bytes)['container']['members']['package.sbs'];bare_file=out/'original.sbs';bare_file.write_bytes(bare)
        bare_project=call('create_project',{'name':'Bare source'})['id'];bare_asset=store.import_asset('local',bare_project,bare_file)['id']
        bare_rev=job(bare_project,'material.import',{'asset':bare_asset},'bare-import');bare_bundle=checkout('bare',bare_rev)
        check('bare imported original retained with correct format',(bare_bundle/'native/original.input').read_bytes()==bare and json.loads((bare_bundle/'native/origin.json').read_text())['source_format']=='sbs')
        bare_next=job(bare_project,'material.edit',structural(current(bare_bundle),'attributes',scalar('label','Bare edited')),'bare-edit',bare_rev)
        check('bare original remains exact after structural revision',(checkout('bare-edited',bare_next)/'native/original.input').read_bytes()==bare)
        # Production asset IDs are project-scoped references, never arbitrary
        # paths or raw bytes in JSON. Owned resource bytes live in the archive.
        resource=args.resource.read_bytes();profile=document.inspect_bytes(resource);inputs=profile['container'];resource_project=call('create_project',{'name':'Owned bitmap'})['id']
        trees={name:source.tree(parsed['elements'][0]) for name,parsed in inputs['xml'].items()};assets={}
        for index,(name,data) in enumerate(inputs['members'].items()):
            if name in trees:continue
            path=out/('asset-'+str(index)+'.input');path.write_bytes(data);assets[name]=store.import_asset('local',resource_project,path)['id']
        resource_rev=job(resource_project,'material.create',{'documents':trees,'assets':assets},'resource-create');resource_bundle=checkout('resource',resource_rev)
        check('created resource members own exact imported bytes',all(document.read_native(resource_bundle/'native/document.mcraft')['container']['members'][name]==inputs['members'][name] for name in assets))
        name=next(iter(assets));original_asset=inputs['members'][name]
        operation={'kind':'asset.replace','member':name,'expected_sha256':hashlib.sha256(original_asset).hexdigest(),'asset':assets[name]}
        replaced=job(resource_project,'material.edit',{'expected_sha256':hashlib.sha256(current(resource_bundle)).hexdigest(),'operations':[operation]},'asset-reuse',resource_rev)
        reused=checkout('resource-reused',replaced)
        replaced_again=job(resource_project,'material.edit',{'expected_sha256':hashlib.sha256(current(reused)).hexdigest(),'operations':[operation]},'asset-reuse-again',replaced)
        check('same project asset can be used across consecutive revisions',replaced_again['parent']==replaced['id'])
        resource_portable=store.import_project('local',reused,'Portable bitmap')
        bitmap_reopened=job(resource_portable['project']['id'],'material.inspect',{},'portable-bitmap',resource_portable['revision'])
        bitmap_bundle=checkout('portable-bitmap',bitmap_reopened)
        check('portable bitmap owns its bytes without old project asset authorization',document.read_native(bitmap_bundle/'native/document.mcraft')['container']['members'][name]==original_asset)
        refused('cross-project asset access refused',lambda:call('submit_job',{'project':project,'operation':'material.create','parameters':{'documents':trees,'assets':assets},'idempotency_key':'foreign-assets'}))
        external=document.inspect_bytes(args.external.read_bytes())['container']
        for label,data in [('malformed',b'<package/>'),('external',external['members'][external['root']])]:
            bad=out/(label+'.input');bad.write_bytes(data);p=call('create_project',{'name':label})['id'];identity=store.import_asset('local',p,bad)['id']
            job(p,'material.import',{'asset':identity},label,success=False)
        for label,operation,params,rev in [('arbitrary command','material.inspect',{'command':'file.open'},'source'),
                ('raw path','material.import',{'asset':'/tmp/input.sbs'},None),('new on revision','material.create',creation,'source'),
                ('inspection without source','material.inspect',{},None),('ambiguous edit','material.edit',{'expected_sha256':'0'*64,'edits':[],'operations':[]},'source'),
                ('raw asset bytes','material.edit',{'expected_sha256':'0'*64,'operations':[{'kind':'asset.add','member':'a.png','data':'raw'}]},'source'),
                ('bad tree namespace','material.create',{'documents':{'package.sbs':{'tag':'x:package','attributes':{},'children':[]}}},None)]:
            refused(label,lambda operation=operation,params=params,rev=rev:material.validate(operation,params,rev))
        # A forged portable lineage does not become a successful native revision.
        tampered=out/'tampered';store.checkout('local',fourth['id'],tampered);(tampered/'native/original.input').write_bytes(b'wrong')
        refused('portable checksum detects original tampering',lambda:store.import_project('local',tampered,'Tampered'))
        # Direct adapter calls also verify lineage before opening native input.
        direct=out/'bad-lineage';store.checkout('local',fourth['id'],direct);(direct/'native/original.input').write_bytes(b'wrong')
        refused('adapter refuses original lineage mismatch',lambda:material.execute(direct,'material.inspect',{}))
        check('resource upstream input unchanged',args.resource.read_bytes()==resource)
        evidence={'passed':True,'checks':checks,'durable_jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),
                  'public_tools':len(tools),'operations':list(material.OPERATIONS),'source_runtime_available':True,'installed_qualification':False,
                  'general_cooking_qualified':False,'remote_actions':False,'goal_complete':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'durable_jobs':len(jobs),'succeeded':evidence['succeeded']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
