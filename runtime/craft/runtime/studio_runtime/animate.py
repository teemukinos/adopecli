"""Typed native Animate creation, import, inspection and precise revisions.

Operations do not execute stored scripts or saved publish templates.
"""
import json
from pathlib import Path
import shutil
import tempfile
import time

from . import animate_document as document, animate_project as project, animate_scene as scene
from . import animate_revision as revision, photo, video
from . import animate_exports as native_exports
from .animate_format import number
from .animate_process import run

VERSION = '0.2.1'
OPERATIONS = ('animate.create', 'animate.import', 'animate.inspect', 'animate.edit', 'animate.export')


def engine():
    return 'dobe-animate'


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported Animate operation or parameters')
    new = operation in ('animate.create', 'animate.import')
    if new and source_revision is not None or not new and not source_revision:
        raise ValueError('Animate creation/import requires a new project; inspection/edit/export requires a source revision')
    options = {'frames', 'scale', 'soundtrack', 'inspect_text'}
    allowed = options | ({'stage', 'scenes'} if operation == 'animate.create' else {'asset'} if new
                         else {'edits'} if operation == 'animate.edit' else {'output'} if operation == 'animate.export' else set())
    if params.keys() - allowed:
        raise ValueError('Animate parameters contain unsupported fields')
    if operation == 'animate.export':
        native_exports.validate(params.get('output'))
    if operation == 'animate.edit':
        revision.validate(params.get('edits'))
        if any(edit['action'] == 'replace_text' for edit in params['edits']) and params.get('inspect_text', True) is not True:
            raise ValueError('Animate text revision requires native text qualification')
    if operation == 'animate.create':
        seed, _, _ = scene.plan({key: value for key, value in params.items() if key not in options})
        profile = document.inspect_bytes(json.dumps(seed).encode())
        selected, _, _ = project.preview_request(profile, params.get('frames'), params.get('scale', 1))
        project.diagnostics.request(profile, selected, params.get('soundtrack'))
        if params.get('inspect_text', True) is not True:
            raise ValueError('Animate creation requires native text qualification')
    if operation == 'animate.import' and (not isinstance(params.get('asset'), str) or not video.ASSET.fullmatch(params['asset'])):
        raise ValueError('Animate import requires an imported asset identifier')
    frames = params.get('frames')
    if 'frames' in params and (not isinstance(frames, list) or len(frames) > project.MAX_PREVIEWS
            or any(type(frame) is not int or not 0 <= frame < 1_000_000 for frame in frames)
            or len(set(frames)) != len(frames)):
        raise ValueError('Animate previews require at most 64 distinct movie frames')
    if not number(params.get('scale', 1), .001, 8):
        raise ValueError('Animate preview scale must be between 0.001 and 8')
    if type(params.get('inspect_text', True)) is not bool:
        raise ValueError('Animate text inspection option must be boolean')
    if 'soundtrack' in params:
        sound = params['soundtrack']
        if not isinstance(sound, dict) or sound.keys() - {'from', 'to', 'rate'}:
            raise ValueError('Animate soundtrack requires a bounded frame range and sample rate')
        if any(type(sound[key]) is not int or not 0 <= sound[key] < 1_000_000 for key in ('from', 'to') if key in sound):
            raise ValueError('Animate soundtrack frames must be bounded integers')
        if 'to' in sound and sound['to'] < sound.get('from', 0):
            raise ValueError('Animate soundtrack range is reversed')
        if type(sound.get('rate', 44100)) is not int or not 8000 <= sound.get('rate', 44100) <= 192000:
            raise ValueError('Animate soundtrack rate must be between 8000 and 192000')


def assets(operation, params):
    return {params['asset']: 'assets/' + params['asset'] + '.anicraft'} if operation == 'animate.import' else {}


def execute(root, operation, params, *, executable=None):
    new = operation in ('animate.create', 'animate.import')
    validate(operation, params, None if new else 'source')
    root = Path(root).resolve(strict=True)
    native = project.owned_path(root, root / 'native')
    exports = project.owned_path(root, root / 'exports')
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    path = project.owned_path(root, native / 'document.anicraft')
    if new and path.exists():
        raise ValueError('Animate creation/import cannot replace an existing project')
    executable = executable if executable is not None else shutil.which(engine())
    if executable is None:
        raise ValueError('Dobe Animate engine is unavailable')
    source = root / next(iter(assets(operation, params).values())) if operation == 'animate.import' else path
    with tempfile.TemporaryDirectory(prefix='.animate-attempt-', dir=root) as folder:
        scratch = Path(folder)
        identity = run([executable, '--version'], scratch, deadline=time.monotonic() + 10)
        if identity.strip() != ('dobe-animate ' + VERSION).encode():
            raise ValueError('Animate requires the maintained native engine version')
        creation = revision_report = None
        if operation == 'animate.create':
            source, creation = scene.create(scratch / 'authoring', {key: params[key] for key in ('stage', 'scenes')}, executable)
        options = {key: value for key, value in params.items() if key not in ('asset', 'stage', 'scenes', 'edits', 'output')}
        if operation == 'animate.edit':
            source, revision_report = revision.apply(scratch / 'revision', path, params['edits'], executable)
            before = project.prepare(root, path, scratch / 'before', executable, **options)
        prepared = scratch / 'prepared'
        report = project.prepare(root, source, prepared, executable, **options)
        export_report = None
        if operation == 'animate.export':
            output, export_report = native_exports.prepare(scratch / 'export', prepared / 'native/document.anicraft', params['output'], executable)
            if export_report['source_sha256'] != report['native_sha256']:
                raise ValueError('Animate export does not match the prepared native source')
            shutil.copytree(output, prepared / 'exports/render')
            report['export'] = export_report
        if creation is not None:
            report['creation'] = creation
        if revision_report is not None:
            if (before['source']['source_sha256'] != revision_report['source_sha256']
                    or report['source']['native_semantics']['semantic_sha256'] != revision_report['semantic_sha256']):
                raise ValueError('Animate revision observations disagree with the checked source state')
            revision_report['previews'] = revision.compare_previews(before, report, revision_report)
            revision_report['text_targets_verified'] = revision.verify_text(report, params['edits'])
            report['revision'] = revision_report
        if creation is not None or revision_report is not None or export_report is not None:
            (prepared / 'exports/inspection.json').write_text(json.dumps(report, sort_keys=True) + '\n')
        # Only attempt-owned files change here. The worker fences publication of
        # all listed artifacts together; a failed attempt cannot change a revision.
        files = [('native/document.anicraft', 'native'), ('native/source.anicraft', 'native'),
                 ('native/objects.json', 'native'), ('exports/inspection.json', 'export')]
        files += [('exports/' + preview['file'], 'preview') for preview in report['previews']]
        if export_report is not None:
            files += [('exports/render/' + artifact['file'], 'export') for artifact in export_report['artifacts']]
        for name, _ in files:
            target = project.owned_path(root, root / name)
            if name == 'native/source.anicraft' and not new and target.exists():
                continue  # Retain the original imported bytes across inspections.
            preserved = scratch / 'before' / name if name == 'native/source.anicraft' and operation == 'animate.edit' else prepared / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(preserved, target)
        recipe = project.owned_path(root, root / 'recipes/create.json')
        if creation is not None:
            recipe.parent.mkdir(exist_ok=True)
            recipe.write_text(json.dumps(params, sort_keys=True) + '\n')
        if recipe.exists():
            files.append(('recipes/create.json', 'recipe'))
        edit_recipe = project.owned_path(root, root / 'recipes/last-edit.json')
        if revision_report is not None:
            edit_recipe.parent.mkdir(exist_ok=True)
            edit_recipe.write_text(json.dumps(params, sort_keys=True) + '\n')
        if edit_recipe.exists():
            files.append(('recipes/last-edit.json', 'recipe'))
        export_recipe = project.owned_path(root, root / 'recipes/last-export.json')
        if export_report is not None:
            export_recipe.parent.mkdir(exist_ok=True)
            export_recipe.write_text(json.dumps(params, sort_keys=True) + '\n')
        if export_recipe.exists():
            files.append(('recipes/last-export.json', 'recipe'))
    return {'engine': {'name': 'anicraft', 'version': VERSION, 'build': 'dobe-animate ' + VERSION},
            'artifacts': [{'path': name, 'role': role} for name, role in files] + photo.retained_assets(root),
            'validation': {'passed': True, 'native_state_equal': True, 'native_cold_reopen': True,
                           'source_bytes_unchanged': True, 'selected_preview_pixels_equal': True,
                           'preview_count': len(report['previews']), 'native_text': report['source']['native_text'],
                           'requested_state_verified': creation is not None or revision_report is not None,
                           'unrequested_native_fields_verified': revision_report is not None,
                           'native_export_verified': export_report is not None,
                           'interactive_playback_verified': False, 'visual_approval': False,
                           'qualification': 'native preservation and selected static previews; no visual approval'}}
