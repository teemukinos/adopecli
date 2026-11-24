"""Verify private native glyph traces against caller-owned, independently parsed fonts.

This observes actual display-list selection. It does not independently reproduce
shaping, authorize font embedding, or admit documents for native execution.
"""
import hashlib
import math

from .write_container import require, strict_json
from .write_fonts import character_maps, inspect as inspect_font


def keys(value, expected, label):
    require(type(value) is dict and set(value) == set(expected.split()), 'glyph trace '+label+' has unknown or missing fields')


def integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, 'glyph trace '+label+' is outside its integer bounds')


def number(value, minimum, maximum, label):
    require(type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum,
            'glyph trace '+label+' is outside its numeric bounds')


def vector(value, count, label):
    require(type(value) is list and len(value) == count, 'glyph trace '+label+' has wrong dimensions')
    for n in value: number(n, -10_000_000, 10_000_000, label)


def inspect(packet, owned_fonts):
    require(type(packet) is bytes and 12 <= len(packet) <= (80 << 20)+12 and packet[:8] == b'DOBEGLY1', 'glyph trace packet is invalid or exceeds budget')
    size = int.from_bytes(packet[8:12], 'little')
    require(0 < size <= 16 << 20 and 12+size <= len(packet), 'glyph trace header exceeds owned bytes')
    header = strict_json(packet[12:12+size]); raw = packet[12+size:]
    keys(header, 'schemaVersion display faces runs glyphCount drawCount fontBytes pages substitutions', 'header')
    integer(header['schemaVersion'], 2, 2, 'schema'); require(header['display'] == 'png', 'glyph trace display is unsupported')
    substitutions = header['substitutions']
    require(type(substitutions) is list and len(substitutions) <= 256, 'glyph trace substitution inventory exceeds budget')
    identities = set()
    for item in substitutions:
        keys(item, 'requested actual', 'substitution')
        require(all(type(value) is str and 0 < len(value) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in value)
                    for value in item.values()), 'glyph trace substitution name is invalid')
        identity = (item['requested'], item['actual'])
        require(identity not in identities, 'glyph trace substitution is duplicated'); identities.add(identity)
    integer(header['fontBytes'], 0, 64 << 20, 'font bytes'); require(header['fontBytes'] == len(raw), 'glyph trace font length mismatch')
    integer(header['glyphCount'], 0, 200_000, 'glyph count'); integer(header['drawCount'], 0, 200_000, 'draw count')
    pages = header['pages']; faces = header['faces']; runs = header['runs']
    require(type(pages) is list and 0 < len(pages) <= 256, 'glyph trace page count is invalid')
    for page in pages:
        vector(page, 2, 'page'); require(all(0 < n <= 1584 for n in page), 'glyph trace page dimensions exceed admission bounds')
    require(type(faces) is list and len(faces) <= 64 and type(runs) is list and len(runs) <= 50_000, 'glyph trace face/run count exceeds budget')
    require(type(owned_fonts) in (list, tuple) and len(owned_fonts) <= 64, 'glyph trace owned font inventory exceeds budget')
    owned = {}; owned_size = 0
    for data in owned_fonts:
        require(type(data) is bytes and 0 < len(data) <= 32 << 20, 'glyph trace owned font exceeds budget')
        owned_size += len(data); require(owned_size <= 64 << 20, 'glyph trace owned fonts exceed aggregate budget')
        owned[hashlib.sha256(data).hexdigest()] = data
    font_reports = []; maps = []; offset = 0
    for face in faces:
        keys(face, 'family style index weight italic unitsPerEm coordinates offset bytes', 'face')
        for key in ('family', 'style'):
            value = face[key]
            require(type(value) is str and 0 < len(value) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'glyph trace font name is invalid')
        integer(face['index'], 0, 0, 'standalone face index')
        require(face['coordinates'] == [], 'glyph trace variable-font identity needs separate qualification')
        number(face['weight'], 1, 1000, 'font weight'); require(type(face['italic']) is bool, 'glyph trace italic is not boolean')
        number(face['unitsPerEm'], 16, 16384, 'font units')
        integer(face['offset'], offset, offset, 'font offset'); integer(face['bytes'], 1, 32 << 20, 'face bytes')
        end = offset+face['bytes']; require(end <= len(raw), 'glyph trace font exceeds owned packet bytes')
        data = raw[offset:end]; sha = hashlib.sha256(data).hexdigest()
        require(sha in owned and owned[sha] == data, 'glyph trace selected an unowned font')
        report = inspect_font(data)
        require(face['unitsPerEm'] == report['units_per_em'], 'glyph trace font units disagree with source')
        cmap = report['tables']['cmap']; maps.append(character_maps(data[cmap['offset']:cmap['offset']+cmap['bytes']], report['glyph_count'])['unicode_maps'])
        font_reports.append({**face, 'sha256': sha, 'glyph_count': report['glyph_count']}); offset = end
    require(offset == len(raw), 'glyph trace contains unreferenced font bytes')
    total = 0; text_bytes = 0; paths = set(); direct = 0; shaped = 0; unknown = 0; used = set()
    for run in runs:
        keys(run, 'page path frames font size xScale syntheticBold syntheticItalic text rangesKnown ranges glyphs', 'run')
        integer(run['page'], 0, len(pages)-1, 'run page'); integer(run['font'], 0, len(faces)-1, 'run face')
        used.add(run['font']); path = run['path']
        require(type(path) is list and 0 < len(path) <= 17, 'glyph trace draw path is invalid')
        for i in path: integer(i, 0, 199_999, 'draw path index')
        identity = (run['page'], tuple(path)); require(identity not in paths, 'glyph trace duplicates a draw path'); paths.add(identity)
        require(type(run['frames']) is list and len(run['frames']) <= 16, 'glyph trace frame nesting exceeds budget')
        for frame in run['frames']:
            require(type(frame) is dict and frame.get('kind') in ('clip', 'transform'), 'glyph trace frame kind is invalid')
            kind = frame['kind']; field = 'rect' if kind == 'clip' else 'matrix'
            keys(frame, 'kind '+field, 'frame'); vector(frame[field], 4 if kind == 'clip' else 6, 'frame geometry')
            if kind == 'clip': require(frame['rect'][2] >= 0 and frame['rect'][3] >= 0, 'glyph trace clip size is negative')
        number(run['size'], 0.01, 1638, 'font size'); number(run['xScale'], 0.01, 6, 'horizontal scale')
        require(type(run['syntheticBold']) is bool and type(run['syntheticItalic']) is bool, 'glyph trace synthetic styles are not boolean')
        text = run['text']; require(type(text) is str, 'glyph trace text is invalid'); encoded = text.encode('utf-8')
        text_bytes += len(encoded); require(text_bytes <= 4 << 20, 'glyph trace text exceeds aggregate budget')
        glyphs = run['glyphs']; ranges = run['ranges']
        require(type(glyphs) is list and type(ranges) is list and type(run['rangesKnown']) is bool, 'glyph trace range state is invalid')
        if run['rangesKnown']: require(len(glyphs) == len(ranges), 'glyph trace ranges do not cover glyphs')
        else: require(not ranges and bool(glyphs), 'glyph trace unknown ranges must be empty with actual glyphs')
        total += len(glyphs); require(total <= 200_000, 'glyph trace glyphs exceed aggregate budget')
        boundaries = {0}; position = 0
        for character in text: position += len(character.encode('utf-8')); boundaries.add(position)
        for index, glyph in enumerate(glyphs):
            vector(glyph, 3, 'glyph'); integer(glyph[0], 1, font_reports[run['font']]['glyph_count']-1, 'glyph ID')
            if not run['rangesKnown']:
                unknown += 1; continue
            interval = ranges[index]
            require(type(interval) is list and len(interval) == 2, 'glyph trace text range has wrong dimensions')
            start, end = interval
            integer(start, 0, len(encoded), 'range start'); integer(end, start, len(encoded), 'range end')
            require(start in boundaries and end in boundaries, 'glyph trace range splits UTF-8')
            chars = encoded[start:end].decode('utf-8')
            if len(chars) == 1 and all(mapping.get(ord(chars), 0) == glyph[0] for mapping in maps[run['font']]): direct += 1
            else: shaped += 1
    require(total == header['glyphCount'] and len(runs) <= header['drawCount'], 'glyph trace aggregate counts disagree')
    require(used == set(range(len(faces))), 'glyph trace includes unused faces')
    return {'faces': font_reports, 'runs': runs, 'pages': pages, 'substitutions': substitutions, 'glyph_count': total, 'direct_cmap_matches': direct,
            'contextual_or_ligature_glyphs': shaped, 'unknown_text_range_glyphs': unknown, 'text_bytes': text_bytes,
            'pending_qualification': ['independent-shaping-comparison', 'font-hint-execution', 'font-outline-renderer-comparison', 'font-layout-and-variation-tables',
                                      'font-embedding-rights', 'document-source-fidelity']+(['unknown-glyph-text-ranges'] if unknown else []),
            'engine_admission_complete': False}
