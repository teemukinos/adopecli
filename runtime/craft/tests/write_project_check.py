#!/usr/bin/env python3
"""Exercise exact-source portable Write projects, replay and detached native use."""
import argparse
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_project as project


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True); parser.add_argument('--embedded', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; calls = []; started = time.monotonic()
    source_path = args.fixtures/'brief.json'; source = source_path.read_bytes(); original = json.loads(source)
    engine_manifest = json.loads((args.engine.resolve().parent.parent/'engine.json').read_text())
    pin = {'product': engine_manifest['product'], 'version': engine_manifest['source_lock']['engine_version'],
           'source_revision': engine_manifest['source_lock']['source']['revision'], 'source_lock_sha256': engine_manifest['source_lock_sha256']}
    assert project.sha(args.engine.read_bytes()) == engine_manifest['files']['bin/dobe-write']['sha256']

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=90)
        index = len(calls); calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def refused(label, operation, expected):
        try: operation()
        except ValueError as error:
            check(expected in str(error), label+' refuses at intended boundary'); refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)

    def mutation(label, edit, expected):
        observed = project.inspect_bytes(revised); manifest = copy.deepcopy(observed['manifest'])
        members = {k: v for k, v in observed['members'].items() if k != 'project.json'}
        edit(manifest, members)
        refused(label, lambda: project.inspect_bytes(project.pack(manifest, members)), expected)

    try:
        bundle = project.create(source, 'json', engine=pin); (out/'original.dobewrite').write_bytes(bundle)
        initial = project.inspect_bytes(bundle)
        check(initial['members']['original.json'] == initial['members']['baseline.json'] == initial['members']['document.json'] == source,
              'initial project owns exact original JSON bytes in all initial roles')
        check(project.create(source, 'json', engine=pin) == bundle, 'same source produces deterministic archive bytes')
        project.require_engine(initial, pin)
        check(initial['manifest']['engine'] == pin, 'portable project pins maintained source and dependency lock without locking to one host binary')
        check(initial['revision_count'] == 0 and not initial['engine_admission_complete'], 'new package does not invent an edit or grant execution permission')
        edit = {'kind': 'text.replace', 'path': '/body/2', 'start': 3, 'end': 11, 'expected': 'Original', 'value': 'Ångström craft'}
        first = project.revise(bundle, project.sha(bundle), [edit]); one = project.inspect_bytes(first)
        text = one['current']['document']['body'][2]['text'].encode(); offset = text.index(b'ceramic')
        second = {'kind': 'text.replace', 'path': '/body/2', 'start': offset, 'end': offset+7, 'expected': 'ceramic', 'value': 'porcelain'}
        revised = project.revise(first, project.sha(first), [second]); (out/'revised.dobewrite').write_bytes(revised)
        observed = project.inspect_bytes(revised)
        check(observed['revision_count'] == 2 and observed['replayed_edits'] == 2, 'two revisions replay against their exact predecessors')
        check(observed['members']['original.json'] == observed['members']['baseline.json'] == source, 'every revision preserves immutable original and baseline')
        expected = copy.deepcopy(original); expected['body'][2]['text'] = '\ufffcÅngström craft\ufffc porcelain study.'
        expected['body'][2]['runs'][1]['len'] = 16; expected['body'][2]['runs'][2]['len'] = 20
        check(observed['current']['document'] == expected, 'entire replayed current model matches independent prediction')
        check(observed['current']['document']['media'] == original['media'] and observed['current']['document']['parts'] == original['parts'], 'portable history retains original artwork and comment stories exactly')
        check(project.revise(first, project.sha(first), [second]) == revised, 'replaying same second revision produces identical portable bytes')
        detached = out/'detached'; detached.mkdir(); folder = detached/'document'
        report = project.checkout(detached, folder, revised)
        check(report['current_sha256'] == observed['current_sha256'] and {p.name for p in folder.iterdir()} == set(observed['members']), 'checkout materializes only fixed owned files in detached root')
        check(all((folder/name).read_bytes() == data for name, data in observed['members'].items()), 'checkout preserves all original, model and manifest bytes')
        native = json.loads(call('snapshot', folder/'document.json'))['document']
        check(native == expected, 'fresh native process reopens entire revised document from detached checkout')
        call('render', folder/'document.json', detached/'preview.png', '--strict', '--scale', '1')
        with Image.open(detached/'preview.png') as image:
            image.load(); check(image.size == (596,842), 'detached project renders strict native A4 raster with owned image')
        check(source_path.read_bytes() == source, 'original fixture remains byte-identical after checkout and rendering')

        original_docx = (args.fixtures/'brief.docx').read_bytes()
        snapshot = json.loads(call('snapshot', args.fixtures/'brief.docx'))['document']; baseline = (json.dumps(snapshot)+'\n').encode()
        docx_bundle = project.create(original_docx, 'docx', baseline, engine=pin); docx_profile = project.inspect_bytes(docx_bundle)
        check(docx_profile['members']['original.docx'] == original_docx and docx_profile['members']['baseline.json'] == baseline,
              'DOCX project retains exact source archive separately from native model observation')
        check('docx-baseline-source-correspondence' in docx_profile['pending_qualification'], 'DOCX observation never claims complete source correspondence from packaging alone')
        docx_revised = project.revise(docx_bundle, project.sha(docx_bundle), [edit]); docx_folder = detached/'docx'
        project.checkout(detached, docx_folder, docx_revised)
        check((docx_folder/'original.docx').read_bytes() == original_docx, 'DOCX original survives model revision and detached checkout exactly')
        reopened = json.loads(call('snapshot', docx_folder/'document.json'))['document']
        check(reopened == project.inspect_bytes(docx_revised)['current']['document'], 'DOCX-derived revised model cold-reopens without omitted fields')
        embedded_source = args.embedded.read_bytes(); embedded_bundle = project.create(embedded_source, 'json', engine=pin); embedded_folder = detached/'fonts'
        project.checkout(detached, embedded_folder, embedded_bundle)
        selected = call('run', '--file', embedded_folder/'document.json', '--cmd', 'font.missing={}', '--print').decode()
        missing = json.loads(selected.removeprefix('font.missing: ').strip())['missing']
        check(not any(item['font'] == 'Dobe Original Embedded Fixture' for item in missing), 'embedded document font travels with detached project and resolves natively')
        check((embedded_folder/'original.json').read_bytes() == embedded_source, 'embedded font source remains exact in portable checkout')

        refused('stale project revision', lambda: project.revise(bundle, '0'*64, [edit]), 'hash is stale')
        refused('JSON baseline substitution', lambda: project.create(source, 'json', baseline, engine=pin), 'cannot replace original')
        refused('DOCX missing baseline', lambda: project.create(original_docx, 'docx', engine=pin), 'separately observed')
        broken_media = copy.deepcopy(original); media_name = next(iter(broken_media['media']))
        broken_media['media'][media_name] = base64.b64encode(b'not-an-image').decode('ascii')
        refused('invalid owned picture before packaging', lambda: project.create(json.dumps(broken_media).encode(), 'json', engine=pin), 'cannot be independently decoded')
        broken_font = json.loads(embedded_source); font_name = next(name for name in broken_font['passthrough'] if name.endswith('.odttf'))
        font_bytes = bytearray(base64.b64decode(broken_font['passthrough'][font_name])); font_bytes[-1] ^= 1
        broken_font['passthrough'][font_name] = base64.b64encode(font_bytes).decode('ascii')
        refused('invalid owned font before packaging', lambda: project.create(json.dumps(broken_font).encode(), 'json', engine=pin), 'checksum')
        refused('different installed engine lock', lambda: project.require_engine(initial, {**pin, 'source_lock_sha256': '0'*64}), 'pinned engine source')
        mutation('invalid engine digest', lambda m, f: m['engine'].update(source_revision='latest'), 'engine pin digest')
        mutation('wrong engine product', lambda m, f: m['engine'].update(product='dobe-other'), 'engine product/version')
        mutation('unknown manifest fields', lambda m, f: m.update(execution_approved=True), 'manifest fields differ')
        mutation('Boolean version', lambda m, f: m.update(version=True), 'format/version')
        mutation('unknown source format', lambda m, f: m.update(source_format='rtf'), 'source format')
        mutation('unexpected archive file', lambda m, f: f.update({'outside.txt': b'opaque'}), 'unaccounted members')
        mutation('missing original', lambda m, f: f.pop('original.json'), 'unaccounted members')
        mutation('corrupted current bytes', lambda m, f: f.update({'document.json': f['document.json']+b' '}), 'hash or size differs')
        mutation('forged member length', lambda m, f: m['members']['document.json'].update(bytes=True), 'member record')
        mutation('forged chain predecessor', lambda m, f: m['history'][0].update(before='0'*64), 'does not own its predecessor')
        mutation('forged chain result', lambda m, f: m['history'][0].update(after='0'*64), 'result differs')
        mutation('unrecorded current revision', lambda m, f: m.update(history=[]), 'differs from exact revision replay')
        mutation('unknown history field', lambda m, f: m['history'][0].update(approved=True), 'revision record')
        mutation('history budget', lambda m, f: m.update(history=m['history']*17), 'history exceeds budget')
        mutation('edit aggregate budget', lambda m, f: m['history'][0].update(edits=[edit]*129), 'edits exceed aggregate')
        mutation('updated hash cannot hide changed replay', lambda m, f: (f.update({'document.json': source}), m['members'].update({'document.json': project.record(source)})), 'differs from exact revision replay')
        sentinel = folder/'sentinel'; sentinel.write_bytes(b'owner file')
        refused('existing checkout', lambda: project.checkout(detached, folder, revised), 'new destination')
        check(sentinel.read_bytes() == b'owner file', 'failed checkout preserves existing owner files')
        refused('escaped checkout', lambda: project.checkout(detached, out/'outside', revised), 'inside its attempt')
        link = detached/'linked'; link.symlink_to(folder, target_is_directory=True)
        refused('symlink checkout ancestor', lambda: project.checkout(detached, link/'child', revised), 'symbolic links')
        cancelled_path = detached/'cancelled'; state = {'checks': 0}
        def cancelled(): state['checks'] += 1; return state['checks'] >= 3
        refused('cancel during checkout', lambda: project.checkout(detached, cancelled_path, revised, cancelled=cancelled), 'cancelled')
        check(not cancelled_path.exists(), 'cancelled disposable checkout leaves no partial project')
        check(args.embedded.read_bytes() == embedded_source and (args.fixtures/'brief.docx').read_bytes() == original_docx, 'all original document inputs remain unchanged')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'remote_actions': False, 'engine_admission_complete': False, 'bundle_bytes': len(revised), 'revision_count': 2,
                    'source_sha256': project.sha(source), 'project_sha256': project.sha(revised),
                    'scope': 'exact original/model ownership, typed replay, bounded portable archives and detached native use; durable public publication and complete admission remain pending'}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally: (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
