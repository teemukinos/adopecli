#!/usr/bin/env python3
"""Qualify full Video/Motion native replay using retained checksum-bound bundles.

Run with the read-only package Python under OS network denial. Six source ZIPs
contain original/revised branded films and four editable Motion compositions.
Source overlays are explicit; this is not sealed-package or Linux qualification.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('package', 'inputs', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(); package = args.package.resolve(strict=True)
    inputs = json.loads(args.inputs.read_text())
    if set(inputs) != {'ending-revised', 'orbit', 'original-film', 'portal', 'revised-film', 'staircase'}:
        raise ValueError('six retained native movie fixtures required')
    for value in inputs.values():
        path = Path(value['path']); raw = path.read_bytes()
        if (not path.is_absolute() or path.is_symlink() or not 0 < len(raw) <= 64 << 20
                or len(raw) != value['bytes'] or sha(raw) != value['sha256']):
            raise ValueError('movie fixture differs from retained evidence')
    args.output.mkdir(mode=0o700, exist_ok=args.resume); out = args.output.resolve(); source = Path(__file__).resolve().parents[1]/'studio_runtime'
    sys.path.insert(0, str(package/'lib/dobe/runtime')); import studio_runtime
    modules = ('video', 'motion', 'media_binding', 'media_decoders', 'movie_replay', 'bundle_replay', 'bundle')
    for name in modules:
        spec = importlib.util.spec_from_file_location('studio_runtime.'+name, source/(name+'.py'))
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
        spec.loader.exec_module(module); setattr(studio_runtime, name, module)
    from studio_runtime import bundle, video, motion, media_binding, movie_replay, construction_support
    bindings = {name: getattr(media_binding, 'resolve_'+name)() for name in ('video', 'motion')}
    binaries = {name: construction_support.binary(name) for name in ('ffmpeg', 'ffprobe')}
    empty = out/'empty-path'; empty.mkdir(exist_ok=args.resume); os.environ['PATH'] = str(empty)
    report = {'started': time.time(), 'inputs': inputs, 'cases': [], 'refusals': [],
              'sourceModules': {name: sha((source/(name+'.py')).read_bytes()) for name in modules},
              'bindings': {n: {k: str(v) for k, v in b.items()} for n, b in bindings.items()},
              'supportingBinaryHashes': {n: sha(Path(p).read_bytes()) for n, p in binaries.items()},
              'sealedSourceQualified': False, 'linuxQualified': False, 'hostedAdmissionChanged': False,
              'enginePathEmpty': True}

    if args.resume:
        prior = json.loads((out/'evidence.json').read_text())
        for key in ('inputs', 'sourceModules', 'bindings', 'supportingBinaryHashes'):
            assert prior[key] == report[key], key
        report = prior

    def save():
        (out/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')

    def accepted(label, path):
        if any(row['label'] == label for row in report['cases']):
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read('project.json'))
            for entry in manifest['files']:
                assert sha((out/label/entry['path']).read_bytes()) == entry['sha256']
            return
        start = time.monotonic(); result = bundle.execute(path, out/label, 64 << 20, replay_families=('video', 'motion'))
        v = result['validation']
        for key in ('passed', 'native_cold_reopen', 'native_model_equal', 'native_inventory_equal',
                    'imported_native_bytes_preserved', 'original_files_unchanged', 'export_semantics_replayed',
                    'all_movie_frames_replayed'):
            assert v[key] is True, key
        assert not v['native_history_replayed'] and not v['initial_source_preserved'] and not v['visual_approval']
        assert not v['historical_render_execution_authenticated']
        report['cases'].append({'label': label, 'seconds': time.monotonic()-start, 'result': result}); save()

    def refused(label, path, expected, profile=('video', 'motion')):
        previous = [row for row in report['refusals'] if row['label'] == label]
        if previous:
            assert len(previous) == 1 and expected in previous[0]['message']
            return
        try:
            bundle.execute(path, out/('denied-'+str(len(report['refusals']))+'-'+str(time.time_ns())), 64 << 20, replay_families=profile)
        except ValueError as error:
            if expected not in str(error):
                raise AssertionError('wrong refusal for '+label+': '+str(error)) from error
            report['refusals'].append({'label': label, 'message': str(error)[:400]}); save()
        else:
            raise AssertionError(label+' unexpectedly succeeded')

    for label, value in inputs.items():
        accepted(label, value['path'])
        refused(label+' default profile', value['path'], 'bundle engine is not qualified', ())

    def update(members, manifest, path, data):
        members[path] = data
        next(f for f in manifest['files'] if f['path'] == path).update(bytes=len(data), sha256=sha(data))

    def native(members, manifest, path, change):
        value = json.loads(members[path]); change(value)
        update(members, manifest, path, (json.dumps(value, sort_keys=True)+'\n').encode())

    def add(members, manifest, path, role, data):
        members[path] = data; manifest['files'].append({'path': path, 'role': role, 'bytes': len(data), 'sha256': sha(data)})

    def variant(seed, label, change, expected):
        with zipfile.ZipFile(inputs[seed]['path']) as archive:
            members = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
        manifest = json.loads(members['project.json']); change(members, manifest)
        members['project.json'] = (json.dumps(manifest, sort_keys=True)+'\n').encode(); path = out/(label+'.zip')
        if path.exists():
            with zipfile.ZipFile(path) as archive:
                assert {n: archive.read(n) for n in archive.namelist()} == members
        else:
            with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in members.items():
                    archive.writestr(name, raw)
        if expected is None:
            accepted(label, path)
        else:
            refused(label, path, expected)

    for family, seed, doc in (('video', 'original-film', 'fcproj'), ('motion', 'orbit', 'ecproj')):
        variant(seed, family+' missing mapping', lambda m,j: native(m,j,'native/objects.json',lambda x:x.pop(next(iter(x)))),
                'names do not match native layers' if family == 'motion' else 'unmapped clips')
        variant(seed, family+' discarded field', lambda m,j: native(m,j,'native/document.'+doc,
                lambda x:x.update(future_owner_annotation='Preserve all editable state.')),
                'reopen/save changed editable content' if family == 'video' else 'repaired or changed on cold reopen')
        variant(seed, family+' extra native', lambda m,j: add(m,j,'native/extra.json','native',b'{}\n'),
                'unsupported native media inventory')
        asset = 'assets/'+'f'*32+('.png' if family == 'motion' else '')
        variant(seed, family+' extra asset', lambda m,j: add(m,j,asset,'asset',next(m[f['path']] for f in j['files'] if f['role']=='asset')),
                'unreferenced or missing assets')
        variant(seed, family+' stale native report', lambda m,j:update(m,j,'native/dependencies.json',b'{}\n'),
                'native replay changed the imported editable state')
        variant(seed, family+' extra export', lambda m,j:add(m,j,'exports/extra.txt','export',b'stale'),
                'movie source/delivery inventory differs')
        variant(seed, family+' stale movie probe', lambda m,j:update(m,j,'exports/probe.json',b'{}\n'),
                'retained movie probe differs')

    variant('orbit', 'motion forged render composition', lambda m,j:native(m,j,'exports/render.json',
            lambda x:x['rendered'][0].update(comp='Unrelated composition')), 'invalid retained Motion render receipt')

    # Encode an actual valid movie with one unsampled frame altered. The three
    # retained previews/native models remain exact; a sample-only check misses it.
    movies = out/'mutated-movies'; movies.mkdir(exist_ok=args.resume)
    source_movie = out/'orbit/exports/document.mp4'; modified = movies/'one-frame.mp4'
    movie_replay.output([binaries['ffmpeg'], '-nostdin', '-v', 'error', '-i', source_movie,
                         '-vf', "drawbox=x=0:y=0:w=32:h=32:color=red:t=fill:enable='eq(n,1)'",
                         '-c:v', 'libx264', '-qp', '0', '-pix_fmt', 'yuv420p', '-an', modified], 1 << 20)
    dimensions = {'width': 1080, 'height': 1920, 'fps': 24}
    before = movie_replay.decoded(source_movie, dimensions, 168, binaries)
    after = movie_replay.decoded(modified, dimensions, 168, binaries)
    differences = [n for n,(a,b) in enumerate(zip(before['frame_sha256'], after['frame_sha256'])) if a != b]
    assert differences == [1], differences
    report['alteredUnsampledFrames'] = differences; save()

    def movie(members, manifest, path, family):
        update(members, manifest, 'exports/document.mp4', path.read_bytes())
        if family == 'motion':
            probe = motion.inspect_movie(path)
        else:
            # Probe the actual conventional delivery name, as the native report includes it.
            named = movies/'document.mp4'; shutil.copyfile(path, named)
            probe = video.run(movies, ['probe', str(named)], executable=bindings['video']['executable'])
        update(members, manifest, 'exports/probe.json', (json.dumps(probe, sort_keys=True)+'\n').encode())

    variant('orbit', 'motion altered unsampled frame', lambda m,j:movie(m,j,modified,'motion'), 'full decoded movie')
    changed_audio = movies/'altered-audio.mp4'
    movie_replay.output([binaries['ffmpeg'], '-nostdin', '-v', 'error', '-i', out/'original-film/exports/document.mp4',
                         '-c:v', 'copy', '-af', 'volume=0.5', '-c:a', 'aac', changed_audio], 1 << 20)
    original_audio = movie_replay.decoded(out/'original-film/exports/document.mp4', dimensions, 360, binaries)
    altered_audio = movie_replay.decoded(changed_audio, dimensions, 360, binaries)
    assert original_audio['frame_sha256'] == altered_audio['frame_sha256'] and original_audio['pcm'] != altered_audio['pcm']
    report['alteredAudioKeepsEveryPictureFrame'] = True; save()
    variant('original-film', 'video altered PCM', lambda m,j:movie(m,j,changed_audio,'video'), 'full decoded movie')
    remuxed = movies/'remuxed.mp4'
    movie_replay.output([binaries['ffmpeg'], '-nostdin', '-v', 'error', '-i', source_movie,
                         '-c', 'copy', '-movflags', '+faststart', remuxed], 1 << 20)
    assert sha(remuxed.read_bytes()) != sha(source_movie.read_bytes())
    variant('orbit', 'equivalent remux', lambda m,j:movie(m,j,remuxed,'motion'), None)

    # Exercise unchanged public production entry points using the actual fixed
    # native binaries through a controlled PATH, not a substituted engine class.
    for family, b in bindings.items():
        (empty/('dobe-'+family)).symlink_to(b['executable'])
    report['productionOperations'] = []
    for family, module in (('video',video),('motion',motion)):
        root = out/('production-'+family); root.mkdir()
        if family == 'video':
            params = {'width': 128, 'height': 96, 'fps': 24,
                      'clips': [{'name': 'background', 'start': 0, 'frames': 24, 'color': '#242424'}],
                      'titles': [{'name': 'title', 'text': 'ONE', 'start': 0, 'frames': 24,
                                  'x': 24, 'y': 50, 'size': 12, 'color': '#FFFFFF'}]}
        else:
            params = {'width': 128, 'height': 96, 'fps': 24, 'frames': 24, 'background': '#242424',
                      'layers': [{'name': 'title', 'type': 'text', 'text': 'ONE', 'start': 0, 'frames': 24,
                                  'position': [24,50], 'size': 12, 'color': '#FFFFFF'}]}
        created = module.execute(root, family+'.create', params)
        before = movie_replay.decoded(root/'exports/document.mp4', {'width':128,'height':96,'fps':24},24,binaries)
        revised = module.execute(root, family+'.edit', {'edits':[{'type':'text','name':'title','text':'TWO'}]})
        after = movie_replay.decoded(root/'exports/document.mp4', {'width':128,'height':96,'fps':24},24,binaries)
        assert after['frame_sha256'] != before['frame_sha256']
        restored = module.execute(root, family+'.edit', {'edits':[{'type':'text','name':'title','text':'ONE'}]})
        assert movie_replay.decoded(root/'exports/document.mp4', {'width':128,'height':96,'fps':24},24,binaries) == before
        report['productionOperations'].append({'family':family,'created':created,'revised':revised,'restored':restored}); save()
    for value in inputs.values():
        assert sha(Path(value['path']).read_bytes()) == value['sha256']
    report.update(passed=True, completed=time.time(), nativeCases=len(report['cases']), refusalCases=len(report['refusals']),
                  productionCases=6, originalInputsUnchanged=True)
    save(); print('PASS',report['nativeCases'],'movie replay cases,',report['refusalCases'],'refusals, six native production operations')
    print(out/'evidence.json')


if __name__ == '__main__':
    main()
