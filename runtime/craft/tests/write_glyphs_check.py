#!/usr/bin/env python3
"""Verify actual native glyph/font identity, cold determinism and bounded packets."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_glyphs as glyphs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True); parser.add_argument('--fonts', type=Path, required=True)
    parser.add_argument('--embedded', type=Path, required=True); parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--rich', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; calls = []; started = time.monotonic()
    owned = [p.read_bytes() for p in sorted(args.fonts.glob('*.ttf'))]
    source = args.embedded.read_bytes(); document = json.loads(source)
    font = (args.fonts/'SourceSans3-Regular.ttf').read_bytes(); expected_sha = hashlib.sha256(font).hexdigest()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments, fail=None):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=90)
        index = len(calls); calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        if fail:
            check(result.returncode != 0 and fail in result.stderr.decode() and not result.stdout, 'native refuses '+fail+' without partial packet')
        elif result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def split(packet):
        size = int.from_bytes(packet[8:12], 'little'); return json.loads(packet[12:12+size]), packet[12+size:]

    def pack(header, raw):
        data = json.dumps(header, separators=(',', ':')).encode(); return b'DOBEGLY1'+len(data).to_bytes(4, 'little')+data+raw

    def refused(label, operation, expected):
        try: operation()
        except ValueError as error:
            check(expected in str(error), label+' fails at the intended boundary')
            refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)

    def mutate(label, change, expected):
        header, raw = split(packet); change(header)
        refused(label, lambda: glyphs.inspect(pack(header, raw), owned), expected)

    try:
        packet = call('glyphs', args.embedded); report = glyphs.inspect(packet, owned)
        check(report['glyph_count'] == 112 and report['direct_cmap_matches'] == 112, 'every original fixture glyph independently matches its font cmap')
        originals = [r for r in report['runs'] if r['text'] == 'Original']
        check(len(originals) == 1, 'selected original text has one actual native glyph run')
        face = report['faces'][originals[0]['font']]
        check(face['family'] == 'Dobe Original Embedded Fixture' and face['sha256'] == expected_sha,
              'actual selected native alias binds to exact pinned embedded font bytes')
        check([g[0] for g in originals[0]['glyphs']] == [16, 45, 36, 34, 36, 41, 28, 39],
              'Original glyph IDs match independently recorded pinned-font values')
        check(call('glyphs', args.embedded) == packet, 'cold native process reproduces complete glyph packet byte for byte')
        check(not report['engine_admission_complete'], 'glyph identity evidence does not grant document execution permission')
        plain = call('glyphs', args.fixtures/'brief.json'); plain_report = glyphs.inspect(plain, owned)
        check(all(f['family'] != 'Dobe Original Embedded Fixture' for f in plain_report['faces']), 'unembedded original uses only actual bundled faces')

        # Turn actual glyph selection into an observable precise font revision.
        revised = copy.deepcopy(document); revised['body'][2]['runs'][1]['props']['font'] = 'Source Serif 4'
        revised_path = out/'revised.json'; revised_path.write_text(json.dumps(revised)+'\n')
        revised_report = glyphs.inspect(call('glyphs', revised_path), owned)
        selected = next(r for r in revised_report['runs'] if r['text'] == 'Original')
        changed_face = revised_report['faces'][selected['font']]
        check(changed_face['family'] == 'Source Serif 4' and changed_face['sha256'] != expected_sha,
              'precise font revision changes actual selected font bytes')
        check(json.loads(call('snapshot', revised_path))['document'] == revised, 'glyph tracing leaves complete revised document model unchanged')
        docx = out/'embedded.docx'; call('convert', args.embedded, docx)
        docx_report = glyphs.inspect(call('glyphs', docx), owned)
        selected = next(r for r in docx_report['runs'] if r['text'] == 'Original')
        check(docx_report['faces'][selected['font']]['sha256'] == expected_sha,
              'actual DOCX round trip selects exact embedded source bytes')

        ligature = copy.deepcopy(document)
        ligature['body'] = [{'kind': 'para', 'text': 'office affinity ffi', 'runs': [{'len': 19, 'props': {'font': 'Dobe Original Embedded Fixture'}}],
                             'props': {'style': 'Normal'}, 'objects': []}]
        ligature_path = out/'ligature.json'; ligature_path.write_text(json.dumps(ligature)+'\n')
        ligature_report = glyphs.inspect(call('glyphs', ligature_path), owned)
        check(ligature_report['contextual_or_ligature_glyphs'] > 0 and ligature_report['glyph_count'] < 19,
              'actual native ligatures retain cluster ranges instead of claiming one glyph per character')
        check('independent-shaping-comparison' in ligature_report['pending_qualification'], 'ligature observation remains distinct from independent shaping proof')
        call('render', ligature_path, out/'ligature.png', '--strict', '--scale', '1')
        call('glyphs', fail='requires exactly one input path')
        call('glyphs', args.embedded, args.embedded, fail='requires exactly one input path')
        call('glyphs', args.fixtures/'missing-glyph.json', fail='strict: 1 character cannot be drawn')
        call('glyphs', args.fixtures/'missing-picture.docx', fail='strict:')
        watermark = copy.deepcopy(document)
        watermark['settings']['watermark'] = {'text': 'DRAFT', 'font': 'Source Sans 3', 'color': [192,192,192], 'diagonal': True, 'semitransparent': True}
        watermark_path = out/'watermark.json'; watermark_path.write_text(json.dumps(watermark)+'\n')
        call('glyphs', watermark_path, fail='watermark identity is not qualified')
        # Keep the original rich fixture immutable. Use its editable nested stories
        # with bundled Latin fonts, then rotate its real text box.
        rich_source = args.rich.read_bytes(); rich = json.loads(rich_source)
        rich['body'][0]['text'] = 'Café'; rich['body'][0]['runs'] = [{'len': 5}]
        for block in rich['body']:
            for item in block.get('objects', []):
                if item.get('type') == 'shape' and item.get('kind') == 'textBox': item['float']['rot'] = 30
        rich_path = out/'rich.json'; rich_path.write_text(json.dumps(rich)+'\n')
        rich_report = glyphs.inspect(call('glyphs', rich_path), owned)
        trace_text = '\n'.join(r['text'] for r in rich_report['runs'])
        check(all(text in trace_text for text in ('Production notebook', 'Editable caption', 'Editable footnote.', 'Editable endnote.')),
              'actual header, nested text box and both note stories participate in glyph identity')
        check(any(r['frames'] for r in rich_report['runs'] if 'Editable caption' in r['text']), 'rotated text-box glyphs retain enclosing transform')
        check(rich_report['unknown_text_range_glyphs'] > 0 and 'unknown-glyph-text-ranges' in rich_report['pending_qualification'],
              'generated labels retain exact font and glyph identity while explicitly reporting absent cluster ranges')
        check(args.rich.read_bytes() == rich_source, 'original rich fixture remains unchanged')

        refused('wrong packet marker', lambda: glyphs.inspect(b'WRONGTAG'+packet[8:], owned), 'packet is invalid')
        refused('truncated packet', lambda: glyphs.inspect(packet[:-1], owned), 'font length mismatch')
        refused('oversized declared header', lambda: glyphs.inspect(packet[:8]+(17 << 20).to_bytes(4, 'little')+packet[12:], owned), 'header exceeds')
        refused('unowned native face', lambda: glyphs.inspect(packet, []), 'unowned font')
        damaged = bytearray(packet); damaged[-1] ^= 1
        refused('modified native font bytes', lambda: glyphs.inspect(bytes(damaged), owned), 'unowned font')
        mutate('unknown header field', lambda h: h.update(extra=True), 'unknown or missing fields')
        mutate('schema bool', lambda h: h.update(schemaVersion=True), 'integer bounds')
        mutate('old schema omits substitution contract', lambda h: h.update(schemaVersion=1), 'integer bounds')
        mutate('unknown substitution field', lambda h: h['substitutions'][0].update(extra=True), 'unknown or missing fields')
        mutate('duplicate substitution', lambda h: h['substitutions'].append(copy.deepcopy(h['substitutions'][0])), 'substitution is duplicated')
        mutate('empty substitution name', lambda h: h['substitutions'][0].update(requested=''), 'substitution name')
        mutate('wrong display mode', lambda h: h.update(display='pdf'), 'display is unsupported')
        mutate('glyph aggregate mismatch', lambda h: h.update(glyphCount=1), 'aggregate counts')
        mutate('invalid page dimensions', lambda h: h['pages'][0].__setitem__(0, 1585), 'page dimensions')
        mutate('face index outside standalone font', lambda h: h['faces'][0].update(index=1), 'standalone face index')
        mutate('variable face coordinates', lambda h: h['faces'][0].update(coordinates=[[[119,103,104,116], 700]]), 'variable-font identity')
        mutate('wrong font units', lambda h: h['faces'][0].update(unitsPerEm=2048), 'units disagree')
        mutate('font byte aliasing', lambda h: h['faces'][1].update(offset=0), 'font offset')
        mutate('run unknown face', lambda h: h['runs'][0].update(font=64), 'run face')
        mutate('duplicate draw identity', lambda h: h['runs'].append(copy.deepcopy(h['runs'][0])), 'duplicates a draw path')
        mutate('unknown frame', lambda h: h['runs'][0].update(frames=[{'kind': 'unknown'}]), 'frame kind')
        mutate('negative clip dimensions', lambda h: h['runs'][0].update(frames=[{'kind': 'clip', 'rect': [0,0,-1,10]}]), 'clip size')
        mutate('invalid matrix dimensions', lambda h: h['runs'][0].update(frames=[{'kind': 'transform', 'matrix': [1,0,0,1]}]), 'wrong dimensions')
        mutate('wrong synthetic style type', lambda h: h['runs'][0].update(syntheticBold=1), 'not boolean')
        mutate('missing glyph zero', lambda h: h['runs'][0]['glyphs'][0].__setitem__(0, 0), 'glyph ID')
        mutate('glyph outside font', lambda h: h['runs'][0]['glyphs'][0].__setitem__(0, 65535), 'glyph ID')
        mutate('missing range', lambda h: h['runs'][0]['ranges'].pop(), 'ranges do not cover')
        mutate('false unknown range state', lambda h: h['runs'][0].update(rangesKnown=False), 'unknown ranges must be empty')
        mutate('nonboolean range state', lambda h: h['runs'][0].update(rangesKnown=1), 'range state is invalid')
        mutate('range outside text', lambda h: h['runs'][0]['ranges'][0].__setitem__(1, 9999), 'range end')
        mutate('UTF-8 split', lambda h: h['runs'][0].update(text='é'+h['runs'][0]['text'][1:]), 'splits UTF-8')
        mutate('excessive font size', lambda h: h['runs'][0].update(size=1639), 'numeric bounds')
        check(args.embedded.read_bytes() == source, 'original embedded document remains byte-identical')
        (out/'glyphs.json').write_text(json.dumps(report, indent=2)+'\n')
        (out/'ligature-glyphs.json').write_text(json.dumps(ligature_report, indent=2)+'\n')
        (out/'rich-glyphs.json').write_text(json.dumps(rich_report, indent=2)+'\n')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'original_glyphs': report['glyph_count'], 'original_cmap_matches': report['direct_cmap_matches'],
                    'ligature_glyphs': ligature_report['glyph_count'], 'ligature_clusters': ligature_report['contextual_or_ligature_glyphs'],
                    'native_font_sha256': expected_sha, 'remote_actions': False, 'engine_admission_complete': False,
                    'scope': 'actual PNG-display faces, font bytes, glyph IDs, text ranges and cold identity; arbitrary shaping, outlines and document execution remain unqualified'}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally: (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
