"""Bounded native composition, media layers and editable transform animation."""
import copy
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import struct
import subprocess
import threading

from . import photo, vector, video

OPERATIONS = ('motion.create', 'motion.edit')
VERSION = '0.24.1'
TICKS = 254016000000
PROPERTIES = ('position', 'scale', 'rotation', 'opacity')
MEDIA = re.compile(r'(' + video.ASSET.pattern + r')\.(png|jpg|mp4)')


def color(value):
    if not isinstance(value, str) or not video.COLOR.fullmatch(value):
        raise ValueError('color must be #rrggbb')


def property_value(name, value):
    if name in ('position', 'scale'):
        low, high = (-8192, 8192) if name == 'position' else (0.01, 1000)
        valid = isinstance(value, list) and len(value) == 2 and all(video.finite(v, low, high) for v in value)
    else:
        low, high = (-36000, 36000) if name == 'rotation' else (0, 100)
        valid = name in PROPERTIES and video.finite(value, low, high)
    if not valid:
        raise ValueError('invalid bounded motion property: ' + str(name))


def animation(name, track, start=0, end=36000):
    if not isinstance(track, dict) or set(track) != {'keys', 'interpolation'}:
        raise ValueError('animation requires keys and interpolation')
    if track['interpolation'] not in ('linear', 'hold', 'easyEase'):
        raise ValueError('animation supports linear, hold or easyEase interpolation')
    keys = track['keys']
    if not isinstance(keys, list) or not 1 <= len(keys) <= 200:
        raise ValueError('animation requires 1 to 200 keys')
    previous = -1
    for key in keys:
        if (not isinstance(key, dict) or set(key) != {'frame', 'value'}
                or not video.integer(key['frame'], start, end - 1) or key['frame'] <= previous):
            raise ValueError('keyframes must be unique, ordered integer composition frames inside the layer')
        previous = key['frame']; property_value(name, key['value'])


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported motion operation or parameters')
    if operation == 'motion.create':
        if source_revision is not None or set(params) != {'width', 'height', 'fps', 'frames', 'background', 'layers'}:
            raise ValueError('motion.create requires a new composition with dimensions, fps, frames, background and layers')
        if any(not video.integer(params[k], 16, 1920) or params[k] % 2 for k in ('width', 'height')):
            raise ValueError('motion dimensions must be even integers between 16 and 1920')
        if type(params['fps']) is not int or params['fps'] not in (24, 25, 30, 50, 60) or not video.integer(params['frames'], 1, 36000):
            raise ValueError('motion requires a supported integer fps and 1 to 36000 frames')
        color(params['background']); layers = params['layers']; names = set(); formats = {}; key_count = 0
        if not isinstance(layers, list) or not 1 <= len(layers) <= 64:
            raise ValueError('motion requires 1 to 64 layers')
        for layer in layers:
            if not isinstance(layer, dict) or not video.named(layer.get('name')) or layer['name'] in names:
                raise ValueError('motion layers require unique identifier names')
            names.add(layer['name']); kind = layer.get('type')
            required = {'type', 'name', 'start', 'frames', 'position'}
            fields = {'shape': {'shape', 'width', 'height', 'color'}, 'text': {'text', 'size', 'color'}, 'media': {'asset', 'format'}}
            if kind not in fields or not (required | fields[kind]) <= set(layer) or set(layer) - required - fields[kind] - {'scale', 'rotation', 'opacity', 'animation'}:
                raise ValueError('unsupported motion layer fields')
            if (not video.integer(layer['start'], 0, params['frames'] - 1) or not video.integer(layer['frames'], 1, params['frames'])
                    or layer['start'] + layer['frames'] > params['frames']):
                raise ValueError('layer timing must fit inside the composition')
            for name in PROPERTIES:
                if name in layer:
                    property_value(name, layer[name])
            if kind == 'shape':
                if layer['shape'] not in ('rect', 'ellipse') or any(not video.finite(layer[k], 1, 8192) for k in ('width', 'height')):
                    raise ValueError('shape requires rect/ellipse and bounded dimensions')
                color(layer['color'])
            elif kind == 'text':
                video.text(layer['text']); color(layer['color'])
                if not video.finite(layer['size'], 1, 512):
                    raise ValueError('text size must be between 1 and 512')
            else:
                asset = layer['asset']
                if not isinstance(asset, str) or not video.ASSET.fullmatch(asset) or layer['format'] not in ('png', 'jpg', 'mp4'):
                    raise ValueError('media requires an imported asset and png, jpg or mp4 format')
                if formats.setdefault(asset, layer['format']) != layer['format']:
                    raise ValueError('one media asset cannot have conflicting formats')
            tracks = layer.get('animation', {})
            if not isinstance(tracks, dict) or set(tracks) - set(PROPERTIES):
                raise ValueError('unsupported animated property')
            for name, track in tracks.items():
                animation(name, track, layer['start'], layer['start'] + layer['frames']); key_count += len(track['keys'])
        if key_count > 2000:
            raise ValueError('motion composition exceeds 2000 keyframes')
    else:
        if not source_revision or set(params) != {'edits'} or not isinstance(params['edits'], list) or not 1 <= len(params['edits']) <= 100:
            raise ValueError('motion.edit requires a source revision and 1 to 100 edits')
        targets = set()
        for edit in params['edits']:
            if not isinstance(edit, dict) or not video.named(edit.get('name')):
                raise ValueError('motion edit requires an existing layer name')
            if edit.get('type') == 'text' and set(edit) == {'type', 'name', 'text'}:
                video.text(edit['text']); target = (edit['name'], 'text')
            elif (edit.get('type') == 'property' and edit.get('property') in PROPERTIES
                  and set(edit) in ({'type', 'name', 'property', 'value'}, {'type', 'name', 'property', 'animation'})):
                if 'value' in edit:
                    property_value(edit['property'], edit['value'])
                else:
                    animation(edit['property'], edit['animation'])
                target = (edit['name'], edit['property'])
            else:
                raise ValueError('motion edits support text or complete static/animated transform property replacement')
            if target in targets:
                raise ValueError('one request cannot replace the same property twice')
            targets.add(target)


def assets(operation, params):
    return {v['asset']: 'assets/' + v['asset'] + '.' + v['format'] for v in params['layers'] if v['type'] == 'media'} if operation == 'motion.create' else {}


def engine():
    return 'dobe-motion' if shutil.which('dobe-motion') else 'effectcraft-cli'


def environment(root):
    return dict(os.environ, EFFECTCRAFT_CONFIG_DIR=str(Path(root) / '.motion-config'))


class Engine(vector.Engine):
    label = 'motion'

    def __init__(self, root, *, executable=None):
        self.root = Path(root).resolve()
        self.proc = subprocess.Popen([str(executable) if executable is not None else engine(), 'mcp', '--automation-read-root', str(self.root), '--automation-write-root', str(self.root)],
                                     cwd=self.root, env=environment(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self.messages = queue.Queue(); self.counter = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            result = self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'dobe-runtime', 'version': '0.1.0'}})
            self.version = result['serverInfo']['version']
            if self.version != VERSION:
                raise ValueError('motion engine version is not qualified; expected ' + VERSION)
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close(); raise

    def tool(self, name, arguments):
        value = self.call('tools/call', {'name': name, 'arguments': arguments})
        texts = [v['text'] for v in value.get('content', []) if v.get('type') == 'text']
        if value.get('isError') or len(texts) != 1:
            raise ValueError('motion engine: ' + str(texts)[:1000])
        return json.loads(texts[0])


def run(root, *args, executable=None):
    result = subprocess.run([str(executable) if executable is not None else engine(), *map(str, args)], cwd=root, env=environment(root), capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ValueError(result.stderr[-1500:] or result.stdout[-1500:] or 'motion engine failed')
    return result.stdout


def inspect_media(path, format):
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file() or path.stat().st_size > 1 << 30:
        raise ValueError('motion requires bounded regular media files')
    if format in ('png', 'jpg'):
        from PIL import Image
        with Image.open(path) as image:
            if image.format != {'png': 'PNG', 'jpg': 'JPEG'}[format] or any(not 1 <= v <= 8192 for v in image.size):
                raise ValueError('motion image format or dimensions differ from its declaration')
            image.verify()
    else:
        with path.open('rb') as stream:
            if stream.read(12)[4:8] != b'ftyp':
                raise ValueError('motion video requires an MP4 file type header')


def validate_text_document(doc):
    if (not isinstance(doc, dict) or doc.get('font') != 'Inter' or doc.get('style') != 'Regular'
            or not video.finite(doc.get('size'), 1, 512)
            or any(doc.get(key) for key in ('runs', 'paragraphs', 'variations', 'vertical',
                                           'faux_bold', 'faux_italic', 'all_caps', 'small_caps'))
            or doc.get('box_size') is not None):
        raise ValueError('motion text requires bounded plain horizontal Inter Regular point text')
    video.text(doc.get('text'))


def read_native(root, normalize=False, filename='document.ecproj'):
    root = Path(root).resolve(); document = root / 'native' / filename
    if document.stat().st_size > 16 << 20:
        raise ValueError('native motion document exceeds 16 MiB')
    data = json.loads(document.read_text())
    if data.get('schema') != 2 or data.get('savedBy') != VERSION or any(data.get(k) for k in ('render_queue', 'render_templates', 'render_prefs')):
        raise ValueError('native motion schema, version or render destinations are not qualified')
    items = data.get('items'); references = {}; comps = []
    if not isinstance(items, dict) or not 1 <= len(items) <= 65:
        raise ValueError('invalid native motion item inventory')
    for key, item in items.items():
        if not isinstance(item, dict) or str(item.get('id')) != key or item.get('proxy') or item.get('parent') is not None:
            raise ValueError('native motion items must have unique identities and no proxies or external parents')
        kind = item['kind']
        if kind['type'] == 'Comp':
            comps.append(item)
        elif kind['type'] == 'Footage':
            if kind.get('kind') not in ('Still', 'Video') or kind.get('missing') or kind.get('sequence') or kind.get('layer'):
                raise ValueError('only present still and video footage is supported')
            stored = kind['path']
            if normalize and Path(stored).is_absolute():
                resolved = Path(stored).resolve()
                if resolved.parent != root / 'assets' or not MEDIA.fullmatch(resolved.name):
                    raise ValueError('motion footage references files outside the project')
                kind['path'] = '../assets/' + resolved.name
            path = kind['path']
            if not isinstance(path, str) or not path.startswith('../assets/') or not MEDIA.fullmatch(path[10:]):
                raise ValueError('motion footage requires portable project assets')
            asset = root / path[3:]
            if asset.is_symlink() or (root / 'assets').is_symlink() or not asset.is_file() or asset.resolve().parent != root / 'assets':
                raise ValueError('motion media is missing or unsafe')
            if kind['kind'] != ('Video' if asset.suffix == '.mp4' else 'Still') or not kind.get('has_video'):
                raise ValueError('motion media kind differs from its declared format')
            inspect_media(asset, asset.suffix[1:])
            if any(not video.integer(kind.get(k), 1, 8192) for k in ('width', 'height')):
                raise ValueError('motion source media exceeds dimension bounds')
            references[asset.name] = video.digest(asset)
        else:
            raise ValueError('native motion item type is not qualified')
    if len(comps) != 1:
        raise ValueError('typed motion requires exactly one composition')
    comp = comps[0]['kind']; rate = comp['frame_rate']
    if (rate.get('den') != 1 or type(rate.get('num')) is not int or rate['num'] not in (24, 25, 30, 50, 60)
            or any(not video.integer(comp.get(k), 16, 1920) or comp[k] % 2 for k in ('width', 'height'))
            or type(comp.get('duration')) is not int or comp['duration'] % (TICKS // rate['num'])
            or not 1 <= comp['duration'] // (TICKS // rate['num']) <= 36000):
        raise ValueError('native composition timing or dimensions are not supported')
    layers = comp['layers']; ids = set()
    if not isinstance(layers, list) or not 1 <= len(layers) <= 64:
        raise ValueError('native composition exceeds layer bounds')
    for layer in layers:
        ident = layer['id']; source = layer['source']
        if type(ident) is not int or ident <= 0 or ident in ids or source.get('type') not in ('Shape', 'Text', 'Footage'):
            raise ValueError('invalid native motion layer identity or type')
        ids.add(ident)
        if source['type'] == 'Footage' and (str(source.get('item')) not in items or items[str(source['item'])]['kind']['type'] != 'Footage'):
            raise ValueError('motion layer must reference admitted project footage')
        if source['type'] == 'Footage':
            footage = items[str(source['item'])]['kind']
            if footage['kind'] == 'Video' and layer['out_point'] - layer['start_time'] > footage['duration']:
                raise ValueError('motion video layer extends past its source duration')
        if (layer.get('parent') is not None or layer.get('track_matte') is not None or layer.get('stretch') != 100
                or layer.get('switches', {}).get('three_d') or not 0 <= layer['in_point'] < layer['out_point'] <= comp['duration']):
            raise ValueError('native layer timing or dependency is not supported')
    # Bound the entire native graph before the engine reads it. Arbitrary
    # expressions, effects, plugins, linked projects and file sources are not
    # part of this typed production contract.
    stack = [(data, 0)]; nodes = 0; keys = 0; uids = set()
    while stack:
        node, depth = stack.pop(); nodes += 1
        if nodes > 150000 or depth > 64:
            raise ValueError('native motion structure exceeds inspection bounds')
        if isinstance(node, dict):
            if 'children' in node and 'uid' in node and node.get('kind', {}).get('kind') not in ('Plain', 'Indexed'):
                raise ValueError('native motion property groups cannot load effects, trackers or external components')
            if node.get('node') in ('Prop', 'Group'):
                if type(node['uid']) is not int or node['uid'] <= 0 or node['uid'] in uids:
                    raise ValueError('motion property identities must be unique positive integers')
                uids.add(node['uid'])
            if node.get('expression') or node.get('expr') or node.get('match') == 'effects' and node.get('children'):
                raise ValueError('motion expressions and effect plugins are not qualified')
            if node.get('t') == 'Text':
                validate_text_document(node.get('v'))
            if node.get('match') == 'sourceText' and node.get('keys'):
                raise ValueError('animated motion source text is not qualified')
            if node.get('match') == 'animators' and node.get('children'):
                raise ValueError('motion character animators are not qualified')
            if 'path' in node and (not isinstance(node['path'], str) or not node['path'].startswith('../assets/') or not MEDIA.fullmatch(node['path'][10:])):
                raise ValueError('native motion has an unsupported file reference')
            if 'keys' in node:
                if not isinstance(node['keys'], list):
                    raise ValueError('invalid native keyframe array')
                keys += len(node['keys'])
            stack.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, depth + 1) for v in node)
        elif isinstance(node, float) and not math.isfinite(node):
            raise ValueError('native motion numbers must be finite')
    if keys > 2000:
        raise ValueError('native motion exceeds 2000 keyframes')
    if normalize:
        document.write_text(json.dumps(data, sort_keys=True) + '\n')
    return data, comps[0], references


def verify_mapping(comp, mapping):
    layers = {v['name']: v for v in comp['kind']['layers']}
    if not isinstance(mapping, dict) or len(layers) != len(comp['kind']['layers']) or set(mapping) != set(layers):
        raise ValueError('editable motion names do not match native layers')
    for name, value in mapping.items():
        if (not video.named(name) or not isinstance(value, dict) or set(value) != {'id', 'type'} or value['type'] not in ('shape', 'text', 'media')
                or type(value['id']) is not int or value['id'] != layers[name]['id'] or layers[name]['source']['type'] != {'shape': 'Shape', 'text': 'Text', 'media': 'Footage'}[value['type']]):
            raise ValueError('editable motion identity or kind differs from the native layer')
    return layers


def native_value(name, value):
    return value + [0 if name == 'position' else 100] if name in ('position', 'scale') else value


def replace_property(session, comp, layer, name, value=None, track=None, fps=24):
    args = {'comp': comp, 'layer': layer, 'path': 'transform/' + name}
    session.command('prop.toggleAnimation', {**args, 'value': False})
    if track is None:
        session.tool('set_property', {**args, 'value': native_value(name, value)})
    else:
        session.tool('add_keyframe', {**args, 'timeBase': 'comp', 'interpolation': track['interpolation'],
                     'keys': [{'time': k['frame'] / fps, 'value': native_value(name, k['value'])} for k in track['keys']]})
    actual = session.tool('get_property', args)
    if track is None:
        if actual.get('keys') or actual['value'] != native_value(name, value):
            raise ValueError('native static property differs from the request')
    else:
        expected = [(k['frame'] / fps, native_value(name, k['value'])) for k in track['keys']]
        observed = [(k['compTime'], k['value']) for k in actual['keys']]
        interpolation = {'linear': 'Linear', 'hold': 'Hold', 'easyEase': 'Bezier'}[track['interpolation']]
        if observed != expected or any(k['in'] != interpolation or k['out'] != interpolation for k in actual['keys']):
            raise ValueError('native key timing, value or interpolation differs from the request')
    return actual['uid']


def protected(data, editable):
    """Ignore only explicitly targeted property leaves when checking revisions."""
    value = copy.deepcopy(data)
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get('node') == 'Prop' and node.get('uid') in editable:
                uid = node['uid']; node.clear(); node['uid'] = uid
            else:
                stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    # Opening a saved project changes only the session's composition view.
    for key in ('activeComp', 'openComps'):
        value.pop(key, None)
    return value


def inspect_movie(path):
    """Inspect the bounded, non-fragmented H.264 export without another engine.

    Read metadata only. Independent acceptance decodes every frame; this runtime
    check establishes encoded dimensions, codec, sample count and exact timing.
    """
    with Path(path).open('rb') as stream:
        length = os.fstat(stream.fileno()).st_size
        if not 16 <= length <= 1 << 30:
            raise ValueError('motion export size exceeds qualification')

        def boxes(start, end):
            entries = []; pos = start
            while pos < end:
                if end - pos < 8 or len(entries) >= 40000:
                    raise ValueError('invalid motion movie box boundary')
                stream.seek(pos); size, kind = struct.unpack('>I4s', stream.read(8)); header = 8
                if size == 1:
                    if end - pos < 16:
                        raise ValueError('truncated extended movie box')
                    size = struct.unpack('>Q', stream.read(8))[0]; header = 16
                elif size == 0:
                    size = end - pos
                if size < header or size > end - pos:
                    raise ValueError('invalid motion movie box size')
                entries.append((kind, pos + header, pos + size)); pos += size
            return entries

        def one(entries, kind):
            found = [v for v in entries if v[0] == kind]
            if len(found) != 1:
                raise ValueError('motion movie requires exactly one ' + kind.decode() + ' box')
            return found[0]

        def children(box):
            return boxes(box[1], box[2])

        def payload(box, maximum=400000):
            if box[2] - box[1] > maximum:
                raise ValueError('motion movie metadata exceeds bounds')
            stream.seek(box[1]); return stream.read(box[2] - box[1])

        top = boxes(0, length)
        if any(v[0] == b'moof' for v in top):
            raise ValueError('fragmented motion exports are not qualified')
        tracks = children(one(top, b'moov')); track = children(one(tracks, b'trak'))
        media = children(one(track, b'mdia')); handler = payload(one(media, b'hdlr'))
        if handler[8:12] != b'vide':
            raise ValueError('motion export requires one video-only track')
        mdhd = payload(one(media, b'mdhd'))
        if mdhd[0] == 0:
            timescale, duration = struct.unpack_from('>II', mdhd, 12)
        elif mdhd[0] == 1:
            timescale, duration = struct.unpack_from('>IQ', mdhd, 20)
        else:
            raise ValueError('unsupported movie time header')
        table = children(one(children(one(media, b'minf')), b'stbl'))
        sizes = payload(one(table, b'stsz')); count = struct.unpack_from('>I', sizes, 8)[0]
        timing = payload(one(table, b'stts')); entries = struct.unpack_from('>I', timing, 4)[0]
        if not 1 <= count <= 36000 or not 1 <= entries <= count or len(timing) != 8 + 8 * entries:
            raise ValueError('invalid movie sample timing')
        rows = [struct.unpack_from('>II', timing, 8 + n * 8) for n in range(entries)]
        if sum(v[0] for v in rows) != count or sum(n * delta for n, delta in rows) != duration or timescale <= 0:
            raise ValueError('motion sample count and duration disagree')
        description = payload(one(table, b'stsd'))
        if struct.unpack_from('>I', description, 4)[0] != 1 or description[12:16] != b'avc1':
            raise ValueError('motion export must contain one H.264 sample description')
        width, height = struct.unpack_from('>HH', description, 40)
        return {'codec': 'H.264', 'width': width, 'height': height, 'frames': count,
                'timescale': timescale, 'duration_ticks': duration, 'sample_deltas': [v[1] for v in rows]}


def text_diagnostics(session, comp, mapping, properties):
    reports = {}
    for name, item in mapping.items():
        if item['type'] != 'text':
            continue
        values = [p['value'] for p in properties[name]['properties'] if p['path'] == 'text/sourceText']
        if len(values) != 1 or not isinstance(values[0], str):
            raise ValueError('native motion inspection did not identify one source text value')
        expected = values[0]
        report = session.command('text.diagnostics', {'comp': comp, 'layer': item['id']})
        glyphs = report.get('glyphs')
        if (report.get('schema_version') != 1 or report.get('profile') != 'static-point-text'
                or report.get('layer') != item['id'] or report.get('text') != expected
                or report.get('requested_family') != 'Inter' or report.get('requested_style') != 'Regular'
                or any(report.get(key) is not False for key in ('family_missing', 'synthetic_bold', 'synthetic_italic'))
                or report.get('characters') != len(expected)
                or report.get('missing_glyph_count') != 0 or report.get('non_bundled_glyph_count') != 0
                or not isinstance(glyphs, list) or len(glyphs) > 16000 or report.get('glyph_count') != len(glyphs)
                or expected.strip() and not glyphs):
            raise ValueError('motion text has missing glyphs, font substitution or unsupported native diagnostics')
        clusters = set(); offset = 0
        for character in expected:
            clusters.add(offset); offset += len(character.encode('utf-8'))
        for glyph in glyphs:
            if (not isinstance(glyph, dict) or not video.integer(glyph.get('id'), 1, 65535)
                    or type(glyph.get('cluster')) is not int or glyph['cluster'] not in clusters
                    or glyph.get('family') != 'Inter' or glyph.get('style') != 'Regular'
                    or glyph.get('bundled_inter_regular') is not True
                    or any(glyph.get(key) is not False for key in ('synthetic_bold', 'synthetic_italic', 'variable_instance'))):
                raise ValueError('motion shaping did not use the exact bundled Inter Regular glyphs')
        reports[name] = report
    return reports


def qualify(root, mapping, *, executable=None):
    root = Path(root); document = root / 'native/document.ecproj'
    data, comp, references = read_native(root); verify_mapping(comp, mapping)
    before = video.digest(document); settings = comp['kind']; fps = settings['frame_rate']['num']; frames = settings['duration'] // (TICKS // fps)
    session = Engine(root, executable=executable)
    try:
        session.tool('open_project', {'path': str(document)})
        inspected = session.tool('get_comp', {'comp': comp['id']})
        if (inspected['width'], inspected['height'], inspected['frameRate'], inspected['duration']) != (settings['width'], settings['height'], fps, frames / fps):
            raise ValueError('motion cold reopen changed the composition settings')
        properties = {name: session.tool('get_layer', {'comp': comp['id'], 'layer': item['id'], 'flat': True}) for name, item in mapping.items()}
        typography = text_diagnostics(session, comp['id'], mapping, properties)
        cold = root / 'native/cold-reopened.ecproj'
        if cold.exists():
            raise ValueError('reserved cold-reopen path is present')
        session.tool('save_project', {'path': str(cold)})
        reopened = read_native(root, normalize=True, filename=cold.name)[0]
        if protected(data, set()) != protected(reopened, set()):
            raise ValueError('native motion properties were repaired or changed on cold reopen')
        cold.unlink()
    finally:
        session.close()
    samples = sorted({0, frames // 2, frames - 1}); fingerprints = {}
    for frame in samples:
        output = root / 'exports' / ('frame-' + str(frame) + '.png')
        run(root, '--project', document, 'render-frame', '--frame', frame, '--out', output, executable=executable)
        repeated = root / 'exports/reopened.png'
        run(root, '--project', document, 'render-frame', '--frame', frame, '--out', repeated, executable=executable)
        fingerprints[str(frame)] = photo.pixel_hash(output)
        if photo.pixel_hash(repeated) != fingerprints[str(frame)]:
            raise ValueError('motion samples differ between cold processes')
        repeated.unlink()
    result = json.loads(run(root, '--project', document, 'render', '--out', root / 'exports/document.mp4', '--format', 'h264', '--audio', 'off', '--json', executable=executable))
    movie = inspect_movie(root / 'exports/document.mp4')
    if (movie['width'], movie['height'], movie['frames']) != (settings['width'], settings['height'], frames) or any(delta * fps != movie['timescale'] for delta in movie['sample_deltas']):
        raise ValueError('encoded motion output differs from composition dimensions or timing')
    if video.digest(document) != before or read_native(root)[2] != references:
        raise ValueError('motion source or dependencies changed during cold reopen')
    session = Engine(root, executable=executable)
    try:
        session.tool('open_project', {'path': str(document)})
        if text_diagnostics(session, comp['id'], mapping, properties) != typography:
            raise ValueError('motion glyph diagnostics changed after rendering and cold reopen')
    finally:
        session.close()
    (root / 'native/composition.json').write_text(json.dumps(inspected, sort_keys=True) + '\n')
    (root / 'native/properties.json').write_text(json.dumps(properties, sort_keys=True) + '\n')
    (root / 'native/text-diagnostics.json').write_text(json.dumps(typography, sort_keys=True) + '\n')
    (root / 'native/dependencies.json').write_text(json.dumps({'assets': references, 'font_policy': 'exact bundled Inter Regular; static point-text glyphs verified'}, sort_keys=True) + '\n')
    (root / 'exports/render.json').write_text(json.dumps(result, sort_keys=True) + '\n')
    (root / 'exports/probe.json').write_text(json.dumps(movie, sort_keys=True) + '\n')
    return {'passed': True, 'native_cold_reopen': True, 'native_state_equal': True, 'native_unchanged_on_reopen': True, 'portable_media_verified': True,
            'frames': frames, 'sampled_native_frames': fingerprints, 'sampled_cold_reopen_equal': True,
            'glyph_coverage_verified': True, 'glyph_coverage_scope': 'static-point-text', 'verified_text_layers': len(typography)}


def execute(root, operation, params):
    validate(operation, params, None if operation == 'motion.create' else 'revision')
    root = Path(root).resolve(); native = root / 'native'; exports = root / 'exports'
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True); document = native / 'document.ecproj'; objects = native / 'objects.json'
    before = None; editable = set(); requested_text = {}
    if operation == 'motion.edit':
        before, composition, _ = read_native(root); mapping = json.loads(objects.read_text()); layers = verify_mapping(composition, mapping)
        fps = composition['kind']['frame_rate']['num']; comp = composition['id']
    else:
        mapping = {}; fps = params['fps']
    session = Engine(root)
    try:
        if operation == 'motion.create':
            comp = session.command('comp.new', {'name': 'Dobe composition', 'width': params['width'], 'height': params['height'],
                    'frameRate': fps, 'duration': params['frames'] / fps, 'background': params['background']})['comp']
            for layer in params['layers']:
                kind = layer['type']
                if kind == 'shape':
                    ident = session.command('layer.newShape', {'name': layer['name'], 'kind': layer['shape'], 'size': [layer['width'], layer['height']],
                            'fill': layer['color'], 'position': layer['position']})['layer']
                elif kind == 'text':
                    ident = session.command('layer.newText', {'name': layer['name'], 'text': layer['text'], 'font': 'Inter', 'style': 'Regular',
                            'size': layer['size'], 'fill': layer['color'], 'position': layer['position']})['layer']
                    requested_text[layer['name']] = layer['text']
                else:
                    path = root / 'assets' / (layer['asset'] + '.' + layer['format'])
                    inspect_media(path, layer['format'])
                    imported = session.command('file.import', {'paths': [str(path)], 'sequence': False, 'importAs': 'footage'})
                    if imported.get('errors') or imported.get('warnings') or len(imported.get('items', [])) != 1:
                        raise ValueError('motion import must produce exactly one media item')
                    item = imported['items'][0]
                    ident = session.command('layer.addItem', {'item': item, 'position': layer['position'], 'time': layer['start'] / fps,
                            'in': layer['start'] / fps, 'out': (layer['start'] + layer['frames']) / fps})['layer']
                    session.command('layer.rename', {'layer': ident, 'name': layer['name']})
                mapping[layer['name']] = {'id': ident, 'type': kind}
                session.command('layer.timing', {'layers': [ident], 'start': layer['start'] / fps, 'in': layer['start'] / fps, 'out': (layer['start'] + layer['frames']) / fps})
                for name, default in (('position', [0, 0]), ('scale', [100, 100]), ('rotation', 0), ('opacity', 100)):
                    replace_property(session, comp, ident, name, layer.get(name, default), layer.get('animation', {}).get(name), fps)
        else:
            session.tool('open_project', {'path': str(document)})
            for edit in params['edits']:
                if edit['name'] not in mapping:
                    raise ValueError('motion edit names an unknown layer')
                item = mapping[edit['name']]
                if edit['type'] == 'text':
                    if item['type'] != 'text':
                        raise ValueError('text revision requires a text layer')
                    prior = session.tool('get_property', {'comp': comp, 'layer': item['id'], 'path': 'text/sourceText'})
                    editable.add(prior['uid']); requested_text[edit['name']] = edit['text']
                    session.command('layer.setText', {'comp': comp, 'layer': item['id'], 'text': edit['text']})
                else:
                    if 'animation' in edit:
                        layer = layers[edit['name']]; frame = TICKS // fps
                        animation(edit['property'], edit['animation'], layer['in_point'] // frame, layer['out_point'] // frame)
                    editable.add(replace_property(session, comp, item['id'], edit['property'], edit.get('value'), edit.get('animation'), fps))
        for name, expected in requested_text.items():
            actual = session.tool('get_property', {'comp': comp, 'layer': mapping[name]['id'], 'path': 'text/sourceText'})
            if actual['value'] != expected:
                raise ValueError('native motion text differs from the request')
        session.tool('save_project', {'path': str(document)})
    finally:
        session.close()
    after, composition, _ = read_native(root, normalize=True); actual_layers = verify_mapping(composition, mapping)
    if before is not None and protected(before, editable) != protected(after, editable):
        raise ValueError('motion revision unexpectedly changed an untargeted native property')
    if operation == 'motion.create':
        for layer in params['layers']:
            actual = actual_layers[layer['name']]; step = TICKS // fps
            if actual['in_point'] != layer['start'] * step or actual['out_point'] != (layer['start'] + layer['frames']) * step:
                raise ValueError('native motion timing differs from the request')
    objects.write_text(json.dumps(mapping, sort_keys=True) + '\n')
    for path in exports.iterdir():
        if path.is_file() and (re.fullmatch(r'frame-[0-9]+\.png', path.name) or path.name in ('document.mp4', 'render.json', 'probe.json')):
            path.unlink()
    validation = qualify(root, mapping)
    if before is not None:
        validation['untargeted_native_properties_preserved'] = True
    artifacts = [{'path': p.relative_to(root).as_posix(), 'role': 'native' if p.parent == native else 'export'}
                 for folder in (native, exports) for p in sorted(folder.iterdir()) if p.is_file()]
    artifacts += photo.retained_assets(root)
    return {'engine': {'name': 'effectcraft', 'version': VERSION}, 'artifacts': artifacts, 'validation': validation}


def observe(root, *, executable):
    """Cold-open and render existing editable state without manufacturing an edit."""
    root = Path(root).resolve()
    names = ('document.ecproj', 'objects.json', 'composition.json', 'properties.json', 'text-diagnostics.json', 'dependencies.json')
    actual = {p.relative_to(root).as_posix() for p in (root/'native').rglob('*') if p.is_file()}
    expected = {'native/'+name for name in names}
    if actual != expected:
        raise ValueError('unsupported native media inventory')
    mapping = json.loads((root/'native/objects.json').read_text())
    _, composition, references = read_native(root)
    verify_mapping(composition, mapping)
    assets = {p.relative_to(root).as_posix() for p in (root/'assets').rglob('*') if p.is_file()}
    if assets != {'assets/'+name for name in references}:
        raise ValueError('native media has unreferenced or missing assets')
    validation = qualify(root, mapping, executable=executable)
    deliveries = {'exports/document.mp4', 'exports/probe.json'}
    deliveries.add('exports/render.json')
    deliveries.update('exports/frame-'+str(frame)+'.png' for frame in validation['sampled_native_frames'])
    artifacts = ([{'path': path, 'role': 'native'} for path in sorted(expected)]
                 + [{'path': path, 'role': 'asset'} for path in sorted(assets)]
                 + [{'path': path, 'role': 'export'} for path in sorted(deliveries)])
    return {'engine': {'name': 'effectcraft', 'version': VERSION},
            'artifacts': artifacts, 'validation': validation}
