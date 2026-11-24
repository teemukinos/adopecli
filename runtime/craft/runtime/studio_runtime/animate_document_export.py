"""Typed SVG, Lottie and self-contained HTML delivery from the native engine.

Construction, metadata, embedded media, source preservation and cold repeatability
are qualified here. Browser/player fidelity and exhaustive loss reporting remain
separate release requirements. Generated pages are never executed by this module.
"""
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import time
from xml.parsers import expat

from . import animate_diagnostics as diagnostics, animate_document as document
from . import animate_format as format, animate_media as media, animate_project as project
from . import animate_semantics as semantics
from .animate_graph import fields
from .animate_native_probe import NativeInspector
from .animate_process import run
from .animate_properties import f32
from .animate_unicode import trim

FORMATS = ('svg', 'lottie', 'html')
# Pinned build 27 embeds these exact maintained player.js and canvas.js bytes.
HTML_PLAYER_SHA256 = '99767358b09afae4be48710ff8ec724e13f87b3a5caf1df327222038c8f63a44'
HTML_CODE_BYTES = 83158


def validate(value):
    fields(value, ('format',), ('frame', 'from', 'to', 'background', 'title', 'sound', 'fit'), 'document export request')
    kind = value['format']
    if kind not in FORMATS:
        raise ValueError('Animate document export format must be svg, lottie or html')
    allowed = ('frame',) if kind == 'svg' else ('from', 'to', 'background') if kind == 'lottie' else ('title', 'sound', 'fit')
    fields(value, ('format',), allowed, 'document export request')
    for key in ('frame', 'from', 'to'):
        if key in value:
            diagnostics.integer(value[key], 0, 999_999, 'document export ' + key)
    for key in ('background', 'sound', 'fit'):
        if key in value and type(value[key]) is not bool:
            raise ValueError('Animate document export ' + key + ' must be boolean')
    if 'title' in value and (not isinstance(value['title'], str) or not trim(value['title'])
            or len(value['title']) > 256 or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xd800 <= ord(c) <= 0xdfff for c in value['title'])):
        raise ValueError('Animate HTML title requires 1 to 256 characters without control characters')


def plan(profile, value):
    validate(value); kind = value['format']; total = profile['graph']['frames']
    request = {'format': kind}
    if kind == 'svg':
        request['frame'] = diagnostics.integer(value.get('frame', 0), 0, total - 1, 'SVG movie frame'); count = 1
    elif kind == 'lottie':
        first = diagnostics.integer(value.get('from', 0), 0, total - 1, 'Lottie first frame')
        last = diagnostics.integer(value.get('to', total - 1), first, total - 1, 'Lottie last frame')
        count = diagnostics.integer(last - first + 1, 1, 600, 'Lottie frame count')
        request.update({'from': first, 'to': last, 'background': value.get('background', False)})
    else:
        count = diagnostics.integer(total, 1, 6000, 'HTML movie frame count')
        request.update(title=value.get('title', 'Dobe animation'), sound=value.get('sound', True), fit=value.get('fit', True))
    stage = profile['envelope']['document']['stage']
    return {'request': request, 'frames': count, 'width': stage['width'], 'height': stage['height'], 'fps': profile['graph']['fps']}


def work(value, kind):
    if kind in ('svg', 'html'):
        fields(value, ('evaluation', 'serialization'), (), 'document export work')
        diagnostics.counters(value['evaluation'], diagnostics.EVALUATION_LIMITS, 'document evaluation work')
        value = value['serialization']
    fields(value, ('bytes_reserved', 'stroke_steps', 'raster_steps', 'helper_steps', 'geometry'), (), 'document serialization work')
    diagnostics.counters({k: v for k, v in value.items() if k != 'geometry'},
        {'bytes_reserved': 512 << 20, 'stroke_steps': 32_000_000 if kind == 'html' else 4_000_000,
         'raster_steps': 1_000_000_000, 'helper_steps': 256_000_000 if kind == 'html' else 20_000_000}, 'document serialization work')
    limits = diagnostics.GEOMETRY_LIMITS if kind == 'svg' else {
        'path_commands': 32_000_000, 'flatten_points': 32_000_000, 'morph_steps': 160_000_000,
        'sliced_commands': 32_000_000, 'walk_steps': 80_000_000}
    diagnostics.counters(value['geometry'], limits, 'document geometry work')


def svg(data, planned):
    parser = expat.ParserCreate(namespace_separator='}')
    depth = count = 0
    def start(name, attrs):
        nonlocal depth, count
        depth += 1; count += 1
        if depth > 64 or count > 400_000:
            raise ValueError('Animate SVG exceeds its XML structure budget')
        if name.rsplit('}', 1)[-1] in ('script', 'foreignObject') or any(key.rsplit('}', 1)[-1].lower().startswith('on') for key in attrs):
            raise ValueError('Animate SVG must remain a static document')
        for key, value in attrs.items():
            if key.rsplit('}', 1)[-1] == 'href' and not value.startswith(('#', 'data:image/png;base64,')):
                raise ValueError('Animate SVG must not reference external resources')
        if count == 1 and (name != 'http://www.w3.org/2000/svg}svg'
                or attrs.get('width') != str(planned['width']) or attrs.get('height') != str(planned['height'])
                or attrs.get('viewBox') != '0 0 ' + str(planned['width']) + ' ' + str(planned['height'])):
            raise ValueError('Animate SVG stage dimensions disagree with its source')
    def end(_):
        nonlocal depth
        depth -= 1
    def forbidden(*_):
        raise ValueError('Animate SVG must not declare entities or a document type')
    parser.StartElementHandler = start; parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = forbidden; parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise ValueError('Animate SVG is incomplete or malformed') from error
    if depth or not count:
        raise ValueError('Animate SVG has no complete root')
    return {'xml_elements': count}


def lottie(data, planned, reply):
    value = format.strict_json(data, max_items=1_000_000)
    fields(value, ('v', 'fr', 'ip', 'op', 'w', 'h', 'nm', 'ddd', 'assets', 'layers', 'meta'), (), 'Lottie root')
    if (value['v'] != '5.7.0' or value['fr'] != math.floor(planned['fps'] * 1000 + .5) / 1000
            or value['ip'] != 0 or value['op'] != planned['frames'] or value['w'] != planned['width']
            or value['h'] != planned['height'] or value['nm'] != 'animation' or value['ddd'] != 0
            or value['assets'] != [] or value['meta'] != {'g': 'Dobe Animate 0.2.1'} or not isinstance(value['layers'], list)):
        raise ValueError('Animate Lottie metadata disagrees with its request')
    background = int(planned['request']['background'])
    diagnostics.integer(reply['layers'], len(value['layers']) - background, len(value['layers']) - background, 'reported Lottie layers')
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            pending.extend(node.values())
            if all(key in node for key in ('v', 'i', 'o', 'c')):
                if (type(node['c']) is not bool or any(not isinstance(node[key], list) for key in ('v', 'i', 'o'))
                        or len(node['v']) != len(node['i']) or len(node['v']) != len(node['o'])
                        or any(not isinstance(point, list) or len(point) != 2 or any(not format.number(n, -1e9, 1e9) for n in point)
                               for key in ('v', 'i', 'o') for point in node[key])):
                    raise ValueError('Animate Lottie contains an invalid Bezier path')
            if node.get('a') == 1 and isinstance(node.get('k'), list):
                previous = -1
                for key in node['k']:
                    if (not isinstance(key, dict) or type(key.get('t')) is not int or not previous < key['t'] < planned['frames']
                            or key.get('h') != 1):
                        raise ValueError('Animate Lottie has invalid held frame timing')
                    previous = key['t']
    return {'layers': len(value['layers']), 'serialized_fps': value['fr']}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts = []; self.current = None; self.canvases = []; self.title = ''; self.in_title = False
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if len(values) != len(attrs) or 'src' in values or 'href' in values:
            raise ValueError('Animate HTML has duplicate attributes or external resource references')
        if tag == 'script':
            if self.current is not None:
                raise ValueError('Animate HTML contains nested scripts')
            self.current = {'attrs': values, 'text': ''}
        if tag == 'canvas': self.canvases.append(values)
        if tag == 'title': self.in_title = True
    def handle_endtag(self, tag):
        if tag == 'script':
            if self.current is None:
                raise ValueError('Animate HTML contains an unmatched script end')
            self.scripts.append(self.current); self.current = None
        if tag == 'title': self.in_title = False
    def handle_data(self, text):
        if self.current is not None: self.current['text'] += text
        if self.in_title: self.title += text


def html(data, profile, planned, reply):
    if not data.startswith(b'<!DOCTYPE html>\n<html ') or not data.endswith(b'</body>\n</html>\n'):
        raise ValueError('Animate HTML must contain the complete standalone document')
    page = Page()
    try:
        page.feed(data.decode('utf-8')); page.close()
    except UnicodeError as error:
        raise ValueError('Animate HTML must be UTF-8') from error
    request = planned['request']
    if (page.current is not None or len(page.scripts) != 2 or len(page.canvases) != 1 or page.title != request['title']
            or page.scripts[0]['attrs'] != {'type': 'application/json', 'id': 'anicraft-movie'}
            or page.scripts[1]['attrs'] != {} or project.digest(page.scripts[1]['text'].encode()) != HTML_PLAYER_SHA256):
        raise ValueError('Animate HTML structure, title or maintained player code is inconsistent')
    canvas = page.canvases[0]
    if canvas.get('width') != str(planned['width']) or canvas.get('height') != str(planned['height']) or canvas.get('aria-label') != request['title']:
        raise ValueError('Animate HTML canvas disagrees with its requested stage or title')
    payload = page.scripts[0]['text']
    if '<' in payload:
        raise ValueError('Animate HTML movie data contains unescaped markup')
    value = format.strict_json(payload, max_items=1_000_000)
    fields(value, ('v', 'generator', 'stage', 'fit', 'scenes', 'symbols', 'timelines', 'contents', 'paths', 'paints', 'images', 'sounds'), (), 'HTML movie')
    stage = value['stage']
    fields(stage, ('w', 'h', 'fps', 'bg'), (), 'HTML stage')
    background = profile['envelope']['document']['stage']['background']
    expected_background = '#' + ''.join(f'{math.floor(f32(f32(background[key]) * 255) + .5):02x}' for key in ('r', 'g', 'b'))
    if (value['v'] != 1 or value['generator'] != 'Dobe Animate 0.2.1' or value['fit'] is not request['fit']
            or stage.get('w') != planned['width'] or stage.get('h') != planned['height']
            or stage.get('fps') != math.floor(planned['fps'] * 1000 + .5) / 1000 or stage['bg'] != expected_background):
        raise ValueError('Animate HTML movie metadata disagrees with its source')
    for key in ('scenes', 'symbols', 'timelines', 'contents', 'paths', 'paints', 'images', 'sounds'):
        if not isinstance(value[key], list):
            raise ValueError('Animate HTML movie tables must be arrays')
    for key, table in [('scenes', 'scenes'), ('timelines', 'timelines'), ('stored_frames', 'contents'), ('paths', 'paths'), ('images', 'images'), ('sounds', 'sounds')]:
        diagnostics.integer(reply[key], len(value[table]), len(value[table]), 'reported HTML ' + key)
    diagnostics.integer(reply['data_bytes'], len(payload.encode()), len(payload.encode()), 'HTML data bytes')
    diagnostics.integer(reply['code_bytes'], HTML_CODE_BYTES, HTML_CODE_BYTES, 'HTML code bytes')
    scenes = profile['envelope']['document']['scenes']
    if value['scenes'] != [{'name': scene['name'], 'tl': i} for i, scene in enumerate(scenes)]:
        raise ValueError('Animate HTML changed scene names or timeline order')
    baked = 0
    for index, timeline in enumerate(value['timelines']):
        if not isinstance(timeline, dict) or not isinstance(timeline.get('f'), list):
            raise ValueError('Animate HTML has an invalid timeline')
        length = diagnostics.integer(timeline.get('n'), 1, 6000, 'HTML timeline length'); baked += length
        if index < len(scenes) and length != profile['graph']['scene_frames'][index]:
            raise ValueError('Animate HTML changed scene duration')
        total = 0
        for pair in timeline['f']:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError('Animate HTML has an invalid frame run')
            diagnostics.integer(pair[0], 0, len(value['contents']) - 1, 'HTML frame content')
            total += diagnostics.integer(pair[1], 1, length, 'HTML frame run length')
        if total != length:
            raise ValueError('Animate HTML frame runs do not cover the timeline')
    diagnostics.integer(baked, 1, 6000, 'HTML baked frames')
    for entry in value['scenes'] + value['symbols']:
        diagnostics.integer(entry.get('tl'), 0, len(value['timelines']) - 1, 'HTML timeline reference')
    images = {row['sha256'] for row in profile['media']['images'].values()}
    sounds = {row['sha256']: row['format'] for row in profile['media']['sounds'].values()}
    for uri in value['images']:
        if not isinstance(uri, str) or not uri.startswith('data:image/png;base64,') or project.digest(media.payload(uri.split(',', 1)[1])) not in images:
            raise ValueError('Animate HTML changed or added embedded image data')
    for sound in value['sounds']:
        fields(sound, ('name', 'mime', 'data'), (), 'HTML sound')
        codec = sounds.get(project.digest(media.payload(sound['data'])))
        if codec is None or sound['mime'] != {'wav': 'audio/wav', 'ogg': 'audio/ogg', 'mp3': 'audio/mpeg'}[codec]:
            raise ValueError('Animate HTML changed or added embedded sound data')
    if not request['sound'] and value['sounds']:
        raise ValueError('Animate HTML included sound despite sound=false')
    return {'baked_frames': baked, 'serialized_fps': stage['fps'], 'player_sha256': HTML_PLAYER_SHA256,
            'embedded_images': len(value['images']), 'embedded_sounds': len(value['sounds'])}


def observe(inspector, source, root, profile, planned):
    from .animate_exports import read_output
    root.mkdir(); output = root / 'output'; output.mkdir()
    kind = planned['request']['format']; filename = {'svg': 'frame.svg', 'lottie': 'animation.json', 'html': 'animation.html'}[kind]
    path = output / filename; saved = root / 'document.anicraft'
    params = {key: value for key, value in planned['request'].items() if key != 'format'}
    steps = [{'cmd': 'file.export_' + kind, 'params': {**params, 'path': str(path)}}, {'cmd': 'file.save', 'params': {'path': str(saved)}}]
    scene_index = 0
    if kind == 'svg':
        local_frame = params['frame']
        for scene_index, length in enumerate(profile['graph']['scene_frames']):
            if local_frame < length:
                break
            local_frame -= length
        steps[0]['params']['frame'] = local_frame
        steps.insert(0, {'cmd': 'scene.select', 'params': {'scene': scene_index}})
    script = root / 'steps.json'; script.write_text(json.dumps(steps))
    replies = format.strict_json(run([str(inspector.executable), 'run', str(source), str(script),
        '--automation-read-root', str(inspector.root), '--automation-write-root', str(root)], root,
        deadline=inspector.deadline, cancelled=inspector.cancelled, stdout_limit=1 << 20), max_items=4096)
    if not isinstance(replies, list) or len(replies) != len(steps) or replies[-1] != {'saved': str(saved)}:
        raise ValueError('Animate document export returned an incomplete native report')
    if kind == 'svg':
        selected = {'scene': scene_index, 'name': profile['envelope']['document']['scenes'][scene_index]['name'],
                    'scenes': len(profile['graph']['scene_frames']), 'frames': profile['graph']['scene_frames'][scene_index]}
        if semantics.difference(selected, replies[0]) is not None:
            raise ValueError('Animate SVG selected an unexpected scene')
    reply = replies[-2]
    extra = ('frame', 'raster_fidelity_verified') if kind == 'svg' else ('frames', 'layers', 'report', 'player_fidelity_verified') if kind == 'lottie' else (
        'frames', 'scenes', 'timelines', 'stored_frames', 'paths', 'images', 'sounds', 'data_bytes', 'code_bytes', 'ms', 'report', 'browser_fidelity_verified')
    fields(reply, ('written', 'bytes', 'notes', 'work', kind + '_serialization_budget_verified', *extra), (), 'document export report')
    fidelity = 'raster' if kind == 'svg' else 'player' if kind == 'lottie' else 'browser'
    if reply['written'] != str(path) or reply[kind + '_serialization_budget_verified'] is not True or reply[fidelity + '_fidelity_verified'] is not False:
        raise ValueError('Animate document export reported an unexpected path or qualification scope')
    diagnostics.integer(reply['frame' if kind == 'svg' else 'frames'], local_frame if kind == 'svg' else planned['frames'],
                        local_frame if kind == 'svg' else planned['frames'], 'reported document frames')
    work(reply['work'], kind)
    if not isinstance(reply['notes'], dict) or any(not isinstance(key, str) or type(n) is not int or not 1 <= n <= 1_000_000 for key, n in reply['notes'].items()):
        raise ValueError('Animate document export has invalid feature-loss notes')
    if {item.name for item in output.iterdir()} != {filename}:
        raise ValueError('Animate document export contains missing or unexpected artifacts')
    data = read_output(path, 64 << 20)
    diagnostics.integer(reply['bytes'], len(data), len(data), 'document export bytes')
    details = svg(data, planned) if kind == 'svg' else lottie(data, planned, reply) if kind == 'lottie' else html(data, profile, planned, reply)
    return saved, {'artifacts': [{'file': filename, 'bytes': len(data), 'sha256': project.digest(data)}],
                   'details': details, 'notes': reply['notes'], 'work': reply['work']}


def prepare(root, source, value, executable, *, cancelled=lambda: False, seconds=120):
    root = Path(root).absolute(); root.mkdir()
    inspector = NativeInspector(executable, root, cancelled=cancelled, seconds=seconds)
    original = document.read_native(source, inspect_sound=inspector); planned = plan(original, value)
    original['native_state'] = inspector.preservation(original['source_bytes'])
    snapshot = root / 'source.anicraft'; snapshot.write_bytes(original['source_bytes'])
    saved, warm = observe(inspector, snapshot, root / 'warm', original, planned)
    decoded = project.reuse_sounds(original); loaded = document.read_native(saved, inspect_sound=decoded)
    semantics.compare(original, loaded)
    saved, cold = observe(inspector, saved, root / 'cold', loaded, planned)
    semantics.compare(loaded, document.read_native(saved, inspect_sound=decoded))
    if warm != cold:
        raise ValueError('Animate cold export changed document bytes, metadata or construction reports')
    if format.read_bytes(source) != original['source_bytes']:
        raise ValueError('Animate document export changed its native source')
    if cancelled() or time.monotonic() >= inspector.deadline:
        raise ValueError('Animate document export cancelled or timed out')
    return root / 'warm/output', {**planned, **warm, 'source_sha256': original['source_sha256'],
        'native_state_equal': True, 'cold_export_equal': True, 'document_structure_verified': True,
        'format_notes': ['SVG style/filter attributes use four-decimal formatting; path coordinates retain native f32 formatting.'] if value['format'] == 'svg' else
                        ['Native numeric rounding includes fps rounded to three decimals.',
                         'Stage background is serialized as opaque RGB when included.'],
        'feature_loss_notes_exhaustive': False, 'browser_player_fidelity_verified': False,
        'interactive_playback_verified': False, 'visual_approval': False, 'publication_authorized': False}
