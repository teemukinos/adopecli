"""Bounded Layout archive admission and precise rich-text change expectations.

Admission never extracts files or resolves links. Native import still requires
engine preflight, complete state comparison and cold reopening by its caller.
These helpers do not register a production operation on their own.
"""
import copy
import base64
import binascii
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
import zlib

MAX_ARCHIVE = 128 << 20
MAX_JSON = 8 << 20
MAX_ASSET = 64 << 20
MAX_ENTRIES = 1024
MAX_PAGES = 64
MAX_PIXELS = 128_000_000
MAX_TEXT = 1 << 20
MIME = b'application/vnd.designcraft+zip'


def strict_json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Layout JSON contains a duplicate key')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('Layout JSON contains a nonfinite number')

    if len(data) > MAX_JSON:
        raise ValueError('Layout JSON exceeds 8 MiB')
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
    except (RecursionError, UnicodeError) as error:
        raise ValueError('Layout JSON is invalid or nested too deeply') from error
    pending = [(value, 0)]; count = 0
    while pending:
        node, depth = pending.pop(); count += 1
        if depth > 64 or count > 200_000:
            raise ValueError('Layout JSON exceeds its structural budget')
        if isinstance(node, dict):
            pending.extend((key, depth + 1) for key in node)
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)
        elif isinstance(node, str):
            if any(0xd800 <= ord(c) <= 0xdfff for c in node):
                raise ValueError('Layout JSON contains invalid Unicode')
        elif type(node) in (int, float) and (abs(node) > 2**64 - 1 or not math.isfinite(node)):
            raise ValueError('Layout JSON contains an unsupported numeric magnitude')
    return value


def archive_entries(path):
    """Read bounded regular ZIP entries, validating CRCs without extraction."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Layout archive requires a regular file of at most 128 MiB')
    entries = {}; total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= MAX_ENTRIES:
                raise ValueError('Layout archive exceeds its entry budget')
            for info in infos:
                name = info.filename
                mode = info.external_attr >> 16
                if (name != info.orig_filename or not name or len(name) > 512
                        or name.startswith('/') or '\\' in name or ':' in name
                        or any(part in ('', '.', '..') for part in name.split('/'))
                        or any(ord(c) < 32 for c in name) or name in entries
                        or info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError('Layout archive contains an ambiguous or unsupported entry')
                limit = MAX_JSON if name.endswith(('.json', '.xml')) else MAX_ASSET
                if info.file_size > limit or total + info.file_size > MAX_ARCHIVE:
                    raise ValueError('Layout archive expansion exceeds its budget')
                with archive.open(info) as stream:
                    data = stream.read(min(limit, MAX_ARCHIVE - total) + 1)
                if len(data) != info.file_size or len(data) > limit or total + len(data) > MAX_ARCHIVE:
                    raise ValueError('Layout archive entry has an invalid expanded length')
                total += len(data); entries[name] = data
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as error:
        raise ValueError('Layout archive is invalid or unsupported') from error
    return entries


def raster_info(data, mime):
    """Inspect and decode bounded embedded raster bytes before native rendering."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (image.format != {'image/png': 'PNG', 'image/jpeg': 'JPEG'}.get(mime)
                    or not 1 <= image.width <= 8192 or not 1 <= image.height <= 8192
                    or image.width * image.height > 32_000_000 or getattr(image, 'n_frames', 1) != 1):
                raise ValueError('Layout embedded artwork requires a bounded single-frame PNG or JPEG')
            size = list(image.size)
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return size
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError('Layout embedded raster cannot be decoded') from error


def story_check(story):
    if not isinstance(story, dict) or not isinstance(story.get('text'), str):
        raise ValueError('Layout story requires text')
    data = story['text'].encode('utf-8')
    if len(data) > MAX_TEXT:
        raise ValueError('Layout story exceeds its text budget')
    runs = story.get('chars'); paragraphs = story.get('paras')
    if (not isinstance(runs, list) or not 1 <= len(runs) <= 10000
            or not isinstance(paragraphs, list) or len(paragraphs) != story['text'].count('\n') + 1):
        raise ValueError('Layout story has invalid character or paragraph runs')
    position = 0
    for run in runs:
        if (not isinstance(run, dict) or type(run.get('len')) is not int
                or run['len'] < (1 if data else 0) or run['len'] > len(data)):
            raise ValueError('Layout character run has an invalid byte length')
        end = position + run['len']
        try:
            data[position:end].decode('utf-8')
        except UnicodeError as error:
            raise ValueError('Layout character run splits a Unicode character') from error
        position = end
    if position != len(data):
        raise ValueError('Layout character runs do not cover their story')
    return len(data)


def read_native(path):
    """Admit native bytes and return complete document state and asset hashes.

    Raster placement is qualified here. PDF/SVG placement and native format
    upgrades need their own admission and preservation evidence before use.
    """
    entries = archive_entries(path)
    if entries.get('mimetype') != MIME or not {'meta.json', 'document.json'} <= entries.keys():
        raise ValueError('Layout requires a native DesignCraft archive')
    meta = strict_json(entries['meta.json'])
    if (not isinstance(meta, dict) or meta.get('format') != 'designcraft'
            or type(meta.get('version')) is not int or not 2 <= meta['version'] <= 4):
        raise ValueError('Layout native format requires an unsupported upgrade or version')
    document = strict_json(entries['document.json'])
    if not isinstance(document, dict):
        raise ValueError('Layout native document must be an object')
    spreads = document.get('spreads'); parents = document.get('parents', [])
    stories = document.get('stories'); assets = document.get('assets')
    if (not isinstance(spreads, list) or not 1 <= len(spreads) <= MAX_PAGES
            or not isinstance(parents, list) or len(parents) > MAX_PAGES
            or not isinstance(stories, dict) or len(stories) > 512
            or not isinstance(assets, dict) or len(assets) > 512):
        raise ValueError('Layout document exceeds its spread, story or asset budget')
    pages = []; items = 0; parent_pages = 0; raster_pixels = 0
    for is_parent, collection in ((False, spreads), (True, parents)):
        for spread in collection:
            if (not isinstance(spread, dict) or not isinstance(spread.get('pages'), list)
                    or not isinstance(spread.get('items'), list)):
                raise ValueError('Layout spread requires pages and items')
            items += len(spread['items'])
            for page in spread['pages']:
                if (not isinstance(page, dict) or type(page.get('id')) is not int or page['id'] < 1
                        or any(type(page.get(k)) not in (int, float) or not 1 <= page[k] <= 8192 for k in ('width', 'height'))):
                    raise ValueError('Layout page has unsupported dimensions')
                if is_parent:
                    parent_pages += 1
                else:
                    pages.append({'id': page['id'], 'width': page['width'], 'height': page['height']})
                raster_pixels += math.ceil(page['width']) * math.ceil(page['height'])
    if not 1 <= len(pages) <= MAX_PAGES or parent_pages > MAX_PAGES or items > 512 or raster_pixels > MAX_PIXELS:
        raise ValueError('Layout page rendering or frame count exceeds its budget')
    # Count nested groups, anchored objects, notes and table-cell stories too.
    # Native preflight does not walk every one of these placements.
    pending = [document]; all_stories = []; all_items = 0
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if {'text', 'chars', 'paras'} <= value.keys():
                all_stories.append(value)
            if {'id', 'shape', 'path', 'content'} <= value.keys():
                all_items += 1
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    if len(all_stories) > 512 or all_items > 512:
        raise ValueError('Layout nested stories or frames exceed their budget')
    for story in stories.values():
        story_check(story)
    text_bytes = sum(story_check(story) for story in all_stories)
    if text_bytes > MAX_TEXT:
        raise ValueError('Layout publication exceeds its total text budget')
    blobs = {}; embedded_pixels = 0
    for name, data in entries.items():
        if name in ('mimetype', 'meta.json', 'document.json', 'preview.png'):
            continue
        match = re.fullmatch(r'assets/([1-9][0-9]*)\.(png|jpg|jpeg)', name)
        if not match or match[1] not in assets or match[1] in blobs:
            raise ValueError('Layout archive contains an unsupported or ambiguous asset entry')
        record = assets[match[1]]
        if not isinstance(record, dict) or str(record.get('id')) != match[1] or record.get('link') is not None:
            raise ValueError('Layout assets must be embedded with matching identities and no external links')
        if record.get('mime') not in ('image/png', 'image/jpeg'):
            raise ValueError('Layout embedded asset type requires additional qualification')
        dimensions = raster_info(data, record['mime'])
        if record.get('pixels') != dimensions:
            raise ValueError('Layout asset dimensions disagree with its embedded bytes')
        embedded_pixels += dimensions[0] * dimensions[1]
        if embedded_pixels > MAX_PIXELS:
            raise ValueError('Layout embedded artwork exceeds its aggregate pixel budget')
        blobs[match[1]] = hashlib.sha256(data).hexdigest()
    if set(blobs) != set(assets):
        raise ValueError('Layout native archive has missing embedded assets')
    return {'document': document, 'assets': blobs, 'pages': pages,
            'format_version': meta['version'], 'text_bytes': text_bytes}


def read_idml(path):
    """Bound IDML XML and embedded artwork before handing bytes to the engine.

    This establishes resource bounds and self-contained dependencies, not
    semantic import fidelity. Native import warnings and preservation checks
    remain mandatory. Embedded PDF/EPS and external linked artwork are not yet
    admitted; their formats need separate production qualification.
    """
    entries = archive_entries(path)
    if (entries.get('mimetype') != b'application/vnd.adobe.indesign-idml-package'
            or 'designmap.xml' not in entries):
        raise ValueError('Layout requires an IDML publication archive')
    names = set(); parts = {}; budget = {'nodes': 0, 'text': 0}

    class Builder(ET.TreeBuilder):
        def __init__(self):
            super().__init__(); self.depth = 0

        def doctype(self, name, pubid, system):
            raise ValueError('Layout IDML must not contain DTDs or entity declarations')

        def start(self, tag, attrs):
            self.depth += 1; budget['nodes'] += 1
            if self.depth > 64 or budget['nodes'] > 200_000:
                raise ValueError('Layout IDML exceeds its XML structure budget')
            if len(attrs) > 256 or any(len(k) + len(v) > MAX_TEXT for k, v in attrs.items()):
                raise ValueError('Layout IDML attribute exceeds its budget')
            return super().start(tag, attrs)

        def end(self, tag):
            self.depth -= 1
            return super().end(tag)

    for name, data in entries.items():
        # The native reader has a lenient case/percent-decoding lookup. Disallow
        # aliases here so two entries cannot acquire the same native identity.
        if '%' in name or name.casefold() in names:
            raise ValueError('Layout IDML package has ambiguous part names')
        names.add(name.casefold())
        if name == 'mimetype':
            continue
        if not name.endswith('.xml'):
            raise ValueError('Layout IDML requires embedded artwork inside XML parts')
        try:
            parts[name] = ET.fromstring(data, parser=ET.XMLParser(target=Builder()))
        except ET.ParseError as error:
            raise ValueError('Layout IDML contains invalid XML') from error
    page_count = 0; frame_count = 0; pixels = 0; embedded_pixels = 0; embedded = []
    local = lambda tag: tag.rsplit('}', 1)[-1]
    for name, tree in parts.items():
        parents = {child: parent for parent in tree.iter() for child in parent}
        for node in tree.iter():
            kind = local(node.tag)
            for key, value in node.attrib.items():
                if local(key) == 'src' and value not in parts:
                    raise ValueError('Layout IDML references an absent or external package part')
            if kind == 'Content':
                budget['text'] += len(''.join(node.itertext()).encode('utf-8'))
                if budget['text'] > MAX_TEXT:
                    raise ValueError('Layout IDML story text exceeds its budget')
            if kind == 'Page':
                try:
                    box = [float(v) for v in node.attrib['GeometricBounds'].split()]
                except (KeyError, ValueError) as error:
                    raise ValueError('Layout IDML page lacks valid geometric bounds') from error
                if (len(box) != 4 or any(not math.isfinite(v) or abs(v) > 16384 for v in box)
                        or not 1 <= box[2] - box[0] <= 8192 or not 1 <= box[3] - box[1] <= 8192):
                    raise ValueError('Layout IDML page exceeds its dimensional budget')
                pixels += math.ceil(box[2] - box[0]) * math.ceil(box[3] - box[1])
                if name.startswith('Spreads/'):
                    page_count += 1
            if kind in ('TextFrame', 'Rectangle', 'Oval', 'Polygon', 'GraphicLine', 'Group'):
                frame_count += 1
            if kind in ('PDF', 'EPS', 'PICT', 'WMF', 'Movie', 'Sound'):
                raise ValueError('Layout IDML placed media requires additional qualification')
            if kind == 'Link':
                parent = parents.get(node)
                contents = [] if parent is None else [n for n in parent.iter() if local(n.tag) == 'Contents']
                if (parent is None or local(parent.tag) != 'Image' or node.get('StoredState') != 'Embedded'
                        or len(contents) != 1):
                    raise ValueError('Layout IDML artwork must be embedded in its image element')
            if kind == 'Image':
                contents = [n for n in node.iter() if local(n.tag) == 'Contents']
                if len(contents) != 1:
                    raise ValueError('Layout IDML image lacks unambiguous embedded bytes')
                try:
                    raw = base64.b64decode(''.join(''.join(contents[0].itertext()).split()), validate=True)
                except (ValueError, binascii.Error) as error:
                    raise ValueError('Layout IDML embedded image has invalid base64') from error
                mime = 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else None
                if mime is None or len(raw) > MAX_ASSET:
                    raise ValueError('Layout IDML embedded artwork requires bounded PNG or JPEG bytes')
                size = raster_info(raw, mime); embedded_pixels += size[0] * size[1]
                embedded.append({'sha256': hashlib.sha256(raw).hexdigest(), 'pixels': size, 'mime': mime})
    if not 1 <= page_count <= MAX_PAGES or frame_count > 512 or pixels > MAX_PIXELS or embedded_pixels > MAX_PIXELS:
        raise ValueError('Layout IDML exceeds its page, frame or pixel budget')
    return {'parts': {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()},
            'pages': page_count, 'frames': frame_count, 'embedded': embedded, 'text_bytes': budget['text']}


def replaced_story(story, start, end, expected, replacement):
    """Predict an exact UTF-8 range edit, retaining all unrelated formatting.

    Ordinary rich text and paragraphs are supported. Stories containing native
    table/anchor/note markers require a separate structural edit contract.
    The caller compares this whole object with the native engine's saved result.
    """
    story_check(story)
    if not isinstance(expected, str) or not isinstance(replacement, str):
        raise ValueError('Layout text revision requires expected and replacement text')
    data = story['text'].encode('utf-8')
    if (type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(data)
            or not start < end and not replacement):
        raise ValueError('Layout text revision requires a nonempty valid byte range or insertion')
    try:
        prefix = data[:start].decode('utf-8'); removed = data[start:end].decode('utf-8')
        suffix = data[end:].decode('utf-8'); inserted = replacement.encode('utf-8')
    except UnicodeError as error:
        raise ValueError('Layout text revision splits a Unicode character') from error
    if removed != expected:
        raise ValueError('Layout text revision does not match its expected source text')
    if any(0xe000 <= ord(c) <= 0xf8ff for c in story['text'] + replacement):
        raise ValueError('Layout native text markers require a structural edit operation')
    if len(data) - (end - start) + len(inserted) > MAX_TEXT:
        raise ValueError('Layout revised story exceeds its text budget')
    if type(story.get('rev')) is not int or not 0 <= story['rev'] <= 2**64 - 3:
        raise ValueError('Layout story revision counter is invalid')
    result = copy.deepcopy(story)
    segments = []; cursor = 0
    for run in story['chars']:
        length = run['len']; formatting = {k: copy.deepcopy(v) for k, v in run.items() if k != 'len'}
        segments.append((cursor, cursor + length, formatting)); cursor += length
    # Replacing characters takes the first removed character's format. Typing
    # at a run boundary takes the preceding format, except an empty paragraph.
    after = start < end or data[start:start + 1] == b'\n' and start > 0 and data[start - 1:start] == b'\n'
    chosen = next((fmt for a, b, fmt in segments if a <= start < b), segments[-1][2]) if after else next(
        (fmt for a, b, fmt in segments if a < start <= b or start == a == 0), segments[-1][2])
    typing = next((fmt for a, b, fmt in segments if a < start <= b or start == a == 0), segments[-1][2])
    runs = []

    def append(length, formatting):
        if not length:
            return
        if runs and {k: v for k, v in runs[-1].items() if k != 'len'} == formatting:
            runs[-1]['len'] += length
        else:
            runs.append({'len': length, **copy.deepcopy(formatting)})

    for a, b, fmt in segments:
        append(max(0, min(b, start) - a), fmt)
    append(len(inserted), chosen)
    for a, b, fmt in segments:
        append(max(0, b - max(a, end)), fmt)
    result['chars'] = runs or [{'len': 0, **typing}]
    result['text'] = prefix + replacement + suffix
    paragraph = prefix.count('\n')
    del result['paras'][paragraph + 1:paragraph + 1 + removed.count('\n')]
    result['paras'][paragraph + 1:paragraph + 1] = [copy.deepcopy(result['paras'][paragraph]) for _ in range(replacement.count('\n'))]
    result['rev'] += int(start < end) + int(bool(replacement))
    story_check(result)
    return result
