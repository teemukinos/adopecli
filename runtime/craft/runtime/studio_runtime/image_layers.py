"""Typed, native image composition and revisions for the pinned PhotoCraft engine.

This module is kept separate from whole-image adjustments. Layer edits validate
the actual native document, rather than trusting a portable bundle's sidecar.
"""
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from . import photo, font_policy

OPERATIONS = ('image.create', 'image.edit')
PACKAGED_FONTS = ('Inter', 'JetBrains Mono')
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
ASSET = re.compile(r'(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})')
COLOR = re.compile(r'#[0-9a-fA-F]{6}')


def number(value, low, high, integer=False):
    types = (int,) if integer else (int, float)
    return type(value) in types and low <= value <= high and math.isfinite(value)


def color(value):
    return isinstance(value, str) and COLOR.fullmatch(value) is not None


def mask(value, creating=False):
    if value is None and not creating:
        return
    if not isinstance(value, dict) or not value or set(value) - {'rect', 'density', 'feather'}:
        raise ValueError('mask requires rect, density or feather; null removes an existing mask')
    if creating and 'rect' not in value:
        raise ValueError('a new mask requires a rectangle')
    if 'rect' in value:
        rect = value['rect']
        if (not isinstance(rect, list) or len(rect) != 4
                or any(not number(v, -8192, 8192, True) for v in rect[:2])
                or any(not number(v, 1, 8192, True) for v in rect[2:])):
            raise ValueError('mask rect must contain integer x, y, width and height')
    for key, maximum in (('density', 100), ('feather', 1000)):
        if key in value and not number(value[key], 0, maximum):
            raise ValueError('invalid mask ' + key)


def properties(value, creating=False):
    if 'opacity' in value and not number(value['opacity'], 0, 1):
        raise ValueError('opacity must be between 0 and 1')
    if 'visible' in value and type(value['visible']) is not bool:
        raise ValueError('visible must be a boolean')
    if 'mask' in value:
        mask(value['mask'], creating)
    if 'text' in value and (not isinstance(value['text'], str) or len(value['text']) > 10000
                            or any(0xD800 <= ord(c) <= 0xDFFF or c == '\0' for c in value['text'])):
        raise ValueError('text must contain at most 10000 valid Unicode characters without NUL')
    if 'font' in value and value['font'] not in PACKAGED_FONTS:
        raise ValueError('font must name a qualified packaged family: ' + ', '.join(PACKAGED_FONTS))
    if 'size' in value and not number(value['size'], 0.1, 1296):
        raise ValueError('text size must be between 0.1 and 1296 points')
    if 'color' in value and not color(value['color']):
        raise ValueError('color must be #rrggbb')


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported image layer operation or parameters')
    if len(json.dumps(params, allow_nan=False).encode()) > 128 << 10:
        raise ValueError('image layer parameters exceed 128 KiB')
    creating = operation == 'image.create'
    if creating:
        if source_revision is not None or set(params) != {'width', 'height', 'background', 'layers'}:
            raise ValueError('image.create requires a new project, width, height, background and layers')
        if any(not number(params[k], 1, 8192, True) for k in ('width', 'height')):
            raise ValueError('canvas dimensions must be integers between 1 and 8192')
        if params['background'] != 'transparent' and not color(params['background']):
            raise ValueError('background must be transparent or #rrggbb')
        values = params['layers']
    else:
        if not source_revision or set(params) != {'edits'}:
            raise ValueError('image.edit requires a source revision and edits')
        values = params['edits']
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise ValueError('provide between 1 and 64 layers or edits')
    names = {'background'} if creating else set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError('each layer or edit must be an object')
        name = value.get('name')
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise ValueError('layer names must be unique identifiers; background is reserved during creation')
        names.add(name)
        common = {'name', 'opacity', 'visible', 'mask'}
        if creating:
            kind = value.get('type')
            if not isinstance(kind, str):
                raise ValueError('layer type must be a string')
            fields = {'solid': {'color'}, 'text': {'x', 'y', 'text', 'font', 'size', 'color'},
                      'asset': {'asset', 'center', 'scale'}}.get(kind)
            if fields is None or not fields <= set(value) or set(value) - common - fields - {'type'}:
                raise ValueError('layer type and properties must match solid, text or asset')
            if kind == 'text' and any(not number(value[k], -8192, 8192) for k in ('x', 'y')):
                raise ValueError('text position exceeds supported canvas coordinates')
            if kind == 'asset':
                if not isinstance(value['asset'], str) or not ASSET.fullmatch(value['asset']):
                    raise ValueError('asset must be an imported asset identifier')
                center = value['center']
                if (not isinstance(center, list) or len(center) != 2
                        or any(not number(v, -8192, 8192) for v in center)
                        or not number(value['scale'], 0.1, 1000)):
                    raise ValueError('asset requires center coordinates and scale between 0.1 and 1000 percent')
        elif len(value) < 2 or set(value) - common - {'text', 'font', 'size', 'color'}:
            raise ValueError('unsupported or empty layer edit')
        properties(value, creating)


def assets(operation, params):
    """Return the exact imported assets that must be authorized and staged."""
    if operation != 'image.create':
        return {}
    return {layer['asset']: 'assets/' + layer['asset'] for layer in params['layers'] if layer['type'] == 'asset'}


def read_native(path):
    with zipfile.ZipFile(path) as archive:
        entry = archive.getinfo('manifest.json')
        if entry.file_size > 8 << 20:
            raise ValueError('native layer manifest exceeds 8 MiB')
        manifest = json.loads(archive.read(entry))
    if manifest.get('format_version') != 1:
        raise ValueError('unsupported native image format')
    document = manifest.get('document', {})
    if (document.get('mode') != 'Rgb' or document.get('depth') != 'U8'
            or any(not number(document.get('size', {}).get(k), 1, 8192, True) for k in ('width', 'height'))):
        raise ValueError('native layer editing requires an 8-bit RGB canvas up to 8192 pixels per dimension')
    layers = document.get('layers')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 200:
        raise ValueError('native image requires between 1 and 200 top-level layers')
    names = set(); ids = set()
    for layer in layers:
        name = layer.get('name'); ident = layer.get('id')
        if (not isinstance(name, str) or name in names or type(ident) is not int
                or ident <= 0 or ident in ids):
            raise ValueError('native image has ambiguous layer names or identifiers')
        names.add(name); ids.add(ident)
        kind = layer.get('content', {}).get('kind')
        if kind not in ('raster', 'fill', 'smart', 'text'):
            raise ValueError('layer editing requires a flat pixel, fill, embedded asset or text document')
        if kind == 'smart' and layer['content'].get('source', {}).get('kind') != 'embedded':
            raise ValueError('linked smart objects must be embedded before editing')
        if kind == 'text':
            content = layer['content']
            families = {content.get('font_family')}
            families.update(run.get('style', {}).get('font_family') for run in content.get('runs', []))
            if families - set(PACKAGED_FONTS):
                raise ValueError('native text depends on an unqualified font family')
    return layers


def asset_copy(source, destination):
    """Detect file content and place an unchanged, extension-bearing copy."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 32 << 20:
        raise ValueError('placed assets must be regular files no larger than 32 MiB')
    data = source.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        suffix = '.png'
    elif data.startswith(b'\xff\xd8\xff'):
        suffix = '.jpg'
    else:
        if len(data) > 2 << 20 or b'<!' in data:
            raise ValueError('SVG must be at most 2 MiB and contain no declarations or entities')
        try:
            tree = ET.fromstring(data)
        except (ET.ParseError, ValueError):
            raise ValueError('placed assets must be PNG, JPEG or self-contained SVG') from None
        namespace = '{http://www.w3.org/2000/svg}'
        if tree.tag != namespace + 'svg':
            raise ValueError('SVG namespace and root are required')
        allowed = {'svg', 'g', 'defs', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
                   'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask', 'use', 'symbol',
                   'title', 'desc', 'pattern', 'marker'}
        nodes = list(tree.iter())
        if len(nodes) > 10000:
            raise ValueError('SVG exceeds 10000 elements')
        for node in nodes:
            if not isinstance(node.tag, str) or not node.tag.startswith(namespace) or node.tag[len(namespace):] not in allowed:
                raise ValueError('SVG requires static, outlined artwork without external media or text')
            for key, value in node.attrib.items():
                key = key.rsplit('}', 1)[-1].lower()
                # Escapes/comments could disguise URLs in CSS. Inline declarations
                # remain supported, but only direct local fragment references.
                if key.startswith('on') or key in ('base', 'src') or any(c in value for c in ('\\', '/*', '*/')):
                    raise ValueError('unsafe SVG attribute')
                if key == 'href' and not re.fullmatch(r'#[A-Za-z_][A-Za-z0-9_.:-]*', value):
                    raise ValueError('SVG references must be local fragments')
                stripped = re.sub(r'url\(\s*[\"\']?#[A-Za-z_][A-Za-z0-9_.:-]*[\"\']?\s*\)', '', value, flags=re.I)
                if re.search(r'url\s*\(|@import|://|javascript:|data:', stripped, re.I):
                    raise ValueError('external SVG resources are not supported')
        suffix = '.svg'
    path = destination.with_suffix(suffix)
    path.write_bytes(data)
    return path


def mask_commands(value, existing):
    steps = []
    if value is None:
        if existing is None:
            raise ValueError('cannot remove a mask from an unmasked layer')
        return [('layer.layerMask.delete', {})]
    if 'rect' in value:
        if existing is not None:
            steps.append(('layer.layerMask.delete', {}))
        steps += [('select.rect', dict(zip(('x', 'y', 'width', 'height'), value['rect']), antiAlias=False)),
                  ('layer.layerMask.revealSelection', {}), ('select.deselect', {})]
        if existing is not None:
            value = {'density': existing['density'] * 100, 'feather': existing['feather'], **value}
            steps += [('layer.layerMask.enabled', {'enabled': existing['enabled']}),
                      ('layer.layerMask.linked', {'linked': existing['linked']})]
    elif existing is None:
        raise ValueError('mask density and feather require an existing mask or a new rectangle')
    changes = {k: value[k] for k in ('density', 'feather') if k in value}
    if changes:
        steps.append(('layer.layerMask.edit', changes))
    return steps


def execute(root, operation, params):
    validate(operation, params, None if operation == 'image.create' else 'revision')
    version_text = photo.run(['photocraft-cli', '--version']).strip()
    if version_text.split()[1] != '0.23.1':
        raise ValueError('image engine version is not qualified; expected 0.23.1')
    root = Path(root).resolve(); native = root / 'native'; exports = root / 'exports'
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    document = native / 'document.pcraft'; pending = native / 'pending.pcraft'
    creating = operation == 'image.create'
    before = [] if creating else read_native(document)
    by_name = {layer['name']: layer for layer in before}
    changes = params['layers'] if creating else params['edits']
    steps = []
    with tempfile.TemporaryDirectory(prefix='.placement-', dir=root) as temp:
        if creating:
            args = ['photocraft-cli', 'run', '--new', json.dumps(
                {k: params[k] for k in ('width', 'height', 'background')} | {'mode': 'rgb', 'depth': 8, 'resolution': 72})]
            steps.append(('layer.setProps', {'name': 'background'}))
        else:
            args = ['photocraft-cli', 'run', str(document)]
        fonts = {layer['content']['font_family'] for layer in before if layer['content']['kind'] == 'text'}
        fonts.update(value['font'] for value in changes if 'font' in value)
        steps += [('type.fonts', {'family': font}) for font in sorted(fonts)]
        for value in changes:
            name = value['name']
            if creating:
                if value['type'] == 'solid':
                    steps.append(('layer.newFillLayer.solidColor', {'color': value['color']}))
                elif value['type'] == 'text':
                    steps.append(('type.create', {k: value[k] for k in ('x', 'y', 'text', 'font', 'size', 'color', 'name')}))
                else:
                    path = asset_copy(root / 'assets' / value['asset'], Path(temp) / value['asset'])
                    steps.append(('file.placeEmbedded', {'path': str(path), 'center': value['center'],
                                                         'scale': value['scale'], 'fit': False, 'smartObject': True}))
                steps.append(('layer.setProps', {'name': name}))
            else:
                if name not in by_name:
                    raise ValueError('edit names an unknown native layer: ' + name)
                old = by_name[name]
                steps.append(('layer.select', {'layer': old['id']}))
                if set(value) & {'text', 'font', 'size', 'color'}:
                    if old['content']['kind'] != 'text':
                        raise ValueError('text and text style edits require a native text layer')
                    if 'text' in value:
                        steps.append(('type.edit', {'text': value['text']}))
                    style = {k: value[k] for k in ('font', 'size', 'color') if k in value}
                    if style:
                        steps.append(('type.setStyle', style))
            props = {k: value[k] for k in ('opacity', 'visible') if k in value}
            if props:
                steps.append(('layer.setProps', props))
            if 'mask' in value:
                steps += mask_commands(value['mask'], None if creating else by_name[name]['mask'])
        if fonts:
            steps.append(('type.resolveMissingFonts', {}))
        for command, parameters in steps:
            args += ['--cmd', command, '--params', json.dumps(parameters)]
        output = photo.run(args + ['--no-gpu', '--out', str(pending), '--pcraft-full-composite'])
    results = [json.loads(line) for line in output.splitlines()]
    if len(results) != len(steps) or any(result.get('command') != step[0] for result, step in zip(results, steps)):
        raise ValueError('image engine returned an incomplete command result')
    font_faces = []
    for result, (_, parameters) in zip(results, steps):
        if result['command'] == 'type.fonts':
            faces = result['result'].get('faces', [])
            if not any(face.get('family') == parameters['family'] and face.get('weight') == 400 and not face.get('italic') for face in faces):
                raise ValueError('requested packaged font is unavailable')
            font_faces.extend(faces)
    if fonts and results[-1]['result'].get('missing') != []:
        raise ValueError('native image contains missing font families')
    after = read_native(pending)
    after_names = {layer['name']: layer for layer in after}
    if creating:
        expected = {'background': 'raster'} | {value['name']: {'solid': 'fill', 'text': 'text', 'asset': 'smart'}[value['type']] for value in changes}
        if {layer['name']: layer['content']['kind'] for layer in after} != expected:
            raise ValueError('native layer types or names differ from the requested composition')
    else:
        if [(layer['id'], layer['name']) for layer in before] != [(layer['id'], layer['name']) for layer in after]:
            raise ValueError('image edit changed native layer identity or order')
        edits = {value['name']: value for value in changes}
        for old in before:
            new = after_names[old['name']]; edit = edits.get(old['name'], {})
            allowed = set(edit) & {'opacity', 'visible', 'mask'}
            if set(edit) & {'text', 'font', 'size', 'color'}:
                allowed.add('content')
            if {k: v for k, v in old.items() if k not in allowed} != {k: v for k, v in new.items() if k not in allowed}:
                raise ValueError('image edit changed an unrelated native layer property')
            if 'mask' in edit and edit['mask'] is not None and old['mask'] is not None:
                mutable = set(edit['mask']) & {'density', 'feather'}
                if 'rect' in edit['mask']:
                    mutable.add('surface')
                if ({k: v for k, v in old['mask'].items() if k not in mutable}
                        != {k: v for k, v in new['mask'].items() if k not in mutable}):
                    raise ValueError('image edit changed an unrelated mask property or its preserved pixels')
            if old['content']['kind'] == 'smart':
                blob = old['content']['source']['blob']
                with zipfile.ZipFile(document) as original, zipfile.ZipFile(pending) as revised:
                    entry = 'blobs/' + blob + '.zst'
                    if original.getinfo(entry).file_size > 32 << 20 or revised.getinfo(entry).file_size > 32 << 20:
                        raise ValueError('embedded source exceeds its validation budget')
                    if original.read(entry) != revised.read(entry):
                        raise ValueError('image edit changed embedded source bytes')
    for value in changes:
        layer = after_names[value['name']]
        if 'text' in value and layer['content'].get('text') != value['text']:
            raise ValueError('native text does not match the requested text')
        content = layer['content']
        styles = ([content] + [run['style'] for run in content.get('runs', [])]) if content['kind'] == 'text' else []
        for style in styles:
            if 'font' in value and style.get('font_family') != value['font']:
                raise ValueError('native font does not match the requested family')
            if 'size' in value and not math.isclose(style.get('size_pt', 0), value['size'], abs_tol=1e-5):
                raise ValueError('native text size does not match the request')
        if 'color' in value:
            expected = [int(value['color'][i:i + 2], 16) / 255 for i in (1, 3, 5)]
            colors = [style.get('color', {}) for style in styles]
            if content['kind'] == 'fill':
                colors = [content.get('fill', {}).get('Solid', {})]
            for saved_color in colors:
                channels = saved_color.get('c', [])
                if (saved_color.get('mode') != 'Rgb' or len(channels) != 4
                        or any(not math.isclose(a, b, abs_tol=1e-6) for a, b in zip(channels[:3], expected))):
                    raise ValueError('native color does not match the request')
        for key in ('opacity', 'visible'):
            if key in value and not math.isclose(layer[key], value[key], abs_tol=1e-6):
                raise ValueError('native layer property does not match the request')
        if 'mask' in value:
            requested = value['mask']; saved = layer['mask']
            if (requested is None) != (saved is None):
                raise ValueError('native mask presence does not match the request')
            for key, scale in (('density', 100), ('feather', 1)):
                if requested is not None and key in requested and not math.isclose(saved[key], requested[key] / scale, abs_tol=1e-6):
                    raise ValueError('native mask property does not match the request')
    png = exports / 'document.png'
    photo.run(['photocraft-cli', 'convert', '--no-gpu', str(pending), str(png)])
    reference = exports / 'saved-composite.png'
    with zipfile.ZipFile(pending) as archive:
        entry = archive.getinfo('composite/full.png')
        if entry.file_size > 512 << 20:
            raise ValueError('native composite exceeds validation budget')
        with archive.open(entry) as src, open(reference, 'wb') as dst:
            shutil.copyfileobj(src, dst)
    if photo.pixel_hash(png) != photo.pixel_hash(reference):
        raise ValueError('native cold-reopen changed image pixels')
    reference.unlink()
    info = json.loads(photo.run(['photocraft-cli', 'info', '--compact', str(pending)]))
    if info.get('warnings') or info.get('depth') != 8 or any(not number(info.get(k), 1, 8192, True) for k in ('width', 'height')):
        raise ValueError('native image has inspection warnings or unsupported dimensions/depth')
    if creating and any(info[k] != params[k] for k in ('width', 'height')):
        raise ValueError('native canvas dimensions do not match the request')
    for key in ('file', 'path'):
        info[key] = 'native/document.pcraft'
    glyphs = font_policy.inspect(pending)
    pending.replace(document)
    (native / 'structure.json').write_text(json.dumps(info, sort_keys=True) + '\n')
    (native / 'fonts-manifest.json').write_text(json.dumps({'engine': 'photocraft', 'version': '0.23.1',
        'source': 'engine-bundled fonts', 'faces': font_faces, 'missing_families': [],
        'glyph_coverage_verified': False} | (glyphs or {}), sort_keys=True) + '\n')
    artifacts = [{'path': name, 'role': role} for name, role in (
        ('native/document.pcraft', 'native'), ('native/structure.json', 'native'),
        ('native/fonts-manifest.json', 'asset'), ('exports/document.png', 'export'))]
    artifacts += photo.retained_assets(root)
    return {'engine': {'name': 'photocraft', 'version': '0.23.1', 'build': version_text}, 'artifacts': artifacts,
            'validation': {'passed': True, 'native_cold_reopen': True, 'pixel_roundtrip_equal': True,
                           'layer_identity_preserved': not creating, 'png_width': info['width'], 'png_height': info['height'],
                           'font_families_available': True, 'glyph_coverage_verified': glyphs is not None,
                           'font_validation_scope': glyphs['scope'] if glyphs else 'family_availability_only'}}
