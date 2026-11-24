#!/usr/bin/env python3
"""Qualify Write page/settings values and exact native page setup revisions."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_container as container, write_structure as structure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--rich-fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    source = args.fixtures/'brief.json'; original = source.read_bytes(); base = container.strict_json(original)
    rich = container.strict_json((args.rich_fixtures/'rich.json').read_bytes())
    checks = []; refusals = []; calls = []; started = time.monotonic()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=90)
        index = len(calls); calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout) if result.stdout.strip() else None

    def refused(label, change, fixture=base):
        doc = copy.deepcopy(fixture); change(doc); before = copy.deepcopy(doc)
        try: structure.inspect(doc)
        except ValueError as error: refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)
        check(doc == before, label+' refused without repair')

    def old_section(doc):
        old = copy.deepcopy(doc['lastSection'])
        doc['revisions'] = [{'kind': 'format', 'author': 'Fixture', 'date': '2026-11-16T00:00:00Z'}]
        doc['lastSection']['fmtChange'] = {'rev': 0, 'old': old}
        return old

    try:
        check(structure.inspect(base)['metadata']['custom_properties'] == ['Project'], 'original custom property inventoried')
        for key, value in [('future', True), ('landscape', 1), ('header', -1), ('footerGap', 1585),
                           ('chapterStyle', 0), ('chapterSep', 'dash'), ('pageNumFormat', 'roman'), ('valign', 'both'),
                           ('pageNumStart', True), ('paperSrcFirst', 65536), ('footnoteColumns', 46),
                           ('lineNumbers', {'countBy': 0}), ('lineNumbers', {'distance': -1}),
                           ('docGrid', {'linePitch': .5}), ('docGrid', {'charSpace': 1.5}),
                           ('docGrid', {'charSpace': 1584*4096+1}), ('footnotePr', {'numRestart': 'everyPage'})]:
            refused('invalid section '+key+' '+repr(value), lambda d, k=key, v=value: d['lastSection'].update({k: v}))
        refused('46 columns exceed native count', lambda d: d['lastSection']['columns'].update(count=46, space=0))
        refused('equal columns would clamp their widths', lambda d: d['lastSection']['columns'].update(count=30, space=0))
        refused('explicit column would clamp width', lambda d: d['lastSection']['columns'].update(count=2, widths=[[17, 10], [100, 0]]))
        refused('old section unknown field', lambda d: old_section(d).update(future=True))
        refused('old section has bad geometry', lambda d: old_section(d).update(marginLeft=1000))
        refused('old section has missing header', lambda d: old_section(d)['headers'].update(default=999))
        refused('old section has wrong story kind', lambda d: old_section(d)['headers'].update(default=1))
        for key, value in [('future', False), ('trackChanges', 'true'), ('defaultTab', 1), ('gridH', 0),
                           ('hyphenationZone', -1), ('majorFont', ''), ('themeColors', [[0, 0, 256]]),
                           ('romanFonts', ['Aptos', 1]), ('attachedTemplate', 'file:///tmp/template.dotm'),
                           ('linkStyles', True), ('protectHash', [['hash', 'a'], ['hash', 'b']]),
                           ('protection', 'unrestricted'), ('zoom', {'percent': 0}), ('zoom', {'fit': 'fullscreen'}),
                           ('odf', {'tabsFromIndent': 1}), ('watermark', {'size': [0, 10]}),
                           ('pagePicture', {'media': 'missing', 'fill_type': 'frame'}), ('math', [])]:
            refused('invalid setting '+key, lambda d, k=key, v=value: d['settings'].update({k: v}))
        refused('page background uses wrong serialized key', lambda d: d['settings'].update(pagePicture={'media': next(iter(d['media'])), 'fillType': 'tile'}))
        refused('core revision has wrong type', lambda d: d['core'].update(revision=True))
        refused('unknown core property', lambda d: d['core'].update(externalTemplate='remote'))
        refused('duplicate custom properties', lambda d: d['customProps'].append(copy.deepcopy(d['customProps'][0])))
        refused('custom property is not text', lambda d: d['customProps'][0].update(value=[]))
        refused('duplicate bibliography tag', lambda d: d.update(sources=[{'tag': 'source'}, {'tag': 'source'}]))
        refused('style boolean disguised as integer', lambda d: d['styles']['styles'][0].update(quick=1))
        refused('style priority negative', lambda d: d['styles']['styles'][0].update(priority=-1))
        refused('latent XML is not text', lambda d: d['styles'].update(latentStyles=[]))
        for key, value in [('format', 'unknown'), ('align', 'middle'), ('suffix', 'none'), ('restart', 1), ('legal', None), ('tab', 1585)]:
            refused('invalid list level '+key, lambda d, k=key, v=value: d['numbering']['abstracts'][0]['levels'][0].update({k: v}), rich)
        refused('unknown list type', lambda d: d['numbering']['abstracts'][0].update(multi_level_type='unknown'), rich)
        refused('list name not text', lambda d: d['numbering']['abstracts'][0].update(name=[]), rich)

        valid = copy.deepcopy(base); old_section(valid)
        valid['settings'].update(defaultTab=2, trackChanges=False, protection='readOnly', protectFormatting=True,
                                 protectHash=[['hash', 'retained']], majorFont='Aptos', romanFonts=['Aptos'],
                                 pagePicture={'media': next(iter(valid['media'])), 'fill_type': 'tile', 'title': 'Original tile'},
                                 watermark={'text': 'DRAFT', 'font': 'Aptos', 'color': [80, 80, 80], 'diagonal': True, 'semitransparent': False, 'size': [200, 60]},
                                 autoHyphenation=True, math={}, zoom={'percent': 100, 'fit': 'pageWidth'}, odf={'tabsFromIndent': False})
        valid['lastSection'].update(pageNumStart=0, footnoteColumns=0, paperSrcFirst=0, chapterStyle=9,
                                    lineNumbers={'countBy': 1, 'start': 1, 'distance': 0, 'restart': 'section'},
                                    docGrid={'type': 'linesAndChars', 'linePitch': 18, 'charSpace': -4096})
        valid['lastSection']['columns'].update(count=2, space=0, widths=[[18, 0], [100, 0]])
        valid['sources'] = [{'tag': 'source', 'title': 'Original source', 'url': 'https://example.test/reference'}]
        valid['customProps'].append({'name': 'Raw', 'kind': 'raw', 'value': '<retained/>', 'linkTarget': 'source', 'odfUserField': False})
        valid['styles']['latentStyles'] = '<retained/>'
        before = copy.deepcopy(valid); report = structure.inspect(valid)
        check(valid == before, 'valid page settings and retained payloads remain exact')
        check(report['counts']['sections'] == 2, 'tracked old section receives independent recursive validation')
        check(report['metadata']['page_picture_media'] == [next(iter(valid['media']))], 'page background enters owned resource inventory')
        check({'document-protection', 'page-picture-layout', 'watermark-layout', 'resolved-document-grid', 'number-label-fidelity',
               'math-settings', 'typed-custom-properties', 'custom-property-bookmark', 'latent-style-xml', 'hyphenation-resource-isolation'}
              <= set(report['pending_qualification']), 'unsupported semantics remain explicit admission gates')
        check(not report['engine_admission_complete'], 'settings checks do not grant native execution or protected editing')

        edited = out/'page-setup.json'
        call('run', '--file', source.resolve(), '--cmd', 'caret.set={"pos":{"story":"body","path":[0],"off":0}}',
             '--cmd', 'layout.margins={"left":54,"right":54}',
             '--cmd', 'layout.columns={"count":2,"space":24,"separator":true,"apply":"section"}',
             '--cmd', 'layout.pageNumberFormat={"format":"upperRoman","start":7}',
             '--cmd', 'layout.documentGrid={"type":"linesAndChars","linePitch":18,"charSpace":1024}',
             '--cmd', 'layout.differentOddEven={"value":true}', '--save', edited)
        actual = container.strict_json(edited.read_bytes()); structure.inspect(actual)
        expected = copy.deepcopy(base); expected['lastSection'].update(marginLeft=54, marginRight=54,
            columns={'count': 2, 'space': 24, 'separator': True, 'widths': []}, pageNumFormat='upperRoman', pageNumStart=7,
            docGrid={'type': 'linesAndChars', 'linePitch': 18, 'charSpace': 1024})
        expected['settings']['evenOddHeaders'] = True
        check(actual['core']['revision'] == base['core']['revision']+1, 'page setup save increments revision once')
        expected['core']['revision'] += 1; expected['core']['modified'] = actual['core']['modified']
        (out/'expected.json').write_text(json.dumps(expected, indent=2)+'\n')
        check(actual == expected, 'complete predicted page setup changes only explicit section settings and save metadata')
        check(call('snapshot', edited)['document'] == actual, 'page setup survives complete cold native reopen')
        call('render', edited, out/'page-setup.png', '--strict', '--scale', '1')
        with Image.open(out/'page-setup.png') as image:
            image.load(); check(image.format == 'PNG' and image.size == (596, 842), 'strict revised page raster decodes as A4')
            with Image.open(args.fixtures/'native.png') as baseline:
                baseline.load(); check(image.convert('RGB').tobytes() != baseline.convert('RGB').tobytes(), 'requested page setup changes visible raster')
        check(source.read_bytes() == original, 'original native document remains byte-identical')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'scope': 'typed page settings, style/list metadata, recursive section history and exact page revision; full resource/source-format/runtime qualification remains open',
                    'engine_admission_complete': False, 'remote_actions': False}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally: (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
