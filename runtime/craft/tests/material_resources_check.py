#!/usr/bin/env python3
"""Package/resource admission and real native agreement on retained local fixtures."""
import argparse
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_container as container,material_resources as resources
from texture_images_check import fixtures
from studio_runtime import texture_images


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--embedded-source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[]
    base=container.read_native(args.fixtures/'embedded.mcraft')
    def pack(members):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('resources/',b'')
            for name,data in members.items():archive.writestr(name,data)
        return stream.getvalue()
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def resource_fixture(data,ext='png',modify=None,extra=None):
        xml=ET.fromstring(base['members']['package.sbs']);r=next(xml.iter('resource'));r.find('format').set('v',ext)
        r.find('source/externalcopy/filename').set('v','resources/input.'+ext)
        if modify:modify(xml,r)
        members={'package.sbs':ET.tostring(xml,encoding='utf-8'),'resources/input.'+ext:data}
        if extra:members.update(extra)
        return pack(members)
    def inspect(data):return resources.inspect(container.inspect_bytes(data))
    def refused(label,data):
        try:inspect(data)
        except ValueError:checks.append(label)
        else:raise AssertionError('accepted '+label)
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        index=len(calls);(out/f'{index:03}.stdout').write_bytes(result.stdout);(out/f'{index:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        if result.returncode:raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout)
    try:
        samples=fixtures()
        for name in ('paint.mcraft','atomic.mcraft','embedded.mcraft','linked-package.mcraft','portable-source.sbs'):
            source=container.read_native(args.fixtures/name);profile=resources.inspect(source)
            check('retained native inventory '+name,not profile['engine_admission_complete'])
            if name=='linked-package.mcraft':check('archived dependency inventoried without opening it',len(profile['packages'])==2)
        embedded=resources.inspect(container.read_native(args.embedded_source))
        check('compressed native embedded image retained',len(embedded['resources'])==1 and next(iter(embedded['resources'].values()))['original_bytes']==(args.fixtures/'external.png').read_bytes())
        for name,data in samples.items():
            ext=name.split('.')[-1];asset=out/name;asset.write_bytes(data);source=out/(ext+'.mcraft')
            run('run',args.fixtures/'paint.mcraft','file.importBitmap',json.dumps({'path':str(asset),'name':'Reference'}),'-o',source)
            original=source.read_bytes()
            admitted=container.read_native(source);profile=resources.inspect(admitted)
            record=next(iter(profile['resources'].values()))
            check('complete decode and exact bytes '+ext,record['original_bytes']==data and (record['decoded']['width'],record['decoded']['height'])==(16,8))
            info=run('info',source);resources.check_native(profile,info,'package.sbs');check('native metadata agreement '+ext,True)
            # The resource must actually be decoded by a connected bitmap node,
            # not merely listed as bytes by native inspection.
            revised=out/(ext+'-bitmap.mcraft');script=out/(ext+'-bitmap.json')
            script.write_text(json.dumps({'open':str(source),'steps':[
                {'id':'graph.node.add','params':{'def':'bitmap','params':{'resource':'Reference'}}},
                {'id':'graph.connect','params':{'from':13,'to':2,'fromPort':'output','toPort':'input'}}], 'save':str(revised)}))
            run('batch',script);info=run('info',revised)
            bitmap=next(node for node in info['graph']['nodes'] if node['def']=='bitmap')
            check('actual native bitmap cook '+ext,bitmap['cooked']['error'] is None and bitmap['cooked']['size']==[64,64])
            exports=out/(ext+'-maps');run('export',revised,exports,'--depth','8')
            image=Image.open(exports/'Paint_basecolor.png').convert('RGB')
            if ext=='hdr':pixel=(137,188,225)
            elif ext=='exr':pixel=(137,188,225)
            else:pixel=Image.open(io.BytesIO(data)).convert('RGB').getpixel((0,0))
            observed=image.getpixel((32,32))
            check('native color pixels agree '+ext,all(abs(a-b)<=1 for a,b in zip(observed,pixel)))
            cold=out/(ext+'-cold.mcraft');run('run',source,'file.save',json.dumps({'path':str(cold)}))
            container.check_preservation(admitted,container.read_native(cold))
            check('native resource bytes and all fields retained '+ext,source.read_bytes()==original)
        png=samples['sample.png']
        # Delimiters can occur in legal archive and item names; compound map
        # keys must not merge resources from distinct package/name pairs.
        root=ET.fromstring(container.read_native(args.fixtures/'paint.mcraft')['members']['package.sbs'])
        collision_members={}
        for index,(path,label) in enumerate((('resources/a.sbs','b.sbs#R'),('resources/a.sbs#b.sbs','R'))):
            dependency=copy.deepcopy(root.find('dependencies/dependency'))
            dependency.find('filename').set('v',path);dependency.find('uid').set('v',str(900000+index));root.find('dependencies').append(dependency)
            nested=ET.fromstring(base['members']['package.sbs']);resource=next(nested.iter('resource'))
            resource.find('identifier').set('v',label);resource.find('source/externalcopy/filename').set('v','input.png')
            # Put both resources at package root so their old delimiter keys
            # would be identical while their proper pairs remain distinct.
            nested.find('content/group/content').remove(resource);nested.find('content').append(resource)
            collision_members[path]=ET.tostring(nested,encoding='utf-8')
        collision_members.update({'package.sbs':ET.tostring(root,encoding='utf-8'),'resources/input.png':png})
        check('compound resource identities never collide on delimiters',len(inspect(pack(collision_members))['resources'])==2)
        cases=[
            ('unknown root attribute',lambda x,r:x.set('future','x')),
            ('duplicate root identifier',lambda x,r:x.append(copy.deepcopy(x.find('identifier')))),
            ('unknown resource field',lambda x,r:ET.SubElement(r,'future')),
            ('duplicate resource source',lambda x,r:r.append(copy.deepcopy(r.find('source')))),
            ('missing resource identifier',lambda x,r:r.remove(r.find('identifier'))),
            ('duplicate resource identity',lambda x,r:x.find('content/group/content').append(copy.deepcopy(r))),
            ('legacy resource path',lambda x,r:r.find('filepath').set('v','elsewhere.png')),
            ('resource traversal',lambda x,r:r.find('source/externalcopy/filename').set('v','../outside.png')),
            ('resource absolute path',lambda x,r:r.find('source/externalcopy/filename').set('v','/outside.png')),
            ('resource URL',lambda x,r:r.find('source/externalcopy/filename').set('v','https://outside/image.png')),
            ('missing archive resource',lambda x,r:r.find('source/externalcopy/filename').set('v','resources/missing.png')),
            ('duplicate resource UID',lambda x,r:r.find('uid').set('v','1000000001')),
            ('oversized UID',lambda x,r:r.find('uid').set('v',str(2**64))),
            ('unknown package item',lambda x,r:ET.SubElement(x.find('content'),'future')),
            ('invalid folder',lambda x,r:x.find('content/group/identifier').set('v','../Resources')),
            ('missing self dependency',lambda x,r:x.find('dependencies').clear()),
            ('duplicate self dependency',lambda x,r:x.find('dependencies').append(copy.deepcopy(x.find('dependencies/dependency')))),
            ('external package reference',lambda x,r:x.find('dependencies/dependency/filename').set('v','sbs://unqualified.sbs')),
        ]
        for label,mutate in cases:refused(label,resource_fixture(png,modify=mutate))
        refused('unused member',resource_fixture(png,extra={'future.bin':b'preserve'}))
        refused('wrong declared image format',resource_fixture(png,'jpg'))
        refused('broken image bytes',resource_fixture(b'invalid'))
        refused('SVG profile pending',resource_fixture(b'<svg/>','svg'))
        ambiguous_hdr=samples['sample.hdr'].replace(b'#?RADIANCE\n',b'#?RADIANCE\n# <svg\n'+(b'# '+b'x'*900+b'\n')*5)
        check('ambiguous HDR remains valid for independent decoder',texture_images.inspect_bytes(ambiguous_hdr)['format']=='HDR')
        refused('native SVG sniff overrides valid HDR',resource_fixture(ambiguous_hdr,'hdr'))
        asset=out/'ambiguous.hdr';asset.write_bytes(ambiguous_hdr);target=out/'ambiguous-import.mcraft'
        result=subprocess.run([str(args.engine.resolve()),'run',str(args.fixtures/'paint.mcraft'),'file.importBitmap',
            json.dumps({'path':str(asset),'name':'Ambiguous'}),'-o',str(target)],capture_output=True,timeout=60)
        index=len(calls);(out/f'{index:03}.stdout').write_bytes(result.stdout);(out/f'{index:03}.stderr').write_bytes(result.stderr)
        calls.append({'case':'native HDR/SVG disagreement','exit_code':result.returncode})
        check('native decoder disagreement reproduces without publication',result.returncode!=0 and not target.exists())
        for key,limit in [('MAX_RESOURCES',0),('MAX_RESOURCE_BYTES',len(png)-1),('MAX_TEXELS',127),('MAX_ITEMS',0),('MAX_PACKAGES',0)]:
            old=getattr(resources,key);setattr(resources,key,limit)
            try:refused('aggregate limit '+key,resource_fixture(png))
            finally:setattr(resources,key,old)
        bare=container.read_native(args.embedded_source)
        profile=resources.inspect(bare);native=run('info',args.embedded_source)
        resources.check_native(profile,native,bare['root']);check('bare embedded native metadata agrees',True)
        for field,value in [('bytes',1),('name','wrong'),('folder','wrong'),('file','wrong'),('missing',True)]:
            altered=copy.deepcopy(native);altered['package']['resources'][0][field]=value
            try:resources.check_native(profile,altered,bare['root'])
            except ValueError:checks.append('native mismatch '+field)
            else:raise AssertionError('accepted native mismatch '+field)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'resource_formats':sorted(samples),'engine_admission_complete':False,'scope':'package and bitmap-resource admission; graph/vector/remaining-format and durable runtime qualification pending','remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls),'evidence':str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
