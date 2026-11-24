#!/usr/bin/env python3
"""Qualify portable Slides originals, exact revision replay and native models."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','fixture','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import slides_source as source,slides_revision as revision,slides_project as project
    checks=[];refusals=[];calls=0;exe=args.engine.resolve();root=Path(__file__).resolve().parents[1]
    lock_bytes=(root/'engines/slides.lock.json').read_bytes();lock=json.loads(lock_bytes)
    engine={'product':'dobe-slides','version':lock['engine_version'],'source_revision':lock['source']['revision'],'source_lock_sha256':source.sha(lock_bytes)}
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def native(*args_):
        nonlocal calls
        calls+=1;result=subprocess.run([str(exe),*map(str,args_)],capture_output=True,timeout=120)
        (out/f'native-{calls}.stdout').write_bytes(result.stdout);(out/f'native-{calls}.stderr').write_bytes(result.stderr)
        check('real native operation succeeded',result.returncode==0);return json.loads(result.stdout)
    def refused(label,call):
        try:call()
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def cold(label,data):
        path=out/(label+'.json');path.write_bytes(data);deck=out/(label+'.deckcraft')
        expected=source.strict_json(data);made=native('encode',path,deck)
        check(label+' full encoded model equals prediction',revision.canonical(made['document'])==revision.canonical(expected))
        check(label+' full cold model equals prediction',revision.canonical(native('snapshot',deck)['document'])==revision.canonical(expected))
        return deck
    try:
        original=args.fixture.read_bytes();base=project.create(original,'deckcraft',engine=engine);initial=project.inspect_bytes(base)
        check('native original remains exact and independently reconstructed',initial['members']['original.deckcraft']==original
              and source.strict_json(initial['members']['baseline.json'])==source.inspect_bytes(original,'deckcraft')['document'])
        check('portable packaging is deterministic',project.create(original,'deckcraft',engine=engine)==base)
        project.require_engine(initial,engine)
        model=source.strict_json(initial['members']['baseline.json']);run_path='/slides/0/shapes/0/text/paragraphs/0/runs/0'
        revision.locate(model,run_path)['text']='Ångström / original / original'
        data=revision.encoded(model);baseline=cold('unicode',data);portable=project.create(data,'json',engine=engine)
        text=revision.locate(model,run_path)['text'];first=text.encode().index(b'original');last=text.encode().rindex(b'original')
        edits=[{'kind':'text.replace','path':run_path,'start':first,'end':first+8,'expected':'original','value':'precise colour'},
               {'kind':'text.replace','path':run_path,'start':last,'end':last+8,'expected':'original','value':'editable'}]
        changed=project.revise(portable,source.sha(portable),edits);after=project.inspect_bytes(changed)
        predicted=copy.deepcopy(model);revision.locate(predicted,run_path)['text']='Ångström / precise colour / editable'
        check('disjoint original UTF-8 edits change only selected text',after['current']['document']==predicted)
        check('original bytes and baseline remain exact',after['members']['original.json']==data and after['members']['baseline.json']==data)
        cold('text-revised',after['members']['document.json'])
        style={'kind':'run.properties','path':run_path,'expected':None,'set':{'font':'Inter','size':32,'bold':True}}
        formatted=project.revise(changed,source.sha(changed),[style]);formatted_profile=project.inspect_bytes(formatted);formatted_model=formatted_profile['current']['document']
        before=copy.deepcopy(predicted);actual=copy.deepcopy(formatted_model);props=revision.locate(actual,run_path).pop('props')
        check('font revision changes only requested run properties',actual==before and props['font']=='Inter' and props['size']==32.0 and props['bold'] is True
              and all(value is None for key,value in props.items() if key not in ('font','size','bold')))
        cold('formatted',formatted_profile['members']['document.json'])
        shape_path='/slides/0/shapes/0';move={'kind':'shape.transform','path':shape_path,'expected':None,'value':{'x':80,'y':100,'w':800,'h':160}}
        metadata={'kind':'slide.properties','path':'/slides/0','expected':{'name':'','hidden':False},'set':{'name':'Direction','hidden':False}}
        moved=project.revise(formatted,source.sha(formatted),[move,metadata]);final=project.inspect_bytes(moved)
        predicted=copy.deepcopy(formatted_model);revision.locate(predicted,shape_path)['xfrm']={'x':80.0,'y':100.0,'w':800.0,'h':160.0};predicted['slides'][0]['name']='Direction'
        check('shape and slide changes retain complete unrelated model',final['current']['document']==predicted)
        deck=cold('positioned',final['members']['document.json']);png=out/'positioned.png';native('render',deck,png,0,1)
        check('portable history replays every typed revision',final['revision_count']==3 and final['replayed_edits']==5)
        check('all resources remain exact',final['current']['resources']==source.inspect_bytes(data,'json')['resources'])
        clear={'kind':'run.properties','path':run_path,'expected':revision.locate(predicted,run_path)['props'],'set':{'font':None,'size':None,'bold':None}}
        cleared=project.revise(moved,source.sha(moved),[clear]);cleared_profile=project.inspect_bytes(cleared)
        clear_prediction=copy.deepcopy(predicted);revision.locate(clear_prediction,run_path).pop('props')
        check('clearing explicit formatting restores inheritance without other changes',cleared_profile['current']['document']==clear_prediction)
        cold('inherited',cleared_profile['members']['document.json'])
        rich=copy.deepcopy(model);rich['slides'][0]['notes']['paragraphs']=[{'level':0,'runs':[{'text':'Speaker original'}]}]
        text_body=copy.deepcopy(rich['slides'][0]['shapes'][0]['text']);text_body['paragraphs']=[{'level':0,'runs':[{'text':'Cell original'}]}]
        kept_body=copy.deepcopy(text_body);kept_body['paragraphs'][0]['runs'][0]['text']='Keep me'
        rich['slides'][0]['shapes'][1]['text']=None
        rich['slides'][0]['shapes'][1]['kind']={'type':'table','cols':[360.0,360.0],'rows':[{'height':40.0,'cells':[
            {'text':text_body,'gridSpan':1,'rowSpan':1},{'text':kept_body,'gridSpan':1,'rowSpan':1}]}]}
        rich_input=out/'rich-input.json';rich_input.write_bytes(revision.encoded(rich));rich_deck=out/'rich.deckcraft'
        rich_native=native('encode',rich_input,rich_deck)['document'];rich_bytes=revision.encoded(rich_native)
        notes='/slides/0/notes/paragraphs/0/runs/0';cell='/slides/0/shapes/1/kind/rows/0/cells/0/text/paragraphs/0/runs/0'
        rich_edits=[{'kind':'text.replace','path':path,'start':text.encode().index(b'original'),'end':len(text.encode()),'expected':'original','value':'revised'}
                    for path,text in ((notes,'Speaker original'),(cell,'Cell original'))]
        rich_revision=revision.revise_bytes(rich_bytes,source.sha(rich_bytes),rich_edits)
        rich_prediction=copy.deepcopy(rich_native);revision.locate(rich_prediction,notes)['text']='Speaker revised';revision.locate(rich_prediction,cell)['text']='Cell revised'
        check('notes and table cell revisions preserve all other native fields',rich_revision['document']==rich_prediction)
        cold('rich-revised',rich_revision['data'])
        saved=out/'revised.dobeslides';saved.write_bytes(moved);check('portable cold read reproduces exact model',project.inspect_bytes(saved.read_bytes())['current']['document']==predicted)
        checkout=out/'checkout';report=project.checkout(out,checkout,moved)
        check('fixed portable checkout preserves every member',all((checkout/name).read_bytes()==value for name,value in final['members'].items()) and not report['engine_admission_complete'])
        count=0
        def cancelled():
            nonlocal count
            count+=1;return count>=3
        refused('cancelled checkout',lambda:project.checkout(out,out/'cancelled',moved,cancelled=cancelled))
        check('cancelled checkout removes only its new directory',not (out/'cancelled').exists() and checkout.exists())
        refused('existing checkout',lambda:project.checkout(out,checkout,moved))
        refused('escaped checkout',lambda:project.checkout(out,out/'../outside',moved))
        linked=out/'linked';linked.symlink_to(checkout,target_is_directory=True)
        refused('symlink checkout parent',lambda:project.checkout(out,linked/'new',moved))
        refused('foreign source lock',lambda:project.require_engine(final,{**engine,'source_lock_sha256':'0'*64}))
        refused('stale portable hash',lambda:project.revise(moved,'0'*64,edits))
        for label,edit in [('split UTF-8',{**edits[0],'start':1,'end':2,'expected':'x'}),('overlapping edits',[edits[0],edits[0]]),
                           ('wrong expected text',{**edits[0],'expected':'changed'}),('unknown owner',{**edits[0],'path':'/props/title'}),
                           ('multiline replacement',{**edits[0],'value':'first\nsecond'}),('boolean offset',{**edits[0],'start':True}),
                           ('unsupported kind',{**edits[0],'kind':[]}),('empty edits',[]),('competing text and format',[edits[0],style]),('no change',{**edits[0],'value':'original'}),
                           ('implicit inactive flip',{**move,'value':{**move['value'],'flipH':False}}),
                           ('clamped rotation',{**move,'value':{**move['value'],'rot':360}}),('unavailable transform key',{**move,'value':{'path':'other'}}),
                           ('font size overflow',{**style,'set':{'size':1e9}}),('unknown run property',{**style,'set':{'path':'elsewhere'}})]:
            batch=edit if type(edit) is list else [edit]
            refused(label,lambda batch=batch:revision.revise_bytes(data,source.sha(data),batch))
        field_model=copy.deepcopy(model);revision.locate(field_model,run_path)['kind']={'kind':'field','field':'slidenum'}
        field_data=revision.encoded(field_model);refused('cached field text edit',lambda:revision.revise_bytes(field_data,source.sha(field_data),edits))
        damaged=copy.deepcopy(final['manifest']);members={name:value for name,value in final['members'].items() if name!='project.json'}
        tampered=dict(members);tampered['document.json']=initial['members']['document.json']
        damaged['members']['document.json']=project.record(tampered['document.json'])
        refused('current model detached from history',lambda:project.inspect_bytes(project.pack(damaged,tampered)))
        wrong_original=dict(members);wrong_original['original.json']=b'{}';wrong=copy.deepcopy(final['manifest']);wrong['members']['original.json']=project.record(b'{}')
        refused('replacement original',lambda:project.inspect_bytes(project.pack(wrong,wrong_original)))
        wrong=copy.deepcopy(final['manifest']);wrong['history'][0]['before']='0'*64
        refused('broken predecessor chain',lambda:project.inspect_bytes(project.pack(wrong,members)))
        wrong=copy.deepcopy(final['manifest']);wrong['history'][0]['after']='0'*64
        refused('broken result chain',lambda:project.inspect_bytes(project.pack(wrong,members)))
        check('all fixture and original project bytes remain unchanged',args.fixture.read_bytes()==original and project.inspect_bytes(portable)['members']['original.json']==data)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':calls,'portable_bytes':len(moved),'revision_count':3,'replayed_edits':5,
                  'exact_native_models':True,'originals_immutable':True,'durable_publication_qualified':False,'engine_admission_complete':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'checks':len(checks),'refusals':len(refusals),'native_calls':calls}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':calls},indent=2)+'\n');raise


if __name__=='__main__':main()
