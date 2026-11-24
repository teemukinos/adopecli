#!/usr/bin/env python3
"""Verify complete native container reconstruction against actual Slides output."""
import argparse
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','fixture','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import slides_source as source
    checks=[];refusals=[];calls=0;exe=args.engine.resolve()
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def native(*arguments):
        nonlocal calls
        calls+=1;result=subprocess.run([str(exe),*map(str,arguments)],capture_output=True,timeout=120)
        (out/f'native-{calls}.stdout').write_bytes(result.stdout);(out/f'native-{calls}.stderr').write_bytes(result.stderr)
        check('actual native call succeeded',result.returncode==0);return json.loads(result.stdout)
    def archive(members):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,value in members.items():z.writestr(name,value,compress_type=zipfile.ZIP_STORED if name=='mimetype' else zipfile.ZIP_DEFLATED)
        return data.getvalue()
    def refused(label,data,kind='deckcraft'):
        try:source.inspect_bytes(data,kind)
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def mutated(checked,change):
        members=dict(checked['members']);manifest=copy.deepcopy(checked['manifest']);change(manifest['presentation'])
        members['presentation.json']=json.dumps(manifest).encode();return archive(members)
    try:
        data=args.fixture.read_bytes();checked=source.inspect_bytes(data,'deckcraft');cold=native('snapshot',args.fixture)
        check('independent whole model reconstruction equals actual native snapshot',checked['document']==cold['document'])
        check('original container and every raw member remain authoritative',checked['source_bytes']==data and checked['source_sha256']==source.sha(data)
              and source.inspect_bytes(archive(checked['members']),'deckcraft')['members']==checked['members'])
        encoded=json.dumps(checked['document']).encode();model=source.inspect_bytes(encoded,'json')
        check('explicit JSON media identity equals native package',model['document']==checked['document'] and model['resources']==checked['resources'])
        check('inspection grants no native permission',not checked['engine_admission_complete'] and 'native-full-model-comparison' in checked['pending_qualification'])
        # Let the real engine materialize full chart defaults. Source prediction
        # then independently restores every separate payload across native owners.
        doc=copy.deepcopy(checked['document']);payload=b'owned chart payload\x00\xff'
        shape=copy.deepcopy(doc['slides'][0]['shapes'][0]);shape['text']=None
        shape['kind']={'type':'chart','kept':{'rels':[],'parts':[{'name':'ppt/embeddings/owned.bin','contentType':'application/octet-stream','bytes':list(payload)}]}}
        doc['slides'][0]['shapes'][0]=copy.deepcopy(shape)
        doc['masters'][0]['layouts'][0]['shapes'][0]['kind']=copy.deepcopy(shape['kind'])
        doc['notesMaster']=copy.deepcopy(doc['masters'][0]);doc['notesMaster']['layouts']=[]
        doc['notesMaster']['shapes']=[copy.deepcopy(shape)]
        doc['handoutMaster']=copy.deepcopy(doc['notesMaster'])
        group=copy.deepcopy(shape);doc['nextId']+=1;group['id']=doc['nextId']
        group['kind']={'type':'group','children':[copy.deepcopy(shape)],'child':{'x':0.0,'y':0.0,'w':960.0,'h':540.0}}
        doc['slides'][0]['shapes'][0]=group
        payloads=[]
        for number,(_,part) in enumerate(source.structure(doc)['chart_parts']):
            owned=payload+bytes([number]);part['bytes']=list(owned);payloads.append(owned)
        input_=out/'charts.json';input_.write_text(json.dumps(doc));fixture=out/'charts.deckcraft'
        expected=native('encode',input_,fixture)['document'];charts=source.inspect_bytes(fixture.read_bytes(),'deckcraft')
        check('chart sidecars on slides, layouts, notes and handout masters reconstruct exactly',charts['document']==expected
              and len([r for r in charts['resources'] if r['kind']=='chart'])==4)
        check('chart reconstruction matches cold native reopening',native('snapshot',fixture)['document']==charts['document'])
        check('original chart sidecar bytes are exact',{charts['members'][name] for name in charts['members'] if name.startswith('chart-parts/')}==set(payloads))
        # Native reader also supports older inline chart bytes. Preserve that
        # representation in original container and predict the same runtime model.
        inline_members=dict(charts['members']);inline_manifest=copy.deepcopy(charts['manifest'])
        for _,part in source.structure(inline_manifest['presentation'])['chart_parts']:
            part['bytes']=list(inline_members.pop(part.pop('nativeEntry')))
        inline_members['presentation.json']=json.dumps(inline_manifest).encode();inline=archive(inline_members)
        inline_file=out/'inline.deckcraft';inline_file.write_bytes(inline);inline_checked=source.inspect_bytes(inline,'deckcraft')
        check('legacy inline chart payloads remain exact and match native model',inline_checked['document']==charts['document']
              and native('snapshot',inline_file)['document']==inline_checked['document'])
        linked=copy.deepcopy(checked['document']);linked['media'][0]['link']='https://example.invalid/never-fetch.png';linked['media'][0]['dataHex']=''
        link_result=source.inspect_bytes(json.dumps(linked).encode(),'json')
        check('external link is retained but never grants loading permission','external-media-link-policy' in link_result['pending_qualification'] and not link_result['engine_admission_complete'])
        future=copy.deepcopy(checked['document']);future['futureFeature']={'scalar':1e100}
        future_result=source.inspect_bytes(json.dumps(future).encode(),'json')
        check('unknown fields and finite binary64 values are retained for later refusal or qualification',future_result['document']==future and future_result['unknown_model_fields']==['futureFeature'])
        compressed=io.BytesIO()
        with zipfile.ZipFile(compressed,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,value in checked['members'].items():z.writestr(name,value)
        compressed_checked=source.inspect_bytes(compressed.getvalue(),'deckcraft')
        compressed_file=out/'compressed-mime.deckcraft';compressed_file.write_bytes(compressed.getvalue())
        check('compressed MIME source opens without reordering or rewriting originals',compressed_checked['document']==checked['document']
              and native('snapshot',compressed_file)['document']==compressed_checked['document'])
        reordered={key:value for key,value in checked['members'].items() if key!='mimetype'};reordered['mimetype']=checked['members']['mimetype']
        reordered_file=out/'reordered-mime.deckcraft';reordered_file.write_bytes(archive(reordered))
        check('MIME member need not be first',native('snapshot',reordered_file)['document']==checked['document'])
        refused('unknown source format',data,'pptx')
        refused('duplicate JSON keys',b'{"a":1,"a":2}','json')
        refused('nonfinite JSON',b'{"a":NaN}','json')
        refused('invalid Unicode',b'{"a":"\\ud800"}','json')
        refused('invalid MIME',archive({**checked['members'],'mimetype':b'wrong'}))
        refused('unowned payload',archive({**checked['members'],'unexpected.bin':b'do not discard'}))
        missing=dict(checked['members']);missing.pop(next(n for n in missing if n.startswith('media/')));refused('missing owned media',archive(missing))
        refused('repeated media identity',mutated(checked,lambda d:d['media'].append(copy.deepcopy(d['media'][0]))))
        refused('reserved observed media field',mutated(checked,lambda d:d['media'][0].update(dataHex='00')))
        refused('replacement master',mutated(checked,lambda d:d.update(masters=[])))
        refused('missing layout',mutated(checked,lambda d:d['slides'][0].update(layout=4294967295)))
        refused('duplicate slide identity',mutated(checked,lambda d:d['slides'].append(copy.deepcopy(d['slides'][0]))))
        refused('duplicate shape in story',mutated(checked,lambda d:d['slides'][0]['shapes'].append(copy.deepcopy(d['slides'][0]['shapes'][0]))))
        refused('stale next identity',mutated(checked,lambda d:d.update(nextId=0)))
        refused('clamped slide size',mutated(checked,lambda d:d['slideSize'].update(width=9000)))
        refused('boolean identity',mutated(checked,lambda d:d['slides'][0].update(id=True)))
        chart_name=next(n for n in charts['members'] if n.startswith('chart-parts/'));missing=dict(charts['members']);missing.pop(chart_name)
        refused('missing chart member',archive(missing))
        def double_chart(d):
            parts=source.structure(d)['chart_parts'];parts[1][1]['nativeEntry']=parts[0][1]['nativeEntry']
        refused('shared native chart owner',mutated(charts,double_chart))
        def ambiguous_chart(d):source.structure(d)['chart_parts'][0][1]['bytes']=[1]
        refused('inline and external chart payload',mutated(charts,ambiguous_chart))
        def bad_chart(d):source.structure(d)['chart_parts'][0][1]['nativeEntry']='chart-parts/00'
        refused('noncanonical chart reference',mutated(charts,bad_chart))
        invalid_inline=copy.deepcopy(charts['document']);source.structure(invalid_inline)['chart_parts'][0][1]['bytes']=[True]
        refused('boolean inline chart byte',json.dumps(invalid_inline).encode(),'json')
        bad=copy.deepcopy(checked['document']);bad['media'][0]['dataHex']='AA';refused('noncanonical media bytes',json.dumps(bad).encode(),'json')
        duplicate=io.BytesIO()
        with zipfile.ZipFile(duplicate,'w') as z:
            for name,value in checked['members'].items():z.writestr(name,value)
            z.writestr('MEDIA/'+str(checked['document']['media'][0]['id']),b'collision')
        refused('case-colliding archive namespace',duplicate.getvalue())
        source.check_preservation(checked,data)
        try:source.check_preservation(checked,archive(checked['members']))
        except ValueError:check('equivalent repacking cannot replace original source bytes',True)
        else:raise AssertionError('repacked original accepted')
        symlink=out/'linked-input';symlink.symlink_to(args.fixture.resolve())
        try:source.read_source(symlink,'deckcraft')
        except ValueError:check('input symlink refused',True)
        else:raise AssertionError('symlink accepted')
        check('all original fixture bytes remain unchanged',args.fixture.read_bytes()==data)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':calls,'complete_model_prediction':True,'chart_sidecar_owners':4,
                  'source_bytes_unchanged':True,'engine_admission_complete':False,'public_runtime_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'checks':len(checks),'refusals':len(refusals),'native_calls':calls}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':calls},indent=2)+'\n');raise


if __name__=='__main__':main()
