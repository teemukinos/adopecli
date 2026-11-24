"""Optimistic typed edits of the complete native Write model.

All selectors and expectations bind to one original revision. Only declared
text/format/page changes occur; original bytes remain the caller's immutable
source. This predicts a new model, not permission to execute or publish it.
"""
import copy
import hashlib
import json
import re

from .write_container import inspect_bytes, require, strict_json
from .write_structure import inspect as inspect_structure

KINDS = {'text.replace', 'text.format', 'paragraph.properties', 'section.properties'}
HISTORY = {'ins', 'del', 'fmtChange', 'numChange'}


def canonical(value): return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def locate(document, path):
    value = document
    for key in path.split('/')[1:]: value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def patch_properties(before, edit):
    values = edit['set']; removed = edit['unset']
    require(type(values) is dict and type(removed) is list and all(type(k) is str for k in removed), 'revision property patch has invalid types')
    require(len(removed) == len(set(removed)) and not set(values) & set(removed), 'revision property patch has duplicate or conflicting keys')
    require(not (set(values) | set(removed)) & HISTORY and not any(before.get(k) is not None for k in HISTORY),
            'revision history requires a tracked-edit operation')
    require(bool(values or removed) and all(k in before for k in removed), 'revision property patch is empty or removes absent values')
    result = copy.deepcopy(before)
    for key in removed: del result[key]
    result.update(copy.deepcopy(values)); return result


def span(block, edit):
    data = block['text'].encode('utf-8'); start = edit['start']; end = edit['end']
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(data), 'revision requires a nonempty bounded UTF-8 range')
    require(type(edit['expected']) is str, 'revision expected text is invalid')
    try: actual = data[start:end].decode('utf-8'); data[:start].decode('utf-8'); data[end:].decode('utf-8')
    except UnicodeError as error: raise ValueError('Write revision range splits UTF-8') from error
    require(actual == edit['expected'], 'revision expected text differs from original')
    require('\ufffc' not in actual, 'revision cannot replace inline objects or range markers')
    return data, start, end


def segments(block, start, end):
    before = []; selected = []; after = []; cursor = 0
    for run in block['runs']:
        stop = cursor+run['len']
        for low, high, destination in ((cursor, min(stop, start), before), (max(cursor, start), min(stop, end), selected), (max(cursor, end), stop, after)):
            if low < high: destination.append({**copy.deepcopy(run), 'len': high-low})
        cursor = stop
    return before, selected, after


def edit_text(block, edit):
    data, start, end = span(block, edit); before, selected, after = segments(block, start, end)
    require(all(not any(run.get('props', {}).get(k) is not None for k in HISTORY) for run in selected),
            'revision selected text contains tracked history')
    if edit['kind'] == 'text.format':
        for run in selected:
            value = patch_properties(run.get('props', {}), edit)
            if value: run['props'] = value
            else: run.pop('props', None)
        block['runs'] = before+selected+after
        return
    replacement = edit['value']
    require(type(replacement) is str and not any(c in replacement for c in ('\ufffc', '\r', '\n'))
            and not any(0xd800 <= ord(c) <= 0xdfff for c in replacement), 'revision replacement requires paragraph text without object markers')
    encoded = replacement.encode('utf-8'); require(len(encoded) <= 1 << 20, 'revision replacement exceeds its byte budget')
    styles = {canonical({k: v for k, v in run.items() if k != 'len'}) for run in selected}
    require(len(styles) == 1, 'revision replacement spans different formatting; select a uniform range explicitly')
    middle = [{**copy.deepcopy(selected[0]), 'len': len(encoded)}] if encoded else []
    # Preserve original boundaries outside the selected region. Rejoin only the
    # surviving pieces of the originally touched run, never unrelated neighbors.
    cursor = 0; start_inside = False; end_inside = False
    for run in block['runs']:
        stop = cursor+run['len']; start_inside |= cursor < start < stop; end_inside |= cursor < end < stop; cursor = stop
    if middle and before and start_inside:
        before[-1]['len'] += middle[0]['len']; middle = []
        if after and end_inside: before[-1]['len'] += after.pop(0)['len']
    elif middle and after and end_inside:
        middle[0]['len'] += after.pop(0)['len']
    elif not encoded and before and after and start_inside and end_inside:
        before[-1]['len'] += after.pop(0)['len']
    block['text'] = (data[:start]+encoded+data[end:]).decode('utf-8')
    block['runs'] = before+middle+after


def revise_bytes(data, expected_sha256, edits):
    require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256) is not None,
            'revision requires the exact original SHA-256')
    require(type(data) is bytes and hashlib.sha256(data).hexdigest() == expected_sha256, 'revision source hash is stale')
    require(type(edits) is list and 1 <= len(edits) <= 128, 'revision requires one to 128 typed edits')
    try: encoded_request = canonical(edits).encode('ascii')
    except (TypeError, ValueError, RecursionError) as error: raise ValueError('Write revision request is not bounded JSON') from error
    require(len(encoded_request) <= 1 << 20, 'revision request exceeds its byte budget')
    # Reuse the bounded strict parser for nested caller values, not json.loads alone.
    edits = strict_json(encoded_request)
    original = inspect_bytes(data, 'json')['document']; profile = inspect_structure(original)
    settings = original['settings']
    require(not settings.get('trackChanges') and settings.get('protection') in (None, 'none') and not settings.get('protectFormatting') and not settings.get('protectHash'),
            'revision requires a separately qualified tracked/protected editing path')
    paragraphs = {item['path']: item for item in profile['paragraphs']}
    sections = {'/lastSection'} | {path+'/section' for path in paragraphs if locate(original, path).get('section') is not None}
    require(not any(locate(original, path).get('formProt') for path in sections), 'revision document has protected sections')
    guarded_stories = {item['story'] for item in profile['objects'] if item['type'] in ('controlStart', 'controlEnd', 'permStart', 'permEnd', 'fieldStart', 'fieldEnd')}
    spans = {}; properties = set(); bound = []
    for edit in edits:
        require(type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in KINDS and type(edit.get('path')) is str,
                'revision kind or selector is invalid')
        kind = edit['kind']; path = edit['path']; is_text = kind.startswith('text.')
        fields = {'kind', 'path', 'expected'} | ({'start', 'end'} if is_text else set()) | ({'value'} if kind == 'text.replace' else {'set', 'unset'})
        require(set(edit) == fields, 'revision fields differ from the typed operation')
        require(path in (sections if kind == 'section.properties' else paragraphs), 'revision selector is not an owned paragraph or section')
        if path in paragraphs: require(paragraphs[path]['story'] not in guarded_stories, 'revision story contains protected/control/complex-field ranges')
        target = locate(original, path)
        if is_text:
            _, start, end = span(target, edit)
            require(all(end <= low or start >= high for low, high in spans.get(path, [])), 'revision text ranges overlap')
            spans.setdefault(path, []).append((start, end))
        else:
            require(path not in properties, 'revision property target is duplicated'); properties.add(path)
            value = target if kind == 'section.properties' else target.get('props', {})
            require(type(edit['expected']) is dict and canonical(value) == canonical(edit['expected']), 'revision expected properties differ from original')
            patch_properties(value, edit)
        bound.append(edit)
    result = copy.deepcopy(original)
    # Descending ranges remain valid against the original byte coordinate system.
    for edit in sorted(bound, key=lambda e: (e['path'], -e.get('start', -1))):
        target = locate(result, edit['path']); kind = edit['kind']
        if kind.startswith('text.'): edit_text(target, edit)
        elif kind == 'paragraph.properties':
            changed = patch_properties(target.get('props', {}), edit)
            if changed: target['props'] = changed
            else: target.pop('props', None)
        else:
            changed = patch_properties(target, edit); target.clear(); target.update(changed)
    after = inspect_structure(result)
    encoded = (json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':'))+'\n').encode('utf-8')
    strict_json(encoded)
    require(canonical(result) != canonical(original), 'revision makes no document change')
    return {'data': encoded, 'document': result, 'source_sha256': expected_sha256, 'revision_sha256': hashlib.sha256(encoded).hexdigest(),
            'edits': edits, 'changed_paths': sorted({e['path'] for e in edits}), 'structure': after,
            'pending_qualification': sorted(set(after['pending_qualification']) | {'complete-resource-admission', 'native-full-model-comparison', 'source-format-fidelity'}),
            'engine_admission_complete': False}
