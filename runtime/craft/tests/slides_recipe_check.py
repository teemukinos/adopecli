#!/usr/bin/env python3
"""Check complete native models, editable exports and precise recipe revisions."""
import argparse
import copy
import json
import re
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import slides_recipes as recipes,slides_source as source,slides_revision as revision,slides_project as project,slides_engine,slides_binding
    checks=[];refusals=[];calls=0;executable=args.engine.resolve();pin=slides_binding.PIN
    request={'recipe':'production_proposal','version':1,'title':'Make room for repair.',
        'subtitle':'A launch campaign for tools worth keeping.','label':'Workshop / Creative proposal','author':'Independent concept study',
        'sections':[{'heading':'One idea. Many useful assets.','paragraphs':[
            'Show the marks of use as evidence of value. Build the campaign around hands, tools and repaired objects.',
            'Keep the same framing, warm paper palette and direct language across every format.'],
            'notes':'Concept example. All content is original; no customer endorsement is implied.'},
            {'heading':'Revise the message.','paragraphs':[
                'Change the launch line after review. Preserve the approved layouts, source files and delivery specifications.',
                'Keep each decision visible so the next person can continue the work.']}],
        'deliverables':[{'asset':'Campaign stills','source':'Layered image project','delivery':'3 × 1600 px PNG'},
            {'asset':'Launch film','source':'Editable timeline','delivery':'15 s / 1080 × 1920'},
            {'asset':'Motion titles','source':'Native motion project','delivery':'Alpha video + PNG'},
            {'asset':'Product icons','source':'Editable vectors','delivery':'SVG + PDF'},
            {'asset':'Handoff guide','source':'Editable presentation','delivery':'Native + PDF + PPTX'}]}
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def native(*arguments):
        nonlocal calls
        calls+=1;r=subprocess.run([str(executable),*map(str,arguments)],capture_output=True,timeout=120)
        (out/f'native-{calls}.stdout').write_bytes(r.stdout);(out/f'native-{calls}.stderr').write_bytes(r.stderr)
        check('native call '+str(calls)+' succeeded',r.returncode==0);return json.loads(r.stdout)
    def assert_model(actual,expected,label):
        if revision.canonical(actual)!=revision.canonical(expected):
            (out/'mismatch-actual.json').write_bytes(revision.encoded(actual));(out/'mismatch-expected.json').write_bytes(revision.encoded(expected))
            raise AssertionError(label)
        checks.append(label)
    try:
        compiled=recipes.compile_recipe(request);model=compiled['document'];data=compiled['data']
        (out/'request.json').write_text(json.dumps(request,indent=2)+'\n');(out/'proposal.json').write_bytes(data)
        (out/'selectors.json').write_text(json.dumps(compiled['selectors'],indent=2)+'\n')
        (out/'text-boxes.json').write_text(json.dumps(compiled['text_boxes'],indent=2)+'\n')
        check('recipe compilation is deterministic',recipes.compile_recipe(copy.deepcopy(request))['data']==data)
        check('recipe metadata keeps admission and text fit unresolved',not compiled['engine_admission_complete'] and not compiled['text_fit_qualified']
              and not recipes.catalog()[0]['shares_user_content'])
        check('delivery rows paginate without losing source or format',compiled['slide_count']==5 and len(compiled['selectors']['deliverables'])==5)
        check('complete native sources are editable text and shapes',all(s['kind']['type']=='shape' for slide in model['slides'] for s in slide['shapes']) and not model['media'])
        for section,selectors in zip(request['sections'],compiled['selectors']['sections']):
            check('section content retains exact paragraph strings',[revision.locate(model,path)['text'] for path in selectors['paragraphs']['runs']]==section['paragraphs'])
        for row,selectors in zip(request['deliverables'],compiled['selectors']['deliverables']):
            check('delivery content retains exact three columns',all(revision.locate(model,selectors[key]['runs'][0])['text']==value for key,value in row.items()))
        deck=out/'proposal.deckcraft';encoded=native('encode',out/'proposal.json',deck)
        assert_model(encoded['document'],model,'complete encoded model equals independent recipe prediction')
        assert_model(source.inspect_bytes(deck.read_bytes(),'deckcraft')['document'],model,'independent container reconstruction equals recipe')
        assert_model(native('snapshot',deck)['document'],model,'cold native model equals complete recipe prediction')
        portable=project.create(data,'json',engine=pin);(out/'proposal.dobeslides').write_bytes(portable)
        observer=slides_engine.Engine(executable,out,expected_pin=pin,expected_binary_sha256=source.sha(executable.read_bytes()))
        report=observer.verify_project(portable,out/'checked-project')
        check('portable recipe retains exact originals and cold native models',report['original_bytes_unchanged'] and report['current_model_equal'])
        run_path=compiled['selectors']['sections'][1]['paragraphs']['runs'][0];original=revision.locate(model,run_path)['text'];start=original.encode().index(b'launch line')
        edit={'kind':'text.replace','path':run_path,'start':start,'end':start+11,'expected':'launch line','value':'opening sentence'}
        revised=project.revise(portable,source.sha(portable),[edit]);changed=project.inspect_bytes(revised);prediction=copy.deepcopy(model)
        revision.locate(prediction,run_path)['text']=original.replace('launch line','opening sentence',1)
        assert_model(changed['current']['document'],prediction,'exact paragraph revision preserves all other fields')
        (out/'revised.dobeslides').write_bytes(revised);(out/'revised.json').write_bytes(changed['members']['document.json'])
        revised_deck=out/'revised.deckcraft';assert_model(native('encode',out/'revised.json',revised_deck)['document'],prediction,'revised native model equals independent prediction')
        for index in range(compiled['slide_count']):
            result=native('render',deck,out/f'slide-{index+1}.png',index,1)
            check('page '+str(index+1)+' has exact output dimensions',result['width']==960 and result['height']==540)
        native('render',revised_deck,out/'revised-slide-3.png',2,1)
        native('render',revised_deck,out/'unchanged-slide-1.png',0,1)
        check('unaffected cover pixels remain byte-exact after selected text revision',(out/'unchanged-slide-1.png').read_bytes()==(out/'slide-1.png').read_bytes())
        check('selected text revision changes target slide pixels',(out/'revised-slide-3.png').read_bytes()!=(out/'slide-3.png').read_bytes())
        native('convert',deck,out/'proposal.pptx','pptx');native('convert',deck,out/'proposal.pdf','pdf')
        with zipfile.ZipFile(out/'proposal.pptx') as archive:
            slides=sorted(name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide[0-9]+\.xml',name))
            check('PPTX has every authored slide',len(slides)==compiled['slide_count'])
            for index,slide in enumerate(model['slides']):
                xml=ET.fromstring(archive.read('ppt/slides/slide'+str(index+1)+'.xml'))
                texts=[node.text or '' for node in xml.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t')]
                expected=[run['text'] for shape in slide['shapes'] if shape['text'] for para in shape['text']['paragraphs'] for run in para['runs']]
                check('PPTX slide '+str(index+1)+' editable text matches exact inventory',texts==expected)
            notes=ET.fromstring(archive.read('ppt/notesSlides/notesSlide2.xml'))
            check('PPTX speaker notes retain original text',request['sections'][0]['notes'] in [n.text for n in notes.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t')])
        check('PDF signature observed without claiming full PDF qualification',(out/'proposal.pdf').read_bytes().startswith(b'%PDF-'))
        alternate=copy.deepcopy(request);alternate['controls']={'accent':'#112233'};alternate['title']='Different content / same production recipe'
        alternate_model=recipes.compile_recipe(alternate)
        check('new content is independent while production configuration is reused',alternate_model['provenance']==compiled['provenance'] and alternate_model['document']!=model
              and recipes.compile_recipe(request)['data']==data and alternate_model['request']['controls']['accent']=='#112233')
        check('accent contrast chooses legible black or white text',recipes.contrast_ink('#FFFFFF')=='#000000' and recipes.contrast_ink('#000000')=='#FFFFFF')
        for label,mutate in [
            ('unavailable recipe',lambda x:x.update(recipe='other')),('boolean version',lambda x:x.update(version=True)),
            ('unknown execution parameter',lambda x:x.update(engine='/tmp/other')),('empty sections',lambda x:x.update(sections=[])),
            ('too many sections',lambda x:x.update(sections=x['sections']*13)),('missing delivery field',lambda x:x['deliverables'][0].pop('source')),
            ('unknown controls',lambda x:x.update(controls={'font':'system'})),('invalid accent',lambda x:x.update(controls={'accent':'red'})),
            ('line-break injection',lambda x:x.update(title='first\nsecond')),('invalid Unicode',lambda x:x.update(title='bad\ud800')),
            ('title byte budget',lambda x:x.update(title='x'*513)),('empty paragraph',lambda x:x['sections'][0].update(paragraphs=[''])),
            ('aggregate content budget',lambda x:x.update(sections=[{'heading':'Section','paragraphs':['x'*8192]*6}]*24))]:
            value=copy.deepcopy(request);mutate(value);refused(label,lambda value=value:recipes.compile_recipe(value))
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':calls+observer.calls,'slide_count':compiled['slide_count'],
                  'recipe':compiled['provenance'],'complete_model_equal':True,'portable_originals_exact':True,'pptx_editable_text_inventory_equal':True,
                  'pptx_source_fidelity_qualified':False,'independent_pdf_qualified':False,'text_fit_qualified':False,'glyph_coverage_qualified':False,
                  'engine_admission_complete':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'checks':len(checks),'refusals':len(refusals),'native_calls':evidence['native_calls'],'slides':compiled['slide_count']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':calls},indent=2)+'\n');raise


if __name__=='__main__':main()
