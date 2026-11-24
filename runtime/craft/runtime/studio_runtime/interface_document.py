"""Bounded native Interface admission, without extracting or rewriting documents.

The caller must still reject native repair/import warnings, verify requested
fonts, compare complete saved state and reopen the result in a fresh engine.
This module alone does not register a supported production operation.
"""
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
import zipfile
import zlib

MAX_ARCHIVE = 128 << 20
MAX_JSON = 8 << 20
MAX_ASSET = 32 << 20
MAX_NODES = 2048
MAX_PAGES = 64
MAX_TEXT = 1 << 20
MAX_PIXELS = 128_000_000
TYPES = frozenset(('page', 'frame', 'group', 'section', 'rectangle', 'ellipse',
                   'polygon', 'star', 'line', 'vector', 'text', 'booleanOp',
                   'component', 'componentSet', 'instance', 'slice'))
IDENTITY = [1, 0, 0, 1, 0, 0]


def number(value, low, high):
    return type(value) in (int, float) and low <= value <= high and math.isfinite(value)


def strict_json(data, *, max_items=200_000):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Interface JSON contains duplicate keys')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('Interface JSON contains nonfinite numbers')

    if isinstance(data, str):
        try:
            data = data.encode('utf-8')
        except UnicodeError as error:
            raise ValueError('Interface JSON contains invalid Unicode') from error
    if not isinstance(data, bytes) or len(data) > MAX_JSON:
        raise ValueError('Interface JSON exceeds 8 MiB')
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
    except (RecursionError, UnicodeError) as error:
        raise ValueError('Interface JSON is invalid or nested too deeply') from error
    pending = [(value, 0)]; count = 0
    while pending:
        item, depth = pending.pop(); count += 1
        if depth > 64 or count > max_items:
            raise ValueError('Interface JSON exceeds its structural budget')
        if isinstance(item, dict):
            pending.extend((v, depth + 1) for v in item.values())
            pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, str):
            if any(0xd800 <= ord(c) <= 0xdfff for c in item):
                raise ValueError('Interface JSON contains invalid Unicode')
        elif type(item) in (int, float) and not number(item, -(2**64 - 1), 2**64 - 1):
            raise ValueError('Interface JSON contains unsupported numeric magnitudes')
    return value


def archive_entries(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Interface input requires a regular ZIP file of at most 128 MiB')
    result = {}; total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= 1024:
                raise ValueError('Interface archive exceeds its entry budget')
            for info in infos:
                name = info.filename
                if (not name or name != info.orig_filename or len(name) > 256 or name.startswith('/')
                        or '\\' in name or ':' in name or any(ord(c) < 32 for c in name)
                        or any(part in ('', '.', '..') for part in name.split('/')) or name in result
                        or info.is_dir() or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                        or info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError('Interface archive contains an ambiguous or unsupported entry')
                limit = MAX_JSON if name.endswith('.json') else MAX_ASSET
                if info.file_size > limit or total + info.file_size > MAX_ARCHIVE:
                    raise ValueError('Interface archive expansion exceeds its budget')
                with archive.open(info) as stream:
                    data = stream.read(limit + 1)
                if len(data) != info.file_size or len(data) > limit:
                    raise ValueError('Interface archive member size is inconsistent')
                result[name] = data; total += len(data)
    except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error, NotImplementedError) as error:
        raise ValueError('Interface archive cannot be read') from error
    return result


def raster_info(data):
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (image.format not in ('PNG', 'JPEG') or not 1 <= image.width <= 8192
                    or not 1 <= image.height <= 8192 or image.width * image.height > 32_000_000
                    or getattr(image, 'n_frames', 1) != 1):
                raise ValueError('Interface artwork requires bounded single-frame PNG or JPEG data')
            size = list(image.size); image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return size
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError('Interface artwork cannot be decoded') from error


def compose(a, b):
    return [a[0]*b[0] + a[2]*b[1], a[1]*b[0] + a[3]*b[1],
            a[0]*b[2] + a[2]*b[3], a[1]*b[2] + a[3]*b[3],
            a[0]*b[4] + a[2]*b[5] + a[4], a[1]*b[4] + a[3]*b[5] + a[5]]


def graph(document):
    nodes = document.get('nodes'); pages = document.get('pages')
    if (not isinstance(nodes, dict) or not 1 <= len(nodes) <= MAX_NODES
            or not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES
            or any(type(p) is not int for p in pages) or len(set(pages)) != len(pages)):
        raise ValueError('Interface document exceeds its page or node budget')
    for key, node in nodes.items():
        if (not isinstance(node, dict) or type(node.get('id')) is not int or node['id'] < 1
                or key != str(node['id']) or not isinstance(node.get('type'), str) or node['type'] not in TYPES):
            raise ValueError('Interface node identity or type is invalid')
        if node.get('parent') is not None and type(node['parent']) is not int:
            raise ValueError('Interface parent must be a node ID')
        children = node.get('children', [])
        if (not isinstance(children, list) or any(type(i) is not int for i in children)
                or len(set(children)) != len(children)):
            raise ValueError('Interface node children must be unique IDs')
        if node['type'] in ('star', 'polygon') and not (type(node.get('count')) is int and 3 <= node['count'] <= 1000):
            raise ValueError('Interface polygon exceeds its side budget')
        if node['type'] == 'instance':
            component = node.get('component')
            main = nodes.get(str(component))
            if type(component) is not int or not isinstance(main, dict) or main.get('type') not in ('component', 'componentSet'):
                raise ValueError('Interface instance has no native component')
        source = node.get('source')
        if source is not None and (type(source) is not int or str(source) not in nodes):
            raise ValueError('Interface instance source is missing')
        if node['type'] == 'text' and (not isinstance(node.get('style'), dict)
                                     or not {'font_family', 'font_style', 'font_size'} <= node['style'].keys()):
            raise ValueError('Interface text requires explicit native typography')
    seen = set(); pending = [(p, None, IDENTITY, 0) for p in pages]; pixels = 0
    while pending:
        node_id, parent, transform, depth = pending.pop()
        node = nodes.get(str(node_id))
        if (node is None or node_id in seen or depth > 32 or node.get('parent') != parent
                or (node['type'] == 'page') != (parent is None)):
            raise ValueError('Interface tree is cyclic, detached or has inconsistent parents')
        seen.add(node_id)
        own = node.get('transform', IDENTITY)
        if (not isinstance(own, list) or len(own) != 6
                or not all(number(v, -64, 64) for v in own[:4])
                or not all(number(v, -32768, 32768) for v in own[4:])):
            raise ValueError('Interface node transform exceeds its budget')
        world = compose(transform, own)
        width = node.get('width'); height = node.get('height')
        if not number(width, 0, 8192) or not number(height, 0, 8192):
            raise ValueError('Interface node dimensions exceed their budget')
        corners = [(world[0]*x + world[2]*y + world[4], world[1]*x + world[3]*y + world[5])
                   for x, y in ((0, 0), (width, 0), (width, height), (0, height))]
        if any(not number(v, -32768, 32768) for point in corners for v in point):
            raise ValueError('Interface transformed bounds exceed their budget')
        pixels += math.ceil(max(x for x, _ in corners) - min(x for x, _ in corners)) * math.ceil(max(y for _, y in corners) - min(y for _, y in corners))
        if pixels > MAX_PIXELS:
            raise ValueError('Interface document exceeds its rendering budget')
        pending.extend((child, node_id, world, depth + 1) for child in node.get('children', []))
    if len(seen) != len(nodes):
        raise ValueError('Interface document contains detached nodes')
    # A valid parent tree can still contain a component that instantiates itself.
    # Follow component dependencies as well before the native engine expands them.
    active = set(); done = set(); pending = [(p, False) for p in pages]
    while pending:
        node_id, leave = pending.pop()
        if leave:
            active.remove(node_id); done.add(node_id); continue
        if node_id in active:
            raise ValueError('Interface components contain recursive dependencies')
        if node_id in done:
            continue
        active.add(node_id)
        if len(active) > 64:
            raise ValueError('Interface component nesting exceeds its budget')
        node = nodes[str(node_id)]; edges = list(node.get('children', []))
        if node['type'] == 'instance':
            edges.append(node['component'])
        pending.append((node_id, True)); pending.extend((i, False) for i in edges)
    return nodes, pages


def read_native(path):
    entries = archive_entries(path)
    if 'document.json' not in entries:
        raise ValueError('Interface archive has no native document')
    document = strict_json(entries['document.json'])
    if (not isinstance(document, dict) or document.get('format') != 'figcraft'
            or type(document.get('version')) is not int or document['version'] != 1):
        raise ValueError('Interface requires native format version 1')
    if not isinstance(document.get('name'), str) or not 1 <= len(document['name']) <= 1000:
        raise ValueError('Interface document requires a bounded name')
    libraries = document.get('libraries', {})
    if not isinstance(libraries, dict) or any(libraries.values()):
        raise ValueError('Interface linked or published libraries require separate qualification')
    nodes, pages = graph(document)
    if type(document.get('current_page')) is not int or document['current_page'] not in pages:
        raise ValueError('Interface current page is missing')
    index = document.get('imageIndex', [])
    if not isinstance(index, list) or len(index) > 512:
        raise ValueError('Interface image index exceeds its budget')
    assets = {}; pixels = 0
    for record in index:
        if (not isinstance(record, dict) or set(record) != {'hash', 'width', 'height'}
                or not isinstance(record['hash'], str) or not re.fullmatch('[0-9a-f]{64}', record['hash'])
                or record['hash'] in assets or type(record['width']) is not int or type(record['height']) is not int):
            raise ValueError('Interface artwork requires unique content hashes and dimensions')
        key = record['hash']; data = entries.get('images/' + key)
        if data is None or hashlib.sha256(data).hexdigest() != key:
            raise ValueError('Interface embedded artwork is missing or its hash differs')
        size = raster_info(data)
        if size != [record['width'], record['height']]:
            raise ValueError('Interface embedded artwork dimensions disagree with its index')
        assets[key] = key; pixels += size[0] * size[1]
    if set(entries) - {'document.json', 'thumbnail.png'} - {'images/' + key for key in assets}:
        raise ValueError('Interface archive history, branches or other entries need separate qualification')
    if 'thumbnail.png' in entries:
        if not entries['thumbnail.png'].startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Interface thumbnail must contain PNG data')
        size = raster_info(entries['thumbnail.png']); pixels += size[0] * size[1]
    if pixels > MAX_PIXELS:
        raise ValueError('Interface decoded artwork exceeds its pixel budget')
    text_bytes = 0; fonts = set()
    for node in nodes.values():
        if node['type'] != 'text':
            continue
        characters = node.get('characters')
        if not isinstance(characters, str):
            raise ValueError('Interface text must be Unicode')
        text_bytes += len(characters.encode('utf-8'))
        runs = node.get('runs', [])
        if not isinstance(runs, list) or len(runs) > 10000:
            raise ValueError('Interface text runs exceed their budget')
        end = 0
        for run in runs:
            if (not isinstance(run, dict) or type(run.get('start')) is not int or type(run.get('end')) is not int
                    or not end <= run['start'] < run['end'] <= len(characters) or not isinstance(run.get('style'), dict)
                    or not {'font_family', 'font_style', 'font_size'} <= run['style'].keys()):
                raise ValueError('Interface styled runs need ordered character ranges and explicit typography')
            end = run['end']
    pending = [document]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if item.get('type') == 'image' and (not isinstance(item.get('image'), str) or item['image'] not in assets):
                raise ValueError('Interface image paint references missing artwork')
            if item.get('type') == 'pattern':
                raise ValueError('Interface repeating pattern paints require separate qualification')
            if {'font_family', 'font_style', 'font_size'} <= item.keys():
                family = item['font_family']; style = item.get('font_style', 'Regular')
                if not all(isinstance(v, str) and 1 <= len(v) <= 128 for v in (family, style)):
                    raise ValueError('Interface font family and style must be explicit names')
                if not number(item.get('font_size', 16), 1, 500):
                    raise ValueError('Interface font size exceeds its budget')
                fonts.add((family, style))
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if text_bytes > MAX_TEXT:
        raise ValueError('Interface document exceeds its text budget')
    return {'document': document, 'nodes': nodes, 'pages': pages, 'assets': assets,
            'fonts': sorted(fonts), 'entries': entries}


def require_state(profile, expected_document, expected_assets):
    """Reject silent repairs, dropped fields or unrelated changes after saving."""
    if profile['document'] != expected_document or profile['assets'] != expected_assets:
        raise ValueError('Interface native state differs from the complete expected document or artwork')
