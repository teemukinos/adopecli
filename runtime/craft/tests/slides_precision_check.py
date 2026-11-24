#!/usr/bin/env python3
"""Compare predicted PPTX numeric changes with actual XML and cold native output."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import slides_precision as precision, slides_pptx as pptx, slides_revision as revision
from studio_runtime import slides_engine, slides_binding, slides_source as source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'model', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    model_bytes = args.model.read_bytes(); model = source.strict_json(model_bytes); checks = []; reports = []
    native = slides_engine.Engine(args.engine.resolve(), out, expected_pin=slides_binding.PIN,
                                 expected_binary_sha256=hashlib.sha256(args.engine.read_bytes()).hexdigest())
    def check(label, value):
        if not value: raise AssertionError(label)
        checks.append(label)
    def exercise(name, document):
        data = revision.encoded(document); path = out/(name+'.json'); path.write_bytes(data)
        report = precision.inspect(data); (out/(name+'-precision.json')).write_text(json.dumps(report, indent=2)+'\n')
        native._snapshot(native._run('encode', path, out/(name+'.deckcraft')), document)
        native._run('convert', out/(name+'.deckcraft'), out/(name+'.pptx'), 'pptx')
        inspected = pptx.inspect_bytes((out/(name+'.pptx')).read_bytes())
        reopened = source.strict_json(native._run('snapshot', out/(name+'.pptx')))['document']
        (out/(name+'-reopened.json')).write_text(json.dumps(reopened, indent=2)+'\n')
        for item in report['changes']:
            if item['source_unit'] == 'alpha-byte': continue
            actual = revision.locate(reopened, item['path'])
            check(name+' exact numeric prediction '+item['path'], actual == item['native_reopen_value'])
        check(name+' source remains byte-exact', path.read_bytes() == data and report['source_model_sha256'] == source.sha(data))
        check(name+' does not claim full semantic or rendered fidelity', not report['complete_semantic_projection'] and not report['source_format_fidelity_qualified'] and not report['conversion_performed'])
        reports.append({'case': name, 'change_count': report['change_count'], 'clamp_count': report['clamp_count']})
        return report, inspected, reopened
    try:
        original, package, reopened = exercise('original', model)
        check('original predicts only the observed title precision change', len(original['changes']) == 1 and original['changes'][0]['source_value'] == 48.828125 and original['changes'][0]['converted_value'] == 48.83)
        changed = copy.deepcopy(model); changed['slideSize']['width'] = 960.000123; changed['notesSize']['height'] = 720.000123
        shape = changed['slides'][0]['shapes'][2]; shape['xfrm'].update(x=-1.125, y=48.000123, w=800.000123, h=100.000123, rot=359.9999999)
        body = shape['text']; body['body'].update(insetL=.000123, rot=12.3456789, colSpacing=1.23456789)
        para = body['paragraphs'][0]; para['props'].update(marginLeft=-.25, marginRight=12.000123, indent=-1.125, defaultTab=12.345678,
            lineSpacing={'kind':'pct','v':200.0}, spaceBefore={'kind':'pts','v':1.125}, spaceAfter={'kind':'pct','v':120.0})
        para['runs'][0]['props'].update(spacing=-1.125, kern=1.125, baseline=.000006)
        para['defProps'] = dict.fromkeys(revision.RUN_FIELDS); para['defProps']['size'] = 20.12345; para['defProps']['baseline'] = .123456789
        para['endProps'] = dict.fromkeys(revision.RUN_FIELDS); para['endProps']['spacing'] = .004999999999999999
        changed['slides'][1]['notes']['paragraphs'][0]['runs'][0]['props'] = dict.fromkeys(revision.RUN_FIELDS)
        changed['slides'][1]['notes']['paragraphs'][0]['runs'][0]['props']['size'] = 12.34567
        numbers, package, reopened = exercise('numeric-fields', changed)
        paths = {item['path']: item for item in numbers['changes']}
        check('native clamps are distinct from simple rounding', numbers['clamp_count'] == 3)
        check('fixed native reader retains the full exported percentage', numbers['native_reader_clamp_count'] == 0 and paths['/slides/0/shapes/2/text/paragraphs/0/props/lineSpacing/v']['converted_value'] == 132 and paths['/slides/0/shapes/2/text/paragraphs/0/props/lineSpacing/v']['native_reopen_value'] == 132)
        check('fixed native reader does not clamp a representable percentage', '/slides/0/shapes/2/text/paragraphs/0/props/spaceAfter/v' not in paths and reopened['slides'][0]['shapes'][2]['text']['paragraphs'][0]['props']['spaceAfter']['v'] == 120)
        a = '{'+pptx.DRAWING[0]+'}'; p = '{'+pptx.PRESENTATION[0]+'}'
        tree = package['xml'][package['slides'][0]['part']]['root']; shape = tree.find(p+'cSld').find(p+'spTree').findall(p+'sp')[2]
        props = shape.find(p+'txBody').find(a+'p').find(a+'pPr')
        check('actual XML independently confirms exported percentage retained by fixed reader', int(props.find(a+'lnSpc').find(a+'spcPct').get('val')) == 13200000 and int(props.find(a+'spcAft').find(a+'spcPct').get('val')) == 12000000)
        check('negative half-centipoint rounds away from zero', paths['/slides/0/shapes/2/text/paragraphs/0/runs/0/props/spacing']['converted_value'] == -1.13)
        check('value immediately below half does not round up', paths['/slides/0/shapes/2/text/paragraphs/0/endProps/spacing']['converted_value'] == 0)
        # Exercise the complete byte-alpha domain in one real native conversion.
        alpha_model = copy.deepcopy(model); alpha_model['slides'] = [alpha_model['slides'][0]]
        seed = copy.deepcopy(alpha_model['slides'][0]['shapes'][0]); seed['text'] = None
        alpha_model['slides'][0]['shapes'] = []
        for value in range(256):
            shape = copy.deepcopy(seed); shape['id'] = 1000+value; shape['fill']['color']['base']['rgb']['a'] = value
            alpha_model['slides'][0]['shapes'].append(shape)
        alpha_model['nextId'] = 1256
        alphas, package, reopened = exercise('alpha-domain', alpha_model)
        p = '{'+pptx.PRESENTATION[0]+'}'; a = '{'+pptx.DRAWING[0]+'}'
        tree = package['xml'][package['slides'][0]['part']]['root']; shapes = tree.find(p+'cSld').find(p+'spTree').findall(p+'sp')
        changes = {item['path']: item for item in alphas['changes']}
        for value, shape in enumerate(shapes):
            color = shape.find(p+'spPr').find(a+'solidFill').find(a+'srgbClr'); alpha = color.find(a+'alpha')
            encoded = 100000 if alpha is None else int(alpha.get('val'))
            check('actual XML alpha byte '+str(value), encoded == value*100000//255)
            item = changes.get('/slides/0/shapes/'+str(value)+'/fill/color/base/rgb/a')
            check('reported alpha change '+str(value), (item is None and encoded*255/100000 == value) or item is not None and item['encoded_integer'] == encoded and item['converted_value'] == encoded*255/100000)
        check('all 256 source alpha values were exported', len(shapes) == 256 and alphas['change_count'] == 250)
        check('input fixture remains byte-exact', args.model.read_bytes() == model_bytes)
        evidence = {'passed': True, 'checks': checks, 'cases': reports, 'native_calls': native.calls,
                    'source_unchanged': True, 'public_pptx_delivery': False, 'complete_semantic_projection': False,
                    'remote_actions': False, 'goal_complete': False}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n'); print(json.dumps({'checks':len(checks),'native_calls':native.calls,'cases':reports}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'cases':reports,'native_calls':native.calls},indent=2)+'\n'); raise


if __name__ == '__main__': main()
