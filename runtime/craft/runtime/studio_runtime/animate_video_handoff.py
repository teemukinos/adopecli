"""Private, owned Animate frames/audio handoff to the maintained Video engine.

This is not a public export format. Container inspection and complete native
decoding run here; durable export integration must precede worker publication.
Caller commands, project paths, stored scripts and external encoders are absent.
"""
import io
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace

from . import animate_exports as exports, animate_format as format
from . import animate_project as project, animate_audio_export as audio_export
from . import animate_video_container as video_container
from . import animate_video_decode as video_decode
from .animate_diagnostics import integer
from .animate_process import run

TICKS = 254016000000
RATE = 48000


def inputs(raster, audio, matte):
    """Preflight only the fields this private handoff consumes."""
    if not isinstance(matte, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', matte) is None:
        raise ValueError('Animate video matte must be #rrggbb')
    count = integer(raster.get('frames'), 1, 600, 'video frame count')
    width = integer(raster.get('width'), 1, 32768, 'video width')
    height = integer(raster.get('height'), 1, 32768, 'video height')
    size = [max(2, (side+1)//2*2) for side in (width, height)]
    if size[0]*size[1] > exports.MAX_PIXELS or size[0]*size[1]*count > exports.MAX_SEQUENCE_PIXELS:
        raise ValueError('Animate padded video exceeds its pixel budget')
    fps = raster.get('fps')
    if not format.number(fps, 1, 240):
        raise ValueError('Animate video requires an admitted native frame rate')
    num, den = float(fps).as_integer_ratio()
    if num > 2147483647 or den > 4294967295:
        raise ValueError('Animate video frame rate exceeds the native container timebase')
    request = raster.get('request', {})
    first = integer(request.get('from'), 0, 999999, 'video first frame')
    if (request.get('format') != 'png_sequence' or request.get('to') != first+count-1
            or raster.get('cold_export_equal') is not True or raster.get('native_state_equal') is not True):
        raise ValueError('Animate video requires qualified native PNG frames')
    names = ['frame_'+str(i+1).zfill(5)+'.png' for i in range(first, first+count)]
    records = raster.get('artifacts', [])
    if not isinstance(records, list) or [r.get('file') for r in records] != names:
        raise ValueError('Animate video frame manifest is incomplete')
    duration = (count*TICKS*den+num-1)//num
    result = {'frames': count, 'source_size': [width, height], 'encoded_size': size,
              'padding_right_bottom': [size[0]-width, size[1]-height], 'matte': matte.lower(),
              'frame_rate': {'num': num, 'den': den}, 'duration_ticks': duration,
              'source_sha256': raster.get('source_sha256'), 'audio_samples': None}
    if audio is not None:
        sound = audio.get('request', {})
        if (sound.get('format') != 'wav' or sound.get('rate') != RATE or sound.get('bits') not in (16, 24, 32)
                or any(sound.get(key) != request[key] for key in ('from', 'to'))
                or audio.get('cold_export_equal') is not True or audio.get('native_state_equal') is not True
                or audio.get('source_sha256') != result['source_sha256'] or audio.get('fps') != fps):
            raise ValueError('Animate video requires a matching qualified native soundtrack')
        samples = integer(audio.get('sample_frames'), 1, 33554432, 'video audio samples')
        if abs(samples-duration*RATE//TICKS) > 1:
            raise ValueError('Animate video audio endpoint differs by more than one sample')
        if len(audio.get('artifacts', [])) != 1 or audio['artifacts'][0].get('file') != 'soundtrack.wav':
            raise ValueError('Animate video soundtrack manifest is incomplete')
        result['audio_samples'] = samples
    return result


def encode(root, raster_directory, raster, executable, *, audio_directory=None, audio=None,
           matte='#000000', deadline, cancelled=lambda: False):
    """Encode owned inputs. The returned file is unqualified for publication."""
    from PIL import Image
    planned = inputs(raster, audio, matte)
    if (audio is None) != (audio_directory is None):
        raise ValueError('Animate video soundtrack and directory must be supplied together')
    root = Path(root).absolute(); root.mkdir()
    raster_directory = Path(raster_directory).absolute()
    if raster_directory.is_symlink() or audio_directory is not None and Path(audio_directory).is_symlink():
        raise ValueError('Animate video input directories must not be symbolic links')

    def check():
        if cancelled() or time.monotonic() >= deadline:
            raise ValueError('Animate video handoff cancelled or timed out')

    def native(args, limit=1<<20):
        check()
        return run([str(executable), '--data-dir', str(root/'settings'), '--compact', *args], root,
                   deadline=deadline, cancelled=cancelled, stdout_limit=limit, file_limit=exports.MAX_BYTES)

    def batch(name, commands, source=None):
        script = root/(name+'.jsonl')
        script.write_text(''.join(json.dumps(command)+'\n' for command in commands))
        raw = native((['--project', str(source)] if source else [])+['run', str(script)])
        replies = [format.strict_json(line, max_items=4096) for line in raw.splitlines()]
        if (len(replies) != len(commands) or any(not isinstance(row, dict) or not isinstance(row.get('result'), dict)
                or row.get('ok') is not True or row.get('id') != command['id']
                or row.get('line') != i+1 for i, (row, command) in enumerate(zip(replies, commands)))):
            raise ValueError('Animate video returned an incomplete command report')
        return [row['result'] for row in replies]

    if native(['--version']).strip() != b'dobe-video 0.20.1':
        raise ValueError('Animate video requires the maintained Video engine')
    records = raster['artifacts']
    if {path.name for path in raster_directory.iterdir()} != {row['file'] for row in records}:
        raise ValueError('Animate video input contains missing or unexpected frames')
    frames = root/'frames'; frames.mkdir(); preserved = []; converted = []; total = 0
    rgb = tuple(int(matte[i:i+2], 16) for i in (1, 3, 5))
    for index, record in enumerate(records):
        check()
        path = project.owned_path(raster_directory, raster_directory/record['file'])
        data = exports.read_output(path)
        if (len(data) != record['bytes'] or project.digest(data) != record['sha256']
                or exports.png(data, *planned['source_size']) != record['rgba_sha256']):
            raise ValueError('Animate video source frame no longer matches its qualification')
        preserved.append((path, record['sha256']))
        # Composite alpha over the declared matte in encoded sRGB. Opaque pixels
        # remain byte-exact. Only right/bottom padding is added; no resize occurs.
        with Image.open(io.BytesIO(data)) as image, image.convert('RGBA') as rgba:
            with Image.new('RGBA', planned['encoded_size'], (*rgb, 255)) as canvas:
                canvas.alpha_composite(rgba, (0, 0))
                with canvas.convert('RGB') as opaque:
                    destination = frames/('frame_'+str(index+1).zfill(5)+'.png')
                    opaque.save(destination, format='PNG')
                    expected = project.digest(opaque.tobytes())
        encoded = exports.read_output(destination); total += len(encoded)
        if total > exports.MAX_BYTES:
            raise ValueError('Animate video input frames exceed the encoded byte budget')
        with Image.open(io.BytesIO(encoded)) as image:
            if image.mode != 'RGB' or list(image.size) != planned['encoded_size'] or project.digest(image.tobytes()) != expected:
                raise ValueError('Animate video padding changed the composed frame')
        converted.append({'file': destination.name, 'sha256': project.digest(encoded), 'rgb_sha256': expected})
    sound_path = None
    if audio is not None:
        directory = Path(audio_directory).absolute()
        if {path.name for path in directory.iterdir()} != {'soundtrack.wav'}:
            raise ValueError('Animate video input contains unexpected audio artifacts')
        path = project.owned_path(directory, directory/'soundtrack.wav')
        data = exports.read_output(path, audio['bytes']); record = audio['artifacts'][0]
        if len(data) != record['bytes'] or project.digest(data) != record['sha256']:
            raise ValueError('Animate video soundtrack no longer matches its qualification')
        # Recheck all PCM fields and samples through the existing WAV validator.
        reply = {'written': str(path), 'bytes': len(data), 'rate': RATE,
                 'seconds': planned['audio_samples']/RATE, 'frames': planned['frames'], 'sounds': audio['soundtrack']['voices']}
        inspector = SimpleNamespace(deadline=deadline, cancelled=cancelled)
        if audio_export.inspect(path, reply, audio['soundtrack'], audio, inspector) != record:
            raise ValueError('Animate video soundtrack metadata changed')
        sound_path = root/'soundtrack.wav'; sound_path.write_bytes(data)
        preserved.append((path, record['sha256']))
    seed = root/'seed.fcproj'
    commands = [
        {'id': 'file.newSequence', 'params': {'name': 'Dobe Animate encode', 'width': planned['encoded_size'][0],
            'height': planned['encoded_size'][1], 'fps': raster['fps'], 'sampleRate': RATE, 'video': 1, 'audio': 1}},
        {'id': 'file.importImageSequence', 'params': {'path': str(frames/'frame_00001.png')}}]
    if sound_path is not None:
        commands.append({'id': 'file.import', 'params': {'paths': [str(sound_path)]}})
    commands.append({'id': 'file.saveAs', 'params': {'path': str(seed)}})
    replies = batch('seed', commands)
    sequence_id = integer(replies[0].get('sequence'), 1, (1<<53)-1, 'video sequence identity')
    imported = replies[1]
    if (imported.get('errors') != [] or len(imported.get('items', [])) != 1 or len(imported.get('imageSequences', [])) != 1
            or imported['imageSequences'][0] != {'item': imported['items'][0], 'frames': planned['frames'], 'missing': []}):
        raise ValueError('Animate video did not import the complete image sequence')
    video_id = integer(imported['items'][0], 1, (1<<53)-1, 'video media identity')
    data = format.strict_json(exports.read_output(seed, 1<<20), max_items=10000)
    items = data['project']['items']; sequence = items[str(sequence_id)]['kind']['Sequence']
    media = items[str(video_id)]['kind']['Media']
    # CLI's floating fps and default image-sequence rate normalize to standard
    # rates. Set exact rationals only in this fresh, generated intermediate.
    sequence['settings']['frame_rate'] = planned['frame_rate']
    media['info']['video']['frame_rate'] = planned['frame_rate']; media['info']['duration'] = planned['duration_ticks']
    seed.write_text(json.dumps(data))
    placements = [(video_id, 'V1', planned['duration_ticks'], True)]
    if audio is not None:
        if replies[2].get('errors') != [] or len(replies[2].get('items', [])) != 1:
            raise ValueError('Animate video did not import its soundtrack')
        audio_id = integer(replies[2]['items'][0], 1, (1<<53)-1, 'video audio identity')
        placements.append((audio_id, 'A1', (planned['audio_samples']*TICKS+RATE-1)//RATE, False))
    native_project = root/'encode.fcproj'
    commands = [{'id': 'timeline.place', 'params': {'item': identity, 'track': track, 'time': 0,
        'duration': duration, 'sourceIn': 0, 'insert': False, 'video': picture, 'audio': not picture}}
        for identity, track, duration, picture in placements]
    commands.append({'id': 'file.saveAs', 'params': {'path': str(native_project)}})
    replies = batch('place', commands, seed)
    saved_bytes = exports.read_output(native_project, 1<<20)
    saved = format.strict_json(saved_bytes, max_items=10000)
    stored = saved['project']['items']; sequence = stored[str(sequence_id)]['kind']['Sequence']
    if (sequence['settings']['frame_rate'] != planned['frame_rate'] or
            [sequence['settings'][key] for key in ('width', 'height')] != planned['encoded_size'] or
            stored[str(video_id)]['kind']['Media']['info']['video']['frame_rate'] != planned['frame_rate']):
        raise ValueError('Animate video native handoff changed dimensions or rate')
    for index, (identity, track, duration, picture) in enumerate(placements):
        tracks = sequence['video_tracks' if picture else 'audio_tracks']
        if len(tracks) != 1 or len(tracks[0]['items']) != 1:
            raise ValueError('Animate video native placement changed track contents')
        clip = tracks[0]['items'][0]
        if (replies[index].get('clips') != [clip['id']] or
                any(clip.get(k) != v for k, v in {'item': identity, 'start': 0, 'duration': planned['duration_ticks'],
                    'source_in': 0, 'speed': 1.0, 'enabled': True}.items())):
            raise ValueError('Animate video native placement changed clip timing')
        if not picture:
            # timeline.place snaps all clips to the picture grid. This owned
            # intermediate must retain the WAV's final sample even when its
            # endpoint is just beyond that grid. A cold native save below proves
            # that the engine preserves this explicit audio-only duration.
            clip['duration'] = duration
    native_project.write_text(json.dumps(saved))
    saved_bytes = exports.read_output(native_project, 1<<20)
    movie = root/'movie.mp4'
    settings = {'maxThreads': 2}
    if audio is not None:
        settings['audioSampleFrames'] = planned['audio_samples']
    # Save As derives the project/bin name from the basename. Keep that basename
    # stable so the complete generated native state can be compared unchanged.
    (root/'reopen').mkdir()
    cold_project = root/'reopen/encode.fcproj'
    replies = batch('export', [{'id': 'file.exportMedia', 'params': {'path': str(movie), 'format': 'h264',
        'wait': True, 'gpuRendering': 'off', 'audio': audio is not None, 'settings': settings,
        'range': 'custom', 'startTime': 0, 'endTime': planned['duration_ticks']}},
        {'id': 'file.saveAs', 'params': {'path': str(cold_project)}}], native_project)
    reply = replies[0]
    container = video_container.inspect(movie, planned, deadline=deadline, cancelled=cancelled, decode_manifest=True)
    if (reply.get('offlineMedia') != [] or reply.get('warnings') != [] or reply.get('path') != str(movie)
            or reply.get('result', {}).get('frames') != planned['frames']
            or reply['result'].get('bytes') != container['bytes'] or reply['result'].get('path') != str(movie)):
        raise ValueError('Animate video encoding report disagrees with its inputs')
    if exports.read_output(native_project, 1<<20) != saved_bytes:
        raise ValueError('Animate video encoding changed its native intermediate')
    if (replies[1].get('path') != str(cold_project) or
            format.strict_json(exports.read_output(cold_project, 1<<20), max_items=10000) != saved):
        raise ValueError('Animate video cold save changed its exact native handoff')
    for path, expected in preserved:
        check()
        if project.digest(exports.read_output(path)) != expected:
            raise ValueError('Animate video encoding changed a qualified source artifact')
    decoded = video_decode.inspect(root, movie, planned, container, native, deadline=deadline, cancelled=cancelled)
    return movie, {**planned, 'input_frames': converted, 'input_encoded_bytes': total,
                   'artifact': {'file': movie.name, 'bytes': container['bytes'], 'sha256': container['sha256']},
                   'container': container, 'decode': decoded,
                   'source_artifacts_unchanged': True, 'native_intermediate_unchanged': True,
                   'complete_decode_verified': True, 'container_timing_verified': True,
                   'publication_authorized': False}
