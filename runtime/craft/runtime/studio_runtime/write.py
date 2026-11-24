"""Durable Write authoring and typed revisions with exact portable originals.

Only owned native JSON and existing portable projects enter this initial adapter.
Direct DOCX conversion and complete source-format fidelity retain separate gates.
The supervisor owns cancellation, lease fencing and atomic revision publication.
"""
import json
from pathlib import Path
import re
import shutil
import tempfile

from . import video, write_binding as binding, write_container as container
from . import write_engine, write_exports, write_project as project, write_revision as revision, write_recipes as recipes
from .write_container import require

VERSION = binding.VERSION
OPERATIONS = ('write.create', 'write.import', 'write.inspect', 'write.edit', 'write.bundle', 'write.export')
MAX_REQUEST_BYTES = 8 << 20


def encoded(value):
    try: data = (revision.canonical(value)+'\n').encode('ascii')
    except (ValueError, TypeError, RecursionError, UnicodeError) as error: raise ValueError('Write parameters must be finite JSON') from error
    require(len(data) <= MAX_REQUEST_BYTES, 'parameters exceed their byte budget; import an asset for larger documents')
    container.strict_json(data); return data


def validate(operation, params, source_revision):
    require(operation in OPERATIONS and type(params) is dict, 'unsupported operation or parameters')
    new = operation in ('write.create', 'write.import')
    require(source_revision is None if new else bool(source_revision), 'creation/import needs a new project; other operations need a source revision')
    encoded(params)
    if operation == 'write.create':
        if 'recipe' in params: recipes.normalize(params)
        else:
            require(set(params) == {'document'}, 'creation requires a complete native document or versioned recipe')
            project.native_profile(encoded(params['document']))
    elif operation == 'write.import':
        require(set(params) == {'asset', 'format'} and params['format'] in ('json', 'dobewrite'), 'import requires an asset and explicit json/dobewrite format')
        require(type(params['asset']) is str and video.ASSET.fullmatch(params['asset']) is not None, 'import requires a project-scoped asset identifier')
    elif operation == 'write.edit':
        require(set(params) == {'expected_sha256', 'edits'} and type(params['expected_sha256']) is str
                and re.fullmatch('[0-9a-f]{64}', params['expected_sha256']) is not None, 'edit requires the exact portable project hash and typed edits')
        edits = params['edits']
        require(type(edits) is list and 1 <= len(edits) <= project.MAX_EDITS, 'edit needs 1 to 128 typed changes')
        require(all(type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in revision.KINDS for edit in edits), 'edit kind is unsupported')
        # Exact selectors, UTF-8 expectations and property values depend on the
        # owned source model and are checked atomically during project replay.
    elif operation == 'write.export': write_exports.validate(params)
    else: require(not params, 'inspection and portable delivery take no additional parameters')


def assets(operation, params):
    return {params['asset']: 'inputs/write-'+params['asset']} if operation == 'write.import' else {}


def execute(root, operation, params):
    new = operation in ('write.create', 'write.import'); validate(operation, params, None if new else 'source')
    root = Path(root).resolve(strict=True)
    current = write_engine.owned(root, root/'native/project.dobewrite')
    origin_recipe = write_engine.owned(root, root/'recipes/origin-write-operation.json')
    require(not new or not (root/'native').exists(), 'creation/import cannot replace existing native files')
    trusted = binding.resolve()
    previous = None if new else container.read_bytes(current)
    retained_recipe = None if new else container.read_bytes(origin_recipe)
    if previous is not None:
        prior = project.inspect_bytes(previous); project.require_engine(prior, trusted['expected_pin'])
        for name in ('baseline.json', 'document.json', 'original.'+prior['manifest']['source_format']):
            require(container.read_bytes(write_engine.owned(root, root/'native'/name)) == prior['members'][name], 'published model/original differs from portable source')
    with tempfile.TemporaryDirectory(prefix='.write-attempt-', dir=root) as temporary:
        scratch = Path(temporary); production = None
        if operation == 'write.create':
            document, production = recipes.compile_recipe(params) if 'recipe' in params else (params['document'], None)
            data = project.create(encoded(document), 'json', engine=trusted['expected_pin'])
        elif operation == 'write.import':
            imported = container.read_bytes(write_engine.owned(root, root/assets(operation, params)[params['asset']]))
            data = project.create(imported, 'json', engine=trusted['expected_pin']) if params['format'] == 'json' else imported
        elif operation == 'write.edit': data = project.revise(previous, params['expected_sha256'], params['edits'])
        else: data = previous
        checked = project.inspect_bytes(data); project.require_engine(checked, trusted['expected_pin'])
        native = write_engine.Engine(root=scratch, **trusted)
        report = native.verify_project(data, scratch/'observed')
        report.update(operation=operation, previous_project_sha256=project.sha(previous) if previous is not None else None,
                      source_format=checked['manifest']['source_format'], source_backed=True,
                      requested_state_verified=operation in ('write.create', 'write.edit'), render_qualified=False)
        if previous is not None:
            require(container.read_bytes(current) == previous and container.read_bytes(origin_recipe) == retained_recipe, 'owned project or origin recipe changed during observation')
            require(checked['source_sha256'] == prior['source_sha256'], 'revision replaced immutable original')
        prepared = scratch/'prepared'; (prepared/'native').mkdir(parents=True)
        (prepared/'exports').mkdir(); (prepared/'recipes').mkdir()
        (prepared/'native/project.dobewrite').write_bytes(data)
        for name, value in checked['members'].items():
            if name != 'project.json': (prepared/'native'/name).write_bytes(value)
        if operation == 'write.export':
            report['delivery'] = write_exports.deliver(native, scratch/'observed/document.json', checked['members']['document.json'], prepared/'exports/delivery', params)
            report['native_calls'] = native.calls; report['render_qualified'] = True
            report['pending_qualification'] = report['delivery']['pending_qualification']
        (prepared/'exports/inspection.json').write_text(json.dumps(report, sort_keys=True, allow_nan=False)+'\n')
        (prepared/'exports/structure.json').write_text(json.dumps(checked['current']['structure'], sort_keys=True, allow_nan=False)+'\n')
        if operation == 'write.bundle': (prepared/'exports/document.dobewrite').write_bytes(data)
        request = encoded({'operation': operation, 'parameters': params})
        (prepared/'recipes/last-write-operation.json').write_bytes(request)
        (prepared/'recipes/origin-write-operation.json').write_bytes(request if new else retained_recipe)
        if production is not None:
            production['source_model_sha256'] = checked['current_sha256']
            (prepared/'recipes/write-production.json').write_text(json.dumps(production,sort_keys=True,allow_nan=False)+'\n')
        elif not new:
            retained_production = write_engine.owned(root, root/'recipes/write-production.json')
            if retained_production.exists(): shutil.copyfile(retained_production, prepared/'recipes/write-production.json')
        artifacts = []
        # These are disposable attempt files. Only Store.publish under the
        # supervisor's live lease may make the complete revision visible.
        for path in sorted(prepared.rglob('*')):
            if not path.is_file(): continue
            relative = path.relative_to(prepared); target = write_engine.owned(root, root/relative)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
            require(container.read_bytes(target) == path.read_bytes(), 'staged artifact differs from verified output')
            artifacts.append({'path': relative.as_posix(), 'role': 'native' if relative.parts[0] == 'native' else 'recipe' if relative.parts[0] == 'recipes' else 'export'})
    return {'engine': {'name': 'wordcraft', 'version': VERSION, 'build': 'dobe-write '+VERSION+' ('+binding.REVISION+')'},
            'artifacts': artifacts, 'validation': {'passed': True, 'native_model_equal': True, 'native_cold_reopen': True,
                'initial_source_preserved': True, 'source_backed': True, 'requested_state_verified': report['requested_state_verified'],
                'engine_admission_complete': False, 'source_format_fidelity_qualified': False, 'render_qualified': report['render_qualified'],
                'visual_approval': False, 'pending_qualification': report['pending_qualification'],
                'qualification': 'receipt-bound complete native models and exact portable originals'}}
