"""Typed Interface authoring/import/inspection through durable runtime attempts.

Native preservation is qualified separately from design approval. Inspection
reports never turn successful shaping or cold rendering into clipping approval.
"""
import json
from pathlib import Path
import shutil
import tempfile

from . import audio, interface_document as document, interface_project as project, interface_revision as revision, interface_scene as scene, photo, video
from .interface_engine import Engine, VERSION

OPERATIONS = ('interface.create', 'interface.import', 'interface.inspect', 'interface.edit')


def engine():
    return 'dobe-interface'


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported Interface operation or parameters')
    new = operation in ('interface.create', 'interface.import')
    if new and source_revision is not None or not new and not source_revision:
        raise ValueError('Interface creation/import requires a new project; inspection/edit requires a source revision')
    options = {'previews', 'font_fallbacks'}
    if 'previews' in params and (not isinstance(params['previews'], list) or len(params['previews']) > project.MAX_PREVIEWS
                                or any(not video.named(name) for name in params['previews'])
                                or len(set(params['previews'])) != len(params['previews'])):
        raise ValueError('Interface previews require at most 64 unique node names')
    fallbacks = params.get('font_fallbacks', [])
    if (not isinstance(fallbacks, list) or len(fallbacks) > 128
            or any(not isinstance(row, list) or len(row) != 4 or not all(scene.text(v, 128) for v in row) for row in fallbacks)):
        raise ValueError('Interface font fallbacks require requested and actual family/style pairs')
    body = {key: value for key, value in params.items() if key not in options}
    if operation == 'interface.create':
        scene.validate(body)
    elif operation == 'interface.import':
        if set(body) != {'asset'} or not isinstance(body['asset'], str) or not video.ASSET.fullmatch(body['asset']):
            raise ValueError('Interface native import requires an imported asset identifier')
    elif operation == 'interface.edit':
        if set(body) != {'edits'}:
            raise ValueError('Interface revision requires an edits list')
        revision.validate(body['edits'])
    elif body:
        raise ValueError('Interface inspection accepts only preview names and explicit font fallbacks')


def assets(operation, params):
    if operation == 'interface.create':
        return scene.assets(params)
    if operation == 'interface.import':
        return {params['asset']: 'assets/' + params['asset'] + '.figcraft'}
    return {}


def execute(root, operation, params, *, executable=None):
    validate(operation, params, None if operation in ('interface.create', 'interface.import') else 'source')
    root = Path(root); native = root / 'native'; exports = root / 'exports'
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    path = native / 'document.figcraft'; pending = native / '.document-pending.figcraft'
    if operation in ('interface.create', 'interface.import') and path.exists():
        raise ValueError('Interface creation/import cannot replace an existing project')
    inputs = {key: root / name for key, name in assets(operation, params).items()}
    for source in inputs.values():
        source.resolve().relative_to(root.resolve())
        limit = document.MAX_ARCHIVE if operation == 'interface.import' else document.MAX_ASSET
        if source.is_symlink() or not source.is_file() or source.stat().st_size > limit:
            raise ValueError('Interface input requires a bounded regular asset file')
    input_hashes = {key: project.digest(value) for key, value in inputs.items()}
    revision_report = None
    with tempfile.TemporaryDirectory(prefix='.interface-project-', dir=root) as temporary:
        scratch = Path(temporary)
        if operation == 'interface.create':
            source = scratch / 'authored.figcraft'
            body = {key: params[key] for key in ('title', 'nodes')}
            with Engine(root, executable=executable) as process:
                profile, _ = scene.create(process, body, inputs, source)
        elif operation == 'interface.import':
            source = inputs[params['asset']]; profile = document.read_native(source)
        else:
            source = path; profile = document.read_native(path)
            old_mapping = audio.load_json(native / 'objects.json', 1 << 20)
            project.check_mapping(old_mapping, profile)
            if operation == 'interface.edit':
                source_hash = project.digest(path)
                with Engine(root, executable=executable) as process:
                    process.open(path)
                    before = project.observe(process, profile, scratch / 'before')
                    changed, edits = revision.apply(process, profile, old_mapping, params['edits'], scratch)
                    after = project.observe(process, changed, scratch / 'after', allowed_fallbacks=params.get('font_fallbacks', []))
                    touched = {identity for edit in edits for identity in edit['content_targets']}
                    touched.update(change['id'] for edit in edits for change in edit['derived_geometry'])
                    expected_pixels = {row['id']: row for row in before['previews']
                                       if not revision.descendants(profile['nodes'], row['id']) & touched}
                    actual_pixels = {row['id']: row for row in after['previews']}
                    if any(actual_pixels.get(identity) != row for identity, row in expected_pixels.items()):
                        raise ValueError('Interface revision changed an untargeted root preview')
                    source = scratch / 'revised.figcraft'
                    profile = process.save(source, title=changed['document']['name'])
                    document.require_state(profile, changed['document'], changed['assets'])
                if project.digest(path) != source_hash:
                    raise ValueError('Interface revision changed its source file')
                revision_report = {'edits': edits, 'untargeted_root_ids': sorted(expected_pixels),
                                   'untargeted_root_pixels_verified': True, 'source_sha256': source_hash}
        mapping = project.mapping_for(profile)
        roots = None
        if 'previews' in params:
            if any(name not in mapping for name in params['previews']):
                raise ValueError('Interface preview names must exist in the native node mapping')
            roots = [mapping[name]['id'] for name in params['previews']]
        report = project.import_native(root, source, pending, scratch / 'inspection', roots=roots,
                                       allowed_fallbacks=params.get('font_fallbacks', []), executable=executable)
        if operation in ('interface.create', 'interface.edit') and not report['observation']['shaping_verified']:
            issues = sorted({issue for row in report['observation']['text'] for issue in row['issues']})
            raise ValueError('Interface production failed text qualification: ' + '; '.join(issues))
        if any(project.digest(inputs[key]) != value for key, value in input_hashes.items()):
            raise ValueError('Interface production changed an input asset')
        previews = report['observation']['previews']
        for item in previews:
            shutil.copyfile(scratch / 'inspection' / item['file'], exports / item['file'])
        if revision_report is not None:
            report['revision'] = revision_report
        (exports / 'inspection.json').write_text(json.dumps(report, sort_keys=True) + '\n')
        (native / 'objects.json').write_text(json.dumps(report['mapping'], sort_keys=True) + '\n')
        pending.replace(path)
    files = [('native/document.figcraft', 'native'), ('native/objects.json', 'native'), ('exports/inspection.json', 'export')]
    files += [('exports/' + item['file'], 'preview') for item in previews]
    observed = report['observation']
    return {'engine': {'name': 'figcraft', 'version': VERSION, 'build': 'dobe-interface ' + VERSION},
            'artifacts': [{'path': name, 'role': role} for name, role in files] + photo.retained_assets(root),
            'validation': {'passed': True, 'native_state_equal': True, 'native_cold_reopen': True,
                           'pixel_roundtrip_equal': True, 'source_bytes_unchanged': True,
                           'node_count': len(report['mapping']), 'preview_count': len(previews),
                           'shaping_verified': observed['shaping_verified'], 'clipping_verified': False,
                           'unrequested_native_fields_verified': revision_report is not None,
                           'untargeted_root_pixels_verified': revision_report is not None,
                           'visual_approval': False,
                           'qualification': 'native preservation and inspection; visual approval remains separate'}}
