"""Validate actual shaped fonts, not just the existence of requested families."""
import json
from pathlib import Path
import re
import zipfile

from . import photo

FACES = {('Inter', 400): 'Inter-Regular.ttf', ('Inter', 500): 'Inter-Medium.ttf',
         ('Inter', 600): 'Inter-SemiBold.ttf', ('JetBrains Mono', 400): 'JetBrainsMono-Regular.ttf'}
HASH = re.compile(r'[0-9a-f]{64}')


def text_layers(document):
    with zipfile.ZipFile(document) as archive:
        entry = archive.getinfo('manifest.json')
        if entry.file_size > 8 << 20:
            raise ValueError('native font inspection exceeds manifest budget')
        manifest = json.loads(archive.read(entry))
    if manifest.get('format_version') != 1:
        raise ValueError('unsupported native font inspection format')
    stack = [(layer, 0) for layer in manifest['document']['layers']]
    texts = []
    seen = set()
    while stack:
        layer, depth = stack.pop()
        ident = layer.get('id')
        if type(ident) is not int or ident <= 0 or ident in seen or depth > 64 or len(seen) >= 1000:
            raise ValueError('native font inspection has invalid or excessive layers')
        seen.add(ident)
        content = layer['content']
        if content['kind'] == 'group':
            stack.extend((child, depth + 1) for child in content['children'])
        elif content['kind'] == 'text':
            if len(texts) >= 200:
                raise ValueError('native font inspection exceeds 200 text layers')
            texts.append((ident, content['text']))
    return sorted(texts)


def validate_info(info, ident, text):
    d = info.get('fontDiagnostics', {})
    if (info.get('layer') != ident or info.get('text') != text or d.get('schema') != 1
            or d.get('scope') != 'shaped-glyphs' or d.get('rangeUnit') != 'utf8-bytes'):
        raise ValueError('image engine does not provide matching shaped-font diagnostics')
    if type(d.get('missingGlyphCount')) is not int or d['missingGlyphCount'] != 0:
        raise ValueError('text contains missing glyphs; choose a supported font or revise the text')
    bundled = {item['name']: item['fontBlake3'] for item in d.get('bundledFonts', [])
               if item.get('collectionIndex') == 0 and isinstance(item.get('fontBlake3'), str)
               and HASH.fullmatch(item['fontBlake3'])}
    if set(bundled) != set(FACES.values()):
        raise ValueError('image engine has an incomplete bundled-font identity table')
    faces = d.get('faces'); glyphs = d.get('glyphs'); runs = info.get('runs')
    if not isinstance(faces, list) or not isinstance(glyphs, list) or not isinstance(runs, list):
        raise ValueError('image engine returned incomplete glyph records')
    raw = text.encode('utf-8')
    if len(raw) > 1 << 20 or d.get('sourceBytes') != len(raw) or len(glyphs) > 65536 or len(faces) > 256:
        raise ValueError('image engine returned inconsistent glyph dimensions')
    boundaries = {i for i, byte in enumerate(raw) if byte & 0xc0 != 0x80} | {len(raw)}
    for glyph in glyphs:
        face_index, style_index = glyph.get('face'), glyph.get('style')
        start, end = glyph.get('sourceByteStart'), glyph.get('sourceByteEnd')
        if (type(face_index) is not int or not 0 <= face_index < len(faces)
                or type(style_index) is not int or not 0 <= style_index < len(runs)
                or type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(raw)
                or start not in boundaries or end not in boundaries
                or type(glyph.get('glyphId')) is not int or glyph['glyphId'] <= 0):
            raise ValueError('image engine returned invalid glyph references')
        style = runs[style_index]['style']; face = faces[face_index]
        expected = FACES.get((style.get('font_family'), style.get('weight')))
        if (expected is None or face.get('fontBlake3') != bundled[expected]
                or face.get('collectionIndex') != 0 or face.get('variationCoordsF2Dot14') != []
                or face.get('syntheticBold') is not False or face.get('syntheticSkewDegrees') != 0
                or style.get('italic') or style.get('variations')):
            raise ValueError('text requires an unqualified font face or fallback; no silent substitution is allowed')
    return {'layer': ident, 'diagnostics': d}


def inspect(document):
    if photo.engine() != 'dobe-image':
        return None
    texts = text_layers(document)
    if sum(len(text) for _, text in texts) > 65536:
        raise ValueError('native font inspection exceeds the total text budget')
    records = []
    if texts:
        args = ['photocraft-cli', 'run', '--no-gpu', str(document)]
        for ident, _ in texts:
            args += ['--cmd', 'type.info', '--params', json.dumps({'layer': ident, 'fontDiagnostics': True})]
        output = photo.run(args)
        rows = [json.loads(line) for line in output.splitlines() if line.strip()]
        if len(rows) != len(texts) or any(row.get('command') != 'type.info' for row in rows):
            raise ValueError('image engine returned an incomplete font inspection')
        for row, (ident, text) in zip(rows, texts):
            records.append(validate_info(row['result'], ident, text))
        if sum(len(record['diagnostics']['glyphs']) for record in records) > 65536:
            raise ValueError('native font inspection exceeds the total glyph budget')
    return {'schema_version': 1, 'source': 'actual shaped font bytes', 'scope': 'shaped_glyphs_in_native_text_layers',
            'embedded_asset_fonts': 'not inspected', 'glyph_coverage_verified': True, 'layers': records}


def write(document, destination):
    result = inspect(document)
    if result is not None:
        Path(destination).write_text(json.dumps(result, sort_keys=True) + '\n')
    return result
