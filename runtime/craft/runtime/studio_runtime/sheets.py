"""Durable Sheets operations with complete native replay and portable originals.

The supervisor owns fencing, cancellation and publication. This adapter writes
only its disposable attempt and never accepts an executable or arbitrary script.
"""
from pathlib import Path
import re
import shutil
import tempfile

from . import sheets_binding as binding, sheets_source as source, sheets_project as project, sheets_engine, sheets_recipes as recipes, video
from .sheets_source import require
from .write_engine import owned
from .write_container import read_bytes

VERSION = binding.VERSION
OPERATIONS = tuple('sheets.'+name for name in ('create','import','inspect','edit','calculate','export','bundle'))


def encoded(value):
    data=source.encoded(value);source.strict_json(data);return data


def validate(operation,params,source_revision):
    require(operation in OPERATIONS and type(params) is dict,'unsupported operation or parameters')
    new=operation in ('sheets.create','sheets.import')
    require(source_revision is None if new else bool(source_revision),'creation/import need a new project; other operations need a source revision')
    encoded(params)
    if operation=='sheets.create':
        if 'document' in params:
            source.fields(params,('document',),'document creation');source.inspect_bytes(encoded(params['document']))
        else:recipes.validate(params)
    elif operation=='sheets.import':
        source.fields(params,('asset','format'),'import');require(params['format'] in ('json','dobesheets'),'import needs explicit json or dobesheets format')
        require(type(params['asset']) is str and video.ASSET.fullmatch(params['asset']),'import needs a project-scoped asset identifier')
    elif operation=='sheets.edit':
        source.fields(params,('expected_sha256','edits'),'edit');source.edits(params['edits'])
    elif operation=='sheets.calculate':source.fields(params,('expected_sha256',),'calculation')
    elif operation=='sheets.export':
        source.fields(params,('expected_sha256','format'),'export');require(params['format'] in ('csv','html'),'export needs csv or html format')
    else:require(not params,'inspection and bundle take no parameters')
    if 'expected_sha256' in params:require(type(params['expected_sha256']) is str and re.fullmatch('[0-9a-f]{64}',params['expected_sha256']),'expected portable hash invalid')


def assets(operation,params):return {params['asset']:'inputs/sheets-'+params['asset']} if operation=='sheets.import' else {}


def execute(root,operation,params):
    new=operation in ('sheets.create','sheets.import');validate(operation,params,None if new else 'source')
    root=Path(root).resolve(strict=True);current=owned(root,root/'native/project.dobesheets');origin=owned(root,root/'recipes/origin-sheets-operation.json')
    require(not new or not (root/'native').exists(),'creation/import cannot replace native files')
    previous=None if new else read_bytes(current);retained_origin=None if new else read_bytes(origin);trusted=binding.resolve()
    if previous is not None:
        prior=project.inspect_bytes(previous)
        for name,payload in prior['members'].items():
            if name!='project.json':require(source.read_bytes(owned(root,root/'native'/name))==payload,'published model differs from portable source')
        if 'expected_sha256' in params:require(source.sha(previous)==params['expected_sha256'],'operation portable hash is stale')
    with tempfile.TemporaryDirectory(prefix='.sheets-attempt-',dir=root) as temporary:
        scratch=Path(temporary);compiled=None;change=None
        if operation=='sheets.create':
            if 'document' in params:initial=encoded(params['document']);change={'kind':'calculate'}
            else:compiled=recipes.compile(params);initial=compiled['source'];change=compiled['operation']
            data=project.create(initial,engine=trusted['expected_pin'])
        elif operation=='sheets.import':
            imported=read_bytes(owned(root,root/assets(operation,params)[params['asset']]))
            data=imported if params['format']=='dobesheets' else project.create(imported,engine=trusted['expected_pin'])
            if params['format']=='json':change={'kind':'calculate'}
        else:data=previous
        checked=project.inspect_bytes(data)
        # Every history model and typed request passes static preflight before
        # even the native version probe. The fixed parser then checks its AST
        # profile before any calculation, never executing macros or Python.
        native=sheets_engine.Engine(root=scratch,**trusted)
        before_report=native.verify_project(data,scratch/'before')
        if operation=='sheets.edit':change={'kind':'cells.edit','edits':params['edits']}
        elif operation=='sheets.calculate':change={'kind':'calculate'}
        if change is not None:
            produced=native.produce(scratch/'before/document.json',checked['members']['document.json'],change)
            data=project.append_candidate(data,source.sha(data),change,produced['data']);checked=project.inspect_bytes(data)
            report=native.verify_project(data,scratch/'after');observed=scratch/'after'
        else:
            # Reuse the previous full replay; no caller report is trusted.
            report=before_report;observed=scratch/'before'
        if previous is not None:
            require(read_bytes(current)==previous and read_bytes(origin)==retained_origin,'owned source/origin changed during observation')
            require(checked['source_sha256']==prior['source_sha256'],'operation replaced immutable original')
        prepared=scratch/'prepared'
        for name in ('native','exports','recipes'):(prepared/name).mkdir(parents=True)
        (prepared/'native/project.dobesheets').write_bytes(data)
        for name,payload in checked['members'].items():
            if name!='project.json':(prepared/'native'/name).write_bytes(payload)
        if operation=='sheets.export':
            delivery=native.export(observed/'document.json',checked['members']['document.json'],params['format'])
            (prepared/('exports/workbook.'+params['format'])).write_bytes(delivery.pop('data'));report['delivery']=delivery
        if operation=='sheets.bundle':(prepared/'exports/workbook.dobesheets').write_bytes(data)
        report.update(operation=operation,native_calls=native.calls,previous_project_sha256=source.sha(previous) if previous else None)
        profile=checked['profiles']['document.json'];structure={k:profile[k] for k in ('sha256','bytes','cell_count','formula_count','sheet_names','profile')}
        (prepared/'exports/inspection.json').write_bytes(source.encoded(report));(prepared/'exports/structure.json').write_bytes(source.encoded(structure))
        request=encoded({'operation':operation,'parameters':params})
        (prepared/'recipes/last-sheets-operation.json').write_bytes(request);(prepared/'recipes/origin-sheets-operation.json').write_bytes(request if new else retained_origin)
        if compiled is not None:(prepared/'recipes/sheets-production.json').write_bytes(source.encoded(compiled['recipe']))
        elif not new:
            retained=owned(root,root/'recipes/sheets-production.json')
            if retained.exists():(prepared/'recipes/sheets-production.json').write_bytes(source.read_bytes(retained))
        artifacts=[]
        for path in sorted(prepared.rglob('*')):
            if not path.is_file():continue
            relative=path.relative_to(prepared);target=owned(root,root/relative);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
            require(target.read_bytes()==path.read_bytes(),'staged artifact differs from verified output')
            artifacts.append({'path':relative.as_posix(),'role':'native' if relative.parts[0]=='native' else 'recipe' if relative.parts[0]=='recipes' else 'export'})
    return {'engine':{'name':'gridcraft','version':VERSION,'build':binding.VERSION_RESPONSE},'artifacts':artifacts,
            'validation':{'passed':True,'native_model_equal':True,'native_cold_reopen':True,'initial_source_preserved':True,
                'source_backed':True,'profile_admission_complete':True,'general_admission_complete':False,
                'admission_profile':'cells-and-formulas-v1','native_history_replayed':True,'native_calculation_verified':report['calculation_verified'],
                'delivery_verified':operation=='sheets.export','render_qualified':False,'visual_approval':False,
                'qualification':'bounded native workbook model, exact native operation replay and portable original'}}
