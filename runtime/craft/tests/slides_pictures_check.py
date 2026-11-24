#!/usr/bin/env python3
"""Exercise owned raster pictures through real native code and durable Slides jobs.

Use a staged distribution fixture with current runtime, Slides and PDF components.
Fixtures are original programmatic color fields; no remote content or GUI is used.
"""
import argparse
import copy
import hashlib
import io
import json
import os
import random
from pathlib import Path
import subprocess
import sys
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--predecessor',required=True,type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir();resources=args.resources.resolve()
    sys.path.insert(0,str(resources/'runtime'))
    from studio_runtime import slides,slides_pictures as pictures,slides_revision as revision,slides_project as project
    from studio_runtime import slides_engine,write_exports,write_binding
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    os.environ['PATH']='/usr/bin:/bin';store=Store(out/'state');checks=[];refusals=[];jobs=[]
    sha=lambda data:hashlib.sha256(data).hexdigest()
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def call(name,params):
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(resources/'runtime'),str(out/'state')],
            input=(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':params}})+'\n').encode(),capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr
        response=json.loads(result.stdout);assert 'error' not in response,response
        value=response['result']
        if value.get('isError'):raise ValueError(value['content'][0]['text'])
        return json.loads(value['content'][0]['text'])
    def job(owner,operation,params,previous=None,success=True):
        request={'project':owner,'operation':operation,'parameters':params,'idempotency_key':'raster-'+str(len(jobs))}
        if previous:request['source_revision']=previous['id']
        submitted=call('submit_job',request);assert call('submit_job',request)['id']==submitted['id']
        Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
        assert actual['state']==('succeeded' if success else 'failed'),actual
        if not success:
            assert actual['result_revision'] is None
            return actual
        return call('get_revision',{'revision':actual['result_revision']})
    def checkout(label,rev):
        path=out/label;call('export_project',{'revision':rev['id'],'destination':str(path)});return path
    def image_bytes(kind='PNG',blue=False):
        image=Image.new('RGBA',(64,32));pixels=[]
        for y in range(32):
            for x in range(64):
                color=(37,91,207) if blue else (231,65,35) if x<32 else (43,154,110)
                pixels.append((*color,255 if y<24 else 128 if y<28 else 0))
        image.putdata(pixels);buffer=io.BytesIO()
        if kind=='JPEG':image=image.convert('RGB')
        image.save(buffer,format=kind);return buffer.getvalue()
    def supplied(data,kind='png'):return {'name':'Owned picture.'+kind,'contentType':'image/'+kind,'dataHex':data.hex()}
    def pixel(path,xy,wanted):
        with Image.open(path) as image:actual=image.convert('RGB').getpixel(xy)
        assert max(abs(a-b) for a,b in zip(actual,wanted))<=2,(path,xy,actual,wanted)
    try:
        native_root=out/'native-probes';native_root.mkdir();native=slides_engine.Engine(root=native_root,seconds=600,**slides.binding.resolve())
        original=image_bytes();jpeg=image_bytes('JPEG');blue=image_bytes(blue=True)
        for label,data,kind in [('rgba',original,'png'),('jpeg',jpeg,'jpeg'),('replacement',blue,'png')]:
            path=native_root/label;path.write_bytes(data);item={**supplied(data,kind),'id':1,'link':None}
            packets=[]
            for index in range(2):
                target=native_root/(label+'-'+str(index)+'.pixels');native._run('picture',path,target,limit=8192);packets.append(target.read_bytes())
            checked=pictures.compare(packets[0],item)
            check(label+' independently decoded pixels and repeat packet',checked['decoder_agreement'] and packets[0]==packets[1] and path.read_bytes()==data)
            if label=='rgba':
                forged=bytearray(packets[0]);forged[-4]^=255
                refused('changed lossless native pixel',lambda:pictures.compare(bytes(forged),item))
                refused('trailing native payload',lambda:pictures.compare(packets[0]+b'0',item))
        recipe={'recipe':'production_proposal','version':1,'title':'Picture study','sections':[{'heading':'Owned assets','paragraphs':['Exact bytes. Editable placement.']} ]}
        compiled=slides.recipes.compile_recipe(recipe);model=compiled['document'];model['slides']=model['slides'][:1]
        owner=call('create_project',{'name':'Editable picture study'})['id'];created=job(owner,'slides.create',{'document':model})
        first=checkout('initial',created);initial=(first/'native/project.dobeslides').read_bytes()
        insert={'kind':'picture.insert','path':'/slides/0','expected':sha(revision.encoded(model['slides'][0])),
                'value':{'image':supplied(original),'transform':{'x':400.0,'y':180.0,'w':256.0,'h':128.0}}}
        revised=job(owner,'slides.edit',{'expected_sha256':sha(initial),'edits':[insert]},created)
        added=checkout('added',revised);portable=(added/'native/project.dobeslides').read_bytes();with_image=json.loads((added/'native/document.json').read_bytes())
        index=len(with_image['slides'][0]['shapes'])-1;shape_path='/slides/0/shapes/'+str(index)
        shape=revision.locate(with_image,shape_path);media=with_image['media'][0]
        check('insert retains original source, complete native model and owned image',
              (added/'native/original.json').read_bytes()==(first/'native/original.json').read_bytes()
              and bytes.fromhex(media['dataHex'])==original and revised['validation']['native_model_equal'])
        png=job(owner,'slides.export',{'format':'png','slides':[1]},revised);png_folder=checkout('png',png)
        pixel(png_folder/'exports/delivery/slide-001.png',(432,196),(231,65,35))
        pixel(png_folder/'exports/delivery/slide-001.png',(624,196),(43,154,110))
        delivery=json.loads((png_folder/'exports/delivery/delivery.json').read_bytes())
        check('PNG contains both picture regions with exact native decoder evidence',delivery['pictures'][0]['source_sha256']==sha(original))
        pdf=job(owner,'slides.export',{'format':'pdf'},png);pdf_folder=checkout('pdf',pdf)
        reader_root=out/'pdf-reader';reader_root.mkdir();reader_native=slides_engine.Engine(root=reader_root,**slides.binding.resolve())
        pdf_path=reader_root/'presentation.pdf';pdf_path.write_bytes((pdf_folder/'exports/delivery/presentation.pdf').read_bytes())
        with write_exports.PDFReader(reader_root,write_binding.resolve_pdf()['executable'],reader_native) as reader:
            document,_=reader.open(pdf_path);preview=reader_root/'preview.png';reader.render(document,1,preview)
        pixel(preview,(432,196),(231,65,35));pixel(preview,(624,196),(43,154,110))
        check('independent PDF raster contains both picture regions',True)
        crop={'kind':'picture.crop','path':shape_path,'expected':[0.0]*4,'value':[.5,0.0,0.0,0.0]}
        cropped=job(owner,'slides.edit',{'expected_sha256':sha(portable),'edits':[crop]},pdf);cropped_folder=checkout('cropped',cropped)
        crop_bytes=(cropped_folder/'native/project.dobeslides').read_bytes()
        crop_export=job(owner,'slides.export',{'format':'png'},cropped);crop_png=checkout('crop-png',crop_export)
        pixel(crop_png/'exports/delivery/slide-001.png',(432,196),(43,154,110))
        check('precise crop changes actual exported region without replacing source image',project.inspect_bytes(crop_bytes)['current']['document']['media']==with_image['media'])
        replacement={'kind':'picture.replace','path':shape_path,'expected':{'media':media['id'],'sha256':sha(original)},'value':supplied(blue)}
        replaced=job(owner,'slides.edit',{'expected_sha256':sha(crop_bytes),'edits':[replacement]},crop_export)
        replaced_folder=checkout('replaced',replaced);replaced_bytes=(replaced_folder/'native/project.dobeslides').read_bytes()
        current=project.inspect_bytes(replaced_bytes)['current']['document'];picture=revision.locate(current,shape_path)
        check('replacement changes only selected reference and retains prior media',current['media'][0]==media and len(current['media'])==2
              and picture['kind']['fill']['crop']==[.5,0.0,0.0,0.0] and bytes.fromhex(current['media'][1]['dataHex'])==blue)
        move={'kind':'shape.transform','path':shape_path,'expected':picture['xfrm'],'value':{**picture['xfrm'],'x':480.0,'w':192.0}}
        moved=job(owner,'slides.edit',{'expected_sha256':sha(replaced_bytes),'edits':[move]},replaced)
        moved_folder=checkout('moved',moved);moved_bytes=(moved_folder/'native/project.dobeslides').read_bytes()
        recipient=call('create_project',{'name':'Transferred editable images'})['id'];input_path=out/'transfer.dobeslides';input_path.write_bytes(moved_bytes)
        asset=store.import_asset('local',recipient,input_path)['id'];imported=job(recipient,'slides.import',{'asset':asset,'format':'dobeslides'})
        output=job(recipient,'slides.export',{'format':'png'},imported);returned=checkout('returned',output)
        pixel(returned/'exports/delivery/slide-001.png',(512,196),(37,91,207))
        check('portable transfer replays image insertion, crop, replacement and placement exactly',(returned/'native/project.dobeslides').read_bytes()==moved_bytes)
        head=store.get_project('local',recipient)['head'];job(recipient,'slides.edit',{'expected_sha256':sha(moved_bytes),'edits':[replacement]},output,False)
        check('stale image identity publishes no revision',store.get_project('local',recipient)['head']==head)
        model_bytes=revision.encoded(with_image)
        for label,mutate in [
            ('external media',lambda d:d['media'][0].update(link='https://example.invalid/image.png')),
            ('wrong MIME',lambda d:d['media'][0].update(contentType='image/jpeg')),
            ('invalid encoded bytes',lambda d:d['media'][0].update(dataHex='0000')),
            ('missing resource',lambda d:d['slides'][0]['shapes'][-1]['kind']['fill'].update(media=999999)),
            ('empty crop',lambda d:d['slides'][0]['shapes'][-1]['kind']['fill'].update(crop=[.5,0.0,.5,0.0])),
            ('boolean crop',lambda d:d['slides'][0]['shapes'][-1]['kind']['fill'].update(crop=[True,0,0,0])),
            ('unknown adjustment',lambda d:d['slides'][0]['shapes'][-1]['kind']['fill']['adjust'].update(surprise=1)),
            ('unqualified rotation',lambda d:d['slides'][0]['shapes'][-1]['xfrm'].update(rot=15.0)),
        ]:
            damaged=copy.deepcopy(with_image);mutate(damaged)
            refused(label,lambda d=damaged:slides.admission.inspect(revision.encoded(d)))
        refused('stale slide insertion',lambda:revision.revise_bytes(model_bytes,sha(model_bytes),[insert]))
        for label,parameters in [('profile',{'icc_profile':b'not-an-admitted-color-profile'}),('orientation',{'exif':Image.Exif()})]:
            if label=='orientation':parameters['exif'][274]=6
            buffer=io.BytesIO();Image.new('RGB',(16,16),(12,80,130)).save(buffer,format='PNG',**parameters)
            refused('unqualified image '+label,lambda data=buffer.getvalue():pictures.decode({**supplied(data),'id':1,'link':None}))
        buffer=io.BytesIO();Image.new('RGBA',(16,16),(0,120,10,255)).save(buffer,format='PNG',save_all=True,
            append_images=[Image.new('RGBA',(16,16),(80,10,10,255))],duration=100,loop=0)
        refused('animated image',lambda:pictures.decode({**supplied(buffer.getvalue()),'id':1,'link':None}))
        excessive=io.BytesIO();Image.new('RGB',(8193,1),(20,40,60)).save(excessive,format='PNG')
        refused('independent image side budget',lambda:pictures.decode({**supplied(excessive.getvalue()),'id':1,'link':None}))
        for label,data in [('malformed',b'not a picture'),('encoded-budget',b'0'*((16<<20)+1)),('pixel-budget',excessive.getvalue())]:
            path=native_root/label;path.write_bytes(data)
            refused('native '+label,lambda path=path:native._run('picture',path,native_root/(label+'.pixels'),limit=8192))
            check('refused '+label+' creates no packet',not (native_root/(label+'.pixels')).exists())
        legacy=args.predecessor.read_bytes();prior=project.inspect_bytes(legacy)
        migrated=project.migrate(legacy,sha(legacy),engine=slides.binding.PIN);migrated_path=out/'migration.dobeslides';migrated_path.write_bytes(migrated)
        migration_owner=call('create_project',{'name':'Maintained decoder transition'})['id'];migration_asset=store.import_asset('local',migration_owner,migrated_path)['id']
        result=job(migration_owner,'slides.import',{'asset':migration_asset,'format':'dobeslides'});checked=checkout('migration',result)
        check('predecessor transition retains exact original and model through new native engine',
              (checked/'native/predecessor.dobeslides').read_bytes()==legacy
              and (checked/'native/document.json').read_bytes()==prior['members']['document.json'])
        large=io.BytesIO();Image.frombytes('RGB',(768,512),random.Random(42).randbytes(768*512*3)).save(large,format='PNG')
        large_bytes=large.getvalue();assert len(large_bytes)>1<<20
        large_owner=call('create_project',{'name':'Photograph-sized owned image'})['id'];base=job(large_owner,'slides.create',{'document':model})
        base_folder=checkout('large-base',base);base_bytes=(base_folder/'native/project.dobeslides').read_bytes()
        large_path=out/'large.png';large_path.write_bytes(large_bytes);large_asset=store.import_asset('local',large_owner,large_path)['id']
        large_insert=copy.deepcopy(insert);large_insert['value']['image']={'asset':large_asset,'sha256':sha(large_bytes),'name':'Owned large picture.png','contentType':'image/png'}
        large_revision=job(large_owner,'slides.edit',{'expected_sha256':sha(base_bytes),'edits':[large_insert]},base)
        large_folder=checkout('large-picture',large_revision);large_project=(large_folder/'native/project.dobeslides').read_bytes()
        large_checked=project.inspect_bytes(large_project)
        check('photograph-sized history exceeds old text cap and retains exact native image',
              len(large_checked['members']['project.json'])>1<<20
              and bytes.fromhex(large_checked['current']['document']['media'][0]['dataHex'])==large_bytes
              and large_revision['validation']['native_model_equal'])
        refused('cross-project image asset admission',lambda:job(recipient,'slides.edit',{'expected_sha256':sha(moved_bytes),'edits':[large_insert]},output,False))
        check('cross-project image asset cannot publish a revision',store.get_project('local',recipient)['head']==head)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'jobs':[{'operation':j['operation'],'state':j['state'],'id':j['id']} for j in jobs],
                  'native_decoder_calls':native.calls,'binary_sha256':slides.binding.resolve()['expected_binary_sha256'],
                  'runtime_qualified':True,'installed_qualified':False,'linux_qualified':False,'remote_actions':False,
                  'png':str(png_folder/'exports/delivery/slide-001.png'),'pdf_preview':str(preview)}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'jobs':len(jobs)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'jobs':jobs},indent=2)+'\n');raise


if __name__=='__main__':main()
