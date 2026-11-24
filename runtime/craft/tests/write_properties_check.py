#!/usr/bin/env python3
"""Check formatting rejection and precise native edits without repairing sources."""
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
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; calls = []; started = time.monotonic()
    source = args.fixtures/'brief.json'; original = source.read_bytes(); base = container.strict_json(original)

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=90)
        index = len(calls); calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout) if result.stdout.strip() else None

    def refused(label, change):
        doc = copy.deepcopy(base); change(doc); encoded = json.dumps(doc, ensure_ascii=False)
        try: structure.inspect(doc)
        except ValueError as error: refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)
        check(json.dumps(doc, ensure_ascii=False) == encoded, label+' refused without repair')

    def char(doc): return doc['body'][2]['runs'][1].setdefault('props', {})
    def para(doc): return doc['body'][2].setdefault('props', {})
    def table(doc): return next(b for b in doc['body'] if b['kind'] == 'table')
    def row(doc): return table(doc)['rows'][0].setdefault('props', {})
    def cell(doc): return table(doc)['rows'][0]['cells'][0]['props']
    def style(doc): return next(s for s in doc['styles']['styles'] if s['kind'] == 'table')['table']

    try:
        report = structure.inspect(base)
        check(report['properties']['counts']['character'] > 63, 'character properties include native styles and editable runs')
        check(not report['engine_admission_complete'], 'formatting values alone never authorize native execution')
        for kind, getter in [('character', char), ('paragraph', para), ('table', lambda d: table(d)['props']), ('row', row), ('cell', cell)]:
            refused('unknown '+kind+' property', lambda d, get=getter: get(d).update(misspelledValue=True))
        for key, value in [('size', 0), ('size', 1639), ('size', True), ('sizeCs', -1), ('scale', 601), ('spacing', 101),
                           ('position', -801), ('kern', -1), ('bold', 1), ('underline', 'wavyDouble'), ('font', ''),
                           ('font', 'Family\nInjected'), ('color', {'Rgb': [0, 256, 0]}), ('shading', [0, True, 0]),
                           ('color', '#123456'), ('ligatures', {'standard': 'yes'}), ('textEffects', []),
                           ('border', {'width': 13}), ('eastAsianLayout', False)]:
            refused('invalid character '+key+' '+repr(value), lambda d, k=key, v=value: char(d).update({k: v}))
        for key, value in [('indentLeft', -1585), ('spaceAfter', -1), ('outlineLevel', 10), ('dropCap', 11),
                           ('autoSpaceDE', 1), ('textDirection', 'sideways'), ('textAlignment', 'middle'),
                           ('lineSpacing', {'rule': 'multiple', 'value': 0}),
                           ('lineSpacing', {'rule': 'exactly', 'value': .5}), ('tabs', [{'pos': 10, 'leader': 'dots'}]),
                           ('tabs', [{'pos': 1}]*257), ('frame', {'w': -1}),
                           ('borders', {'insideV': {'width': 1}})]:
            refused('invalid paragraph '+key+' '+str(type(value).__name__), lambda d, k=key, v=value: para(d).update({k: v}))
        for key, value in [('widthPct', 1001), ('cellMargins', [1, 2]), ('fixed', None), ('look', {'headerRow': 1}),
                           ('float', {'dist': [-1, 0, 0, 0]}), ('shading', [1, 2, 3, 4])]:
            refused('invalid table '+key, lambda d, k=key, v=value: table(d)['props'].update({k: v}))
        refused('invalid row height', lambda d: row(d).update(height=-1))
        refused('invalid row exception boolean', lambda d: row(d).update(exceptions={'fixed': 1}))
        refused('invalid cell margin', lambda d: cell(d).update(partialMargins=[None, -1, None, 0]))
        refused('missing cell background media', lambda d: cell(d).update(picture={'media': 'absent', 'size': [10, 10]}))
        refused('invalid cell background alignment', lambda d: cell(d).update(picture={'media': next(iter(d['media'])), 'size': [10, 10], 'align': [2, 0]}))
        refused('unknown conditional region', lambda d: style(d).update(regions={'northCell': {}}))
        refused('invalid conditional region font size', lambda d: style(d).update(regions={'neCell': {'chr': {'size': 0}}}))
        refused('missing conditional character style', lambda d: style(d).update(regions={'neCell': {'chr': {'style': 'Absent'}}}))
        for link in ('file:///tmp/private', 'javascript:alert(1)', 'https://user:pass@example.test', 'https://example.test:bad', '#absent'):
            refused('unsafe or missing hyperlink '+link, lambda d, v=link: char(d).update(link=v))

        def old_row(doc, exception):
            doc['revisions'] = [{'kind': 'format', 'author': 'Fixture', 'date': '2026-11-16T00:00:00Z'}]
            row(doc)['fmtChange'] = {'rev': 0, 'old': {'exceptions': exception}}
        refused('old row exception contains invalid dimension', lambda d: old_row(d, {'width': -1}))
        refused('old row exception contains missing style', lambda d: old_row(d, {'style': 'Absent'}))
        refused('old character formatting contains unknown key', lambda d: (d.update(revisions=[{'kind': 'format', 'author': 'Fixture', 'date': ''}]), char(d).update(fmtChange={'rev': 0, 'old': {'future': True}})))

        rich = copy.deepcopy(base)
        char(rich).update(bold=False, size=1, sizeCs=1638, scale=600, spacing=-100, position=-800, kern=0,
                          color='Auto', ligatures={'standard': False, 'contextual': True},
                          underline='doubleWave', link='https://example.test/brief', textEffects={}, eastAsianLayout={})
        para(rich).update(indentFirst=-36, indentLeftChars=2, spaceBefore=0, outlineLevel=9, dropCap=0,
                          autoSpaceDE=False, autoSpaceDN=True, textDirection='tbRlV', textAlignment='baseline',
                          lineSpacing={'rule': 'atLeast', 'value': 0},
                          tabs=[{'pos': -10, 'align': 'clear'}, {'pos': 36, 'leader': 'middleDot'}],
                          borders={'inside_v': {'style': 'single', 'width': 1, 'space': 0, 'color': [0, 0, 0]}},
                          frame={'w': 0, 'h': 0})
        cell(rich).update(partialMargins=[None, 0, 4, None], picture={'media': next(iter(rich['media'])), 'size': [24, 16], 'repeat': 'tile', 'align': [.5, 0]})
        table(rich)['props']['widthPct'] = 150
        style(rich)['regions'] = {'neCell': {'chr': {'font': 'Aptos', 'bold': False}, 'vAlign': 'center'}}
        rich_before = copy.deepcopy(rich); rich_report = structure.inspect(rich)
        check(rich == rich_before, 'valid zero false null negative offset and clear tab values remain exact')
        check('Aptos' in rich_report['properties']['font_requests'], 'conditional table region font enters resource inventory')
        check(rich_report['properties']['cell_picture_media'] == [next(iter(rich['media']))], 'cell background enters owned media inventory')
        check({'text-effects', 'east-asian-layout', 'resolved-character-indent-budget', 'cell-picture-tiling-budget'} <= set(rich_report['pending_qualification']),
              'complex and inherited formatting retains explicit qualification gates')
        bookmarked = copy.deepcopy(base); bookmarked['body'].append({'kind': 'para', 'text': '\ufffcX\ufffc', 'runs': [{'len': 7}],
            'objects': [{'type': 'bookmarkStart', 'name': 'destination'}, {'type': 'bookmarkEnd', 'name': 'destination'}]})
        char(bookmarked)['link'] = '#destination'
        check(structure.inspect(bookmarked)['properties']['hyperlinks'] == ['#destination'], 'internal hyperlink binds after all story bookmarks are collected')

        changes = {'size': 18, 'italic': True, 'bold': False, 'color': {'Rgb': [24, 76, 112]}, 'spacing': 1.5,
                   'scale': 105, 'kern': 14, 'underline': 'doubleWave', 'ligatures': {'standard': True, 'contextual': True, 'historical': False, 'discretional': False}}
        para_changes = {'align': 'right', 'spaceAfter': 18, 'lineSpacing': {'rule': 'multiple', 'value': 1.5}, 'keepNext': True}
        edited = out/'precise-format.json'
        call('run', '--file', source.resolve(), '--cmd', 'select.text={"text":"Original"}',
             '--cmd', 'format.set='+json.dumps({'props': changes}), '--cmd', 'para.set='+json.dumps({'props': para_changes}), '--save', edited)
        actual = container.strict_json(edited.read_bytes()); structure.inspect(actual)
        expected = copy.deepcopy(base); char(expected).update(changes); para(expected).update(para_changes)
        # format.set applies size/bold/italic to both scripts unless the command
        # explicitly supplies complex-script overrides (cmd/format.rs).
        char(expected).update(sizeCs=18, boldCs=False, italicCs=True)
        check(actual['core']['revision'] == base['core']['revision']+1, 'format revision increments save metadata once')
        expected['core']['revision'] += 1; expected['core']['modified'] = actual['core']['modified']
        (out/'expected.json').write_text(json.dumps(expected, indent=2)+'\n')
        check(actual == expected, 'precise native format changes only selected run paragraph and explicit save metadata')
        check(call('snapshot', edited)['document'] == actual, 'complete formatted model survives cold reopen exactly')
        call('render', edited, out/'formatted.png', '--strict', '--scale', '1')
        with Image.open(out/'formatted.png') as image:
            image.load()
            check(image.format == 'PNG' and image.size == (596, 842), 'strict formatted A4 raster fully decodes independently')
            check(len(image.convert('RGB').getcolors(596*842)) > 32, 'formatted raster contains text and image variation')
            with Image.open(args.fixtures/'native.png') as baseline_image:
                baseline_image.load()
                check(image.convert('RGB').tobytes() != baseline_image.convert('RGB').tobytes(), 'precise formatting changes rendered pixels')
        check(source.read_bytes() == original, 'original editable fixture remains byte-identical')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls),
                    'seconds': time.monotonic()-started, 'engine_admission_complete': False, 'remote_actions': False,
                    'scope': 'typed character/paragraph/table/row/cell values, conditional styles and precise native formatting; complete semantic/resource/runtime qualification remains open'}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n')
        raise
    finally: (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
