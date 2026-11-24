#!/usr/bin/env python3
"""Original recipe graphs, independent full-image math and portable precise edits."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_recipes as recipes, material_source as source, material_maps as maps, material_document as document, material_preview as preview, material
from studio_runtime.store import Store
from studio_runtime.worker import Worker


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
    images={key:bytearray() for key in recipes.OUTPUTS}
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True);engine=args.engine.resolve();checks=[];jobs=[];timings=[]
    os.environ['PATH']=str(engine.parent)+':/usr/bin:/bin'
    def check(label,ok=True):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def refuse(label,action):
        try:action()
        except ValueError:check(label)
        else:raise AssertionError('accepted '+label)
    def export(label,path,name,controls,size):
        target=root/(label+'-maps');start=time.monotonic()
        report=maps.export(root,path,target,{'graph':'Surface','format':'png','depth':8},engine)
        timings.append({'label':label,'resolution':size,'seconds':time.monotonic()-start,'scope':'source admission, native snapshot, bounded cook, six PNG8 maps and complete decoding'})
        check(label+' single bounded cook',report['native_calls']==3 and report['full_size'] and report['finite_outputs'])
        expected=oracle(name,controls,size);actual={}
        for item in report['maps']:
            with Image.open(target/item['file']) as image:actual[item['usage']]=image.convert('RGBA').tobytes()
            error=max(abs(a-b) for a,b in zip(expected[item['usage']],actual[item['usage']]))
            check(label+' independent every pixel '+item['usage'],len(actual[item['usage']])==size*size*4 and error<=1)
        check(label+' all six channels',set(actual)==set(recipes.OUTPUTS))
        (root/(label+'-maps.json')).write_text(json.dumps(report,indent=2)+'\n')
        return actual,report
    state=root/'store';store=Store(state);runtime=Path(__file__).resolve().parents[1]/'runtime'
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
    def call(name,arguments):
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':arguments}}
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps(request)+'\n').encode(),capture_output=True,timeout=30)
        check('MCP process exits',result.returncode==0);reply=json.loads(result.stdout)
        if 'error' in reply:raise AssertionError(reply)
        value=reply['result']
        if value.get('isError'):raise ValueError(value['content'][0]['text'])
        return json.loads(value['content'][0]['text'])
    def job(project,operation,params,key,previous=None,cli=False):
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:arguments['source_revision']=previous['id']
        if cli:
            specification=root/(key+'-parameters.json');specification.write_text(json.dumps(params))
            program="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
            result=subprocess.run([sys.executable,'-I','-B','-c',program,str(runtime),'--state',str(state),'submit',project,operation,'--parameters',str(specification),'--key',key],capture_output=True,timeout=30)
            check('public CLI recipe submission exits',result.returncode==0);submitted=json.loads(result.stdout)
        else:submitted=call('submit_job',arguments)
        check(key+' idempotent after disconnect',call('submit_job',arguments)['id']==submitted['id'])
        Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
        check(key+' succeeds',actual['state']=='succeeded')
        return call('get_revision',{'revision':actual['result_revision']})
    def checkout(label,revision):
        path=root/label;call('export_project',{'revision':revision['id'],'destination':str(path)});return path
    try:
        catalog=call('capabilities',{})['applications']['material']['production_recipes']
        check('catalog discoverable through product MCP',catalog==recipes.catalog() and {v['id'] for v in catalog}==set(recipes.RECIPES))
        for name in recipes.RECIPES:
            params={'recipe':name,'version':1,'resolution':128,'controls':{'repeat':4.,'relief':.35}}
            documents,production=recipes.compile_recipe(params);data,_=source.create(documents);path=root/(name+'.mcraft');path.write_bytes(data)
            check(name+' deterministic source and recipe hash',recipes.compile_recipe(params)==(documents,production) and source.create(documents)[0]==data)
            profile=document.read_native(path);graph=profile['model']['packages']['package.sbs']['graphs'][0]
            check(name+' exposed values match recipe controls',{e['id']:e['default']['v'] for e in graph['exposed']}==production['controls'])
            check(name+' source has actual pixel graphs and no resources',sum(n['def']=='pixel_processor' for n in graph['nodes'])==4 and not profile['resources']['resources'])
            actual,report=export(name,path,name,production['controls'],128)
            again,_=export(name+'-cold',path,name,production['controls'],128);check(name+' exact cold pixels',actual==again)
            check(name+' seamless mirrored boundary heights',all(actual['height'][(y*128)*4:(y*128)*4+4]==actual['height'][(y*128+127)*4:(y*128+127)*4+4] for y in range(128)))
            render=preview.render(root,path,root/(name+'-preview'),{'graph':'Surface','view':'3d','width':256,'height':256,'scene':'plane','displacement':.08},engine)
            check(name+' real six-channel displaced preview',len(render['selection'])==6 and render['geometry']['displaced'] and render['finite_display_samples'])
            project=call('create_project',{'name':name})['id'];created=job(project,'material.create',params,name+'-create',cli=name=='ribbed_metal');bundle=checkout(name+'-created',created)
            check(name+' durable original matches compiled source',(bundle/'native/original.input').read_bytes()==data)
            retained=(bundle/'recipes/material-production.json').read_bytes();record=json.loads(retained)
            check(name+' production provenance',{**production,'source_sha256':hashlib.sha256(data).hexdigest()}==record)
            imported=store.import_project('local',bundle,'Portable '+name);p=imported['project']['id'];rev=imported['revision']
            edit={'expected_sha256':hashlib.sha256(data).hexdigest(),'edits':[{'kind':'input.default','package':'package.sbs','graph':'Surface','name':'color_r','expected':{'t':'float','v':production['controls']['color_r']},'value':{'t':'float','v':.75}}]}
            edited=job(p,'material.edit',edit,name+'-recolor',rev);after=checkout(name+'-edited',edited)
            controls={**production['controls'],'color_r':.75};recolored,_=export(name+'-recolored',after/'native/document.mcraft',name,controls,128)
            check(name+' recolor changes baseColor only',recolored['baseColor']!=actual['baseColor'] and all(recolored[k]==actual[k] for k in recipes.OUTPUTS if k!='baseColor'))
            check(name+' immutable recipe and source survive portable revision',(after/'recipes/material-production.json').read_bytes()==retained and (after/'native/original.input').read_bytes()==data)
            rendered=job(p,'material.preview',{'graph':'Surface','view':'3d','width':64,'height':64},name+'-durable-preview',edited)
            check(name+' preview has independent qualification',rendered['validation']['preview_performed'] and not rendered['validation']['visual_approval'])
        for name,spec in recipes.RECIPES.items():
            for endpoint in (1,2):
                request={'recipe':name,'version':1,'resolution':1024,'controls':{key:values[endpoint] for key,values in spec['controls'].items()}}
                normalized=recipes.normalize(request)
                check(name+' normalized endpoint '+str(endpoint)+' can be reused exactly',recipes.normalize(normalized)==normalized)
        base={'recipe':'ceramic_tiles','version':1}
        for label,params in [('unknown recipe',{**base,'recipe':'other'}),('version drift',{**base,'version':2}),('boolean version',{**base,'version':True}),('nonpower resolution',{**base,'resolution':255}),('oversized resolution',{**base,'resolution':2048}),('mixed authored documents',{**base,'documents':{}}),('assets forbidden',{**base,'assets':{}}),('unknown control',{**base,'controls':{'missing':1}}),('NaN',{**base,'controls':{'roughness':float('nan')}}),('huge integer',{**base,'controls':{'repeat':10**1000}}),('nonseamless frequency',{**base,'controls':{'repeat':3.5}}),('zero bevel',{**base,'controls':{'bevel':0}}),('undersampled pattern',{**base,'resolution':32,'controls':{'repeat':64}}),('boolean control',{**base,'controls':{'relief':True}})]:
            refuse(label,lambda params=params:material.validate('material.create',params,None))
        # Recipe expansion is creation only. It cannot replace an existing revision.
        refuse('recipe does not overwrite existing project',lambda:material.validate('material.create',base,'existing'))
        for name in recipes.RECIPES:
            params={'recipe':name,'version':1,'resolution':256};docs,record=recipes.compile_recipe(params);data,_=source.create(docs);path=root/(name+'-default.mcraft');path.write_bytes(data)
            export(name+'-default',path,name,record['controls'],256)
            maximum={'recipe':name,'version':1,'resolution':1024}
            docs,record=recipes.compile_recipe(maximum);data,_=source.create(docs);path=root/(name+'-maximum.mcraft');path.write_bytes(data)
            export(name+'-maximum',path,name,record['controls'],1024)
        result={'passed':True,'checks':checks,'durable_jobs':len(jobs),'timings':timings,'recipes':list(recipes.RECIPES),'native_engine_unchanged':True,'public_cli':True,'public_mcp':True,'visual_approval':False,'installed_qualification':False,'remote_actions':False,'goal_complete':False}
        (root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks),'durable_jobs':len(jobs),'timings':timings}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(root/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
