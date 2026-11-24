"""Closed, metre-based 3D production contract; independent of 2D construction."""
import copy
import math
import re
from .construction_schema import require, digest, NAME

POLICY = {'network': 'offline', 'media_generation': 'disabled'}
PROFILE = 'product-scene-v1'

def fields(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional), 'Missing or unsupported production fields')

def number(value, low, high):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, 'Production number outside bounds')

def vector(value, low=-100, high=100):
    require(isinstance(value, list) and len(value) == 3, 'Expected three coordinates')
    for n in value: number(n, low, high)

def color(value):
    require(isinstance(value, str) and re.fullmatch('#[0-9a-fA-F]{6}', value), 'Expected RGB hex color')

def named(rows, maximum):
    require(isinstance(rows, list) and 1 <= len(rows) <= maximum, 'Production collection outside bounds')
    names = set()
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get('id'), str) and NAME.fullmatch(row['id']) and row['id'] not in names, 'Invalid or duplicate native ID')
        names.add(row['id'])
    return names

def validate(d):
    fields(d, ('schema_version', 'profile', 'policy', 'render', 'camera', 'materials', 'objects', 'lights', 'world'))
    require(type(d['schema_version']) is int and d['schema_version'] == 1 and d['profile'] == PROFILE, 'Unsupported 3D production version/profile')
    require(d['policy'] == POLICY, '3D production requires offline execution; image models are a separate route')
    r = d['render']; fields(r, ('width', 'height', 'samples', 'seed'))
    for k in ('width', 'height'): require(type(r[k]) is int and 64 <= r[k] <= 2048 and r[k] % 8 == 0, 'Render size must be a multiple of 8, 64–2048')
    require(type(r['samples']) is int and 1 <= r['samples'] <= 512, 'Samples outside 1–512')
    require(type(r['seed']) is int and 0 <= r['seed'] < 2**31, 'Invalid render seed')
    c = d['camera']; fields(c, ('location', 'target', 'lens', 'fstop'))
    vector(c['location']); vector(c['target']); number(c['lens'], 18, 200); number(c['fstop'], 1, 32)
    require(math.dist(c['location'], c['target']) > .001, 'Camera requires a distinct target')
    w = d['world']; fields(w, ('color', 'strength')); color(w['color']); number(w['strength'], 0, 2)
    materials = named(d['materials'], 32)
    for m in d['materials']:
        fields(m, ('id', 'color', 'roughness', 'metallic', 'transmission', 'ior'), ('coat', 'bump', 'bump_scale'))
        color(m['color'])
        for k in ('roughness', 'metallic', 'transmission', 'coat'): number(m.get(k, 0), 0, 1)
        number(m['ior'], 1, 2.5); number(m.get('bump', 0), 0, .002); number(m.get('bump_scale', 100), 1, 20000)
    names = named(d['objects'], 128)
    for o in d['objects']:
        common = ('id', 'kind', 'material', 'location', 'rotation')
        extras = {'box': ('size', 'bevel'), 'cylinder': ('radius', 'depth', 'bevel'), 'sphere': ('radius',), 'lathe': ('profile',), 'text': ('text', 'size', 'extrude')}
        require(isinstance(o.get('kind'), str) and o['kind'] in extras, 'Unsupported 3D primitive')
        fields(o, common + extras[o['kind']]); require(o['material'] in materials, 'Unknown material')
        vector(o['location']); vector(o['rotation'], -360, 360)
        if o['kind'] == 'box':
            vector(o['size'], .0001, 50); number(o['bevel'], 0, min(o['size']) / 2)
        if o['kind'] in ('cylinder', 'sphere'): number(o['radius'], .0001, 25)
        if o['kind'] == 'cylinder': number(o['depth'], .0001, 50); number(o['bevel'], 0, min(o['radius'], o['depth']/2))
        if o['kind'] == 'lathe':
            p = o['profile']; require(isinstance(p, list) and 3 <= len(p) <= 128, 'Lathe requires 3–128 radius/height points')
            for v in p:
                require(isinstance(v, list) and len(v) == 2, 'Invalid lathe point'); number(v[0], .00001, 25); number(v[1], -50, 50)
        if o['kind'] == 'text':
            require(isinstance(o['text'], str) and 1 <= len(o['text']) <= 256 and all(32 <= ord(v) <= 126 or v == '\n' for v in o['text']), 'Text profile supports printable ASCII')
            number(o['size'], .0001, 1); number(o['extrude'], 0, .01)
    lights = named(d['lights'], 16)
    require(not names & lights and 'Camera' not in names | lights, 'Object and light IDs must be disjoint')
    for light in d['lights']:
        fields(light, ('id', 'location', 'target', 'color', 'power', 'size', 'size_y'))
        vector(light['location']); vector(light['target']); color(light['color'])
        require(math.dist(light['location'], light['target']) > .001, 'Light requires a distinct target')
        number(light['power'], 0, 10000); number(light['size'], .001, 20); number(light['size_y'], .001, 20)
    require(len(__import__('json').dumps(d, allow_nan=False).encode()) <= 262144, 'Production recipe exceeds 256 KiB')
    return d

EDIT_FIELDS = {
    'materials': {'color','roughness','metallic','transmission','ior','coat','bump','bump_scale'},
    'lights': {'location','target','color','power','size','size_y'},
    'objects': {'location','rotation','material','text','size','extrude'},
    'camera': {'location','target','lens','fstop'},
    'world': {'color','strength'},
}

def validate_edit(edit):
    fields(edit, ('collection', 'id', 'field', 'before', 'value'))
    collection, identifier, field = edit['collection'], edit['id'], edit['field']
    require(isinstance(collection,str) and collection in EDIT_FIELDS and isinstance(identifier,str)
            and isinstance(field,str) and field in EDIT_FIELDS[collection], 'Unsupported production edit field')
    if collection in ('camera','world'):
        require(identifier == collection, 'Singleton edit ID must match its collection')

def revise(before, edits):
    require(isinstance(edits, list) and 1 <= len(edits) <= 64, 'Provide 1–64 supported native edits')
    after = copy.deepcopy(before); seen = set()
    for edit in edits:
        validate_edit(edit)
        collection, identifier, field = edit['collection'], edit['id'], edit['field']
        key = (collection, identifier, field); require(key not in seen, 'Duplicate edit'); seen.add(key)
        row = after[collection] if collection in ('camera','world') else next((r for r in after[collection] if r['id'] == identifier), None)
        require(row is not None and field in row and row[field] == edit['before'], 'Production revision precondition failed')
        if collection == 'objects' and field in ('text','size','extrude'):
            require(row['kind']=='text', 'Mesh topology and dimensions are not native patch fields')
        row[field] = copy.deepcopy(edit['value'])
    validate(after)
    return after
