#!/usr/bin/env python3
"""Portable material selection, embedded images, signed height and failed writes."""
import argparse
import io
import json
from pathlib import Path
import sys
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_bundle as bundle, texture_material as handoff, texture_workflow as workflow, texture_document as document
from material_export_codecs_check import bitmap_recipe


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('material','texture','fixtures','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=args.output.resolve();root.mkdir();checks=[]
    engine=args.material.resolve();texture=args.texture.resolve();fixtures=args.fixtures.resolve()
    base=fixtures/'texture-before/native/document.tcraft';base_digest=document.read_native(base)['source_sha256']
    original=root/'original.mcraft';original.write_bytes((fixtures/'material/native/document.mcraft').read_bytes());full=(fixtures/'material/exports/material.mcmat').read_bytes()
    def check(name,condition=True):
        if not condition:raise AssertionError(name)
        checks.append(name)
    def refused(name,action):
        try:action()
        except (ValueError,OSError):check(name)
        else:raise AssertionError('accepted '+name)
    def apply(label,asset,options=None):
        params={'asset':'a'*32,'expected_sha256':base_digest,'texture_set':0,**(options or {})}
        source,report=handoff.apply(root/label,base,asset,params,texture,engine)
        result=workflow.prepare(root,source,root/(label+'-exports'),texture,export_maps=True)
        (root/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        return source,report,result
    try:
        subset=root/'subset.mcmat';bundle.export(root,original,subset,{'graph':'Surface','outputs':['baseColor']},engine)
        check('explicit single output retained',len(bundle.inspect_bytes(subset.read_bytes())['maps'])==1)
        source,report,_=apply('subset',subset)
        check('material without height needs no height mode',report['channels']==['BaseColor'] and not report['map_conversions'])
        fullfile=root/'full.mcmat';fullfile.write_bytes(full)
        source,report,result=apply('signed',fullfile,{'height_mode':'signed'})
        check('explicit signed height keeps exact map bytes',not report['map_conversions'])
        admitted=bundle.inspect_bytes(full);height=next(m for m in admitted['maps'] if m['usage']=='height')
        with Image.open(io.BytesIO(admitted['members'][height['file']])) as image:expected=[round(int(v)/65535*255) for v in image.get_flattened_data()]
        output=next(m for m in result['maps'] if m['file'].endswith('_height.png'))
        with Image.open(root/'signed-exports/exports/maps'/output['file']) as image:actual=list(image.convert('L').get_flattened_data())
        check('signed Texture export matches every input height sample',len(actual)==len(expected) and max(abs(a-b) for a,b in zip(actual,expected))<=1)
        refused('replace cannot silently drop channels',lambda:handoff.apply(root/'wrong-channels',source,subset,{'asset':'a'*32,'texture_set':0,'layer':report['layer'],'expected_sha256':document.read_native(source)['source_sha256']},texture,engine))
        # Source images remain inside the exact source archive; neither app needs
        # the original external image path to reopen this material.
        stream=io.BytesIO();Image.new('RGBA',(32,32),(255,0,0,255)).save(stream,format='PNG');pixels=stream.getvalue()
        data,_=bitmap_recipe(pixels,'png');path=root/'bitmap.mcraft';path.write_bytes(data)
        portable=root/'bitmap.mcmat';bundle.export(root,path,portable,{'graph':'Original'},engine)
        imported=bundle.verify(root,portable.read_bytes(),engine)
        check('embedded resource bytes retained inside exact source',imported['members']['source.mcraft']==data and pixels in imported['profile']['container']['members'].values())
        source,report,result=apply('bitmap',portable)
        check('map and target dimensions explicit',report['source_map_size']==[32,32] and report['texture_resolution']==128)
        output=next(m for m in result['maps'] if m['file'].endswith('_baseColor.png'))
        with Image.open(root/'bitmap-exports/exports/maps'/output['file']) as image:check('actual Texture resampling preserves uniform red',image.convert('RGB').tobytes()==bytes((255,0,0))*128*128)
        for label,corrupt in [('trailing ZIP',full+b'extra'),('truncated ZIP',full[:-1])]:refused(label,lambda corrupt=corrupt:bundle.inspect_bytes(corrupt))
        refused('unknown output cannot create a bundle',lambda:bundle.export(root,original,root/'unknown.mcmat',{'graph':'Surface','outputs':['absent']},engine))
        check('failed selection leaves no output',not (root/'unknown.mcmat').exists())
        existing=root/'existing.mcmat';existing.write_bytes(b'keep')
        refused('existing output preserved',lambda:bundle.export(root,original,existing,{'graph':'Surface'},engine));check('existing bytes exact',existing.read_bytes()==b'keep')
        original_sync=bundle.os.fsync
        def fail_sync(fd):raise OSError('controlled storage sync failure')
        bundle.os.fsync=fail_sync
        try:refused('failed bundle sync refuses',lambda:bundle.export(root,original,root/'incomplete.mcmat',{'graph':'Surface'},engine))
        finally:bundle.os.fsync=original_sync
        check('failed bundle sync removes only its own partial file',not (root/'incomplete.mcmat').exists() and existing.read_bytes()==b'keep')
        result={'passed':True,'checks':checks,'native_engines_unchanged':True,'remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks)}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise


if __name__=='__main__':main()
