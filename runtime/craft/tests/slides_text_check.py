#!/usr/bin/env python3
"""Qualify actual Slides overflow, font identity and missing-glyph observations."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','native-source','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import slides_text as text,slides_source as source,slides_revision as revision,slides_engine,slides_binding
    checks=[];refusals=[];calls=0;exe=args.engine.resolve();original=args.native_source.read_bytes();(out/'source.deckcraft').write_bytes(original)
    model=source.inspect_bytes(original,'deckcraft')['document'];engine=slides_engine.Engine(exe,out,expected_pin=slides_binding.PIN,expected_binary_sha256=source.sha(exe.read_bytes()))
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def native(*arguments):
        nonlocal calls
        calls+=1;r=subprocess.run([str(exe),*map(str,arguments)],capture_output=True,timeout=120)
        (out/f'native-{calls}.stdout').write_bytes(r.stdout);(out/f'native-{calls}.stderr').write_bytes(r.stderr)
        check('native operation '+str(calls)+' succeeded',r.returncode==0);return r.stdout
    def fixture(name,change):
        value=copy.deepcopy(model);change(value['slides'][0]['shapes'][2]);data=revision.encoded(value);path=out/(name+'.json');path.write_bytes(data)
        deck=out/(name+'.deckcraft');native('encode',path,deck)
        report=engine.observe_text(deck,deck.read_bytes(),0);(out/(name+'-report.json')).write_text(json.dumps(report,indent=2)+'\n')
        return report
    def pack(header,raw):
        encoded=revision.encoded(header);return b'DOBESLY1'+len(encoded).to_bytes(4,'little')+encoded+raw
    try:
        packet=None;reports=[]
        for index,slide in enumerate(model['slides']):
            first=native('text-layout',out/'source.deckcraft',index);second=native('text-layout',out/'source.deckcraft',index)
            check('slide '+str(index)+' has identical cold native layout/font packets',first==second)
            report=text.inspect(first);text.require_clear(report);reports.append(report)
            expected={shape['id']:[ ''.join(run['text'] for run in paragraph['runs']) for paragraph in shape['text']['paragraphs'] ]
                      for shape in slide['shapes'] if shape.get('text') and not shape['hidden']}
            observed={body['owner']:body['paragraphs'] for body in report['texts']}
            check('slide '+str(index)+' owns every expected native text body exactly',observed==expected and len(observed)==len(report['texts']))
            check('slide '+str(index)+' uses exact pinned fonts without synthetic styles',report['actual_font_bytes_verified'] and all(f['source']=='pinned-built-in' and f['family']=='Inter' for f in report['faces']))
            check('slide '+str(index)+' keeps unqualified coverage boundaries explicit',not report['complete_render_coverage'] and not report['independent_shaping_qualified'] and not report['engine_admission_complete'])
            (out/f'slide-{index}-report.json').write_text(json.dumps(report,indent=2)+'\n')
            if index==0:packet=first
        observer=engine.observe_text(out/'source.deckcraft',original,0)
        check('receipt-bound transport reproduces independently parsed native packet',observer==reports[0])
        tall=fixture('vertical-overflow',lambda shape:shape['text']['paragraphs'][0]['runs'][0].update(text='A long presentation title. '*60))
        check('actual native layout detects vertical overflow',any(i['kind']=='vertical-overflow' for i in tall['issues']))
        refused('vertical overflow delivery',lambda:text.require_clear(tall))
        def wide(shape):
            shape['text']['body']['wrap']=False;shape['text']['paragraphs'][0]['runs'][0]['text']='W'*200
        width=fixture('horizontal-overflow',wide)
        check('actual line extents detect horizontal overflow',any(i['kind'] in ('horizontal-overflow','line-outside-horizontal-box') for i in width['issues']))
        refused('horizontal overflow delivery',lambda:text.require_clear(width))
        outside=fixture('outside-slide',lambda shape:shape['xfrm'].update(x=1000.0))
        check('actual transformed text detects placement outside the slide',any(i['kind']=='line-outside-slide' for i in outside['issues']))
        refused('outside slide delivery',lambda:text.require_clear(outside))
        def shrink(shape):shape['text']['body']['autofit']={'kind':'shrink','font_scale':.5,'line_reduction':.1}
        reduced=fixture('shrink',shrink)
        check('saved automatic font scaling is visible',any(i['kind']=='automatic-text-shrink' for i in reduced['issues']))
        refused('silent shrink delivery',lambda:text.require_clear(reduced))
        missing=fixture('missing-glyph',lambda shape:shape['text']['paragraphs'][0]['runs'][0].update(text='Missing \U0010ffff'))
        check('actual missing glyph zero is detected',any(i['kind']=='missing-glyph' for i in missing['issues']))
        refused('missing glyph delivery',lambda:text.require_clear(missing))
        size=int.from_bytes(packet[8:12],'little');header=source.strict_json(packet[12:12+size]);raw=packet[12+size:]
        for label,mutate in [('boolean schema',lambda h:h.update(schemaVersion=True)),('complete render claim',lambda h:h.update(completeRenderCoverage=True)),
            ('wrong aggregate glyph count',lambda h:h.update(glyphCount=h['glyphCount']+1)),('wrong aggregate line count',lambda h:h.update(lineCount=h['lineCount']+1)),
            ('unowned font offset',lambda h:h['faces'][0].update(offset=1)),('font name spoof',lambda h:h['faces'][0].update(family='Different family')),
            ('collection face',lambda h:h['faces'][0].update(index=1)),('variable font identity',lambda h:h['faces'][0].update(coordinates=[[[119,103,104,116],700]])),
            ('invalid paragraph owner',lambda h:h['texts'][0]['lines'][0].update(paragraph=99999)),
            ('invalid glyph index',lambda h:h['texts'][0]['runs'][0]['glyphs'][0].__setitem__(0,999999)),
            ('cell text mismatch',lambda h:h['texts'][0]['runs'][0]['cells'][0].__setitem__(1,'!')),
            ('nonfinite geometry',lambda h:h['texts'][0].update(contentWidth=float('inf'))),
            ('reversed text box',lambda h:h['texts'][0].update(inner=[1,0,0,10]))]:
            bad=copy.deepcopy(header);mutate(bad)
            refused(label,lambda bad=bad:text.inspect(pack(bad,raw)))
        refused('unowned font bytes',lambda:text.inspect(pack(header,bytes([raw[0]^1])+raw[1:])))
        refused('trailing packet bytes',lambda:text.inspect(packet+b'x'))
        refused('short header',lambda:text.inspect(b'DOBESLY1'+(200).to_bytes(4,'little')+b'{}'))
        refused('stale native source bytes',lambda:engine.observe_text(out/'source.deckcraft',original+b'x',0))
        refused('boolean slide selection',lambda:engine.observe_text(out/'source.deckcraft',original,True))
        check('all original native bytes remain exact',args.native_source.read_bytes()==original and (out/'source.deckcraft').read_bytes()==original)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':calls+engine.calls,'source_sha256':source.sha(original),
                  'slides':len(reports),'glyphs':sum(r['glyph_count'] for r in reports),'native_vertical_overflow':True,'native_horizontal_overflow':True,
                  'native_saved_shrink':True,'native_missing_glyph':True,'actual_pinned_font_bytes':True,'cold_packets_identical':True,
                  'complete_render_coverage':False,'independent_shaping_qualified':False,'engine_admission_complete':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'checks':len(checks),'refusals':len(refusals),'native_calls':evidence['native_calls'],'glyphs':evidence['glyphs']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':calls+engine.calls},indent=2)+'\n');raise


if __name__=='__main__':main()
