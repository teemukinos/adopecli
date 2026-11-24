"""Interpret native shaping evidence without treating it as full publication approval.

Fallbacks require explicit requested/actual family and style pairs. Clipping,
paint visibility, effects and complete document preservation have separate gates.
"""
import re
import json

from .interface_document import number

HASH = re.compile(r'[0-9a-f]{64}')


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def whitespace(char):
    """Unicode White_Space, matching Rust char::is_whitespace (not Python's C0 additions)."""
    value = ord(char)
    return (9 <= value <= 13 or value in (0x20, 0x85, 0xa0, 0x1680, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000)
            or 0x2000 <= value <= 0x200a)


def nonprinting(char):
    value = ord(char)
    return (whitespace(char) or value in (0x00ad, 0x034f, 0x061c, 0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2060, 0xfeff)
            or 0x202a <= value <= 0x202e or 0x2066 <= value <= 0x2069
            or 0xfe00 <= value <= 0xfe0f or 0xe0100 <= value <= 0xe01ef)


def coordinates(values):
    return isinstance(values, list) and len(values) <= 64 and all(integer(v, -32768, 32767) for v in values)


def variations_available(style, face):
    axes = {axis['tag']: axis for axis in face['axes']}
    return all(tag in axes and number(value, axes[tag]['min'], axes[tag]['max'])
               for tag, value in style['variations'].items())


def inspect(report, node, allowed_fallbacks=()):
    """Return shaping issues and actual face identities for one saved native text node.

    `allowed_fallbacks` contains (requested family, requested style, actual family,
    actual style) tuples. It never excuses a missing requested family/style,
    a missing glyph, an ignored variation, truncation or lost source characters.
    """
    if (not isinstance(node, dict) or node.get('type') != 'text' or not isinstance(node.get('characters'), str)
            or not integer(node.get('id'), 1, 2**64 - 1)):
        raise ValueError('Interface text qualification requires a native text node')
    source = node['characters']
    if (not isinstance(report, dict) or report.get('version') != 2 or report.get('id') != node['id']
            or not integer(report.get('source_characters'), 0, 16_384) or report['source_characters'] != len(source)
            or report.get('publication_approved') is not False
            or type(report.get('truncated')) is not bool or type(report.get('on_path')) is not bool):
        raise ValueError('Interface text diagnostics do not match the native node or supported version')
    if not isinstance(allowed_fallbacks, (list, tuple)) or len(allowed_fallbacks) > 128:
        raise ValueError('Interface allows at most 128 explicit font fallback approvals')
    allowed = set()
    for item in allowed_fallbacks:
        if (not isinstance(item, (tuple, list)) or len(item) != 4
                or not all(isinstance(v, str) and 0 < len(v) <= 128 for v in item)):
            raise ValueError('Interface fallback approval requires four explicit font names')
        allowed.add(tuple(item))
    faces, styles, glyphs = (report.get(key) for key in ('faces', 'styles', 'glyphs'))
    if (not isinstance(faces, list) or len(faces) > 512 or not isinstance(styles, list) or len(styles) > 16_384
            or not isinstance(glyphs, list) or len(glyphs) > 32_768):
        raise ValueError('Interface text diagnostics exceed their collection budgets')
    for face in faces:
        if (not isinstance(face, dict) or not isinstance(face.get('sha256'), str) or not HASH.fullmatch(face['sha256'])
                or not integer(face.get('index'), 0, 2**32 - 1)
                or not all(isinstance(face.get(k), str) and 0 < len(face[k]) <= 128 for k in ('family', 'style'))
                or not isinstance(face.get('axes'), list) or len(face['axes']) > 64):
            raise ValueError('Interface text diagnostics contain an invalid font identity')
        tags = set()
        for axis in face['axes']:
            if (not isinstance(axis, dict) or not isinstance(axis.get('tag'), str) or len(axis['tag']) != 4
                    or axis['tag'] in tags or not all(number(axis.get(k), -1e6, 1e6) for k in ('min', 'max', 'default'))
                    or not axis['min'] <= axis['default'] <= axis['max']):
                raise ValueError('Interface text diagnostics contain invalid font axes')
            tags.add(axis['tag'])
    issues = set()
    native_styles = [node.get('style', {})] + [run.get('style', {}) for run in node.get('runs', [])]
    def style_key(style, native=False):
        names = ('font_family', 'font_style', 'font_size') if native else ('family', 'style', 'size')
        # Canonical numeric form makes native integer/float font sizes equivalent.
        size = style.get(names[2])
        return json.dumps([style.get(names[0]), style.get(names[1]), float(size) if number(size, 1, 500) else None,
                           style.get('case', 'original'), style.get('variations', {})], sort_keys=True)
    expected_styles = {style_key(style, True) for style in native_styles}
    for style in styles:
        if (not isinstance(style, dict) or not all(isinstance(style.get(k), str) for k in ('family', 'style'))
                or not number(style.get('size'), 1, 500) or not isinstance(style.get('variations'), dict)
                or len(style['variations']) > 64
                or type(style.get('family_available')) is not bool or type(style.get('style_available')) is not bool):
            raise ValueError('Interface text diagnostics contain an invalid requested style')
        if style_key(style) not in expected_styles:
            raise ValueError('Interface text diagnostics disagree with saved typography')
        if not style['family_available'] or not style['style_available']:
            issues.add('requested font family or style is unavailable')
        primary = style.get('primary')
        if (not isinstance(primary, dict) or not integer(primary.get('face'), 0, len(faces) - 1)
                or not coordinates(primary.get('coords_f2dot14'))):
            raise ValueError('Interface text diagnostics omit the selected primary face')
        if not variations_available(style, faces[primary['face']]):
            issues.add('requested font variation is unavailable or would be clamped')
    # Many glyphs can share one long cluster. Range deltas keep this linear in
    # glyphs plus source characters instead of repeatedly filling that cluster.
    coverage = [0] * (len(source) + 1)
    missing = 0
    substitutions = set()
    checked_variations = set()
    for glyph in glyphs:
        if (not isinstance(glyph, dict) or not integer(glyph.get('face'), 0, len(faces) - 1)
                or not integer(glyph.get('style'), 0, len(styles) - 1) or not integer(glyph.get('gid'), 0, 2**32 - 1)
                or not integer(glyph.get('start'), 0, len(source)) or not integer(glyph.get('end'), glyph['start'], len(source))
                or not coordinates(glyph.get('coords_f2dot14')) or type(glyph.get('coordinates_match_style')) is not bool
                or type(glyph.get('rtl')) is not bool
                or not number(glyph.get('size'), 0.001, 500)
                or not all(number(glyph.get(k), -1e9, 1e9) for k in ('x', 'y', 'size', 'advance'))):
            raise ValueError('Interface text diagnostics contain an invalid glyph or cluster')
        start, end = glyph['start'], glyph['end']
        coverage[start] += 1
        coverage[end] -= 1
        missing += glyph['gid'] == 0
        style, face = styles[glyph['style']], faces[glyph['face']]
        pair = (glyph['style'], glyph['face'])
        if pair not in checked_variations:
            checked_variations.add(pair)
            if not variations_available(style, face):
                issues.add('shaped font cannot honor the requested variation')
        primary = faces[style['primary']['face']]
        same_face = (face['sha256'], face['index']) == (primary['sha256'], primary['index'])
        if not same_face:
            substitution = (style['family'], style['style'], face['family'], face['style'])
            substitutions.add(substitution)
            if substitution not in allowed:
                issues.add('a shaped font fallback requires explicit approval')
        if (not glyph['coordinates_match_style']
                or same_face and glyph['coords_f2dot14'] != style['primary']['coords_f2dot14']):
            issues.add('shaped variation coordinates disagree with the requested style')
    if not integer(report.get('missing_glyphs'), 0, len(glyphs)) or missing != report['missing_glyphs']:
        raise ValueError('Interface text diagnostics have an inconsistent missing-glyph count')
    if missing:
        issues.add('text contains missing glyphs')
    covered = []
    active = 0
    for delta in coverage[:-1]:
        active += delta
        covered.append(active > 0)
    unmapped = [{'index': i, 'codepoint': ord(c), 'whitespace': whitespace(c), 'control': ord(c) < 32 or 0x7f <= ord(c) <= 0x9f}
                for i, c in enumerate(source) if not covered[i]]
    if report.get('unmapped') != unmapped:
        raise ValueError('Interface text diagnostics have inconsistent source coverage')
    if any(not covered[i] and not nonprinting(c) for i, c in enumerate(source)):
        issues.add('visible source characters have no shaped cluster')
    if report['truncated']:
        issues.add('native text layout is truncated')
    bounds = report.get('ink_bounds')
    if (bounds is not None and (not isinstance(bounds, list) or len(bounds) != 4
                               or not all(number(v, -1e9, 1e9) for v in bounds)
                               or bounds[0] > bounds[2] or bounds[1] > bounds[3])):
        raise ValueError('Interface text diagnostics contain invalid ink bounds')
    return {'id': node['id'], 'shaping_verified': not issues, 'publication_approved': False,
            'issues': sorted(issues), 'glyphs': len(glyphs), 'faces': faces,
            'fallbacks': [list(row) for row in sorted(substitutions)], 'ink_bounds': bounds,
            'clipping_verified': False}
