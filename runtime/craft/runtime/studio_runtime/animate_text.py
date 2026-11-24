"""Interpret actual native shaping and stored-outline evidence, without repairing it.

The maintained engine embeds the catalog's pinned font bytes. Glyph coverage and
reproduction of that engine's layout do not prove full bidirectional layout or
publication fidelity. Substitutions and stale outlines are returned as issues.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

from .animate_diagnostics import integer
from .animate_format import number
from .animate_graph import fields
from .animate_properties import f32
from .animate_unicode import trim, contains, WHITESPACE

CATALOG = json.loads(Path(__file__).with_name('animate_fonts.json').read_text())
MODEL = 'one shaping run per paragraph; space wrapping; no bidirectional itemization'


def targets(profile):
    result = []
    document = profile['envelope']['document']
    timelines = [(('scene', i), scene['timeline']) for i, scene in enumerate(document['scenes'])]
    timelines += [(('symbol', symbol['id']), symbol['timeline']) for symbol in document['library']]
    for owner, timeline in timelines:
        for layer in timeline['layers']:
            for ki, key in enumerate(layer['keyframes']):
                for ei, element in enumerate(key.get('elements', [])):
                    kind = element['kind']
                    if not isinstance(kind, dict) or 'Text' not in kind:
                        continue
                    body = kind['Text']
                    if len(body['text']) > 8192 or len(body['text'].encode('utf-8')) > 32768:
                        raise ValueError('Animate stored text exceeds the native shaping budget')
                    result.append({'selector': {owner[0]: owner[1], 'layer': layer['id'],
                                                'frame': key['start'], 'element': element['id']},
                                   'body': body, 'outline': profile['graph']['path_slots'][(owner, layer['id'], ki, ei)]})
    return result


def batches(items):
    current = []; size = 0
    for item in items:
        count = len(item['body']['text'])
        if current and (len(current) == 32 or size + count > 8192):
            yield current; current = []; size = 0
        current.append(item); size += count
    if current:
        yield current


def ascii_lower(text):
    return text.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


def finite(value, label):
    if not number(value, -1e9, 1e9):
        raise ValueError('Animate text report has invalid ' + label)
    return f32(value)


def inspect(report, target):
    fields(report, ('family', 'requested_family', 'family_match', 'style_match', 'face', 'missing_characters',
        'notdef_glyphs', 'draw_failures', 'unavailable_outlines', 'width', 'height', 'ascent', 'line_height',
        'lines', 'outline_commands', 'ink_bounds', 'runs', 'drawn', 'document_changed', 'layout_model',
        'stored_outline_matches', 'stored_metrics_match', 'stored_style_unchanged', 'element', 'layer', 'keyframe'), (), 'stored text report')
    body = target['body']; source = body['text']; selector = target['selector']
    for key, selected in [('element', 'element'), ('layer', 'layer'), ('keyframe', 'frame')]:
        integer(report[key], selector[selected], selector[selected], 'stored text ' + key)
    for key in ('family_match', 'style_match', 'stored_outline_matches', 'stored_metrics_match', 'stored_style_unchanged'):
        if type(report[key]) is not bool:
            raise ValueError('Animate text report requires boolean qualification flags')
    if report['document_changed'] is not False or report['layout_model'] != MODEL or report['requested_family'] != body['font']:
        raise ValueError('Animate text report disagrees with the saved source or layout model')
    face = report['face']
    fields(face, ('file', 'index', 'bytes', 'postscript', 'weight', 'italic'), (), 'text face')
    if not isinstance(face['file'], str) or face['file'] not in CATALOG['faces']:
        raise ValueError('Animate text report did not select a pinned embedded face')
    known = CATALOG['faces'][face['file']]
    if any(type(face[key]) is not type(known[key]) or face[key] != known[key]
           for key in ('index', 'bytes', 'postscript', 'weight', 'italic')) or report['family'] != known['family']:
        raise ValueError('Animate text face identity disagrees with its pinned source')
    family_match = ascii_lower(trim(body['font'])) == ascii_lower(report['family'])
    style_match = face['weight'] == (700 if body.get('bold', False) else 400) and face['italic'] == body.get('italic', False)
    if report['family_match'] != family_match or report['style_match'] != style_match:
        raise ValueError('Animate native font-match flags are inconsistent')
    for key in ('width', 'height', 'ascent', 'line_height'):
        finite(report[key], key)
    metrics_match = all(f32(report[key]) == f32(body['box_'+key]) for key in ('width', 'height'))
    style_unchanged = (1 <= f32(body['size']) <= 2000
        and all(-1000 <= f32(body.get(key, 0)) <= 1000 for key in ('letter_spacing', 'line_spacing'))
        and (body.get('width') is None or 0 < f32(body['width']) <= 100000))
    if report['stored_metrics_match'] != metrics_match or report['stored_style_unchanged'] != style_unchanged:
        raise ValueError('Animate stored metrics/style flags disagree with saved typography')
    integer(report['lines'], 1, 40961, 'text lines')
    integer(report['outline_commands'], 0, 250000, 'text outline commands')
    if report['stored_outline_matches'] and report['outline_commands'] != len(target['outline'].commands):
        raise ValueError('Animate stored outline count disagrees with native equality evidence')
    ink = report['ink_bounds']
    if report['outline_commands'] == 0:
        if ink is not None:
            raise ValueError('Animate empty text outline has unexpected ink bounds')
    elif (not isinstance(ink, list) or len(ink) != 4
          or not all(number(x, -1e9, 1e9) for x in ink) or ink[0] > ink[2] or ink[1] > ink[3]):
        raise ValueError('Animate text ink bounds are invalid')
    offsets = {}; at = 0
    for char in source:
        offsets[at] = char; at += len(char.encode('utf-8'))
    paragraphs = []; start = 0
    for paragraph in source.split('\n'):
        raw = paragraph.encode('utf-8'); length = len(raw) - raw.endswith(b'\r')
        paragraphs.append((start, length)); start += len(raw)+1
    runs = report['runs']; drawn = report['drawn']
    if not isinstance(runs, list) or len(runs) != len(paragraphs) or not isinstance(drawn, list) or len(drawn) > 32768:
        raise ValueError('Animate text report omitted paragraphs or exceeded its glyph budget')
    glyphs = Counter(); glyph_count = notdef = 0; issues = set()
    for run, (start, length) in zip(runs, paragraphs):
        fields(run, ('byte_start', 'byte_length', 'direction', 'script', 'glyphs'), (), 'shaping run')
        integer(run['byte_start'], start, start, 'paragraph byte start')
        integer(run['byte_length'], length, length, 'paragraph byte length')
        if (run['direction'] not in ('LeftToRight', 'RightToLeft', 'Invalid')
                or not isinstance(run['script'], str) or len(run['script']) > 64
                or not isinstance(run['glyphs'], list)):
            raise ValueError('Animate shaping run is invalid')
        glyph_count += len(run['glyphs'])
        if glyph_count > 32768:
            raise ValueError('Animate text report exceeds its shaped glyph budget')
        if length and not run['glyphs']:
            issues.add('source paragraph has no shaped glyphs')
        for glyph in run['glyphs']:
            fields(glyph, ('glyph', 'cluster', 'x_offset', 'y_offset', 'advance'), (), 'shaped glyph')
            gid = integer(glyph['glyph'], 0, known['glyphs']-1, 'glyph identity')
            cluster = integer(glyph['cluster'], start, start+length-1, 'glyph cluster')
            if cluster not in offsets:
                raise ValueError('Animate glyph cluster splits a UTF-8 character')
            for key in ('x_offset', 'y_offset', 'advance'):
                finite(glyph[key], key)
            notdef += gid == 0
            glyphs[(gid, cluster, f32(glyph['advance']))] += 1
    integer(report['notdef_glyphs'], notdef, notdef, 'notdef glyph count')
    integer(report['draw_failures'], 0, len(drawn), 'glyph draw failures')
    integer(report['unavailable_outlines'], 0, glyph_count, 'unavailable glyph outlines')
    commands = 0
    for glyph in drawn:
        fields(glyph, ('glyph', 'cluster', 'line', 'x', 'y', 'advance', 'outline_commands'), (), 'drawn glyph')
        integer(glyph['glyph'], 0, known['glyphs']-1, 'drawn glyph identity')
        integer(glyph['cluster'], 0, max(at-1, 0), 'drawn glyph cluster')
        integer(glyph['line'], 0, report['lines']-1, 'drawn line')
        for key in ('x', 'y', 'advance'):
            finite(glyph[key], key)
        key = (glyph['glyph'], glyph['cluster'], f32(glyph['advance']))
        if glyphs[key] <= 0:
            raise ValueError('Animate drawing contains a glyph absent from shaping')
        glyphs[key] -= 1
        commands += integer(glyph['outline_commands'], 0, 250000, 'drawn outline commands')
    if commands != report['outline_commands']:
        raise ValueError('Animate drawn outline total is inconsistent')
    if any(count and not contains(WHITESPACE, offsets[key[1]]) for key, count in glyphs.items()):
        issues.add('some non-whitespace shaped glyphs were not drawn')
    missing = report['missing_characters']
    if not isinstance(missing, list) or len(missing) > len(source):
        raise ValueError('Animate missing-character report is invalid')
    previous = -1
    for item in missing:
        fields(item, ('byte', 'character'), (), 'missing character')
        offset = integer(item['byte'], previous+1, max(at-1, 0), 'missing character offset')
        if offset not in offsets or item['character'] != offsets[offset]:
            raise ValueError('Animate missing-character evidence disagrees with saved text')
        previous = offset
    if missing: issues.add('font lacks source characters')
    if notdef: issues.add('shaping produced notdef glyphs')
    if report['draw_failures']: issues.add('native glyph drawing failed')
    if report['unavailable_outlines']: issues.add('font outlines unavailable')
    coverage = not issues
    if not family_match: issues.add('requested font family was substituted')
    if not style_match: issues.add('requested font style was substituted')
    if not metrics_match: issues.add('stored text metrics are stale')
    if not report['stored_outline_matches']: issues.add('stored text outline is stale')
    if not style_unchanged: issues.add('stored text style would be clamped')
    return {'selector': selector, 'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'requested_family': body['font'], 'actual_family': report['family'],
            'face': {**face, 'sha256': known['sha256']}, 'glyphs': glyph_count,
            'drawn_glyphs': len(drawn), 'outline_commands': commands,
            'missing_characters': missing, 'glyph_coverage_verified': coverage,
            'native_layout_reproduced': not issues, 'issues': sorted(issues),
            'bidirectional_itemization_verified': False, 'publication_authorized': False}
