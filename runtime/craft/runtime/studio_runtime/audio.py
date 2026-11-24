"""Typed native multitrack audio, portable sources and precise editable revisions."""
import copy
import hashlib
import json
import math
from pathlib import Path
import queue
import re
import shutil
import struct
import subprocess
import threading
import tempfile

from . import vector, video

OPERATIONS = ('audio.create', 'audio.edit')
VERSION = '0.20.1'
RATES = (44100, 48000, 96000)
MAX_SAMPLES = 64_000_000
MAX_SECONDS = 600
MAX_OUTPUT_SAMPLES = 2 * max(RATES) * MAX_SECONDS
FADE_SHAPES = {'linear': 'Linear', 'equal_power': 'EqualPower', 's_curve': 'SCurve'}
CLIP_FIELDS = {'start', 'source_in', 'frames', 'gain_db', 'fade_in', 'fade_out', 'fade_shape'}


def clip_values(clip, maximum):
    if (not video.integer(clip.get('start'), 0, maximum - 1)
            or not video.integer(clip.get('source_in', 0), 0, max(RATES) * MAX_SECONDS)
            or not video.integer(clip.get('frames'), 1, maximum)
            or clip['start'] + clip['frames'] > maximum):
        raise ValueError('audio clip requires bounded sample positions and length inside the mix')
    if not video.finite(clip.get('gain_db', 0), -60, 12):
        raise ValueError('audio gain must be between -60 and 12 dB')
    for key in ('fade_in', 'fade_out'):
        if not video.integer(clip.get(key, 0), 0, clip['frames']):
            raise ValueError('audio fade must fit inside the clip')
    if not isinstance(clip.get('fade_shape', 'linear'), str) or clip.get('fade_shape', 'linear') not in FADE_SHAPES:
        raise ValueError('audio fades support linear, equal_power or s_curve')


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported audio operation or parameters')
    if operation == 'audio.create':
        if source_revision is not None or set(params) != {'sample_rate', 'frames', 'tracks'}:
            raise ValueError('audio.create requires sample_rate, frames, tracks and a new project')
        rate = params['sample_rate']
        if type(rate) is not int or rate not in RATES or not video.integer(params['frames'], 1, rate * MAX_SECONDS):
            raise ValueError('audio requires 44100, 48000 or 96000 Hz and at most 600 seconds')
        tracks = params['tracks']; names = set(); count = 0
        if not isinstance(tracks, list) or not 1 <= len(tracks) <= 16:
            raise ValueError('audio requires 1 to 16 tracks')
        for track in tracks:
            if (not isinstance(track, dict) or set(track) - {'name', 'gain_db', 'clips'}
                    or not video.named(track.get('name')) or track['name'] in names
                    or not video.finite(track.get('gain_db', 0), -60, 12)):
                raise ValueError('audio tracks require unique names and bounded gain')
            names.add(track['name']); clips = track.get('clips')
            if not isinstance(clips, list) or not clips:
                raise ValueError('each audio track requires clips')
            end = 0
            for clip in clips:
                if (not isinstance(clip, dict) or set(clip) - CLIP_FIELDS - {'name', 'asset'}
                        or not video.named(clip.get('name')) or clip['name'] in names
                        or not isinstance(clip.get('asset'), str) or not video.ASSET.fullmatch(clip['asset'])):
                    raise ValueError('audio clips require unique names and imported asset identifiers')
                clip_values(clip, params['frames'])
                if clip['start'] < end:
                    raise ValueError('clips on one track must be ordered without overlap; use separate tracks for a mix')
                end = clip['start'] + clip['frames']; names.add(clip['name']); count += 1
            if count > 64:
                raise ValueError('audio supports at most 64 clips')
    else:
        if not source_revision or set(params) != {'edits'} or not isinstance(params['edits'], list) or not 1 <= len(params['edits']) <= 64:
            raise ValueError('audio.edit requires a source revision and 1 to 64 edits')
        targets = set()
        for edit in params['edits']:
            if not isinstance(edit, dict) or not video.named(edit.get('name')) or edit.get('type') not in ('clip', 'track'):
                raise ValueError('audio edit requires a named clip or track')
            changes = set(edit) - {'name', 'type'}
            if not changes or changes - (CLIP_FIELDS if edit['type'] == 'clip' else {'gain_db'}):
                raise ValueError('audio edits support clip timing/gain/fades or track gain')
            target = (edit['type'], edit['name'])
            if target in targets:
                raise ValueError('one audio request cannot edit the same target twice')
            targets.add(target)
            for key in changes:
                value = edit[key]
                if key == 'gain_db':
                    valid = video.finite(value, -60, 12)
                elif key == 'fade_shape':
                    valid = isinstance(value, str) and value in FADE_SHAPES
                else:
                    valid = video.integer(value, 1 if key == 'frames' else 0, max(RATES) * MAX_SECONDS)
                if not valid:
                    raise ValueError('invalid bounded audio edit value')


def assets(operation, params):
    return ({clip['asset']: 'assets/' + clip['asset'] + '.wav' for track in params['tracks'] for clip in track['clips']}
            if operation == 'audio.create' else {})


def engine():
    return 'dobe-audio' if shutil.which('dobe-audio') else 'soundcraft-cli'


class Engine(vector.Engine):
    label = 'audio'

    def __init__(self, root, executable=None):
        self.root = Path(root).resolve()
        self.proc = subprocess.Popen([str(executable) if executable is not None else engine(), 'mcp', '--automation-read-root', str(self.root), '--automation-write-root', str(self.root)],
                                     cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.messages = queue.Queue(); self.counter = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            info = self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                           'clientInfo': {'name': 'dobe-runtime', 'version': '0.1.0'}})
            self.version = info['serverInfo']['version']
            if self.version != VERSION:
                raise ValueError('audio engine version is not qualified; expected ' + VERSION)
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close(); raise

    def tool(self, name, args):
        result = self.call('tools/call', {'name': name, 'arguments': args})
        texts = [part['text'] for part in result.get('content', []) if part.get('type') == 'text']
        if result.get('isError') or len(texts) != 1:
            raise ValueError(str(result.get('content', []))[:1000])
        return json.loads(texts[0])

    def command(self, name, params):
        return self.tool('execute', {'command': name, 'params': params})


def wav_info(path, maximum_samples=MAX_SAMPLES):
    """Bound RIFF metadata and stream all audio bytes, including finite float checks."""
    path = Path(path); size = path.stat().st_size
    if path.is_symlink() or not 44 <= size <= 512 << 20:
        raise ValueError('audio requires a regular bounded WAV file')
    fmt = None; data = None; chunks = 0
    with path.open('rb') as stream:
        header = stream.read(12)
        if header[:4] != b'RIFF' or header[8:] != b'WAVE' or struct.unpack('<I', header[4:8])[0] != size - 8:
            raise ValueError('audio requires a complete RIFF/WAVE file')
        while stream.tell() < size:
            raw = stream.read(8); chunks += 1
            if len(raw) != 8 or chunks > 256:
                raise ValueError('invalid or excessive WAV chunks')
            tag, length = struct.unpack('<4sI', raw); offset = stream.tell(); end = offset + length
            if end + (length & 1) > size:
                raise ValueError('truncated WAV chunk')
            if tag == b'fmt ':
                if fmt is not None or not 16 <= length <= 128:
                    raise ValueError('invalid WAV format chunk')
                raw = stream.read(length); kind, channels, rate, byte_rate, align, bits = struct.unpack('<HHIIHH', raw[:16])
                if kind == 0xfffe:
                    if len(raw) < 40 or raw[26:40] != bytes.fromhex('000000001000800000aa00389b71'):
                        raise ValueError('unsupported extensible WAV subtype')
                    kind = struct.unpack('<H', raw[24:26])[0]
                    if struct.unpack('<H', raw[18:20])[0] != bits:
                        raise ValueError('WAV valid bits must match container width')
                if (kind not in (1, 3) or channels not in (1, 2) or rate not in RATES
                        or bits not in ((8, 16, 24, 32) if kind == 1 else (32,))
                        or align != channels * bits // 8 or byte_rate != rate * align):
                    raise ValueError('WAV requires mono/stereo PCM or float32 at a supported rate')
                fmt = (kind, channels, rate, align, bits)
            elif tag == b'data':
                if data is not None:
                    raise ValueError('multiple WAV audio chunks are not supported')
                data = (offset, length)
            stream.seek(end + (length & 1))
        if fmt is None or data is None or not data[1] or data[1] % fmt[3]:
            raise ValueError('WAV has no complete audio frames')
        kind, channels, rate, align, bits = fmt; frames = data[1] // align
        if frames > rate * MAX_SECONDS or frames * channels > maximum_samples:
            raise ValueError('WAV exceeds the duration or decoded sample budget')
        stream.seek(data[0]); remaining = data[1]; digest = hashlib.sha256(); peak = 0.0
        while remaining:
            raw = stream.read(min(65536, remaining))
            if not raw:
                raise ValueError('truncated WAV audio')
            digest.update(raw); remaining -= len(raw)
            if kind == 3:
                for (value,) in struct.iter_unpack('<f', raw):
                    if not math.isfinite(value):
                        raise ValueError('WAV contains nonfinite samples')
                    peak = max(peak, abs(value))
    return {'sample_rate': rate, 'channels': channels, 'frames': frames, 'bits': bits, 'float': kind == 3,
            'pcm_sha256': digest.hexdigest(), 'peak': peak if kind == 3 else None}


def load_json(path, maximum):
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('audio metadata exceeds its byte limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate audio metadata key')
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite audio metadata')))
    stack = [(data, 0)]; count = 0
    while stack:
        node, depth = stack.pop(); count += 1
        if depth > 48 or count > 50000:
            raise ValueError('audio metadata exceeds structural bounds')
        if isinstance(node, dict):
            stack.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, depth + 1) for v in node)
        elif isinstance(node, float) and not math.isfinite(node):
            raise ValueError('nonfinite audio metadata')
    return data


def native(root):
    """Inspect every media and plugin-bearing field before opening a portable session."""
    root = Path(root).resolve(); folder = root / 'native'
    model = load_json(folder / 'document.scraft', 4 << 20)
    mapping = load_json(folder / 'objects.json', 65536)
    if (not isinstance(model, dict) or model.get('format_version') != 1 or type(model.get('sample_rate')) is not int
            or model.get('sample_rate') not in RATES
            or any(model.get(key) for key in ('videos', 'busses', 'groups', 'midi_originals'))):
        raise ValueError('native audio requires a supported audio-only session')
    if (not isinstance(mapping, dict) or set(mapping) != {'frames', 'tracks', 'clips'}
            or not video.integer(mapping['frames'], 1, model['sample_rate'] * MAX_SECONDS)
            or not isinstance(mapping['tracks'], dict) or not isinstance(mapping['clips'], dict)):
        raise ValueError('invalid audio object mapping or mix duration')
    tracks = model.get('tracks'); sources = model.get('sources')
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 16 or not isinstance(sources, list) or not 1 <= len(sources) <= 64:
        raise ValueError('audio requires bounded native tracks and sources')
    ids = set(); names = set(); source_by_id = {}; dependencies = {}; samples = 0
    def identity(value):
        if not video.integer(value, 1, 2**64 - 1) or value in ids:
            raise ValueError('native audio IDs must be unique positive integers')
        ids.add(value)
    for source in sources:
        identity(source['id']); rel = source.get('path')
        if not isinstance(rel, str) or not re.fullmatch(r'Audio Files/[A-Za-z0-9_-]{1,100}\.wav', rel):
            raise ValueError('native audio source must be a relative packaged WAV')
        path = folder / rel
        if any(p.is_symlink() for p in (folder, folder / 'Audio Files', path)) or not path.resolve().is_relative_to(folder):
            raise ValueError('native audio refuses linked or external sources')
        info = wav_info(path); samples += info['frames'] * info['channels']
        if (source.get('sample_rate') != model['sample_rate'] or source.get('sample_rate') != info['sample_rate']
                or source.get('frames') != info['frames'] or source.get('channels') != info['channels'] or source.get('unsaved')):
            raise ValueError('native source metadata disagrees with its audio')
        source_by_id[source['id']] = source; dependencies['native/' + rel] = video.digest(path)
    if samples > MAX_SAMPLES:
        raise ValueError('native audio exceeds the aggregate decoded sample budget')
    actual_tracks = {}; actual_clips = {}; clip_count = 0
    for track in tracks:
        identity(track['id']); name = track.get('name')
        if (not video.named(name) or name in names or track.get('kind') != 'Audio' or track.get('format') not in ('Mono', 'Stereo')
                or track.get('instrument') is not None or track.get('elastic') is not None or track.get('frozen')
                or track.get('automation') or track.get('ticks_timebase') or track.get('inactive') or track.get('folder') is not None):
            raise ValueError('native audio contains unsupported track state or plugins')
        names.add(name); actual_tracks[name] = track['id']; mixer = track['mixer']
        pan = mixer.get('pan')
        if (any(v is not None for v in mixer.get('inserts', [])) or any(v is not None for v in mixer.get('sends', []))
                or mixer.get('input') != 'None' or mixer.get('output') != 'Main' or mixer.get('vca') is not None
                or mixer.get('surround') is not None or mixer.get('trim_db', 0) != 0 or mixer.get('phase_invert')
                or mixer.get('mute') or mixer.get('solo') or mixer.get('automation_mode') != 'Read'
                or not isinstance(pan, list) or len(pan) != (1 if track['format'] == 'Mono' else 2)
                or any(not video.finite(value, -1, 1) for value in pan)
                or not video.finite(mixer.get('volume_db'), -60, 12)):
            raise ValueError('native audio contains unsupported mixer routing, automation or plugins')
        playlists = track.get('playlists')
        if not isinstance(playlists, list) or len(playlists) != 1 or track.get('active_playlist') != 0:
            raise ValueError('native audio requires one active playlist per track')
        end = 0
        for clip in playlists[0]['clips']:
            identity(clip['id']); name = clip.get('name'); clip_count += 1
            if not video.named(name) or name in names or clip_count > 64 or set(clip['content']) != {'Audio'}:
                raise ValueError('native audio requires unique named audio clips')
            names.add(name); content = clip['content']['Audio']; source = source_by_id.get(content.get('source'))
            if (source is None or set(content) != {'source', 'offset'} or clip.get('stretch', 1) != 1
                    or clip.get('gain_env') or clip.get('muted') or clip.get('group') is not None or clip.get('loop_id') is not None):
                raise ValueError('native audio contains unsupported clip processing')
            spec = {'start': clip['start'], 'source_in': content['offset'], 'frames': clip['length'], 'gain_db': clip['gain_db'],
                    'fade_in': clip['fade_in']['len'], 'fade_out': clip['fade_out']['len']}
            clip_values(spec, mapping['frames'])
            if clip['start'] < end or content['offset'] + clip['length'] > source['frames']:
                raise ValueError('native audio clip overlaps or exceeds its source')
            if source['channels'] != (1 if track['format'] == 'Mono' else 2):
                raise ValueError('native audio track and source channel counts differ')
            for key in ('fade_in', 'fade_out'):
                if clip[key]['shape'] not in FADE_SHAPES.values() or clip[key].get('curvature', 0) != 0:
                    raise ValueError('native audio fade shape is not supported')
            end = clip['start'] + clip['length']; actual_clips[name] = {'id': clip['id'], 'track': track['id']}
    if not clip_count or mapping['tracks'] != actual_tracks or mapping['clips'] != actual_clips:
        raise ValueError('audio mapping does not match the native tracks and clips')
    if not video.integer(model.get('next_id'), max(ids) + 1, 2**64 - 1):
        raise ValueError('native audio allocation counter is invalid')
    return model, mapping, dependencies


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def track_snapshot(model):
    # Rust writes the shortest decimal that round-trips to f32. Compare gain
    # values at that native precision, without relaxing other document fields.
    tracks = copy.deepcopy(model['tracks'])
    for track in tracks:
        track['mixer']['volume_db'] = f32(track['mixer']['volume_db'])
        for clip in track['playlists'][0]['clips']:
            clip['gain_db'] = f32(clip['gain_db'])
    return tracks


def session_snapshot(model):
    """Preserve the complete session, including metadata outside its audio graph.

    Only gain values have the existing native f32 comparison rule. Unknown
    fields must not disappear merely because the remaining PCM still matches.
    """
    result = copy.deepcopy(model)
    result['tracks'] = track_snapshot(model)
    return result


def edit_native(model, edits):
    """Change only declared native fields; native reopening validates the resulting session."""
    tracks = {t['name']: t for t in model['tracks']}
    clips = {c['name']: c for t in model['tracks'] for c in t['playlists'][0]['clips']}
    for edit in edits:
        target = (tracks if edit['type'] == 'track' else clips).get(edit['name'])
        if target is None:
            raise ValueError('audio edit names an unknown ' + edit['type'])
        if edit['type'] == 'track':
            target['mixer']['volume_db'] = f32(edit['gain_db']); continue
        for key in CLIP_FIELDS & edit.keys():
            value = edit[key]
            if key == 'source_in':
                target['content']['Audio']['offset'] = value
            elif key == 'frames':
                target['length'] = value
            elif key in ('fade_in', 'fade_out'):
                target[key]['len'] = value
            elif key == 'fade_shape':
                target['fade_in']['shape'] = target['fade_out']['shape'] = FADE_SHAPES[value]
            else:
                target[key] = f32(value) if key == 'gain_db' else value
    for track in tracks.values():
        track['playlists'][0]['clips'].sort(key=lambda c: (c['start'], c['id']))


def verify_creation(model, params):
    """Check native command effects against the brief, not only a valid file shape."""
    tracks = {track['name']: track for track in model['tracks']}
    if set(tracks) != {track['name'] for track in params['tracks']}:
        raise ValueError('native audio tracks differ from the requested composition')
    for spec in params['tracks']:
        track = tracks[spec['name']]
        if f32(track['mixer']['volume_db']) != f32(spec.get('gain_db', 0)):
            raise ValueError('native track gain differs from the request')
        clips = {clip['name']: clip for clip in track['playlists'][0]['clips']}
        if set(clips) != {clip['name'] for clip in spec['clips']}:
            raise ValueError('native audio placement replaced or omitted a requested clip')
        for wanted in spec['clips']:
            clip = clips[wanted['name']]
            if (clip['start'] != wanted['start'] or clip['length'] != wanted['frames']
                    or clip['content']['Audio']['offset'] != wanted.get('source_in', 0)
                    or f32(clip['gain_db']) != f32(wanted.get('gain_db', 0))):
                raise ValueError('native clip timing or gain differs from the request')
            for key in ('fade_in', 'fade_out'):
                if (clip[key]['len'] != wanted.get(key, 0)
                        or (wanted.get(key, 0) and clip[key]['shape'] != FADE_SHAPES[wanted.get('fade_shape', 'linear')])):
                    raise ValueError('native fade differs from the request')


def execute(root, operation, params, *, executable=None):
    root = Path(root).resolve(); folder = root / 'native'; exports = root / 'exports'
    folder.mkdir(exist_ok=True); exports.mkdir(exist_ok=True); path = folder / 'document.scraft'
    mapping_path = folder / 'objects.json'
    if operation == 'audio.create':
        infos = {asset: wav_info(root / location) for asset, location in assets(operation, params).items()}
        samples = sum(math.ceil(infos[c['asset']]['frames'] * params['sample_rate'] / infos[c['asset']]['sample_rate'])
                      * infos[c['asset']]['channels'] for t in params['tracks'] for c in t['clips'])
        if samples > MAX_SAMPLES:
            raise ValueError('audio import exceeds the aggregate resampled budget')
        e = Engine(root, executable); mapping = {'frames': params['frames'], 'tracks': {}, 'clips': {}}
        try:
            e.command('session.new', {'name': 'Dobe Audio', 'sample_rate': params['sample_rate'], 'bit_depth': 24})
            for track in params['tracks']:
                channels = infos[track['clips'][0]['asset']]['channels']
                if any(infos[c['asset']]['channels'] != channels for c in track['clips']):
                    raise ValueError('clips on one track must have matching channel counts')
                tid = e.command('track.new', {'count': 1, 'kind': 'audio', 'format': 'mono' if channels == 1 else 'stereo', 'name': track['name']})['tracks'][0]
                mapping['tracks'][track['name']] = tid
                e.command('mix.volume', {'tracks': [tid], 'db': track.get('gain_db', 0)})
                for clip in track['clips']:
                    # Import beyond the finished mix: native placement replaces
                    # overlapping clips, so never stage a source over earlier work.
                    staging = params['frames']
                    result = e.command('file.import_audio', {'path': str(root / 'assets' / (clip['asset'] + '.wav')),
                                                            'track': tid, 'at': staging, 'new_tracks': False})['imported'][0]
                    cid = result['clip']; offset = clip.get('source_in', 0)
                    if offset + clip['frames'] > result['frames']:
                        raise ValueError('audio clip exceeds its resampled source')
                    e.command('edit.trim_clip', {'clip': cid, 'start': staging + offset, 'end': staging + offset + clip['frames']})
                    e.command('edit.move_clips', {'clips': [cid], 'to': clip['start']})
                    e.command('clip.rename', {'clip': cid, 'name': clip['name']})
                    e.command('clip.gain', {'clips': [cid], 'db': clip.get('gain_db', 0)})
                    e.command('edit.select', {'clips': [cid], 'start': clip['start'], 'end': clip['start'] + clip['frames']})
                    for key, side in (('fade_in', 'in'), ('fade_out', 'out')):
                        if clip.get(key, 0):
                            shape = {'linear': 'linear', 'equal_power': 'equal power', 's_curve': 's-curve'}[clip.get('fade_shape', 'linear')]
                            e.command('edit.fades_create', {'clip': cid, 'side': side, 'length': clip[key], 'shape': shape})
                    mapping['clips'][clip['name']] = {'id': cid, 'track': tid}
            e.command('session.save_as', {'path': str(path)})
        finally:
            e.close()
        write_json(mapping_path, mapping)
    else:
        model, mapping, _ = native(root)
        edit_native(model, params['edits']); write_json(path, model)
    if operation == 'audio.create':
        verify_creation(native(root)[0], params)
    return observe(root, executable=executable)


def observe(root, *, executable=None, replay_backups=False):
    """Cold-open and render the complete existing session without inventing an edit.

    Callers inspecting imported projects must use a disposable copy: the native
    save proves parser preservation and may normalize serialization. Portable
    replay separately requires every imported native byte to remain exact.
    """
    root = Path(root).resolve(); folder = root / 'native'; exports = root / 'exports'
    exports.mkdir(exist_ok=True); path = folder / 'document.scraft'
    model, mapping, dependencies = native(root)
    expected = copy.deepcopy(model)
    reports = []
    # Two separate native processes must produce identical PCM, and saved
    # editable content must survive reopening without changing audio fields.
    for name in ('document', 'reopened'):
        e = Engine(root, executable)
        try:
            opened = e.command('session.open', {'path': str(path)})
            if opened.get('missing'):
                raise ValueError('native audio has missing media')
            inspection = e.tool('inspect_session', {})
            if any(not s.get('loaded') for s in inspection['sources']):
                raise ValueError('native audio source did not load')
            if name == 'document':
                e.command('session.save_as', {'path': str(path), 'replace': True})
            report = e.command('file.bounce_mix', {'path': str(exports / (name + '.wav')), 'format': 'wav', 'bit_depth': '32f',
                                                 'start': 0, 'end': mapping['frames'], 'normalize': False, 'dither': False})
            reports.append(report)
        finally:
            e.close()
    reopened, current_mapping, current_dependencies = native(root)
    if (session_snapshot(reopened) != session_snapshot(expected)
            or current_mapping != mapping or current_dependencies != dependencies):
        raise ValueError('native audio reopen/save changed editable content or source audio')
    first = wav_info(exports / 'document.wav', MAX_OUTPUT_SAMPLES)
    second = wav_info(exports / 'reopened.wav', MAX_OUTPUT_SAMPLES)
    if (first != second or first['sample_rate'] != model['sample_rate'] or first['frames'] != mapping['frames']
            or first['channels'] != 2 or not first['float']):
        raise ValueError('native audio mix or cold-reopen PCM does not match')
    (exports / 'reopened.wav').unlink()
    write_json(folder / 'dependencies.json', dependencies)
    # Enumerate the actual native contract, not arbitrary files found under
    # native/. Replay rejects undeclared extras instead of blessing them.
    artifacts = [{'path': 'native/'+name, 'role': 'native'}
                 for name in ('document.scraft', 'objects.json', 'dependencies.json')]
    artifacts += [{'path': location, 'role': 'asset'} for location in sorted(dependencies)]
    # Original imports remain separate from the native engine's resampled media.
    if (root / 'assets').exists():
        artifacts += [{'path': str(p.relative_to(root)), 'role': 'asset'}
                      for p in sorted((root / 'assets').glob('*.wav'))]
    backups = folder / 'Backups'
    observations = []
    if backups.exists():
        if backups.is_symlink() or not backups.is_dir():
            raise ValueError('Audio backup directory must be local and regular')
        entries = sorted(backups.iterdir())
        if len(entries) > 64:
            raise ValueError('Audio backup count exceeds the replay budget')
        for backup in entries:
            if (backup.is_symlink() or not backup.is_file()
                    or not re.fullmatch(r'document backup [1-9][0-9]*\.scraft', backup.name)
                    or not 0 < backup.stat().st_size <= 4 << 20):
                raise ValueError('Audio backup must be a bounded native session')
            artifacts.append({'path': backup.relative_to(root).as_posix(), 'role': 'native'})
            if replay_backups:
                original = backup.read_bytes()
                # A backup is an independently observed retained session, not
                # proof of a typed revision chain. Never normalize its bytes.
                with tempfile.TemporaryDirectory(prefix='.audio-backup-', dir=root) as temporary:
                    inspection_root = Path(temporary)
                    (inspection_root/'native/Audio Files').mkdir(parents=True)
                    (inspection_root/'native/document.scraft').write_bytes(original)
                    shutil.copyfile(folder/'objects.json', inspection_root/'native/objects.json')
                    for location in dependencies:
                        shutil.copyfile(root/location, inspection_root/location)
                    inspected = observe(inspection_root, executable=executable)
                    pcm = wav_info(inspection_root/'exports/document.wav', MAX_OUTPUT_SAMPLES)
                if backup.read_bytes() != original:
                    raise ValueError('Audio retained backup bytes changed during observation')
                observations.append({'path': backup.relative_to(root).as_posix(),
                                     'sha256': hashlib.sha256(original).hexdigest(),
                                     'native_state_equal': inspected['validation']['native_state_equal'],
                                     'pcm_sha256': pcm['pcm_sha256']})
    expected_paths = {entry['path'] for entry in artifacts if entry['path'].startswith('native/')}
    actual_paths = {p.relative_to(root).as_posix() for p in folder.rglob('*') if p.is_file() or p.is_symlink()}
    if actual_paths != expected_paths:
        raise ValueError('Audio native inventory contains unqualified files')
    artifacts.append({'path': 'exports/document.wav', 'role': 'export'})
    return {'engine': {'name': 'soundcraft', 'version': VERSION}, 'artifacts': artifacts,
            'validation': {'passed': True, 'native_cold_reopen': True, 'pcm_roundtrip_equal': True,
                           'native_state_equal': True, 'retained_backups_observed': replay_backups,
                           'backup_observations': observations,
                           'editable_audio_unchanged_on_reopen': True, 'source_audio_hashes_preserved': True,
                           'sample_rate': first['sample_rate'], 'channels': first['channels'], 'frames': first['frames'],
                           'peak': first['peak'], 'float_output_preserves_headroom': True},
            'provenance': {'native_bounce': reports[0]}}
