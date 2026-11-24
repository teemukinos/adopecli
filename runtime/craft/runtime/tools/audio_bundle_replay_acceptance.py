#!/usr/bin/env python3
"""Qualify complete Audio replay using fixed packaged engines and explicit source.

Run with the package Python under an OS network-deny policy. Inputs contain
original, revised and restored checksum-bound ZIPs; output must be new. This
qualifies a source overlay, not a sealed package or Linux/hosted deployment.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
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
    if type(inputs) is not dict or set(inputs) != {'original', 'revised', 'restored'}:
        raise ValueError('three checksum-bound Audio fixtures required')
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
    modules = ('audio', 'media_binding', 'bundle_replay', 'bundle')
    for name in modules:
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, source/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        setattr(studio_runtime, name, module)
    from studio_runtime import audio, bundle, media_binding
    binding = media_binding.resolve_audio()
    empty = output/'empty-path'; empty.mkdir()
    os.environ['PATH'] = str(empty)
    report = {'started': time.time(), 'inputs': inputs, 'cases': [], 'refusals': [],
              'sourceModules': {name: sha((source/(name+'.py')).read_bytes()) for name in modules},
              'nativeExecutable': str(binding['executable']),
              'nativeExecutableSha256': binding['expected_binary_sha256'],
              'sealedSourceQualified': False, 'linuxQualified': False, 'hostedAdmissionChanged': False,
              'enginePathEmpty': True}

    def save():
        (output/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')

    def refused(label, path, expected, profile=('audio',)):
        try:
            bundle.execute(path, output/('denied-'+str(len(report['refusals']))), 64 << 20,
                           replay_families=profile)
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError('wrong refusal for '+label+': '+str(error)) from error
            report['refusals'].append({'label': label, 'message': str(error)[:400]}); save()
        else:
            raise AssertionError(label+' unexpectedly succeeded')

    for label, info in inputs.items():
        started = time.monotonic()
        result = bundle.execute(info['path'], output/label, 64 << 20, replay_families=('audio',))
        validation = result['validation']
        for key in ('passed', 'native_cold_reopen', 'native_model_equal', 'native_inventory_equal',
                    'imported_native_bytes_preserved', 'original_files_unchanged', 'export_semantics_replayed'):
            assert validation[key] is True, key
        assert not validation['native_history_replayed'] and not validation['initial_source_preserved']
        assert not validation['visual_approval']
        with zipfile.ZipFile(info['path']) as archive:
            retained = {path for path in archive.namelist() if path.startswith('native/Backups/')}
        observations = validation['native_replay_validation']['backup_observations']
        assert {entry['path'] for entry in observations} == retained
        assert all(entry['native_state_equal'] for entry in observations)
        report['cases'].append({'label': label, 'wallSeconds': time.monotonic()-started, 'result': result}); save()
        refused(label+' default hosted boundary', info['path'], 'bundle engine is not qualified', ())

    with zipfile.ZipFile(inputs['revised']['path']) as archive:
        original = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}

    def update(members, manifest, path, data):
        members[path] = data
        next(f for f in manifest['files'] if f['path'] == path).update(bytes=len(data), sha256=sha(data))

    def native_json(members, manifest, path, edit):
        value = json.loads(members[path]); edit(value)
        update(members, manifest, path, (json.dumps(value)+'\n').encode())

    def mutated(label, change, expected):
        members = dict(original); manifest = json.loads(members['project.json'])
        change(members, manifest)
        members['project.json'] = (json.dumps(manifest, sort_keys=True)+'\n').encode()
        destination = output/(label+'.zip')
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in members.items():
                archive.writestr(path, data)
        refused(label, destination, expected)

    def add_member(members, manifest, path, role, data):
        members[path] = data
        manifest['files'].append({'path': path, 'role': role, 'bytes': len(data), 'sha256': sha(data)})

    def remove_export(members, manifest):
        path = 'exports/document.wav'; del members[path]
        manifest['files'] = [f for f in manifest['files'] if f['path'] != path]

    def sample_change(members, manifest, value):
        path = 'exports/document.wav'; raw = bytearray(members[path]); at = 12
        while raw[at:at+4] != b'data':
            length = struct.unpack_from('<I', raw, at+4)[0]; at += 8+length+(length & 1)
        struct.pack_into('<f', raw, at+8+800, value)
        update(members, manifest, path, bytes(raw))

    mutated('missing-clip-mapping', lambda m, j: native_json(m, j, 'native/objects.json',
            lambda x: x['clips'].pop(next(iter(x['clips'])))), 'audio mapping does not match')
    mutated('discarded-native-field', lambda m, j: native_json(m, j, 'native/document.scraft',
            lambda x: x.update(future_owner_annotation='Retain this complete editable field.')),
            'native audio reopen/save changed editable content')
    mutated('unexpected-native', lambda m, j: add_member(m, j, 'native/extra.json', 'native', b'{}\n'),
            'Audio native inventory contains unqualified files')
    mutated('incorrect-dependencies', lambda m, j: update(m, j, 'native/dependencies.json', b'{}\n'),
            'native replay changed the imported editable state')
    mutated('missing-export', remove_export, 'native source and export required')
    mutated('altered-pcm', lambda m, j: sample_change(m, j, 0.125), 'Audio delivery PCM differs')
    mutated('nonfinite-pcm', lambda m, j: sample_change(m, j, float('nan')), 'WAV contains nonfinite samples')
    mutated('extra-preview', lambda m, j: add_member(m, j, 'exports/unused.txt', 'preview', b'preview'),
            'Audio delivery inventory differs')
    mutated('unreferenced-native-source', lambda m, j: add_member(m, j, 'native/Audio Files/unused.wav',
            'asset', next(m[f['path']] for f in j['files'] if f['path'].startswith('native/Audio Files/'))),
            'Audio native inventory contains unqualified files')
    backup = next(path for path in original if path.startswith('native/Backups/'))
    mutated('discarded-backup-field', lambda m, j: native_json(m, j, backup,
            lambda x: x.update(future_owner_annotation='Retain this backup field.')),
            'native audio reopen/save changed editable content')
    mutated('external-native-source', lambda m, j: native_json(m, j, 'native/document.scraft',
            lambda x: x['sources'][0].update(path='/tmp/external.wav')), 'relative packaged WAV')

    # Exercise the refactored production entry points using real create/edit
    # operations. Only the named clip gain changes, then complete PCM is restored.
    work = output/'production'; work.mkdir(); (work/'assets').mkdir()
    source_path = next(f['path'] for f in json.loads(original['project.json'])['files']
                       if f['path'].startswith('assets/') and f['path'].endswith('.wav'))
    asset = 'a'*32
    (work/'assets'/(asset+'.wav')).write_bytes(original[source_path])
    info = audio.wav_info(work/'assets'/(asset+'.wav'))
    frames = min(info['frames'], info['sample_rate'])
    params = {'sample_rate': info['sample_rate'], 'frames': frames,
              'tracks': [{'name': 'track', 'clips': [{'name': 'clip', 'asset': asset, 'start': 0, 'frames': frames}]}]}
    audio.validate('audio.create', params, None)
    created = audio.execute(work, 'audio.create', params, executable=binding['executable'])
    before = (work/'native/document.scraft').read_bytes(); pcm = audio.wav_info(work/'exports/document.wav')
    edits = {'edits': [{'type': 'clip', 'name': 'clip', 'gain_db': -3}]}
    audio.validate('audio.edit', edits, 'prior')
    revised = audio.execute(work, 'audio.edit', edits, executable=binding['executable'])
    after = audio.native(work)[0]; expected = json.loads(before)
    expected['tracks'][0]['playlists'][0]['clips'][0]['gain_db'] = -3
    assert after == expected and audio.wav_info(work/'exports/document.wav')['pcm_sha256'] != pcm['pcm_sha256']
    restored = audio.execute(work, 'audio.edit', {'edits': [{'type': 'clip', 'name': 'clip', 'gain_db': 0}]},
                             executable=binding['executable'])
    assert (work/'native/document.scraft').read_bytes() == before and audio.wav_info(work/'exports/document.wav') == pcm
    report['productionOperations'] = [created, revised, restored]
    for info in inputs.values():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    assert media_binding.resolve_audio() == binding
    report.update(passed=True, completed=time.time(), nativeCases=len(report['cases']),
                  refusalCases=len(report['refusals']), productionCases=3, originalInputsUnchanged=True)
    save()
    print('PASS three Audio replays, fourteen refusals and three native production operations')
    print(output/'evidence.json')


if __name__ == '__main__':
    main()
