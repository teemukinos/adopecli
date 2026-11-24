"""Bounded non-destructive photo libraries with portable originals and native edits."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import struct
import subprocess
import threading
import tempfile
import zlib

from . import vector, video

OPERATIONS = ('photo.create', 'photo.edit')
VERSION = '0.21.1'
MAX_PIXELS = 64_000_000
FORMATS = {'png': 'PNG', 'jpeg': 'JPEG', 'tiff': 'TIFF', 'dng': 'DNG'}
CONTROLS = {'light.exposure': (-5, 5), 'wb.temp': (2000, 50000), 'wb.tint': (-150, 150)}
CONTROLS.update({key: (-100, 100) for key in (
    'light.contrast', 'light.highlights', 'light.shadows', 'light.whites', 'light.blacks',
    'color.vibrance', 'color.saturation', 'effects.texture', 'effects.clarity', 'effects.dehaze')})
DEFAULTS = json.loads(Path(__file__).with_name('photo_defaults.json').read_text())


def crop_valid(rect):
    return (isinstance(rect, list) and len(rect) == 4 and all(video.finite(x, 0, 1) for x in rect)
            and rect[2] - rect[0] >= 1 / 8192 and rect[3] - rect[1] >= 1 / 8192)


def adjustments_valid(values):
    return (isinstance(values, dict) and bool(values) and not set(values) - CONTROLS.keys()
            and all(video.finite(value, *CONTROLS[key]) for key, value in values.items()))


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict) or set(params) - {'photos', 'bit_depth'}:
        raise ValueError('unsupported photo operation or parameters')
    if operation == 'photo.create' and source_revision is not None or operation == 'photo.edit' and not source_revision:
        raise ValueError('photo.create requires a new project; photo.edit requires a source revision')
    if 'bit_depth' in params and (type(params['bit_depth']) is not int or params['bit_depth'] not in (8, 16)):
        raise ValueError('photo PNG bit depth must be 8 or 16')
    photos = params.get('photos')
    if not isinstance(photos, list) or not 1 <= len(photos) <= 32:
        raise ValueError('photo operations require 1 to 32 named photos')
    names = set()
    for photo in photos:
        allowed = {'name', 'adjustments', 'crop'} | ({'asset', 'format'} if operation == 'photo.create' else set())
        if not isinstance(photo, dict) or set(photo) - allowed or not video.named(photo.get('name')) or photo['name'] in names:
            raise ValueError('photos require unique names and supported fields')
        names.add(photo['name'])
        if operation == 'photo.create':
            if (not isinstance(photo.get('asset'), str) or not video.ASSET.fullmatch(photo['asset'])
                    or not isinstance(photo.get('format'), str) or photo['format'] not in FORMATS):
                raise ValueError('photos require an imported asset and png, jpeg, tiff or dng format')
        elif not set(photo) & {'adjustments', 'crop'}:
            raise ValueError('photo edits require adjustments or crop')
        if 'adjustments' in photo and not adjustments_valid(photo['adjustments']):
            raise ValueError('photo adjustments require finite supported controls inside their ranges')
        if 'crop' in photo and not crop_valid(photo['crop']):
            raise ValueError('photo crop must be a nonempty normalized [x0,y0,x1,y1] rectangle')
    if operation == 'photo.create' and len({p['asset'] for p in photos}) != len(photos):
        raise ValueError('each photo needs a distinct imported asset')


def assets(operation, params):
    return ({p['asset']: 'assets/' + p['asset'] + '.' + p['format'] for p in params['photos']}
            if operation == 'photo.create' else {})


def engine():
    return 'dobe-photo'


def read_json(path, maximum=16 << 20):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('photo JSON must be a regular bounded file')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate photo JSON field')
            result[key] = value
        return result
    value = json.loads(path.read_text(), object_pairs_hook=pairs)
    count = 0
    def walk(item, depth=0):
        nonlocal count
        count += 1
        if count > 250000 or depth > 40:
            raise ValueError('photo JSON exceeds structural limits')
        if isinstance(item, dict):
            for key, child in item.items():
                if len(key) > 256:
                    raise ValueError('photo JSON key too long')
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, str) and len(item) > 32768 or type(item) is float and not math.isfinite(item):
            raise ValueError('photo JSON contains oversized or nonfinite data')
    walk(value)
    return value


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')


def source_info(path, format):
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 256 << 20:
        raise ValueError('photo source must be a bounded regular file')
    if format == 'dng':
        # Inspect every TIFF directory before native decoding, including raw SubIFDs.
        # Native decoding must subsequently identify sensor RAW, never preview fallback.
        data = path.read_bytes()
        if data[:4] not in (b'II*\x00', b'MM\x00*'):
            raise ValueError('DNG requires classic TIFF directories')
        endian = '<' if data[:2] == b'II' else '>'
        def unpack(kind, at):
            size = struct.calcsize(kind)
            if at < 0 or at + size > len(data):
                raise ValueError('truncated DNG directory')
            return struct.unpack_from(endian + kind, data, at)[0]
        pending = [unpack('I', 4)]; visited = set(); dimensions = []; dng = False
        sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
        while pending:
            offset = pending.pop()
            if not offset:
                continue
            if offset in visited or len(visited) >= 64:
                raise ValueError('cyclic or excessive DNG directories')
            visited.add(offset); number = unpack('H', offset)
            if number > 512 or offset + 2 + 12 * number + 4 > len(data):
                raise ValueError('invalid DNG directory length')
            fields = {}
            for n in range(number):
                at = offset + 2 + n * 12; tag = unpack('H', at); kind = unpack('H', at + 2); count = unpack('I', at + 4)
                if kind not in sizes or tag in fields or count > 16_000_000:
                    raise ValueError('invalid DNG field')
                length = sizes[kind] * count; start = at + 8 if length <= 4 else unpack('I', at + 8)
                if start + length > len(data):
                    raise ValueError('DNG field exceeds source bytes')
                values = None
                if kind in (3, 4, 13) and tag in (256, 257, 330, 34665, 34853):
                    if count > 64:
                        raise ValueError('excessive DNG directory references')
                    values = [unpack('H' if kind == 3 else 'I', start + i * sizes[kind]) for i in range(count)]
                fields[tag] = values
                if tag == 50706 and kind == 1 and count == 4:
                    dng = data[start] == 1
                if tag in (330, 34665, 34853) and values:
                    pending.extend(values)
            if 256 in fields or 257 in fields:
                if not fields.get(256) or not fields.get(257) or len(fields[256]) != 1 or len(fields[257]) != 1:
                    raise ValueError('DNG image dimensions missing')
                dimensions.append((fields[256][0], fields[257][0]))
            pending.append(unpack('I', offset + 2 + 12 * number))
        if not dng or not dimensions:
            raise ValueError('source is not a dimensioned DNG')
        for width, height in dimensions:
            if not video.integer(width, 1, 8192) or not video.integer(height, 1, 8192) or width * height > MAX_PIXELS:
                raise ValueError('DNG dimensions exceed the photo budget')
        width, height = max(dimensions, key=lambda x: x[0] * x[1])
    else:
        from PIL import Image
        with Image.open(path) as image:
            if image.format != FORMATS[format] or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('photo source format differs or has multiple frames')
            width, height = image.size
            if not video.integer(width, 1, 8192) or not video.integer(height, 1, 8192) or width * height > MAX_PIXELS:
                raise ValueError('photo dimensions exceed the pixel budget')
            image.verify()
    return {'width': width, 'height': height, 'format': format,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def settings_valid(settings, raw):
    if not isinstance(settings, dict):
        raise ValueError('native photo settings must be an object')
    baseline = copy.deepcopy(DEFAULTS['raw' if raw else 'image'])
    for control, bounds in CONTROLS.items():
        section, name = control.split('.'); value = settings.get(section, {}).get(name)
        if not video.finite(value, *bounds):
            raise ValueError('native photo control is outside its admitted range')
        baseline[section][name] = value
    wb = settings.get('wb', {})
    if wb.get('mode') not in ('asShot', 'custom') or wb.get('scale') not in (None, 'kelvin'):
        raise ValueError('unsupported native photo white balance mode')
    baseline['wb'] = copy.deepcopy(wb)
    if set(wb) - {'mode', 'temp', 'tint', 'scale'}:
        raise ValueError('unsupported native white balance fields')
    crop = settings.get('crop', {}); geometry = crop.get('geometry', {}); rect = geometry.get('rect', {})
    if set(rect) != {'x0', 'y0', 'x1', 'y1'} or not crop_valid([rect[k] for k in ('x0', 'y0', 'x1', 'y1')]):
        raise ValueError('invalid native photo crop')
    baseline['crop']['geometry']['rect'] = copy.deepcopy(rect)
    orientation = settings.get('orientation')
    if orientation not in ('Normal', 'FlipH', 'Rotate180', 'FlipV', 'Transpose', 'Rotate90', 'Transverse', 'Rotate270'):
        raise ValueError('unsupported native photo orientation')
    baseline['orientation'] = orientation
    if settings != baseline:
        raise ValueError('native photo has unqualified profiles, effects, masks or settings')


class Engine(vector.Engine):
    label = 'photo'

    def __init__(self, root, executable=None):
        root = Path(root).resolve()
        self.home = tempfile.TemporaryDirectory(prefix='.photo-home-', dir=root)
        host = Path(self.home.name)
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR', 'TMP', 'TEMP') if key in os.environ}
        env.update(HOME=str(host), XDG_CONFIG_HOME=str(host / 'config'),
                   LIGHTCRAFT_CAMERA_PROFILES=str(host / 'camera-profiles'), LIGHTCRAFT_GPU='0', LIGHTCRAFT_GPU_BACKEND='off')
        try:
            self.proc = subprocess.Popen([str(executable) if executable is not None else engine(), 'mcp', '--library', 'native/library'], cwd=root, env=env,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except BaseException:
            self.home.cleanup(); raise
        self.messages = queue.Queue(); self.counter = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            info = self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                           'clientInfo': {'name': 'dobe-runtime', 'version': '0.1.0'}})
            if info['serverInfo']['version'] != VERSION or info['serverInfo']['name'] != 'dobe-photo':
                raise ValueError('photo engine identity or version is not qualified')
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close(); raise

    def tool(self, name, args):
        result = self.call('tools/call', {'name': name, 'arguments': args})
        texts = [p['text'] for p in result.get('content', []) if p.get('type') == 'text']
        if result.get('isError') or len(texts) != 1:
            raise ValueError(str(result.get('content', []))[:1000])
        return None if texts[0] == 'ok' else json.loads(texts[0])

    def close(self):
        try:
            self.proc.stdin.close(); self.proc.wait(timeout=60)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            self.proc.kill(); self.proc.wait()
            raise RuntimeError('photo engine did not close its native library cleanly')
        finally:
            self.home.cleanup()
        if self.proc.returncode != 0:
            raise RuntimeError('photo engine failed while closing its native library')


def png_info(path):
    """Validate bounded 8/16-bit PNG streams without reducing 16-bit precision."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 512 << 20:
        raise ValueError('photo export must be a regular bounded PNG')
    data = path.read_bytes()
    if len(data) > 512 << 20 or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('photo export requires a bounded PNG')
    offset = 8; header = None; chunks = []; ended = False; metadata = hashlib.sha256()
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError('truncated photo PNG chunk')
        length = struct.unpack_from('>I', data, offset)[0]; tag = data[offset + 4:offset + 8]
        content = data[offset + 8:offset + 8 + length]; end = offset + 12 + length
        if end > len(data) or zlib.crc32(tag + content) != struct.unpack_from('>I', data, end - 4)[0]:
            raise ValueError('photo PNG checksum mismatch')
        if tag != b'IDAT':
            metadata.update(data[offset:end])
        if tag == b'IHDR':
            if header is not None or offset != 8 or length != 13:
                raise ValueError('invalid photo PNG header')
            header = struct.unpack('>IIBBBBB', content)
        elif tag == b'IDAT':
            chunks.append(content)
        elif tag == b'IEND':
            if length or end != len(data):
                raise ValueError('invalid photo PNG end')
            ended = True
        offset = end
    if not header or not ended or not chunks:
        raise ValueError('incomplete photo PNG')
    width, height, depth, color, compression, filtering, interlace = header
    if (not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > MAX_PIXELS
            or depth not in (8, 16) or color not in (0, 2, 4, 6) or compression or filtering or interlace):
        raise ValueError('photo PNG layout exceeds qualification')
    row = width * {0: 1, 2: 3, 4: 2, 6: 4}[color] * (depth // 8) + 1; expected = row * height
    decoder = zlib.decompressobj(); decoded = decoder.decompress(b''.join(chunks), expected + 1)
    if len(decoded) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or any(decoded[i] > 4 for i in range(0, expected, row)):
        raise ValueError('photo PNG scanlines are invalid')
    return {'width': width, 'height': height, 'bit_depth': depth, 'color_type': color,
            'scanlines_sha256': hashlib.sha256(decoded).hexdigest(), 'metadata_sha256': metadata.hexdigest()}


def native(root, check_dependencies=True):
    root = Path(root).resolve(); folder = root / 'native'; library = folder / 'library'
    admitted = {'objects.json', 'dependencies.json', 'library/catalog.snap', 'library/catalog.log', 'library/catalog.lock', 'library/view.json'}
    if folder.is_symlink() or library.is_symlink() or (root / 'assets').is_symlink():
        raise ValueError('photo directories must not be symlinks')
    for entry in folder.rglob('*'):
        if entry.is_symlink() or entry.is_file() and entry.relative_to(folder).as_posix() not in admitted:
            raise ValueError('native photo contains an external link or unsupported file')
        if not entry.is_dir() and not entry.is_file():
            raise ValueError('native photo requires regular files')
    # View state is not part of the admitted editable document. A supplied view
    # could browse arbitrary folders on open; exports select explicit photo IDs.
    view = library / 'view.json'
    if view.exists():
        state = read_json(view, 65536)
        if (not isinstance(state, dict) or set(state) - {'source', 'browse', 'library_folder', 'sort', 'selection'}
                or state.get('source') != {'kind': 'all'} or state.get('browse') is not None or state.get('library_folder') is not None):
            raise ValueError('native photo view references unsupported folders')
        view.unlink()
    journal = library / 'catalog.log'
    if journal.exists() and journal.stat().st_size:
        raise ValueError('native photo snapshot has an unreconciled journal')
    model = read_json(library / 'catalog.snap'); mapping = read_json(folder / 'objects.json', 65536)
    if (not isinstance(mapping, dict) or set(mapping) != {'bit_depth', 'photos'}
            or type(mapping['bit_depth']) is not int or mapping['bit_depth'] not in (8, 16)
            or not isinstance(mapping['photos'], dict) or not 1 <= len(mapping['photos']) <= 32):
        raise ValueError('invalid editable photo mapping')
    if (not isinstance(model, dict) or set(model) != {'format', 'version', 'seq', 'catalog'}
            or model['format'] != 'lightcraft-catalog' or type(model['version']) is not int or model['version'] != 13
            or not video.integer(model['seq'], 0, 10_000_000)):
        raise ValueError('unsupported native photo catalog')
    catalog = model['catalog']
    if (not isinstance(catalog, dict) or set(catalog) != {'photos', 'albums', 'next_photo', 'next_album', 'next_stack'}
            or catalog['albums'] != {} or not video.integer(catalog['next_album'], 1, 1) or not video.integer(catalog['next_stack'], 1, 1)
            or not isinstance(catalog['photos'], dict)):
        raise ValueError('unsupported native photo catalog structure')
    dependencies = {}; ids = set(); total = 0
    required = {'id', 'source', 'file_name', 'kind', 'format', 'width', 'height', 'file_size', 'captured', 'imported', 'meta',
                'rating', 'flag', 'label', 'develop', 'edited', 'versions', 'history', 'deleted', 'duration', 'as_shot_wb'}
    optional = {'content_hash', 'embedded_lens', 'preview_checked'}
    for name, item in mapping['photos'].items():
        if (not video.named(name) or not isinstance(item, dict) or set(item) != {'id', 'asset', 'format'}
                or not video.integer(item['id'], 1, 1_000_000) or item['id'] in ids
                or not isinstance(item['asset'], str) or not video.ASSET.fullmatch(item['asset'])
                or not isinstance(item['format'], str) or item['format'] not in FORMATS):
            raise ValueError('invalid native photo identity or source mapping')
        ids.add(item['id']); photo = catalog['photos'].get(str(item['id'])); location = 'assets/' + item['asset'] + '.' + item['format']
        if (not isinstance(photo, dict) or not required <= photo.keys() or set(photo) - required - optional
                or photo['id'] != item['id'] or photo['source'] != {'type': 'file', 'path': location}
                or photo['file_name'] != Path(location).name
                or photo['format'] != FORMATS[item['format']] or photo['kind'] != ('raw' if item['format'] == 'dng' else 'image')
                or photo['deleted'] is not False or photo['duration'] is not None
                or photo['rating'] != 0 or photo['flag'] != 'none' or photo['label'] is not None):
            raise ValueError('native photo mapping, media type or catalog record differs from its admitted contract')
        for dimension in ('width', 'height'):
            if not video.integer(photo[dimension], 1, 8192):
                raise ValueError('invalid native photo dimensions')
        if photo['width'] * photo['height'] > MAX_PIXELS:
            raise ValueError('native photo exceeds its pixel budget')
        info = source_info(root / location, item['format']); total += info['width'] * info['height']
        if location in dependencies or total > MAX_PIXELS:
            raise ValueError('photo sources are duplicated or exceed the aggregate pixel budget')
        dependencies[location] = info
        if photo['file_size'] != (root / location).stat().st_size:
            raise ValueError('native photo source size differs from its original')
        settings_valid(photo['develop'], item['format'] == 'dng')
        for key, fields in (('history', {'label', 'settings'}), ('versions', {'name', 'created', 'settings', 'auto'})):
            entries = photo[key]
            if not isinstance(entries, list) or len(entries) > 256:
                raise ValueError('native photo history exceeds its bounded revision contract')
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != fields:
                    raise ValueError('invalid native photo history record')
                settings_valid(entry['settings'], item['format'] == 'dng')
    if set(catalog['photos']) != {str(i) for i in ids} or not video.integer(catalog['next_photo'], max(ids) + 1, max(ids) + 1):
        raise ValueError('native photo identities do not match the editable mapping')
    present = set()
    for entry in (root / 'assets').rglob('*'):
        if entry.is_symlink() or not entry.is_file():
            raise ValueError('photo assets must be regular files without extra directories')
        present.add(entry.relative_to(root).as_posix())
    if present != set(dependencies):
        raise ValueError('photo project contains unreferenced sources or sidecars')
    if check_dependencies and read_json(folder / 'dependencies.json', 65536) != dependencies:
        raise ValueError('photo originals differ from their recorded content')
    return model, mapping, dependencies


def expected_settings(before, spec):
    result = copy.deepcopy(before)
    for control, value in spec.get('adjustments', {}).items():
        section, name = control.split('.'); result[section][name] = value
        if section == 'wb':
            result['wb']['mode'] = 'custom'
    if 'crop' in spec:
        result['crop']['geometry']['rect'] = dict(zip(('x0', 'y0', 'x1', 'y1'), spec['crop']))
    return result


def verify_edit(before, after, requests, mapping):
    old = before['catalog']['photos']; new = after['catalog']['photos']
    wanted = {str(mapping['photos'][spec['name']]['id']): spec for spec in requests}
    if set(old) != set(new) or {k: v for k, v in before['catalog'].items() if k != 'photos'} != {k: v for k, v in after['catalog'].items() if k != 'photos'}:
        raise ValueError('photo edit changed catalog identities or unrelated structure')
    for identity, original in old.items():
        current = new[identity]
        if identity not in wanted:
            if current != original:
                raise ValueError('photo edit changed an untargeted native photo')
            continue
        if current['develop'] != expected_settings(original['develop'], wanted[identity]):
            raise ValueError('native photo settings differ from the precise requested edit')
        for key in original.keys() - {'develop', 'history', 'versions', 'edited'}:
            if current.get(key) != original[key]:
                raise ValueError('photo edit changed an untargeted native field')
        for key, maximum in (('history', 2), ('versions', 1)):
            existing = original[key]; added = current[key][len(existing):]
            if current[key][:len(existing)] != existing or len(added) > maximum:
                raise ValueError('photo edit rewrote existing history or versions')
            if key == 'versions' and any(v.get('auto') is not True or v['settings'] != current['develop'] for v in added):
                raise ValueError('native photo automatic version differs from the requested result')


def export_all(e, root, mapping, prefix):
    results = {}
    for name, photo in mapping['photos'].items():
        output = root / 'exports' / (prefix + name + '.png')
        report = e.tool('export', {'id': photo['id'], 'path': str(output), 'format': 'png', 'longEdge': 0,
                                   'bitDepth': mapping['bit_depth'], 'colorSpace': 'srgb', 'metadata': 'none',
                                   'addToPhotos': False, 'sharpen': 'none', 'conflict': 'overwrite'})
        info = png_info(output)
        if (info['bit_depth'] != mapping['bit_depth'] or info['width'] != report.get('width')
                or info['height'] != report.get('height')):
            raise ValueError('native photo export metadata differs from the encoded output')
        results[name] = info
    return results


def execute(root, operation, params, *, executable=None):
    root = Path(root).resolve(); folder = root / 'native'; library = folder / 'library'; exports = root / 'exports'
    for directory in (folder, library, exports, root / 'assets', root / '.photo-config', root / '.photo-camera-profiles'):
        if directory.is_symlink() or directory.exists() and not directory.is_dir():
            raise ValueError('photo workspace directories must be real directories')
    folder.mkdir(exist_ok=True); library.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    old_outputs = {}; before = None
    if operation == 'photo.create':
        inputs = assets(operation, params)
        initial = {location: source_info(root / location, p['format']) for p in params['photos'] for location in [inputs[p['asset']]]}
        if sum(x['width'] * x['height'] for x in initial.values()) > MAX_PIXELS:
            raise ValueError('photo sources exceed the aggregate pixel budget')
        # Identical bytes would be deduplicated by the native importer. Fail
        # explicitly instead of pretending two requested identities were created.
        if len({x['sha256'] for x in initial.values()}) != len(initial):
            raise ValueError('photo creation requires distinct original content')
        mapping = {'bit_depth': params.get('bit_depth', 16), 'photos': {}}
        e = Engine(root, executable)
        try:
            for spec in params['photos']:
                location = inputs[spec['asset']]
                report = e.tool('import', {'paths': [location], 'mode': 'add'})
                if report.get('failed') or report.get('duplicates') or len(report.get('imported', [])) != 1:
                    raise ValueError('native photo import failed or deduplicated a requested source')
                mapping['photos'][spec['name']] = {'id': report['imported'][0], 'asset': spec['asset'], 'format': spec['format']}
        finally:
            e.close()
        model = read_json(library / 'catalog.snap')
        for item in mapping['photos'].values():
            photo = model['catalog']['photos'][str(item['id'])]; location = 'assets/' + item['asset'] + '.' + item['format']
            if photo['source'] != {'type': 'file', 'path': str(root / location)}:
                raise ValueError('native photo import returned an unexpected source path')
            photo['source']['path'] = location
        write_json(library / 'catalog.snap', model); write_json(folder / 'objects.json', mapping)
        before, mapping, dependencies = native(root, False)
        if dependencies != initial:
            raise ValueError('photo import changed an original source')
        write_json(folder / 'dependencies.json', dependencies)
    else:
        before, mapping, dependencies = native(root)
        if any(spec['name'] not in mapping['photos'] for spec in params['photos']):
            raise ValueError('photo edit names an unknown photo')
        if params.get('bit_depth', mapping['bit_depth']) == mapping['bit_depth']:
            old_outputs = {name: png_info(exports / (name + '.png')) for name in mapping['photos']}
        mapping['bit_depth'] = params.get('bit_depth', mapping['bit_depth'])
        write_json(folder / 'objects.json', mapping)
    e = Engine(root, executable)
    try:
        for spec in params['photos']:
            identity = mapping['photos'][spec['name']]['id']
            if 'adjustments' in spec:
                response = e.tool('set_develop', {'id': identity, 'values': spec['adjustments']})
                actual = {item['id']: item['value'] for item in response.get('controls', [])}
                if actual != spec['adjustments']:
                    raise ValueError('native photo control values differ from the requested values')
            if 'crop' in spec:
                e.tool('crop', {'id': identity, 'rect': spec['crop']})
        rendered = export_all(e, root, mapping, '')
    finally:
        e.close()
    after, current_mapping, current_dependencies = native(root)
    verify_edit(before, after, params['photos'], mapping)
    if mapping != current_mapping or dependencies != current_dependencies:
        raise ValueError('native photo revision changed original content or mapping')
    for name in mapping['photos'].keys() - {p['name'] for p in params['photos']}:
        if old_outputs and rendered[name] != old_outputs[name]:
            raise ValueError('photo revision changed untargeted export pixels')
    e = Engine(root, executable)
    try:
        reopened = export_all(e, root, mapping, 'reopened-')
    finally:
        e.close()
    final, final_mapping, final_dependencies = native(root)
    if rendered != reopened or final['catalog'] != after['catalog'] or final_mapping != mapping or final_dependencies != dependencies:
        raise ValueError('native photo cold reopen changed pixels, settings or original content')
    for name in mapping['photos']:
        (exports / ('reopened-' + name + '.png')).unlink()
    artifacts = [{'path': p.relative_to(root).as_posix(), 'role': 'native'} for p in sorted(folder.rglob('*'))
                 if p.is_file() and p.name not in ('catalog.lock', 'view.json')]
    artifacts += [{'path': location, 'role': 'asset'} for location in sorted(dependencies)]
    artifacts += [{'path': 'exports/' + name + '.png', 'role': 'export'} for name in mapping['photos']]
    return {'engine': {'name': 'lightcraft', 'version': VERSION}, 'artifacts': artifacts,
            'validation': {'passed': True, 'native_cold_reopen': True, 'source_hashes_preserved': True,
                           'pixel_roundtrip_equal': True, 'pixel_validation_precision': mapping['bit_depth'],
                           'editable_photo_ids_and_history_preserved': True, 'photos': rendered,
                           'raw_preview_fallback': False, 'general_camera_raw_fidelity_qualified': False}}


def observe(root, *, executable=None):
    """Observe and render an existing complete library without submitting an edit.

    Portable callers inspect a disposable copy and independently require exact
    native bytes. The complete snapshot includes all retained history/version
    settings; observing it does not imply a typed operation-history replay.
    """
    root = Path(root).resolve(); folder = root / 'native'; exports = root / 'exports'
    exports.mkdir(exist_ok=True)
    before, mapping, dependencies = native(root)
    rendered = None
    for prefix in ('', 'reopened-'):
        e = Engine(root, executable)
        try:
            current = export_all(e, root, mapping, prefix)
        finally:
            e.close()
        after, current_mapping, current_dependencies = native(root)
        if after != before or current_mapping != mapping or current_dependencies != dependencies:
            raise ValueError('Photo observation changed the complete native catalog, history or original content')
        if rendered is not None and current != rendered:
            raise ValueError('Photo cold observation changed full-precision pixels or PNG metadata')
        rendered = current
    for name in mapping['photos']:
        (exports / ('reopened-' + name + '.png')).unlink()
    artifacts = [{'path': p.relative_to(root).as_posix(), 'role': 'native'}
                 for p in sorted(folder.rglob('*')) if p.is_file() and p.name not in ('catalog.lock', 'view.json')]
    artifacts += [{'path': location, 'role': 'asset'} for location in sorted(dependencies)]
    artifacts += [{'path': 'exports/' + name + '.png', 'role': 'export'} for name in mapping['photos']]
    return {'engine': {'name': 'lightcraft', 'version': VERSION}, 'artifacts': artifacts,
            'validation': {'passed': True, 'native_cold_reopen': True, 'native_state_equal': True,
                           'source_hashes_preserved': True, 'pixel_roundtrip_equal': True,
                           'pixel_validation_precision': mapping['bit_depth'],
                           'editable_photo_ids_and_history_preserved': True, 'photos': rendered,
                           'raw_preview_fallback': False, 'general_camera_raw_fidelity_qualified': False}}
