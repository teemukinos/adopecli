"""Pre-execution admission for editable metric drawings and parametric panels.

Every field is either checked here or equal to source-pinned native defaults.
Portable source ownership is broader: unsupported data remains preserved there,
but cannot enter public native execution through this profile. Admission does
not attest solving, rendering, manufacturing or general CAD/DXF fidelity.
"""
from pathlib import Path
import math
import re

from . import cad_source as source, cad_revision as revision, cad_parametric as panel, cad_solid as solid
from .cad_source import require
from .write_container import read_bytes

PROFILE = 'metric-drawing-panel-v1'
BASE_SHA256 = '597a1e95c2e7f66eb38740cd82ef6281616c8c68280737100155f82e31209629'
MAX_ENTITIES = 2048
MAX_TEXT = 100_000


def base():
    data = read_bytes(Path(__file__).with_name('cad_recipe_base.json'))
    require(source.sha(data) == BASE_SHA256, 'admission native defaults changed')
    return source.strict_json(data)


def same(actual, expected, label):
    require(revision.canonical(actual) == revision.canonical(expected), 'admission '+label+' needs separate qualification')


def fields(value, names, label):
    require(type(value) is dict and set(value) == set(names), 'admission '+label+' fields differ')


def number(value, low, high, label):
    # Complete native geometry serializes floating values as floating JSON.
    require(type(value) is float and math.isfinite(value) and low <= value <= high,
            'admission '+label+' must be a bounded native floating value')


def point(value):
    fields(value, ('x','y','z'), 'point')
    for value in value.values(): number(value, -1e6, 1e6, 'coordinate')


def text(value, maximum, label):
    require(type(value) is str and len(value.encode('utf-8')) <= maximum
            and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'admission '+label+' must be bounded plain text')


def literal(value):
    require(type(value) is str and len(value) <= 64 and re.fullmatch(r'[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',value),
            'admission panel parameter must be a numeric literal')
    return panel.dimension(float(value))


def inspect(data):
    checked = source.inspect_bytes(data, 'json'); document = checked['document']; defaults = base()
    fields(document, defaults, 'drawing')
    for key in set(defaults)-{'model','handseed','constraints','parametric','read_notes'}:
        same(document[key], defaults[key], 'drawing '+key)
    notes = source.sequence(document['read_notes'], 'admitted source notes', 256)
    text_bytes = 0
    for note in notes:
        text(note, 4096, 'source note'); text_bytes += len(note.encode('utf-8'))
    rows = source.sequence(document['model'], 'admitted entities', MAX_ENTITIES)
    common = panel.create(defaults, 1, 1)['document']['model'][0]['common']
    meshes = []
    for entity in rows:
        fields(entity, ('handle','common','kind'), 'entity'); properties = entity['common']; fields(properties, common, 'entity properties')
        for key in set(common)-{'layer','visible','ltscale','thickness'}: same(properties[key], common[key], 'entity '+key)
        require(type(properties['layer']) is str and properties['layer'] in ('0','Defpoints'), 'admission layer is not owned')
        require(type(properties['visible']) is bool, 'admission visibility must be boolean')
        number(properties['ltscale'], 1e-6, 1e4, 'linetype scale'); number(properties['thickness'], -1e4, 1e4, 'thickness')
        geometry = entity['kind']; kind = geometry['type']
        if kind == 'line':
            fields(geometry, ('type','a','b'), 'line'); point(geometry['a']); point(geometry['b'])
        elif kind == 'circle':
            fields(geometry, ('type','center','radius'), 'circle'); point(geometry['center']); number(geometry['radius'], 1e-6, 1e6, 'radius')
        elif kind == 'text':
            fields(geometry, ('type','insert','alignPt','height','value','rotation','widthFactor','oblique','style','halign','valign'), 'text')
            point(geometry['insert'])
            if geometry['alignPt'] is not None: point(geometry['alignPt'])
            number(geometry['height'], 1e-3, 1e4, 'text height'); number(geometry['widthFactor'], 1e-3, 100, 'text width factor')
            number(geometry['rotation'], -360, 360, 'rotation'); number(geometry['oblique'], -85, 85, 'oblique')
            same(geometry['style'], 'Standard', 'text style')
            require(type(geometry['halign']) is str and geometry['halign'] in ('left','center','right','aligned','middle','fit'), 'admission horizontal alignment invalid')
            require(type(geometry['valign']) is str and geometry['valign'] in ('baseline','bottom','middle','top'), 'admission vertical alignment invalid')
            text(geometry['value'], MAX_TEXT, 'text value'); text_bytes += len(geometry['value'].encode('utf-8'))
        elif kind == 'polyfaceMesh':
            fields(geometry, ('type','vertices','faces'), 'panel mesh')
            points = source.sequence(geometry['vertices'], 'panel vertices', 8); require(len(points) == 8, 'admission panel vertex count differs')
            for value in points: point(value)
            corner = points[6]; dimensions = dict(zip(('width','height','depth'), (corner[k] for k in ('x','y','z'))))
            measured = solid.inspect_mesh(geometry, **dimensions)
            same(points, solid.vertices(**dimensions), 'panel vertex order'); same(geometry['faces'], solid.FACES, 'panel face order')
            meshes.append({'handle':entity['handle'], 'measurements':measured})
        else: raise ValueError('CAD admission entity '+kind+' needs separate qualification')
    require(text_bytes <= MAX_TEXT, 'admission aggregate text budget exceeded')
    parameters = document['parametric']; fields(parameters, defaults['parametric'], 'parametric settings')
    same(parameters['settings'], defaults['parametric']['settings'], 'constraint settings')
    recipe = None; dimensions = None
    if document['constraints']:
        require(len(rows) in (4,5) and all(row['kind']['type']=='line' for row in rows[:4])
                and (len(rows)==4 or rows[4]['kind']['type']=='polyfaceMesh'), 'admission constrained entities need the panel recipe')
        handles = [row['handle'] for row in rows[:4]]
        same(document['constraints'], panel.constraints(handles), 'panel constraints')
        recipe = {'id':panel.RECIPE,'version':panel.VERSION,'units':'mm','entities':dict(zip(('bottom','right','top','left'),handles)),
                  'fixed_origin':[0.0,0.0],'parameters':['width','height']}
        same(rows[0]['kind']['a'], panel.point(0,0), 'fixed panel origin')
        names = ['width','height']+(['depth'] if meshes else [])
        values = source.sequence(parameters['parameters'], 'panel parameters', 3)
        require(len(values)==len(names), 'admission panel parameter count differs'); dimensions = {}
        for value, name in zip(values,names):
            fields(value, ('name','expr','description'), 'parameter'); same(value['name'], name, 'parameter name')
            text(value['description'], 4096, 'parameter description'); dimensions[name] = literal(value['expr'])
    else:
        same(parameters['parameters'], [], 'unconstrained parameters'); require(not meshes, 'admission mesh requires an owned panel sketch')
    return {'profile':PROFILE,'profile_admission_complete':True,'general_admission_complete':False,'source_sha256':checked['source_sha256'],
            'entities':len(rows),'entity_kinds':checked['inventory']['entity_kinds'],'text_bytes':text_bytes,'units':'mm',
            'recipe':recipe,'parameters':dimensions,'meshes':meshes,'system_fonts':False,'external_resources':False,
            'native_execution_verified':False,'constraint_solve_verified':False,'render_qualified':False,
            'source_format_fidelity_qualified':False,'general_manufacturing_qualified':False,
            'pending_qualification':['native-full-model-comparison','rendered-fidelity','broader-model-and-resource-admission','complete-dxf-semantics']}


def inspect_project(checked):
    # DXF ownership alone does not qualify its native parser. Its wire semantics
    # need a separate admission boundary before even a version probe is run.
    require(checked['manifest']['source_format']=='json', 'admission DXF execution needs separate wire-semantic qualification')
    replay = checked['members']['baseline.json']; baseline = inspect(replay); states = [baseline['source_sha256']]
    current = baseline
    for entry in checked['manifest']['history']:
        replay = revision.revise_bytes(replay, entry['before'], entry['edits'])['data']; current = inspect(replay); states.append(current['source_sha256'])
    require(replay==checked['members']['document.json'], 'admission history differs from current model')
    return {'profile':PROFILE,'baseline':baseline,'current':current,'admitted_state_sha256':states,
            'profile_admission_complete':True,'general_admission_complete':False}
