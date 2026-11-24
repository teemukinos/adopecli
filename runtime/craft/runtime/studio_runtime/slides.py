"""Durable Slides creation, owned imports and precise editable revisions.

Every native execution passes the complete editable-raster-slides-v2 profile.
PNG/PDF delivery adds stricter text coverage and independent output checks.
Broader resources/imports and PPTX delivery remain separate required work.
The existing supervisor owns cancellation, fencing and atomic publication.
"""
import json
from pathlib import Path
import re
import shutil
import tempfile

from . import slides_binding as binding, slides_source as source, slides_project as project, slides_revision as revision
from . import slides_engine, slides_recipes as recipes, slides_admission as admission, slides_exports, slides_precision, video
from .slides_source import require
from .write_container import read_bytes
from .write_engine import owned

VERSION = binding.VERSION
OPERATIONS = ('slides.create','slides.import','slides.inspect','slides.edit','slides.bundle','slides.export','slides.migrate')
MAX_REQUEST_BYTES = 8 << 20


def encoded(value):
    try:data=revision.encoded(value)
    except (ValueError,TypeError,RecursionError,UnicodeError) as error:raise ValueError('Slides parameters must be finite JSON') from error
    require(len(data)<=MAX_REQUEST_BYTES,'parameters exceed byte budget; import an owned asset for larger models')
    source.strict_json(data);return data


def validate(operation,params,source_revision):
    require(operation in OPERATIONS and type(params) is dict,'unsupported operation or parameters')
    new=operation in ('slides.create','slides.import') or operation=='slides.migrate' and 'asset' in params
    require(source_revision is None if new else bool(source_revision),'creation/import and asset migration need a new project; other operations need a source revision')
    encoded(params)
    if operation=='slides.create':
        if 'recipe' in params:recipes.normalize(params)
        else:
            require(set(params)=={'document'},'creation requires a complete admitted native model or versioned recipe')
            admission.inspect(encoded(params['document']))
    elif operation=='slides.import':
        require(set(params)=={'asset','format'} and params['format'] in ('json','deckcraft','dobeslides'),'import requires an asset and explicit json/deckcraft/dobeslides format')
        require(type(params['asset']) is str and video.ASSET.fullmatch(params['asset']) is not None,'import requires a project-scoped asset identifier')
    elif operation=='slides.edit':
        require(set(params)=={'expected_sha256','edits'} and type(params['expected_sha256']) is str
                and re.fullmatch('[0-9a-f]{64}',params['expected_sha256']) is not None,'edit requires exact portable hash and typed changes')
        edits=params['edits'];require(type(edits) is list and 1<=len(edits)<=project.MAX_EDITS,'edit needs 1 to 128 changes')
        require(all(type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in revision.KINDS for edit in edits),'edit kind unsupported')
        for image in picture_inputs(edits):
            if 'asset' in image:
                require(set(image)=={'asset','sha256','name','contentType'} and type(image['asset']) is str
                        and video.ASSET.fullmatch(image['asset']) is not None and type(image['sha256']) is str
                        and re.fullmatch('[0-9a-f]{64}',image['sha256']) is not None, 'picture requires a scoped asset and exact input hash')
    elif operation=='slides.migrate':
        require(set(params)==({'asset','expected_sha256'} if new else {'expected_sha256'})
                and type(params['expected_sha256']) is str and re.fullmatch('[0-9a-f]{64}',params['expected_sha256']) is not None,
                'migration requires exact predecessor hash and an optional owned asset for a new project')
        if new:require(type(params['asset']) is str and video.ASSET.fullmatch(params['asset']) is not None,'migration needs a project-scoped asset')
    elif operation=='slides.export':slides_exports.validate(params)
    else:require(not params,'inspection and portable delivery take no parameters')


def picture_inputs(edits):
    for edit in edits:
        if edit['kind'] not in ('picture.insert','picture.replace'):continue
        image=edit.get('value')
        if edit['kind']=='picture.insert':
            require(type(image) is dict and set(image)=={'image','transform'},'picture insertion fields differ')
            image=image['image']
        require(type(image) is dict,'picture input must be an object')
        yield image


def assets(operation,params):
    if operation in ('slides.import','slides.migrate') and 'asset' in params:return {params['asset']:'inputs/slides-'+params['asset']}
    if operation=='slides.edit':return {image['asset']:'inputs/slides-picture-'+image['asset'] for image in picture_inputs(params['edits']) if 'asset' in image}
    return {}


def resolved_edits(root,params):
    edits=source.strict_json(encoded(params['edits']))
    for image in picture_inputs(edits):
        if 'asset' not in image:continue
        data=read_bytes(owned(root,root/('inputs/slides-picture-'+image['asset'])))
        require(0<len(data)<=16<<20,'picture asset exceeds encoded byte budget')
        require(source.sha(data)==image['sha256'],'picture asset differs from expected bytes')
        image.pop('asset');image.pop('sha256');image['dataHex']=data.hex()
    return edits


def execute(root,operation,params):
    new=operation in ('slides.create','slides.import') or operation=='slides.migrate' and 'asset' in params;validate(operation,params,None if new else 'source')
    root=Path(root).resolve(strict=True);current=owned(root,root/'native/project.dobeslides');origin=owned(root,root/'recipes/origin-slides-operation.json')
    require(not new or not (root/'native').exists(),'creation/import cannot replace existing native files')
    trusted=binding.resolve();previous=None if new else read_bytes(current);retained_origin=None if new else read_bytes(origin)
    if previous is not None:
        prior=project.inspect_bytes(previous)
        if operation!='slides.migrate':project.require_engine(prior,trusted['expected_pin'])
        for name in (name for name in prior['members'] if name!='project.json'):
            require(read_bytes(owned(root,root/'native'/name))==prior['members'][name],'published original/model differs from portable source')
    with tempfile.TemporaryDirectory(prefix='.slides-attempt-',dir=root) as temporary:
        scratch=Path(temporary);production=None
        if operation=='slides.create':
            if 'recipe' in params:
                compiled=recipes.compile_recipe(params);model=compiled['data']
                production={key:compiled[key] for key in ('request','selectors','text_boxes','provenance','slide_count','pending_qualification')}
            else:model=encoded(params['document'])
            data=project.create(model,'json',engine=trusted['expected_pin'])
        elif operation=='slides.import':
            imported=read_bytes(owned(root,root/assets(operation,params)[params['asset']]))
            data=imported if params['format']=='dobeslides' else project.create(imported,params['format'],engine=trusted['expected_pin'])
        elif operation=='slides.migrate':
            predecessor=previous if previous is not None else read_bytes(owned(root,root/assets(operation,params)[params['asset']]))
            data=project.migrate(predecessor,params['expected_sha256'],engine=trusted['expected_pin'])
        elif operation=='slides.edit':data=project.revise(previous,params['expected_sha256'],resolved_edits(root,params))
        else:data=previous
        checked=project.inspect_bytes(data);project.require_engine(checked,trusted['expected_pin'])
        # This must precede even the native version probe. Inspection-only source
        # ownership and portable edit replay do not grant execution permission.
        admitted=admission.inspect_project(checked)
        native=slides_engine.Engine(root=scratch,**trusted);report=native.verify_project(data,scratch/'observed')
        report.update(operation=operation,previous_project_sha256=source.sha(previous) if previous is not None else None,
            source_format=checked['manifest']['source_format'],source_backed=True,migration=checked['migration'],requested_state_verified=operation in ('slides.create','slides.edit'),
            admission=admitted,render_qualified=False,pptx_precision=slides_precision.inspect(checked['members']['document.json']))
        if previous is not None:
            require(read_bytes(current)==previous and read_bytes(origin)==retained_origin,'owned project or origin changed during observation')
            require(checked['source_sha256']==prior['source_sha256'],'revision replaced immutable original')
        prepared=scratch/'prepared'
        for directory in ('native','exports','recipes'):(prepared/directory).mkdir(parents=True)
        (prepared/'native/project.dobeslides').write_bytes(data)
        for name,value in checked['members'].items():
            if name!='project.json':(prepared/'native'/name).write_bytes(value)
        if operation=='slides.export':
            report['delivery']=slides_exports.deliver(native,scratch/'observed/document.json',checked['members']['document.json'],prepared/'exports/delivery',params)
            report['native_calls']=native.calls;report['render_qualified']=True
            report['pending_qualification']=report['delivery']['pending_qualification']
        (prepared/'exports/inspection.json').write_text(json.dumps(report,sort_keys=True,allow_nan=False)+'\n')
        (prepared/'exports/structure.json').write_text(json.dumps(admitted['current'],sort_keys=True,allow_nan=False)+'\n')
        if operation=='slides.bundle':(prepared/'exports/presentation.dobeslides').write_bytes(data)
        request=encoded({'operation':operation,'parameters':params})
        (prepared/'recipes/last-slides-operation.json').write_bytes(request)
        (prepared/'recipes/origin-slides-operation.json').write_bytes(request if new else retained_origin)
        if production is not None:
            production['source_model_sha256']=checked['current_sha256']
            (prepared/'recipes/slides-production.json').write_text(json.dumps(production,sort_keys=True,allow_nan=False)+'\n')
        elif not new:
            retained=owned(root,root/'recipes/slides-production.json')
            if retained.exists():(prepared/'recipes/slides-production.json').write_bytes(read_bytes(retained))
        artifacts=[]
        for path in sorted(prepared.rglob('*')):
            if not path.is_file():continue
            relative=path.relative_to(prepared);target=owned(root,root/relative);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target);require(read_bytes(target)==path.read_bytes(),'staged artifact differs from verified output')
            artifacts.append({'path':relative.as_posix(),'role':'native' if relative.parts[0]=='native' else 'recipe' if relative.parts[0]=='recipes' else 'export'})
    return {'engine':{'name':'deckcraft','version':VERSION,'build':binding.VERSION_RESPONSE},'artifacts':artifacts,
        'validation':{'passed':True,'native_model_equal':True,'native_cold_reopen':True,'initial_source_preserved':True,'source_backed':True,
            'requested_state_verified':report['requested_state_verified'],'engine_migration_verified':operation=='slides.migrate','admission_profile':admission.PROFILE,'profile_admission_complete':True,
            'general_admission_complete':False,'source_format_fidelity_qualified':False,'render_qualified':report['render_qualified'],'visual_approval':False,
            'pending_qualification':report['pending_qualification'] if report['render_qualified'] else admitted['current']['pending_qualification'],
            'qualification':'complete editable-raster-slides-v2 admission, native preservation and exact portable originals'}}
