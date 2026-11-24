#!/usr/bin/env python3
"""Real Texture declarative creation, precise edits and durable publication."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import texture, texture_authoring as authoring, texture_document as document, texture_workflow as workflow
from studio_runtime.store import Store
from studio_runtime.worker import Worker


def recipe(mesh='plane'):
    return {'name':'Layered material','mesh':mesh,'resolution':128,'layers':[
        {'name':'Base','sources':{'BaseColor':{'Uniform':[0,0,1]},'Roughness':{'Uniform':[.25,.25,.25]}}},
        {'name':'Finish','sources':{'BaseColor':{'Uniform':[1,0,0]}},'channels':{'BaseColor':{'mode':'Normal','opacity':.5}}}]}


def edit(layer=1, prop='source', expected=None, value=None, channel='Roughness'):
    result={'layer':layer,'property':prop,'expected':expected,'value':value}
    if prop in ('source','blend'):result['channel']=channel
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();root=args.output.resolve();root.mkdir();engine=args.engine.resolve(strict=True)
    os.environ['PATH']=str(engine.parent)+':/usr/bin:/bin';checks=[];started=time.monotonic()
    def check(label,value=True):
        assert value,label
        checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError:checks.append(label)
        else:raise AssertionError('unexpected acceptance: '+label)
    def report(path):return json.loads((path/'exports/inspection.json').read_text())
    def pixels(path,name):
        item=next(item for item in report(path)['maps'] if name in item['file'])
        with Image.open(path/'exports/maps'/item['file']) as image:return image.convert('RGB').tobytes()
    try:
        create=root/'create';create.mkdir();params=recipe();result=texture.execute(create,'texture.create',params)
        before=document.read_native(create/'native/document.tcraft');original=(create/'native/source.tcraft').read_bytes()
        before_report=report(create)
        check('authored layer order produces independent linear compositing oracle',pixels(create,'baseColor')==bytes((188,0,188))*128*128)
        check('creation publishes editable source, map set and recipe', result['validation']['requested_state_verified'] and json.loads((create/'recipes/create.json').read_text())==params)
        check('inspection exposes complete current native fields for edit preconditions',before_report['project']==before['structure']['project'])
        before_maps={item['file']:item['pixel_sha256'] for item in before_report['maps']}
        change=edit(expected={'Uniform':[.25,.25,.25]},value={'Uniform':[.75,.75,.75]})
        texture.execute(create,'texture.edit',{'edits':[change]});after=report(create)
        check('precise roughness revision changes only requested native source slot',after['revision']['unrequested_native_fields_verified'])
        check('roughness pixels agree with independent value oracle',pixels(create,'roughness')==bytes((191,191,191))*128*128)
        check('unrequested material maps retain exact decoded pixels',all(item['pixel_sha256']==before_maps[item['file']] for item in after['maps'] if 'roughness' not in item['file']))
        check('original authored source bytes survive edits', (create/'native/source.tcraft').read_bytes()==original)
        check('creation recipe survives precise revisions',json.loads((create/'recipes/create.json').read_text())==params)
        refused('stale expected native value refused',lambda:texture.execute(create,'texture.edit',{'edits':[change]}))
        check('failed edit leaves current native document unchanged',document.read_native(create/'native/document.tcraft')['source_sha256']==after['native_sha256'])
        rename=edit(prop='name',expected='Base',value='Body finish')
        texture.execute(create,'texture.edit',{'edits':[rename]})
        check('metadata rename verifies every exported map unchanged',len(report(create)['revision']['maps']['unchanged_map_files'])==len(after['maps']))
        high_precision=edit(expected={'Uniform':[.75,.75,.75]},value={'Uniform':[.123456789]*3})
        texture.execute(create,'texture.edit',{'edits':[high_precision]})
        check('native f32 rounding is explicit and limited to requested fields',len(report(create)['revision']['native_float_rounding'])==3)
        color=edit(layer=2,channel='BaseColor',expected={'Uniform':[1.,0.,0.]},value={'Uniform':[0,1,0]})
        projection=edit(layer=2,prop='projection',expected=authoring.UV,value={'Uv':{'scale':[2,2],'rotation':45,'offset':[0,0]}})
        blend=edit(layer=2,prop='blend',channel='BaseColor',expected={'mode':'Normal','opacity':.5},value={'mode':'Normal','opacity':1})
        texture.execute(create,'texture.edit',{'edits':[color,projection,blend]})
        check('source projection and blend revisions preserve other native fields',report(create)['revision']['unrequested_native_fields_verified'])
        check('fully opaque revised green material matches oracle',pixels(create,'baseColor')==bytes((0,255,0))*128*128)
        texture.execute(create,'texture.edit',{'edits':[edit(layer=2,prop='visible',expected=True,value=False)]})
        check('visibility revision restores underlying blue material',pixels(create,'baseColor')==bytes((0,0,255))*128*128)
        missing_source=root/'missing-source';shutil.copytree(create,missing_source)
        (missing_source/'native/source.tcraft').unlink()
        previous=(missing_source/'native/document.tcraft').read_bytes()
        texture.execute(missing_source,'texture.edit',{'edits':[edit(prop='name',expected='Body finish',value='Retained predecessor')]})
        check('a bundle missing provenance starts from the unedited predecessor', (missing_source/'native/source.tcraft').read_bytes()==previous)

        for mesh in ('material_ball','sphere','cube','rounded_cube','cylinder','torus','crate','udim_plane','preview_orb'):
            folder=root/mesh;folder.mkdir();request=recipe(mesh)
            if mesh=='crate':request['layers'].append({'name':'Separate lid','texture_set':1,'sources':{'BaseColor':{'Uniform':[0,1,0]}}})
            texture.execute(folder,'texture.create',request);current=report(folder)
            check(mesh+' native create and cold export preserve requested project',current['creation']['requested_state_verified'] and current['export_pixels_equal'])
            if mesh=='crate':
                texture.execute(folder,'texture.edit',{'edits':[change]});changed=report(folder)['revision']['maps']
                check('separate texture sets retain their complete exported map inventory',changed['affected_texture_sets']==[0] and len(changed['unchanged_map_files'])==10)
            if mesh=='udim_plane':check('builtin UDIM creation preserves both panels',current['project']['texture_sets'][0]['uv_tiles']==[1001,1002] and len(current['maps'])==10)

        pattern={'Procedural':{'pattern':{'kind':'Checker','scale':4,'seed':7,'contrast':1,'balance':0,'invert':False},'low':[1,0,0],'high':[0,0,1]}}
        procedural=root/'procedural';procedural.mkdir();request=recipe();request['layers']=[{'name':'Checker','sources':{'BaseColor':pattern}}]
        texture.execute(procedural,'texture.create',request)
        data=pixels(procedural,'baseColor');check('authored procedural material renders spatial variation',len({data[i:i+3] for i in range(0,len(data),3)})>1)
        projections={
            'Triplanar':{'scale':1,'sharpness':4,'offset':[0,0,0]},
            'Planar':{'scale':1,'axis':2,'offset':[0,0,0]},
            'Spherical':{'scale':1},'Cylindrical':{'scale':1,'axis':1},
            'Decal':{'center':[0,0,0],'normal':[0,1,0],'up':[0,0,1],'size':[2,2],'rotation':0,'offset':[0,0],'depth':1},
        }
        for kind,body in projections.items():
            folder=root/('projection-'+kind);folder.mkdir();request=recipe();request['layers']=[{'name':kind,'sources':{'BaseColor':pattern},'projection':{kind:body}}]
            texture.execute(folder,'texture.create',request)
            check(kind+' authored projection retains typed axes and native float fields',report(folder)['creation']['requested_state_verified'])
        all_channels=root/'all-channels';all_channels.mkdir();request=recipe();request['layers']=[{'name':'All channels','sources':{name:{'Uniform':[.25,.5,.75]} for name in authoring.structure.CHANNELS}}]
        texture.execute(all_channels,'texture.create',request)
        check('all twenty-one channel schemas survive authored native roundtrip',len(report(all_channels)['project']['texture_sets'][0]['channels'])==21)

        bad=[]
        for label,mutate in [
            ('unknown field',lambda p:p.update(command='serve')),
            ('invalid source kind',lambda p:p['layers'][0]['sources'].update(BaseColor={'Executable':{'path':'bad'}})),
            ('invalid procedural seed',lambda p:p['layers'][0]['sources'].update(BaseColor={'Procedural':{**pattern['Procedural'],'pattern':{**pattern['Procedural']['pattern'],'seed':True}}})),
            ('nested vector',lambda p:p['layers'][0]['sources'].update(BaseColor={'Uniform':[[0],0,1]})),
            ('boolean uniform',lambda p:p['layers'][0]['sources'].update(BaseColor={'Uniform':[True,0,1]})),
            ('oversized layer count',lambda p:p.update(layers=p['layers']*65)),
            ('unsupported resource creation',lambda p:p['layers'][0]['sources'].update(BaseColor={'Image':{'name':'absent.png'}})),
        ]:
            request=recipe();mutate(request);bad.append((label,request))
        for label,request in bad:
            with patch.object(workflow,'Engine',side_effect=AssertionError('engine launched before refusal')):
                refused(label+' refused before native launch',lambda:authoring.create(root/('bad-'+str(len(checks))),request,engine))
        refused('duplicate edit target refused',lambda:authoring.validate_edits([change,change]))
        refused('arbitrary edit path refused',lambda:authoring.validate_edits([{**change,'path':'/tmp/escape'}]))
        refused('boolean layer id refused',lambda:authoring.validate_edits([{**change,'layer':True}]))
        refused('f32 check refuses nonnumeric repair',lambda:authoring.native_float_equivalence({'x':1.},{'x':True}))
        refused('f32 check refuses changed adjacent value',lambda:authoring.native_float_equivalence(1.,1.0001))
        refused('f32 check refuses added defaults',lambda:authoring.native_float_equivalence({'x':1.},{'x':1.,'repair':0}))

        state=root/'store';store=Store(state)
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        def call(name,arguments):
            message={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':arguments}}
            child=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).resolve().parents[1]/'runtime'),str(state)],input=(json.dumps(message)+'\n').encode(),capture_output=True,timeout=20)
            assert child.returncode==0,child.stderr
            response=json.loads(child.stdout);assert 'error' not in response,response
            result=response['result'];assert not result.get('isError'),result
            return json.loads(result['content'][0]['text'])
        project=call('create_project',{'name':'Authored Texture'})['id']
        def job(operation,parameters,key,revision=None,expected='succeeded'):
            args={'project':project,'operation':operation,'parameters':parameters,'idempotency_key':key}
            if revision:args['source_revision']=revision
            first=call('submit_job',args);assert call('submit_job',args)['id']==first['id']
            Worker(store).run_one();result=call('get_job',{'job':first['id']});assert result['state']==expected,result
            return call('get_revision',{'revision':result['result_revision']}) if result['result_revision'] else result
        first=job('texture.create',recipe(),'create');second=job('texture.edit',{'edits':[change]},'edit',first['id'])
        check('durable creation and revision survive disconnected MCP clients',second['parent']==first['id'])
        failed=job('texture.edit',{'edits':[change]},'stale',second['id'],expected='failed')
        check('failed edit precondition publishes no revision or changed head',failed['result_revision'] is None and store.get_project('local',project)['head']==second['id'])
        checkout=root/'checkout';call('export_project',{'revision':second['id'],'destination':str(checkout)})
        check('durable revision preserves original source and authoring recipe',json.loads((checkout/'recipes/create.json').read_text())==recipe() and report(checkout)['revision']['unrequested_native_fields_verified'])
        check('first durable revision remains immutable',call('get_revision',{'revision':first['id']})==first)
        imported=store.import_project('local',checkout,'Portable authored texture')
        request=store.submit('local',imported['project']['id'],'texture.inspect',{},'cold',imported['revision']['id']);Worker(store).run_one()
        check('authored portable revision reopens through a new native job',store.get_job('local',request['id'])['state']=='succeeded')
        result={'passed':True,'checks':len(checks),'cases':checks,'seconds':round(time.monotonic()-started,3),'durable_jobs':4,'installed_qualification':False,'goal_complete':False}
        (root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='cases'}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'passed':False,'cases':checks,'error':str(error)},indent=2)+'\n');raise


if __name__=='__main__':main()
