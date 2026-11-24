"""Prepare editable Animate artifacts inside a durable job's owned attempt.

Native imports retain the exact input, a cold-qualified editable document and
selected stage previews. The complete prepared directory appears only after all
checks pass. This is preparation, not publication of a durable revision.
"""
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import time

from . import animate_document as document, animate_diagnostics as diagnostics
from . import animate_format as format, animate_media as media, animate_semantics as semantics
from .animate_graph import fields
from .animate_native_probe import NativeInspector
from .animate_process import run
from .animate_properties import f32

MAX_PREVIEWS = 64
MAX_PREVIEW_PIXELS = 64_000_000
MAX_PREVIEW_BYTES = 256 << 20


def digest(data):
    return hashlib.sha256(data).hexdigest()


def owned_path(root, path):
    """Require a path below an owned root, with no symlink in its descendants."""
    path = Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError('Animate project path must stay inside its attempt') from error
    if not relative.parts or '..' in relative.parts:
        raise ValueError('Animate project path must name an attempt descendant')
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Animate project paths must not contain symbolic links')
    return path


def mapping_for(profile):
    """Address occurrences, not just IDs reused in different keyframes.

    Scene indices and native IDs are authoritative. Names are descriptive and
    may repeat. Hidden content and unused library symbols remain addressable.
    """
    result = []
    stored = profile['envelope']['document']
    timelines = [({'scene': i}, scene['name'], scene['timeline'])
                 for i, scene in enumerate(stored['scenes'])]
    timelines += [({'symbol': symbol['id']}, symbol['name'], symbol['timeline'])
                  for symbol in stored['library']]
    for owner, name, timeline in timelines:
        result.append({'type': 'timeline', 'selector': owner, 'name': name})
        for layer in timeline['layers']:
            selected = {**owner, 'layer': layer['id']}
            result.append({'type': 'layer', 'selector': selected, 'name': layer['name']})
            for key in layer['keyframes']:
                selected_key = {**selected, 'frame': key['start']}
                result.append({'type': 'keyframe', 'selector': selected_key, 'duration': key['duration']})
                for element in key.get('elements', []):
                    kind = element['kind']
                    result.append({'type': 'element', 'selector': {**selected_key, 'element': element['id']},
                                   'name': element.get('name', ''),
                                   'kind': kind if isinstance(kind, str) else next(iter(kind))})
    return result


def preview_request(profile, frames, scale):
    if frames is None:
        # First frame of every scene makes the multi-scene import visible.
        frames = []; offset = 0
        for length in profile['graph']['scene_frames']:
            frames.append(offset); offset += length
    if not isinstance(frames, list) or len(frames) > MAX_PREVIEWS:
        raise ValueError('Animate previews require at most 64 distinct movie frames')
    requested = diagnostics.request(profile, frames, None)['frames']
    if not format.number(scale, .001, 8):
        raise ValueError('Animate preview scale must be between 0.001 and 8')
    scale = f32(scale)
    stage = profile['envelope']['document']['stage']
    dimensions = [max(1, math.floor(f32(stage[key] * scale) + .5)) for key in ('width', 'height')]
    pixels = dimensions[0] * dimensions[1]
    if requested and (pixels > 16_777_216 or pixels * len(requested) > MAX_PREVIEW_PIXELS):
        raise ValueError('Animate previews exceed the per-frame or aggregate pixel budget')
    return requested, scale, dimensions


def reuse_sounds(profile):
    reports = {row['sha256']: {key: value for key, value in row.items() if key != 'sha256'}
               for row in profile['media']['sounds'].values()}

    def inspect(data, max_samples):
        report = reports.get(digest(data))
        if report is None or report['samples'] > max_samples:
            raise ValueError('Animate prepared document changed embedded audio')
        return report
    return inspect


def observe(inspector, source, directory, frames, scale, dimensions):
    """Render a generated fixed batch, then save to detect render mutations."""
    from PIL import Image
    directory.mkdir()
    steps = [{'cmd': 'file.export_png', 'params': {'path': str(directory / ('frame-' + str(frame) + '.png')),
                                                  'frame': frame, 'scale': scale}} for frame in frames]
    saved = directory / 'document.anicraft'
    steps.append({'cmd': 'file.save', 'params': {'path': str(saved)}})
    script = directory / 'steps.json'; script.write_text(json.dumps(steps))
    command = [str(inspector.executable), 'run', str(source), str(script),
               '--automation-read-root', str(inspector.root), '--automation-write-root', str(directory)]
    replies = format.strict_json(run(command, directory, deadline=inspector.deadline,
                                     cancelled=inspector.cancelled, stdout_limit=1 << 20), max_items=4096)
    if not isinstance(replies, list) or len(replies) != len(steps):
        raise ValueError('Animate preview batch returned an incomplete report')
    fields(replies[-1], ('saved',), (), 'prepared native save report')
    if replies[-1]['saved'] != str(saved):
        raise ValueError('Animate prepared native save reported an unexpected path')
    previews = []; total = 0
    for frame, reply in zip(frames, replies[:-1]):
        fields(reply, ('written', 'bytes', 'frame'), (), 'preview report')
        path = directory / ('frame-' + str(frame) + '.png')
        if (reply['written'] != str(path) or type(reply['frame']) is not int or reply['frame'] != frame
                or type(reply['bytes']) is not int or not 1 <= reply['bytes'] <= format.MAX_JSON):
            raise ValueError('Animate preview report disagrees with its request')
        data = format.read_bytes(path); total += len(data)
        if len(data) != reply['bytes'] or total > MAX_PREVIEW_BYTES:
            raise ValueError('Animate previews exceed their byte budget or reported size')
        media.png(data, *dimensions)
        with Image.open(io.BytesIO(data)) as image:
            with image.convert('RGBA') as rgba:
                pixel_hash = digest(rgba.tobytes())
        previews.append({'frame': frame, 'file': path.name, 'width': dimensions[0], 'height': dimensions[1],
                         'scale': scale, 'bytes': len(data), 'sha256': digest(data), 'rgba_sha256': pixel_hash})
    return saved, previews


def prepare(root, source, destination, executable, *, frames=None, scale=1, soundtrack=None,
            inspect_text=True, cancelled=lambda: False, seconds=120):
    """Return qualified artifacts in one new directory; never modify the source.

    The caller chooses a verified executable and owns the attempt root. Input
    cannot choose commands, scripts, output names or publish-template paths.
    Text issues remain visible on imports; they do not silently repair outlines.
    The durable worker still owns lease fencing and revision publication.
    """
    root = Path(root).resolve(strict=True)
    source = owned_path(root, source); destination = owned_path(root, destination)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Animate preparation requires a new destination in an existing directory')
    if type(inspect_text) is not bool:
        raise ValueError('Animate text inspection option must be boolean')
    inspector = NativeInspector(executable, root, cancelled=cancelled, seconds=seconds)

    def check():
        if inspector.cancelled() or time.monotonic() >= inspector.deadline:
            raise ValueError('Animate project preparation cancelled or timed out')

    check()
    original = document.read_native(source, inspect_sound=inspector)
    frames, scale, dimensions = preview_request(original, frames, scale)
    # Validate audio ranges before any native document is opened.
    diagnostics.request(original, frames, soundtrack)
    original['native_state'] = inspector.preservation(original['source_bytes'])
    original['native_diagnostics'] = inspector.diagnostics(original, frames=frames, soundtrack=soundtrack)
    if inspect_text:
        original['native_text'] = inspector.text(original)
    with tempfile.TemporaryDirectory(prefix='.animate-project-', dir=root) as temporary:
        scratch = Path(temporary); snapshot = scratch / 'source.anicraft'
        snapshot.write_bytes(original['source_bytes'])
        saved, previews = observe(inspector, snapshot, scratch / 'warm', frames, scale, dimensions)
        decoded = reuse_sounds(original)
        prepared = document.read_native(saved, inspect_sound=decoded)
        original['native_semantics'] = semantics.compare(original, prepared)
        cold_saved, cold_previews = observe(inspector, saved, scratch / 'cold', frames, scale, dimensions)
        cold = document.read_native(cold_saved, inspect_sound=decoded)
        semantics.compare(prepared, cold)
        if previews != cold_previews:
            raise ValueError('Animate cold reopen changed selected preview bytes or pixels')
        if format.read_bytes(source) != original['source_bytes']:
            raise ValueError('Animate project preparation changed its input source')
        check()
        result = scratch / 'prepared'; result.mkdir()
        native = result / 'native'; native.mkdir()
        exports = result / 'exports'; exports.mkdir()
        (native / 'document.anicraft').write_bytes(prepared['source_bytes'])
        (native / 'source.anicraft').write_bytes(original['source_bytes'])
        mapping = mapping_for(prepared)
        (native / 'objects.json').write_text(json.dumps(mapping, sort_keys=True) + '\n')
        for preview in previews:
            (exports / preview['file']).write_bytes(format.read_bytes(scratch / 'warm' / preview['file']))
        report = {'source': document.summary(original), 'native_sha256': prepared['source_sha256'],
                  'mapping': mapping, 'previews': previews, 'cold_reopen_equal': True,
                  'selected_preview_pixels_equal': True, 'source_bytes_unchanged': True,
                  'native_state_equal': True, 'visual_approval': False, 'publication_authorized': False,
                  'preview_scope': 'Selected static movie frames only; no interactive playback or audio fidelity claim.'}
        (exports / 'inspection.json').write_text(json.dumps(report, sort_keys=True) + '\n')
        check()
        if destination.exists() or destination.is_symlink():
            raise ValueError('Animate preparation destination appeared during inspection')
        result.rename(destination)
    return report
