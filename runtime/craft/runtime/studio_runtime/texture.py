"""Typed Texture authoring, native import, inspection, revision and map export.

No arbitrary engine command, stored path replay or linked package cooking route
is exposed through this adapter.
"""
import json
from pathlib import Path
import shutil
import tempfile

from . import photo, video, texture_workflow as workflow, texture_authoring as authoring, texture_document as document
from . import texture_compute as compute, texture_material as material_handoff
from .texture_structure import require

VERSION = workflow.VERSION
OPERATIONS = ('texture.create', 'texture.import', 'texture.inspect', 'texture.edit', 'texture.export', 'texture.render', 'texture.bake', 'texture.material')


def engine():
    return 'dobe-texture'


def validate(operation, params, source_revision):
    require(operation in OPERATIONS and type(params) is dict, 'unsupported Texture operation or parameters')
    new = operation in ('texture.create', 'texture.import')
    require(source_revision is None if new else bool(source_revision),
            'Texture creation/import requires a new project; inspection/edit/export requires a source revision')
    allowed = {'name', 'mesh', 'resolution', 'layers'} if operation == 'texture.create' else {'accept_generated_uvs'}
    if operation == 'texture.import': allowed.add('asset')
    if operation == 'texture.edit': allowed.add('edits')
    if operation == 'texture.render': allowed.add('render')
    if operation == 'texture.bake': allowed.add('bake')
    if operation == 'texture.material': allowed.update({'asset','expected_sha256','texture_set','layer','name','height_mode'})
    require(not params.keys() - allowed,
            'Texture parameters contain unsupported fields')
    require(type(params.get('accept_generated_uvs', False)) is bool, 'Texture generated UV acceptance must be boolean')
    if operation == 'texture.create': authoring.validate_creation(params)
    if operation == 'texture.edit': authoring.validate_edits(params.get('edits'))
    if operation == 'texture.render': compute.validate_render(params.get('render'))
    if operation == 'texture.bake': compute.validate_bake(params.get('bake'))
    if operation == 'texture.material': material_handoff.validate(params)
    if operation in ('texture.import','texture.material'):
        require(type(params.get('asset')) is str and video.ASSET.fullmatch(params['asset']),
                'Texture import requires an imported asset identifier')


def assets(operation, params):
    if operation=='texture.import': return {params['asset']:'assets/'+params['asset']+'.tcraft'}
    if operation=='texture.material': return {params['asset']:'inputs/material-'+params['asset']+'.mcmat'}
    return {}


def execute(root, operation, params, *, executable=None):
    new = operation in ('texture.create', 'texture.import')
    validate(operation, params, None if new else 'source')
    root = Path(root).resolve(strict=True)
    native = workflow.owned(root, root / 'native'); exports = workflow.owned(root, root / 'exports')
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    path = workflow.owned(root, native / 'document.tcraft')
    require(not new or not path.exists(), 'Texture creation/import cannot replace an existing project')
    source = root / next(iter(assets(operation, params).values())) if operation == 'texture.import' else path
    executable = executable if executable is not None else shutil.which(engine())
    require(executable is not None, 'maintained Dobe Texture engine is not installed')
    with tempfile.TemporaryDirectory(prefix='.texture-attempt-', dir=root) as temporary:
        scratch = Path(temporary); prepared = scratch / 'prepared'; authored = revision = before = baked = preview = handoff = None
        if operation == 'texture.create':
            source, authored = authoring.create(scratch/'authoring', params, executable)
        if operation == 'texture.edit':
            original = document.read_native(path)
            # Check selectors and expected values before expensive rendering.
            source, revision = authoring.revise(scratch/'revision', path, params['edits'], executable,
                                               accept_generated_uvs=params.get('accept_generated_uvs', False))
            before = workflow.prepare(root, path, scratch/'before', executable,
                                      accept_generated_uvs=params.get('accept_generated_uvs', False), export_maps=True)
        if operation == 'texture.material':
            material_engine=shutil.which('dobe-material');require(material_engine is not None, 'material handoff requires the maintained Dobe Material engine')
            asset=workflow.owned(root,root/next(iter(assets(operation,params).values())))
            source,handoff=material_handoff.apply(scratch/'material',path,asset,params,executable,material_engine,accept_generated_uvs=params.get('accept_generated_uvs',False))
        if operation == 'texture.bake':
            source, baked = compute.bake(scratch/'baking', path, params['bake'], executable,
                                         accept_generated_uvs=params.get('accept_generated_uvs', False))
            before = workflow.prepare(root, path, scratch/'before', executable,
                                      accept_generated_uvs=params.get('accept_generated_uvs', False))
        report = workflow.prepare(root, source, prepared, executable,
                                  accept_generated_uvs=params.get('accept_generated_uvs', False),
                                  export_maps=operation in ('texture.create', 'texture.edit', 'texture.export', 'texture.bake', 'texture.material'))
        if operation == 'texture.render':
            image, preview = compute.render(scratch/'rendering', prepared/'native/document.tcraft', params['render'], executable,
                                             accept_generated_uvs=params.get('accept_generated_uvs', False))
            shutil.copyfile(image, prepared/'exports/preview.png'); report['preview'] = preview
        if baked is not None:
            require(before['source_sha256'] == baked['source_sha256'], 'bake source disagrees with independent preparation')
            report['bake'] = baked
        if authored is not None: report['creation'] = authored
        if handoff is not None:
            report['material_handoff']=handoff
            data=material_handoff.material_container.read_bytes(asset)
            require(material_handoff.bundle.sha(data)==handoff['bundle_sha256'], 'material bundle changed after verification')
            retained=workflow.owned(root,root/('assets/material-'+handoff['bundle_sha256']+'.mcmat'));retained.parent.mkdir(exist_ok=True)
            if retained.exists():require(retained.read_bytes()==data, 'retained material bundle differs')
            else:
                with retained.open('xb') as stream:stream.write(data)
        if revision is not None:
            require(before['source_sha256'] == revision['source_sha256'], 'revision source disagrees with independent preparation')
            revision['maps'] = authoring.compare_maps(before, report, original, params['edits'])
            report['revision'] = revision
        (prepared/'exports/inspection.json').write_text(json.dumps(report, sort_keys=True)+'\n')
        files = [('native/document.tcraft', 'native'), ('native/source.tcraft', 'native'),
                 ('native/objects.json', 'native'), ('exports/inspection.json', 'export')]
        files += [('exports/maps/' + item['file'], 'export') for item in report['maps']]
        if preview is not None: files.append(('exports/preview.png','preview'))
        for name, _ in files:
            target = workflow.owned(root, root / name)
            if name == 'native/source.tcraft' and not new and target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            preserved = scratch/'before'/name if name == 'native/source.tcraft' and (revision is not None or baked is not None) else prepared/name
            shutil.copyfile(preserved, target)
        recipe = workflow.owned(root, root / 'recipes/last-texture-operation.json')
        recipe.parent.mkdir(exist_ok=True)
        recipe.write_text(json.dumps({'operation': operation, 'parameters': params}, sort_keys=True) + '\n')
        files.append(('recipes/last-texture-operation.json', 'recipe'))
        for name, active in (('create', authored is not None), ('last-edit', revision is not None),
                             ('last-render', preview is not None), ('last-bake', baked is not None), ('last-material', handoff is not None)):
            kept = workflow.owned(root, root/('recipes/'+name+'.json'))
            if active: kept.write_text(json.dumps(params, sort_keys=True)+'\n')
            if kept.exists(): files.append(('recipes/'+name+'.json', 'recipe'))
    return {'engine': {'name': 'texturecraft', 'version': VERSION, 'build': 'dobe-texture ' + VERSION},
            'artifacts': [{'path': name, 'role': role} for name, role in files] + photo.retained_assets(root),
            'validation': {'passed': True, 'native_state_equal': True, 'native_cold_reopen': True,
                           'source_bytes_unchanged': True, 'native_resource_geometry_agreement': True,
                           'export_pixels_equal': report['export_pixels_equal'], 'map_count': len(report['maps']),
                           'requested_state_verified': authored is not None or revision is not None or baked is not None or preview is not None or handoff is not None,
                           'unrequested_native_fields_verified': revision is not None or baked is not None or handoff is not None,
                           'material_handoff_verified':handoff is not None,
                           'cpu_preview_verified': preview is not None, 'cpu_bake_verified': baked is not None,
                           'visual_approval': False, 'qualification': 'native preservation and requested document maps'}}
