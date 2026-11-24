"""Native Interface import and inspection with complete-state preservation.

These helpers prepare attempt-owned artifacts. They do not register customer
operations or approve visual quality, and never publish a runtime revision.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile

from . import interface_document as document, video
from .interface_engine import Engine

MAX_PREVIEWS = 64
MAX_PREVIEW_BYTES = 256 << 20


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def mapping_for(profile):
    """Keep unique usable names; assign stable keys to duplicate/imported names."""
    nodes = [node for node in profile['nodes'].values() if node['type'] != 'page']
    counts = Counter(node.get('name') for node in nodes if video.named(node.get('name')))
    reserved = set(counts); result = {}
    for node in nodes:
        name = node.get('name')
        if not video.named(name) or counts[name] != 1:
            base = 'node_' + str(node['id']); name = base; suffix = 2
            while name in reserved:
                name = base + '_' + str(suffix); suffix += 1
        reserved.add(name)
        result[name] = {'id': node['id'], 'type': node['type'], 'name': node.get('name')}
    return result


def check_mapping(mapping, profile):
    expected = {node['id'] for node in profile['nodes'].values() if node['type'] != 'page'}
    seen = set()
    if not isinstance(mapping, dict) or len(mapping) != len(expected):
        raise ValueError('Interface node mapping does not cover the native document')
    for name, record in mapping.items():
        if (not video.named(name) or not isinstance(record, dict) or set(record) != {'id', 'type', 'name'}
                or not video.integer(record.get('id'), 1, 2**64 - 1) or record['id'] in seen):
            raise ValueError('Interface node mapping is invalid or ambiguous')
        node = profile['nodes'].get(str(record['id']))
        if node is None or node['type'] == 'page' or record['type'] != node['type'] or record['name'] != node.get('name'):
            raise ValueError('Interface node mapping disagrees with native identity')
        seen.add(record['id'])
    if seen != expected:
        raise ValueError('Interface node mapping omits native nodes')


def preview_roots(profile, roots=None):
    if roots is None:
        roots = [child for page in profile['pages'] for child in profile['nodes'][str(page)].get('children', [])]
    if (not isinstance(roots, list) or len(roots) > MAX_PREVIEWS
            or any(not video.integer(value, 1, 2**64 - 1) for value in roots) or len(set(roots)) != len(roots)):
        raise ValueError('Interface inspection requires at most 64 unique preview node IDs')
    for value in roots:
        node = profile['nodes'].get(str(value))
        if node is None or node['type'] == 'page':
            raise ValueError('Interface preview root must be a native layer')
    return list(roots)


def observe(process, profile, directory, roots=None, allowed_fallbacks=()):
    """Inspect current native state and render explicitly identified subtrees."""
    directory = Path(directory)
    process.relative(directory)
    if directory.exists() or directory.is_symlink():
        raise ValueError('Interface inspection requires a new attempt-owned directory')
    roots = preview_roots(profile, roots)
    directory.mkdir()
    # Every saved field and embedded hash must match before attributing diagnostic
    # reports to this profile. A successful open can silently drop unknown fields.
    current = process.save(directory / 'before.figcraft', title=profile['document']['name'])
    document.require_state(current, profile['document'], profile['assets'])
    reports = process.inspect_text(profile, allowed_fallbacks)
    previews = []; pixels = 0; size = 0
    for node_id in roots:
        filename = 'node-' + str(node_id) + '.png'
        path = directory / filename
        rendered = process.render(path, node_id)
        pixels += rendered['pixels'][0] * rendered['pixels'][1]
        size += path.stat().st_size
        if pixels > document.MAX_PIXELS or size > MAX_PREVIEW_BYTES:
            raise ValueError('Interface inspection exceeds its aggregate preview budget')
        previews.append({'id': node_id, 'file': filename, **rendered})
    after = process.save(directory / 'after.figcraft', title=profile['document']['name'])
    document.require_state(after, profile['document'], profile['assets'])
    return {'text': reports, 'previews': previews, 'preview_pixels': pixels, 'preview_bytes': size,
            'export_scope': 'Each preview exports its selected subtree; ancestor clipping and opacity do not apply.',
            'native_state_unchanged': True, 'shaping_verified': all(row['shaping_verified'] for row in reports),
            'clipping_verified': False, 'publication_approved': False}


def import_native(root, source, pending, inspection, *, roots=None, allowed_fallbacks=(), executable=None):
    """Copy a native project through the engine and qualify its cold readback.

    Existing files are never destinations. The source is read only. All outputs
    belong to the current attempt; callers retain or discard them as a unit.
    """
    root, source, pending, inspection = map(Path, (root, source, pending, inspection))
    for path in (source, pending, inspection):
        if path.is_symlink():
            raise ValueError('Interface project paths must not be symbolic links')
        path.resolve().relative_to(root.resolve())
    if pending.exists() or inspection.exists() or pending.resolve() == inspection.resolve():
        raise ValueError('Interface import requires new native and inspection destinations')
    original = document.read_native(source)
    roots = preview_roots(original, roots)
    source_hash = digest(source)
    mapping = mapping_for(original); check_mapping(mapping, original)
    # Keep render probes and save-readback files out of the delivered artifact set.
    with tempfile.TemporaryDirectory(prefix='.interface-inspect-', dir=root) as temporary:
        scratch = Path(temporary)
        with Engine(root, executable=executable) as process:
            opened = process.open(source)
            document.require_state(opened, original['document'], original['assets'])
            saved = process.save(pending, title=original['document']['name'])
            document.require_state(saved, original['document'], original['assets'])
            observed = observe(process, saved, scratch / 'warm', roots, allowed_fallbacks)
        with Engine(root, executable=executable) as process:
            cold = process.open(pending)
            document.require_state(cold, original['document'], original['assets'])
            reopened = observe(process, cold, scratch / 'cold', roots, allowed_fallbacks)
        if reopened != observed:
            raise ValueError('Interface cold reopen changed its diagnostics or preview pixels')
        if digest(source) != source_hash:
            raise ValueError('Interface import changed its source bytes')
        inspection.mkdir()
        for preview in observed['previews']:
            (inspection / preview['file']).write_bytes((scratch / 'warm' / preview['file']).read_bytes())
        report = {'mapping': mapping, 'native_document': saved['document'], 'assets': saved['assets'],
                  'observation': observed, 'source_sha256': source_hash, 'native_sha256': digest(pending),
                  'native_state_equal': True, 'cold_reopen_equal': True, 'source_bytes_unchanged': True,
                  'publication_approved': False}
        (inspection / 'inspection.json').write_text(json.dumps(report, sort_keys=True) + '\n')
    return report
