#!/usr/bin/env python3
"""Actual bounded map delivery, format policies and durable public CLI/MCP jobs."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_maps as maps, material_source as source, material_document as document
from studio_runtime import texture_image_codecs as codecs
from studio_runtime.store import Store
from studio_runtime.worker import Worker
from material_source_check import recipe, bridge
from texture_images_check import exr_table, exr_fixture
from material_export_codecs_check import bitmap_recipe


def altered(color=None,size=None,name=None):
    tree=recipe();graph=tree['children'][-1]['children'][0]
    if color is not None:
        node=next(n for n in graph['children'] if n['tag']=='compNodes')['children'][0]
        node['children'][-1]['children'][0]['children'][1]['children'][0]['children'][2]['children'][0]['attributes']['v']=color
    if size is not None:
        option=next(n for n in graph['children'] if n['tag']=='options')['children'][0]
        next(n for n in option['children'] if n['tag']=='value')['attributes']['v']=size
    if name is not None:
        output=next(n for n in graph['children'] if n['tag']=='graphOutputs')['children'][0]
        output['children'][0]['attributes']['v']=name
    return source.create({'package.sbs':tree})[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);engine=args.engine.resolve()
    os.environ['PATH']=str(engine.parent)+':/usr/bin:/bin';checks=[];jobs=[]
    def check(label,ok=True):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def refused(label,action,contains=None):
        try:action()
        except (ValueError,FileExistsError) as error:check(label,contains is None or contains in str(error))
        else:raise AssertionError('accepted '+label)
    def export(label,data,params):
        path=out/(label+'.mcraft');path.write_bytes(data);target=out/(label+'-maps')
        result=maps.export(out,path,target,params,engine)
        check(label+' exact immutable source',path.read_bytes()==data and result['source_bytes_unchanged'])
        check(label+' one bounded cook and complete decoding',result['native_calls']==3 and result['full_size'] and result['complete_decoding'] and result['usage']['node_visits']==5)
        (out/(label+'.json')).write_text(json.dumps(result,indent=2)+'\n');return result,target
    def bad_export(label,data,params,part):
        path=out/(label+'.mcraft');path.write_bytes(data);target=out/(label+'-maps')
        refused(label,lambda:maps.export(out,path,target,params,engine),part)
        check(label+' no output or source changes',not target.exists() and path.read_bytes()==data)
    def exr_values(path):
        data=path.read_bytes();offset=struct.unpack_from('<Q',data,exr_table(data))[0]
        x,y,lx,ly,packed=struct.unpack_from('<4iI',data,offset);assert (x,y,lx,ly)==(0,0,0,0)
        raw=codecs.exr_block(data[offset+20:offset+20+packed],32*32*12,1)
        return list(struct.unpack('<'+str(len(raw)//4)+'f',raw))
    state=out/'store';store=Store(state);runtime=Path(__file__).resolve().parents[1]/'runtime'
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
    def request(method,params):
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n').encode(),capture_output=True,timeout=30)
        check('public MCP client exits',result.returncode==0);response=json.loads(result.stdout)
        if 'error' in response:raise AssertionError(response)
        return response['result']
    def call(name,arguments):
        result=request('tools/call',{'name':'dope_'+name,'arguments':arguments})
        if result.get('isError'):raise ValueError(result['content'][0]['text'])
        return json.loads(result['content'][0]['text'])
    def job(project,operation,params,key,previous=None,success=True,cli=False):
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:arguments['source_revision']=previous['id']
        if cli:
            spec=out/(key+'-request.json');spec.write_text(json.dumps(params))
            program="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
            command=[sys.executable,'-I','-B','-c',program,str(runtime),'--state',str(state),'submit',project,operation,'--parameters',str(spec),'--key',key,'--source',previous['id']]
            result=subprocess.run(command,capture_output=True,timeout=30);check('public CLI submit exits',result.returncode==0);submitted=json.loads(result.stdout)
        else:submitted=call('submit_job',arguments)
        check(key+' client-independent idempotency',call('submit_job',arguments)['id']==submitted['id'])
        Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
        check(key+' durable state',actual['state']==('succeeded' if success else 'failed'))
        if not success:
            check(key+' prior head preserved',actual['result_revision'] is None and store.get_project('local',project)['head']==previous['id']);return None
        return call('get_revision',{'revision':actual['result_revision']})
    def checkout(label,revision):
        path=out/label;call('export_project',{'revision':revision['id'],'destination':str(path)});return path
    base={'graph':'Original','format':'png','depth':16};original=altered()
    try:
        listed=request('tools/list',{})['tools'];schema=next(t for t in listed if t['name']=='dope_submit_job')
        check('same product MCP offers durable Material export','material.export' in schema['inputSchema']['properties']['operation']['enum'])
        project=call('create_project',{'name':'Material map suite'})['id'];revision=job(project,'material.create',{'documents':{'package.sbs':recipe()}},'create')
        first=checkout('created',revision);initial=(first/'native/original.input').read_bytes();origin=(first/'recipes/origin-material-operation.json').read_bytes()
        expected_first=None
        for extension,depth in [('png',8),('png',16),('jpg',8),('tga',8),('bmp',8),('webp',8),('exr',32),('hdr',32)]:
            label=extension+str(depth);revision=job(project,'material.export',{**base,'format':extension,'depth':depth},label,revision,cli=extension=='tga')
            path=checkout(label,revision);report=json.loads((path/'exports/maps.json').read_text());artifacts={f['path'] for f in revision['files'] if f['path'].startswith('exports/maps/')}
            check(label+' exact public map inventory',artifacts=={'exports/maps/map-4.'+extension,'exports/maps/map-5.'+extension})
            check(label+' bounded full-size native export',revision['validation']['map_export_performed'] and report['complete_decoding'] and report['usage']=={'node_visits':5,'output_texels':5120})
            check(label+' original source and recipe survive',(path/'native/document.mcraft').read_bytes()==original and (path/'native/original.input').read_bytes()==initial and (path/'recipes/origin-material-operation.json').read_bytes()==origin)
            for name,pixel in [('map-4',(255,0,0,255)),('map-5',(0,0,0,255))]:
                file=path/'exports/maps'/(name+'.'+extension)
                if extension not in ('exr','hdr'):
                    with Image.open(file) as image:
                        actual=image.convert('RGBA').tobytes();expected=bytes(pixel)*1024
                        check(label+' all decoded '+name+' pixels',image.size==(32,32) and all(abs(a-b)<=(1 if extension=='jpg' else 0) for a,b in zip(actual,expected)))
                if extension=='exr':
                    expected=([0.]*64+[1.]*32)*32 if name=='map-4' else [0.]*3072
                    check(label+' every float '+name+' sample',exr_values(file)==expected)
            if extension=='png' and depth==16:expected_first={p.name:p.read_bytes() for p in (path/'exports/maps').iterdir()}
        again=job(project,'material.export',base,'repeat',revision);bundle=checkout('repeat',again)
        check('cold export byte-repeatable',{p.name:p.read_bytes() for p in (bundle/'exports/maps').iterdir()}==expected_first)
        imported=store.import_project('local',bundle,'Portable maps');portable=imported['revision'];portable_project=imported['project']['id']
        edited=job(portable_project,'material.edit',{'expected_sha256':hashlib.sha256(original).hexdigest(),'edits':[{'kind':'node.parameter','package':'package.sbs','graph':'Original','node':'3','name':'outputcolor','expected':{'t':'float4','v':[1.,0.,0.,1.]},'value':{'t':'float4','v':[0.,0.,1.,1.]}}]},'portable-blue',portable)
        blue=job(portable_project,'material.export',base,'portable-blue-export',edited);blue_bundle=checkout('portable-blue',blue)
        with Image.open(blue_bundle/'exports/maps/map-4.png') as image:check('portable revision exports exact requested blue',image.convert('RGBA').tobytes()==bytes((0,0,255,255))*1024)
        check('unrequested roughness map unchanged',(blue_bundle/'exports/maps/map-5.png').read_bytes()==expected_first['map-5.png'])
        check('portable edit retains first source',(blue_bundle/'native/original.input').read_bytes()==initial)
        job(project,'material.export',{**base,'outputs':['absent']},'missing-output',again,success=False)
        # Explicit selection removes old maps from the manifest.
        selected=job(project,'material.export',{**base,'outputs':['roughness']},'selection',again);selected_path=checkout('selection',selected)
        check('selection publishes only requested map',sorted(p.name for p in (selected_path/'exports/maps').iterdir())==['map-5.png'])
        # Floating encodings default to linear even for a base-color usage.
        mid=altered('0.25 0.5 0.75 1');profile=document.inspect_bytes(mid);linear=profile['model']['packages']['package.sbs']['graphs'][0]['nodes'][0]['params']['color']['v'][:3]
        result,path=export('linear-exr',mid,{**base,'format':'exr','depth':32,'outputs':['basecolor']})
        expected=([linear[2]]*32+[linear[1]]*32+[linear[0]]*32)*32
        check('EXR preserves every linear float sample',exr_values(path/'map-4.exr')==expected and result['maps'][0]['colorSpace']=='linear')
        result,path=export('raw-png',mid,{**base,'depth':8,'outputs':['basecolor'],'color_spaces':{'basecolor':'raw'}})
        with Image.open(path/'map-4.png') as image:
            expected=bytes([int(v*255+.5) for v in linear]+[255])*1024
            check('explicit raw PNG skips transfer curve',image.convert('RGBA').tobytes()==expected)
        result,path=export('full-size',altered(size='9x8'),base)
        check('full-size export exceeds legacy preview cap',all((row['width'],row['height'])==(512,256) for row in result['maps']) and result['usage']['output_texels']==5*512*256)
        with Image.open(path/'map-4.png') as image:check('full-size exact pixels',image.convert('RGBA').tobytes()==bytes((255,0,0,255))*(512*256))
        alpha=altered('1 0 0 0.5')
        result,path=export('rgba',alpha,base)
        with Image.open(path/'map-4.png') as image:check('PNG preserves nonopaque alpha',image.convert('RGBA').getpixel((0,0))[3] in (127,128))
        for extension in ('jpg','exr','hdr'):
            params={**base,'format':extension,'depth':8 if extension=='jpg' else 32}
            bad_export('alpha-refusal-'+extension,alpha,params,'discard_alpha')
            result,_=export('alpha-approved-'+extension,alpha,{**params,'discard_alpha':True})
            check(extension+' explicit alpha loss recorded',result['maps'][0]['alphaDiscarded'] and not result['maps'][1]['alphaDiscarded'])
        bad_export('raster-budget',altered(size='13x13'),base,'raster budget')
        bad_export('hdr-negative',altered('-0.25 0 0 1'),{**base,'format':'hdr','depth':32},'negative')
        bad_export('hdr-exponent',bitmap_recipe(exr_fixture(width=32,height=32,compression=0,sample_size=4,values=(0,0,2e38)),'exr')[0],{**base,'format':'hdr','depth':32},'exponent')
        bad_export('hdr-underflow',bitmap_recipe(exr_fixture(width=32,height=32,compression=0,sample_size=4,values=(0,0,1e-39)),'exr')[0],{**base,'format':'hdr','depth':32},'exponent')
        bad_export('transfer-overflow',bitmap_recipe(exr_fixture(width=32,height=32,compression=0,sample_size=4,values=(0,0,-3e38)),'exr')[0],
                   {**base,'format':'exr','depth':32,'color_spaces':{'basecolor':'srgb'}},'nonfinite')
        for label,params in [('empty selection',{**base,'outputs':[]}),('duplicate selection',{**base,'outputs':['basecolor']*2}),('TIFF',{**base,'format':'tiff'}),
            ('ignored depth',{**base,'format':'jpg','depth':16}),('boolean depth',{**base,'depth':True}),('unknown option',{**base,'command':'export'}),
            ('bad override',{**base,'color_spaces':{'basecolor':'display-p3'}}),('implicit alpha',{**base,'discard_alpha':1})]:refused(label,lambda params=params:maps.validate(params))
        bad_export('gray-srgb',original,{**base,'color_spaces':{'roughness':'srgb'}},'grayscale')
        bad_export('unselected-override',original,{**base,'outputs':['roughness'],'color_spaces':{'basecolor':'raw'}},'override')
        path=out/'existing.mcraft';path.write_bytes(original);target=out/'existing';target.mkdir();(target/'canary').write_bytes(b'keep')
        refused('existing destination refused',lambda:maps.export(out,path,target,base,engine));check('existing destination preserved',(target/'canary').read_bytes()==b'keep')
        refused('source identifier traversal rejected',lambda:altered(name='../Finish Δ'),'ambiguous path')
        result,path=export('label-metadata',altered(name='Finish Δ'),base)
        check('output labels never become filenames',result['maps'][0]['identifier']=='Finish Δ' and sorted(p.name for p in path.iterdir())==['map-4.png','map-5.png'])
        many=recipe();graph=many['children'][-1]['children'][0]
        outputs=next(n for n in graph['children'] if n['tag']=='graphOutputs')['children']
        nodes=next(n for n in graph['children'] if n['tag']=='compNodes')['children']
        roots=next(n for n in graph['children'] if n['tag']=='root')['children'][0]['children']
        for i in range(255):
            output=copy.deepcopy(outputs[0]);output['children'][0]['attributes']['v']='extra'+str(i);output['children'][1]['attributes']['v']=str(10000+i)
            outputs.append(output);nodes.append(bridge(20000+i,10000+i,3,4));root=copy.deepcopy(roots[0]);root['children'][0]['attributes']['v']=str(10000+i);roots.append(root)
        bad_export('map-count',source.create({'package.sbs':many})[0],base,'map count')
        single=recipe();graph=single['children'][-1]['children'][0]
        for n in graph['children']:
            if n['tag']=='graphOutputs':n['children']=n['children'][:1]
            if n['tag']=='compNodes':n['children']=[n['children'][0],n['children'][3]]
            if n['tag']=='root':n['children'][0]['children']=n['children'][0]['children'][:1]
            if n['tag']=='options':n['children'][0]['children'][1]['attributes']['v']='12x12'
        bad_export('encoded-size',source.create({'package.sbs':single})[0],{**base,'format':'tga','depth':8},'byte budget')
        # Corrupt a completed native output before validation: no public-ready
        # output directory may survive a failed independent decoder.
        original_run=document.Engine._run
        def corrupt(self,*arguments):
            reply=original_run(self,*arguments)
            if arguments[0]=='maps':
                file=Path(arguments[-1])/'map-4.png';file.write_bytes(file.read_bytes()[:30])
            return reply
        document.Engine._run=corrupt
        try:bad_export('truncated-native-map',original,base,'cannot be decoded')
        finally:document.Engine._run=original_run
        result={'passed':True,'checks':checks,'durable_jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),'formats':list(maps.DEPTHS),
                'bounded_public_map_export':True,'public_cli_and_mcp':True,'installed_qualification':False,'preview_qualified':False,'goal_complete':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks),'durable_jobs':len(jobs),'succeeded':result['succeeded']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
