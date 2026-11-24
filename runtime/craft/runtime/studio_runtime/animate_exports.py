"""Typed native exports, qualified before durable artifact publication.

The maintained engine renders the movie. This module chooses owned destinations,
checks every encoded frame and atlas entry, and proves cold export repeatability.
GIF quantization and centisecond timing are explicit format losses.
"""
import io
import json
import math
import os
from pathlib import Path
import stat
import time

from . import animate_document as document, animate_format as format
from . import animate_media as media, animate_project as project, animate_semantics as semantics
from .animate_diagnostics import counters, integer
from .animate_graph import fields
from .animate_native_probe import NativeInspector
from .animate_process import run
from .animate_properties import f32
from . import animate_audio_export, animate_document_export, animate_video_export

RASTER_FORMATS = ('png_sequence', 'gif', 'sprite_sheet')
FORMATS = RASTER_FORMATS + ('wav',) + animate_document_export.FORMATS + ('mp4',)
MAX_BYTES = 512 << 20
MAX_PIXELS = 16_777_216
MAX_SEQUENCE_PIXELS = 552_960_000


def validate(value):
    if isinstance(value, dict) and value.get('format') == 'mp4':
        return animate_video_export.validate(value)
    if isinstance(value, dict) and value.get('format') in animate_document_export.FORMATS:
        return animate_document_export.validate(value)
    if isinstance(value, dict) and value.get('format') == 'wav':
        return animate_audio_export.validate(value)
    fields(value, ('format',), ('from', 'to', 'scale', 'loop', 'columns', 'padding', 'background'), 'export request')
    kind = value['format']
    if kind not in RASTER_FORMATS:
        raise ValueError('Animate export format must be ' + ', '.join(FORMATS))
    extras = {'loop'} if kind == 'gif' else {'columns', 'padding', 'background'} if kind == 'sprite_sheet' else set()
    fields(value, ('format',), {'from', 'to', 'scale'} | extras, 'export request')
    for key in ('from', 'to'):
        if key in value:
            integer(value[key], 0, 999_999, 'export ' + key)
    if value.get('to', value.get('from', 0)) < value.get('from', 0):
        raise ValueError('Animate export frame range is reversed')
    if not format.number(value.get('scale', 1), .001, 8):
        raise ValueError('Animate export scale must be between 0.001 and 8')
    for key in ('loop', 'background'):
        if key in value and type(value[key]) is not bool:
            raise ValueError('Animate export ' + key + ' must be boolean')
    if 'columns' in value:
        integer(value['columns'], 1, 600, 'sprite columns')
    if 'padding' in value:
        integer(value['padding'], 0, 256, 'sprite padding')


def plan(profile, value):
    if isinstance(value, dict) and value.get('format') == 'mp4':
        return animate_video_export.plan(profile, value)
    if isinstance(value, dict) and value.get('format') in animate_document_export.FORMATS:
        return animate_document_export.plan(profile, value)
    if isinstance(value, dict) and value.get('format') == 'wav':
        return animate_audio_export.plan(profile, value)
    validate(value)
    last = profile['graph']['frames'] - 1
    first = integer(value.get('from', 0), 0, last, 'export first frame')
    last = integer(value.get('to', last), first, last, 'export last frame')
    count = integer(last - first + 1, 1, 600, 'export frame count')
    scale = f32(value.get('scale', 1))
    stage = profile['envelope']['document']['stage']
    width, height = [max(1, math.floor(f32(stage[key] * scale) + .5)) for key in ('width', 'height')]
    if width * height > MAX_PIXELS or width * height * count > MAX_SEQUENCE_PIXELS:
        raise ValueError('Animate export exceeds its frame or aggregate pixel budget')
    request = {'format': value['format'], 'from': first, 'to': last, 'scale': scale}
    result = {'request': request, 'frames': count, 'width': width, 'height': height, 'fps': profile['graph']['fps']}
    if value['format'] == 'gif':
        if width > 65535 or height > 65535:
            raise ValueError('Animate GIF dimensions exceed the format limit')
        request['loop'] = value.get('loop', True)
    if value['format'] == 'sprite_sheet':
        columns = value.get('columns', math.ceil(math.sqrt(count)))
        if columns > count:
            raise ValueError('Animate sprite columns must not exceed the selected frame count')
        padding = value.get('padding', 0)
        rows = (count + columns - 1) // columns
        size = [width * columns + padding * (columns - 1), height * rows + padding * (rows - 1)]
        if size[0] * size[1] > MAX_PIXELS:
            raise ValueError('Animate sprite atlas exceeds its pixel budget')
        request.update(columns=columns, padding=padding, background=value.get('background', False))
        result.update(columns=columns, rows=rows, atlas_size=size)
    return result


def delays(count, fps):
    # Native GIF timing carries fractional centiseconds between frames, with a
    # two-centisecond floor imposed for browser compatibility.
    return [10 * max(2, math.floor((i + 1) * 100 / fps + .5) - math.floor(i * 100 / fps + .5)) for i in range(count)]


def read_output(path, limit=MAX_BYTES):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                raise ValueError('Animate export requires a bounded regular output file')
            data = stream.read(before.st_size + 1)
            after = os.fstat(stream.fileno())
        if (len(data) != before.st_size or len(data) > limit or
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('Animate export changed while it was read')
        return data
    except OSError as error:
        raise ValueError('Animate export output cannot be read') from error


def png(data, width, height):
    from PIL import Image
    media.png(data, width, height)
    with Image.open(io.BytesIO(data)) as image:
        with image.convert('RGBA') as rgba:
            return project.digest(rgba.tobytes())


def gif_container(data, count):
    """Require complete GIF blocks and exactly one terminal trailer."""
    if len(data) < 14 or data[:6] not in (b'GIF87a', b'GIF89a'):
        raise ValueError('Animate GIF has an incomplete header')
    offset = 13 + (3 * (2 ** ((data[10] & 7) + 1)) if data[10] & 128 else 0)
    frames = 0

    def blocks(at):
        while at < len(data):
            size = data[at]; at += 1
            if not size:
                return at
            at += size
        raise ValueError('Animate GIF contains an incomplete data block')

    while offset < len(data):
        tag = data[offset]; offset += 1
        if tag == 59:
            if offset != len(data) or frames != count:
                raise ValueError('Animate GIF contains trailing data or the wrong frame count')
            return
        if tag == 33 and offset < len(data):
            offset = blocks(offset + 1)
        elif tag == 44 and offset + 9 <= len(data):
            packed = data[offset + 8]; offset += 9
            offset += 3 * (2 ** ((packed & 7) + 1)) if packed & 128 else 0
            if offset >= len(data) or not 2 <= data[offset] <= 8:
                raise ValueError('Animate GIF contains invalid image data')
            offset = blocks(offset + 1); frames += 1
            if frames > count:
                raise ValueError('Animate GIF contains too many frames')
        else:
            raise ValueError('Animate GIF contains an invalid block')
    raise ValueError('Animate GIF has no terminal trailer')


def render_work(report):
    fields(report, ('bytes_reserved', 'stroke_steps', 'raster_steps', 'helper_steps', 'geometry'), (), 'export work')
    counters({key: value for key, value in report.items() if key != 'geometry'},
             {'bytes_reserved': 8 << 30, 'stroke_steps': 32_000_000, 'raster_steps': 8_000_000_000,
              'helper_steps': 160_000_000}, 'export work')
    counters(report['geometry'], {'path_commands': 32_000_000, 'flatten_points': 32_000_000,
             'morph_steps': 160_000_000, 'sliced_commands': 32_000_000, 'walk_steps': 80_000_000}, 'export geometry')


def inspect(directory, reply, planned):
    from PIL import Image
    request = planned['request']; kind = request['format']; count = planned['frames']
    width, height = planned['width'], planned['height']
    base = {'frames', 'render_work'}
    required = {'dir', 'encoded_bytes'} if kind == 'png_sequence' else {'written', 'bytes', 'width', 'height'} if kind == 'gif' else {'written', 'map', 'columns', 'rows', 'width', 'height'}
    fields(reply, base | required, (), 'raster export report')
    integer(reply['frames'], count, count, 'reported export frames')
    render_work(reply['render_work'])
    if kind == 'png_sequence':
        names = ['frame_' + str(frame + 1).zfill(5) + '.png' for frame in range(request['from'], request['to'] + 1)]
        if reply['dir'] != str(directory):
            raise ValueError('Animate sequence reported an unexpected directory')
    else:
        names = ['movie.gif'] if kind == 'gif' else ['atlas.png', 'atlas.json']
        if reply['written'] != str(directory / names[0]):
            raise ValueError('Animate export reported an unexpected path')
        expected_width, expected_height = [width, height] if kind == 'gif' else planned['atlas_size']
        integer(reply['width'], expected_width, expected_width, 'reported export width')
        integer(reply['height'], expected_height, expected_height, 'reported export height')
    if {path.name for path in directory.iterdir()} != set(names):
        raise ValueError('Animate export contains missing or unexpected artifacts')
    artifacts = []; total = 0; frame_hashes = []; timing = delays(count, planned['fps'])
    for name in names:
        data = read_output(directory / name, (4 << 20) if name.endswith('.json') else MAX_BYTES)
        total += len(data)
        if total > MAX_BYTES + (4 << 20):
            raise ValueError('Animate raster export exceeds its encoded byte budget')
        record = {'file': name, 'bytes': len(data), 'sha256': project.digest(data)}
        if kind == 'png_sequence':
            record['rgba_sha256'] = png(data, width, height)
            frame_hashes.append(record['rgba_sha256'])
        elif kind == 'gif':
            integer(reply['bytes'], len(data), len(data), 'reported GIF bytes')
            gif_container(data, count)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'GIF' or image.size != (width, height) or image.n_frames != count:
                    raise ValueError('Animate GIF dimensions or frame count disagree with the request')
                if (request['loop'] and image.info.get('loop') != 0) or (not request['loop'] and 'loop' in image.info):
                    raise ValueError('Animate GIF loop setting disagrees with the request')
                for index in range(count):
                    image.seek(index)
                    if image.info.get('duration') != timing[index]:
                        raise ValueError('Animate GIF frame timing disagrees with native rounding')
                    with image.convert('RGBA') as rgba:
                        frame_hashes.append(project.digest(rgba.tobytes()))
            record['frame_rgba_sha256'] = frame_hashes
        elif name == 'atlas.png':
            record['rgba_sha256'] = png(data, *planned['atlas_size'])
            with Image.open(io.BytesIO(data)) as image:
                with image.convert('RGBA') as rgba:
                    for index in range(count):
                        x = (index % planned['columns']) * (width + request['padding'])
                        y = (index // planned['columns']) * (height + request['padding'])
                        with rgba.crop((x, y, x + width, y + height)) as tile:
                            frame_hashes.append(project.digest(tile.tobytes()))
        else:
            atlas = format.strict_json(data)
            frames = {}
            for index, frame in enumerate(range(request['from'], request['to'] + 1)):
                x = (index % planned['columns']) * (width + request['padding'])
                y = (index // planned['columns']) * (height + request['padding'])
                frames['atlas_' + str(frame + 1).zfill(4)] = {
                    'frame': {'x': x, 'y': y, 'w': width, 'h': height}, 'rotated': False, 'trimmed': False,
                    'spriteSourceSize': {'x': 0, 'y': 0, 'w': width, 'h': height},
                    'sourceSize': {'w': width, 'h': height}, 'duration': timing[index]}
            expected = {'frames': frames, 'meta': {'app': 'Dobe Animate', 'version': '0.2.1', 'image': 'atlas.png',
                        'format': 'RGBA8888', 'size': dict(zip(('w', 'h'), planned['atlas_size'])),
                        'scale': atlas.get('meta', {}).get('scale'), 'frameRate': planned['fps']}}
            scale = expected['meta']['scale']
            if (not isinstance(scale, str) or not format.number(float(scale), .001, 8)
                    or f32(float(scale)) != request['scale'] or semantics.difference(expected, atlas) is not None):
                raise ValueError('Animate sprite map disagrees with its exact frame layout or timing')
            if reply['map'] != str(directory / name):
                raise ValueError('Animate sprite map reported an unexpected path')
            for key in ('columns', 'rows'):
                integer(reply[key], planned[key], planned[key], 'reported sprite ' + key)
        artifacts.append(record)
    if kind == 'png_sequence':
        integer(total, 1, MAX_BYTES, 'sequence encoded bytes')
        integer(reply['encoded_bytes'], total, total, 'reported sequence bytes')
    return {'artifacts': artifacts, 'frame_rgba_sha256': frame_hashes,
            'frame_durations_ms': timing if kind != 'png_sequence' else None}


def observe(inspector, source, root, planned):
    root.mkdir(); output = root / 'output'; output.mkdir()
    request = planned['request']; kind = request['format']
    params = {key: value for key, value in request.items() if key != 'format'}
    if kind == 'png_sequence':
        params['dir'] = str(output)
    else:
        params['path'] = str(output / ('movie.gif' if kind == 'gif' else 'atlas.png'))
    saved = root / 'document.anicraft'
    steps = [{'cmd': 'file.export_' + kind, 'params': params}, {'cmd': 'file.save', 'params': {'path': str(saved)}}]
    script = root / 'steps.json'; script.write_text(json.dumps(steps))
    replies = format.strict_json(run([str(inspector.executable), 'run', str(source), str(script),
        '--automation-read-root', str(inspector.root), '--automation-write-root', str(root)], root,
        deadline=inspector.deadline, cancelled=inspector.cancelled, stdout_limit=1 << 20), max_items=4096)
    if not isinstance(replies, list) or len(replies) != 2 or replies[1] != {'saved': str(saved)}:
        raise ValueError('Animate raster export returned an incomplete native report')
    return saved, inspect(output, replies[0], planned)


def prepare(root, source, value, executable, *, cancelled=lambda: False, seconds=120):
    if isinstance(value, dict) and value.get('format') == 'mp4':
        return animate_video_export.prepare(root, source, value, executable, cancelled=cancelled, seconds=seconds)
    if isinstance(value, dict) and value.get('format') in animate_document_export.FORMATS:
        return animate_document_export.prepare(root, source, value, executable, cancelled=cancelled, seconds=seconds)
    if isinstance(value, dict) and value.get('format') == 'wav':
        return animate_audio_export.prepare(root, source, value, executable, cancelled=cancelled, seconds=seconds)
    root = Path(root).absolute(); root.mkdir()
    inspector = NativeInspector(executable, root, cancelled=cancelled, seconds=seconds)
    original = document.read_native(source, inspect_sound=inspector)
    planned = plan(original, value)
    original['native_state'] = inspector.preservation(original['source_bytes'])
    snapshot = root / 'source.anicraft'; snapshot.write_bytes(original['source_bytes'])
    saved, warm = observe(inspector, snapshot, root / 'warm', planned)
    decoded = project.reuse_sounds(original)
    loaded = document.read_native(saved, inspect_sound=decoded)
    semantics.compare(original, loaded)
    saved, cold = observe(inspector, saved, root / 'cold', planned)
    semantics.compare(loaded, document.read_native(saved, inspect_sound=decoded))
    if warm != cold:
        raise ValueError('Animate cold export changed raster bytes, pixels or timing')
    if format.read_bytes(source) != original['source_bytes']:
        raise ValueError('Animate raster export changed the native source')
    if cancelled() or time.monotonic() >= inspector.deadline:
        raise ValueError('Animate raster export cancelled or timed out')
    return root / 'warm/output', {**planned, **warm, 'source_sha256': original['source_sha256'],
        'native_state_equal': True, 'cold_export_equal': True, 'complete_decode_verified': True,
        'notes': ['GIF reduces colors to a palette and rounds timing to centiseconds, with a 20 ms minimum.']
                 if value['format'] == 'gif' else ['Sprite durations use centiseconds with a 20 ms minimum; frameRate retains native fps.']
                 if value['format'] == 'sprite_sheet' else [],
        'interactive_playback_verified': False, 'visual_approval': False, 'publication_authorized': False}
