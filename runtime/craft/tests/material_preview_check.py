#!/usr/bin/env python3
"""Bounded CPU preview pixels, scene controls and durable CLI/MCP preservation."""
import copy
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_preview as preview, material_document as document, material_source as source
from studio_runtime.store import Store
from studio_runtime.worker import Worker
from material_source_check import recipe
from material_maps_check import altered
from material_export_codecs_check import bitmap_recipe
from texture_images_check import exr_fixture


def usage_recipe(first='baseColor',second='roughness'):
    tree=recipe();graph=tree['children'][-1]['children'][0];outputs=next(n for n in graph['children'] if n['tag']=='graphOutputs')['children']
    for output,usage in zip(outputs,(first,second)):
        usages=next(n for n in output['children'] if n['tag']=='usages');usages['children'][0]['children'][1]['attributes']['v']=usage
    return source.create({'package.sbs':tree})[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True);engine=args.engine.resolve();checks=[];jobs=[]
    os.environ['PATH']=str(engine.parent)+':/usr/bin:/bin';base={'graph':'Original','view':'3d','width':64,'height':48};original=altered()
    def check(label,ok=True):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def refused(label,action,part=None):
        try:action()
        except ValueError as error:check(label,part is None or part in str(error))
        else:raise AssertionError('accepted '+label)
    def render(label,data,params):
        path=root/(label+'.mcraft');path.write_bytes(data);target=root/label
        report=preview.render(root,path,target,params,engine)
        check(label+' one full-size bounded cook and complete pixels',report['native_calls']==3 and report['full_size_cook'] and report['complete_decoding'] and report['finite_display_samples'])
        check(label+' unchanged source',path.read_bytes()==data and report['source_bytes_unchanged'])
        (root/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        with Image.open(target/'preview.png') as image:rgba=image.convert('RGBA').tobytes()
        return report,rgba
    def fail(label,data,params,part):
        path=root/(label+'.mcraft');path.write_bytes(data);target=root/label
        refused(label,lambda:preview.render(root,path,target,params,engine),part)
        check(label+' no output and immutable source',not target.exists() and path.read_bytes()==data)
    state=root/'store';store=Store(state);runtime=Path(__file__).resolve().parents[1]/'runtime'
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
    def call(name,arguments):
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':arguments}}
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps(request)+'\n').encode(),capture_output=True,timeout=30)
        check('public MCP client exits',result.returncode==0);reply=json.loads(result.stdout)
        if 'error' in reply:raise AssertionError(reply)
        result=reply['result']
        if result.get('isError'):raise ValueError(result['content'][0]['text'])
        return json.loads(result['content'][0]['text'])
    def job(project,operation,params,key,previous=None,success=True,cli=False):
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:arguments['source_revision']=previous['id']
        if cli:
            spec=root/(key+'-request.json');spec.write_text(json.dumps(params));program="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
            result=subprocess.run([sys.executable,'-I','-B','-c',program,str(runtime),'--state',str(state),'submit',project,operation,'--parameters',str(spec),'--key',key,'--source',previous['id']],capture_output=True,timeout=30)
            check('public CLI submit exits',result.returncode==0);submitted=json.loads(result.stdout)
        else:submitted=call('submit_job',arguments)
        check(key+' idempotency after client exit',call('submit_job',arguments)['id']==submitted['id']);Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
        check(key+' durable state',actual['state']==('succeeded' if success else 'failed'))
        if not success:check(key+' prior head preserved',actual['result_revision'] is None and store.get_project('local',project)['head']==previous['id']);return None
        return call('get_revision',{'revision':actual['result_revision']})
    def checkout(label,revision):
        path=root/label;call('export_project',{'revision':revision['id'],'destination':str(path)});return path
    try:
        for output,pixel in [('basecolor',(255,0,0,255)),('roughness',(0,0,0,255))]:
            report,rgba=render('2d-'+output,original,{'graph':'Original','view':'2d','width':73,'height':19,'output':output})
            check('2d '+output+' every exact resized pixel',rgba==bytes(pixel)*(73*19) and report['selection'][0]['width']==32)
        report,rgba=render('alpha-2d',altered('1 0 0 0.5'),{'graph':'Original','view':'2d','width':32,'height':32,'output':'basecolor'})
        check('2d alpha preserved independently',rgba==bytes((255,0,0,128))*1024)
        hashes={}
        for scene in preview.SCENES:
            report,rgba=render('scene-'+scene,original,{**base,'scene':scene});hashes[scene]=report['sha256']
            check(scene+' bounded geometry and spatial shading',0<report['geometry']['triangles']<=500000 and len(set(zip(*(iter(rgba),)*4)))>16 and any(r>g+32 for r,g,_,_ in zip(*(iter(rgba),)*4)))
        check('nine scene outputs are distinct',len(set(hashes.values()))==9)
        report,rgba=render('cold-sphere',original,base);check('cold render byte-repeatable',report['sha256']==hashes['sphere'])
        environments=[]
        for environment in preview.ENVIRONMENTS:
            report,_=render('environment-'+environment,original,{**base,'environment':environment,'show_environment':True});environments.append(report['sha256'])
        check('six environments are distinct',len(set(environments))==6)
        # Fully transparent geometry must agree with a separately computed
        # vignette, supersampling, ACES and sRGB transform at every pixel.
        report,rgba=render('transparent',altered('1 0 0 0'),base);expected=[]
        for y in range(48):
            for x in range(64):
                total=0.
                for sy in range(2):
                    for sx in range(2):
                        px=(x+(sx+.5)/2)/64*2-1;py=1-(y+(sy+.5)/2)/48*2;t=min(1,math.hypot(px,py)*.75)
                        total+=.04+(.012-.04)*t*t*(3-2*t)
                value=total/4;value=(value*(2.51*value+.03))/(value*(2.43*value+.59)+.14)
                value=12.92*value if value<=.0031308 else 1.055*value**(1/2.4)-.055
                gray=int(value*255+.5);expected.extend((gray,gray,gray,255))
        check('transparent full frame matches independent analytic backdrop',all(abs(a-b)<=1 for a,b in zip(rgba,expected)))
        _,opaque=render('ignore-alpha',altered('1 0 0 0'),{**base,'transparency':False});check('explicit transparency control changes render',opaque!=rgba)
        _,alpha=render('alpha-view',altered('1 0 0 0.5'),{**base,'alpha_view':True});center=(24*64+32)*4
        check('alpha view has independent linear half-opacity center',alpha[center:center+3]==bytes((128,128,128)))
        report,_=render('high-quality',original,{**base,'supersample':3,'ao_rays':8,'key_light':2.5,'yaw':-20.,'pitch':40.,'distance':4.,'target':[.1,.2,0.],
                                              'tiling':2.,'exposure':1.,'environment_rotation':30.,'normal_y_flip':True})
        check('quality work counters include transparent surfaces and secondary rays',report['samples']==64*48*9 and report['ray_work']==64*48*9*8*10)
        report,_=render('displaced',original,{**base,'scene':'plane','channels':{'height':'basecolor'},'displacement':.1,'triangles':10000})
        check('displacement obeys triangle budget',report['geometry']['displaced'] and report['geometry']['baseTriangles']<report['geometry']['triangles']<=10000)
        diffuse,_=render('diffuse-alias',usage_recipe(first='diffuse'),base);check('native diffuse alias retained',diffuse['selection'][0]['channel']=='baseColor' and diffuse['sha256']==hashes['sphere'])
        ambiguous=usage_recipe(second='baseColor');fail('ambiguous-channel',ambiguous,base,'ambiguous')
        report,rgba=render('explicit-channel',ambiguous,{**base,'channels':{'baseColor':'basecolor'}});check('explicit mapping resolves duplicate usage',len(report['selection'])==1)
        fail('absent-map',original,{'graph':'Original','view':'2d','width':32,'height':32,'output':'missing'},'absent')
        fail('height-required',original,{**base,'displacement':.1},'height channel')
        fail('base-mesh-limit',original,{**base,'triangles':64},'triangle budget')
        fail('normal-range',altered('2 0 0 1'),{**base,'channels':{'normal':'basecolor'}},'encoded samples')
        extreme=bitmap_recipe(exr_fixture(width=32,height=32,compression=0,sample_size=4,values=(0,0,2e38)),'exr')[0]
        fail('nonfinite-shading',extreme,base,'nonfinite shading')
        fail('displacement-range',extreme,{**base,'channels':{'height':'basecolor'},'displacement':.1},'eight scene radii')
        fail('displacement-sum-range',extreme,{**base,'channels':{'height':'basecolor'},'displacement':1e-40},'working range')
        negative=bitmap_recipe(exr_fixture(width=32,height=32,compression=0,sample_size=4,values=(0,0,-3e38)),'exr')[0]
        fail('2d-transfer-overflow',negative,{'graph':'Original','view':'2d','width':32,'height':32,'output':'basecolor'},'nonfinite')
        unused_alpha=bitmap_recipe(exr_fixture(width=32,height=32,compression=0,sample_size=4,values=(2e38,.5,.5,.5)),'exr')[0]
        report,_=render('normal-unused-alpha',unused_alpha,{**base,'channels':{'normal':'basecolor'}})
        check('normal validation ignores unused alpha',any(row['channel']=='normal' for row in report['selection']))
        report,_=render('height-unused-alpha',unused_alpha,{**base,'scene':'plane','channels':{'height':'basecolor'},'displacement':.1,'triangles':10000})
        check('height validation ignores unused alpha',report['geometry']['displaced'])
        fail('cook-budget',altered(size='13x13'),base,'raster budget')
        for label,params in [('unknown scene',{**base,'scene':'typo'}),('unknown lighting',{**base,'environment':'typo'}),('NaN',{**base,'yaw':float('nan')}),
            ('clamped pitch',{**base,'pitch':90}),('integer bool',{**base,'width':True}),('zero size',{**base,'height':0}),('sample budget',{**base,'width':4096,'height':4096,'supersample':4}),
            ('ray budget',{**base,'width':4096,'height':4096,'supersample':1,'ao_rays':32}),('bad target',{**base,'target':[0,0]}),('unknown channel',{**base,'channels':{'typo':'basecolor'}}),
            ('2d options',{**base,'view':'2d','output':'basecolor','scene':'sphere'}),('3d output',{**base,'output':'basecolor'}),('alpha bool',{**base,'alpha_view':1})]:refused(label,lambda params=params:preview.normalize(params))
        # Native output tampering cannot survive independent validation.
        original_run=document.Engine._run
        def corrupt(self,*arguments):
            reply=original_run(self,*arguments)
            if arguments[0]=='preview':(Path(arguments[-1])/'preview.png').write_bytes(b'broken')
            return reply
        document.Engine._run=corrupt
        try:fail('broken-native-png',original,base,'cannot be decoded')
        finally:document.Engine._run=original_run
        project=call('create_project',{'name':'Editable material previews'})['id'];first=job(project,'material.create',{'documents':{'package.sbs':recipe()}},'create')
        first_bundle=checkout('created',first);origin=(first_bundle/'recipes/origin-material-operation.json').read_bytes()
        second=job(project,'material.preview',base,'preview',first);bundle=checkout('preview',second)
        check('durable preview validated and not visually approved',second['validation']['preview_performed'] and second['validation']['render_qualified'] and not second['validation']['visual_approval'])
        check('public preview agrees with independently exercised native route',hashlib.sha256((bundle/'exports/preview/preview.png').read_bytes()).hexdigest()==hashes['sphere'])
        third=job(project,'material.preview',{'graph':'Original','view':'2d','width':73,'height':19,'output':'basecolor'},'cli-2d',second,cli=True)
        flat=checkout('flat',third);check('public CLI exact 2d pixels',Image.open(flat/'exports/preview/preview.png').convert('RGBA').tobytes()==bytes((255,0,0,255))*(73*19))
        imported=store.import_project('local',bundle,'Portable preview');p=imported['project']['id'];revision=imported['revision']
        edited=job(p,'material.edit',{'expected_sha256':hashlib.sha256(original).hexdigest(),'edits':[{'kind':'node.parameter','package':'package.sbs','graph':'Original','node':'3','name':'outputcolor','expected':{'t':'float4','v':[1.,0.,0.,1.]},'value':{'t':'float4','v':[0.,0.,1.,1.]}}]},'blue',revision)
        blue=job(p,'material.preview',base,'blue-preview',edited);blue_bundle=checkout('blue',blue)
        check('portable edit changes actual preview',(blue_bundle/'exports/preview/preview.png').read_bytes()!=(bundle/'exports/preview/preview.png').read_bytes())
        check('preview revisions retain exact initial source and recipe',(blue_bundle/'native/original.input').read_bytes()==original and (blue_bundle/'recipes/origin-material-operation.json').read_bytes()==origin)
        job(project,'material.preview',{**base,'displacement':.1},'failed-preview',third,success=False)
        result={'passed':True,'checks':checks,'durable_jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),'scenes':list(preview.SCENES),'environments':list(preview.ENVIRONMENTS),
                'public_cli_and_mcp':True,'bounded_cpu_preview':True,'installed_qualification':False,'visual_approval':False,'goal_complete':False,'remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks),'durable_jobs':len(jobs),'succeeded':result['succeeded']}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(root/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
