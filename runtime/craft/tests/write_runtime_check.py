#!/usr/bin/env python3
"""Exercise real Write CLI/MCP jobs in an unpublished distribution-layout fixture.

This copies the current runtime and qualified native pack, not an installed release.
No fake engine, receipt override, network action or editor is used.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def digest(data): return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'project', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--pdf-engine', type=Path)
    parser.add_argument('--staged', action='store_true'); args = parser.parse_args()
    out = args.output.resolve(); resources = out/'fixture/DobeCLI/lib/dobe'; runtime = resources/'runtime'
    if not args.staged:
        out.mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1]/'runtime/studio_runtime', runtime/'studio_runtime', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(args.engine.resolve().parent.parent, resources/'engines/write')
        if args.pdf_engine: shutil.copytree(args.pdf_engine.resolve().parent.parent, resources/'engines/pdf')
        metadata = json.loads((resources/'engines/write/engine.json').read_bytes())
        manifest = {'schema_version': 1, 'product': 'dobe', 'distribution': 'dobe-cli', 'platform': 'macos-arm64',
                    'release_signed': False, 'qualification': 'test-layout-only-not-installed',
                    'components': [{'name': 'dobe-write', 'version': metadata['version'], 'source_lock_sha256': metadata['source_lock_sha256'],
                                    'engine_manifest_sha256': digest((resources/'engines/write/engine.json').read_bytes())}], 'files': {}}
        if args.pdf_engine:
            pdf_metadata = json.loads((resources/'engines/pdf/engine.json').read_bytes())
            manifest['components'].append({'name': 'dobe-pdf', 'version': pdf_metadata['version'], 'source_lock_sha256': pdf_metadata['source_lock_sha256'],
                                          'engine_manifest_sha256': digest((resources/'engines/pdf/engine.json').read_bytes())})
        for path in resources.rglob('*'):
            if path.is_file(): manifest['files'][path.relative_to(resources.parent.parent).as_posix()] = {'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes())}
        (resources/'bundle.json').write_text(json.dumps(manifest, sort_keys=True)+'\n')
        result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--engine', str(args.engine.resolve()),
                                 '--project', str(args.project.resolve()), '--output', str(out), '--staged'], timeout=240)
        raise SystemExit(result.returncode)
    sys.path.insert(0, str(runtime))
    from studio_runtime import write, write_binding, write_project as project, capabilities
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    checks = []; jobs = []; refusals = []
    state = out/'state'; store = Store(state)
    original_bundle = args.project.read_bytes(); original = project.inspect_bytes(original_bundle)
    model = original['baseline']['document']
    os.environ['PATH'] = '/usr/bin:/bin'
    os.environ['STUDIO_BUNDLE_RESOURCES'] = str(out/'untrusted-resources')
    code = "import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"

    def check(label, condition=True):
        if not condition: raise AssertionError(label)
        checks.append(label)

    def request(method, params):
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(runtime), str(state)],
                                input=(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})+'\n').encode(), capture_output=True, timeout=30)
        if result.returncode: raise AssertionError(result.stderr.decode()[:2000])
        response = json.loads(result.stdout)
        if 'error' in response: raise AssertionError(response)
        return response['result']

    def call(name, params):
        result = request('tools/call', {'name': 'dope_'+name, 'arguments': params})
        if result.get('isError'): raise ValueError(result['content'][0]['text'])
        return json.loads(result['content'][0]['text'])

    def cli(*arguments):
        program = "import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(runtime), '--state', str(state), *map(str, arguments)], capture_output=True, timeout=30)
        if result.returncode: raise AssertionError(result.stderr.decode()[:2000])
        return json.loads(result.stdout)

    def refused(label, action):
        try: action()
        except ValueError as error: checks.append(label); refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)

    def job(identity, operation, params, key, previous=None, *, success=True):
        arguments = {'project': identity, 'operation': operation, 'parameters': params, 'idempotency_key': key}
        if previous: arguments['source_revision'] = previous['id']
        submitted = call('submit_job', arguments)
        check(key+' idempotent after client exits', call('submit_job', arguments)['id'] == submitted['id'])
        Worker(store).run_one(); actual = call('get_job', {'job': submitted['id']}); jobs.append(actual)
        check(key+' durable outcome: '+str(actual.get('error')), actual['state'] == ('succeeded' if success else 'failed'))
        if not success:
            check(key+' failure publishes no revision', actual['result_revision'] is None and store.get_project('local', identity)['head'] == (previous['id'] if previous else None))
            return actual
        result = call('get_revision', {'revision': actual['result_revision']})
        check(key+' complete observation with explicit fidelity limits', result['validation']['native_model_equal'] and result['validation']['native_cold_reopen']
              and not result['validation']['source_format_fidelity_qualified'] and not result['validation']['render_qualified'])
        return result

    def checkout(label, value):
        path = out/label; call('export_project', {'revision': value['id'], 'destination': str(path)}); return path

    def asset(identity, data, name):
        path = out/name; path.write_bytes(data); return store.import_asset('local', identity, path)['id']

    try:
        tools = request('tools/list', {})['tools']; operations = next(t for t in tools if t['name'] == 'dope_submit_job')['inputSchema']['properties']['operation']['enum']
        check('same product MCP exposes all six Write operations', set(write.OPERATIONS) <= set(operations) and 'write.export' in operations)
        cap = cli('capabilities')['applications']['write']
        check('capabilities distinguish available engine from unresolved delivery gates', cap['available'] and not cap['installed_qualification']
              and not cap['direct_docx_import_qualified'] and cap['render_qualified'] and set(cap['export_formats']) == {'dobewrite', 'png', 'pdf'})
        check('engine resolution ignores PATH and resource environment', write_binding.resolve()['executable'] == resources/'engines/write/bin/dobe-write')
        identity = call('create_project', {'name': 'Write authoring'})['id']
        first = job(identity, 'write.create', {'document': model}, 'create')
        initial = checkout('created', first); initial_data = (initial/'native/project.dobewrite').read_bytes()
        check('created source is complete independently supplied model', project.inspect_bytes(initial_data)['current']['document'] == model)
        edit = {'expected_sha256': digest(initial_data), 'edits': [{'kind': 'text.replace', 'path': '/body/2', 'start': 3, 'end': 11, 'expected': 'Original', 'value': 'Ångström craft'}]}
        request_path = out/'edit.json'; request_path.write_text(json.dumps(edit))
        submitted = cli('submit', identity, 'write.edit', '--parameters', request_path, '--key', 'edit', '--source', first['id'])
        Worker(store).run_one(); edited_job = cli('job', submitted['id']); jobs.append(edited_job)
        check('CLI edit publishes durable revision', edited_job['state'] == 'succeeded')
        second = cli('revision', edited_job['result_revision']); edited = checkout('edited', second)
        expected = copy.deepcopy(model); expected['body'][2]['text'] = '\ufffcÅngström craft\ufffc ceramic study.'; expected['body'][2]['runs'][1]['len'] = 16
        check('entire edited native model equals independent prediction', json.loads((edited/'native/document.json').read_bytes()) == expected)
        third = job(identity, 'write.inspect', {}, 'inspect', second)
        fourth = job(identity, 'write.bundle', {}, 'bundle', third); delivered = checkout('delivered', fourth)
        final_data = (delivered/'native/project.dobewrite').read_bytes()
        check('editable delivery equals verified portable source bytes', (delivered/'exports/document.dobewrite').read_bytes() == final_data)
        check('original and origin recipe survive editing and delivery', (delivered/'native/original.json').read_bytes() == (initial/'native/original.json').read_bytes()
              and (delivered/'recipes/origin-write-operation.json').read_bytes() == (initial/'recipes/origin-write-operation.json').read_bytes())
        check('first committed revision remains unchanged', call('get_revision', {'revision': first['id']}) == first)
        check('temporary inputs are not durable artifacts', not any(f['path'].startswith(('inputs/', '.write-attempt-')) for f in fourth['files']))
        imported_id = call('create_project', {'name': 'Portable Write'})['id']
        imported_asset = asset(imported_id, final_data, 'portable.dobewrite')
        imported = job(imported_id, 'write.import', {'asset': imported_asset, 'format': 'dobewrite'}, 'import')
        imported_path = checkout('imported', imported)
        check('portable import keeps source, history and bundle exact', (imported_path/'native/project.dobewrite').read_bytes() == final_data)
        text = expected['body'][2]['text'].encode(); start = text.index(b'ceramic')
        portable_edit = {'expected_sha256': digest(final_data), 'edits': [{'kind': 'text.replace', 'path': '/body/2', 'start': start, 'end': start+7, 'expected': 'ceramic', 'value': 'porcelain'}]}
        portable_next = job(imported_id, 'write.edit', portable_edit, 'portable-edit', imported)
        check('portable source remains editable in another project', portable_next['parent'] == imported['id'])
        transferred = store.import_project('local', delivered, 'Whole project transfer')
        transferred_next = job(transferred['project']['id'], 'write.inspect', {}, 'transfer-inspect', transferred['revision'])
        check('whole project transfer retains native engine identity', transferred_next['engine']['name'] == 'wordcraft')
        raw_id = call('create_project', {'name': 'JSON source'})['id']; raw = original['members']['baseline.json']
        raw_asset = asset(raw_id, raw, 'original.json')
        raw_revision = job(raw_id, 'write.import', {'asset': raw_asset, 'format': 'json'}, 'raw')
        check('imported JSON exact bytes retained', (checkout('raw', raw_revision)/'native/original.json').read_bytes() == raw)
        job(identity, 'write.edit', edit, 'stale', fourth, success=False)
        mismatch_id = call('create_project', {'name': 'Omitted default'})['id']
        missing = copy.deepcopy(model); del missing['core']['subject']
        missing_asset = asset(mismatch_id, json.dumps(missing).encode(), 'missing-default.json')
        job(mismatch_id, 'write.import', {'asset': missing_asset, 'format': 'json'}, 'mismatch', success=False)
        refused('foreign project asset rejected by public MCP', lambda: call('submit_job', {'project': identity, 'operation': 'write.import', 'parameters': {'asset': raw_asset, 'format': 'json'}, 'idempotency_key': 'foreign'}))
        for label, operation, params, source in [
            ('raw import path', 'write.import', {'asset': '/tmp/source.json', 'format': 'json'}, None),
            ('unqualified direct DOCX', 'write.import', {'asset': raw_asset, 'format': 'docx'}, None),
            ('caller receipt injection', 'write.inspect', {'engine': '/tmp/dobe-write'}, 'source'),
            ('arbitrary native command', 'write.edit', {'command': 'file.open'}, 'source'),
            ('inspection needs source', 'write.inspect', {}, None),
            ('create cannot replace revision', 'write.create', {'document': model}, 'source')]:
            refused(label, lambda op=operation, p=params, s=source: write.validate(op, p, s))
        # The runtime derives its own bundle path. An adjacent tampered receipt
        # fails before publication; neither PATH nor project data repairs it.
        receipt_path = resources/'bundle.json'; receipt_bytes = receipt_path.read_bytes()
        damaged = json.loads(receipt_bytes); damaged['files']['lib/dobe/engines/write/bin/dobe-write']['sha256'] = '0'*64
        receipt_path.write_text(json.dumps(damaged))
        try:
            check('damaged receipt reports unavailable', not write_binding.available())
            job(identity, 'write.inspect', {}, 'damaged-receipt', fourth, success=False)
        finally: receipt_path.write_bytes(receipt_bytes)
        job(identity, 'write.inspect', {}, 'restored-receipt', fourth)
        check('upstream portable input and native engine unchanged', args.project.read_bytes() == original_bundle
              and digest(args.engine.read_bytes()) == digest((resources/'engines/write/bin/dobe-write').read_bytes()))
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'durable_jobs': len(jobs),
                    'succeeded': sum(job['state'] == 'succeeded' for job in jobs), 'operations': list(write.OPERATIONS),
                    'public_tools': len(tools), 'distribution_layout_fixture': True, 'installed_qualification': False,
                    'remote_actions': False, 'goal_complete': False}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'durable_jobs': len(jobs), 'succeeded': evidence['succeeded']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally: (out/'jobs.json').write_text(json.dumps(jobs, indent=2)+'\n')


if __name__ == '__main__': main()
