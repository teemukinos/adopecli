#!/usr/bin/env python3
"""Qualify portable Material/Texture source replay with real packaged engines.

Use packaged Python under an OS network-deny policy. The checksum-bound input
JSON has material-revised, material-restored, texture-linked and texture-restored
keys, each containing path, bytes and sha256. Output must be a fresh directory.
No package mutation, hosted admission, rendering approval or Linux claim follows.
"""
import argparse
import hashlib
import importlib.util
import io
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
    if type(inputs) is not dict or set(inputs) != {'material-revised', 'material-restored', 'texture-linked', 'texture-restored'}:
        raise ValueError('four checksum-bound surface bundles required')
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
    modules = ('material', 'texture', 'surface_binding', 'bundle_replay', 'bundle')
    for name in modules:
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, source/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        setattr(studio_runtime, name, module)
    from studio_runtime import bundle, surface_binding
    # An empty engine search path proves imported content cannot choose a host
    # executable. Both maintained engines resolve exclusively from receipts.
    os.environ['PATH'] = str(output/'no-engine-search-path')
    bindings = {family: surface_binding.resolve(family) for family in ('material', 'texture')}
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
        assert validation['initial_source_preserved'] is (family == 'material')
        assert validation['export_semantics_replayed'] is False
        assert validation['visual_approval'] is False
        if family == 'texture':
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
        source_input = inputs['material-revised' if family == 'material' else 'texture-linked']['path']
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

    for family in ('material', 'texture'):
        path = modified(family, 'wrong-objects', lambda m, j: update(m, j, 'native/objects.json', b'{}\n'))
        refused(family+' inconsistent native mapping', path, family, 'native replay changed the imported editable state')
        path = modified(family, 'extra-native', extra_native)
        refused(family+' extra native member', path, family, 'bundle native inventory differs')

        def altered_export(members, manifest):
            path = next(item['path'] for item in manifest['files'] if item['role'] == 'export')
            update(members, manifest, path, b'Explicitly unvalidated surface export.\n')

        path = modified(family, 'unvalidated-export', altered_export)
        execute(family+'-preserved-unvalidated-export', path, family)
    # Original Texture source is not opened by the ordinary inspect adapter.
    # Portable replay must refuse its corruption even with valid outer hashes.
    path = modified('texture', 'invalid-retained-source',
                    lambda m, j: update(m, j, 'native/source.tcraft', b'not a native archive\n'))
    refused('Texture invalid retained original', path, 'texture', 'Texture')

    def unapproved_uvs(members, manifest):
        path = 'native/source.tcraft'
        with zipfile.ZipFile(io.BytesIO(members[path])) as archive:
            native = {name: archive.read(name) for name in archive.namelist()}
        project = json.loads(native['project.json'])
        project['mesh'] = 'mesh.obj'
        native['project.json'] = (json.dumps(project, sort_keys=True)+'\n').encode()
        native['mesh.obj'] = b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in native.items():
                archive.writestr(name, raw)
        update(members, manifest, path, buffer.getvalue())
        recipe_path = 'recipes/last-texture-operation.json'
        update(members, manifest, recipe_path,
               b'{"operation":"texture.inspect","parameters":{"accept_generated_uvs":true}}\n')

    path = modified('texture', 'unapproved-uvs', unapproved_uvs)
    refused('embedded recipe cannot authorize generated UVs', path, 'texture',
            'requires explicit acceptance of generated UVs')
    for family, binding in bindings.items():
        assert surface_binding.resolve(family) == binding
    for info in inputs.values():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    report.update(passed=True, completed=time.time(), nativeCases=len(report['cases']),
                  refusalCases=len(report['refusals']), originalInputsUnchanged=True)
    save()
    print('PASS six native surface replays and ten boundary refusals')
    print(output/'evidence.json')


if __name__ == '__main__':
    main()
