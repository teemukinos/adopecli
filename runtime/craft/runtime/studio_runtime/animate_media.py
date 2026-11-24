"""Bounded embedded media and stored sound-placement admission for Animate.

Use after graph admission. The sound inspector is an internal trusted decoder,
not document-supplied code or reports. No operation is registered here. Complete
native state preservation, shaping and composed rendering/mixing budgets remain
separate requirements; stored sound effects do not prove the exported mix.
"""
import base64
import binascii
import hashlib
import io
import math
import struct
import zlib

from .animate_format import number
from .animate_graph import fields, identity, label, sequence
from .animate_properties import boolean, choice, f32

MAX_ENCODED = 32 << 20
MAX_TOTAL_BYTES = 48 << 20
MAX_PIXELS = 64_000_000
MAX_SAMPLES = 64 * 1024 * 1024
MAX_PLACEMENTS = 8192
MAX_ENVELOPE_POINTS = 32768
EFFECTS = ('none', 'left_channel', 'right_channel', 'fade_left_to_right',
           'fade_right_to_left', 'fade_in', 'fade_out')


def payload(value):
    if not isinstance(value, str) or len(value) > (MAX_ENCODED + 2) // 3 * 4:
        raise ValueError('Animate embedded media exceeds its encoded byte budget')
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('Animate embedded media has invalid base64') from error
    # Decoder permissiveness must not hide discarded pad bits or excess padding.
    if not result or len(result) > MAX_ENCODED or base64.b64encode(result).decode('ascii') != value:
        raise ValueError('Animate embedded media requires canonical nonempty base64')
    return result


def png(data, width, height):
    """Check the complete PNG stream before invoking its bounded pixel decoder."""
    from PIL import Image
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Animate bitmap is not a PNG')
    offset = 8; count = 0; idat = False; ended = False; idat_closed = False
    decoder = zlib.decompressobj(); raw_bytes = 0; expected = 0
    while offset < len(data):
        count += 1
        if count > 4096 or offset + 12 > len(data) or ended:
            raise ValueError('Animate PNG has excess or incomplete chunks')
        length, tag = struct.unpack_from('>I4s', data, offset)
        end = offset + 12 + length
        if end > len(data):
            raise ValueError('Animate PNG chunk is truncated')
        chunk = memoryview(data)[offset + 8:end - 4]
        crc = zlib.crc32(chunk, zlib.crc32(tag)) & 0xffffffff
        if crc != struct.unpack_from('>I', data, end - 4)[0]:
            raise ValueError('Animate PNG chunk checksum does not match')
        if count == 1:
            if tag != b'IHDR' or length != 13 or struct.unpack_from('>II', chunk) != (width, height):
                raise ValueError('Animate bitmap dimensions disagree with PNG header')
            depth, color, compression, filtering, interlace = chunk[8:13]
            allowed = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if depth not in allowed.get(color, ()) or compression or filtering or interlace not in (0, 1):
                raise ValueError('Animate PNG has unsupported image parameters')
            bits = depth * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            passes = ((0, 0, 1, 1),) if not interlace else (
                (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
            for x, y, dx, dy in passes:
                w, h = max(0, (width-x+dx-1)//dx), max(0, (height-y+dy-1)//dy)
                if w and h:
                    expected += (1 + (w*bits+7)//8) * h
        elif tag == b'IHDR':
            raise ValueError('Animate PNG repeats its image header')
        if tag == b'IDAT':
            if idat_closed:
                raise ValueError('Animate PNG image chunks must be contiguous')
            idat = True
            pending = chunk
            try:
                while pending:
                    raw_bytes += len(decoder.decompress(pending, min(65536, expected - raw_bytes + 1)))
                    if raw_bytes > expected or decoder.unused_data:
                        raise ValueError('Animate PNG exceeds its scanline budget or has trailing compressed data')
                    pending = decoder.unconsumed_tail
            except zlib.error as error:
                raise ValueError('Animate PNG compressed image stream is damaged') from error
        elif idat:
            idat_closed = True
        if tag == b'IEND':
            if length or not idat:
                raise ValueError('Animate PNG has no complete image stream')
            ended = True
        offset = end
    if not ended or not decoder.eof or raw_bytes != expected:
        raise ValueError('Animate PNG has incomplete image bytes or no end marker')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'PNG' or image.size != (width, height) or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Animate bitmap must decode to one image with its stated dimensions')
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError('Animate bitmap pixels cannot be decoded') from error


def placements(document):
    count = points = clamped_repeats = changed_envelopes = 0
    for owner in document['scenes'] + document['library']:
        for layer in owner['timeline']['layers']:
            for key in layer['keyframes']:
                sound = key.get('sound')
                if sound is None:
                    continue
                count += 1
                if count > MAX_PLACEMENTS:
                    raise ValueError('Animate document exceeds its stored sound placement budget')
                fields(sound, ('sound',), ('sync', 'repeat', 'loop', 'effect'), 'frame sound')
                identity(sound['sound'])  # Graph admission checks the library reference.
                choice(sound.get('sync', 'event'), ('event', 'start', 'stop', 'stream'), 'sound sync')
                boolean(sound.get('loop', False), 'sound loop')
                repeat = sound.get('repeat', 1)
                if type(repeat) is not int or not 0 <= repeat <= 0xffffffff:
                    raise ValueError('Animate sound repeat must be a native u32')
                # Native loading preserves these values; heard() clamps only
                # during playback. Retain and report, never silently repair.
                clamped_repeats += not 1 <= repeat <= 9999
                effect = sound.get('effect', 'none')
                if isinstance(effect, str):
                    choice(effect, EFFECTS, 'sound effect'); continue
                fields(effect, ('custom',), (), 'sound envelope')
                envelope = sequence(effect['custom'], 256, 'stored envelope points')
                points += len(envelope)
                if points > MAX_ENVELOPE_POINTS:
                    raise ValueError('Animate document exceeds its stored envelope budget')
                changed = len(envelope) > 16; previous = -math.inf
                for point in envelope:
                    fields(point, ('at', 'left', 'right'), (), 'envelope point')
                    if not number(point['at'], -(2**64-1), 2**64-1):
                        raise ValueError('Animate envelope time must be finite')
                    changed |= not 0 <= point['at'] <= 86400 or point['at'] < previous
                    previous = point['at']
                    for channel in ('left', 'right'):
                        if not number(point[channel], -(2**64-1), 2**64-1):
                            raise ValueError('Animate envelope level exceeds its finite range')
                        changed |= not 0 <= f32(point[channel]) <= 1
                changed_envelopes += changed
    return {'placements': count, 'envelope_points': points,
            'playback_clamped_repeats': clamped_repeats,
            'playback_normalized_envelopes': changed_envelopes,
            'expanded_voice_budget_verified': False, 'mix_fidelity_verified': False}


def inspect_media(document, inspect_sound):
    """Validate bytes and metadata with an internal complete native sound probe.

    Sound budgets are passed to the decoder before allocation. A falsely small
    stored frame count fails during decoding; a falsely large count fails exact
    readback. Reports are produced here from bytes, never accepted from a caller's
    imported document. The inspector must support cancellation and a deadline.
    """
    sound_placements = placements(document)
    pixels = samples = encoded = 0; images = {}; sounds = {}
    for item in document.get('bitmaps', []):
        fields(item, ('id', 'name', 'width', 'height', 'png'), ('smoothing',), 'bitmap')
        identity(item['id']); label(item['name']); boolean(item.get('smoothing', True), 'bitmap smoothing')
        width, height = item['width'], item['height']
        if any(type(n) is not int or not 1 <= n <= 8192 for n in (width, height)) or width * height > 32_000_000:
            raise ValueError('Animate bitmap dimensions exceed the decode budget')
        pixels += width * height
        if pixels > MAX_PIXELS:
            raise ValueError('Animate bitmaps exceed the aggregate decoded pixel budget')
        data = payload(item['png']); encoded += len(data)
        if encoded > MAX_TOTAL_BYTES:
            raise ValueError('Animate embedded media exceeds the total byte budget')
        png(data, width, height)
        images[item['id']] = {'width': width, 'height': height, 'encoded_bytes': len(data),
                              'sha256': hashlib.sha256(data).hexdigest()}
    # Validate aggregate claimed audio dimensions before any native allocation.
    for item in document.get('sounds', []):
        fields(item, ('id', 'name', 'format', 'rate', 'channels', 'frames', 'data'), (), 'sound')
        identity(item['id']); label(item['name']); choice(item['format'], ('wav', 'ogg', 'mp3'), 'sound encoding')
        if (type(item['rate']) is not int or not 1000 <= item['rate'] <= 384000
                or type(item['channels']) is not int or item['channels'] not in (1, 2)
                or type(item['frames']) is not int or item['frames'] < 1):
            raise ValueError('Animate sound metadata has invalid rate, channels or frames')
        samples += item['frames'] * item['channels']
        if samples > MAX_SAMPLES:
            raise ValueError('Animate sounds exceed the aggregate decoded sample budget')
    payloads = []
    for item in document.get('sounds', []):
        data = payload(item['data']); encoded += len(data)
        if encoded > MAX_TOTAL_BYTES:
            raise ValueError('Animate embedded media exceeds the total byte budget')
        payloads.append(data)
    for item, data in zip(document.get('sounds', []), payloads):
        report = inspect_sound(data, item['frames'] * item['channels'])
        fields(report, ('format', 'rate', 'channels', 'frames', 'samples', 'encoded_bytes',
                        'peak', 'rms', 'decode', 'channel_policy', 'document_changed'), (), 'native sound report')
        if (report.get('decode') != 'complete-native' or report.get('channel_policy') != 'first_two'
                or report.get('document_changed') is not False
                or type(report.get('encoded_bytes')) is not int or report['encoded_bytes'] != len(data)
                or any(type(report.get(name)) is not int or report[name] != item[name]
                       for name in ('rate', 'channels', 'frames'))
                or type(report.get('samples')) is not int or report['samples'] != item['frames'] * item['channels']
                or not number(report['peak'], 0, float('inf')) or not number(report['rms'], 0, float('inf'))
                or report['rms'] > report['peak'] * (1 + 1e-9) + 1e-12
                or report.get('format') != item['format']):
            raise ValueError('Animate stored sound metadata disagrees with the complete native decode')
        sounds[item['id']] = {**report, 'sha256': hashlib.sha256(data).hexdigest()}
    return {'images': images, 'sounds': sounds, 'encoded_bytes': encoded,
            'decoded_pixels': pixels, 'decoded_samples': samples, 'sound_placements': sound_placements}
