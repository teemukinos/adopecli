"""Full decoded media comparison for explicitly selected native replay profiles.

The supporting decoder is an exact pinned local binary, separate from the native
renderer. Every H.264 frame, presentation timestamp and audio PCM byte is checked.
Historical render elapsed time and machine paths are preserved as unauthenticated
provenance; they are never followed or used as commands.
"""
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time

from . import media_decoders, photo, video, motion, media_binding


def output(command, maximum, *, keep=True, timeout=600):
    """Consume bounded output without buffering a whole decoded film in memory."""
    count = 0; digest = hashlib.sha256(); chunks = []
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([str(x) for x in command], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=errors)
        selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic()+timeout
        try:
            while True:
                if time.monotonic() >= deadline or errors.tell() > 1 << 20:
                    raise ValueError('media decoder exceeded time or diagnostic bounds')
                if not selector.select(min(1, max(0, deadline-time.monotonic()))):
                    continue
                data = os.read(process.stdout.fileno(), 1 << 16)
                if not data:
                    break
                count += len(data)
                if count > maximum:
                    raise ValueError('media decoder exceeded output bounds')
                digest.update(data)
                if keep:
                    chunks.append(data)
            if process.wait(timeout=max(.1, deadline-time.monotonic())) != 0:
                errors.seek(0)
                raise ValueError('media decoder failed: '+errors.read(1000).decode(errors='replace'))
        finally:
            selector.close(); process.stdout.close()
            if process.poll() is None:
                process.kill(); process.wait()
    return b''.join(chunks) if keep else {'bytes': count, 'sha256': digest.hexdigest()}


def decoded(path, settings, frames, binaries):
    fields = ('index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,'
              'sample_aspect_ratio,color_range,color_space,color_transfer,color_primaries,'
              'sample_rate,channels,channel_layout,start_time,duration')
    info = json.loads(output([binaries['ffprobe'], '-v', 'error', '-show_entries', 'stream='+fields,
                              '-of', 'json', '-f', 'mov', '-enable_drefs', '0', '-protocol_whitelist', 'file,pipe', path], 1 << 20))
    streams = info.get('streams')
    if not isinstance(streams, list) or len(streams) not in (1, 2):
        raise ValueError('replayed movie requires one picture and at most one audio stream')
    picture = [v for v in streams if v.get('codec_type') == 'video']
    audio = [v for v in streams if v.get('codec_type') == 'audio']
    if len(picture) != 1 or len(audio)+1 != len(streams):
        raise ValueError('replayed movie has unsupported streams')
    v = picture[0]; fps = settings['fps']; size = settings['width']*settings['height']*3//2
    if (v.get('codec_name') != 'h264' or v.get('pix_fmt') != 'yuv420p'
            or v.get('width') != settings['width'] or v.get('height') != settings['height']
            or Fraction(v.get('r_frame_rate', '0')) != fps or Fraction(v.get('avg_frame_rate', '0')) != fps
            or Fraction(v.get('start_time', '0')) != 0
            or abs(Fraction(v.get('duration', '0'))-Fraction(frames, fps)) > Fraction(1, 100000)):
        raise ValueError('decoded picture metadata differs from native timing or dimensions')
    if audio and (audio[0].get('codec_name') != 'aac' or audio[0].get('sample_rate') != '48000'
                  or audio[0].get('channels') != 2 or audio[0].get('channel_layout') != 'stereo'):
        raise ValueError('replayed movie audio must be stereo 48 kHz AAC')
    raw = output([binaries['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-copyts', '-f', 'mov', '-enable_drefs', '0', '-protocol_whitelist', 'file,pipe', '-i', path,
                  '-map', '0:v:0', '-an', '-fps_mode', 'passthrough', '-enc_time_base', 'demux',
                  '-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-hash', 'sha256', 'pipe:1'], 16 << 20)
    rows = []; base = None
    for line in raw.decode('ascii').splitlines():
        if line.startswith('#tb 0: '):
            base = Fraction(line[7:])
        elif line and not line.startswith('#'):
            fields = [s.strip() for s in line.split(',')]
            if len(fields) != 6 or base is None:
                raise ValueError('invalid decoded frame receipt')
            stream, dts, pts, duration, length = map(int, fields[:5]); digest = fields[5]
            if (stream != 0 or pts != dts or pts*base != Fraction(len(rows), fps)
                    or duration*base != Fraction(1, fps) or length != size
                    or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
                raise ValueError('decoded frame timing or pixel count differs from native timeline')
            rows.append(digest)
    if len(rows) != frames:
        raise ValueError('decoded movie has missing or extra frames')
    pcm = None
    if audio:
        expected = frames*48000//fps
        pcm = output([binaries['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-f', 'mov', '-enable_drefs', '0', '-protocol_whitelist', 'file,pipe', '-i', path,
                      '-map', '0:a:0', '-vn', '-f', 'f32le', '-c:a', 'pcm_f32le', 'pipe:1'],
                     (expected+4096)*8, keep=False)
        if pcm['bytes'] % 8 or abs(pcm['bytes']//8-expected) > 2048:
            raise ValueError('decoded PCM duration differs from native timeline')
    return {'streams': streams, 'frame_sha256': rows, 'pcm': pcm}


def render_receipt(path, composition):
    value = json.loads(path.read_text())
    if type(value) is not dict or set(value) != {'rendered'} or not isinstance(value['rendered'], list) or len(value['rendered']) != 1:
        raise ValueError('invalid retained Motion render receipt')
    row = value['rendered'][0]
    if (type(row) is not dict or set(row) != {'comp', 'output', 'seconds'} or row['comp'] != composition
            or type(row['output']) is not str or not Path(row['output']).is_absolute()
            or Path(row['output']).parts[-2:] != ('exports', 'document.mp4')
            or type(row['seconds']) not in (int, float) or not math.isfinite(row['seconds'])
            or not 0 <= row['seconds'] <= 600):
        raise ValueError('invalid retained Motion render receipt')


def deliveries(root, replay_root, declared, result, family):
    expected = {entry['path']: entry['role'] for entry in result['artifacts']
                if entry['role'] in ('asset', 'export', 'preview')}
    actual = {path: entry['role'] for path, entry in declared.items() if entry['role'] in ('asset', 'export', 'preview')}
    if actual != expected:
        raise ValueError('movie source/delivery inventory differs from native replay')
    if family == 'video':
        sequence = json.loads((replay_root/'native/sequence.json').read_text())
        settings = {k: sequence['settings'][k] for k in ('width', 'height')}
        settings['fps'] = sequence['settings']['frame_rate']['num']
        # Bind the retained probe to the retained movie, including original
        # compression size/bitrate. Do not replace them with rerender statistics.
        probe = video.run(root, ['probe', str(root/'exports/document.mp4')],
                          executable=media_binding.resolve_video()['executable'])
    else:
        comp = motion.read_native(replay_root)[1]
        settings = {k: comp['kind'][k] for k in ('width', 'height')}
        settings['fps'] = comp['kind']['frame_rate']['num']
        probe = motion.inspect_movie(root/'exports/document.mp4')
        render_receipt(root/'exports/render.json', comp['name'])
        render_receipt(replay_root/'exports/render.json', comp['name'])
    if json.loads((root/'exports/probe.json').read_text()) != probe:
        raise ValueError('retained movie probe differs from the delivered movie')
    for path, role in expected.items():
        original, replayed = root/path, replay_root/path
        if role == 'asset' and video.digest(original) != video.digest(replayed):
            raise ValueError('movie source bytes differ from native replay')
        if path.endswith('.png') and role != 'asset':
            if photo.pixel_hash(original) != photo.pixel_hash(replayed):
                raise ValueError('movie frame preview differs from native replay')
    binaries = media_decoders.resolve()
    frames = result['validation']['frames']
    original = decoded(root/'exports/document.mp4', settings, frames, binaries)
    replayed = decoded(replay_root/'exports/document.mp4', settings, frames, binaries)
    if original != replayed:
        raise ValueError('full decoded movie pixels, timing, color or PCM differ from native replay')
    return {'all_movie_frames_replayed': True, 'decoded_frame_count': frames,
            'full_audio_pcm_replayed': original['pcm'] is not None,
            'decoded_audio_sample_frames': original['pcm']['bytes']//8 if original['pcm'] else 0,
            'historical_render_execution_authenticated': False,
            'render_receipt_scope': 'structure and composition; original elapsed time/path preserved without authentication'}
