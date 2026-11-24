"""Typed editable publications with native preservation and cold-reopen checks."""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
import tempfile

from . import audio, layout_document as document, pdf, photo, video
from .layout_engine import Engine, VERSION

OPERATIONS = ('layout.create', 'layout.import', 'layout.inspect', 'layout.edit')
FONT_FIELDS = {'font_family', 'font_style', 'size', 'leading'}
FONT_NATIVE = {'font_family': 'fontFamily', 'font_style': 'fontStyle', 'size': 'size', 'leading': 'leading'}
FITS = {'contain': 'fitProportionally', 'cover': 'fillProportionally', 'stretch': 'fitContentToFrame'}


def engine():
    return 'dobe-layout'


def text(value, maximum=10000, empty=False):
    return (isinstance(value, str) and (empty or bool(value)) and len(value.encode('utf-8', errors='replace')) <= maximum
            and not any(ord(c) < 32 and c not in '\n\t' or 0xd800 <= ord(c) <= 0xdfff
                        or 0xe000 <= ord(c) <= 0xf8ff for c in value))


def font_fields(value, required=False):
    if required and not {'font_family', 'font_style', 'size'} <= value.keys():
        raise ValueError('Layout text requires explicit font_family, font_style and size')
    for key in FONT_FIELDS & value.keys():
        valid = text(value[key], 128) if key in ('font_family', 'font_style') else video.finite(value[key], 1, 500)
        if not valid:
            raise ValueError('invalid Layout typography: ' + key)


def rectangle(value):
    return (isinstance(value, list) and len(value) == 4 and all(video.finite(v, 0, 8192) for v in value)
            and value[0] < value[2] and value[1] < value[3])


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported Layout operation or parameters')
    new = operation in ('layout.create', 'layout.import')
    if new and source_revision is not None or not new and not source_revision:
        raise ValueError('Layout creation/import requires a new project; inspection/edit requires a source revision')
    if operation == 'layout.create':
        if (set(params) - {'width', 'height', 'pages', 'title'}
                or not all(video.finite(params.get(k), 72, 8192) for k in ('width', 'height'))
                or not isinstance(params.get('pages'), list) or not 1 <= len(params['pages']) <= document.MAX_PAGES
                or not text(params.get('title', 'Untitled'), 200)):
            raise ValueError('Layout creation requires bounded page dimensions, pages and optional title')
        if math.ceil(params['width']) * math.ceil(params['height']) * (len(params['pages']) + 1) > document.MAX_PIXELS:
            raise ValueError('Layout creation exceeds the page rendering budget')
        names = set(); total_text = 0
        for page in params['pages']:
            if not isinstance(page, dict) or set(page) != {'objects'} or not isinstance(page['objects'], list):
                raise ValueError('each Layout page requires an objects list')
            for obj in page['objects']:
                if (not isinstance(obj, dict) or not video.named(obj.get('name')) or obj['name'] in names
                        or obj.get('type') not in ('text', 'image', 'rectangle', 'ellipse') or not rectangle(obj.get('rect'))):
                    raise ValueError('Layout objects require unique names, supported types and rectangles')
                names.add(obj['name'])
                if len(names) > 512 or obj['rect'][2] > params['width'] or obj['rect'][3] > params['height']:
                    raise ValueError('Layout object exceeds its page or object budget')
                fields = {'name', 'type', 'rect'}
                if obj['type'] == 'text':
                    fields |= FONT_FIELDS | {'text', 'color'}; font_fields(obj, True)
                    if not text(obj.get('text')):
                        raise ValueError('Layout text requires bounded nonempty text')
                    total_text += len(obj['text'].encode('utf-8'))
                elif obj['type'] == 'image':
                    fields |= {'asset', 'fit'}
                    if (not isinstance(obj.get('asset'), str) or not video.ASSET.fullmatch(obj['asset'])
                            or not isinstance(obj.get('fit', 'contain'), str) or obj.get('fit', 'contain') not in FITS):
                        raise ValueError('Layout image requires an imported asset and supported fitting mode')
                else:
                    fields |= {'color'}
                if set(obj) - fields or 'color' in obj and (not isinstance(obj['color'], str) or not video.COLOR.fullmatch(obj['color'])):
                    raise ValueError('Layout object contains unsupported fields or colour')
        if total_text > document.MAX_TEXT:
            raise ValueError('Layout text exceeds its publication budget')
    elif operation == 'layout.import':
        if (set(params) != {'asset', 'format'} or params['format'] not in ('native', 'idml')
                or not isinstance(params['asset'], str) or not video.ASSET.fullmatch(params['asset'])):
            raise ValueError('Layout import requires an imported asset and native or idml format')
    elif operation == 'layout.inspect':
        if params:
            raise ValueError('Layout inspection takes no parameters')
    else:
        if set(params) != {'edits'} or not isinstance(params['edits'], list) or not 1 <= len(params['edits']) <= 128:
            raise ValueError('Layout edit requires 1 to 128 named edits')
        targets = set()
        for edit in params['edits']:
            if not isinstance(edit, dict) or not video.named(edit.get('name')) or edit['name'] in targets:
                raise ValueError('Layout edits require unique named targets')
            targets.add(edit['name'])
            if edit.get('action') == 'replace_text':
                if (set(edit) != {'name', 'action', 'start', 'end', 'expected', 'text'}
                        or not video.integer(edit['start'], 0, document.MAX_TEXT)
                        or not video.integer(edit['end'], edit['start'], document.MAX_TEXT)
                        or not text(edit['expected'], document.MAX_TEXT, True) or not text(edit['text'], document.MAX_TEXT, True)
                        or edit['start'] == edit['end'] and not edit['text']):
                    raise ValueError('Layout replacement requires an exact UTF-8 range, expected text and replacement')
            elif edit.get('action') == 'move':
                if (set(edit) != {'name', 'action', 'dx', 'dy'}
                        or not all(video.finite(edit[k], -8192, 8192) for k in ('dx', 'dy'))):
                    raise ValueError('Layout move requires bounded dx and dy')
            elif edit.get('action') == 'typography':
                if set(edit) - FONT_FIELDS - {'name', 'action'} or not FONT_FIELDS & edit.keys():
                    raise ValueError('Layout typography edit requires supported font fields')
                font_fields(edit)
            elif edit.get('action') == 'replace_image':
                if (set(edit) != {'name', 'action', 'expected_sha256', 'asset', 'fit'}
                        or not isinstance(edit['expected_sha256'], str)
                        or not re.fullmatch('[0-9a-f]{64}', edit['expected_sha256'])
                        or not isinstance(edit['asset'], str) or not video.ASSET.fullmatch(edit['asset'])
                        or not isinstance(edit['fit'], str) or edit['fit'] not in FITS):
                    raise ValueError('Layout image replacement requires an expected SHA-256, imported asset and explicit fitting mode')
            else:
                raise ValueError('Layout edits support replace_text, replace_image, move and typography')


def assets(operation, params):
    if operation == 'layout.import':
        return {params['asset']: 'assets/' + params['asset'] + ('.idml' if params['format'] == 'idml' else '.designcraft')}
    if operation == 'layout.create':
        return {obj['asset']: 'assets/' + obj['asset'] + '.image' for page in params['pages']
                for obj in page['objects'] if obj['type'] == 'image'}
    if operation == 'layout.edit':
        return {edit['asset']: 'assets/' + edit['asset'] + '.image'
                for edit in params['edits'] if edit['action'] == 'replace_image'}
    return {}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replacement_content(item, asset, pixels, fit):
    """Predict a bounded placement without accepting native output as its own oracle.

    Native placement resets graphic options. Refuse anything that would silently
    lose clipping, wrapping, tint, automatic fitting or per-placement settings.
    The frame's transform is separate and is preserved, including prior moves.
    """
    content = item['content']
    if (set(content) != {'type', 'asset', 'size', 'xf', 'autoFit', 'fitAlign', 'crop'}
            or content['type'] != 'graphic' or content['autoFit'] != 'none'
            or content['fitAlign'] != 4 or content['crop'] != [0, 0, 0, 0]):
        raise ValueError('Layout image replacement requires a plain graphic without custom fitting, clipping, wrap or tint')
    path = item['path']; subpaths = path.get('subpaths', [])
    if len(subpaths) != 1 or len(subpaths[0].get('anchors', [])) != 4:
        raise ValueError('Layout image replacement requires a rectangular frame')
    points = [anchor.get('p', []) for anchor in subpaths[0]['anchors']]
    if any(len(point) != 2 or not all(video.finite(v, -8192, 8192) for v in point) for point in points):
        raise ValueError('Layout image replacement requires bounded frame coordinates')
    left, top = points[0]; right, bottom = points[2]
    corners = [[left, top], [right, top], [right, bottom], [left, bottom]]
    if (item['shape'] != 'rectangle' or left >= right or top >= bottom
            or path != {'subpaths': [{'anchors': [{'p': p} for p in corners], 'closed': True}]}):
        raise ValueError('Layout image replacement requires an unmodified rectangular path')
    width, height = pixels
    sx, sy = (right - left) / width, (bottom - top) / height
    if fit != 'stretch':
        sx = sy = (min if fit == 'contain' else max)(sx, sy)
    return {'type': 'graphic', 'asset': asset, 'size': list(pixels),
            'xf': [sx, 0, 0, sy, left + (right - left - sx * width) / 2,
                   top + (bottom - top - sy * height) / 2],
            'autoFit': 'none', 'fitAlign': 4, 'crop': [0, 0, 0, 0]}


def compact_replacements(state, hashes, replacements):
    """Mirror the pinned engine's merge-before-prune behavior for new placements.

    Saved sources have already been compacted. A file placement allocates one
    fresh identity even if saving later merges its bytes into an older asset.
    Keep the older record and every unrequested reference exactly unchanged.
    """
    for item, fresh in replacements:
        record = state['assets'][str(fresh)]
        matches = [int(key) for key, candidate in state['assets'].items()
                   if hashes[key] == hashes[str(fresh)] and candidate['mime'] == record['mime']
                   and candidate.get('page', 0) == 0 and candidate.get('pdfCrop', 'crop') == 'crop'
                   and candidate.get('link') is None]
        item['content']['asset'] = min(matches)
    # Conservatively count references throughout groups, parent pages and stories.
    # A false positive fails the exact native comparison; it cannot drop artwork.
    used = set(); pending = [value for key, value in state.items() if key != 'assets']
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if type(value.get('asset')) is int:
                used.add(str(value['asset']))
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    state['assets'] = {key: value for key, value in state['assets'].items() if key in used}
    return {key: hashes[key] for key in state['assets']}


def native_items(state):
    return {item['id']: item for spread in state['spreads'] for item in spread['items']}


def mapping_for(state):
    mapping = {}
    for item in native_items(state).values():
        kind = item['content']['type']
        if kind not in ('text', 'graphic', 'unassigned'):
            continue
        name = item.get('label')
        if not video.named(name) or name in mapping:
            name = 'frame_' + str(item['id'])
        if name in mapping:
            raise ValueError('Layout native frame names are ambiguous')
        mapping[name] = {'id': item['id'], 'type': kind}
        if kind == 'text':
            mapping[name]['story'] = item['content']['story']
    return mapping


def check_mapping(mapping, state):
    items = native_items(state); seen = set()
    if not isinstance(mapping, dict) or len(mapping) > 512:
        raise ValueError('Layout frame mapping exceeds its budget')
    for name, record in mapping.items():
        if (not video.named(name) or not isinstance(record, dict) or record.get('type') not in ('text', 'graphic', 'unassigned')
                or set(record) != ({'id', 'type', 'story'} if record['type'] == 'text' else {'id', 'type'})
                or not video.integer(record.get('id'), 1, 2**64 - 1) or record['id'] in seen):
            raise ValueError('invalid Layout native frame mapping')
        item = items.get(record['id']); seen.add(record['id'])
        if item is None or item['content']['type'] != record['type']:
            raise ValueError('Layout frame mapping does not match the native document')
        if record['type'] == 'text' and (item['content']['story'] != record['story'] or str(record['story']) not in state['stories']):
            raise ValueError('Layout mapped story does not exist')
    expected = {identity for identity, item in items.items()
                if item['content']['type'] in ('text', 'graphic', 'unassigned')}
    if seen != expected:
        raise ValueError('Layout frame mapping does not cover the native document')


def font_attrs(values):
    return {FONT_NATIVE[k]: {'kind': 'points', 'value': v} if k == 'leading' else v
            for k, v in values.items() if k in FONT_FIELDS}


def styled_story(story, attrs):
    result = copy.deepcopy(story); runs = []
    for run in result['chars']:
        run.setdefault('over', {}).update(copy.deepcopy(attrs))
        if runs and {k: v for k, v in runs[-1].items() if k != 'len'} == {k: v for k, v in run.items() if k != 'len'}:
            runs[-1]['len'] += run['len']
        else:
            runs.append(run)
    result['chars'] = runs; result['rev'] += 1
    return result


def pages_for_frames(state, ids):
    pages = set(); start = 0
    for spread in state['spreads']:
        if any(item['id'] in ids for item in spread['items']):
            pages.update(range(start, start + len(spread['pages'])))
        start += len(spread['pages'])
    return pages


def inspect(process, profile):
    summary = process.tool('inspect_document')
    if summary.get('pageCount') != len(profile['pages']):
        raise ValueError('Layout inspected page count disagrees with its native file')
    for story in summary.get('stories', []):
        if story.get('overset'):
            raise ValueError('Layout contains overset text')
    return summary


def validate_pdf(root, path, profile, *, executable=None):
    """Use the independent PDF engine to inspect exported pages and live text."""
    with pdf.Engine(root, executable=executable) as reader:
        doc, structure = reader.open(path)
        pages = structure['pages']
        if len(pages) != len(profile['pages']):
            raise ValueError('Layout PDF export changed the page count')
        for actual, expected in zip(pages, profile['pages']):
            if actual['rotation'] != 0 or any(abs(actual[k] - expected[k]) > 0.01 for k in ('width', 'height')):
                raise ValueError('Layout PDF export changed page dimensions')
        extracted = reader.tool('text_extract', doc=doc)
        if extracted.get('html_truncated') or any(p.get('truncated') for p in extracted['pages']):
            raise ValueError('Layout PDF text inspection was truncated')
        # Check ordinary visible, unthreaded stories. Complex imported tables,
        # notes and threaded stories remain subject to the native/IDML guards;
        # this check does not claim independent coverage of their PDF text.
        state = profile['document']; items = native_items(state); checked = []
        layers = {layer['id']: layer for layer in state['layers']}
        normalize = lambda value: ' '.join(value.split())
        for sid, story in state['stories'].items():
            if len(story['frames']) != 1 or any(0xe000 <= ord(c) <= 0xf8ff for c in story['text']):
                continue
            item = items.get(story['frames'][0])
            if item is None or item['hidden'] or item['nonprinting'] or item['opacity'] == 0:
                continue
            layer = layers[item['layer']]
            if not layer['visible'] or not layer['printable']:
                continue
            indexes = pages_for_frames(state, {item['id']})
            visible_text = normalize(' '.join(extracted['pages'][i]['text'] for i in sorted(indexes)))
            if normalize(story['text']) not in visible_text:
                raise ValueError('Layout PDF export lost an ordinary visible story')
            checked.append(sid)
    return {'sha256': structure['sha256'], 'pages': pages, 'text': extracted['pages'],
            'independently_checked_stories': checked, 'general_text_fidelity_qualified': False}


def requested(process, profile, params, mapping, raster_sources):
    """Verify actual native positions, text, typography, colour and artwork."""
    summary = inspect(process, profile)
    observed = {item['id']: (spread['index'], item) for spread in summary['spreads'] for item in spread['items']}
    items = native_items(profile['document']); state = profile['document']
    if state['title'] != params.get('title', 'Untitled'):
        raise ValueError('Layout did not retain the requested publication title')
    if (len(profile['pages']) != len(params['pages'])
            or any(page['width'] != params['width'] or page['height'] != params['height'] for page in profile['pages'])):
        raise ValueError('Layout page count or dimensions differ from the request')
    for page_number, page in enumerate(params['pages']):
        for request in page['objects']:
            record = mapping[request['name']]; item = items[record['id']]
            spread, actual = observed[record['id']]
            if spread != page_number or any(abs(a - b) > 1e-6 for a, b in zip(actual['bounds'], request['rect'])):
                raise ValueError('Layout frame geometry differs from the request')
            if request['type'] == 'text':
                story = state['stories'][str(record['story'])]
                if story['text'] != request['text'] or any(any(run.get('over', {}).get(k) != v for k, v in font_attrs(request).items()) for run in story['chars']):
                    raise ValueError('Layout text or typography differs from the request')
                swatch_names = {run['over']['fill'] for run in story['chars']} if 'color' in request else set()
            elif request['type'] == 'image':
                asset = str(item['content']['asset'])
                if profile['assets'][asset] != raster_sources[request['asset']]['sha256']:
                    raise ValueError('Layout embedded artwork differs from the requested source')
                width, height = raster_sources[request['asset']]['pixels']
                left, top, right, bottom = request['rect']
                sx, sy = (right - left) / width, (bottom - top) / height
                if request.get('fit', 'contain') != 'stretch':
                    sx = sy = (min if request.get('fit', 'contain') == 'contain' else max)(sx, sy)
                transform = [sx, 0, 0, sy, left + (right - left - sx * width) / 2, top + (bottom - top - sy * height) / 2]
                if any(abs(a - b) > 1e-6 for a, b in zip(item['content']['xf'], transform)):
                    raise ValueError('Layout artwork fitting differs from the request')
                swatch_names = set()
            else:
                if item['shape'] != {'rectangle': 'rectangle', 'ellipse': 'oval'}[request['type']]:
                    raise ValueError('Layout vector shape differs from the request')
                if item['stroke']['swatch'] != '[None]' or item['stroke']['weight'] != 0:
                    raise ValueError('Layout vector acquired an unrequested outline')
                swatch_names = {item['fill']['swatch']} if 'color' in request else set()
            if 'color' in request:
                expected = [int(request['color'][i:i + 2], 16) / 255 for i in (1, 3, 5)]
                for name in swatch_names:
                    swatch = next(s for s in state['swatches'] if s['name'] == name)['value']
                    color = swatch.get('color', {})
                    if color.get('model') != 'rgb' or any(abs(color[k] - v) > 1e-6 for k, v in zip(('r', 'g', 'b'), expected)):
                        raise ValueError('Layout native ink differs from the requested colour')


def execute(root, operation, params, *, executable=None, pdf_executable=None):
    validate(operation, params, None if operation in ('layout.create', 'layout.import') else 'source')
    root = Path(root).resolve(); native = root / 'native'; exports = root / 'exports'
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    path = native / 'document.designcraft'; pending = native / 'pending.designcraft'
    inputs = {key: root / value for key, value in assets(operation, params).items()}
    hashes = {key: digest(value) for key, value in inputs.items()}
    source_hash = digest(path) if operation in ('layout.edit', 'layout.inspect') else None
    mapping = {}; before = None; before_pixels = None; touched = set(); raster_sources = {}; import_profile = None
    with tempfile.TemporaryDirectory(prefix='.layout-check-', dir=root) as temporary:
        scratch = Path(temporary)
        with Engine(root, executable=executable) as process:
            if operation in ('layout.create', 'layout.edit'):
                for key, source in inputs.items():
                    if source.is_symlink() or not source.is_file() or source.stat().st_size > document.MAX_ASSET:
                        raise ValueError('Layout artwork exceeds its source file budget')
                    raw = source.read_bytes()
                    mime = 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else None
                    if mime is None:
                        raise ValueError('Layout artwork requires PNG or JPEG')
                    size = document.raster_info(raw, mime)
                    # Native placement uses file extensions to select its decoder.
                    material = scratch / (key + ('.png' if mime == 'image/png' else '.jpg'))
                    material.write_bytes(raw)
                    raster_sources[key] = {'path': material, 'pixels': size, 'sha256': hashes[key], 'mime': mime}
                if sum(r['pixels'][0] * r['pixels'][1] for r in raster_sources.values()) > document.MAX_PIXELS:
                    raise ValueError('Layout artwork exceeds its aggregate pixel budget')
            if operation == 'layout.create':
                process.command('file.new', width=params['width'], height=params['height'], pages=len(params['pages']),
                                facingPages=False, intent='web', units='points', margins=36, title=params.get('title', 'Untitled'))
                for index, page in enumerate(params['pages']):
                    for obj in page['objects']:
                        kind = 'text' if obj['type'] == 'text' else 'graphic' if obj['type'] == 'image' else 'unassigned'
                        args = {'spread': index, 'rect': obj['rect'], 'content': kind,
                                'shape': obj['type'] if kind == 'unassigned' else 'rectangle'}
                        if kind == 'text':
                            args.update(text=obj['text'], caret=False)
                        created = process.command('frame.create', **args)
                        process.command('object.label', label=obj['name'], ids=[created['id']])
                        mapping[obj['name']] = {'id': created['id'], 'type': kind}
                        if kind == 'text':
                            mapping[obj['name']]['story'] = created['story']
                            process.command('type.char', attrs=font_attrs(obj))
                        elif kind == 'graphic':
                            result = process.tool('place_image', frame=created['id'], path=process.relative(raster_sources[obj['asset']]['path']))
                            process.command('links.embed', asset=result['asset'])
                            process.command('object.fit', mode=FITS[obj.get('fit', 'contain')], ids=[created['id']])
                        else:
                            process.command('object.stroke', swatch='[None]', weight=0, ids=[created['id']])
                        if 'color' in obj:
                            process.command('selection.set', ids=[created['id']])
                            # Explicit native ids target the frame fill even with
                            # text=true. Text ink uses the selected frame's story.
                            process.command('object.color', color=obj['color'], text=kind == 'text')
                profile = process.save(pending)
                requested(process, profile, params, mapping, raster_sources)
            elif operation == 'layout.import':
                source = inputs[params['asset']]
                if params['format'] == 'native':
                    import_profile = process.open(source)
                    profile = process.save(pending)
                    if profile != import_profile:
                        raise ValueError('Layout native import changed document fields or embedded assets')
                else:
                    import_profile = document.read_idml(source)
                    process.command('file.openIdml', path=process.relative(source))
                    profile = process.save(pending)
                    if len(profile['pages']) != import_profile['pages'] or sorted(set(profile['assets'].values())) != sorted({a['sha256'] for a in import_profile['embedded']}):
                        raise ValueError('Layout IDML import changed page count or embedded artwork')
                mapping = mapping_for(profile['document'])
            else:
                before = process.open(path); process.preflight()
                before_pixels = process.render(before, scratch / 'before')
                mapping = audio.load_json(native / 'objects.json', 1 << 20); check_mapping(mapping, before['document'])
                expected = copy.deepcopy(before['document']); items = native_items(expected)
                expected_hashes = dict(before['assets']); replacements = []
                if operation == 'layout.edit':
                    for edit in params['edits']:
                        record = mapping.get(edit['name'])
                        if record is None:
                            raise ValueError('unknown Layout edit target')
                        item = items[record['id']]
                        layer = next(layer for layer in expected['layers'] if layer['id'] == item['layer'])
                        if item['locked'] or layer['locked']:
                            raise ValueError('Layout target or its layer is locked')
                        process.command('selection.set', ids=[record['id']])
                        if edit['action'] == 'move':
                            item['xf'][4] += edit['dx']; item['xf'][5] += edit['dy']
                            process.command('transform.move', ids=[record['id']], dx=edit['dx'], dy=edit['dy'])
                            touched.update(pages_for_frames(expected, {record['id']}))
                        elif edit['action'] == 'replace_image':
                            if record['type'] != 'graphic':
                                raise ValueError('Layout image replacement requires a graphic frame')
                            if expected_hashes[str(item['content']['asset'])] != edit['expected_sha256']:
                                raise ValueError('Layout image replacement expected SHA-256 does not match the target')
                            source = raster_sources[edit['asset']]; fresh = expected['nextId'] + 1
                            content = replacement_content(item, fresh, source['pixels'], edit['fit'])
                            placed = process.tool('place_image', frame=record['id'], path=process.relative(source['path']))
                            if placed.get('asset') != fresh:
                                raise ValueError('Layout image replacement allocated an unexpected native asset')
                            process.command('links.embed', asset=fresh)
                            process.command('object.fit', mode=FITS[edit['fit']], ids=[record['id']])
                            item['content'] = content; expected['nextId'] += 1
                            expected['assets'][str(fresh)] = {'id': fresh, 'name': source['path'].name,
                                                              'mime': source['mime'], 'pixels': source['pixels']}
                            expected_hashes[str(fresh)] = source['sha256']; replacements.append((item, fresh))
                            touched.update(pages_for_frames(expected, {record['id']}))
                        else:
                            if record['type'] != 'text':
                                raise ValueError('Layout text or typography edit requires a text frame')
                            sid = str(record['story']); story = expected['stories'][sid]
                            if edit['action'] == 'replace_text':
                                expected['stories'][sid] = document.replaced_story(story, edit['start'], edit['end'], edit['expected'], edit['text'])
                                process.command('story.replaceRange', story=record['story'], start=edit['start'], end=edit['end'], text=edit['text'])
                            else:
                                attrs = font_attrs(edit); expected['stories'][sid] = styled_story(story, attrs)
                                process.command('type.char', attrs=attrs)
                            touched.update(pages_for_frames(expected, set(story['frames'])))
                if replacements:
                    expected_hashes = compact_replacements(expected, expected_hashes, replacements)
                profile = process.save(pending)
                if profile['document'] != expected or profile['assets'] != expected_hashes:
                    raise ValueError('Layout revision changed an unrequested native field or embedded asset')
            check_mapping(mapping, profile['document'])
            diagnostics = process.preflight(); summary = inspect(process, profile)
            if operation == 'layout.edit':
                moved = {mapping[e['name']]['id'] for e in params['edits'] if e['action'] == 'move'}
                for spread in summary['spreads']:
                    for item in spread['items']:
                        if item['id'] in moved and not any(
                                item['bounds'][0] >= page['bounds'][0] and item['bounds'][1] >= page['bounds'][1]
                                and item['bounds'][2] <= page['bounds'][2] and item['bounds'][3] <= page['bounds'][3]
                                for page in spread['pages']):
                            raise ValueError('Layout move places its frame outside the page')
            pixels = process.render(profile, exports)
            if before_pixels is not None and any(old != new for i, (old, new) in enumerate(zip(before_pixels, pixels)) if i not in touched):
                raise ValueError('Layout revision changed an untargeted page')
            process.command('file.exportPdf', path=process.relative(exports / 'document.pdf'))
            process.command('file.exportIdml', path=process.relative(exports / 'document.idml'), embedImages=True)
            interchange = document.read_idml(exports / 'document.idml')
            if interchange['pages'] != len(profile['pages']):
                raise ValueError('Layout IDML export changed the page count')
        with Engine(root, executable=executable) as reopened:
            cold = reopened.open(pending)
            if cold != profile or reopened.save(scratch / 'cold.designcraft') != profile:
                raise ValueError('Layout cold reopen changed native document state')
            reopened.preflight()
            if reopened.render(cold, scratch / 'cold') != pixels:
                raise ValueError('Layout cold reopen changed page pixels')
        with Engine(root, executable=executable) as reopened:
            reopened.command('file.openIdml', path=reopened.relative(exports / 'document.idml'))
            roundtrip = reopened.save(scratch / 'idml.designcraft'); reopened.preflight()
            if reopened.render(roundtrip, scratch / 'idml') != pixels:
                raise ValueError('Layout IDML interchange changed page pixels')
        pdf_report = validate_pdf(root, exports / 'document.pdf', profile, executable=pdf_executable)
        if any(digest(inputs[key]) != value for key, value in hashes.items()) or source_hash is not None and digest(path) != source_hash:
            raise ValueError('Layout production modified source bytes')
        pending.replace(path)
    (native / 'objects.json').write_text(json.dumps(mapping, sort_keys=True) + '\n')
    (exports / 'inspection.json').write_text(json.dumps({'objects': mapping, 'document': profile['document'],
        'assets': profile['assets'], 'fonts': diagnostics['fonts'], 'preflight': diagnostics['preflight'],
        'pdf': pdf_report}, sort_keys=True) + '\n')
    files = [('native/document.designcraft', 'native'), ('native/objects.json', 'native'),
             ('exports/document.pdf', 'export'), ('exports/document.idml', 'export'), ('exports/inspection.json', 'export')]
    files += [(f'exports/page-{i + 1:03}.png', 'preview') for i in range(len(pixels))]
    return {'engine': {'name': 'designcraft', 'version': VERSION, 'build': 'dobe-layout ' + VERSION},
            'artifacts': [{'path': path, 'role': role} for path, role in files] + photo.retained_assets(root),
            'validation': {'passed': True, 'native_cold_reopen': True, 'native_state_equal': True,
                'pixel_roundtrip_equal': True, 'idml_pixel_roundtrip_equal': True, 'source_bytes_unchanged': True,
                'exact_bundled_fonts': True, 'preflight': diagnostics['preflight'], 'page_count': len(pixels),
                'untargeted_native_fields_verified': before is not None, 'untargeted_page_pixels_verified': before is not None,
                'general_idml_fidelity_qualified': False, 'independent_pdf_validation': True,
                'independently_checked_pdf_stories': pdf_report['independently_checked_stories'],
                'qualification': 'bounded local publication contract; no general interchange fidelity claim'}}
