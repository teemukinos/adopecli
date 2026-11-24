#!/usr/bin/env python3
"""Actual CPU Texture preview/bake, retained maps and durable job qualification."""
import argparse
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from unittest.mock import patch

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import texture, texture_compute as compute, texture_document as document
from studio_runtime import texture_authoring as authoring, texture_project as settings, texture_workflow as workflow
from studio_runtime.store import Store
from studio_runtime.worker import Worker


def scene(mesh='plane'):
    return {'name':'CPU material','mesh':mesh,'resolution':128,'layers':[{'name':'Blue','sources':{'BaseColor':{'Uniform':[0,0,1]}}}]}


def bake_request(**overrides):
    return {'texture_sets':[0],'resolution':16,'maps':['normal','ambientOcclusion'],'rays':1,'use_low_as_high':True,**overrides}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',required=True,type=Path);parser.add_argument('--fixtures',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();root=args.output.resolve();root.mkdir();engine=args.engine.resolve(strict=True)
    os.environ['PATH']=str(engine.parent)+':/usr/bin:/bin';checks=[];started=time.monotonic()
    def check(label,value=True):
        assert value,label
        checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError:checks.append(label)
        else:raise AssertionError('unexpected admission: '+label)
    def report(path):return json.loads((path/'exports/inspection.json').read_text())
    try:
        current=root/'material';current.mkdir();texture.execute(current,'texture.create',scene())
        source=(current/'native/source.tcraft').read_bytes();original=document.read_native(current/'native/document.tcraft')
        request={'width':64,'height':64,'samples':2,'bounces':2,'yaw':20,'pitch':20}
        texture.execute(current,'texture.render',{'render':request});preview=report(current)['preview']
        check('CPU preview reproduces encoded and decoded pixels after cold reopen',preview['backend']=='CPU' and preview['cold_preview_equal'])
        with Image.open(current/'exports/preview.png') as image:
            colors=image.convert('RGB').get_flattened_data()
            check('actual preview contains directed blue material and spatial variation',len(set(colors))>1 and any(b>r+30 and b>g+30 for r,g,b in colors))
        check('preview leaves all native fields and payloads unchanged',document.check_preservation(original,document.read_native(current/'native/document.tcraft'))['embedded_bytes_preserved'])
        check('preview reports bounded counters separately from measured command time',preview['budget']=={'pixels':4096,'sample_bounce_work':16384} and len(preview['native_command_seconds'])==2)
        cameras=copy.deepcopy(original['structure']['project']);cameras['cameras']=[{**settings.CAMERA_DEFAULT,'name':'Inspection','yaw':.5,'pitch':.25}]
        camera_source=root/'camera.tcraft';authoring.write_project(camera_source,original['members'],cameras)
        _,saved=compute.render(root/'saved-camera',camera_source,{**request,'camera':'Inspection'},engine)
        check('explicit saved camera renders without changing the stored camera',saved['source_bytes_unchanged'] and saved['cold_preview_equal'])
        with patch.object(workflow,'Engine',side_effect=AssertionError('engine launched before camera refusal')):
            refused('absent saved camera refused before native launch',lambda:compute.render(root/'absent-camera',camera_source,{**request,'camera':'Missing'},engine))
        for key,value in [('width',15),('height',4097),('samples',0),('samples',True),('bounces',33),('pitch',90),('yaw',float('nan')),('cpu',False)]:
            refused('preview rejects '+key+'='+repr(value),lambda key=key,value=value:compute.validate_render({**request,key:value}))
        refused('preview aggregate sample-bounce budget enforced',lambda:compute.validate_render({'width':2048,'height':2048,'samples':256,'bounces':32}))

        texture.execute(current,'texture.bake',{'bake':bake_request()});baked=document.read_native(current/'native/document.tcraft');proof=report(current)['bake']
        check('actual bake agrees with exact payload allocation plan',proof['budget']['output_bytes']==4144 and proof['budget']['nominal_ray_work']==512)
        for name,expected in [('normal',(.5,.5,1.)),('ambientOcclusion',(1.,))]:
            data=baked['members']['baked/0_'+name+'.bin'];values=list(struct.unpack('<'+'f'*((len(data)-24)//4),data[24:]))
            check(name+' matches independent plane oracle',all(abs(value-expected[i%len(expected)])<1e-5 for i,value in enumerate(values)))
        check('bake is explicitly CPU and repeatable before cold native reopen',proof['backend']=='CPU' and proof['repeated_bake_equal'] and proof['native_cold_reopen'])
        old_normal=baked['members']['baked/0_normal.bin']
        texture.execute(current,'texture.bake',{'bake':bake_request(maps=['ambientOcclusion'])})
        check('partial rebake preserves unrequested native normal map bytes',document.read_native(current/'native/document.tcraft')['members']['baked/0_normal.bin']==old_normal)
        unchanged=document.read_native(current/'native/document.tcraft')['source_bytes']
        refused('resizing refuses dropping an unselected existing map',lambda:texture.execute(current,'texture.bake',{'bake':bake_request(resolution=32,maps=['ambientOcclusion'])}))
        check('refused resize leaves current native artifact unchanged',(current/'native/document.tcraft').read_bytes()==unchanged)
        texture.execute(current,'texture.bake',{'bake':bake_request(resolution=32)})
        check('explicit complete map resize retains native fields and new dimensions',all(item['width']==32 for item in report(current)['bake']['maps'].values()))
        texture.execute(current,'texture.bake',{'bake':bake_request(resolution=32,maps=list(compute.MAPS))})
        check('all ten native map types pass finite payload and repeatability checks',len(report(current)['bake']['maps'])==10)
        check('original source and creation recipe survive render and multiple bakes',(current/'native/source.tcraft').read_bytes()==source and json.loads((current/'recipes/create.json').read_text())==scene())

        for label,mesh,selection in [('crate','crate',[0,1]),('udim','udim_plane',[0])]:
            target=root/label;target.mkdir();texture.execute(target,'texture.create',scene(mesh))
            texture.execute(target,'texture.bake',{'bake':bake_request(texture_sets=selection,antialiasing=2)})
            proof=report(target)['bake'];check(label+' selected sets bake on CPU with squared antialiasing',proof['budget']['samples']==2048)
            if label=='udim':
                before=document.read_native(target/'native/document.tcraft');p=copy.deepcopy(before['structure']['project']);p['texture_sets'][0]['bake_excluded_tiles']=[1002]
                changed=root/'excluded.tcraft';authoring.write_project(changed,before['members'],p)
                path,partial=compute.bake(root/'excluded-bake',changed,bake_request(maps=['normal']),engine)
                check('excluded tile bytes and unrequested AO map remain unchanged',partial['excluded_map_tiles_verified']==1 and document.read_native(path)['members']['baked/0_ambientOcclusion.bin']==before['members']['baked/0_ambientOcclusion.bin'])
                with patch.object(workflow,'Engine',side_effect=AssertionError('engine launched before excluded resize refusal')):
                    refused('excluded tile resize refused before native launch',lambda:compute.bake(root/'excluded-resize',changed,bake_request(resolution=32),engine))
        high_source=root/'high-poly.tcraft';high_source.write_bytes((args.fixtures/'texture-mesh-check-5/bake-meshes-cold.tcraft').read_bytes())
        _,high=compute.bake(root/'high-bake',high_source,bake_request(use_low_as_high=False),engine)
        check('admitted high-poly and cage inventory supports real CPU bake',high['unrequested_embedded_bytes_verified'] and high['repeated_bake_equal'])
        for key,value in [('texture_sets',[]),('texture_sets',[0,0]),('texture_sets',[True]),('maps',[]),('maps',['normal','normal']),('maps',['unknown']),('rays',0),('resolution',17),('antialiasing',3),('use_low_as_high',1),('command','serve')]:
            refused('bake rejects '+key+'='+repr(value),lambda key=key,value=value:compute.validate_bake(bake_request(**{key:value})))
        with patch.object(workflow,'Engine',side_effect=AssertionError('engine launched before bake admission')):
            refused('bake budget refused before native launch',lambda:compute.bake(root/'huge',current/'native/document.tcraft',bake_request(resolution=8192,rays=256),engine))
            refused('missing high-poly refuses implicit fallback to low',lambda:compute.bake(root/'missing-high',current/'native/document.tcraft',bake_request(use_low_as_high=False),engine))

        state=root/'store';store=Store(state)
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        def call(name,arguments):
            message={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':arguments}}
            child=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).resolve().parents[1]/'runtime'),str(state)],input=(json.dumps(message)+'\n').encode(),capture_output=True,timeout=20)
            assert child.returncode==0,child.stderr
            response=json.loads(child.stdout);assert 'error' not in response,response
            result=response['result'];assert not result.get('isError'),result
            return json.loads(result['content'][0]['text'])
        project=call('create_project',{'name':'Durable CPU Texture'})['id']
        def job(operation,parameters,key,revision=None):
            arguments={'project':project,'operation':operation,'parameters':parameters,'idempotency_key':key}
            if revision:arguments['source_revision']=revision
            first=call('submit_job',arguments);assert call('submit_job',arguments)['id']==first['id']
            Worker(store).run_one();result=call('get_job',{'job':first['id']});assert result['state']=='succeeded',result
            return call('get_revision',{'revision':result['result_revision']})
        first=job('texture.create',scene(),'create');rendered=job('texture.render',{'render':request},'render',first['id'])
        result=job('texture.bake',{'bake':bake_request()},'bake',rendered['id'])
        check('fresh MCP clients direct durable CPU preview and bake jobs',result['parent']==rendered['id'])
        check('pre-bake durable revisions remain immutable',call('get_revision',{'revision':first['id']})==first)
        checkout=root/'checkout';call('export_project',{'revision':result['id'],'destination':str(checkout)})
        imported=store.import_project('local',checkout,'Portable baked material')
        last=store.submit('local',imported['project']['id'],'texture.inspect',{},'cold',imported['revision']['id']);Worker(store).run_one()
        check('portable baked project retains finite maps through native reopening',store.get_job('local',last['id'])['state']=='succeeded')
        evidence={'passed':True,'checks':len(checks),'cases':checks,'seconds':round(time.monotonic()-started,3),'durable_jobs':4,'installed_qualification':False,'goal_complete':False}
        (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({k:v for k,v in evidence.items() if k!='cases'}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'passed':False,'cases':checks,'error':str(error)},indent=2)+'\n');raise


if __name__=='__main__':main()
