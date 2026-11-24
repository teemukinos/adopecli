"""Owned CAD production, precise revisions and editable portable deliverables.

The existing durable supervisor owns retries, cancellation, fencing and atomic
publication. This adapter writes only its disposable attempt. Every source and
intermediate model passes admission before the first native process starts.
"""
from pathlib import Path
import re
import shutil
import tempfile

from . import cad_binding as binding, cad_source as source, cad_project as project, cad_revision as revision
from . import cad_admission as admission, cad_engine, cad_parametric as panel, cad_solid as solid, cad_history, video
from .cad_source import require
from .write_container import read_bytes
from .write_engine import owned

VERSION = binding.VERSION
OPERATIONS = tuple('cad.'+name for name in ('create','import','inspect','edit','solve','solid','export','bundle','migrate'))
MAX_REQUEST_BYTES = 8 << 20


def encoded(value):
    try: data = revision.encoded(value)
    except (TypeError,ValueError,RecursionError,UnicodeError) as error: raise ValueError('CAD parameters must be finite JSON') from error
    require(len(data)<=MAX_REQUEST_BYTES, 'parameters exceed byte budget; import an owned asset for larger models')
    source.strict_json(data); return data


def catalog():
    return [{'id':name,'version':1,'units':'mm','required':['width','height']+(['depth'] if name==solid.RECIPE else []),
             'dimension_range_mm':[.1,10000],'editable':True,'shares_user_content':False,'general_manufacturing_qualified':False}
            for name in (panel.RECIPE,solid.RECIPE)]


def validate(operation, params, source_revision):
    require(operation in OPERATIONS and type(params) is dict, 'unsupported operation or parameters')
    new = operation in ('cad.create','cad.import') or operation=='cad.migrate' and 'asset' in params
    require(source_revision is None if new else bool(source_revision), 'creation/import and asset migration need a new project; other operations need a source revision')
    encoded(params)
    if operation=='cad.create':
        if 'document' in params:
            require(set(params)=={'document'}, 'document creation fields differ'); admission.inspect(encoded(params['document']))
        else:
            require(type(params.get('recipe')) is str and params['recipe'] in (panel.RECIPE,solid.RECIPE), 'creation needs a complete model or known panel recipe')
            require(set(params)=={'recipe','version','width','height'}|({'depth'} if params['recipe']==solid.RECIPE else set()), 'recipe fields differ')
            require(type(params['version']) is int and params['version']==1, 'recipe version unsupported')
            for key in ('width','height')+ (('depth',) if 'depth' in params else ()): panel.dimension(params[key])
    elif operation=='cad.import':
        require(set(params)=={'asset','format'} and type(params['format']) is str and params['format'] in ('json','dobecad'), 'import needs explicit json or dobecad format')
    elif operation=='cad.edit':
        require(set(params)=={'expected_sha256','edits'}, 'edit needs portable hash and typed changes')
        edits=params['edits']; require(type(edits) is list and 1<=len(edits)<=project.MAX_EDITS, 'edit needs one to 128 changes')
        require(all(type(e) is dict and type(e.get('kind')) is str and e['kind'] in revision.KINDS-cad_history.KINDS for e in edits),
                'edit needs primitive changes; use solve or solid for native production')
    elif operation=='cad.migrate': require(set(params)==({'asset','expected_sha256'} if new else {'expected_sha256'}), 'migration fields differ')
    elif operation=='cad.solve': require(set(params)=={'expected_sha256'}, 'solve needs exact portable hash')
    elif operation=='cad.solid':
        require(set(params)=={'expected_sha256','depth'}, 'solid needs exact portable hash and depth'); panel.dimension(params['depth'])
    elif operation=='cad.export':
        require(set(params)=={'expected_sha256','format'} and params['format']=='obj', 'delivery needs exact portable hash and explicit obj format')
    else: require(not params, 'inspection and portable delivery take no parameters')
    if 'expected_sha256' in params:
        require(type(params['expected_sha256']) is str and re.fullmatch('[0-9a-f]{64}',params['expected_sha256']), 'expected portable hash invalid')
    if 'asset' in params: require(type(params['asset']) is str and video.ASSET.fullmatch(params['asset']), 'import needs a project-scoped asset identifier')


def assets(operation, params):
    return {params['asset']:'inputs/cad-'+params['asset']} if operation in ('cad.import','cad.migrate') and 'asset' in params else {}


def execute(root, operation, params):
    new = operation in ('cad.create','cad.import') or operation=='cad.migrate' and 'asset' in params
    validate(operation,params,None if new else 'source')
    root=Path(root).resolve(strict=True); current=owned(root,root/'native/project.dobecad'); origin=owned(root,root/'recipes/origin-cad-operation.json')
    require(not new or not (root/'native').exists(), 'creation/import cannot replace existing native files')
    trusted=binding.resolve(); previous=None if new else read_bytes(current); retained_origin=None if new else read_bytes(origin)
    if previous is not None:
        prior=project.inspect_bytes(previous)
        if operation!='cad.migrate': project.require_engine(prior,trusted['expected_pin'])
        for name in (n for n in prior['members'] if n!='project.json'):
            require(read_bytes(owned(root,root/'native'/name))==prior['members'][name], 'published original/model differs from portable source')
        if 'expected_sha256' in params: require(source.sha(previous)==params['expected_sha256'], 'operation portable hash is stale')
    with tempfile.TemporaryDirectory(prefix='.cad-attempt-',dir=root) as temporary:
        scratch=Path(temporary); production=None; immediate=None
        if operation=='cad.create':
            if 'document' in params: model=encoded(params['document'])
            else:
                compiled=panel.create(admission.base(),params['width'],params['height']); model=encoded(compiled['document'])
                production={'request':params,'recipe':compiled['recipe'],'defaults_sha256':admission.BASE_SHA256,
                            'source_revision':binding.REVISION,'shares_user_content':False}
            data=project.create(model,'json',engine=trusted['expected_pin'])
            if params.get('recipe')==solid.RECIPE:
                data=project.revise(data,source.sha(data),[{'kind':'panel.solid','recipe':compiled['recipe'],
                    'width':params['width'],'height':params['height'],'depth':params['depth'],'mesh_handle':None}])
        elif operation=='cad.import':
            imported=read_bytes(owned(root,root/assets(operation,params)[params['asset']]))
            data=imported if params['format']=='dobecad' else project.create(imported,'json',engine=trusted['expected_pin'])
        elif operation=='cad.migrate':
            predecessor=previous if previous is not None else read_bytes(owned(root,root/assets(operation,params)[params['asset']]))
            data=project.migrate(predecessor,params['expected_sha256'],engine=trusted['expected_pin'])
        elif operation=='cad.edit': data=project.revise(previous,params['expected_sha256'],params['edits'])
        else: data=previous
        checked=project.inspect_bytes(data); project.require_engine(checked,trusted['expected_pin'])
        admitted=admission.inspect_project(checked); profile=admitted['current']
        if operation in ('cad.solve','cad.solid','cad.export'):
            require(profile['recipe'] is not None, 'production operation needs a constrained panel recipe')
        if operation=='cad.solid':
            data=project.revise(data,params['expected_sha256'],[{'kind':'panel.solid','recipe':profile['recipe'],
                'width':profile['parameters']['width'],'height':profile['parameters']['height'],'depth':params['depth'],
                'mesh_handle':profile['meshes'][0]['handle'] if profile['meshes'] else None}])
            checked=project.inspect_bytes(data); admitted=admission.inspect_project(checked); profile=admitted['current']
        # Even the native version probe follows complete admission of all states.
        native=cad_engine.Engine(root=scratch,**trusted)
        if operation=='cad.solve':
            model=checked['members']['document.json']; path=scratch/'solve-input.json'; path.write_bytes(model)
            options={'width':profile['parameters']['width'],'height':profile['parameters']['height'],
                     'mesh_handle':profile['meshes'][0]['handle'] if profile['meshes'] else None}
            solved=native.solve_panel(path,model,profile['recipe'],**options)
            immediate={'measurements':solved['measurements'],'source_sha256':solved['source_sha256'],'solved_sha256':solved['solved_sha256']}
            if revision.canonical(solved['document'])!=revision.canonical(checked['current']['document']):
                captured=cad_history.capture_solve(model,solved['data'],profile['recipe'],**options)
                data=project.revise(data,source.sha(data),[captured]); checked=project.inspect_bytes(data)
                admitted=admission.inspect_project(checked); profile=admitted['current']
        report=native.verify_project(data,scratch/'observed')
        if immediate is not None:
            report['native_constraint_solve_verified']=True
            report['pending_qualification']=[item for item in report['pending_qualification'] if item!='native-constraint-solve']
        report.update(operation=operation,previous_project_sha256=source.sha(previous) if previous else None,admission=admitted,
            immediate_solve=immediate,requested_state_verified=operation in ('cad.create','cad.edit','cad.solve','cad.solid'),render_qualified=False)
        if previous is not None:
            require(read_bytes(current)==previous and read_bytes(origin)==retained_origin, 'owned project or origin changed during observation')
            require(checked['source_sha256']==prior['source_sha256'], 'revision replaced immutable original')
        prepared=scratch/'prepared'
        for directory in ('native','exports','recipes'): (prepared/directory).mkdir(parents=True)
        (prepared/'native/project.dobecad').write_bytes(data)
        for name,value in checked['members'].items():
            if name!='project.json': (prepared/'native'/name).write_bytes(value)
        if operation=='cad.export':
            require(len(profile['meshes'])==1, 'OBJ delivery needs a generated panel solid')
            mesh=profile['meshes'][0]['handle']; dimensions=profile['parameters']
            solid.request(checked['current']['document'],profile['recipe'],mesh_handle=mesh,**dimensions)
            delivery=native.export_panel_obj(scratch/'observed/document.json',checked['members']['document.json'],mesh,**dimensions)
            (prepared/'exports/panel.obj').write_bytes(delivery.pop('data')); report['delivery']=delivery
        report['native_calls']=native.calls
        (prepared/'exports/inspection.json').write_bytes(revision.encoded(report))
        (prepared/'exports/structure.json').write_bytes(revision.encoded(profile))
        if operation=='cad.bundle': (prepared/'exports/drawing.dobecad').write_bytes(data)
        request=encoded({'operation':operation,'parameters':params})
        (prepared/'recipes/last-cad-operation.json').write_bytes(request)
        (prepared/'recipes/origin-cad-operation.json').write_bytes(request if new else retained_origin)
        if production is not None: (prepared/'recipes/cad-production.json').write_bytes(revision.encoded(production))
        elif not new:
            retained=owned(root,root/'recipes/cad-production.json')
            if retained.exists(): (prepared/'recipes/cad-production.json').write_bytes(read_bytes(retained))
        artifacts=[]
        for path in sorted(prepared.rglob('*')):
            if not path.is_file(): continue
            relative=path.relative_to(prepared); target=owned(root,root/relative); target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target); require(read_bytes(target)==path.read_bytes(), 'staged artifact differs from verified output')
            artifacts.append({'path':relative.as_posix(),'role':'native' if relative.parts[0]=='native' else 'recipe' if relative.parts[0]=='recipes' else 'export'})
    return {'engine':{'name':'cadcraft','version':VERSION,'build':binding.VERSION_RESPONSE},'artifacts':artifacts,
        'validation':{'passed':True,'native_model_equal':True,'native_cold_reopen':True,'initial_source_preserved':True,'source_backed':True,
            'requested_state_verified':report['requested_state_verified'],'engine_migration_verified':operation=='cad.migrate',
            'admission_profile':admission.PROFILE,'profile_admission_complete':True,'general_admission_complete':False,
            'native_constraint_solve_verified':report['native_constraint_solve_verified'] or immediate is not None,
            'native_solid_regeneration_verified':report['native_solid_regeneration_verified'],
            'geometry_delivery_verified':operation=='cad.export','render_qualified':False,'visual_approval':False,
            'source_format_fidelity_qualified':False,'general_manufacturing_qualified':False,
            'pending_qualification':report['pending_qualification'],
            'qualification':'metric-drawing-panel-v1 admission, exact native history and portable originals'}}
