"""Exact CAD source bytes, bounded JSON and typed DXF tag inventories.

Inspection never runs an engine, reads a referenced path or grants execution
permission. DXF tags are owned independently; their full native Drawing mapping
still requires receipt-bound native baseline verification.
"""
import hashlib
import json
import math
import re
import struct

from . import animate_format, write_container

MAX_SOURCE = 128 << 20
MAX_JSON = 32 << 20
MAX_ENTITIES = 100_000
MAX_TAGS = 250_000
MAX_RASTERS = 64 << 20
BINARY = b'AutoCAD Binary DXF\r\n\x1a\x00'
FIELDS = set('header foreign layers linetypes text_styles dim_styles mleader_styles table_styles mline_styles blocks model layouts active_layout views vports ucss layer_states groups plot_style_tables constraints parametric scales handseed hidden_objects read_notes refedit skipped_records portable_fonts rasters'.split())
LINE_END = re.compile(rb'\r\n|\r|\n')


def require(condition, message):
    if not condition: raise ValueError('CAD '+message)


def sha(data): return hashlib.sha256(data).hexdigest()


def strict_json(data):
    require(type(data) is bytes and 0 < len(data) <= MAX_JSON, 'JSON exceeds byte budget')
    try: animate_format._preflight(data, 2_000_000)
    except ValueError as error: raise ValueError('CAD JSON preflight failed: '+str(error)) from error
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'JSON contains duplicate keys'); result[key] = value
        return result
    def integer(token):
        require(len(token.lstrip('-')) <= 20 and -2**63 <= int(token) < 2**64, 'JSON integer exceeds native range')
        return int(token)
    def floating(token):
        value = float(token); require(math.isfinite(value), 'JSON number must be finite binary64'); return value
    def constant(_): raise ValueError('CAD JSON number must be finite')
    try: value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_int=integer, parse_float=floating, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error: raise ValueError('CAD JSON is malformed') from error
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict: pending.extend(item); pending.extend(item.values())
        elif type(item) is list: pending.extend(item)
        elif type(item) is str: require(not any(0xd800 <= ord(c) <= 0xdfff for c in item), 'JSON contains invalid Unicode')
    return value


def sequence(value, label, maximum):
    require(type(value) is list and len(value) <= maximum, label+' exceeds list budget'); return value


def identity(value, label):
    require(type(value) is int and 0 < value < 2**64, label+' must be a positive native handle'); return value


def model_inventory(document):
    require(type(document) is dict and FIELDS <= set(document), 'model omits native drawing fields')
    require(type(document['blocks']) is dict and len(document['blocks']) <= 4096, 'block inventory invalid')
    layouts = sequence(document['layouts'], 'layouts', 4096)
    stores = [('/model', document['model'])]; external = []; layout_names = set()
    for index, layout in enumerate(layouts):
        require(type(layout) is dict and type(layout.get('name')) is str and layout['name'] not in layout_names, 'layout identity invalid')
        layout_names.add(layout['name']); stores.append((f'/layouts/{index}/entities', layout.get('entities')))
    for name, block in document['blocks'].items():
        require(type(block) is dict and block.get('name') == name, 'block identity differs')
        stores.append(('/blocks/'+name.replace('~','~0').replace('/','~1')+'/entities', block.get('entities')))
        path = block.get('xrefPath')
        require(path is None or type(path) is str, 'xref path must be text or null')
        if path is not None: external.append({'kind':'xref', 'owner':name, 'reference':path})
    entities = []; handles = set(); kinds = set()
    for owner, store in stores:
        for index, entity in enumerate(sequence(store, 'entity store', MAX_ENTITIES)):
            require(type(entity) is dict and type(entity.get('kind')) is dict and type(entity['kind'].get('type')) is str, 'entity lacks typed geometry')
            handle = identity(entity.get('handle'), 'entity')
            require(handle not in handles, 'duplicate entity handle across drawing stores'); handles.add(handle)
            entities.append((owner+'/'+str(index), entity)); require(len(entities) <= MAX_ENTITIES, 'aggregate entity budget exceeded')
            kinds.add(entity['kind']['type'])
            if entity['kind']['type'] == 'image':
                path = entity['kind'].get('path'); require(type(path) is str, 'image reference must be text')
                external.append({'kind':'image', 'owner':handle, 'reference':path})
    seed = identity(document['handseed'], 'next handle')
    require(not handles or seed > max(handles), 'next handle would collide with an existing entity')
    constraints = sequence(document['constraints'], 'constraints', 5000); ids = set(); unresolved = []
    for constraint in constraints:
        require(type(constraint) is dict and type(constraint.get('id')) is int and 0 <= constraint['id'] < 2**32
                and constraint['id'] not in ids, 'constraint identity invalid or duplicated'); ids.add(constraint['id'])
        for reference in sequence(constraint.get('refs'), 'constraint references', 64):
            require(type(reference) is dict, 'constraint reference must be an object')
            handle = identity(reference.get('handle'), 'constraint reference')
            if handle not in handles: unresolved.append({'constraint':constraint['id'],'handle':handle})
    rasters = document['rasters']; require(type(rasters) is dict and len(rasters) <= 4096, 'raster inventory invalid')
    resources = []; total = 0
    for name, raster in rasters.items():
        require(type(raster) is dict and set(raster) == {'width','height','rgba','opaque'}, 'raster fields differ')
        width = raster['width']; height = raster['height']; pixels = raster['rgba']
        require(type(width) is int and type(height) is int and 0 < width < 2**32 and 0 < height < 2**32, 'raster geometry invalid')
        require(type(pixels) is list and len(pixels) == width*height*4 and len(pixels) <= MAX_RASTERS, 'raster byte count differs')
        require(all(type(value) is int and 0 <= value <= 255 for value in pixels), 'raster channels must be bytes')
        require(type(raster['opaque']) is bool and raster['opaque'] == all(alpha == 255 for alpha in pixels[3::4]), 'raster opacity differs')
        total += len(pixels); require(total <= MAX_RASTERS, 'aggregate raster bytes exceeded')
        resources.append({'name':name,'width':width,'height':height,'bytes':len(pixels),'sha256':sha(bytes(pixels))})
    foreign = document['foreign']; require(type(foreign) is dict, 'foreign source data must be an object')
    records = sequence(foreign.get('records'), 'foreign records', 100_000); keys = set()
    for row in records:
        require(type(row) is list and len(row) == 2 and type(row[0]) is list and len(row[0]) == 2
                and all(type(s) is str for s in row[0]) and type(row[1]) is dict, 'foreign compound record invalid')
        key = tuple(row[0]); require(key not in keys, 'duplicate foreign compound record'); keys.add(key)
    return {'entities':entities,'entity_count':len(entities),'entity_kinds':sorted(kinds),'external_references':external,
            'resources':resources,'binary_bytes':total,'unresolved_constraints':unresolved,'unknown_fields':sorted(set(document)-FIELDS)}


def group_kind(code):
    # Mirrors the pinned DXF crate's wire-type classification, not its permissive
    # numeric repair. Unknown codes retain their exact string payload.
    if any(low <= code <= high for low,high in ((10,59),(110,149),(210,239),(460,469),(1010,1059))): return 'real'
    if any(low <= code <= high for low,high in ((60,79),(170,179),(270,289),(370,389),(400,409),(1060,1070))): return 'int16'
    if any(low <= code <= high for low,high in ((90,99),(420,429),(440,459))) or code == 1071: return 'int32'
    if 160 <= code <= 169: return 'int64'
    if 290 <= code <= 299: return 'bool'
    if 310 <= code <= 319 or code == 1004: return 'hex'
    return 'string'


def dxf_inventory(data):
    require(type(data) is bytes and 0 < len(data) <= MAX_SOURCE, 'DXF exceeds byte budget')
    binary = data.startswith(BINARY); position = len(BINARY) if binary else 3 if data.startswith(b'\xef\xbb\xbf') else 0
    tags = []; section = None; sections = []; expect_section = False; eof = False; records = {}
    def take(count):
        nonlocal position
        require(count >= 0 and position+count <= len(data), 'DXF payload is truncated')
        value = data[position:position+count]; position += count; return value
    def line():
        nonlocal position
        require(position < len(data), 'DXF value line is missing')
        match = LINE_END.search(data, position); end = match.start() if match else len(data)
        require(end-position <= 1<<20, 'DXF line exceeds budget')
        value = data[position:end]; position = match.end() if match else end; return value
    while position < len(data):
        start = position
        if binary:
            code = struct.unpack('<h', take(2))[0]
            if code == 255: code = struct.unpack('<h', take(2))[0]
            kind = group_kind(code)
            if kind == 'string':
                end = data.find(b'\x00', position); require(position <= end <= position+(1<<20), 'binary DXF string is unterminated or oversized')
                raw = take(end-position); take(1); value = raw
            elif kind == 'hex': raw = take(take(1)[0]); value = raw
            else:
                fmt, count = {'real':('<d',8),'int16':('<h',2),'int32':('<i',4),'int64':('<q',8),'bool':('<B',1)}[kind]
                raw = take(count); value = struct.unpack(fmt, raw)[0]
                require(kind != 'real' or math.isfinite(value), 'binary DXF contains a nonfinite number')
                require(kind != 'bool' or value in (0,1), 'binary DXF boolean would be coerced')
        else:
            spelling = line().strip()
            if not spelling: continue
            require(re.fullmatch(rb'[+-]?[0-9]{1,10}', spelling) is not None, 'DXF group code is malformed')
            code = int(spelling); require(-2**31 <= code < 2**31, 'DXF group code exceeds native range')
            raw = line(); kind = group_kind(code); value = raw
            if kind in ('real','int16','int32','int64','bool'):
                token = raw.strip()
                require(len(token) <= 128 and re.fullmatch(rb'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',token) is not None,
                        'DXF numeric spelling would require native repair')
                if kind == 'real':
                    value = float(token); require(math.isfinite(value), 'DXF number is not finite')
                else:
                    require(re.fullmatch(rb'[+-]?[0-9]+',token) is not None, 'DXF integer would require native truncation or conversion')
                    value = int(token); require(-2**63 <= value < 2**63, 'DXF integer exceeds native range')
                    if kind == 'bool': require(value in (0,1), 'DXF boolean would be coerced')
                    else:
                        bits = int(kind[3:]); require(-(2**(bits-1)) <= value < 2**bits if bits < 64 else -2**63 <= value < 2**63,
                                                    'DXF integer exceeds declared wire width')
            elif kind == 'hex':
                token = raw.strip(); require(len(token)%2 == 0 and re.fullmatch(rb'[0-9a-fA-F]*',token) is not None, 'DXF binary chunk would require repair')
                value = bytes.fromhex(token.decode('ascii'))
        require(len(tags) < MAX_TAGS, 'DXF tag budget exceeded')
        tags.append({'code':code,'kind':kind,'value':value,'span':[start,position]})
        if expect_section:
            require(code == 2 and type(value) is bytes and re.fullmatch(rb'[A-Z][A-Z0-9_]{0,63}',value.strip()) is not None, 'DXF section name is invalid')
            section = value.strip().decode('ascii'); require(section not in sections, 'DXF section is duplicated')
            sections.append(section); expect_section = False
        elif code != 0:
            require(section is not None or code == 999, 'DXF data lies outside a section')
        elif code == 0:
            require(type(value) is bytes, 'DXF record type is invalid'); marker = value.strip()
            if marker == b'SECTION': require(section is None, 'DXF sections overlap'); expect_section = True
            elif marker == b'ENDSEC': require(section is not None, 'DXF ENDSEC has no section'); section = None
            elif marker == b'EOF':
                require(section is None, 'DXF EOF appears inside a section'); eof = True; break
            else:
                require(section is not None, 'DXF record lies outside a section')
                require(re.fullmatch(rb'[A-Z0-9_$]+',marker) is not None and len(marker) <= 256, 'DXF record type is malformed')
                label = section+'/'+marker.decode('ascii'); records[label] = records.get(label,0)+1
    require(eof and not expect_section and sections, 'DXF has no complete section/EOF structure')
    require(not data[position:].strip(b' \t\r\n'), 'DXF has unowned bytes after EOF')
    return {'encoding':'binary-r13' if binary else 'text','tags':tags,'tag_count':len(tags),'sections':sections,
            'records':records,'numeric_repairs':[],'native_baseline_binding_required':True}


def inspect_bytes(data, kind):
    require(type(data) is bytes and 0 < len(data) <= MAX_SOURCE, 'source exceeds byte budget')
    require(kind in ('json','dxf'), 'source format must be explicit json or dxf')
    pending = ['complete-model-semantics','native-full-model-comparison','resource-and-font-admission','rendered-fidelity']
    if kind == 'json':
        document = strict_json(data); inventory = model_inventory(document); dxf = None
        if inventory['external_references']: pending.append('external-reference-policy')
        if inventory['unknown_fields']: pending.append('unknown-model-fields')
        if inventory['unresolved_constraints']: pending.append('unresolved-constraint-references')
    else:
        document = None; inventory = None; dxf = dxf_inventory(data)
        pending.extend(['native-baseline-binding','complete-dxf-semantics','dxf-codepage-and-escape-semantics'])
    return {'format':kind,'source_bytes':data,'source_sha256':sha(data),'source_size':len(data),
            'document':document,'inventory':inventory,'dxf':dxf,'pending_qualification':pending,'engine_admission_complete':False}


def read_source(path, kind):
    try: data = write_container.read_bytes(path)
    except ValueError as error: raise ValueError('CAD source cannot be read') from error
    return inspect_bytes(data, kind)
