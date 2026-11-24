#!/usr/bin/env python3
"""Qualify original document fixtures against the maintained private Write engine.

This is not a public runtime, arbitrary-import, installed-package or release test.
Each invocation needs a new output directory; failures retain their evidence.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--pdf-engine', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    engine = args.engine.resolve(); pdf = args.pdf_engine.resolve()
    out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; calls = []; started = time.monotonic()

    def check(value, label):
        if not value:
            raise AssertionError(label)
        checks.append(label)

    def call(*arguments, fail=None, env=None, executable=engine):
        before = time.monotonic()
        result = subprocess.run([str(executable), *map(str, arguments)], capture_output=True, timeout=90, env=env)
        number = len(calls)
        (out/f'{number:03}.stdout').write_bytes(result.stdout)
        (out/f'{number:03}.stderr').write_bytes(result.stderr)
        calls.append({'executable': str(executable), 'arguments': list(map(str, arguments)),
                      'exit_code': result.returncode, 'seconds': time.monotonic()-before})
        if fail is not None:
            check(result.returncode != 0 and fail in result.stderr.decode(), 'refused: '+str(arguments[:2]))
        elif result.returncode != 0:
            raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def value(*arguments, **kwargs):
        return json.loads(call(*arguments, **kwargs))

    def snapshot(path, **kwargs):
        report = value('snapshot', path, **kwargs)
        check(report['schemaVersion'] == 1 and report['encrypted'] is False,
              'unencrypted complete serialized snapshot: '+path.name)
        return report['document']

    def command(name, **params):
        return {'command': name, 'params': params}

    def run_script(name, script):
        path = out/(name+'.json'); path.write_text(json.dumps(script, indent=2)+'\n')
        call('run', '--script', path)

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def expected_saved(before, after):
        predicted = copy.deepcopy(before)
        check(after['core']['revision'] == before['core']['revision']+1, 'save increments revision exactly once')
        check(bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', after['core']['modified'])),
              'save records explicit UTC modification time')
        predicted['core']['revision'] += 1
        predicted['core']['modified'] = after['core']['modified']
        return predicted

    try:
        check(call('--version').decode().strip() == 'dobe-write 0.18.1 (079f478bd85df7bcc567e3bafa7d7219096f9c3c)',
              'maintained executable identity and exact upstream revision')
        help_text = call('--help').decode()
        check('dobe-write' in help_text and 'wordcraft-cli' not in help_text and 'snapshot' in help_text, 'private Dobe help')
        for arguments in [('mcp',), ('serve',), ('zotero',), ('info', '--connect=localhost'),
                          ('mcp', '--bridge', '1'), ('info', '--port', '1'), ('info', '--token=fixture')]:
            call(*arguments, fail='private engine has no editor connection or network server')
        for name in ('file.print', 'proof.packs', 'proof.installPack', 'proof.removePack'):
            call('run', '--template', 'blank', '--cmd', name+'={}', fail='explicit managed external-service handoff')

        picture = out/'original-tile.png'
        im = Image.new('RGB', (32, 24), (26, 94, 115))
        im.paste((216, 169, 103), (16, 0, 32, 12)); im.save(picture)
        original_picture = picture.read_bytes()
        commands = [command('text.insert', text='Ceramic production brief'), command('para.style', style='Heading1'),
                    command('text.newParagraph'), command('text.insert', text='Create six editable maps.'),
                    command('text.newParagraph'), command('text.insert', text='Original ceramic study.'),
                    command('select.text', text='Original'), command('format.bold'),
                    command('review.newComment', text='Keep source editable.'), command('caret.docEnd'),
                    command('text.newParagraph'), command('insert.picture', path=str(picture), width=96, alt='Original two-color tile'),
                    command('text.newParagraph'), command('insert.table', rows=2, cols=2)]
        for index, text in enumerate(('Asset', 'Editable source', 'Material', 'Native graph')):
            if index: commands.append(command('text.tab'))
            commands.append(command('text.insert', text=text))
        commands.append(command('file.properties', title='Ceramic production brief', author='Dobe fixture', custom={'Project': 'Ceramic'}))
        run_script('create', {'template': 'blank', 'commands': commands, 'save': ['brief.json', 'brief.docx']})
        native = out/'brief.json'; docx = out/'brief.docx'
        original = {path: path.read_bytes() for path in (native, docx, picture)}
        before = snapshot(native)
        check(before == json.loads(native.read_text()), 'snapshot preserves every serialized native field and float encoding')
        state = value('snapshot', native)['sourceState']
        check(state == {'keptMarkup': None, 'missingPictures': {'total': 0, 'truncated': False, 'pictures': []}},
              'native JSON snapshot explicitly reports read-time state outside serialization')
        check(before['core']['lastModifiedBy'] == 'Dobe User' and before['comments']['0']['author'] == 'Dobe User',
              'default editing and comment authors use Dobe identity')
        check(before['body'][0]['props']['style'] == 'Heading1' and len(before['comments']) == 1 and bool(before['media']),
              'editable fixture contains heading, comment story and embedded image')
        table = next(block for block in before['body'] if block['kind'] == 'table')
        check([[cell['blocks'][0]['text'] for cell in row['cells']] for row in table['rows']] ==
              [['Asset', 'Editable source'], ['Material', 'Native graph']], 'table retains all four editable cell values')
        check(snapshot(native) == before, 'fresh-process snapshot is stable without save or layout')

        environment = dict(os.environ)
        environment.update({'LANG': 'en_US.UTF-8', 'LC_ALL': 'ja_JP.UTF-8', 'WORDCRAFT_PASSWORD': 'not-used',
                            'CRAFT_FONTS_DIR': str(out/'missing-font-directory')})
        check(snapshot(native, env=environment) == before, 'ambient locale, password and build-font variables do not change fixture')
        region = out/'region.txt'; region.write_text('Paper has an explicit default.\n')
        a = snapshot(region); b = snapshot(region, env=environment)
        check(a['lastSection'] == b['lastSection'] and a['lastSection']['pageW'] == 595.28 and a['lastSection']['pageH'] == 841.89,
              'format without page metadata uses fixed A4 under conflicting locales')

        cold = out/'cold.json'; call('convert', native, cold)
        after = snapshot(cold)
        check(after == expected_saved(before, after), 'native JSON cold save preserves all fields except declared save metadata')
        revised = out/'revised.json'
        run_script('revise', {'file': 'brief.json', 'commands': [command('select.text', text='Original'),
                   command('text.insert', text='Refined!')], 'save': ['revised.json']})
        revised_model = snapshot(revised); predicted = expected_saved(before, revised_model)
        predicted['body'][2]['text'] = predicted['body'][2]['text'].replace('Original', 'Refined!')
        check(revised_model == predicted, 'precise equal-length revision retains formatting, comments, table, image and every other field')

        docx_before = snapshot(docx)
        with zipfile.ZipFile(docx) as archive:
            xml = ET.fromstring(archive.read('word/document.xml'))
            texts = ''.join(xml.itertext())
            check(all(text in texts for text in ('Ceramic production brief', 'Original', 'Native graph')), 'independent OOXML parser finds expected body and table text')
            check(any(archive.read(name) == original_picture for name in archive.namelist() if name.startswith('word/media/')),
                  'DOCX embeds exact original image bytes')
        cold_docx = out/'cold.docx'; call('convert', docx, cold_docx)
        docx_after = snapshot(cold_docx)
        check(docx_after == expected_saved(docx_before, docx_after), 'complete decoded DOCX model survives cold DOCX save')
        check(docx_before['body'][2] == before['body'][2] and docx_before['parts'] == before['parts'],
              'DOCX exchange retains precise formatted paragraph and editable comment story')
        missing_picture = out/'missing-picture.docx'
        with zipfile.ZipFile(docx) as archive, zipfile.ZipFile(missing_picture, 'w') as damaged:
            for item in archive.infolist():
                if not item.filename.startswith('word/media/'):
                    damaged.writestr(item, archive.read(item))
        missing_report = value('snapshot', missing_picture)['sourceState']['missingPictures']
        check(missing_report['total'] == 1 and len(missing_report['pictures']) == 1 and not missing_report['truncated'],
              'snapshot exposes missing source picture despite omission from native document JSON')
        call('render', missing_picture, out/'missing-picture.png', '--strict', fail='strict')
        check(not (out/'missing-picture.png').exists(), 'strict missing-source-picture refusal writes no raster')
        odt = out/'brief.odt'; call('convert', native, odt)
        kept = value('snapshot', odt)['sourceState']['keptMarkup']
        check(kept is not None and kept['format'] == 'odt' and kept['bytes'] > 0,
              'snapshot declares retained ODT markup that JSON conversion would omit')

        for source, name in ((native, 'native'), (native, 'repeat'), (revised, 'revised'), (docx, 'docx'), (cold_docx, 'docx-cold')):
            result = value('render', source, out/(name+'.png'), '--strict', '--scale', '1')
            with Image.open(out/(name+'.png')) as image:
                image.load()
                check(image.size == (596, 842) and result['width'] == 596 and result['height'] == 842,
                      'strict A4 raster fully decodes: '+name)
                check(len(image.convert('RGB').getcolors(596*842)) > 32, 'render contains text and image variation: '+name)
        check(sha(out/'native.png') == sha(out/'repeat.png'), 'fresh-process strict raster is byte-repeatable')
        check(sha(out/'docx.png') == sha(out/'docx-cold.png'), 'cold DOCX save preserves strict raster bytes')
        check(sha(out/'native.png') != sha(out/'revised.png'), 'requested text revision changes rendered pixels')
        pdf_path = out/'brief.pdf'; call('convert', native, pdf_path, '--strict')
        pdf_text = call('text', pdf_path, executable=pdf).decode()
        check(all(text in pdf_text for text in ('Ceramic production brief', 'Original', 'Native graph')), 'independent MuPDF engine extracts exported PDF text and table cells')
        call('render', pdf_path, '--page', '1', '--dpi', '72', '--out', out/'pdf.png', executable=pdf)
        with Image.open(out/'pdf.png') as image:
            image.load(); check(image.width >= 595 and image.height >= 841, 'independent MuPDF rasterizes exported PDF')

        # A cached DATE result is document content until an explicit update command.
        run_script('date-create', {'template': 'blank', 'commands': [command('insert.field', instr='DATE \\@ "yyyy-MM-dd"')], 'save': ['date.json']})
        date = out/'date.json'; date_model = json.loads(date.read_text())
        date_model['body'][0]['objects'][0]['result'] = '2001-01-01'
        date.write_text(json.dumps(date_model)+'\n')
        check(snapshot(date) == date_model, 'opening document does not refresh cached DATE field from wall clock')
        run_script('date-update', {'file': 'date.json', 'commands': [command('references.updateFields', all=True)], 'save': ['date-updated.json']})
        check(snapshot(out/'date-updated.json')['body'][0]['objects'][0]['result'] != '2001-01-01', 'explicit field update still works')

        missing = copy.deepcopy(before)
        missing['body'] = [{'kind': 'para', 'text': '\U0010fffd', 'runs': [{'len': 4}]}]
        missing['parts'] = {}; missing['comments'] = {}; missing.pop('media', None)
        bad = out/'missing-glyph.json'; bad.write_text(json.dumps(missing)+'\n')
        call('render', bad, out/'missing-glyph.png', '--strict', fail='strict')
        call('convert', bad, out/'missing-glyph.pdf', '--strict', fail='strict')
        check(not (out/'missing-glyph.png').exists() and not (out/'missing-glyph.pdf').exists(), 'strict missing-glyph failure publishes no raster or PDF')
        broken = out/'broken-script.json'
        broken.write_text(json.dumps({'template': 'blank', 'commands': ['no.such.command'], 'save': ['must-not-exist.docx']}))
        call('run', '--script', broken, fail='no.such.command')
        check(not (out/'must-not-exist.docx').exists(), 'failed command does not publish requested document')
        check(all(path.read_bytes() == data for path, data in original.items()), 'all source documents and original image remain byte-identical')
        evidence = {'passed': True, 'checks': checks, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'scope': 'original private macOS ARM64 native fixtures; no runtime, installed, arbitrary-import, full upstream CI or Linux/Cloud qualification',
                    'remote_actions': False, 'engine_sha256': sha(engine)}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks}, indent=2)+'\n')
        raise
    finally:
        (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__':
    main()
