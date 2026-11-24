#!/usr/bin/env python3
"""Qualify complete Photo libraries and full-precision portable PNG deliveries.

Use the read-only package Python under an OS network-deny policy. The input JSON
contains original, editorial, monochrome and portable-restored checksum-bound
project ZIPs plus formats, raw-revised and eight-bit libraries. Output must be
new. Source overlays are explicit and unsealed.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import time
import zipfile
import zlib


def sha(data):
    return hashlib.sha256(data).hexdigest()


def png_chunks(raw):
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'
    at = 8; result = []
    while at < len(raw):
        size = struct.unpack_from('>I', raw, at)[0]; tag = raw[at+4:at+8]; data = raw[at+8:at+8+size]
        assert zlib.crc32(tag+data) == struct.unpack_from('>I', raw, at+8+size)[0]
        result.append((tag, data)); at += size+12
    assert at == len(raw)
    return result


def png_bytes(chunks):
    return b'\x89PNG\r\n\x1a\n'+b''.join(struct.pack('>I', len(data))+tag+data+struct.pack('>I', zlib.crc32(tag+data))
                                          for tag, data in chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); package = args.package.resolve(strict=True)
    inputs = json.loads(args.inputs.read_text())
    if type(inputs) is not dict or set(inputs) != {'original', 'editorial', 'monochrome', 'portable-restored', 'formats', 'raw-revised', 'eight-bit'}:
        raise ValueError('seven checksum-bound Photo fixtures required')
    for info in inputs.values():
        if type(info) is not dict or set(info) != {'path', 'bytes', 'sha256'}:
            raise ValueError('fixture requires path, bytes and sha256')
        path = Path(info['path'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 64 << 20:
            raise ValueError('fixture must be a bounded regular absolute file')
        raw = path.read_bytes()
        if len(raw) != info['bytes'] or sha(raw) != info['sha256']:
            raise ValueError('fixture differs from its retained evidence')
    args.output.mkdir(mode=0o700); output = args.output.resolve(strict=True)
    source = Path(__file__).resolve().parents[1]/'studio_runtime'
    sys.path.insert(0, str(package/'lib/dobe/runtime'))
    import studio_runtime
    modules = ('photo_library', 'media_binding', 'bundle_replay', 'bundle')
    for name in modules:
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, source/(name+'.py'))
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
        spec.loader.exec_module(module); setattr(studio_runtime, name, module)
    from studio_runtime import photo_library as photo, bundle, media_binding
    from PIL import Image
    binding = media_binding.resolve_photo(); empty = output/'empty-path'; empty.mkdir(); os.environ['PATH'] = str(empty)
    report = {'started': time.time(), 'inputs': inputs, 'cases': [], 'refusals': [],
              'sourceModules': {name: sha((source/(name+'.py')).read_bytes()) for name in modules},
              'nativeExecutable': str(binding['executable']), 'nativeExecutableSha256': binding['expected_binary_sha256'],
              'sealedSourceQualified': False, 'linuxQualified': False, 'hostedAdmissionChanged': False,
              'enginePathEmpty': True}

    def save():
        (output/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')

    def refused(label, path, expected, profile=('photo',)):
        try:
            bundle.execute(path, output/('denied-'+str(len(report['refusals']))), 64 << 20, replay_families=profile)
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError('wrong refusal for '+label+': '+str(error)) from error
            report['refusals'].append({'label': label, 'message': str(error)[:400]}); save()
        else:
            raise AssertionError(label+' unexpectedly succeeded')

    def accepted(label, path):
        started = time.monotonic()
        result = bundle.execute(path, output/label, 64 << 20, replay_families=('photo',))
        validation = result['validation']
        for key in ('passed', 'native_cold_reopen', 'native_model_equal', 'native_inventory_equal',
                    'imported_native_bytes_preserved', 'original_files_unchanged', 'export_semantics_replayed'):
            assert validation[key] is True, key
        assert not validation['native_history_replayed'] and not validation['initial_source_preserved']
        assert not validation['visual_approval']
        assert validation['native_replay_validation']['pixel_validation_precision'] == (8 if label == 'eight-bit' else 16)
        report['cases'].append({'label': label, 'wallSeconds': time.monotonic()-started, 'result': result}); save()

    for label, info in inputs.items():
        accepted(label, info['path'])
        refused(label+' default hosted boundary', info['path'], 'bundle engine is not qualified', ())
    with zipfile.ZipFile(inputs['monochrome']['path']) as archive:
        original = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
    png = next(f['path'] for f in json.loads(original['project.json'])['files'] if f['role'] == 'export')
    model_path = 'native/library/catalog.snap'

    def update(members, manifest, path, data):
        members[path] = data
        next(f for f in manifest['files'] if f['path'] == path).update(bytes=len(data), sha256=sha(data))

    def native_json(members, manifest, path, edit):
        value = json.loads(members[path]); edit(value)
        update(members, manifest, path, (json.dumps(value)+'\n').encode())

    def variant(label, change, expected=None):
        members = dict(original); manifest = json.loads(members['project.json']); change(members, manifest)
        members['project.json'] = (json.dumps(manifest, sort_keys=True)+'\n').encode()
        destination = output/(label+'.zip')
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in members.items():
                archive.writestr(path, data)
        if expected is None:
            accepted(label, destination)
        else:
            refused(label, destination, expected)

    def add_member(members, manifest, path, role, data):
        members[path] = data; manifest['files'].append({'path': path, 'role': role, 'bytes': len(data), 'sha256': sha(data)})

    def pixels(members, manifest, change=False):
        chunks = png_chunks(members[png]); raw = bytearray(zlib.decompress(b''.join(data for tag, data in chunks if tag == b'IDAT')))
        assert struct.unpack('>IIBBBBB', chunks[0][1])[2:4] == (16, 2)
        if change:
            # The first pixel has no preceding row or left pixel. Changing its
            # red low byte alters 16-bit data while retaining all 8-bit output.
            raw[2] ^= 1
        packed = zlib.compress(bytes(raw), 1); result = []; inserted = False
        for tag, data in chunks:
            if tag == b'IDAT':
                if not inserted:
                    result.extend([(b'IDAT', packed[:len(packed)//2]), (b'IDAT', packed[len(packed)//2:])]); inserted = True
            else:
                result.append((tag, data))
        rewritten = png_bytes(result)
        if change:
            with Image.open(io.BytesIO(members[png])) as before, Image.open(io.BytesIO(rewritten)) as after:
                assert before.convert('RGB').tobytes() == after.convert('RGB').tobytes()
            report['altered16BitDataInvisibleAt8Bits'] = True; save()
        update(members, manifest, png, rewritten)

    variant('recompressed-png', pixels)
    variant('altered-low-bits', lambda m, j: pixels(m, j, True), 'Photo delivery pixels or metadata differ')
    variant('altered-color-metadata', lambda m, j: update(m, j, png,
            png_bytes([png_chunks(m[png])[0], (b'gAMA', struct.pack('>I', 100000)), *png_chunks(m[png])[1:]])),
            'Photo delivery pixels or metadata differ')
    variant('missing-photo-mapping', lambda m, j: native_json(m, j, 'native/objects.json', lambda x: x['photos'].clear()),
            'invalid editable photo mapping')
    variant('incorrect-dependencies', lambda m, j: update(m, j, 'native/dependencies.json', b'{}\n'),
            'photo originals differ from their recorded content')
    variant('unreconciled-journal', lambda m, j: update(m, j, 'native/library/catalog.log', b'pending\n'),
            'unreconciled journal')
    variant('extra-native', lambda m, j: add_member(m, j, 'native/extra.json', 'native', b'{}\n'),
            'unsupported file')
    variant('unreferenced-original', lambda m, j: add_member(m, j, 'assets/unused.png', 'asset',
            next(m[f['path']] for f in j['files'] if f['role'] == 'asset')), 'unreferenced sources or sidecars')
    variant('extra-preview', lambda m, j: add_member(m, j, 'exports/extra.png', 'preview', m[png]),
            'Photo source/delivery inventory differs')
    variant('external-source', lambda m, j: native_json(m, j, model_path,
            lambda x: next(iter(x['catalog']['photos'].values()))['source'].update(path='/tmp/external.png')),
            'native photo mapping, media type or catalog record differs')
    variant('unsupported-retained-history', lambda m, j: native_json(m, j, model_path,
            lambda x: next(iter(x['catalog']['photos'].values()))['history'][0]['settings'].update(external_profile='/tmp/profile')),
            'native photo has unqualified profiles')

    # Real production checks exercise the modified transport and metadata
    # comparisons. Revisions preserve originals and all earlier history.
    work = output/'production'; work.mkdir(); (work/'assets').mkdir()
    asset = 'a'*32; source_path = next(f['path'] for f in json.loads(original['project.json'])['files'] if f['role'] == 'asset')
    (work/'assets'/(asset+'.png')).write_bytes(original[source_path])
    params = {'bit_depth': 16, 'photos': [{'name': 'photo', 'asset': asset, 'format': 'png'}]}
    photo.validate('photo.create', params, None)
    created = photo.execute(work, 'photo.create', params, executable=binding['executable'])
    before, mapping, dependencies = photo.native(work); image = photo.png_info(work/'exports/photo.png')
    change = {'photos': [{'name': 'photo', 'adjustments': {'light.exposure': 0.5}}]}
    photo.validate('photo.edit', change, 'prior')
    revised = photo.execute(work, 'photo.edit', change, executable=binding['executable'])
    changed, _, changed_dependencies = photo.native(work)
    photo.verify_edit(before, changed, change['photos'], mapping)
    assert changed_dependencies == dependencies and photo.png_info(work/'exports/photo.png') != image
    restore = {'photos': [{'name': 'photo', 'adjustments': {'light.exposure': 0}}]}
    restored = photo.execute(work, 'photo.edit', restore, executable=binding['executable'])
    final, _, final_dependencies = photo.native(work); photo.verify_edit(changed, final, restore['photos'], mapping)
    assert final_dependencies == dependencies and photo.png_info(work/'exports/photo.png') == image
    report['productionOperations'] = [created, revised, restored]
    for info in inputs.values():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    assert media_binding.resolve_photo() == binding
    report.update(passed=True, completed=time.time(), nativeCases=len(report['cases']), refusalCases=len(report['refusals']),
                  productionCases=3, originalInputsUnchanged=True)
    save(); print('PASS eight Photo replays, seventeen refusals and three native production operations'); print(output/'evidence.json')


if __name__ == '__main__':
    main()
