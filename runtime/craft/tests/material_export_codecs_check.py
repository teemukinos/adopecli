#!/usr/bin/env python3
"""Qualify native map encodings and independent complete resource decoding.

The legacy export route is exercised only on small, owned fixtures. This does
not qualify it for public jobs or replace the bounded evaluation requirement.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_source as source, material_document as document, material_compute as compute
from studio_runtime import texture_images as images
from material_source_check import recipe, element, scalar, parameter, uniform
from texture_images_check import exr_fixture


def bitmap_recipe(data,extension):
    tree=recipe();content=next(n for n in tree['children'] if n['tag']=='content');graph=content['children'][0]
    member='resources/reference.'+extension
    content['children'].append(element('group',scalar('identifier','Resources'),scalar('uid',90),element('content',element('resource',
        scalar('identifier','Reference'),scalar('uid',91),scalar('type','bitmap'),scalar('format',extension),scalar('filepath',''),
        element('source',element('externalcopy',scalar('filename',member)))))))
    bitmap=uniform(3,4,'1 1 1 1');bitmap['children'][-1]=element('compImplementation',element('compFilter',scalar('filter','bitmap'),element('parameters',
        parameter('bitmapresourcepath','String','pkg:///Resources/Reference'),parameter('colorswitch','Bool',1),parameter('colorspace','Int32',0))))
    next(n for n in graph['children'] if n['tag']=='compNodes')['children'][0]=bitmap
    return source.create({'package.sbs':tree},{member:data})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[];reports=[]
    def check(label,ok):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def native(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        index=len(calls);(out/f'{index:03}.stdout').write_bytes(result.stdout);(out/f'{index:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        if result.returncode:raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout)
    def roundtrip(label,data,extension,expected,tolerance=0,mode="RGB"):
        native_data,report=bitmap_recipe(data,extension);destination=out/label
        source.prepare(out,native_data,destination,args.engine,report)
        path=destination/'native/document.mcraft';profile=document.read_native(path)
        check(label+' exact embedded resource bytes',profile['container']['members']['resources/reference.'+extension]==data)
        cooked=compute.cook(out,path,'Original',args.engine)
        check(label+' bounded finite native bitmap cook',cooked['finite_outputs'] and cooked['full_size'])
        folder=destination/'pixels';native('export',path,folder,'--depth','8')
        with Image.open(folder/'Original_basecolor.png') as image:
            actual=image.convert(mode).tobytes()
            check(label+' every pixel matches independent oracle',image.size==(32,32) and len(actual)==len(expected)
                  and all(abs(a-b)<=tolerance for a,b in zip(actual,expected)))
        check(label+' editable source unchanged',path.read_bytes()==native_data)
    try:
        original,_=source.create({'package.sbs':recipe()});input_path=out/'original.mcraft';input_path.write_bytes(original)
        for extension,depth in [('png',8),('png',16),('jpg',8),('tga',8),('bmp',8),('webp',8),('exr',32),('hdr',32)]:
            label=extension+str(depth);directory=out/label;native('export',input_path,directory,'--format',extension,'--depth',depth)
            check(label+' exact map inventory',sorted(p.name for p in directory.iterdir())==['Original_basecolor.'+extension,'Original_roughness.'+extension])
            for name,expected in [('basecolor',bytes((255,0,0))*1024),('roughness',bytes((0,0,0))*1024)]:
                data=(directory/('Original_'+name+'.'+extension)).read_bytes();report=images.inspect_bytes(data)
                check(label+' '+name+' complete independent decoder',report['width']==report['height']==32)
                if extension=='tga':check(label+' '+name+' uncompressed interoperable TGA',data[2] in (2,3))
                if extension=='png':check(label+' '+name+' actual PNG sample depth',data[24]==depth)
                if extension=='exr':check(label+' '+name+' native tiled RLE EXR',report['storage']=='tiles' and report['compression']==1 and report['tile_width']==64)
                reports.append({'name':label+'-'+name,**report})
                roundtrip('reimport-'+label+'-'+name,data,extension,expected,1 if extension=='jpg' else 0)
        # Independent spatial fixtures cover all accepted compression forms,
        # channel sizes, edge tiles and nonsequential physical chunk storage.
        def linear(x,y):return (x/31*.75,y/31*.5,.25)  # EXR channel order B,G,R.
        def quantized(v):
            srgb=12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055
            return int(srgb*255+.5)
        expected=bytes(quantized(v) for y in range(32) for x in range(32) for v in reversed(linear(x,y)))
        for compression in (0,1,2,3):
            for size in (2,4):
                data=exr_fixture(width=32,height=32,tiles=(13,9),compression=compression,sample_size=size,reverse_storage=True,pixel_values=linear)
                label=f'spatial-tile-{compression}-{size}';(out/(label+'.exr')).write_bytes(data)
                report=images.inspect_bytes(data);check(label+' independent complete decoder',report['chunks']==12)
                roundtrip(label,data,'exr',expected,1)
        for compression in (0,1,2,3):
            for size in (2,4):
                def rgba(x,y):return (x/31,*linear(x,y))  # EXR A,B,G,R.
                data=exr_fixture(width=32,height=32,tiles=(13,9),compression=compression,sample_size=size,reverse_storage=True,
                                 values=(.5,.75,.5,.25),pixel_values=rgba)
                label=f'rgba-tile-{compression}-{size}';(out/(label+'.exr')).write_bytes(data)
                expected_alpha=bytes(value for y in range(32) for x in range(32) for value in
                    (*[quantized(v) for v in reversed(linear(x,y))],int(x/31*255+.5)))
                roundtrip(label,data,'exr',expected_alpha,1,mode='RGBA')
        # A native file with more than one 64x64 tile exercises the actual
        # producer's chunk table, in addition to the independent fixture writer.
        tree=recipe();graph=next(n for n in tree['children'] if n['tag']=='content')['children'][0]
        option=next(n for n in graph['children'] if n['tag']=='options')['children'][0]
        next(n for n in option['children'] if n['tag']=='value')['attributes']['v']='7x7'
        large,_=source.create({'package.sbs':tree});path=out/'multiple-tiles.mcraft';path.write_bytes(large)
        native('export',path,out/'multiple-tiles','--format','exr','--depth','32')
        for item in (out/'multiple-tiles').iterdir():
            report=images.inspect_bytes(item.read_bytes());check('native multiple tile image '+item.name,report['width']==report['height']==128 and report['chunks']==4)
        check('original authoring remains byte-identical',input_path.read_bytes()==original and path.read_bytes()==large)
        result={'passed':True,'checks':checks,'explicit_native_calls':len(calls),'source_prepare_and_bounded_cook_calls_additional':True,
                'encodings':reports,'legacy_exports_use_owned_small_fixtures_only':True,'public_map_export_qualified':False,
                'installed_qualification':False,'goal_complete':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks),'explicit_native_calls':len(calls),'roundtrips':32}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
