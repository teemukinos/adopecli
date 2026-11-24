#!/usr/bin/env python3
"""Qualify controlled native Slides models, owned media and real output files.

This is private-engine evidence, not public untrusted-source admission or a
claim of complete PPTX/font fidelity. Every child is an actual source build.
"""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);exe=args.engine.resolve()
    checks=[];refusals=[];calls=0
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def invoke(*arguments,fail=False):
        nonlocal calls
        calls+=1
        result=subprocess.run([str(exe),*map(str,arguments)],capture_output=True,timeout=120)
        (out/f'call-{calls:02d}.stdout').write_bytes(result.stdout);(out/f'call-{calls:02d}.stderr').write_bytes(result.stderr)
        if fail:
            check('refuse '+str(arguments[0]),result.returncode!=0);refusals.append({'arguments':list(map(str,arguments)),'error':result.stderr.decode()});return
        check('native '+str(arguments[0])+' exits successfully',result.returncode==0)
        return json.loads(result.stdout)
    try:
        version=subprocess.check_output([str(exe),'--version'],text=True).strip()
        check('maintained source identity',version=='dobe-slides 0.18.1 (7cc73ab1895ed2e30c8afbcada20c70b9ea0a440)')
        blank=out/'blank.deckcraft';first=invoke('new',blank);model=first['document']
        check('new document cold-opens exactly',invoke('snapshot',blank)['document']==model)
        check('complete model includes one editable slide',len(model['slides'])==1 and len(model['slides'][0]['shapes'])>=2)
        authored=copy.deepcopy(model);authored['props']['title']='A coherent visual suite'
        title,subtitle=authored['slides'][0]['shapes'][:2]
        title['text']['paragraphs']=[{'level':0,'runs':[{'text':'A coherent visual suite'}]}]
        subtitle['text']['paragraphs']=[{'level':0,'runs':[{'text':'Editable images, motion and materials'}]}]
        # A tiny original fixture also proves the upstream serde-skipped media
        # bytes survive the private model interface and native ZIP sidecar.
        picture=io.BytesIO();Image.new('RGBA',(3,2),(19,62,73,255)).save(picture,format='PNG');data=picture.getvalue()
        authored['nextId']+=1;media_id=authored['nextId']
        authored['media'].append({'id':media_id,'name':'original-tile.png','contentType':'image/png','link':None,'dataHex':data.hex()})
        model_file=out/'authored.json';model_file.write_text(json.dumps(authored)+'\n');native=out/'authored.deckcraft'
        encoded=invoke('encode',model_file,native)
        check('complete authored model stays exact',encoded['document']==authored)
        cold=invoke('snapshot',native);check('native reopen preserves every model field and media byte',cold['document']==authored)
        check('native selected requested families are available',cold['missingFonts']==[])
        with zipfile.ZipFile(native) as z:check('original PNG sidecar is exact',z.read('media/'+str(media_id))==data)
        png=out/'slide.png';render=invoke('render',native,png,0,1)
        with Image.open(png) as image:
            image.load();check('real PNG is 960 by 540 with content',image.size==(960,540) and len(image.getcolors(image.width*image.height) or [])>1)
        repeat=out/'slide-repeat.png';invoke('render',native,repeat,0,1);check('two cold PNG files match exactly',repeat.read_bytes()==png.read_bytes())
        check('reported PNG dimensions match decode',(render['width'],render['height'])==(960,540))
        pdf=out/'deck.pdf';invoke('convert',native,pdf,'pdf');check('real PDF signature',pdf.read_bytes().startswith(b'%PDF-'))
        pptx=out/'deck.pptx';invoke('convert',native,pptx,'pptx')
        with zipfile.ZipFile(pptx) as z:
            check('PPTX contains editable slide XML','ppt/slides/slide1.xml' in z.namelist())
            check('PPTX retains title bytes',b'A coherent visual suite' in z.read('ppt/slides/slide1.xml'))
        converted=invoke('snapshot',pptx)
        check('PPTX conversion retains slide count',len(converted['document']['slides'])==1)
        changed=copy.deepcopy(authored);changed['slides'][0]['shapes'][0]['text']['paragraphs'][0]['runs'][0]['text']='One precise revision'
        revision=out/'revision.json';revision.write_text(json.dumps(changed)+'\n');revised=out/'revised.deckcraft'
        invoke('encode',revision,revised);check('precise text revision retains complete unrelated model',invoke('snapshot',revised)['document']==changed)
        original=native.read_bytes();invoke('encode',revision,native,fail=True);check('existing source never overwritten',native.read_bytes()==original)
        for args_ in [('app',),('mcp',),('run','arbitrary.json'),('render',native,out/'negative.png',99,1),('render',native,out/'negative.png',0,'nan'),('render',native,out/'negative.png',0,5),('convert',native,out/'negative.png','unknown')]:invoke(*args_,fail=True)
        missing=copy.deepcopy(authored);missing['slides'][0]['shapes'][0]['text']['paragraphs'][0]['runs'][0]['props']={'font':'Dobe Missing Fixture Font'}
        missing_file=out/'missing.json';missing_file.write_text(json.dumps(missing));missing_native=out/'missing.deckcraft';invoke('encode',missing_file,missing_native)
        invoke('render',missing_native,out/'missing.png',0,1,fail=True)
        check('refused render creates no output',not (out/'missing.png').exists() and not (out/'negative.png').exists())
        check('input model and native source remain unchanged',json.loads(model_file.read_bytes())==authored and native.read_bytes()==original)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':calls,'version':version,'binary_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                  'complete_native_model_compared':True,'original_media_bytes_preserved':True,'cold_png_equal':True,
                  'pptx_complete_fidelity_qualified':False,'pdf_independent_reader_qualified':False,'actual_glyph_identity_qualified':False,
                  'public_runtime_qualified':False,'installed_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'checks':len(checks),'refusals':len(refusals),'native_calls':calls}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':calls},indent=2)+'\n');raise


if __name__=='__main__':main()
