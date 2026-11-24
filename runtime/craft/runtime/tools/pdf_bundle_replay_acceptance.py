#!/usr/bin/env python3
"""Replay PDF bundles with packaged engines and explicit, unsealed source modules.

Use the package Python under an OS network-deny policy. Inputs are a JSON object
with original, replacement-restyled and portable-restored keys. Each entry has
an absolute path, byte count and SHA-256. Output must be a new scratch directory.
The read-only package supplies the receipt-bound engine and unchanged helpers.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import time
import zipfile


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
    if type(inputs) is not dict or set(inputs) != {'original', 'replacement-restyled', 'portable-restored'}:
        raise ValueError('three checksum-bound PDF fixtures required')
    for info in inputs.values():
        if type(info) is not dict or set(info) != {'path', 'bytes', 'sha256'}:
            raise ValueError('fixture requires path, bytes and sha256')
        path = Path(info['path'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 << 20:
            raise ValueError('fixture must be a bounded regular absolute file')
        raw = path.read_bytes()
        if len(raw) != info['bytes'] or sha(raw) != info['sha256']:
            raise ValueError('fixture differs from its retained evidence')
    args.output.mkdir(mode=0o700)
    output = args.output.resolve(strict=True)
    source = Path(__file__).resolve().parents[1]/'studio_runtime'
    sys.path.insert(0, str(package/'lib/dobe/runtime'))
    import studio_runtime
    modules = ('pdf', 'bundle_replay', 'bundle')
    for name in modules:
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, source/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        setattr(studio_runtime, name, module)
    from studio_runtime import bundle, write_binding
    from PIL import Image
    binding = write_binding.resolve_pdf()
    report = {'started': time.time(), 'inputs': inputs, 'cases': [], 'refusals': [],
              'sourceModules': {name: sha((source/(name+'.py')).read_bytes()) for name in modules},
              'nativeExecutable': str(binding['executable']),
              'nativeExecutableSha256': binding['expected_binary_sha256'],
              'sealedSourceQualified': False, 'linuxQualified': False, 'hostedAdmissionChanged': False}

    def save():
        (output/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')

    def refused(label, path, expected, *, profile=('pdf',)):
        try:
            bundle.execute(path, output/('denied-'+str(len(report['refusals']))), 64 << 20,
                           replay_families=profile)
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError('wrong refusal for '+label+': '+str(error)) from error
            report['refusals'].append({'label': label, 'message': str(error)[:400]})
            save()
        else:
            raise AssertionError(label+' unexpectedly succeeded')

    for label, info in inputs.items():
        started = time.monotonic()
        result = bundle.execute(info['path'], output/label, 64 << 20, replay_families=('pdf',))
        validation = result['validation']
        for key in ('passed', 'native_cold_reopen', 'native_model_equal', 'native_inventory_equal',
                    'imported_native_bytes_preserved', 'original_files_unchanged', 'export_semantics_replayed'):
            assert validation[key] is True, key
        assert validation['native_history_replayed'] is False
        assert validation['initial_source_preserved'] is False
        assert validation['visual_approval'] is False
        report['cases'].append({'label': label, 'wallSeconds': time.monotonic()-started, 'result': result})
        save()
        refused(label+' default hosted boundary', info['path'], 'bundle engine is not qualified', profile=())

    with zipfile.ZipFile(inputs['replacement-restyled']['path']) as archive:
        original = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}

    def mutated(label, change, expected):
        members = dict(original)
        manifest = json.loads(members['project.json'])
        change(members, manifest)
        members['project.json'] = (json.dumps(manifest, sort_keys=True)+'\n').encode()
        destination = output/(label+'.zip')
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in members.items():
                archive.writestr(path, data)
        refused(label, destination, expected)

    def update(members, manifest, path, data):
        members[path] = data
        record = next(entry for entry in manifest['files'] if entry['path'] == path)
        record.update(bytes=len(data), sha256=sha(data))

    def add_native(members, manifest):
        path, raw = 'native/undeclared-model.json', b'{}\n'
        members[path] = raw
        manifest['files'].append({'path': path, 'role': 'native', 'bytes': len(raw), 'sha256': sha(raw)})

    def remove_preview(members, manifest):
        path = next(entry['path'] for entry in manifest['files'] if entry['role'] == 'preview')
        del members[path]
        manifest['files'] = [entry for entry in manifest['files'] if entry['path'] != path]

    def changed_pixel(members, manifest):
        path = next(entry['path'] for entry in manifest['files'] if entry['role'] == 'preview')
        with Image.open(io.BytesIO(members[path])) as image:
            image = image.convert('RGBA')
            r, g, b, a = image.getpixel((0, 0))
            image.putpixel((0, 0), (r ^ 1, g, b, a))
            out = io.BytesIO()
            image.save(out, format='PNG')
        update(members, manifest, path, out.getvalue())

    mutated('inconsistent-native-structure', lambda m, j: update(m, j, 'native/structure.json', b'{}\n'),
            'native replay changed the imported editable state')
    mutated('extra-native-member', add_native, 'bundle native inventory differs')
    mutated('altered-pdf-export', lambda m, j: update(m, j, 'exports/document.pdf', b'not a PDF\n'),
            'PDF delivery differs from native replay')
    mutated('altered-inspection-report', lambda m, j: update(m, j, 'exports/inspection.json', b'{}\n'),
            'PDF delivery differs from native replay')
    mutated('missing-page-preview', remove_preview, 'PDF delivery inventory differs')
    mutated('altered-page-pixel', changed_pixel, 'PDF page preview differs')
    for info in inputs.values():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    assert write_binding.resolve_pdf() == binding
    report.update(passed=True, completed=time.time(), nativeCases=len(report['cases']),
                  refusalCases=len(report['refusals']), originalInputsUnchanged=True)
    save()
    print('PASS three native PDF replays and nine boundary refusals')
    print(output/'evidence.json')


if __name__ == '__main__':
    main()
