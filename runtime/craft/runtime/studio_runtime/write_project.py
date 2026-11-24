"""Portable Write projects with exact originals and replayable typed revisions.

The package owns source, baseline model and current model independently. A DOCX
baseline is an observation supplied by the caller, never proof that conversion
preserved every source feature. Native execution and durable publication remain
the responsibility of the operation adapter.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import zipfile

from . import write_container as container, write_structure, write_resources, write_retained, write_revision
from .write_container import require

MAX_HISTORY = 32
MAX_EDITS = 128
MAX_REPLAY_BYTES = 256 << 20
MAX_MANIFEST = 1 << 20


def sha(data): return hashlib.sha256(data).hexdigest()


def native_profile(data):
    document = container.inspect_bytes(data, 'json')['document']
    structure = write_structure.inspect(document); resources = write_resources.inspect(document); retained = write_retained.inspect(document)
    pending = set(structure['pending_qualification']) | set(resources['pending_qualification']) | set(retained['pending_qualification'])
    return {'document': document, 'structure': structure, 'resources': resources, 'retained': retained,
            'pending_qualification': sorted(pending), 'engine_admission_complete': False}


def record(data): return {'sha256': sha(data), 'bytes': len(data)}


def engine_pin(value):
    require(type(value) is dict and set(value) == {'product', 'version', 'source_revision', 'source_lock_sha256'}, 'project engine pin fields differ')
    require(value['product'] == 'dobe-write' and type(value['version']) is str and re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', value['version']) is not None,
            'project engine product/version is invalid')
    for field, length in (('source_revision', 40), ('source_lock_sha256', 64)):
        require(type(value[field]) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}', value[field]) is not None, 'project engine pin digest is invalid')
    return dict(value)


def require_engine(checked, installed_pin):
    """Compare a pin already verified by the caller's installed-engine receipt."""
    require(engine_pin(installed_pin) == checked['manifest']['engine'], 'project needs its pinned engine source and dependency lock')


def pack(manifest, members):
    require('project.json' not in members, 'project manifest conflicts with a payload member')
    encoded = (write_revision.canonical(manifest)+'\n').encode('ascii')
    require(len(encoded) <= MAX_MANIFEST, 'project manifest exceeds its byte budget')
    require(sum(map(len, members.values()))+len(encoded) <= container.MAX_SOURCE, 'project members exceed aggregate byte budget')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data in sorted({'project.json': encoded, **members}.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0)); entry.create_system = 3; entry.external_attr = 0o100600 << 16
            archive.writestr(entry, data)
    result = buffer.getvalue(); require(len(result) <= container.MAX_SOURCE, 'project archive exceeds byte budget'); return result


def inspect_bytes(data):
    require(type(data) is bytes and 0 < len(data) <= container.MAX_SOURCE, 'project archive exceeds byte budget')
    members, directories, _ = container.archive_members(data)
    require(not directories and 'project.json' in members and len(members['project.json']) <= MAX_MANIFEST, 'project manifest/directory inventory is invalid')
    manifest = container.strict_json(members['project.json'])
    require(type(manifest) is dict and set(manifest) == {'format', 'version', 'source_format', 'engine', 'members', 'history'}, 'project manifest fields differ')
    require(manifest['format'] == 'dobe-write-project' and type(manifest['version']) is int and manifest['version'] == 1,
            'project format/version is unsupported')
    engine_pin(manifest['engine'])
    kind = manifest['source_format']; require(type(kind) is str and kind in ('json', 'docx'), 'project source format is unsupported')
    original_name = 'original.'+kind
    expected_names = {original_name, 'baseline.json', 'document.json'}
    require(set(members) == expected_names | {'project.json'} and type(manifest['members']) is dict and set(manifest['members']) == expected_names,
            'project contains missing or unaccounted members')
    for name in expected_names:
        expected = manifest['members'][name]
        require(type(expected) is dict and set(expected) == {'sha256', 'bytes'} and type(expected['bytes']) is int
                and type(expected['sha256']) is str and re.fullmatch('[0-9a-f]{64}', expected['sha256']) is not None,
                'project member record is invalid')
        require(expected == record(members[name]), 'project member hash or size differs')
    source = container.inspect_bytes(members[original_name], kind)
    baseline = members['baseline.json']; current = members['document.json']
    if kind == 'json': require(baseline == members[original_name], 'project JSON baseline must preserve exact original bytes')
    baseline_profile = native_profile(baseline)
    history = manifest['history']
    require(type(history) is list and len(history) <= MAX_HISTORY, 'project revision history exceeds budget')
    replay = baseline; replay_bytes = len(replay); edits = 0
    for entry in history:
        require(type(entry) is dict and set(entry) == {'before', 'after', 'edits'} and type(entry['edits']) is list,
                'project revision record is invalid')
        edits += len(entry['edits']); require(edits <= MAX_EDITS, 'project revision edits exceed aggregate budget')
        require(entry['before'] == sha(replay), 'project revision chain does not own its predecessor')
        prediction = write_revision.revise_bytes(replay, entry['before'], entry['edits']); replay = prediction['data']
        require(entry['after'] == sha(replay), 'project revision result differs from exact typed replay')
        replay_bytes += len(replay); require(replay_bytes <= MAX_REPLAY_BYTES, 'project revision replay exceeds byte budget')
    require(replay == current, 'project current document differs from exact revision replay')
    profile = baseline_profile if current == baseline else native_profile(current)
    pending = set(baseline_profile['pending_qualification']) | set(profile['pending_qualification']) | {'native-full-model-comparison', 'document-source-fidelity'}
    if kind == 'docx': pending.add('docx-baseline-source-correspondence')
    return {'manifest': manifest, 'members': members, 'source': source, 'baseline': baseline_profile, 'current': profile,
            'sha256': sha(data), 'source_sha256': sha(members[original_name]), 'current_sha256': sha(current),
            'revision_count': len(history), 'replayed_edits': edits, 'replayed_bytes': replay_bytes,
            'pending_qualification': sorted(pending), 'engine_admission_complete': False}


def create(source, kind, baseline=None, *, engine):
    container.inspect_bytes(source, kind)
    if kind == 'json':
        require(baseline is None or baseline == source, 'project JSON baseline cannot replace original source'); baseline = source
    else: require(type(baseline) is bytes, 'project DOCX requires a separately observed complete native baseline')
    native_profile(baseline)
    members = {'original.'+kind: source, 'baseline.json': baseline, 'document.json': baseline}
    manifest = {'format': 'dobe-write-project', 'version': 1, 'source_format': kind, 'engine': engine_pin(engine),
                'members': {k: record(v) for k, v in members.items()}, 'history': []}
    result = pack(manifest, members); inspect_bytes(result); return result


def revise(data, expected_sha256, edits):
    require(type(data) is bytes and type(expected_sha256) is str and sha(data) == expected_sha256, 'project revision hash is stale')
    checked = inspect_bytes(data); manifest = checked['manifest']
    require(len(manifest['history']) < MAX_HISTORY, 'project revision history exceeds budget')
    current = checked['members']['document.json']; prediction = write_revision.revise_bytes(current, sha(current), edits)
    members = {k: v for k, v in checked['members'].items() if k != 'project.json'}; members['document.json'] = prediction['data']
    manifest['members']['document.json'] = record(prediction['data'])
    manifest['history'].append({'before': sha(current), 'after': sha(prediction['data']), 'edits': prediction['edits']})
    result = pack(manifest, members); updated = inspect_bytes(result)
    require(updated['members']['original.'+manifest['source_format']] == checked['members']['original.'+manifest['source_format']]
            and updated['members']['baseline.json'] == checked['members']['baseline.json'], 'project revision changed immutable original or baseline')
    return result


def checkout(root, destination, data, *, cancelled=lambda: False):
    """Materialize fixed owned files in a new disposable attempt directory.

This is not the durable revision publication boundary. The worker publishes a
completed attempt only after native verification, cancellation and lease checks.
"""
    checked = inspect_bytes(data); root = Path(root).resolve(strict=True); destination = Path(destination).absolute()
    try: relative = destination.relative_to(root)
    except ValueError as error: raise ValueError('Write project checkout must stay inside its attempt') from error
    require(relative.parts and '..' not in relative.parts, 'project checkout must name an attempt descendant')
    cursor = root
    for part in relative.parts:
        cursor /= part; require(not cursor.is_symlink(), 'project checkout path cannot contain symbolic links')
    require(destination.parent.is_dir() and not destination.exists() and not cancelled(), 'project checkout needs a new destination and active attempt')
    destination.mkdir(mode=0o700); created = []
    try:
        for name, value in checked['members'].items():
            require(not cancelled(), 'project checkout cancelled')
            path = destination/name
            with path.open('xb') as stream:
                created.append(path); stream.write(value); stream.flush(); os.fsync(stream.fileno())
            require(container.read_bytes(path) == value, 'project checkout changed owned bytes')
        require(not cancelled(), 'project checkout cancelled')
    except BaseException:
        for path in reversed(created): path.unlink()
        destination.rmdir(); raise
    return {'directory': str(destination), 'project_sha256': checked['sha256'], 'source_sha256': checked['source_sha256'],
            'current_sha256': checked['current_sha256'], 'revision_count': checked['revision_count'],
            'engine': checked['manifest']['engine'],
            'pending_qualification': checked['pending_qualification'], 'engine_admission_complete': False}
