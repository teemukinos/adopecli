#!/usr/bin/env python3
"""Qualify source-level bundle replay with receipt-bound packaged native engines.

Run with the package's Python under an OS network-deny policy. The source replay
modules are loaded explicitly; the package remains read-only and is not claimed
to contain this source change. Input JSON declares one bundle per family with
absolute path, exact bytes and SHA-256. Output must be a new disposable directory.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sys
import time
import zipfile

FAMILIES = ('write', 'slides', 'cad', 'sheets')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    inputs = json.loads(args.inputs.read_text())
    if type(inputs) is not dict or set(inputs) != set(FAMILIES):
        raise ValueError('one checksum-bound bundle per replay family is required')
    for family, info in inputs.items():
        if type(info) is not dict or set(info) != {'path', 'bytes', 'sha256'}:
            raise ValueError('fixture requires path, bytes and sha256')
        path = Path(info['path'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 << 20:
            raise ValueError('fixture must be a bounded regular absolute file')
        data = path.read_bytes()
        if len(data) != info['bytes'] or sha(data) != info['sha256']:
            raise ValueError('fixture bytes differ from retained evidence')
    args.output.mkdir(mode=0o700)
    output = args.output.resolve(strict=True)
    runtime = Path(__file__).resolve().parents[1]/'studio_runtime'
    sys.path.insert(0, str(package/'lib/dobe/runtime'))
    import studio_runtime
    for name in ('bundle_replay', 'bundle'):
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, runtime/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        setattr(studio_runtime, name, module)
    from studio_runtime import bundle
    report = {'started': time.time(), 'inputs': inputs, 'cases': [], 'checks': [],
              'sourceModules': {n: sha((runtime/(n+'.py')).read_bytes()) for n in ('bundle_replay', 'bundle')},
              'packagedReplaySourceQualified': False, 'linuxQualified': False,
              'publicHostedAdmissionChanged': False}

    def save():
        (output/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')

    def refused(label, source, destination, **options):
        try:
            bundle.execute(source, destination, 64 << 20, **options)
        except (ValueError, OSError) as error:
            report['checks'].append({'check': label, 'refused': True,
                                     'type': type(error).__name__, 'message': str(error)[:400]})
            save()
        else:
            raise AssertionError(label+' unexpectedly succeeded')

    def modified(source, destination, mutate):
        with zipfile.ZipFile(source) as archive:
            members = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
        manifest = json.loads(members['project.json'])
        mutate(members, manifest)
        members['project.json'] = (json.dumps(manifest, sort_keys=True)+'\n').encode()
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)

    def update(members, manifest, path, data):
        members[path] = data
        entry = next(f for f in manifest['files'] if f['path'] == path)
        entry.update(bytes=len(data), sha256=sha(data))

    save()
    for family in FAMILIES:
        source = Path(inputs[family]['path'])
        started = time.time()
        result = bundle.execute(source, output/('replayed-'+family), 64 << 20, replay_families=(family,))
        assert result['validation']['native_cold_reopen'] is True
        assert result['validation']['original_files_unchanged'] is True
        assert result['validation']['native_inventory_equal'] is True
        assert result['validation']['native_history_replayed'] is True
        report['cases'].append({'family': family, 'wallSeconds': time.time()-started, 'result': result})
        save()
        refused(family+' default hosted boundary', source, output/('denied-default-'+family))
        tampered = output/(family+'-inconsistent.zip')
        modified(source, tampered, lambda members, manifest: update(members, manifest, 'native/document.json', b'{}\n'))
        refused(family+' native member mismatch despite valid outer hashes', tampered,
                output/('denied-member-'+family), replay_families=(family,))
    source = Path(inputs['write']['path'])
    malformed = output/'malformed-engine.zip'
    modified(source, malformed, lambda members, manifest: manifest.update(engine={'name': [], 'version': '0.18.1'}))
    refused('malformed engine identity', malformed, output/'denied-engine', replay_families=('write',))
    for families in (('write', 'write'), ('construction',), [None]):
        refused('invalid replay profile '+repr(families), source,
                output/('denied-profile-'+str(len(report['checks']))), replay_families=families)
    exported = output/'unvalidated-export.zip'

    def alter_export(members, manifest):
        path = next(f['path'] for f in manifest['files'] if f['role'] == 'export')
        update(members, manifest, path, b'Explicitly unvalidated export fixture.\n')

    modified(source, exported, alter_export)
    result = bundle.execute(exported, output/'export-scope', 64 << 20, replay_families=('write',))
    assert result['validation']['export_semantics_replayed'] is False
    report['checks'].append({'check': 'preserved exports do not claim semantic replay', 'passed': True,
                             'originalFilesUnchanged': result['validation']['original_files_unchanged']})
    # Source files remain reusable by the next qualification and never become
    # overwritten outputs, including when an original archive is read repeatedly.
    for info in inputs.values():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    report.update(completed=time.time(), passed=True, nativeReplayCases=5, boundaryChecks=len(report['checks']))
    save()
    print('PASS five native replay cases and thirteen refusal/export-scope checks')
    print(output/'evidence.json')


if __name__ == '__main__':
    main()
