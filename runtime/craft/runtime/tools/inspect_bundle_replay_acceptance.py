#!/usr/bin/env python3
"""Replay owned Inspect fixtures with fresh, hash-bound caller authorization.

Run with package Python under an OS network-deny policy. Input entries contain
path, bytes, sha256 and a separate explicit authorization object. The fixture
uses real static-analysis engines; it never executes an inspected target.
"""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
import types
import zipfile


LABELS = {'annotated', 'bundle', 'elf', 'empty-notes', 'fallback-javascript', 'html',
          'inspected', 'invalid-wasm', 'json', 'mach-o', 'native-imported', 'original',
          'pe', 'portable-json', 'removed-note', 'resolved-note', 'second-note', 'wasm'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); package = args.package.resolve(strict=True)
    inputs = json.loads(args.inputs.read_text())
    if type(inputs) is not dict or set(inputs) != LABELS:
        raise ValueError('eighteen owned, checksum-bound Inspect fixtures required')
    for info in inputs.values():
        if type(info) is not dict or set(info) != {'path', 'bytes', 'sha256', 'authorization'}:
            raise ValueError('fixture needs separate explicit authorization and a file receipt')
        path = Path(info['path'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 << 20:
            raise ValueError('fixture must be a bounded regular absolute file')
        raw = path.read_bytes()
        if len(raw) != info['bytes'] or sha(raw) != info['sha256']:
            raise ValueError('fixture differs from retained evidence')
    args.output.mkdir(mode=0o700); output = args.output.resolve(strict=True)
    source = Path(__file__).resolve().parents[1]/'studio_runtime'
    sys.path.insert(0, str(package/'lib/dobe/runtime'))
    import studio_runtime
    modules = ('inspect_source', 'inspect_host', 'inspect_project', 'inspect_engine', 'inspection',
               'inspect_bundle', 'bundle_replay', 'bundle')
    for name in modules:
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, source/(name+'.py'))
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
        spec.loader.exec_module(module); setattr(studio_runtime, name, module)
    from studio_runtime import bundle, inspect_bundle, inspect_engine, inspect_binding, inspect_project, inspect_source, inspect_host
    binding = inspect_binding.resolve(); empty = output/'empty-path'; empty.mkdir(); os.environ['PATH'] = str(empty)
    attempts = []
    original_engine = inspect_engine.Engine

    class ObservedEngine(original_engine):
        def __init__(self, *arguments, **keywords):
            attempts.append({'started': time.time()})
            super().__init__(*arguments, **keywords)

    inspect_engine.Engine = ObservedEngine
    report = {'started': time.time(), 'inputs': inputs, 'cases': [], 'refusals': [],
              'sourceModules': {name: sha((source/(name+'.py')).read_bytes()) for name in modules},
              'nativeExecutable': str(binding['executable']), 'nativeExecutableSha256': binding['expected_binary_sha256'],
              'sealedSourceQualified': False, 'linuxQualified': False, 'hostedAdmissionChanged': False,
              'enginePathEmpty': True, 'nativeConstructionObserverDelegatesToRealEngine': True}

    def save():
        report['nativeEngineConstructions'] = len(attempts)
        (output/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')

    def consent(info):
        return {'inspect': dict(info['authorization'])}

    def refused(label, path, expected, authorization=None, profile=('inspect',), before_engine=False):
        start = len(attempts)
        try:
            bundle.execute(path, output/('denied-'+str(len(report['refusals']))), 64 << 20,
                           replay_families=profile, replay_authorizations=authorization)
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError('wrong refusal for '+label+': '+str(error)) from error
            if before_engine:
                assert len(attempts) == start, 'consent/admission refusal started a native engine'
            report['refusals'].append({'label': label, 'message': str(error)[:400],
                                       'nativeEnginesStarted': len(attempts)-start}); save()
        else:
            raise AssertionError(label+' unexpectedly succeeded')

    for label, info in inputs.items():
        started = time.monotonic()
        result = bundle.execute(info['path'], output/label, 64 << 20,
                                replay_families=('inspect',), replay_authorizations=consent(info))
        validation = result['validation']
        for key in ('passed', 'native_cold_reopen', 'native_model_equal', 'native_inventory_equal',
                    'initial_source_preserved', 'imported_native_bytes_preserved', 'original_files_unchanged',
                    'export_semantics_replayed', 'annotation_history_replayed', 'current_content_deliveries_replayed',
                    'historical_request_consistent'):
            assert validation[key] is True, key
        assert not validation['native_history_replayed'] and not validation['visual_approval']
        assert not validation['historical_execution_authenticated']
        assert validation['native_replay_validation']['input_executed'] is False
        assert validation['native_replay_validation']['external_references_resolved'] is False
        report['cases'].append({'label': label, 'wallSeconds': time.monotonic()-started, 'result': result}); save()
        refused(label+' default hosted boundary', info['path'], 'bundle engine is not qualified', profile=(), before_engine=True)
        refused(label+' stored consent grants nothing', info['path'], 'fresh replay input consent is required', before_engine=True)

    original = inputs['original']; authorized = consent(original)
    wrong = copy.deepcopy(authorized); wrong['inspect']['input_sha256'] = '0'*64
    refused('wrong-input-consent', original['path'], 'consent does not match original input', wrong, before_engine=True)
    wrong = copy.deepcopy(authorized); wrong['inspect']['expected_sha256'] = '0'*64
    refused('stale-project-consent', original['path'], 'portable revision hash is stale', wrong, before_engine=True)
    wrong = copy.deepcopy(authorized); wrong['inspect']['permission'] = 'inherited-from-recipe'
    refused('inherited-permission', original['path'], 'explicit input consent is required', wrong, before_engine=True)
    refused('unselected-consent-profile', original['path'], 'authorization requires an explicit Inspect replay profile',
            authorized, profile=(), before_engine=True)
    refused('unknown-consent-family', original['path'], 'replay authorization keys are invalid',
            {'video': authorized['inspect']}, before_engine=True)
    old_platform = inspect_host.platform
    try:
        # A local unsupported-host branch check, not foreign engine execution.
        inspect_host.platform = types.SimpleNamespace(system=lambda: 'Linux', machine=lambda: 'aarch64')
        refused('unsupported-host-policy', original['path'], 'replay host is unsupported', authorized, before_engine=True)
    finally:
        inspect_host.platform = old_platform

    def update(members, manifest, path, data):
        members[path] = data
        next(f for f in manifest['files'] if f['path'] == path).update(bytes=len(data), sha256=sha(data))

    def variant(label, fixture, change, expected, before_engine=False):
        with zipfile.ZipFile(inputs[fixture]['path']) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(members['project.json']); change(members, manifest)
        members['project.json'] = (json.dumps(manifest, sort_keys=True)+'\n').encode()
        destination = output/(label+'.zip')
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in members.items():
                archive.writestr(path, data)
        # These are explicitly constructed owned negative fixtures. Authorize
        # their exact native bytes without taking consent from any recipe.
        authorization = consent(inputs[fixture])
        authorization['inspect']['expected_sha256'] = sha(members['native/project.dobeinspect'])
        refused(label, destination, expected, authorization, before_engine=before_engine)

    def report_change(members, manifest, change):
        with zipfile.ZipFile(io.BytesIO(members['native/project.dobeinspect'])) as archive:
            inner = {name: archive.read(name) for name in archive.namelist()}
        native_manifest = json.loads(inner.pop('project.json'))
        report = json.loads(inner['report.json']); change(report)
        inner['report.json'] = inspect_source.encoded(report)
        native_manifest['report'] = sha(inner['report.json'])
        native_manifest['members'] = {name: inspect_project.record(data) for name, data in inner.items()}
        update(members, manifest, 'native/project.dobeinspect', inspect_project.pack(native_manifest, inner))
        for name, data in inner.items():
            update(members, manifest, 'native/'+name, data)

    def break_notes(members, manifest):
        with zipfile.ZipFile(io.BytesIO(members['native/project.dobeinspect'])) as archive:
            inner = {name: archive.read(name) for name in archive.namelist()}
        native_manifest = json.loads(inner.pop('project.json')); notes = json.loads(inner['annotations.json'])
        notes[0]['text'] += ' forged'; inner['annotations.json'] = inspect_source.encoded(notes)
        native_manifest['current'] = sha(inner['annotations.json'])
        native_manifest['members'] = {name: inspect_project.record(data) for name, data in inner.items()}
        update(members, manifest, 'native/project.dobeinspect', inspect_project.pack(native_manifest, inner))
        update(members, manifest, 'native/annotations.json', inner['annotations.json'])

    def add(members, manifest, path, role, data):
        members[path] = data; manifest['files'].append({'path': path, 'role': role, 'bytes': len(data), 'sha256': sha(data)})

    variant('forged-native-findings', 'original', lambda m, j: report_change(m, j,
            lambda value: value['evidence']['result'].update(forged=True)), 'complete native report replay differs')
    variant('unqualified-report-platform', 'original', lambda m, j: report_change(m, j,
            lambda value: value['evidence']['environment'].update(host='windows-x86_64')),
            'report environment is unsupported', True)
    variant('broken-annotation-chain', 'annotated', break_notes, 'annotations differ from complete history replay', True)
    variant('mismatched-published-native', 'original', lambda m, j: update(m, j, 'native/report.json', b'{}'),
            'published native member differs from portable source', True)
    variant('extra-native', 'original', lambda m, j: add(m, j, 'native/extra.json', 'native', b'{}'),
            'bundle native inventory differs')
    variant('extra-asset', 'original', lambda m, j: add(m, j, 'assets/unused.bin', 'asset', b'unused'),
            'source/delivery inventory differs')
    variant('forged-inspection-summary', 'original', lambda m, j: update(m, j, 'exports/inspection.json', b'{}'),
            'delivery differs from current native findings')
    variant('altered-json-delivery', 'json', lambda m, j: update(m, j, 'exports/findings.json', b'{}'),
            'delivery differs from current native findings')
    variant('active-html-delivery', 'html', lambda m, j: update(m, j, 'exports/findings.html', b'<script>alert(1)</script>'),
            'delivery differs from current native findings')
    variant('altered-portable-delivery', 'bundle', lambda m, j: update(m, j, 'exports/findings.dobeinspect', b'not a portable project'),
            'delivery differs from current native findings')
    def wrong_request(members, manifest):
        recipe = json.loads(members['recipes/last-inspect-operation.json']); recipe['parameters']['edits'][0]['text'] += ' wrong'
        update(members, manifest, 'recipes/last-inspect-operation.json', inspect_source.encoded(recipe))
    variant('wrong-retained-annotation-request', 'annotated', wrong_request, 'retained annotation request differs')
    for info in inputs.values():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    assert inspect_binding.resolve() == binding
    report.update(passed=True, completed=time.time(), nativeCases=len(report['cases']), refusalCases=len(report['refusals']),
                  originalInputsUnchanged=True, linuxPolicyCheckOnly=True)
    save(); print('PASS', report['nativeCases'], 'Inspect replays and', report['refusalCases'], 'refusals'); print(output/'evidence.json')


if __name__ == '__main__':
    main()
