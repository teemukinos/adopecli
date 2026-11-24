#!/usr/bin/env python3
"""Qualify typed revisions against complete cold native documents and exports."""
import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_revision as revision


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True); parser.add_argument('--rich', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    source = (args.fixtures/'brief.json').read_bytes(); sha = hashlib.sha256(source).hexdigest(); original = json.loads(source)
    checks = []; refusals = []; calls = []; started = time.monotonic()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=90)
        index = len(calls); calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def text_edit(path, block, old, new):
        start = block['text'].encode().index(old.encode())
        return {'kind': 'text.replace', 'path': path, 'start': start, 'end': start+len(old.encode()), 'expected': old, 'value': new}

    def qualify(label, data, edits):
        untouched = copy.deepcopy(edits); report = revision.revise_bytes(data, hashlib.sha256(data).hexdigest(), edits)
        check(edits == untouched, label+' preserves caller request')
        path = out/(label+'.json'); path.write_bytes(report['data'])
        actual = json.loads(call('snapshot', path))['document']
        check(revision.canonical(actual) == revision.canonical(report['document']), label+' complete native snapshot equals predicted document')
        check(not report['engine_admission_complete'], label+' remains separate from public execution admission')
        return report, path

    base_edit = text_edit('/body/2', original['body'][2], 'Original', 'Ångström craft')

    def refused(label, data=source, edits=None, digest=None, expected=''):
        values = [copy.deepcopy(base_edit)] if edits is None else copy.deepcopy(edits); before = copy.deepcopy(values)
        try: revision.revise_bytes(data, sha if digest is None else digest, values)
        except ValueError as error:
            check(expected in str(error) and values == before, label+' refuses atomically at expected boundary')
            refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)

    def bad_edit(label, change, expected):
        edit = copy.deepcopy(base_edit); change(edit); refused(label, edits=[edit], expected=expected)

    try:
        result, path = qualify('unicode', source, [base_edit])
        predicted = copy.deepcopy(original); predicted['body'][2]['text'] = '\ufffcÅngström craft\ufffc ceramic study.'
        predicted['body'][2]['runs'][1]['len'] = 16
        check(result['document'] == predicted, 'independent complete prediction changes only selected text and its UTF-8 run length')
        check(result['document']['parts'] == original['parts'] and result['document']['media'] == original['media'], 'comments, stories and original image bytes remain exact')
        second = text_edit('/body/2', original['body'][2], 'ceramic', 'porcelain')
        result2, _ = qualify('batch', source, [base_edit, second])
        check(result2['document']['body'][2]['text'] == '\ufffcÅngström craft\ufffc porcelain study.', 'batch uses immutable original offsets despite variable byte-length edits')
        reverse = revision.revise_bytes(source, sha, [second, base_edit])
        check(reverse['data'] == result2['data'], 'disjoint batch order produces identical complete document')
        interior = text_edit('/body/2', original['body'][2], 'rig', 'wide')
        interior_result, _ = qualify('inside-run', source, [interior])
        check(interior_result['document']['body'][2]['runs'][1]['len'] == 9 and len(interior_result['document']['body'][2]['runs']) == 3,
              'replacement inside one run rejoins only its original surviving fragments')
        deletion = text_edit('/body/2', original['body'][2], 'rig', '')
        deleted, _ = qualify('delete', source, [deletion])
        check(deleted['document']['body'][2]['text'] == '\ufffcOinal\ufffc ceramic study.', 'deletion keeps surrounding comment anchors and text')
        formatted = {k: v for k, v in base_edit.items() if k != 'value'}
        formatted.update(kind='text.format', set={'size': 18.0, 'sizeCs': 18.0, 'bold': False, 'boldCs': False, 'color': {'Rgb': [14,64,90]}}, unset=[])
        format_result, _ = qualify('format', source, [formatted])
        check(format_result['document']['body'][2]['text'] == original['body'][2]['text'], 'formatting preserves every text byte and inline marker')
        partial_format = copy.deepcopy(formatted); partial_format.update(start=4, end=7, expected='rig')
        partial, _ = qualify('partial-format', source, [partial_format, second])
        check(len(partial['document']['body'][2]['runs']) == 5 and partial['document']['body'][2]['runs'][1]['props'] == original['body'][2]['runs'][1]['props'],
              'partial formatting splits only selected run and preserves unselected character properties')
        unicode_edit = text_edit('/body/2', result['document']['body'][2], 'Ångström', 'Café')
        unicode_again, _ = qualify('unicode-source', result['data'], [unicode_edit])
        check(unicode_again['document']['body'][2]['text'] == '\ufffcCafé craft\ufffc ceramic study.', 'UTF-8 offsets apply correctly to a multibyte source revision')
        paragraph = {'kind': 'paragraph.properties', 'path': '/body/2', 'expected': original['body'][2]['props'], 'set': {'align': 'center', 'spaceAfter': 12.0}, 'unset': []}
        section = {'kind': 'section.properties', 'path': '/lastSection', 'expected': original['lastSection'], 'set': {'marginLeft': 54.0, 'marginRight': 54.0}, 'unset': []}
        setup, _ = qualify('page-and-format', source, [formatted, paragraph, section])
        check(setup['document']['body'][2]['props']['align'] == 'center' and setup['document']['lastSection']['marginLeft'] == 54.0,
              'typed formatting, paragraph and page changes compose without changing unrelated model fields')
        table_index = next(i for i, b in enumerate(original['body']) if b['kind'] == 'table')
        table_path = f'/body/{table_index}/rows/1/cells/1/blocks/0'; table_block = revision.locate(original, table_path)
        table_result, _ = qualify('table', source, [text_edit(table_path, table_block, 'Native graph', 'Editable graph')])
        check(revision.locate(table_result['document'], table_path)['text'] == 'Editable graph', 'exact nested table-cell selector revises owned text')
        rich_source = args.rich.read_bytes(); rich = json.loads(rich_source)
        note_path = '/parts/1/blocks/0'; note = revision.locate(rich, note_path)
        note_result, _ = qualify('note', rich_source, [text_edit(note_path, note, 'Editable', 'Revised')])
        check(revision.locate(note_result['document'], note_path)['objects'] == note['objects'], 'note revision preserves native reference marker and owned story')

        call('render', path, out/'unicode.png', '--strict', '--scale', '1')
        with Image.open(out/'unicode.png') as image:
            image.load(); check(image.size == (596,842) and len(image.convert('RGB').getcolors(image.width*image.height)) > 100, 'actual revised native raster fully decodes with visible content')
        docx = out/'unicode.docx'; call('convert', path, docx)
        with zipfile.ZipFile(docx) as archive:
            text = ''.join(ET.fromstring(archive.read('word/document.xml')).itertext())
            check('Ångström craft' in text and 'Original' not in text, 'independent OOXML reader sees requested variable-length Unicode revision')
        cold = out/'cold.json'; before_save = int(time.time()); call('convert', path, cold); reopened = json.loads(call('snapshot', cold))['document']
        saved_expected = copy.deepcopy(predicted)
        check(reopened['core']['revision'] == predicted['core']['revision']+1 and bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', reopened['core']['modified'])), 'native save uses explicit revision/time metadata contract')
        modified = datetime.datetime.fromisoformat(reopened['core']['modified'].replace('Z', '+00:00')).timestamp()
        check(before_save <= modified <= time.time(), 'native save timestamp falls inside actual save/reopen interval')
        saved_expected['core']['revision'] += 1; saved_expected['core']['modified'] = reopened['core']['modified']
        check(revision.canonical(reopened) == revision.canonical(saved_expected), 'complete cold native save changes only declared save metadata')

        refused('stale source', digest='0'*64, expected='source hash is stale')
        refused('invalid digest', digest='abc', expected='exact original SHA')
        refused('empty edits', edits=[], expected='one to 128')
        refused('too many edits', edits=[base_edit]*129, expected='one to 128')
        bad_edit('unknown operation', lambda e: e.update(kind='raw.command'), 'kind or selector')
        bad_edit('unowned pointer', lambda e: e.update(path='/settings'), 'not an owned paragraph')
        bad_edit('noncanonical pointer', lambda e: e.update(path='/body/02'), 'not an owned paragraph')
        bad_edit('extra request field', lambda e: e.update(command='file.save'), 'fields differ')
        bad_edit('Boolean offset', lambda e: e.update(start=True), 'UTF-8 range')
        bad_edit('empty range', lambda e: e.update(end=3), 'UTF-8 range')
        bad_edit('range outside text', lambda e: e.update(end=999), 'UTF-8 range')
        bad_edit('split object UTF-8', lambda e: e.update(start=1), 'splits UTF-8')
        bad_edit('stale expected text', lambda e: e.update(expected='Another'), 'expected text differs')
        bad_edit('replacement paragraph break', lambda e: e.update(value='two\nparagraphs'), 'paragraph text')
        bad_edit('replacement object marker', lambda e: e.update(value='\ufffc'), 'paragraph text')
        bad_edit('selected object marker', lambda e: e.update(start=0, end=3, expected='\ufffc'), 'inline objects')
        bad_edit('no change', lambda e: e.update(value='Original'), 'no document change')
        refused('overlapping spans', edits=[base_edit, interior], expected='text ranges overlap')
        bad = copy.deepcopy(formatted); bad['set'] = {'bold': 1}
        refused('wrong formatting type', edits=[bad], expected='boolean has the wrong type')
        bad = copy.deepcopy(formatted); bad['set'] = {'ins': 1}
        refused('invented tracked history', edits=[bad], expected='tracked-edit operation')
        bad = copy.deepcopy(formatted); bad['unset'] = ['color']
        refused('conflicting patch', edits=[bad], expected='conflicting keys')
        bad = copy.deepcopy(paragraph); bad['unset'] = ['spaceBefore']
        refused('remove absent property', edits=[bad], expected='removes absent')
        bad = copy.deepcopy(paragraph); bad['expected'] = {}
        refused('stale properties', edits=[bad], expected='expected properties differ')
        refused('duplicate property target', edits=[paragraph, paragraph], expected='target is duplicated')
        bad = copy.deepcopy(paragraph); bad['set'] = {'notAProperty': True}
        refused('invalid second edit leaves no partial revision', edits=[base_edit, bad], expected='unknown fields')
        bad = copy.deepcopy(section); bad['set'] = {'pageW': 0}
        refused('invalid page geometry', edits=[bad], expected='out of range')
        for field, value in [('trackChanges', True), ('protection', 'readOnly'), ('protectFormatting', True)]:
            changed = copy.deepcopy(original); changed['settings'][field] = value; raw = json.dumps(changed).encode()
            refused('protected '+field, data=raw, digest=hashlib.sha256(raw).hexdigest(), expected='tracked/protected')
        changed = copy.deepcopy(original); changed['body'][2]['runs'][1] = {'len': 4, 'props': {'bold': True}}
        changed['body'][2]['runs'].insert(2, {'len': 4, 'props': {'italic': True}}); raw = json.dumps(changed).encode()
        refused('mixed selected formatting', data=raw, digest=hashlib.sha256(raw).hexdigest(), expected='different formatting')
        check((args.fixtures/'brief.json').read_bytes() == source and args.rich.read_bytes() == rich_source, 'all original files remain byte-identical')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'remote_actions': False, 'engine_admission_complete': False, 'source_sha256': sha,
                    'scope': 'typed full-model text/format/paragraph/section revisions and real cold native exports; complete admission, tracked/protected edits and runtime publication remain pending'}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally: (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
