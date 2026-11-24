"""Write byte-store ownership and independent raster decoding.

No resource name grants filesystem access. Original encodings remain unchanged.
Native picture packets prove decoder agreement only, never document admission.
"""
import base64
import binascii
import hashlib
import io
import struct
import unicodedata
import warnings

from .write_container import require, strict_json

MAX_ITEM = 32 << 20
MAX_BYTES = 128 << 20
MAX_PIXELS = 16_777_216
MAX_TOTAL_PIXELS = 33_554_432
MAX_SIDE = 8192
FORMATS = {'PNG': 'Png', 'JPEG': 'Jpeg', 'GIF': 'Gif', 'WEBP': 'WebP', 'BMP': 'Bmp', 'TIFF': 'Tiff'}
TIFF_COMPRESSIONS = {1, 4, 5, 8, 32946, 32773}
CONTROL_PARTS = frozenset(('wordcraft:embedded.parts', 'wordcraft:customXml.roots', 'wordcraft:settings.orig',
                           'wordcraft:app.kept', 'wordcraft:unmodelled.roots', 'wordcraft:glossary.read'))


def webp_lossless(data):
    require(data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) >= 20, 'WebP container is invalid')
    position = 12; codecs = []
    while position+8 <= len(data):
        kind = data[position:position+4]; size = struct.unpack_from('<I', data, position+4)[0]
        position += 8+size+(size & 1)
        require(position <= len(data), 'WebP chunk is truncated')
        if kind in (b'VP8 ', b'VP8L'): codecs.append(kind)
    require(position == len(data) and len(codecs) == 1 and struct.unpack_from('<I', data, 4)[0]+8 == len(data),
            'WebP picture must have one complete image payload')
    return codecs[0] == b'VP8L'


def decode_store(store, label, *, package=False):
    require(type(store) is dict and len(store) <= 4096, label+' inventory exceeds its budget')
    result = {}; folded = set(); total = 0
    for name, encoded in store.items():
        require(type(name) is str and 0 < len(name.encode('utf-8')) <= 512
                and name == unicodedata.normalize('NFC', name) and not any(ord(c) < 32 or ord(c) == 127 for c in name)
                and not any(c in name for c in ('\\', '%')) and not name.startswith('/')
                and (':' not in name or package and name in CONTROL_PARTS), label+' identity is ambiguous or unsafe')
        parts = name.split('/')
        require(all(p and p not in ('.', '..') and p == p.strip() for p in parts)
                and (package or len(parts) == 1), label+' identity escapes its owned namespace')
        key = name.casefold(); require(key not in folded, label+' identities collide'); folded.add(key)
        if type(encoded) is str:
            require(len(encoded) <= 4*((MAX_ITEM+2)//3), label+' encoded bytes exceed the item budget')
            try: data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error: raise ValueError('Write '+label+' is not canonical base64') from error
            require(base64.b64encode(data).decode('ascii') == encoded, label+' base64 has ambiguous padding bits')
            encoding = 'base64'
        else:
            require(type(encoded) is list and len(encoded) <= MAX_ITEM
                    and all(type(v) is int and 0 <= v <= 255 for v in encoded), label+' legacy byte array is invalid')
            data = bytes(encoded); encoding = 'legacy-byte-array'
        total += len(data)
        require(len(data) <= MAX_ITEM and total <= MAX_BYTES, label+' decoded bytes exceed the budget')
        result[name] = {'data': data, 'encoding': encoding, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    for name in result:
        require(not any('/'.join(name.split('/')[:i]).casefold() in folded for i in range(1, len(name.split('/')))),
                label+' file collides with an ancestor')
    return result


def decode_image(data, *, remaining_pixels=MAX_TOTAL_PIXELS):
    from PIL import Image, ImageFile
    require(type(data) is bytes and 0 < len(data) <= MAX_ITEM, 'picture byte size exceeds its budget')
    require(not ImageFile.LOAD_TRUNCATED_IMAGES, 'picture decoder must refuse truncated images')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                require(image.format in FORMATS, 'picture format requires separate qualification')
                width, height = image.size; pixels = width*height
                require(0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE
                        and pixels <= MAX_PIXELS and pixels <= remaining_pixels, 'picture dimensions exceed the pixel budget')
                require(getattr(image, 'n_frames', 1) == 1, 'animated or multipage pictures require explicit frame selection')
                if image.format == 'TIFF':
                    require(image.tag_v2.get(259, 1) in TIFF_COMPRESSIONS, 'native TIFF decoder does not admit this compression')
                profile = {'format': image.format, 'width': width, 'height': height, 'sample_type': image.mode,
                           'lossy_decoder_tolerance': image.format == 'JPEG' or (image.format == 'WEBP' and not webp_lossless(data))}
                # Verify integrity before reopening for full pixel decoding.
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.mode in ('I;16', 'I;16L', 'I;16B'):
                    # Pillow convert(RGBA) clips these samples at 255. Native
                    # image::DynamicImage rounds the full 0..65535 range to 0..255.
                    values = image.get_flattened_data()
                    gray = bytes((v+128)//257 for v in values)
                    with Image.frombytes('L', image.size, gray) as eight: rgba = eight.convert('RGBA').tobytes()
                else:
                    require(image.mode in ('1', 'L', 'LA', 'P', 'RGB', 'RGBA', 'CMYK'), 'picture sample type requires separate qualification')
                    rgba = image.convert('RGBA').tobytes()
                pending = []
                if image.info.get('icc_profile'): pending.append('embedded-color-profile')
                if image.getexif().get(274, 1) != 1: pending.append('image-orientation')
                if image.mode in ('I;16', 'I;16L', 'I;16B') or (data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) > 24 and data[24] == 16):
                    pending.append('sixteen-bit-source-fidelity')
                if image.mode == 'CMYK': pending.append('cmyk-color-fidelity')
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ValueError('Write picture cannot be independently decoded: '+str(error)) from error
    require(len(rgba) == pixels*4, 'independent decoder returned inconsistent pixel dimensions')
    return {**profile, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'rgba8_sha256': hashlib.sha256(rgba).hexdigest(), 'rgba8_bytes': len(rgba), 'pending_qualification': pending}, rgba


def inspect(document):
    media = decode_store(document.get('media', {}), 'media')
    passthrough = decode_store(document.get('passthrough', {}), 'retained package part', package=True)
    total = sum(v['bytes'] for v in media.values())+sum(v['bytes'] for v in passthrough.values())
    require(total <= MAX_BYTES, 'aggregate embedded bytes exceed the budget')
    images = {}; pixels = 0; pending = {'native-picture-comparison', 'font-identity-and-glyphs', 'source-format-fidelity'}
    for name, item in media.items():
        report, _ = decode_image(item['data'], remaining_pixels=MAX_TOTAL_PIXELS-pixels)
        pixels += report['width']*report['height']; images[name] = {**report, 'encoding': item['encoding']}
        pending.update(report['pending_qualification'])
    # Retained parts can contain font tables, obfuscated fonts, custom XML and
    # embedded-package manifests. They must never be treated as inert leftovers.
    if passthrough: pending.add('retained-package-and-embedded-fonts')
    return {'images': images, 'passthrough': {k: {n: v for n, v in item.items() if n != 'data'} for k, item in passthrough.items()},
            'decoded_bytes': total, 'pixels': pixels, 'rgba8_bytes': pixels*4,
            'pending_qualification': sorted(pending), 'engine_admission_complete': False}


def compare_picture(packet, source):
    require(type(packet) is bytes and 12 <= len(packet) <= 4*MAX_PIXELS+65548 and packet[:8] == b'DOBEPIC1',
            'native picture packet is invalid')
    size = struct.unpack_from('<I', packet, 8)[0]
    require(1 <= size <= 65536 and 12+size <= len(packet), 'native picture header exceeds its budget')
    header = strict_json(packet[12:12+size]); rgba = packet[12+size:]
    expected, independent = decode_image(source)
    require(type(header) is dict and set(header) == {'schemaVersion', 'format', 'width', 'height', 'sourceBytes', 'nativePeakBytes', 'sampleType', 'pixelFormat', 'pixelBytes'},
            'native picture header has missing or unknown fields')
    for key, value in [('schemaVersion', 1), ('width', expected['width']), ('height', expected['height']),
                       ('sourceBytes', len(source)), ('pixelBytes', len(independent))]:
        require(type(header[key]) is int and header[key] == value, 'native picture disagrees with independent '+key)
    require(header['format'] == FORMATS[expected['format']] and header['pixelFormat'] == 'RGBA8'
            and type(header['nativePeakBytes']) is int and 0 < header['nativePeakBytes'] <= 128 << 20
            and header['sampleType'] in ('L8', 'La8', 'Rgb8', 'Rgba8', 'L16', 'La16', 'Rgb16', 'Rgba16')
            and len(rgba) == len(independent), 'native picture encoding or payload is inconsistent')
    # JPEG/WebP decoders can round color channels differently. Alpha must agree
    # exactly; lossless formats require byte equality, including transparent RGB.
    require(rgba[3::4] == independent[3::4], 'native picture alpha differs from the independent decoder')
    maximum = 0; total = 0
    for a, b in zip(rgba, independent):
        delta = abs(a-b); maximum = max(maximum, delta); total += delta
    mean = total / len(rgba)
    lossy = expected['lossy_decoder_tolerance']
    require((maximum <= 3 and mean <= .5) if lossy else maximum == 0, 'native picture pixels differ from the independent decoder')
    return {'source_sha256': expected['sha256'], 'native': header, 'max_channel_error': maximum, 'mean_channel_error': mean,
            'rgba8_sha256': hashlib.sha256(rgba).hexdigest(), 'pending_qualification': expected['pending_qualification'],
            'decoder_agreement': True, 'engine_admission_complete': False}
