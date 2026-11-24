#!/usr/bin/env python3
"""Immutable archived image/function dependencies through real native jobs."""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_document as document, material_compute as compute, material_maps as maps
from studio_runtime import material_source as source, material_dependencies as dependencies, material_preview as preview, material_bundle as bundle
from studio_runtime.store import Store
from studio_runtime.worker import Worker
from material_source_check import recipe
from material_procedural_check import child
from material_export_codecs_check import bitmap_recipe


def xml_recipe():
    data,_=source.create({'package.sbs':recipe()})
    return ET.fromstring(document.inspect_bytes(data)['container']['members']['package.sbs'])


def dependency(root,name,uid=900):
    dep=copy.deepcopy(root.find('dependencies/dependency'));dep.find('filename').set('v',name);dep.find('uid').set('v',str(uid));root.find('dependencies').append(dep)
    return uid


def parent(root,target,reference,name='Parent'):
    root=copy.deepcopy(root);graph=root.find('content/graph');graph.find('identifier').set('v',name)
    uid=dependency(root,reference);holder=graph.find('compNodes');bridges=[n for n in holder if n.find('compImplementation/compOutputBridge') is not None];holder.clear()
    node=child(holder,'compNode');child(node,'uid',800);child(child(node,'GUILayout'),'gpos','50 40 0');outputs=child(node,'compOutputs')
    impl=child(child(node,'compImplementation'),'compInstance');child(impl,'path','pkg:///'+target+'?dependency='+str(uid));child(impl,'parameters');bindings=child(impl,'outputBridgings')
    for index,(output,bridge) in enumerate(zip(graph.findall('graphOutputs/graphoutput'),bridges)):
        identity=810+index;port=child(outputs,'compOutput');child(port,'uid',identity);child(port,'comptype',output.find('channels').get('v'))
        port=child(bindings,'outputBridging');child(port,'uid',identity);child(port,'identifier',output.find('identifier').get('v'))
        bridge.find('connections/connection/connRef').set('v','800');bridge.find('connections/connection/connRefOutput').set('v',str(identity));holder.append(bridge)
    return root


def archive(trees,assets=None):
    return source.create({name:source.tree(document.container.parse_xml(ET.tostring(tree,encoding='utf-8'))['root']) for name,tree in trees.items()},assets or {})[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','references','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=args.output.resolve();root.mkdir();engine=args.engine.resolve();os.environ['PATH']=str(engine.parent)+':/usr/bin:/bin'
    checks=[];jobs=[];calls=[];original_run=document.run
    def tracked(command,*a,**kw):calls.append(list(map(str,command)));return original_run(command,*a,**kw)
    document.run=tracked
    def check(name,condition=True):
        if not condition:raise AssertionError(name)
        checks.append(name)
    def refused(name,action,contains=None):
        try:action()
        except ValueError as error:check(name,contains is None or contains in str(error))
        else:raise AssertionError('accepted '+name)
    def file(name,data):p=root/name;p.write_bytes(data);return p
    def prepare(label,data):
        path=file(label+'.mcraft',data);result=document.prepare(root,path,root/(label+'-prepared'),engine)
        check(label+' exact archive and original bytes',(root/(label+'-prepared/native/document.mcraft')).read_bytes()==data and path.read_bytes()==data)
        check(label+' all packages compared twice',result['native_calls']==3 and result['native_packages_compared']==sorted(document.inspect_bytes(data)['model']['packages']))
        return path
    def pixels(label,path,expected):
        dest=root/(label+'-maps');result=maps.export(root,path,dest,{'graph':'Parent','format':'png','depth':8},engine)
        for item in result['maps']:
            with Image.open(dest/item['file']) as im:
                rgba=expected if 'basecolor'==item['identifier'] else (0,0,0,255)
                check(label+' every '+item['identifier']+' pixel',im.convert('RGBA').tobytes()==bytes(rgba)*(im.width*im.height))
        check(label+' instance evaluation charged',result['usage']['node_visits']>3)
        return result
    try:
        original=xml_recipe();outer=parent(original,'Original','deps/child.sbs');trees={'package.sbs':outer,'deps/child.sbs':original}
        data=archive(trees);path=prepare('image',data);pixels('image',path,(255,0,0,255))
        check('source still records literal relative references',b'deps/child.sbs' in document.inspect_bytes(data)['container']['members']['package.sbs'])
        nested=parent(original,'Original','../lib/leaf.sbs',name='Middle')
        deep=archive({'package.sbs':parent(original,'Middle','deps/middle.sbs'),'deps/middle.sbs':nested,'lib/leaf.sbs':original})
        deep_path=prepare('nested',deep);pixels('nested',deep_path,(255,0,0,255))
        unused=copy.deepcopy(outer);dependency(unused,'unused/extra.sbs',901)
        unused_data=archive({'package.sbs':unused,'deps/child.sbs':original,'unused/extra.sbs':original});unused_path=prepare('unused',unused_data)
        profile=document.inspect_bytes(unused_data);process=document.Engine(engine,root);reply=document.snapshot_json(process._run('snapshot',unused_path))
        check('native archive registry has exactly admitted stable identities',set(reply['archivedPackages'])=={dependencies.PREFIX+p for p in profile['model']['packages']})
        for label,mutate in [
            ('missing package',lambda r:r['archivedPackages'].pop(dependencies.PREFIX+'unused/extra.sbs')),
            ('unknown package',lambda r:r['archivedPackages'].update({'ambient':r['nativePackage']})),
            ('unused package alteration',lambda r:r['archivedPackages'][dependencies.PREFIX+'unused/extra.sbs'].update(name='changed')),
            ('root package alias alteration',lambda r:r['archivedPackages'][dependencies.PREFIX+'package.sbs'].update(name='changed')),
            ('changed reference',lambda r:r['nativePackage']['graphs'][0]['nodes'][0]['instance'].update(package='ambient'))]:
            changed=copy.deepcopy(reply);mutate(changed);refused(label,lambda:dependencies.check_reply(profile,changed))
        # A function body moved into an archive retains its source default and
        # receives the same registry as image instances, including nested calls.
        fn=ET.fromstring((args.references/'source-default.sbs').read_bytes());callee=fn.find('content/function');fn.find('content').remove(callee)
        library=copy.deepcopy(original);library.find('content').clear();library.find('content').append(callee)
        uid=dependency(fn,'functions/default.sbs')
        reference=fn.find('.//materialcraftInterface/../funcDatas/funcData/constantValue/constantValueString');reference.set('v','pkg:///F1?dependency='+str(uid))
        functions=archive({'package.sbs':fn,'functions/default.sbs':library});fn_path=prepare('function',functions)
        cooked=compute.cook(root,fn_path,'Atomic',engine)
        check('external function default produces independent arithmetic result',any(o.get('value')=={'t':'float','v':.125} for n in cooked['nodes'] for o in n['outputs']))
        chain=ET.fromstring((args.references/'depth-eight.sbs').read_bytes())
        functions_by_name={f.find('identifier').get('v'):f for f in chain.findall('content/function')}
        for f in functions_by_name.values():chain.find('content').remove(f)
        uid=dependency(chain,'functions/F1.sbs')
        entry=chain.find('.//materialcraftInterface/../funcDatas/funcData/constantValue/constantValueString')
        entry.set('v','pkg:///F1?dependency='+str(uid));chain_trees={'package.sbs':chain}
        for index in range(1,9):
            lib=copy.deepcopy(original);lib.find('content').clear();lib.find('content').append(functions_by_name['F'+str(index)])
            if index<8:
                uid=dependency(lib,'F'+str(index+1)+'.sbs')
                entry=lib.find('.//materialcraftInterface/../funcDatas/funcData/constantValue/constantValueString')
                entry.set('v','pkg:///F'+str(index+1)+'?dependency='+str(uid))
            chain_trees['functions/F'+str(index)+'.sbs']=lib
        chain_data=archive(chain_trees);chain_path=prepare('function-depth-eight',chain_data)
        cooked=compute.cook(root,chain_path,'Atomic',engine)
        check('eight archived function levels preserve connected arguments',any(o.get('value')=={'t':'float','v':.375} for n in cooked['nodes'] for o in n['outputs']))
        # Resource decoding occurs in the source package, not under the caller's
        # same-named resource or a disk-relative path.
        image=io.BytesIO();Image.new('RGBA',(32,32),(0,0,255,255)).save(image,format='PNG')
        bitmap,_=bitmap_recipe(image.getvalue(),'png');bp=document.inspect_bytes(bitmap)['container'];bt=ET.fromstring(bp['members'][bp['root']])
        assets={'deps/'+name:value for name,value in bp['members'].items() if name!=bp['root']}
        textured=archive({'package.sbs':outer,'deps/child.sbs':bt},assets);texture_path=prepare('bitmap',textured);pixels('bitmap',texture_path,(0,0,255,255))
        red=io.BytesIO();Image.new('RGBA',(32,32),(255,0,0,255)).save(red,format='PNG')
        red_data,_=bitmap_recipe(red.getvalue(),'png');rp=document.inspect_bytes(red_data)['container'];rt=ET.fromstring(rp['members'][rp['root']])
        collision=archive({'package.sbs':parent(rt,'Original','deps/child.sbs'),'deps/child.sbs':bt},
            {**assets,**{name:value for name,value in rp['members'].items() if name!=rp['root']}})
        collision_path=prepare('resource-namespaces',collision);pixels('resource-namespaces',collision_path,(0,0,255,255))
        moved=root/'copied-location.mcraft';moved.write_bytes(unused_data)
        relocated=document.snapshot_json(process._run('snapshot',moved))
        check('snapshot identities independent of disk location',relocated==reply)
        # Package paths and function bodies remain immutable through bundle and
        # preview, with every exported map checked against a fresh bounded cook.
        result=preview.render(root,deep_path,root/'preview',{'graph':'Parent','view':'3d','width':64,'height':48},engine)
        check('nested preview performs bounded cook',result['native_calls']==3)
        portable=root/'nested.mcmat';bundle.export(root,deep_path,portable,{'graph':'Parent'},engine)
        verified=bundle.verify(root,portable.read_bytes(),engine);check('portable bundle preserves every exact package',verified['members']['source.mcraft']==deep and verified['cook_verified'])
        # All package/node/instance limits still apply before native access.
        for label,reference in [('escape','../../outside.sbs'),('absolute','/outside.sbs'),('library','sbs://outside.sbs')]:
            bad=copy.deepcopy(trees);bad['package.sbs'].findall('dependencies/dependency')[1].find('filename').set('v',reference)
            before=len(calls);refused(label+' refuses before native',lambda:archive(bad));check(label+' no native call',len(calls)==before)
        cycle=parent(original,'Parent','../package.sbs',name='Original')
        refused('cyclic image expansion refuses before native',lambda:archive({'package.sbs':outer,'deps/child.sbs':cycle}))
        oversized=copy.deepcopy(original);oversized.find('.//option/value').set('v','13x13')
        # Instance output inherits caller size; an explicit child base must be
        # large to exercise its own resolved raster budget.
        params=oversized.find('.//compNode/compImplementation/compFilter/parameters');p=child(params,'parameter');child(p,'name','outputsize');child(p,'relativeTo','0');child(child(p,'paramValue'),'constantValueInt2','13 13')
        excessive=archive({'package.sbs':outer,'deps/child.sbs':oversized});large=file('large.mcraft',excessive)
        refused('nested raster budget remains shared',lambda:compute.cook(root,large,'Parent',engine),'node raster budget')
        # Real durable import/edit/export/bundle/import and portable reopen.
        state=root/'store';store=Store(state);project=store.create_project('local','Archived materials')['id']
        runtime=Path(__file__).resolve().parents[1]/'runtime'
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        def call(name,arguments):
            request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':arguments}}
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps(request)+'\n').encode(),capture_output=True,timeout=30)
            check('MCP client exits before worker executes',result.returncode==0)
            response=json.loads(result.stdout);assert 'error' not in response,response
            result=response['result'];assert not result.get('isError'),result
            return json.loads(result['content'][0]['text'])
        def job(operation,params,key,previous=None,success=True,project_id=None):
            owner=project_id or project
            arguments={'project':owner,'operation':operation,'parameters':params,'idempotency_key':key}
            if previous:arguments['source_revision']=previous
            if key=='import':
                spec=file('cli-import.json',json.dumps(params).encode())
                program="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
                command=[sys.executable,'-I','-B','-c',program,str(runtime),'--state',str(state),'submit',owner,operation,'--parameters',str(spec),'--key',key]
                result=subprocess.run(command,capture_output=True,timeout=30);check('CLI import submission exits',result.returncode==0);submitted=json.loads(result.stdout)
            else:submitted=call('submit_job',arguments)
            check(key+' idempotency survives client exit',call('submit_job',arguments)['id']==submitted['id'])
            Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
            check(key+' durable result',actual['state']==('succeeded' if success else 'failed'))
            if not success:check(key+' prior head preserved',store.get_project('local',owner)['head']==previous);return None
            return actual['result_revision']
        asset=store.import_asset('local',project,path)['id'];rev=job('material.import',{'asset':asset},'import')
        rev=job('material.export',{'graph':'Parent','format':'png','depth':8},'maps',rev)
        rev=job('material.edit',{'expected_sha256':hashlib.sha256(data).hexdigest(),'edits':[{'kind':'node.parameter','package':'deps/child.sbs','graph':'Original','node':'3','name':'outputcolor','expected':{'t':'float4','v':[1.,0.,0.,1.]},'value':{'t':'float4','v':[0.,1.,0.,1.]}}]},'edit-child',rev)
        rev=job('material.export',{'graph':'Parent','format':'png','depth':8},'edited-maps',rev)
        exported=root/'durable';store.checkout('local',rev,exported)
        changed=(exported/'native/document.mcraft').read_bytes();profile=document.inspect_bytes(changed)
        check('precise child edit preserves root package',profile['container']['members']['package.sbs']==document.inspect_bytes(data)['container']['members']['package.sbs'])
        check('initial archive retained through child edit',(exported/'native/original.input').read_bytes()==data)
        pixels('edited',exported/'native/document.mcraft',(0,255,0,255))
        imported=store.import_project('local',exported,'Portable archived materials')
        job('material.inspect',{},'portable',imported['revision']['id'],project_id=imported['project']['id'])
        rev=job('material.bundle',{'graph':'Parent'},'bundle',rev)
        exported=root/'durable-bundle';store.checkout('local',rev,exported)
        other=store.create_project('local','Bundle import')['id'];asset=store.import_asset('local',other,exported/'exports/material.mcmat')['id']
        job('material.import',{'asset':asset,'format':'mcmat'},'bundle-import',project_id=other)
        check('all exact input archives preserved',path.read_bytes()==data and deep_path.read_bytes()==deep and fn_path.read_bytes()==functions and texture_path.read_bytes()==textured)
        (root/'evidence.json').write_text(json.dumps({'passed':True,'checks':checks,'native_calls':len(calls),'durable_jobs':len(jobs),'remote_actions':False,'installed_qualification':False},indent=2)+'\n')
        print(json.dumps({'passed':len(checks),'native_calls':len(calls),'durable_jobs':len(jobs)}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:
        document.run=original_run;(root/'calls.json').write_text(json.dumps(calls,indent=2)+'\n');(root/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
