#!/usr/bin/env python3
"""Qualify portable Layout/Interface/Animate source replay with real packaged engines.

Use packaged Python under an OS network-deny policy. The checksum-bound input
JSON has layout-original, layout-revised, interface-original, interface-revised, animate-revised and animate-restored
keys, each containing path, bytes and sha256. Output must be a fresh directory.
No package mutation, hosted admission, rendering approval or Linux claim follows.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import zipfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    inputs = json.loads(args.inputs.read_text())
    if type(inputs) is not dict or set(inputs) != {'layout-original','layout-revised','interface-original','interface-revised','animate-revised','animate-restored'}:
        raise ValueError('six checksum-bound publication bundles required')
    for info in inputs.values():
        if type(info) is not dict or set(info) != {'path', 'bytes', 'sha256'}:
            raise ValueError('fixture requires path, bytes and sha256')
        path = Path(info['path'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 << 20:
            raise ValueError('fixture must be a bounded regular absolute file')
        raw = path.read_bytes()
        if len(raw) != info['bytes'] or sha(raw) != info['sha256']:
            raise ValueError('fixture differs from retained evidence')
    args.output.mkdir(mode=0o700)
    output = args.output.resolve(strict=True)
    source = Path(__file__).resolve().parents[1]/'studio_runtime'
    sys.path.insert(0, str(package/'lib/dobe/runtime'))
    import studio_runtime
    modules = ('layout_engine', 'layout', 'interface_engine', 'interface_project', 'interface', 'animate', 'publication_binding', 'bundle_replay', 'bundle')
    for name in modules:
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, source/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        setattr(studio_runtime, name, module)
    from studio_runtime import bundle, publication_binding
    # An empty engine search path proves imported content cannot choose a host
    # executable. The maintained engines resolve exclusively from receipts.
    os.environ['PATH'] = str(output/'no-engine-search-path')
    bindings = {family: publication_binding.resolve(family) for family in ('layout', 'interface', 'animate')}
    report = {'started': time.time(), 'inputs': inputs, 'cases': [], 'refusals': [],
              'sourceModules': {name: sha((source/(name+'.py')).read_bytes()) for name in modules},
              'engineHashes': {family: value['expected_binary_sha256'] for family, value in bindings.items()},
              'sealedSourceQualified': False, 'linuxQualified': False, 'hostedAdmissionChanged': False,
              'engineSearchPathEmpty': True}

    def save():
        (output/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')

    def execute(label, path, family):
        started = time.monotonic()
        result = bundle.execute(path, output/label, 64 << 20, replay_families=(family,))
        validation = result['validation']
        for key in ('passed', 'native_cold_reopen', 'native_model_equal', 'native_inventory_equal',
                    'imported_native_bytes_preserved', 'original_files_unchanged'):
            assert validation[key] is True, key
        assert validation['native_history_replayed'] is False
        assert validation['initial_source_preserved'] is False
        assert validation['export_semantics_replayed'] is False
        assert validation['visual_approval'] is False
        if family == 'animate':
            assert validation['retained_source_replay']['native_cold_reopen'] is True
            assert validation['additional_native_history_observations'] == []
        report['cases'].append({'label': label, 'family': family, 'wallSeconds': time.monotonic()-started, 'result': result})
        save()

    def refused(label, path, family, expected, *, default=False):
        try:
            bundle.execute(path, output/('denied-'+str(len(report['refusals']))), 64 << 20,
                           replay_families=() if default else (family,))
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError('wrong refusal for '+label+': '+str(error)) from error
            report['refusals'].append({'label': label, 'message': str(error)[:400]})
            save()
        else:
            raise AssertionError(label+' unexpectedly succeeded')

    for label, info in inputs.items():
        family = label.split('-')[0]
        execute(label, info['path'], family)
        refused(label+' default hosted boundary', info['path'], family, 'bundle engine is not qualified', default=True)

    def modified(family, label, change):
        source_input = inputs[family+'-revised']['path']
        with zipfile.ZipFile(source_input) as archive:
            members = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
        manifest = json.loads(members['project.json'])
        change(members, manifest)
        members['project.json'] = (json.dumps(manifest, sort_keys=True)+'\n').encode()
        destination = output/(family+'-'+label+'.zip')
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, raw in members.items():
                archive.writestr(path, raw)
        return destination

    def update(members, manifest, path, raw):
        members[path] = raw
        item = next(item for item in manifest['files'] if item['path'] == path)
        item.update(bytes=len(raw), sha256=sha(raw))

    def extra_native(members, manifest):
        path, raw = 'native/extra.json', b'{}\n'
        members[path] = raw
        manifest['files'].append({'path': path, 'role': 'native', 'bytes': len(raw), 'sha256': sha(raw)})

    for family in ('layout', 'interface', 'animate'):
        path = modified(family, 'wrong-objects', lambda m, j: update(m, j, 'native/objects.json', b'{}\n'))
        refused(family+' inconsistent native mapping', path, family, 'mapping does not cover' if family in ('layout', 'interface') else 'native replay changed the imported editable state')
        path = modified(family, 'extra-native', extra_native)
        refused(family+' extra native member', path, family, 'bundle native inventory differs')

        def altered_export(members, manifest):
            path = next(item['path'] for item in manifest['files'] if item['role'] == 'export')
            update(members, manifest, path, b'Explicitly unvalidated publication export.\n')

        path = modified(family, 'unvalidated-export', altered_export)
        execute(family+'-preserved-unvalidated-export', path, family)
    # An incomplete but individually valid mapping must not hide an editable frame.
    def partial_mapping(members, manifest):
        path = 'native/objects.json'
        mapping = json.loads(members[path])
        assert len(mapping) > 1
        mapping.pop(next(iter(mapping)))
        update(members, manifest, path, (json.dumps(mapping, sort_keys=True)+'\n').encode())

    path = modified('layout', 'partial-mapping', partial_mapping)
    refused('Layout partial native mapping', path, 'layout', 'mapping does not cover')
    # Ordinary inspection retains the original animation without opening it.
    path = modified('animate', 'invalid-retained-source',
                    lambda m, j: update(m, j, 'native/source.anicraft', b'not a native document\n'))
    refused('Animate invalid retained original', path, 'animate', 'Expecting value:')
    for family, binding in bindings.items():
        assert publication_binding.resolve(family) == binding
    for info in inputs.values():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    report.update(passed=True, completed=time.time(), nativeCases=len(report['cases']),
                  refusalCases=len(report['refusals']), originalInputsUnchanged=True)
    save()
    print('PASS nine native publication replays and fourteen boundary refusals')
    print(output/'evidence.json')


if __name__ == '__main__':
    main()
