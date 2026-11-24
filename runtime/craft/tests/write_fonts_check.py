#!/usr/bin/env python3
"""Check bounded font parsing with pinned real fonts and checksum-correct mutations."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_fonts as fonts, write_retained as retained


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fonts', type=Path, required=True)
    parser.add_argument('--retained', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; started = time.monotonic(); reports = {}

    def check(condition, label):
        if not condition: raise AssertionError(label)
        checks.append(label)

    def refused(label, operation, expected):
        try: operation()
        except ValueError as error:
            check(expected in str(error), label+' fails at the intended boundary')
            refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)

    # Test fixture writer is separate from the parser. It reconstructs a complete
    # valid SFNT directory/checksums so malformed internals reach semantic checks.
    def sum32(data):
        padded = data+b'\0'*((-len(data)) % 4)
        return sum(int.from_bytes(padded[i:i+4], 'big') for i in range(0, len(padded), 4)) & 0xffffffff

    def directory(data):
        tables = {}
        for i in range(int.from_bytes(data[4:6], 'big')):
            tag, _, offset, length = struct.unpack_from('>4sIII', data, 12+16*i)
            tables[tag] = bytearray(data[offset:offset+length])
        return tables

    def rebuild(tables):
        tables = copy.deepcopy(tables); tables[b'head'][8:12] = bytes(4)
        count = len(tables); power = 2**(count.bit_length()-1)
        data = bytearray(struct.pack('>4sHHHH', b'\0\1\0\0', count, 16*power, power.bit_length()-1, 16*(count-power)))
        data.extend(bytes(16*count)); head = None
        for i, (tag, table) in enumerate(sorted(tables.items())):
            offset = len(data)
            struct.pack_into('>4sIII', data, 12+16*i, tag, sum32(table), offset, len(table))
            if tag == b'head': head = offset
            data.extend(table); data.extend(bytes((-len(data)) % 4))
        struct.pack_into('>I', data, head+8, (0xb1b0afba-sum32(data)) & 0xffffffff)
        return bytes(data)

    def changed(tag, offset, pattern, value):
        tables = copy.deepcopy(original_tables); struct.pack_into(pattern, tables[tag], offset, value)
        return rebuild(tables)

    def cmap_table(subtables):
        header = bytearray(struct.pack('>HH', 0, len(subtables))+bytes(8*len(subtables)))
        for i, (platform, encoding, sub) in enumerate(subtables):
            struct.pack_into('>HHI', header, 4+8*i, platform, encoding, len(header)); header.extend(sub)
        return bytes(header)

    def format4(glyph=3, relative=False):
        # U+0041 followed by required terminal segment; independently written arrays.
        return struct.pack('>HHHHHHH', 4, 34 if relative else 32, 0, 4, 4, 1, 0)+struct.pack(
            '>HHHHHhhHH', 65, 65535, 0, 65, 65535, 0 if relative else glyph-65, 1, 4 if relative else 0, 0)+(struct.pack('>H', glyph) if relative else b'')

    def format12(first, last, glyph): return struct.pack('>HHIIIIII', 12, 0, 28, 0, 1, first, last, glyph)

    try:
        paths = sorted(args.fonts.glob('*.ttf')); check(len(paths) == 13, 'all thirteen pinned bundled TrueType fonts are exercised')
        for path in paths:
            source = path.read_bytes(); report = fonts.inspect(source, 'Original Åé Ω Ж 中文 😀')
            reports[path.name] = report
            check(report['sha256'] == hashlib.sha256(source).hexdigest() and not report['engine_admission_complete'], path.name+' records exact identity without execution permission')
            check(any(n['id'] in (1, 16) and n['text'] for n in report['names']), path.name+' has decoded family identity')
            latin = [item for item in report['coverage'] if item['codepoint'] in map(ord, 'Original')]
            check(all(item['all_maps_present'] and item['maps_agree'] for item in latin), path.name+' agrees across Unicode maps for original text')
            check(path.read_bytes() == source, path.name+' original remains unchanged')

        source = (args.fonts/'SourceSans3-Regular.ttf').read_bytes(); original_tables = directory(source)
        check(fonts.inspect(rebuild(original_tables))['glyph_count'] == reports['SourceSans3-Regular.ttf']['glyph_count'], 'independent checksum-correct reconstruction preserves glyph count')
        for signature in (b'ttcf', b'OTTO', b'wOFF', b'wOF2'):
            refused('unqualified '+signature.decode(), lambda s=signature: fonts.inspect(s+source[4:]), 'not standalone TrueType')
        refused('empty font', lambda: fonts.inspect(b''), 'bytes exceed')
        refused('oversized font', lambda: fonts.inspect(bytes(fonts.MAX_BYTES+1)), 'bytes exceed')
        refused('too many tables', lambda: fonts.inspect(source[:4]+struct.pack('>H', 129)+source[6:]), 'table count')
        damaged = bytearray(source); damaged[6:8] = bytes(2)
        refused('directory search mismatch', lambda: fonts.inspect(bytes(damaged)), 'search fields')
        duplicate = bytearray(source); duplicate[28:32] = duplicate[12:16]
        refused('duplicate table', lambda: fonts.inspect(bytes(duplicate)), 'table tags')
        unaligned = bytearray(source); struct.pack_into('>I', unaligned, 20, 1)
        refused('table points into header', lambda: fonts.inspect(bytes(unaligned)), 'offset/length')
        outside = bytearray(source); struct.pack_into('>I', outside, 20, len(source)+4)
        refused('table exceeds file', lambda: fonts.inspect(bytes(outside)), 'exceeds owned bytes')
        corrupted = bytearray(source); corrupted[-1] ^= 1
        refused('checksum corruption', lambda: fonts.inspect(bytes(corrupted)), 'checksum')
        refused('trailing bytes', lambda: fonts.inspect(source+bytes(4)), 'trailing bytes')
        wrong_adjustment = bytearray(source)
        head_offset = reports['SourceSans3-Regular.ttf']['tables']['head']['offset']
        wrong_adjustment[head_offset+8] ^= 1
        refused('whole-file adjustment corruption', lambda: fonts.inspect(bytes(wrong_adjustment)), 'whole-file checksum')
        padded = bytearray(source)
        entry = next(t for t in reports['SourceSans3-Regular.ttf']['tables'].values() if t['bytes'] % 4)
        padded[entry['offset']+entry['bytes']] = 1
        refused('nonzero table padding', lambda: fonts.inspect(bytes(padded)), 'padding is nonzero')
        tables = copy.deepcopy(original_tables); tables[b'AAAA'] = bytearray(tables[b'BASE'])
        overlap = bytearray(rebuild(tables))
        # AAAA and BASE have identical content and checksum, but cannot own the same interval.
        struct.pack_into('>I', overlap, 20, int.from_bytes(overlap[36:40], 'big'))
        refused('overlapping table ownership', lambda: fonts.inspect(bytes(overlap)), 'tables overlap')
        tables = copy.deepcopy(original_tables); tables.pop(b'hmtx')
        refused('missing metrics', lambda: fonts.inspect(rebuild(tables)), 'required TrueType tables')
        cases = [
            ('head magic', b'head', 12, '>I', 0, 'magic'),
            ('units too small', b'head', 18, '>H', 15, 'units/bounds'),
            ('units too large', b'head', 18, '>H', 16385, 'units/bounds'),
            ('unknown loca format', b'head', 50, '>h', 2, 'glyph format'),
            ('unknown glyph format', b'head', 52, '>h', 1, 'glyph format'),
            ('no glyphs', b'maxp', 4, '>H', 0, 'no glyphs'),
            ('wrong maxp version', b'maxp', 0, '>I', 0x5000, 'maxp version'),
            ('unknown metrics version', b'hhea', 0, '>I', 0, 'hhea version'),
            ('nonzero metric reserved', b'hhea', 24, '>H', 1, 'reserved fields'),
            ('zero horizontal metrics', b'hhea', 34, '>H', 0, 'metrics do not cover'),
            ('excess horizontal metrics', b'hhea', 34, '>H', 65535, 'metrics do not cover'),
            ('unknown OS/2 version', b'OS/2', 0, '>H', 6, 'OS/2 version'),
            ('invalid weight', b'OS/2', 4, '>H', 1001, 'OS/2 classes'),
            ('invalid width', b'OS/2', 6, '>H', 0, 'OS/2 classes'),
            ('reserved embedding bits', b'OS/2', 8, '>H', 1, 'embedding bits'),
            ('unsupported name version', b'name', 0, '>H', 1, 'name table'),
            ('oversized name count', b'name', 2, '>H', 4097, 'name table'),
            ('name storage in header', b'name', 4, '>H', 0, 'name table'),
            ('name string outside file', b'name', 16, '>H', 65535, 'exceeds owned bytes'),
            ('unknown cmap version', b'cmap', 0, '>H', 1, 'cmap version'),
            ('oversized cmap count', b'cmap', 2, '>H', 33, 'cmap version'),
            ('cmap points into header', b'cmap', 8, '>I', 0, 'header overlap'),
        ]
        for label, tag, offset, pattern, value, expected in cases:
            mutated = changed(tag, offset, pattern, value)
            check(sum32(mutated) == 0xb1b0afba, label+' mutation has a correct whole-file checksum')
            refused(label, lambda d=mutated: fonts.inspect(d), expected)
        tables = copy.deepcopy(original_tables); tables[b'loca'] = tables[b'loca'][:-2]
        refused('short loca', lambda: fonts.inspect(rebuild(tables)), 'location count')
        location = int.from_bytes(original_tables[b'head'][50:52], 'big'); width = 2 if location == 0 else 4
        refused('loca starts past first glyph', lambda: fonts.inspect(changed(b'loca', 0, '>H' if width == 2 else '>I', 1)), 'glyph locations')
        tables = copy.deepcopy(original_tables); tables[b'loca'][-width:] = b'\xff'*width
        refused('loca exceeds glyph data', lambda: fonts.inspect(rebuild(tables)), 'glyph locations')
        tables = copy.deepcopy(original_tables); tables[b'name'][18:26] = tables[b'name'][6:14]
        refused('duplicate font name identity', lambda: fonts.inspect(rebuild(tables)), 'duplicate name record')
        tables = copy.deepcopy(original_tables); name_table = tables[b'name']
        for i in range(int.from_bytes(name_table[2:4], 'big')):
            record = 6+12*i
            if int.from_bytes(name_table[record:record+2], 'big') == 3:
                struct.pack_into('>H', name_table, record+8, 1); break
        refused('odd-length Unicode name', lambda: fonts.inspect(rebuild(tables)), 'not valid UTF-16')
        for bits, expected in ((2, 'restricted'), (4, 'preview-print'), (8, 'editable'), (256, 'no-subsetting'), (512, 'bitmap-only')):
            report = fonts.inspect(changed(b'OS/2', 8, '>H', bits))
            check(expected in report['declared_embedding_restrictions'] and 'font-embedding-rights' in report['pending_qualification'],
                  expected+' bit recorded without granting legal or export permission')

        direct = format4(); indirect = format4(relative=True)
        for label, sub in (('delta', direct), ('relative glyph array', indirect)):
            report = fonts.character_maps(cmap_table([(3, 1, sub)]), 10)
            check(report['unicode_maps'][0] == {65: 3}, 'format 4 '+label+' independently maps A to glyph 3')
        supplementary = fonts.character_maps(cmap_table([(3, 10, format12(0x1f600, 0x1f602, 4))]), 10)
        check(supplementary['unicode_maps'][0] == {0x1f600: 4, 0x1f601: 5, 0x1f602: 6}, 'format 12 supplementary range maps exact glyph sequence')
        short_map = struct.pack('>HHHHHHHH', 6, 16, 0, 65, 3, 3, 0, 5)
        check(fonts.character_maps(cmap_table([(0, 0, short_map)]), 10)['unicode_maps'][0] == {65: 3, 67: 5},
              'format 6 preserves missing glyph zero independently')
        refused('cmap lacks Unicode encoding', lambda: fonts.character_maps(cmap_table([(1, 0, short_map)]), 10), 'lacks a supported Unicode')
        tables = copy.deepcopy(original_tables); tables[b'cmap'] = bytearray(cmap_table([(0, 3, format4(3)), (3, 1, format4(4))]))
        coverage = fonts.inspect(rebuild(tables), 'AB')['coverage']
        check(coverage[0] == {'codepoint': 65, 'glyph_ids': [3, 4], 'all_maps_present': True, 'maps_agree': False},
              'disagreeing Unicode maps are explicit instead of silently choosing one')
        check(coverage[1] == {'codepoint': 66, 'glyph_ids': [0], 'all_maps_present': False, 'maps_agree': True},
              'missing character remains explicit instead of granting fallback coverage')
        refused('cmap missing glyph', lambda: fonts.character_maps(cmap_table([(3, 1, format4(11))]), 10), 'missing glyph')
        refused('cmap 12 outside Unicode', lambda: fonts.character_maps(cmap_table([(3, 10, format12(0x110000, 0x110000, 1))]), 10), 'range is invalid')
        refused('cmap 12 surrogate', lambda: fonts.character_maps(cmap_table([(3, 10, format12(0xd800, 0xd800, 1))]), 10), 'surrogate')
        refused('cmap 12 glyph overflow', lambda: fonts.character_maps(cmap_table([(3, 10, format12(65, 67, 9))]), 10), 'range is invalid')
        bad_relative = bytearray(indirect); struct.pack_into('>H', bad_relative, 28, 2)
        refused('cmap 4 offset into arrays', lambda: fonts.character_maps(cmap_table([(3, 1, bytes(bad_relative))]), 10), 'into its header')
        refused('cmap duplicate encoding', lambda: fonts.character_maps(cmap_table([(3, 1, direct), (3, 1, direct)]), 10), 'duplicate identity')
        refused('cmap unknown format', lambda: fonts.character_maps(cmap_table([(3, 1, b'\0\x0e'+bytes(20))]), 10), 'outside the qualified profile')
        refused('coverage surrogate', lambda: fonts.inspect(source, '\ud800'), 'surrogate')
        refused('coverage budget', lambda: fonts.inspect(source, 'A'*65_537), 'coverage request')

        document = json.loads(args.retained.read_text()); before = copy.deepcopy(document)
        report = retained.inspect(document)
        check(report['embedded_fonts'][0]['font_profile']['sha256'] == hashlib.sha256(source).hexdigest(), 'retained de-obfuscation runs independent font profile before any native call')
        check(document == before and not report['engine_admission_complete'], 'retained font inspection preserves original and pending gates')
        broken = copy.deepcopy(document); name = report['embedded_fonts'][0]['part']
        encoded = bytearray(base64.b64decode(broken['passthrough'][name])); encoded[-1] ^= 1
        broken['passthrough'][name] = base64.b64encode(encoded).decode('ascii')
        refused('corrupt embedded font', lambda: retained.inspect(broken), 'checksum')
        (out/'fonts.json').write_text(json.dumps(reports, indent=2)+'\n')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'font_files': len(paths), 'native_calls': 0,
                    'remote_actions': False, 'seconds': time.monotonic()-started, 'engine_admission_complete': False,
                    'scope': 'standalone TrueType directory, checksums, metrics, location ranges, names and cmap; outlines, hint programs, shaping and rights remain pending'}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'font_files': len(paths), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise


if __name__ == '__main__': main()
