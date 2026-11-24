"""Independent, bounded inspection of standalone TrueType font resources.

This checks containers, metrics, character maps and bounded outline records. It
does not execute hint programs or grant native execution permission. Collections,
compressed fonts and CFF outlines need separate profiles and are refused here.
"""
import hashlib
import struct

from .write_container import require
from .write_outlines import inspect as inspect_outlines

MAX_BYTES = 32 << 20
MAX_TABLES = 128
MAX_CMAPS = 32
MAX_MAPPINGS = 2_000_000


def span(data, offset, size, label):
    require(0 <= offset <= len(data) and 0 <= size <= len(data)-offset, 'font '+label+' exceeds owned bytes')
    return data[offset:offset+size]


def unpack(data, offset, pattern, label):
    return struct.unpack(pattern, span(data, offset, struct.calcsize(pattern), label))


def checksum(data):
    return sum(value[0] for value in struct.iter_unpack('>I', data+b'\0'*((-len(data)) % 4))) & 0xffffffff


def character_maps(data, glyphs):
    version, count = unpack(data, 0, '>HH', 'cmap header')
    require(version == 0 and 0 < count <= MAX_CMAPS, 'font cmap version/count is unsupported')
    header_end = 4+8*count; span(data, 0, header_end, 'cmap records')
    records = []; seen = set(); decoded = {}; intervals = []; work = 0
    for i in range(count):
        platform, encoding, offset = unpack(data, 4+8*i, '>HHI', 'cmap record')
        require((platform, encoding) not in seen and offset >= header_end, 'font cmap has duplicate identity or header overlap')
        seen.add((platform, encoding))
        if offset not in decoded:
            kind, = unpack(data, offset, '>H', 'cmap format')
            require(kind in (4, 6, 12), 'font cmap format is outside the qualified profile')
            if kind == 12:
                _, reserved, length, language, groups = unpack(data, offset, '>HHIII', 'cmap 12 header')
                require(reserved == 0 and 0 < groups <= 65_536 and length == 16+12*groups,
                        'font cmap 12 length/count is invalid')
            else:
                _, length, language = unpack(data, offset, '>HHH', 'cmap header')
            sub = span(data, offset, length, 'cmap subtable'); intervals.append((offset, offset+length))
            mapping = {}; previous = -1

            def add(codepoint, glyph):
                nonlocal work
                work += 1; require(work <= MAX_MAPPINGS, 'font cmap exceeds aggregate mapping budget')
                require(0 <= glyph < glyphs, 'font cmap references a missing glyph')
                require(not (0xd800 <= codepoint <= 0xdfff) or glyph == 0, 'font cmap maps a surrogate')
                if glyph: mapping[codepoint] = glyph

            if kind == 12:
                for j in range(groups):
                    first, last, start_glyph = unpack(sub, 16+12*j, '>III', 'cmap 12 group')
                    require(previous < first <= last <= 0x10ffff and start_glyph+last-first < glyphs,
                            'font cmap 12 group range is invalid')
                    require(last-first+1 <= MAX_MAPPINGS-work, 'font cmap exceeds aggregate mapping budget')
                    for cp in range(first, last+1): add(cp, start_glyph+cp-first)
                    previous = last
            elif kind == 6:
                first, entries = unpack(sub, 6, '>HH', 'cmap 6 range')
                require(length == 10+2*entries and first+entries <= 65_536, 'font cmap 6 range is invalid')
                for j in range(entries): add(first+j, unpack(sub, 10+2*j, '>H', 'cmap 6 glyph')[0])
            else:
                twice, search, selector, shift = unpack(sub, 6, '>HHHH', 'cmap 4 search')
                require(twice > 0 and twice % 2 == 0, 'font cmap 4 segment count is invalid')
                segments = twice//2; power = 1 << (segments.bit_length()-1)
                require((search, selector, shift) == (2*power, power.bit_length()-1, twice-2*power),
                        'font cmap 4 search fields are invalid')
                array_end = 16+8*segments; span(sub, 0, array_end, 'cmap 4 arrays')
                require(unpack(sub, 14+2*segments, '>H', 'cmap 4 padding')[0] == 0, 'font cmap 4 reserved padding is nonzero')
                for j in range(segments):
                    last = unpack(sub, 14+2*j, '>H', 'cmap 4 end')[0]
                    first = unpack(sub, 16+2*segments+2*j, '>H', 'cmap 4 start')[0]
                    delta = unpack(sub, 16+4*segments+2*j, '>h', 'cmap 4 delta')[0]
                    address = 16+6*segments+2*j
                    relative = unpack(sub, address, '>H', 'cmap 4 offset')[0]
                    require(previous < first <= last and relative % 2 == 0, 'font cmap 4 ranges overlap or are invalid')
                    if relative:
                        require(address+relative >= array_end, 'font cmap 4 glyph offset points into its header')
                        span(sub, address+relative, 2*(last-first+1), 'cmap 4 glyph array')
                    for cp in range(first, last+1):
                        value = unpack(sub, address+relative+2*(cp-first), '>H', 'cmap 4 glyph')[0] if relative else cp
                        glyph = (value+delta) & 0xffff if not relative or value else 0
                        add(cp, glyph)
                    previous = last
                require(previous == 0xffff, 'font cmap 4 lacks terminal segment')
            decoded[offset] = (kind, language, mapping)
        kind, language, mapping = decoded[offset]
        records.append({'platform': platform, 'encoding': encoding, 'format': kind, 'language': language,
                        'mapped_characters': len(mapping), 'offset': offset})
    ordered = sorted(intervals)
    require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), 'font cmap subtables partially overlap')
    unicode_records = [r for r in records if r['platform'] == 0 or (r['platform'], r['encoding']) in ((3, 1), (3, 10))]
    require(bool(unicode_records), 'font lacks a supported Unicode cmap')
    return {'records': records, 'mapping_work': work, 'unicode_maps': [decoded[r['offset']][2] for r in unicode_records]}


def names(data):
    version, count, storage = unpack(data, 0, '>HHH', 'name header')
    require(version == 0 and 0 < count <= 4096 and 6+12*count <= storage <= len(data),
            'font name table version/count/storage is unsupported')
    result = []; seen = set(); total = 0
    for i in range(count):
        platform, encoding, language, identity, size, offset = unpack(data, 6+12*i, '>HHHHHH', 'name record')
        key = (platform, encoding, language, identity)
        require(key not in seen, 'font has duplicate name record'); seen.add(key)
        total += size; require(size <= 8192 and total <= 1 << 20, 'font names exceed their budget')
        raw = span(data, storage+offset, size, 'name string')
        text = None
        if platform == 0 or platform == 3 and encoding in (0, 1, 10):
            try: text = raw.decode('utf-16-be')
            except UnicodeError as error: raise ValueError('Write font name is not valid UTF-16') from error
        elif (platform, encoding) == (1, 0): text = raw.decode('mac_roman')
        result.append({'platform': platform, 'encoding': encoding, 'language': language, 'id': identity,
                       'text': text, 'bytes': size, 'sha256': hashlib.sha256(raw).hexdigest()})
    return result


def inspect(data, text=''):
    require(type(data) is bytes and 12 <= len(data) <= MAX_BYTES, 'font bytes exceed profile bounds')
    require(type(text) is str and len(text) <= 65_536, 'font coverage request exceeds its budget')
    signature, count, search, selector, shift = unpack(data, 0, '>4sHHHH', 'directory header')
    require(signature == b'\0\1\0\0', 'font is not standalone TrueType; collections, CFF and compressed fonts need separate admission')
    require(0 < count <= MAX_TABLES, 'font table count exceeds profile bounds')
    power = 1 << (count.bit_length()-1)
    require((search, selector, shift) == (16*power, power.bit_length()-1, 16*(count-power)), 'font directory search fields are invalid')
    directory_end = 12+16*count; span(data, 0, directory_end, 'directory')
    tables = {}; inventory = {}; intervals = []; previous = b''
    for i in range(count):
        tag, expected, offset, length = unpack(data, 12+16*i, '>4sIII', 'directory record')
        require(all(32 <= c <= 126 for c in tag) and tag > previous, 'font table tags are duplicated, unsorted or invalid')
        previous = tag; name = tag.decode('ascii')
        require(offset % 4 == 0 and offset >= directory_end and length > 0, 'font table offset/length is invalid')
        table = span(data, offset, length, name); padded_end = offset+(length+3)//4*4
        padding = span(data, offset+length, padded_end-offset-length, name+' padding')
        require(not any(padding), 'font table padding is nonzero')
        checked = table[:8]+bytes(4)+table[12:] if name == 'head' and length >= 12 else table
        require(checksum(checked) == expected, 'font '+name+' checksum mismatch')
        intervals.append((offset, padded_end)); tables[name] = table
        inventory[name] = {'offset': offset, 'bytes': length, 'sha256': hashlib.sha256(table).hexdigest(), 'checksum': expected}
    ordered = sorted(intervals)
    require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), 'font tables overlap')
    require(ordered[-1][1] == len(data), 'font has unowned trailing bytes')
    require(checksum(data) == 0xb1b0afba, 'font whole-file checksum mismatch')
    required = {'head', 'maxp', 'hhea', 'hmtx', 'loca', 'glyf', 'cmap', 'name', 'OS/2', 'post'}
    require(required <= tables.keys(), 'font lacks required TrueType tables')
    head = tables['head']; maxp = tables['maxp']; hhea = tables['hhea']; os2 = tables['OS/2']
    require(len(head) == 54 and unpack(head, 0, '>I', 'head version')[0] == 0x10000, 'font head version/length is unsupported')
    require(unpack(head, 12, '>I', 'head magic')[0] == 0x5f0f3cf5, 'font head magic is invalid')
    upem = unpack(head, 18, '>H', 'units per em')[0]
    x_min, y_min, x_max, y_max = unpack(head, 36, '>hhhh', 'global bounds')
    location, glyph_format = unpack(head, 50, '>hh', 'glyph format')
    require(16 <= upem <= 16384 and x_min <= x_max and y_min <= y_max and location in (0, 1) and glyph_format == 0,
            'font units/bounds/glyph format is invalid')
    require(len(maxp) == 32 and unpack(maxp, 0, '>I', 'maxp version')[0] == 0x10000, 'font maxp version/length is unsupported')
    glyphs = unpack(maxp, 4, '>H', 'glyph count')[0]; require(glyphs > 0, 'font has no glyphs')
    require(len(hhea) == 36 and unpack(hhea, 0, '>I', 'hhea version')[0] == 0x10000, 'font hhea version/length is unsupported')
    require(not any(hhea[24:34]), 'font horizontal metric reserved fields or format are unsupported')
    metrics = unpack(hhea, 34, '>H', 'horizontal metric count')[0]
    require(1 <= metrics <= glyphs and len(tables['hmtx']) == 4*metrics+2*(glyphs-metrics), 'font horizontal metrics do not cover glyphs')
    size = 2 if location == 0 else 4; loca = tables['loca']
    require(len(loca) == (glyphs+1)*size, 'font glyph location count is invalid')
    offsets = [v[0]*(2 if location == 0 else 1) for v in struct.iter_unpack('>H' if location == 0 else '>I', loca)]
    require(offsets[0] == 0 and offsets[-1] <= len(tables['glyf']) and all(a <= b for a, b in zip(offsets, offsets[1:])),
            'font glyph locations are unordered or outside outlines')
    require(all(a == b or b-a >= 10 for a, b in zip(offsets, offsets[1:])), 'font nonempty glyph lacks its header')
    outlines = inspect_outlines(tables, offsets)
    os_version = unpack(os2, 0, '>H', 'OS/2 version')[0]
    require(os_version in (0, 1, 2, 3, 4, 5) and len(os2) >= (78, 86, 96, 96, 96, 100)[os_version], 'font OS/2 version/length is unsupported')
    weight, width, embedding = unpack(os2, 4, '>HHH', 'OS/2 classes')
    require(1 <= weight <= 1000 and 1 <= width <= 9 and embedding & ~0x30e == 0, 'font OS/2 classes or embedding bits are invalid')
    # Record declared restrictions. This does not decide legal ownership or grant a license.
    restrictions = [label for bit, label in ((2, 'restricted'), (4, 'preview-print'), (8, 'editable'), (256, 'no-subsetting'), (512, 'bitmap-only')) if embedding & bit]
    cmap = character_maps(tables['cmap'], glyphs); name_records = names(tables['name'])
    coverage = []
    for cp in sorted(set(map(ord, text))):
        require(not 0xd800 <= cp <= 0xdfff, 'font coverage text has a surrogate')
        values = sorted({m.get(cp, 0) for m in cmap['unicode_maps']})
        coverage.append({'codepoint': cp, 'glyph_ids': values, 'all_maps_present': 0 not in values, 'maps_agree': len(values) == 1})
    return {'format': 'TrueType', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'tables': inventory,
            'glyph_count': glyphs, 'units_per_em': upem, 'horizontal_metrics': metrics, 'names': name_records,
            'embedding_bits': embedding, 'declared_embedding_restrictions': restrictions, 'cmap_records': cmap['records'],
            'cmap_mapping_work': cmap['mapping_work'], 'coverage': coverage, 'outlines': outlines,
            'pending_qualification': outlines['pending_qualification']+['font-embedding-rights',
                                      'native-font-identity', 'shaped-glyph-coverage'], 'engine_admission_complete': False}
