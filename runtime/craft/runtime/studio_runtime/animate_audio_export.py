"""Native soundtrack export with exact range, PCM and cold-save qualification."""
import json
import math
from pathlib import Path
import struct
import time

from . import animate_diagnostics as diagnostics, animate_document as document
from . import animate_format as format, animate_project as project, animate_semantics as semantics
from .animate_graph import fields
from .animate_native_probe import NativeInspector
from .animate_process import run


def validate(value):
    fields(value, ('format',), ('from', 'to', 'rate', 'bits'), 'audio export request')
    if value['format'] != 'wav':
        raise ValueError('Animate audio export format must be wav')
    for key in ('from', 'to'):
        if key in value:
            diagnostics.integer(value[key], 0, 999_999, 'audio export ' + key)
    if value.get('to', value.get('from', 0)) < value.get('from', 0):
        raise ValueError('Animate audio export range is reversed')
    diagnostics.integer(value.get('rate', 44100), 8000, 192000, 'audio export rate')
    bits = value.get('bits', 16)
    if type(bits) is not int or bits not in (16, 24, 32):
        raise ValueError('Animate WAV bits must be 16, 24 or 32 (float)')


def plan(profile, value):
    validate(value)
    requested = diagnostics.request(profile, (), {key: value[key] for key in ('from', 'to', 'rate') if key in value})['soundtrack']
    samples = (diagnostics.frame_start(requested['to'] + 1, profile['graph']['fps'], requested['rate'])
               - diagnostics.frame_start(requested['from'], profile['graph']['fps'], requested['rate']))
    bits = value.get('bits', 16)
    return {'request': {'format': 'wav', **requested, 'bits': bits}, 'frames': requested['to'] - requested['from'] + 1,
            'sample_frames': samples, 'channels': 2, 'fps': profile['graph']['fps'],
            'bytes': 44 + samples * 2 * (bits // 8)}


def inspect(path, reply, soundtrack, planned, inspector):
    from .animate_exports import read_output
    request = planned['request']; rate = request['rate']; bits = request['bits']
    fields(reply, ('written', 'bytes', 'rate', 'seconds', 'frames', 'sounds'), (), 'audio export report')
    for key, expected in [('bytes', planned['bytes']), ('rate', rate), ('frames', planned['frames']), ('sounds', soundtrack['voices'])]:
        diagnostics.integer(reply[key], expected, expected, 'reported audio ' + key)
    if (reply['written'] != str(path) or not format.number(reply['seconds'], 0, diagnostics.MAX_OUTPUT_FRAMES / 8000)
            or reply['seconds'] != planned['sample_frames'] / rate):
        raise ValueError('Animate audio export path or duration disagrees with its request')
    data = read_output(path, planned['bytes'])
    block = 2 * (bits // 8); length = planned['bytes'] - 44
    header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', length + 36, b'WAVE', b'fmt ', 16,
                         3 if bits == 32 else 1, 2, rate, rate * block, block, bits, b'data', length)
    if len(data) != planned['bytes'] or data[:44] != header:
        raise ValueError('Animate WAV header, PCM format or complete sample count is incorrect')
    pcm = memoryview(data)[44:]
    # Every bit pattern is a valid signed PCM integer. Float PCM additionally
    # requires checking every sample for NaN/infinity; no sample list is retained.
    if bits == 32:
        for index, (sample,) in enumerate(struct.iter_unpack('<f', pcm)):
            if not math.isfinite(sample):
                raise ValueError('Animate WAV contains a nonfinite float sample')
            if index % 65536 == 0 and (inspector.cancelled() or time.monotonic() >= inspector.deadline):
                raise ValueError('Animate WAV inspection cancelled or timed out')
    return {'file': path.name, 'bytes': len(data), 'sha256': project.digest(data),
            'pcm_sha256': project.digest(pcm), 'sample_frames': planned['sample_frames'],
            'channels': 2, 'rate': rate, 'bits': bits, 'encoding': 'float' if bits == 32 else 'signed-integer'}


def observe(inspector, source, root, profile, planned):
    root.mkdir(); output = root / 'output'; output.mkdir()
    path = output / 'soundtrack.wav'; saved = root / 'document.anicraft'
    request = planned['request']; sound = {key: request[key] for key in ('from', 'to', 'rate')}
    steps = [{'cmd': 'file.inspect_soundtrack', 'params': sound},
             {'cmd': 'file.export_audio', 'params': {**sound, 'bits': request['bits'], 'path': str(path)}},
             {'cmd': 'file.save', 'params': {'path': str(saved)}}]
    script = root / 'steps.json'; script.write_text(json.dumps(steps))
    replies = format.strict_json(run([str(inspector.executable), 'run', str(source), str(script),
        '--automation-read-root', str(inspector.root), '--automation-write-root', str(root)], root,
        deadline=inspector.deadline, cancelled=inspector.cancelled, stdout_limit=1 << 20), max_items=4096)
    if not isinstance(replies, list) or len(replies) != 3 or replies[-1] != {'saved': str(saved)}:
        raise ValueError('Animate audio export returned an incomplete native report')
    if {item.name for item in output.iterdir()} != {'soundtrack.wav'}:
        raise ValueError('Animate audio export contains missing or unexpected artifacts')
    soundtrack = diagnostics.soundtrack_report(replies[0], sound, profile)
    artifact = inspect(path, replies[1], soundtrack, planned, inspector)
    return saved, {'artifacts': [artifact], 'soundtrack': soundtrack}


def prepare(root, source, value, executable, *, cancelled=lambda: False, seconds=120):
    root = Path(root).absolute(); root.mkdir()
    inspector = NativeInspector(executable, root, cancelled=cancelled, seconds=seconds)
    original = document.read_native(source, inspect_sound=inspector)
    planned = plan(original, value)
    original['native_state'] = inspector.preservation(original['source_bytes'])
    snapshot = root / 'source.anicraft'; snapshot.write_bytes(original['source_bytes'])
    saved, warm = observe(inspector, snapshot, root / 'warm', original, planned)
    decoded = project.reuse_sounds(original)
    loaded = document.read_native(saved, inspect_sound=decoded)
    semantics.compare(original, loaded)
    saved, cold = observe(inspector, saved, root / 'cold', loaded, planned)
    semantics.compare(loaded, document.read_native(saved, inspect_sound=decoded))
    if warm != cold:
        raise ValueError('Animate cold export changed WAV bytes, samples or soundtrack layout')
    if format.read_bytes(source) != original['source_bytes']:
        raise ValueError('Animate audio export changed the native source')
    if cancelled() or time.monotonic() >= inspector.deadline:
        raise ValueError('Animate audio export cancelled or timed out')
    return root / 'warm/output', {**planned, **warm, 'source_sha256': original['source_sha256'],
        'native_state_equal': True, 'cold_export_equal': True, 'complete_decode_verified': True,
        'notes': ['Stereo native soundtrack. Event sounds starting before the selected range are omitted; stream sounds join mid-way.',
                  '16/24-bit PCM rounds and clips samples to the integer range; 32-bit PCM stores finite floats.'],
        'interactive_playback_verified': False, 'audible_approval': False, 'publication_authorized': False}
