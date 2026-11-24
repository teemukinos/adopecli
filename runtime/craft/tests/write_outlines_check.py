#!/usr/bin/env python3
"""Exercise real outlines and independent adversarial simple/composite glyphs."""
import argparse
import copy
import json
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_fonts as fonts, write_outlines as outlines


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--fonts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; started = time.monotonic()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def refused(label, operation, expected):
        try: operation()
        except ValueError as error:
            check(expected in str(error), label+' fails at the intended boundary'); refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)

    # A three-point triangle. Endpoints, repeat flags and delta bytes are authored
    # independently rather than serializing the parser's intermediate model.
    def triangle(hints=b''):
        return struct.pack('>hhhhhHH', 1, 0, 0, 100, 100, 2, len(hints))+hints+b'\x31\x33\x27\x64\x64\x64'

    def composite(children, hints=None):
        data = bytearray(struct.pack('>hhhhh', -1, 0, 0, 200, 200))
        for i, (child, extra, args, transform) in enumerate(children):
            flags = extra | (32 if i < len(children)-1 else 0) | (256 if hints is not None and i == len(children)-1 else 0)
            data.extend(struct.pack('>HH', flags, child)); data.extend(args); data.extend(transform)
        if hints is not None: data.extend(struct.pack('>H', len(hints))+hints)
        return bytes(data)

    def component(child, x=0, y=0): return (child, 3, struct.pack('>hh', x, y), b'')

    def fixture(glyphs, **limits):
        values = {'points': 4096, 'contours': 1024, 'comp_points': 65535, 'comp_contours': 65535, 'zones': 2,
                  'twilight': 0, 'storage': 0, 'functions': 0, 'definitions': 0, 'stack': 0, 'instructions': 65535, 'components': 128, 'depth': 16}
        values.update(limits); data = bytearray(); offsets = [0]
        for glyph in glyphs:
            data.extend(glyph); data.extend(bytes((-len(data)) % 4)); offsets.append(len(data))
        return {'glyf': bytes(data), 'maxp': struct.pack('>IH13H', 0x10000, len(glyphs), *values.values())}, offsets

    def run(glyphs, **limits): return outlines.inspect(*fixture(glyphs, **limits))

    try:
        reports = {}
        for path in sorted(args.fonts.glob('*.ttf')):
            before = path.read_bytes(); report = fonts.inspect(before)['outlines']; reports[path.name] = report
            check(report['expanded_points'] > 0 and report['maximum_depth'] <= 3, path.name+' full outline graph and point decoding pass')
            check(not report['hint_execution_qualified'] and path.read_bytes() == before, path.name+' inspection neither executes hints nor rewrites source')
        check(len(reports) == 13, 'all thirteen pinned fonts exercised')
        simple = triangle(); report = run([simple])
        check(report['simple_points'] == 3 and report['expanded_points'] == 3, 'independently encoded triangle has three decoded points')
        repeated = struct.pack('>hhhhhHH', 1, 0, 0, 0, 0, 2, 0)+b'\x39\x02'
        check(run([repeated])['simple_points'] == 3, 'repeat flags cover exactly three same-position points')
        delta_words = struct.pack('>hhhhhHH', 1, -100, -100, 100, 100, 1, 0)+b'\x01\x01'+struct.pack('>hhhh', -100, 200, -100, 200)
        check(run([delta_words])['simple_points'] == 2, 'signed sixteen-bit coordinate deltas decode independently')
        shared = composite([component(0), component(0, 100)])
        nested = composite([component(1), component(0)])
        report = run([simple, shared, nested])
        check(report['expanded_points'] == 18 and report['expanded_nodes'] == 9 and report['maximum_depth'] == 2,
              'shared components count each occurrence without recursively copying outlines')
        attached = composite([component(0), (0, 1, struct.pack('>HH', 2, 0), b'')])
        check(run([simple, attached])['point_attachments'] == 1, 'point attachment references existing base and child points')
        for label, extra, transform in [('uniform', 8, struct.pack('>h', 8192)), ('anisotropic', 64, struct.pack('>hh', 8192, 16384)), ('matrix', 128, struct.pack('>hhhh', 16384, 8192, 0, 16384))]:
            check(run([simple, composite([(0, 3|extra, struct.pack('>hh', 0, 0), transform)])])['components'] == 1, label+' F2DOT14 transform parses')
        for data, count in ((b'\xb0\xff', 1), (b'\xb8\x80\x00', 1), (b'\x40\x02\xb0\xb8', 1), (b'\x41\x01\xff\xff', 1), (b'\x21', 1)):
            check(outlines.program(data)['opcodes'] == count, 'push operands stay data, not opcodes: '+data.hex())
        hinted = run([triangle(b'\xb0\x00\x21')]); check(hinted['glyph_instruction_opcodes'] == 2, 'glyph hint stream is inventoried without executing its stack')
        tables, offsets = fixture([simple]); tables.update(fpgm=b'\xb0\x00\x2c\x2d', prep=b'\xb0\x01\x21', **{'cvt ': b'\x00\x80'})
        check(set(outlines.inspect(tables, offsets)['programs']) == {'fpgm','prep'}, 'font/prep programs and control values receive bounded structural inspection')

        for label, value, expected in [
            ('short header', b'\x00', 'exceeds owned bytes'),
            ('inverted bounds', struct.pack('>hhhhhHH', 0, 1, 0, 0, 0, 0, 0), 'bounds are inverted'),
            ('unknown contour kind', struct.pack('>hhhhh', -2, 0, 0, 0, 0), 'contour type'),
            ('unordered endpoints', struct.pack('>hhhhhHHH', 2, 0, 0, 100, 100, 2, 1, 0), 'endpoints are unordered'),
            ('repeat overflow', repeated[:-1]+b'\x03', 'repeat exceeds'),
            ('cubic point flag', simple[:14]+b'\xb1'+simple[15:], 'cubic outline'),
            ('escaping coordinate', simple[:-1]+b'\x65', 'escapes declared bounds'),
            ('truncated instructions', struct.pack('>hhhhhHH', 1, 0, 0, 100, 100, 2, 100)+b'\0', 'exceeds owned bytes'),
            ('nonzero tail', simple+b'\xff', 'trailing bytes'),
            ('oversized tail', simple+bytes(4), 'trailing bytes'),
        ]: refused(label, lambda v=value: run([v]), expected)
        refused('undeclared point allocation', lambda: run([simple], points=2), 'points exceed maxp')
        refused('undeclared contour allocation', lambda: run([simple], contours=0), 'contours exceed maxp')
        refused('undeclared glyph hints', lambda: run([triangle(b'\x21')], instructions=0), 'instructions exceed maxp')
        for label, kwargs in [('twilight', {'twilight': 1025}), ('stack', {'stack': 4097}), ('storage', {'storage': 16385}), ('zones', {'zones': 3}), ('functions', {'functions': 4097}), ('instruction definitions', {'definitions': 257})]:
            refused('excess '+label, lambda k=kwargs: run([simple], **k), 'allocation declarations')
        refused('excess declared components', lambda: run([simple], components=129), 'composite declarations')
        refused('excess declared depth', lambda: run([simple], depth=17), 'composite declarations')
        refused('missing component glyph', lambda: run([composite([component(5)])]), 'glyph reference')
        refused('self cycle', lambda: run([composite([component(0)])]), 'contains a cycle')
        refused('two-node cycle', lambda: run([composite([component(1)]), composite([component(0)])]), 'contains a cycle')
        refused('reserved component flags', lambda: run([simple, composite([(0, 0x2003, bytes(4), b'')])]), 'flags or glyph reference')
        refused('multiple transform encodings', lambda: run([simple, composite([(0, 3|8|64, bytes(4), bytes(6))])]), 'transform flags conflict')
        refused('conflicting offset modes', lambda: run([simple, composite([(0, 3|0x1800, bytes(4), b'')])]), 'transform flags conflict')
        refused('instructions before final child', lambda: run([simple, composite([(0, 3|256, bytes(4), b''), component(0)])]), 'instructions precede')
        refused('component count declaration', lambda: run([simple, shared], components=1), 'components exceed')
        refused('expanded points declaration', lambda: run([simple, shared], comp_points=5), 'expansion exceeds')
        refused('expanded contours declaration', lambda: run([simple, shared], comp_contours=1), 'expansion exceeds')
        refused('composite depth declaration', lambda: run([simple, shared, nested], depth=1), 'expansion exceeds')
        refused('point attachment before base', lambda: run([simple, composite([(0, 1, bytes(4), b'')])]), 'point attachment')
        refused('child point attachment outside glyph', lambda: run([simple, composite([component(0), (0, 1, struct.pack('>HH', 0, 3), b'')])]), 'point attachment')
        chain = [simple]
        for index in range(12): chain.append(composite([component(index), component(index)]))
        refused('exponential repeated components', lambda: run(chain), 'expansion exceeds')
        empty_chain = [b'']
        for index in range(10): empty_chain.append(composite([component(index), component(index)]))
        empty_chain.extend([composite([component(10)])]*1000)
        refused('aggregate empty-outline expansion', lambda: run(empty_chain), 'aggregate expansion exceeds')
        point_chain = [simple]
        for index in range(10): point_chain.append(composite([component(index), component(index)]))
        point_chain.extend([composite([component(10)])]*700)
        refused('aggregate point expansion', lambda: run(point_chain), 'aggregate expansion exceeds')
        scaled_chain = [simple]
        for index in range(14):
            scaled_chain.append(composite([(index, 3|128, bytes(4), struct.pack('>hhhh', 32767,32767,32767,32767))]))
        refused('transformed coordinate explosion', lambda: run(scaled_chain), 'transformed coordinates exceed')
        for data in (b'\xb0', b'\xb8\0', b'\x40', b'\x41\x02\0\0'):
            refused('truncated hint operands '+data.hex(), lambda d=data: outlines.program(d), 'exceeds owned bytes')
        refused('oversized hint stream', lambda: outlines.program(bytes((256 << 10)+1)), 'program exceeds')
        bad = copy.deepcopy(tables); bad['cvt '] = b'\0'
        refused('odd control value length', lambda: outlines.inspect(bad, offsets), 'control-value table')
        (out/'outlines.json').write_text(json.dumps(reports, indent=2)+'\n')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'font_files': len(reports), 'native_calls': 0,
                    'remote_actions': False, 'seconds': time.monotonic()-started, 'hint_execution_qualified': False,
                    'scope': 'bounded simple outline decoding, component ownership/DAG/expansion and hint operand inventory; hint execution and renderer fidelity remain pending'}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'fonts': len(reports), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise


if __name__ == '__main__': main()
