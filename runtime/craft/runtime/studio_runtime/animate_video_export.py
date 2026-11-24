"""Typed MP4 delivery from qualified native frames and optional native audio."""
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time

from . import animate_audio_export as audio_export, animate_format as format, animate_graph as graph
from .animate_diagnostics import integer


def validate(value):
    graph.fields(value, ('format',), ('from', 'to', 'scale', 'audio', 'matte'), 'video export request')
    if value['format'] != 'mp4':
        raise ValueError('Animate video export format must be mp4')
    for key in ('from', 'to'):
        if key in value:
            integer(value[key], 0, 999999, 'video export '+key)
    if value.get('to', value.get('from', 0)) < value.get('from', 0):
        raise ValueError('Animate video export range is reversed')
    if not format.number(value.get('scale', 1), .001, 8):
        raise ValueError('Animate video export scale must be between 0.001 and 8')
    if type(value.get('audio', True)) is not bool:
        raise ValueError('Animate video audio option must be boolean')
    matte = value.get('matte', '#000000')
    if not isinstance(matte, str) or re.fullmatch('#[0-9a-fA-F]{6}', matte) is None:
        raise ValueError('Animate video matte must be #rrggbb')


def plan(profile, value):
    from . import animate_exports as exports
    validate(value)
    raster = exports.plan(profile, {'format': 'png_sequence', **{key: value[key] for key in ('from', 'to', 'scale') if key in value}})
    dimensions = [max(2, (raster[key]+1)//2*2) for key in ('width', 'height')]
    if (any(side > 32768 for side in dimensions) or math.prod(dimensions) > exports.MAX_PIXELS
            or math.prod(dimensions)*raster['frames'] > exports.MAX_SEQUENCE_PIXELS):
        raise ValueError('Animate padded video exceeds its pixel or dimension budget')
    num, den = float(raster['fps']).as_integer_ratio()
    if num > 2147483647 or den > 4294967295:
        raise ValueError('Animate video frame rate exceeds the native container timebase')
    request = {**raster['request'], 'format': 'mp4', 'audio': value.get('audio', True), 'matte': value.get('matte', '#000000').lower()}
    sound = audio_export.plan(profile, {'format': 'wav', 'from': request['from'], 'to': request['to'], 'rate': 48000, 'bits': 32}) if request['audio'] else None
    return {'request': request, 'frames': raster['frames'], 'width': dimensions[0], 'height': dimensions[1],
            'source_size': [raster['width'], raster['height']], 'fps': raster['fps'], 'frame_rate': {'num': num, 'den': den},
            'sample_frames': sound['sample_frames'] if sound else 0}


def prepare(root, source, value, executable, *, cancelled=lambda: False, seconds=120):
    from . import animate_exports as exports, animate_video_handoff as handoff, animate_video_container as container
    validate(value)
    if not format.number(seconds, 0, 120) or seconds <= 0:
        raise ValueError('Animate video export deadline must be within 120 seconds')
    deadline = time.monotonic()+seconds

    def remaining():
        left = deadline-time.monotonic()
        if cancelled() or left <= 0:
            raise ValueError('Animate video export cancelled or timed out')
        return left

    remaining()
    encoder = shutil.which('dobe-video')
    if encoder is None:
        raise ValueError('Animate MP4 export requires the maintained Dobe Video engine')
    original = format.read_bytes(source)
    envelope, paths = format.decode_envelope(original)
    # This is only cheap sizing/range preflight. Both actual producers perform
    # full media admission and native semantic reconciliation before rendering.
    planned = plan({'envelope': envelope, 'graph': graph.inspect_graph(envelope['document'], paths)}, value)
    root = Path(root).absolute(); root.mkdir()
    snapshot = root/'source.anicraft'; snapshot.write_bytes(original)
    request = planned['request']
    raster_dir, raster = exports.prepare(root/'raster', snapshot,
        {'format': 'png_sequence', **{key: request[key] for key in ('from', 'to', 'scale')}},
        executable, cancelled=cancelled, seconds=remaining())
    sound_dir = sound = None
    if request['audio']:
        sound_dir, sound = audio_export.prepare(root/'audio', snapshot,
            {'format': 'wav', 'from': request['from'], 'to': request['to'], 'rate': 48000, 'bits': 32},
            executable, cancelled=cancelled, seconds=remaining())
    options = {'audio_directory': sound_dir, 'audio': sound, 'matte': request['matte'], 'deadline': deadline, 'cancelled': cancelled}
    movie, warm = handoff.encode(root/'warm', raster_dir, raster, encoder, **options)
    _, cold = handoff.encode(root/'cold', raster_dir, raster, encoder, **options)
    if warm != cold:
        raise ValueError('Animate cold MP4 export changed encoded bytes, decoded samples or timing')
    if (warm['source_size'] != planned['source_size'] or warm['encoded_size'] != [planned['width'], planned['height']]
            or warm['frames'] != planned['frames'] or warm['frame_rate'] != planned['frame_rate']
            or (warm['audio_samples'] or 0) != planned['sample_frames']):
        raise ValueError('Animate MP4 handoff disagrees with the planned output')
    if format.read_bytes(source) != original or format.read_bytes(snapshot) != original:
        raise ValueError('Animate MP4 export changed its native source')
    remaining()
    output = root/'output'; output.mkdir()
    target = output/'movie.mp4'
    # Copy in bounded chunks under the same deadline. The complete destination
    # is reinspected and hashed before it can enter a durable revision.
    descriptor = os.open(movie, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as src, target.open('xb') as dst:
        info = os.fstat(src.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != warm['artifact']['bytes']:
            raise ValueError('Animate MP4 delivery requires its qualified regular file')
        copied = 0
        while copied < warm['artifact']['bytes']:
            remaining()
            block = src.read(min(1 << 20, warm['artifact']['bytes']-copied))
            if not block:
                raise ValueError('Animate MP4 output was truncated before delivery')
            dst.write(block); copied += len(block)
        if src.read(1):
            raise ValueError('Animate MP4 output grew before delivery')
    if container.inspect(target, warm, deadline=deadline, cancelled=cancelled) != warm['container']:
        raise ValueError('Animate MP4 delivery changed the qualified encoded file')
    remaining()
    notes = ['H.264 video and AAC audio are lossy. Alpha is composited over the requested sRGB matte.',
             'Odd dimensions receive right/bottom padding to even dimensions of at least 2 pixels; no additional resizing occurs.']
    if sound:
        notes.append('Stereo 48 kHz soundtrack. Earlier event sounds are omitted from partial ranges; stream sounds join mid-way.')
    return output, {**planned, 'source_sha256': raster['source_sha256'], 'bytes': warm['artifact']['bytes'],
        'artifacts': [warm['artifact']], 'video': warm, 'native_state_equal': True, 'cold_export_equal': True,
        'complete_decode_verified': True, 'container_timing_verified': True, 'notes': notes,
        'interactive_playback_verified': False, 'visual_approval': False, 'publication_authorized': False}
