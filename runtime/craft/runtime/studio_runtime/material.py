"""Durable source-backed Material authoring, import, inspection and precise edits.

Only fixed snapshot, bounded evaluation, map and CPU preview routes run here. Every portable revision retains the initial input bytes.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from . import material_container as container, material_document as document
from . import material_source as source, material_revision as revision, material_compute as compute, material_maps as maps, material_preview as preview, material_recipes as recipes, material_bundle as bundle, video
from .material_container import require

VERSION = document.VERSION
OPERATIONS = ('material.create', 'material.import', 'material.inspect', 'material.edit', 'material.cook', 'material.export', 'material.preview', 'material.bundle')
MAX_REQUEST_BYTES = 8 << 20


def engine(): return 'dobe-material'


def digest(data): return hashlib.sha256(data).hexdigest()


def sha(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None, 'expected digest must be lowercase SHA-256')


def asset(value):
    require(type(value) is str and video.ASSET.fullmatch(value) is not None, 'input requires an imported asset identifier')


def member(name, *, sbs):
    require(type(name) is str and not name.endswith('/') and name.lower().endswith('.sbs')==sbs, 'source or binary member name is invalid')
    container._name(zipfile.ZipInfo(name))


def structural(operations):
    require(type(operations) is list and 1<=len(operations)<=source.MAX_OPERATIONS, 'structural edit needs 1 to 128 operations')
    for operation in operations:
        require(type(operation) is dict and type(operation.get('kind')) is str, 'structural operation is malformed')
        kind=operation['kind']
        if kind in ('asset.add','asset.replace','asset.remove'):
            fields={'kind','member'} | ({'asset'} if kind!='asset.remove' else set()) | ({'expected_sha256'} if kind!='asset.add' else set())
            require(set(operation)==fields, 'asset operation has unexpected fields');member(operation['member'],sbs=False)
            if kind!='asset.remove':asset(operation['asset'])
            if kind!='asset.add':sha(operation['expected_sha256'])
        else:
            fields={'kind','package','element','expected_sha256'} | ({'value'} if kind!='remove' else set()) | ({'before'} if kind=='insert' else set())
            require(kind in ('replace','remove','insert') and set(operation)==fields, 'element operation has unexpected fields')
            member(operation['package'],sbs=True);sha(operation['expected_sha256'])
            require(type(operation['element']) is int and 0<=operation['element']<container.MAX_XML_NODES, 'element index is invalid')
            if kind=='insert':require(operation['before'] is None or type(operation['before']) is int and 0<=operation['before']<container.MAX_XML_NODES, 'insertion anchor is invalid')
            if kind!='remove':source.encode(operation['value'])


def validate(operation, params, source_revision):
    require(operation in OPERATIONS and type(params) is dict, 'unsupported operation or parameters')
    new=operation in ('material.create','material.import')
    require(source_revision is None if new else bool(source_revision), 'creation/import needs a new project; inspection/edit needs a source revision')
    try:encoded=json.dumps(params,allow_nan=False).encode('utf-8')
    except (TypeError,ValueError,RecursionError,UnicodeError) as error:raise ValueError('Material parameters must be finite bounded JSON') from error
    require(len(encoded)<=MAX_REQUEST_BYTES, 'parameters exceed their byte budget; import a source asset for larger documents')
    if operation=='material.create' and 'recipe' in params:
        recipes.normalize(params)
    elif operation=='material.create':
        require(set(params)<= {'documents','assets'} and type(params.get('documents')) is dict and params['documents'], 'creation needs named source trees')
        require(type(params.get('assets',{})) is dict and len(params['documents'])+len(params.get('assets',{}))<=4096, 'creation asset inventory is invalid')
        for name,tree in params['documents'].items():member(name,sbs=True);source.encode(tree)
        for name,identity in params.get('assets',{}).items():member(name,sbs=False);asset(identity)
    elif operation=='material.import':
        require({'asset'}<=set(params)<={'asset','format'} and params.get('format','source') in ('source','mcmat'), 'import needs an asset and optional source/mcmat format');asset(params['asset'])
    elif operation=='material.inspect':require(not params, 'inspection has no additional parameters')
    elif operation=='material.cook':compute.validate(params)
    elif operation=='material.export':maps.validate(params)
    elif operation=='material.preview':preview.validate(params)
    elif operation=='material.bundle':bundle.validate(params)
    else:
        require(set(params) in ({'expected_sha256','edits'},{'expected_sha256','operations'}), 'edit requires a digest and exactly one typed edit list')
        sha(params['expected_sha256'])
        if 'edits' in params:revision.validate(params['edits'])
        else:structural(params['operations'])


def assets(operation, params):
    identities=[]
    if operation=='material.import':identities=[params['asset']]
    elif operation=='material.create':identities=list(params.get('assets',{}).values())
    elif operation=='material.edit':identities=[item['asset'] for item in params.get('operations',[]) if 'asset' in item]
    # Input copies are private staging. Portable native archives own every
    # referenced resource byte, so revisions never replay these transient paths.
    return {identity:'inputs/material-'+identity for identity in identities}


def execute(root, operation, params, *, executable=None):
    new=operation in ('material.create','material.import');validate(operation,params,None if new else 'source')
    root=Path(root).resolve(strict=True);native=document.owned(root,root/'native');current=document.owned(root,native/'document.mcraft')
    original_path=document.owned(root,native/'original.input');origin_path=document.owned(root,native/'origin.json')
    require(not new or not any(path.exists() for path in (current,original_path,origin_path)), 'creation/import cannot replace an existing project')
    executable=executable if executable is not None else shutil.which(engine());require(executable is not None, 'maintained Dobe Material engine is not installed')
    def input_bytes(identity):return container.read_bytes(document.owned(root,root/assets(operation,params)[identity]))
    previous=None
    if not new:
        previous=container.read_bytes(current);original=container.read_bytes(original_path)
        origin=document.snapshot_json(container.read_bytes(origin_path))
        require(type(origin) is dict and set(origin)=={'schema_version','source_sha256','source_format','operation'}
                and type(origin['schema_version']) is int and origin['schema_version']==1 and origin['source_sha256']==digest(original)
                and origin['source_format'] in ('sbs','mcraft','mcmat') and origin['operation'] in ('material.create','material.import'), 'initial source lineage is invalid')
        if origin['source_format']=='mcmat':
            bundle.inspect_bytes(original);original_format='mcmat'
        else:original_format=container.inspect_bytes(original)['format']
        require(original_format==origin['source_format'], 'initial source format disagrees with its lineage')
    with tempfile.TemporaryDirectory(prefix='.material-attempt-',dir=root) as temporary:
        scratch=Path(temporary);prepared=scratch/'prepared';change=None;cooked=None;exported=None;rendered=None;production=None;bundled=None;imported_bundle=None
        if operation=='material.create':
            documents=params.get('documents')
            if 'recipe' in params:documents,production=recipes.compile_recipe(params)
            original,change=source.create(documents,{name:input_bytes(identity) for name,identity in params.get('assets',{}).items()})
            change=source.prepare(root,original,prepared,executable,change)
        elif operation=='material.import':
            original=input_bytes(params['asset']);stage=scratch/'import.input';data=original
            if params.get('format')=='mcmat':
                admitted=bundle.verify(root,original,executable);data=admitted['members']['source.mcraft']
                imported_bundle={'sha256':admitted['sha256'],'source_sha256':admitted['source_sha256'],'manifest':admitted['manifest'],'native_calls':admitted['native_calls'],'bounded_cook_verified':True}
            stage.write_bytes(data);document.prepare(root,stage,prepared,executable)
        elif operation in ('material.inspect','material.cook','material.export','material.preview','material.bundle'):
            document.prepare(root,current,prepared,executable)
            if operation=='material.cook':
                cooked=compute.cook(root,prepared/'native/document.mcraft',params['graph'],executable)
                (prepared/'exports/cook.json').write_text(json.dumps(cooked,sort_keys=True,allow_nan=False)+'\n')
            elif operation=='material.export':
                exported=maps.export(root,prepared/'native/document.mcraft',prepared/'exports/maps',params,executable)
                (prepared/'exports/maps.json').write_text(json.dumps(exported,sort_keys=True,allow_nan=False)+'\n')
            elif operation=='material.bundle':
                bundled=bundle.export(root,prepared/'native/document.mcraft',prepared/'exports/material.mcmat',params,executable)
                (prepared/'exports/material.json').write_text(json.dumps(bundled,sort_keys=True,allow_nan=False)+'\n')
            elif operation=='material.preview':
                rendered=preview.render(root,prepared/'native/document.mcraft',prepared/'exports/preview',params,executable)
                (prepared/'exports/preview.json').write_text(json.dumps(rendered,sort_keys=True,allow_nan=False)+'\n')
        elif 'edits' in params:
            change=revision.prepare(root,current,prepared,executable,params['expected_sha256'],params['edits'])
        else:
            operations=copy.deepcopy(params['operations'])
            for item in operations:
                if 'asset' in item:item['data']=input_bytes(item.pop('asset'))
            data,change=source.revise(previous,params['expected_sha256'],operations)
            change=source.prepare(root,data,prepared,executable,change,source=current)
        report=json.loads((prepared/'exports/inspection.json').read_text())
        if new:
            origin={'schema_version':1,'source_sha256':digest(original),'source_format':'mcmat' if imported_bundle is not None else report['source_format'],'operation':operation}
        else:
            require(container.read_bytes(original_path)==original and container.read_bytes(current)==previous, 'original or current source changed during the attempt')
        (prepared/'native/original.input').write_bytes(original)
        (prepared/'native/origin.json').write_text(json.dumps(origin,sort_keys=True)+'\n')
        report.update(operation=operation,initial_source_sha256=origin['source_sha256'],previous_document_sha256=digest(previous) if previous is not None else None,
                      initial_source_preserved=True,source_backed=True,render_qualified=False)
        if change is not None:report['change']=change
        if imported_bundle is not None:
            report['imported_bundle']=imported_bundle;report['cook_performed']=True;report['native_calls']+=imported_bundle['native_calls']
        if production is not None:
            production['source_sha256']=digest(original);report['production_recipe']=production
        if cooked is not None:
            report['cook']=cooked;report['cook_performed']=True;report['native_calls']+=cooked['native_calls']
        if exported is not None:
            report['maps']=exported;report['cook_performed']=True;report['map_export_performed']=True;report['native_calls']+=exported['native_calls']
        if bundled is not None:
            report['bundle']=bundled;report['cook_performed']=True;report['bundle_export_performed']=True;report['native_calls']+=bundled['native_calls']
        if rendered is not None:
            report['preview']=rendered;report['cook_performed']=True;report['preview_performed']=True;report['render_qualified']=True;report['native_calls']+=rendered['native_calls']
        (prepared/'exports/inspection.json').write_text(json.dumps(report,sort_keys=True,allow_nan=False)+'\n')
        recipe_dir=prepared/'recipes';recipe_dir.mkdir()
        if production is not None:(recipe_dir/'material-production.json').write_text(json.dumps(production,sort_keys=True)+'\n')
        elif not new:
            retained_recipe=document.owned(root,root/'recipes/material-production.json')
            if retained_recipe.exists():shutil.copyfile(retained_recipe,recipe_dir/'material-production.json')
        request=json.dumps({'operation':operation,'parameters':params},sort_keys=True,allow_nan=False)+'\n'
        (recipe_dir/'last-material-operation.json').write_text(request)
        if new:(recipe_dir/'origin-material-operation.json').write_text(request)
        else:
            origin_recipe=document.owned(root,root/'recipes/origin-material-operation.json')
            shutil.copyfile(origin_recipe,recipe_dir/origin_recipe.name)
        artifacts=[]
        # Copies happen only inside a disposable attempt. The supervisor checks
        # cancellation/lease ownership and publishes one atomic revision later.
        for path in sorted(prepared.rglob('*')):
            if not path.is_file():continue
            relative=path.relative_to(prepared);target=document.owned(root,root/relative);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
            role='native' if relative.parts[0]=='native' else 'recipe' if relative.parts[0]=='recipes' else 'export'
            artifacts.append({'path':relative.as_posix(),'role':role})
    return {'engine':{'name':'materialcraft','version':VERSION,'build':'dobe-material '+VERSION+' ('+document.REVISION+')'},
            'artifacts':artifacts,'validation':{'passed':True,'native_model_equal':True,'native_cold_reopen':True,
                'initial_source_preserved':True,'source_members_equal':report['source_members_equal'],'source_backed':True,
                'requested_state_verified':change is not None,'cook_performed':cooked is not None or exported is not None or rendered is not None or bundled is not None or imported_bundle is not None,'bundle_export_performed':bundled is not None,'bundle_import_verified':imported_bundle is not None,'map_export_performed':exported is not None,'render_qualified':rendered is not None,'preview_performed':rendered is not None,
                'engine_admission_complete':False,'visual_approval':False,'finite_outputs':True if cooked is not None or exported is not None or rendered is not None or bundled is not None or imported_bundle is not None else None,
                'qualification':'exact source and verified portable material import' if imported_bundle is not None else 'exact source and bounded portable material bundle' if bundled is not None else 'source preservation and bounded CPU preview' if rendered is not None else 'source preservation and bounded decoded map export' if exported is not None else 'source preservation and bounded native graph evaluation' if cooked is not None else 'source authoring and cold native state'}}
