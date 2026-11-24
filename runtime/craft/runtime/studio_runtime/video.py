"""Typed native timeline production. No caller-supplied engine commands or paths."""
import copy
import hashlib
import json
import math
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import tempfile
import time

from . import photo, vector

OPERATIONS = ('video.create', 'video.edit')
VERSION = '0.20.1'
TICKS = 254016000000
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
ASSET = re.compile(r'(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})')
COLOR = re.compile(r'#[a-fA-F0-9]{6}')
LABELS = {'Violet', 'Iris', 'Caribbean', 'Lavender', 'Cerulean', 'Forest', 'Rose', 'Mango',
          'Purple', 'Blue', 'Teal', 'Magenta', 'Tan', 'Green', 'Brown', 'Yellow'}


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def finite(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def named(value):
    return isinstance(value, str) and NAME.fullmatch(value)


def clip_spec(value, audio=False):
    if not isinstance(value, dict) or not named(value.get('name')):
        raise ValueError('video items require a unique identifier name')
    allowed = {'name', 'start', 'frames', 'asset', 'source_in'} | ({'gain_db'} if audio else {'color', 'transition'})
    if set(value) - allowed or not integer(value.get('start'), 0, 36000) or not integer(value.get('frames'), 1, 36000):
        raise ValueError('clip timing must use bounded integer frames')
    if value['start'] + value['frames'] > 36000 or not integer(value.get('source_in', 0), 0, 36000):
        raise ValueError('clip timing exceeds the supported timeline')
    if ('asset' in value) == ('color' in value) or (audio and 'asset' not in value):
        raise ValueError('provide exactly one imported asset or color; audio requires an asset')
    if 'asset' in value and (not isinstance(value['asset'], str) or not ASSET.fullmatch(value['asset'])):
        raise ValueError('media requires an imported asset identifier')
    if 'color' in value and (not isinstance(value['color'], str) or not COLOR.fullmatch(value['color']) or value.get('source_in', 0)):
        raise ValueError('color clips require #rrggbb and no source offset')
    if not integer(value.get('transition', 0), 0, min(120, value['frames'])):
        raise ValueError('transition duration exceeds the clip or 120 frames')
    if not finite(value.get('gain_db', 0), -60, 12):
        raise ValueError('audio gain must be between -60 and 12 dB')


def title_spec(value):
    fields = {'name', 'text', 'start', 'frames', 'x', 'y', 'size', 'color'}
    if not isinstance(value, dict) or set(value) != fields or not named(value.get('name')):
        raise ValueError('title requires name, text, start, frames, x, y, size and color')
    text(value['text'])
    if not integer(value['start'], 0, 36000) or not integer(value['frames'], 1, 36000) or value['start'] + value['frames'] > 36000:
        raise ValueError('title timing exceeds the supported timeline')
    if any(not finite(value[k], -4096, 4096) for k in ('x', 'y')) or not finite(value['size'], 1, 512):
        raise ValueError('title position or size exceeds supported bounds')
    if not isinstance(value['color'], str) or not COLOR.fullmatch(value['color']):
        raise ValueError('title color must be #rrggbb')


def text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4000 or '\x00' in value:
        raise ValueError('title text must contain 1 to 4000 characters without NUL')


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported video operation or parameters')
    if operation == 'video.create':
        if source_revision is not None or set(params) - {'width', 'height', 'fps', 'clips', 'titles', 'audio'}:
            raise ValueError('video.create requires a new project and supported parameters')
        if any(not integer(params.get(k), 16, 1920) or params[k] % 2 for k in ('width', 'height')):
            raise ValueError('video dimensions must be even integers between 16 and 1920')
        if type(params.get('fps')) is not int or params['fps'] not in (24, 25, 30, 50, 60):
            raise ValueError('video frame rate must be 24, 25, 30, 50 or 60')
        names = set()
        for key, maximum in (('clips', 100), ('audio', 32), ('titles', 32)):
            values = params.get(key, [])
            if not isinstance(values, list) or len(values) > maximum or (key == 'clips' and not values):
                raise ValueError('video requires 1–100 picture clips, up to 32 audio clips and 32 titles')
            end = 0
            for value in values:
                title_spec(value) if key == 'titles' else clip_spec(value, key == 'audio')
                if value['name'] in names or value['start'] < end:
                    raise ValueError('item names must be unique; each track must be sorted without overlapping clips')
                names.add(value['name']); end = value['start'] + value['frames']
    else:
        if not source_revision or set(params) != {'edits'} or not isinstance(params['edits'], list) or not 1 <= len(params['edits']) <= 100:
            raise ValueError('video.edit requires a source revision and 1 to 100 edits')
        replacements = set()
        for edit in params['edits']:
            if not isinstance(edit, dict) or not named(edit.get('name')):
                raise ValueError('edit requires an existing item name')
            kind = edit.get('type')
            if kind == 'text' and set(edit) == {'type', 'name', 'text'}:
                text(edit['text'])
            elif kind == 'trim' and set(edit) == {'type', 'name', 'edge', 'delta_frames'}:
                if edit['edge'] not in ('in', 'out') or not integer(edit['delta_frames'], -36000, 36000) or not edit['delta_frames']:
                    raise ValueError('trim requires in/out edge and a nonzero bounded delta')
            elif kind == 'gain' and set(edit) == {'type', 'name', 'gain_db'}:
                if not finite(edit['gain_db'], -60, 12):
                    raise ValueError('audio gain exceeds supported bounds')
            elif kind == 'media' and set(edit) == {'type', 'name', 'asset'}:
                if not isinstance(edit['asset'], str) or not ASSET.fullmatch(edit['asset']):
                    raise ValueError('media replacement requires an imported asset identifier')
                if edit['name'] in replacements:
                    raise ValueError('one request cannot replace the same picture clip twice')
                replacements.add(edit['name'])
            else:
                raise ValueError('supported edits are text, regular trim, audio gain and picture media replacement')


def assets(operation, params):
    if operation == 'video.edit':
        return {v['asset']: 'assets/' + v['asset'] for v in params['edits'] if v['type'] == 'media'}
    if operation != 'video.create':
        return {}
    return {v['asset']: 'assets/' + v['asset'] for key in ('clips', 'audio') for v in params.get(key, []) if 'asset' in v}


def engine():
    return 'dobe-video' if shutil.which('dobe-video') else 'filmcraft-cli'


class Engine(vector.Engine):
    """Reuse the internal JSON-RPC transport, with an explicit headless video process."""
    label = 'video'

    def __init__(self, root, *, executable=None):
        self.root = Path(root).resolve()
        self.proc = subprocess.Popen([str(executable) if executable is not None else engine(), '--data-dir', str(self.root / '.video-data'), 'mcp'],
                                     cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self.messages = queue.Queue(); self.counter = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            result = self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                             'clientInfo': {'name': 'dobe-runtime', 'version': '0.1.0'}})
            self.version = result['serverInfo']['version']
            if self.version != VERSION:
                raise ValueError('video engine version is not qualified; expected ' + VERSION)
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close()
            raise

    def tool(self, name, arguments):
        value = self.call('tools/call', {'name': name, 'arguments': arguments})
        if value.get('isError'):
            raise ValueError(str(value.get('content', []))[:1000])
        rows = [v['text'] for v in value.get('content', []) if v.get('type') == 'text']
        if len(rows) != 1:
            raise ValueError('video engine returned an invalid result')
        return json.loads(rows[0])


def run(root, args, json_output=True, *, executable=None):
    result = subprocess.run([str(executable) if executable is not None else engine(), '--data-dir', str(Path(root) / '.video-data'), '--compact', *args],
                            cwd=root, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ValueError(result.stderr[-1500:] or result.stdout[-1500:] or 'video engine failed')
    return json.loads(result.stdout) if json_output else result.stdout


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def portable_native(root, normalize=False):
    """Constrain every native file reference to this project's immutable media."""
    root = Path(root).resolve(); path = root / 'native/document.fcproj'
    if path.stat().st_size > 16 << 20:
        raise ValueError('native video project exceeds 16 MiB')
    data = json.loads(path.read_text())
    if data.get('format') != 'filmcraft.project' or data.get('schema_version') != 17:
        raise ValueError('native video format or schema is not qualified')
    project = data['project']; settings = project['settings']
    if sum('Sequence' in item['kind'] for item in project['items'].values()) != 1:
        raise ValueError('typed video requires exactly one native sequence')
    if (any(settings.get('scratch', {}).values()) or settings.get('ingest', {}).get('enabled')
            or settings.get('ingest', {}).get('destination') or project.get('narrations')
            or project.get('source_graphics') or data.get('view', {}).get('source_path')):
        raise ValueError('native video contains unqualified scratch, ingest or linked-source settings')
    references = {}; nodes = 0; stack = [(data, 0)]
    while stack:
        node, depth = stack.pop(); nodes += 1
        if nodes > 100000 or depth > 64:
            raise ValueError('native video exceeds inspection bounds')
        if isinstance(node, dict):
            if 'File' in node:
                value = node['File']
                if not isinstance(value, dict) or set(value) != {'path'} or not isinstance(value['path'], str):
                    raise ValueError('unsupported native media reference')
                stored = value['path']
                if normalize and Path(stored).is_absolute():
                    resolved = Path(stored).resolve()
                    if resolved.parent != root / 'assets' or not ASSET.fullmatch(resolved.name):
                        raise ValueError('native video references media outside the project')
                    value['path'] = '../assets/' + resolved.name
                if not value['path'].startswith('../assets/') or not ASSET.fullmatch(value['path'][10:]):
                    raise ValueError('native video requires portable project media paths')
                asset = root / value['path'][3:]
                if (asset.is_symlink() or not asset.is_file() or (root / 'assets').is_symlink()
                        or asset.resolve().parent != root / 'assets'):
                    raise ValueError('native video media is missing or unsafe')
                references[asset.name] = digest(asset)
            # These typed recipes do not admit file-bearing effects, proxies,
            # linked projects, narration caches or custom scratch directories.
            for key, value in node.items():
                if key == 'proxy' and value is not None:
                    raise ValueError('native video proxies are not qualified')
                if key == 'path' and value and not (isinstance(value, str) and value.startswith('../assets/') and ASSET.fullmatch(value[10:])):
                    raise ValueError('native video contains an unqualified file path')
                stack.append((value, depth + 1))
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in node)
    if normalize:
        path.write_text(json.dumps(data, sort_keys=True) + '\n')
    return references


def sequence(root, *, executable=None):
    return run(root, ['--project', str(Path(root) / 'native/document.fcproj'), 'inspect', 'sequence'], executable=executable)


def native_clips(root):
    data = json.loads((Path(root) / 'native/document.fcproj').read_text())
    native = next(v['kind']['Sequence'] for v in data['project']['items'].values() if 'Sequence' in v['kind'])
    return {c['id']: c for key in ('video_tracks', 'audio_tracks') for track in native[key] for c in track['items']}


def verify_replacements(root, mapping, before, replacements, edits):
    """Bind each replacement to its authorized asset and preserve the clip around it."""
    if not replacements:
        return
    after = native_clips(root)
    inspected = verify_sequence(sequence(root), mapping)
    data = json.loads((Path(root) / 'native/document.fcproj').read_text())
    for name, replacement in replacements.items():
        ident = mapping[name]['clip']; old = copy.deepcopy(before[ident]); new = copy.deepcopy(after[ident])
        if new['item'] != replacement['item']:
            raise ValueError('native picture replacement selected an unexpected source item')
        source = data['project']['items'][str(new['item'])]['kind'].get('Media', {}).get('media')
        if source != {'File': {'path': '../assets/' + replacement['asset']}}:
            raise ValueError('native picture replacement does not reference its authorized asset')
        # Trimming is separately validated against the requested frame deltas.
        allowed = {'item'}
        if any(e['type'] == 'trim' and e['name'] == name for e in edits):
            allowed |= {'start', 'duration', 'source_in'}
        for key in allowed:
            old.pop(key, None); new.pop(key, None)
        if old != new:
            raise ValueError('picture replacement changed unrelated clip properties')
        clip = inspected[ident]
        if not 0 <= clip['sourceIn'] < clip['sourceOut'] <= replacement['duration']:
            raise ValueError('replacement media is too short for the final trimmed clip')


def verify_sequence(info, mapping):
    settings = info['settings']; rate = settings['frame_rate']
    if rate['den'] != 1 or rate['num'] not in (24, 25, 30, 50, 60):
        raise ValueError('native frame rate is unsupported')
    if any(not integer(settings[k], 16, 1920) or settings[k] % 2 for k in ('width', 'height')):
        raise ValueError('native video dimensions are unsupported')
    if not integer(info.get('durationFrames'), 1, 36000):
        raise ValueError('native video duration exceeds qualification')
    items = [item for kind in ('video', 'audio') for track in info[kind] for item in track['items']]
    clips = {item['clip']: item for item in items}
    if len(items) != len(clips) or len(items) > 164:
        raise ValueError('native video has duplicate or excessive clip identities')
    if not isinstance(mapping, dict) or not 1 <= len(mapping) <= 164:
        raise ValueError('native video requires bounded editable item names')
    ids = set()
    audio_ids = {item['clip'] for track in info['audio'] for item in track['items']}
    for name, value in mapping.items():
        if (not named(name) or not isinstance(value, dict) or set(value) != {'clip', 'kind'}
                or value['kind'] not in ('clip', 'audio', 'title') or type(value['clip']) is not int or value['clip'] <= 0
                or value['clip'] in ids or value['clip'] not in clips):
            raise ValueError('editable video mapping does not match native clips')
        item = clips[value['clip']]
        is_title = any(effect['effect'] == 'graphic_text' for effect in item['effects'])
        if ((value['kind'] == 'audio') != (value['clip'] in audio_ids)
                or (value['kind'] == 'title') != is_title):
            raise ValueError('editable item kind differs from the native clip')
        ids.add(value['clip'])
    if ids != set(clips):
        raise ValueError('native video has unmapped clips')
    return clips


def title_diagnostics(root, mapping, *, executable=None):
    """Qualify native static titles using the renderer's own shaped glyphs.

    Font names alone do not establish coverage. The native query compares every
    used font's bytes with its compiled Inter Regular and rejects animated or
    rich text, for which a single layout would not qualify the whole timeline.
    """
    titles = {name: value for name, value in mapping.items() if value['kind'] == 'title'}
    if not titles:
        return {}
    result = {}
    session = Engine(root, executable=executable)
    try:
        opened = session.command('file.open', {'path': str(Path(root) / 'native/document.fcproj')})
        if opened.get('missingMedia'):
            raise ValueError('source video has missing media')
        for name, value in sorted(titles.items()):
            diagnostic = session.command('graphics.textDiagnostics', {'clip': value['clip']})
            faces = diagnostic.get('faces', [])
            glyphs = diagnostic.get('glyphs', [])
            if (diagnostic.get('schemaVersion') != 1 or diagnostic.get('clip') != value['clip']
                    or diagnostic.get('staticText') is not True or diagnostic.get('simpleInterProfile') is not True
                    or diagnostic.get('font') != 'Inter' or diagnostic.get('style') != 'Regular'
                    or diagnostic.get('missingFamily') is not False or diagnostic.get('missingGlyphs') != 0
                    or diagnostic.get('overflow') is not False or not faces
                    or any(face.get('matchesBundledInterRegular') is not True or face.get('index') != 0 for face in faces)
                    or any(g.get('id', 0) == 0 or g.get('syntheticBold') is not False
                           or g.get('syntheticItalic') is not False or g.get('run') != 0 for g in glyphs)
                    or (not glyphs and diagnostic.get('text', '').strip())):
                raise ValueError('video title ' + name + ' has missing glyphs or unqualified font/layout; requires static bundled Inter Regular')
            result[name] = diagnostic
    finally:
        session.close()
    return result


def qualify(root, mapping, *, executable=None):
    root = Path(root); document = root / 'native/document.fcproj'
    references = portable_native(root)
    inspected = sequence(root, executable=executable); verify_sequence(inspected, mapping)
    before = digest(document)
    # Check before rendering. A failed attempt must not publish a successful
    # movie with missing characters or silently substituted fonts.
    typography = title_diagnostics(root, mapping, executable=executable)
    result = run(root, ['--project', str(document), 'export', str(root / 'exports/document.mp4'),
                        '--format', 'h264', '--range', 'entire', '--gpu-rendering', 'off'], executable=executable)
    exported = result.get('result', result)
    if exported.get('offlineMedia') or exported.get('frames') != inspected['durationFrames']:
        raise ValueError('video export has missing media or an unexpected frame count')
    probe = run(root, ['probe', str(root / 'exports/document.mp4')], executable=executable)
    settings = inspected['settings']; picture = probe.get('video', {})
    if (picture.get('width') != settings['width'] or picture.get('height') != settings['height']
            or picture.get('frame_rate') != settings['frame_rate']
            or not picture.get('codec', '').startswith('H.264')
            or type(probe.get('duration')) is not int
            or abs(probe['duration'] - inspected['duration']) > TICKS // settings['frame_rate']['num']
            or (any(t['items'] for t in inspected['audio']) and len(probe.get('audio_streams', [])) != 1)
            or any(a.get('sample_rate') != 48000 or a.get('channels') != 2 for a in probe.get('audio_streams', []))):
        raise ValueError('encoded video metadata differs from the native timeline')
    boundaries={0,inspected['durationFrames']-1,inspected['durationFrames']//2}
    for track in inspected['video']:
        for item in track['items']:
            boundaries.update((item['startFrame'],item['endFrame']-1))
    samples=sorted(n for n in boundaries if 0<=n<inspected['durationFrames'])
    if len(samples)>12:samples=[samples[round(i*(len(samples)-1)/11)] for i in range(12)]
    fingerprints = {}
    for frame in samples:
        output = root / 'exports' / ('frame-' + str(frame) + '.png')
        run(root, ['--project', str(document), 'render', '--seconds', str(frame / inspected['settings']['frame_rate']['num']),
                   '--out', str(output)], json_output=False, executable=executable)
        fingerprints[str(frame)] = photo.pixel_hash(output)
        repeated = root / 'exports/reopened.png'
        run(root, ['--project', str(document), 'render', '--seconds', str(frame / settings['frame_rate']['num']),
                   '--out', str(repeated)], json_output=False, executable=executable)
        if photo.pixel_hash(repeated) != fingerprints[str(frame)]:
            raise ValueError('native video renders differ between cold processes')
        repeated.unlink()
    if (digest(document) != before or portable_native(root) != references or sequence(root, executable=executable) != inspected
            or title_diagnostics(root, mapping, executable=executable) != typography):
        raise ValueError('native video or dependencies changed during cold reopen')
    (root / 'native/sequence.json').write_text(json.dumps(inspected, sort_keys=True) + '\n')
    (root / 'native/title-diagnostics.json').write_text(json.dumps(typography, sort_keys=True) + '\n')
    (root / 'native/dependencies.json').write_text(json.dumps({'assets': references,
        'font_policy': 'static Inter Regular; used font bytes equal the pinned font compiled into the native engine',
        'title_diagnostics': 'native/title-diagnostics.json'}, sort_keys=True) + '\n')
    (root / 'exports/probe.json').write_text(json.dumps(probe, sort_keys=True) + '\n')
    # Reuse the existing bounded owned H.264/AAC verifier. Longer timelines keep
    # their established native verification without implying complete decoding.
    if decode_inspected(inspected['durationFrames'], settings):
        from . import animate_video_container as container, animate_video_decode as decoder
        rate=settings['frame_rate']
        planned={'frames':inspected['durationFrames'],'encoded_size':[settings['width'],settings['height']],
                 'frame_rate':rate,'audio_samples':round(inspected['durationFrames']*48000*rate['den']/rate['num']) if probe.get('audio_streams') else None}
        movie=root/'exports/document.mp4';deadline=time.monotonic()+120
        checked=container.inspect(movie,planned,deadline=deadline,decode_manifest=True)
        def native(arguments,limit):return json.dumps(run(root,arguments,executable=executable)).encode()
        decoded=decoder.inspect(root,movie,planned,checked,native,deadline=deadline,cancelled=lambda:False)
        decoded.update(cut_boundaries=sorted(boundaries),sampled_native_frames=samples,
                       all_cut_boundaries_sampled=set(boundaries)<=set(samples))
        (root/'exports/decode-inspection.json').write_text(json.dumps(decoded,sort_keys=True)+'\n')
    return {'passed': True, 'native_cold_reopen': True, 'native_unchanged_on_reopen': True,
            'portable_media_verified': True, 'frames': inspected['durationFrames'],
            'sampled_cold_reopen_equal': True, 'sampled_native_frames': fingerprints, 'glyph_coverage_verified': True,
            'glyph_coverage_scope': 'static bundled Inter Regular titles', 'title_count': len(typography),
            'title_diagnostics_cold_reopen_equal': True}


def execute(root, operation, params):
    validate(operation, params, None if operation == 'video.create' else 'revision')
    root = Path(root).resolve(); native = root / 'native'; exports = root / 'exports'
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    document = native / 'document.fcproj'; objects = native / 'objects.json'
    replacements = {}; prior_native = {}
    if operation == 'video.edit':
        portable_native(root)
        mapping = json.loads(objects.read_text()); before = sequence(root); verify_sequence(before, mapping)
        fps = before['settings']['frame_rate']['num']
        prior_native = native_clips(root)
    else:
        mapping = {}; fps = params['fps']
    session = Engine(root)
    try:
        if operation == 'video.create':
            session.command('file.newSequence', {'name': 'Dobe sequence', 'width': params['width'], 'height': params['height'],
                                                'fps': fps, 'sampleRate': 48000, 'video': 2, 'audio': 1})
            for key in ('clips', 'audio'):
                for value in params.get(key, []):
                    if 'asset' in value:
                        imported = session.tool('media_import', {'paths': [str(root / 'assets' / value['asset'])]})
                        if imported.get('errors') or len(imported.get('items', [])) != 1:
                            raise ValueError('media import did not produce exactly one source item')
                        item = imported['items'][0]
                    else:
                        item = session.command('file.newColorMatte', {'color': value['color'], 'seconds': value['frames'] / fps})['item']
                    placed = session.command('timeline.place', {'item': item, 'track': 'A1' if key == 'audio' else 'V1',
                            'time': value['start'] * (TICKS // fps), 'duration': value['frames'] * (TICKS // fps),
                            'sourceIn': value.get('source_in', 0) * (TICKS // fps), 'insert': False,
                            'video': key == 'clips', 'audio': key == 'audio'})
                    if len(placed['clips']) != 1:
                        raise ValueError('media placement created unexpected linked clips')
                    clip = placed['clips'][0]
                    mapping[value['name']] = {'clip': clip, 'kind': 'audio' if key == 'audio' else 'clip'}
                    if value.get('transition'):
                        session.command('sequence.applyVideoTransition', {'clip': clip, 'edge': 'in', 'effect': 'cross_dissolve', 'frames': value['transition']})
                    if key == 'audio':
                        session.command('clip.audioGain', {'clips': [clip], 'mode': 'set', 'db': value.get('gain_db', 0)})
            for value in params.get('titles', []):
                made = session.command('graphics.newText', {'text': value['text'], 'position': [value['x'], value['y']],
                         'size': value['size'], 'font': 'Inter', 'fontStyle': 'Regular', 'seconds': value['frames'] / fps,
                         'track': 1, 'time': value['start'] * (TICKS // fps), 'newClip': True})
                session.command('graphics.set', {'clip': made['clip'], 'layer': made['layer'], 'props': {'fill_color': value['color']}})
                mapping[value['name']] = {'clip': made['clip'], 'kind': 'title'}
        else:
            opened = session.command('file.open', {'path': str(document)})
            if opened.get('missingMedia'):
                raise ValueError('source video has missing media')
            for edit in params['edits']:
                item = mapping.get(edit['name'])
                if item is None:
                    raise ValueError('video edit names an unknown item')
                if edit['type'] == 'text':
                    if item['kind'] != 'title':
                        raise ValueError('text edits require a title')
                    session.command('graphics.setText', {'clip': item['clip'], 'layer': 0, 'text': edit['text']})
                elif edit['type'] == 'trim':
                    session.command('timeline.trim', {'clip': item['clip'], 'edge': edit['edge'], 'mode': 'regular',
                                      'deltaFrames': edit['delta_frames'], 'linked': False})
                elif edit['type'] == 'media':
                    prior = prior_native[item['clip']]
                    if (item['kind'] != 'clip' or prior.get('link') is not None or prior.get('frame_hold') is not None
                            or prior.get('multicam') is not None or prior.get('custom_label_color') is not None
                            or prior.get('speed') != 1 or prior.get('reverse') is not False
                            or prior.get('label') not in LABELS or not prior.get('name', '').strip()):
                        raise ValueError('media replacement requires an unlinked regular picture clip without holds or custom labels')
                    media = root / 'assets' / edit['asset']
                    probe = run(root, ['probe', str(media)])
                    if not probe.get('video') or type(probe.get('duration')) is not int or probe['duration'] <= 0:
                        raise ValueError('picture replacement requires finite video media')
                    imported = session.tool('media_import', {'paths': [str(media)]})
                    if imported.get('errors') or len(imported.get('items', [])) != 1:
                        raise ValueError('replacement import did not produce exactly one source item')
                    source_item = imported['items'][0]
                    session.command('sequence.linkedSelection', {'on': False})
                    replaced = session.command('clip.replaceFromBin', {'clips': [item['clip']], 'item': source_item, 'keepSourceIn': True})
                    if (replaced.get('clips') != [item['clip']] or replaced.get('item') != source_item
                            or replaced.get('short') != [] or replaced.get('sourceInClamped') != []):
                        raise ValueError('picture replacement changed unexpected clips or has insufficient media')
                    session.command('clip.rename', {'clips': [item['clip']], 'name': prior['name']})
                    session.command('edit.label.' + prior['label'].lower(), {'clips': [item['clip']]})
                    replacements[edit['name']] = {'item': source_item, 'asset': edit['asset'], 'duration': probe['duration']}
                else:
                    if item['kind'] != 'audio':
                        raise ValueError('gain edits require an audio item')
                    session.command('clip.audioGain', {'clips': [item['clip']], 'mode': 'set', 'db': edit['gain_db']})
        session.command('file.saveAs', {'path': str(document)})
    finally:
        session.close()
    portable_native(root, normalize=True)
    objects.write_text(json.dumps(mapping, sort_keys=True) + '\n')
    verify_replacements(root, mapping, prior_native, replacements, params.get('edits', []))
    # Old exports belong to the parent revision. This attempt publishes only
    # the new validated movie, probe and current sample frames.
    for path in exports.iterdir():
        if path.is_file() and (re.fullmatch(r'frame-[0-9]+\.png', path.name) or path.name in ('document.mp4', 'probe.json')):
            path.unlink()
    validation = qualify(root, mapping)
    actual = sequence(root); actual_clips = verify_sequence(actual, mapping)
    if operation == 'video.create':
        for key in ('clips', 'titles', 'audio'):
            for requested in params.get(key, []):
                clip = actual_clips[mapping[requested['name']]['clip']]
                if clip['startFrame'] != requested['start'] or clip['durationFrames'] != requested['frames']:
                    raise ValueError('native clip placement differs from requested timing')
                if key != 'titles' and clip['sourceIn'] != requested.get('source_in', 0) * (TICKS // fps):
                    raise ValueError('native source trim differs from the requested offset')
    raw = json.loads(document.read_text())
    raw_sequence = next(v['kind']['Sequence'] for v in raw['project']['items'].values() if 'Sequence' in v['kind'])
    raw_clips = {c['id']: c for key in ('video_tracks', 'audio_tracks') for t in raw_sequence[key] for c in t['items']}
    requested_text = ({v['name']: v['text'] for v in params.get('titles', [])} if operation == 'video.create'
                      else {v['name']: v['text'] for v in params['edits'] if v['type'] == 'text'})
    for name, expected in requested_text.items():
        effects = [e for e in raw_clips[mapping[name]['clip']]['effects'] if e['effect'] == 'graphic_text']
        if len(effects) != 1 or effects[0]['params']['text'].get('value') != {'Text': expected}:
            raise ValueError('native title text differs from the request')
    requested_gains = ({v['name']: v.get('gain_db', 0) for v in params.get('audio', [])} if operation == 'video.create'
                       else {v['name']: v['gain_db'] for v in params['edits'] if v['type'] == 'gain'})
    for name, expected in requested_gains.items():
        if abs(actual_clips[mapping[name]['clip']]['gainDb'] - expected) > 1e-6:
            raise ValueError('native audio gain differs from the request')
    if operation == 'video.edit':
        after = sequence(root)
        prior_clips = verify_sequence(before, mapping); final_clips = verify_sequence(after, mapping)
        changed_ids = {mapping[e['name']]['clip'] for e in params['edits']}
        if any(prior_clips[k] != final_clips[k] for k in prior_clips.keys() - changed_ids):
            raise ValueError('video edit unexpectedly changed an unrelated clip')
        for edit in params['edits']:
            if edit['type'] == 'trim':
                ident = mapping[edit['name']]['clip']; key = 'startFrame' if edit['edge'] == 'in' else 'endFrame'
                if final_clips[ident][key] - prior_clips[ident][key] != sum(e['delta_frames'] for e in params['edits'] if e['type'] == 'trim' and e['name'] == edit['name'] and e['edge'] == edit['edge']):
                    raise ValueError('requested trim was clamped or changed unexpectedly')
        validation['unaffected_clip_identity_preserved'] = True
        if replacements:
            validation['picture_replacement_identity_preserved'] = True
            validation['replacement_assets'] = {name: value['asset'] for name, value in replacements.items()}
    artifacts = [{'path': p.relative_to(root).as_posix(), 'role': 'native' if p.parent == native else 'export'}
                 for folder in (native, exports) for p in sorted(folder.iterdir()) if p.is_file()]
    artifacts += photo.retained_assets(root)
    return {'engine': {'name': 'filmcraft', 'version': VERSION}, 'artifacts': artifacts, 'validation': validation}


def decode_inspected(frames, settings):
    """Whether qualify() writes the complete owned decode inspection."""
    return frames <= 600 and settings['width']*settings['height']*frames <= 552960000


def observe(root, *, executable):
    """Cold-open and render existing editable state without manufacturing an edit."""
    root = Path(root).resolve()
    names = ('document.fcproj', 'objects.json', 'sequence.json', 'title-diagnostics.json', 'dependencies.json')
    actual = {p.relative_to(root).as_posix() for p in (root/'native').rglob('*') if p.is_file()}
    expected = {'native/'+name for name in names}
    if actual != expected:
        raise ValueError('unsupported native media inventory')
    mapping = json.loads((root/'native/objects.json').read_text())
    references = portable_native(root)
    assets = {p.relative_to(root).as_posix() for p in (root/'assets').rglob('*') if p.is_file()}
    if assets != {'assets/'+name for name in references}:
        raise ValueError('native media has unreferenced or missing assets')
    # Keep the filename: the native save command derives project names from it.
    # Compare the complete serialized model, including fields omitted by the
    # sequence query. No synthetic edits or ignored unknown fields are admitted.
    original = json.loads((root/'native/document.fcproj').read_text())
    with tempfile.TemporaryDirectory(prefix='.cold-video-', dir=root) as directory:
        cold = Path(directory)/'document.fcproj'
        session = Engine(root, executable=executable)
        try:
            opened = session.command('file.open', {'path': str(root/'native/document.fcproj')})
            if opened.get('missingMedia') != 0 or opened.get('migrated') is not False or opened.get('schemaVersion') != 17:
                raise ValueError('native video cold reopen requires exact schema and complete media')
            session.command('file.saveAs', {'path': str(cold)})
        finally:
            session.close()
        if json.loads(cold.read_text()) != original:
            raise ValueError('native video reopen/save changed editable content')
    validation = qualify(root, mapping, executable=executable)
    validation['native_state_equal'] = True
    deliveries = {'exports/document.mp4', 'exports/probe.json'}
    deliveries.update('exports/frame-'+str(frame)+'.png' for frame in validation['sampled_native_frames'])
    # Native execution publishes the decode inspection that qualify() writes for
    # bounded timelines, so replay declares the same delivery.
    replayed = json.loads((root/'native/sequence.json').read_text())
    if decode_inspected(replayed['durationFrames'], replayed['settings']):
        deliveries.add('exports/decode-inspection.json')
    artifacts = ([{'path': path, 'role': 'native'} for path in sorted(expected)]
                 + [{'path': path, 'role': 'asset'} for path in sorted(assets)]
                 + [{'path': path, 'role': 'export'} for path in sorted(deliveries)])
    return {'engine': {'name': 'filmcraft', 'version': VERSION},
            'artifacts': artifacts, 'validation': validation}
