#!/usr/bin/env python3
"""Check Write structure against native editable fixtures and independent mutations."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_container as container, write_structure as structure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--legacy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; calls = []; started = time.monotonic()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=90)
        index = len(calls); (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def command(identifier, **params): return {'command': identifier, 'params': params}
    def refused(label, document):
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False)
        try: structure.inspect(document)
        except ValueError as error:
            refusals.append({'case': label, 'error': str(error)}); checks.append(label+' refused')
        else: raise AssertionError('accepted '+label)
        check(json.dumps(document, ensure_ascii=False, allow_nan=False) == encoded, label+' is not repaired')

    def mutate(label, change, base):
        altered = copy.deepcopy(base); change(altered); refused(label, altered)

    def paragraph(value, objects=None):
        return {'kind': 'para', 'text': value, 'runs': [{'len': len(value.encode())}] if value else [], **({'objects': objects} if objects is not None else {})}

    try:
        old = container.read_source(args.legacy/'brief.json', 'json')['document']
        refused('previous native template has unresolved linked styles', old)
        baseline_path = args.fixtures/'brief.json'; original = baseline_path.read_bytes()
        base = container.strict_json(original); report = structure.inspect(base)
        check(report['counts'] == {'blocks': 11, 'text_bytes': 142, 'objects': 3, 'cells': 4, 'tables': 1, 'sections': 1},
              'independent original document counts include comment story and four cells')
        styles = {item['id']: item for item in base['styles']['styles']}
        for n in range(1, 10):
            heading = styles['Heading'+str(n)]; linked = styles[heading['linked']]
            check(linked['kind'] == 'character' and linked['linked'] == heading['id'] and linked['chr'] == heading['chr']
                  and linked['basedOn'] == 'DefaultParagraphFont', 'heading '+str(n)+' owns its exact linked character style')
        check(json.loads(call('snapshot', baseline_path))['document'] == base, 'complete original model matches independent cold native snapshot')
        check(not report['engine_admission_complete'] and report['pending_qualification'], 'structure check does not authorize an engine or render')

        body = command('caret.set', pos={'story': 'body', 'path': [0], 'off': 0})
        commands = [command('text.insert', text='Café 世界 😀'), command('text.newParagraph'), command('para.numbering'),
                    command('text.insert', text='First deliverable'), command('text.newParagraph'), command('text.insert', text='Second deliverable'),
                    command('text.newParagraph'), command('para.numbering', off=True), command('text.insert', text='Reference section'),
                    command('select.text', text='Reference'), command('insert.bookmark', name='reference'), command('caret.docEnd'),
                    command('references.footnote', text='Editable footnote.'), body, command('caret.docEnd'),
                    command('references.endnote', text='Editable endnote.'), body, command('caret.docEnd'), command('text.newParagraph'),
                    command('insert.textBox', text='Editable caption', width=144, height=48), command('insert.header', text='Production notebook'),
                    command('insert.closeHeader'), command('insert.footer', preset='pageNumber'), command('insert.closeHeader'),
                    body, command('caret.docEnd'), command('text.newParagraph'), command('insert.shape', kind='straightConnector', width=108, height=0)]
        script = out/'create.json'; script.write_text(json.dumps({'template': 'blank', 'commands': commands, 'save': ['rich.json', 'rich.docx']}))
        call('run', '--script', script); rich_path = out/'rich.json'; rich = container.strict_json(rich_path.read_bytes())
        rich_report = structure.inspect(rich)
        check({item['kind'] for item in rich['parts'].values()} == {'footnote', 'endnote', 'textBox', 'header', 'footer'}, 'native fixture owns five distinct secondary stories')
        check(rich_report['bookmarks'] == ['reference'] and rich_report['styles']['list_count'] == 1, 'native bookmark and list bind to owned definitions')
        check(rich_report['paragraphs'][0]['utf8_bytes'] == 17, 'UTF-8 byte positions remain distinct from Unicode character count')
        check(any(o.get('kind') == 'straightConnector' and o['h'] == 0 for b in rich['body'] for o in b.get('objects', [])),
              'native horizontal connector keeps zero height without being treated as an invalid image')
        check(json.loads(call('snapshot', rich_path))['document'] == rich, 'rich model exactly matches cold native snapshot')
        tracked_path = out/'native-tracked.json'
        call('run', '--file', rich_path, '--cmd', 'review.trackChanges={"value":true}', '--cmd', 'select.text={"text":"Café"}',
             '--cmd', 'text.insert={"text":"Refined café"}', '--save', tracked_path)
        native_tracked = container.strict_json(tracked_path.read_bytes()); structure.inspect(native_tracked)
        check({item['kind'] for item in native_tracked['revisions']} == {'insert', 'delete'},
              'actual native tracked replacement owns insertion and deletion revisions')
        check(json.loads(call('snapshot', tracked_path))['document'] == native_tracked,
              'tracked replacement retains every serialized field on cold native reopen')
        edited = out/'linked-style.json'
        call('run', '--file', baseline_path, '--cmd', 'select.text={"text":"Original"}', '--cmd', 'styles.apply={"style":"Heading1Char"}', '--save', edited)
        styled = container.strict_json(edited.read_bytes()); structure.inspect(styled)
        check(any(run.get('props', {}).get('style') == 'Heading1Char' for run in styled['body'][2]['runs']), 'native editor applies newly owned heading character style')

        mutate('unknown top-level state', lambda d: d.update(future=True), base)
        mutate('unknown paragraph state', lambda d: d['body'][0].update(future=True), base)
        mutate('empty body requiring repair', lambda d: d.update(body=[]), base)
        mutate('UTF-8 split', lambda d: d['body'][0].update(runs=[{'len': 4}, {'len': 13}]), rich)
        mutate('uncovered text', lambda d: d['body'][0]['runs'][0].update(len=1), rich)
        mutate('zero run requiring repair', lambda d: d['body'][0]['runs'].insert(0, {'len': 0}), rich)
        mutate('boolean run length', lambda d: d['body'][0]['runs'][0].update(len=True), rich)
        mutate('missing object marker', lambda d: d['body'][0].update(objects=[{'type': 'fieldEnd'}]), rich)
        mutate('missing image bytes', lambda d: d.update(media={}), base)
        mutate('ambiguous part ID', lambda d: d['parts'].update({'01': copy.deepcopy(d['parts']['1'])}), base)
        mutate('invalid part kind', lambda d: d['parts']['1'].update(kind=[]), base)
        mutate('missing comment story', lambda d: d['comments']['0'].update(part=999), base)
        mutate('comment reply cycle', lambda d: d['comments']['0'].update(parent=0), base)
        mutate('wrong header kind', lambda d: d['lastSection']['headers'].update(default=1), rich)
        mutate('missing footer', lambda d: d['lastSection']['footers'].update(default=999), rich)
        mutate('no text area', lambda d: d['lastSection'].update(marginLeft=595), base)
        mutate('oversized page', lambda d: d['lastSection'].update(pageW=1e20), base)
        mutate('zero columns', lambda d: d['lastSection']['columns'].update(count=0), base)
        mutate('column width count mismatch', lambda d: d['lastSection']['columns'].update(count=2, widths=[[100, 10]]), base)
        mutate('column spacing consumes page', lambda d: d['lastSection']['columns'].update(count=20, space=36), base)

        table_index = next(i for i, block in enumerate(base['body']) if block['kind'] == 'table')
        def table(d): return d['body'][table_index]
        mutate('zero cell span', lambda d: table(d)['rows'][0]['cells'][0]['props'].update(span=0), base)
        mutate('grid mismatch', lambda d: table(d)['grid'].append(50), base)
        mutate('unmatched vertical merge', lambda d: table(d)['rows'][0]['cells'][0]['props'].update(vmerge='continue'), base)
        merged = copy.deepcopy(base); table(merged)['rows'][0]['cells'][0]['props']['vmerge'] = 'restart'
        table(merged)['rows'][1]['cells'][0]['props']['vmerge'] = 'continue'; table(merged)['rows'][1]['cells'][0]['blocks'] = [paragraph('')]
        check(structure.inspect(merged)['counts']['cells'] == 4, 'valid vertical merge retains both editable cell records')
        skipped = copy.deepcopy(base); table(skipped)['rows'][0]['cells'].pop(0); table(skipped)['rows'][0]['props']['gridBefore'] = 1
        check(structure.inspect(skipped)['counts']['cells'] == 3, 'explicit skipped grid column is retained')
        nested = copy.deepcopy(base); inner = copy.deepcopy(table(base)); table(nested)['rows'][0]['cells'][0]['blocks'] = [inner]
        check(structure.inspect(nested)['counts']['tables'] == 2, 'nested editable table is independently counted')

        mutate('style inheritance cycle', lambda d: d['styles']['styles'][0].update(basedOn='Normal'), base)
        mutate('missing linked style', lambda d: d['styles']['styles'][0].update(linked='MissingChar'), base)
        mutate('missing paragraph style', lambda d: d['body'][0].setdefault('props', {}).update(style='Missing'), rich)
        mutate('wrong character style kind', lambda d: d['body'][0]['runs'][0].update(props={'style': 'Normal'}), rich)
        mutate('duplicate style', lambda d: d['styles']['styles'].append(copy.deepcopy(d['styles']['styles'][0])), base)
        mutate('missing list', lambda d: d['body'][1]['props']['numbering'].update(num=999), rich)
        mutate('missing abstract list', lambda d: d['numbering']['nums'][0].update(abstractId=999), rich)
        mutate('duplicate list override', lambda d: d['numbering']['nums'][0].update(startOverrides=[[0, 1], [0, 2]]), rich)
        mutate('missing revision', lambda d: d['body'][0]['runs'][0].update(props={'ins': 0}), rich)
        tracked = copy.deepcopy(rich); tracked['revisions'] = [{'kind': 'insert', 'author': 'Fixture', 'date': '2026-01-01T00:00:00Z'}]
        tracked['body'][0]['runs'][0]['props'] = {'ins': 0}
        check(structure.inspect(tracked)['counts']['text_bytes'] == rich_report['counts']['text_bytes'], 'tracked insertion references owned revision without changing text')
        mutate('wrong revision kind', lambda d: d['revisions'][0].update(kind='delete'), tracked)
        for kind, payload in [('fieldEnd', {}), ('bookmarkEnd', {'name': 'absent'}), ('commentEnd', {'id': 0}), ('permEnd', {'id': 1})]:
            malformed = copy.deepcopy(base); malformed['body'] = [paragraph('\ufffc', [{'type': kind, **payload}])]
            refused('unmatched '+kind, malformed)
        for code in ('DDE', 'INCLUDETEXT', 'INCLUDEPICTURE', 'MACROBUTTON'):
            malformed = copy.deepcopy(base); malformed['body'] = [paragraph('\ufffc', [{'type': 'field', 'instr': code+' external'}])]
            refused('active field '+code, malformed)
        balanced = copy.deepcopy(base); balanced['body'] = [paragraph('\ufffcA', [{'type': 'fieldStart', 'instr': 'TOC'}]), paragraph('B\ufffc', [{'type': 'fieldEnd'}])]
        check(structure.inspect(balanced)['counts']['fields'] == 1, 'complex field spans paragraphs without flattening content')

        box = next(o for b in rich['body'] for o in b.get('objects', []) if o['type'] == 'shape')
        cyclic = copy.deepcopy(rich); cyclic['parts']['3']['blocks'] = [paragraph('\ufffc', [copy.deepcopy(box)])]
        refused('text box embeds itself', cyclic)
        mutate('text-box chain cycle', lambda d: d['parts']['3'].update(body={'next': 3}), rich)
        mutate('text-box chain wrong kind', lambda d: d['parts']['3'].update(body={'next': 1}), rich)
        deep = copy.deepcopy(rich)
        for i in range(6, 11):
            child = copy.deepcopy(box); child['story'] = i+1
            deep['parts'][str(i)] = {'kind': 'textBox', 'blocks': [paragraph('\ufffc', [child])] if i < 10 else [paragraph('End')]}
        deep['parts']['3']['blocks'] = [paragraph('\ufffc', [{**copy.deepcopy(box), 'story': 6}])]
        refused('text-box depth would omit content', deep)
        repeated = copy.deepcopy(rich)
        repeated['parts']['6'] = {'kind': 'textBox', 'blocks': [paragraph('Leaf')]}
        repeated['parts']['3']['blocks'] = [paragraph('\ufffc'*65, [{**copy.deepcopy(box), 'story': 6} for _ in range(65)])]
        refused('repeated text-box expansion exceeds native budget', repeated)
        group = {'type': 'group', 'w': 100, 'h': 100, 'ch_w': 100, 'ch_h': 100, 'children': [{'x': 0, 'y': 0, 'obj': copy.deepcopy(box)}]}
        grouped = copy.deepcopy(rich); grouped['body'].append(paragraph('\ufffc', [group]))
        check(any(o['type'] == 'group' for o in structure.inspect(grouped)['objects']), 'grouped text box retains owned editable story')
        canvas = copy.deepcopy(grouped); canvas['body'][-1]['objects'][0].update(children=[], canvas={'fill': None, 'stroke': None, 'strokeWidth': 0})
        check(structure.inspect(canvas)['structural_validation_complete'], 'empty editable drawing canvas is retained')
        mutate('group child is not a drawing', lambda d: d['body'][-1]['objects'][0]['children'][0].update(obj={'type': 'fieldEnd'}), grouped)
        mutate('group child kind has invalid type', lambda d: d['body'][-1]['objects'][0]['children'][0].update(obj={'type': []}), grouped)
        check(baseline_path.read_bytes() == original, 'native probes and structural checks leave original source byte-identical')
        (out/'structure.json').write_text(json.dumps(rich_report, indent=2)+'\n')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'scope': 'story/reference structure and maintained linked-style correction; property/media/source-format/runtime/install qualification remains open',
                    'engine_admission_complete': False, 'remote_actions': False}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n')
        raise
    finally:
        (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
