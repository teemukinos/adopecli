"""Bounded complete Sheets models and typed requests, without evaluation.

This preflight validates every model field against the pinned native profile.
Formula grammar/AST admission remains the fixed native parser's job, before its
calculator runs. Inspection, a hash or a claimed source pin never grants execution
rights or proves that a cached formula result was calculated.
"""
import copy
import hashlib
import json
import math
import os
import stat
from pathlib import Path
import re

from . import animate_format

MAX_JSON = 8 << 20
MAX_NODES = 200_000
FORMATS = {'General', '0', '0.00', '#,##0', '#,##0.00', '0%', '0.00%'}
ERRORS = {'Null','Div0','Value','Ref','Name','Num','NA','GettingData','Spill','Calc','Circ','Python','Busy','Timeout','Blocked'}


def require(condition, message):
    if not condition: raise ValueError('Sheets '+message)


def sha(data):
    require(type(data) is bytes, 'source must be immutable bytes'); return hashlib.sha256(data).hexdigest()


def encoded(value):
    try: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as error: raise ValueError('Sheets value cannot be encoded') from error


def strict_json(data):
    require(type(data) is bytes and 0 < len(data) <= MAX_JSON, 'JSON exceeds byte budget')
    try: animate_format._preflight(data, MAX_NODES)
    except ValueError as error: raise ValueError('Sheets JSON preflight refused: '+str(error)) from error
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'JSON contains duplicate keys'); out[key] = value
        return out
    def integer(token):
        require(len(token.lstrip('-')) <= 20, 'JSON integer exceeds native range')
        number = int(token); require(-2**63 <= number < 2**64, 'JSON integer exceeds native range'); return number
    def floating(token):
        number = float(token); require(math.isfinite(number), 'JSON number is not finite'); return number
    def constant(_): raise ValueError('Sheets JSON number is not finite')
    try: value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_int=integer, parse_float=floating, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error: raise ValueError('Sheets JSON is malformed: '+str(error)) from error
    pending = [value]; count = 0
    while pending:
        item = pending.pop(); count += 1; require(count <= MAX_NODES, 'JSON exceeds node budget')
        if type(item) is dict:
            for key in item: text(key, 256, 'JSON key')
            pending.extend(item.values())
        elif type(item) is list: pending.extend(item)
        elif type(item) is str: text(item, 16_384, 'JSON text')
    return value


def text(value, maximum, label):
    require(type(value) is str and not any(0xd800 <= ord(c) <= 0xdfff for c in value), label+' is invalid Unicode')
    require(len(value.encode('utf-8')) <= maximum, label+' exceeds byte budget'); return value


def fields(value, names, label):
    require(type(value) is dict and set(value) == set(names), label+' fields differ')


def same(value, expected, label):
    require(encoded(value) == encoded(expected), label+' differs from the supported native profile')


def baseline():
    data = Path(__file__).with_name('sheets_base.json').read_bytes()
    require(sha(data) == BASE_SHA256, 'native baseline fixture changed')
    return strict_json(data)


def number(value, label):
    require(type(value) in (int, float), label+' must be numeric data')
    try: numeric = float(value)
    except (OverflowError, ValueError) as error: raise ValueError('Sheets '+label+' exceeds binary64') from error
    require(math.isfinite(numeric), label+' must be finite numeric data')
    require(type(value) is float or int(numeric) == value, label+' would lose integer precision in native binary64')


def address(value):
    require(type(value) is str and re.fullmatch(r'\$?[A-Za-z]{1,2}\$?[1-9][0-9]{0,2}', value), 'cell address is invalid')
    clean = value.replace('$','').upper(); match = re.fullmatch(r'([A-Z]+)([0-9]+)', clean)
    col = 0
    for c in match[1]: col = col*26+ord(c)-64
    row = int(match[2]); require(1 <= row <= 512 and 1 <= col <= 64, 'cell exceeds supported grid')
    return row-1, col-1


def edits(value):
    require(type(value) is list and 1 <= len(value) <= 1024, 'expected 1..1024 cell edits')
    result = copy.deepcopy(value)
    for item in result:
        require(type(item) is dict and {'sheet','cell'} <= set(item) <= {'sheet','cell','value','formula','format'}, 'edit fields differ')
        require(type(item['sheet']) is int and 0 <= item['sheet'] < 8, 'edit sheet index invalid'); address(item['cell'])
        require(bool(set(item) & {'value','formula','format'}) and not {'value','formula'} <= set(item), 'edit must change content or format without conflicting content')
        if 'value' in item:
            v = item['value']; require(v is None or type(v) in (bool,int,float,str), 'cell value is not scalar')
            if type(v) is str: text(v, 16384, 'cell text')
            elif type(v) in (int,float): number(v, 'cell number')
        if 'formula' in item:
            text(item['formula'], 2048, 'formula'); require(bool(item['formula']), 'formula is empty')
        if 'format' in item:
            fmt = item['format']; require(type(fmt) is dict and bool(fmt) and set(fmt) <= {'bold','italic','number_format'}, 'format fields differ')
            for key, v in fmt.items():
                if key in ('bold','italic'): require(type(v) is bool, key+' must be boolean')
                else: require(type(v) is str and v in FORMATS, 'number format is unsupported')
    require(len(encoded(result)) <= MAX_JSON, 'edit request exceeds byte budget')
    return result


def inspect_bytes(data):
    model = strict_json(data); defaults = baseline(); fields(model, defaults, 'workbook')
    for key in set(defaults)-{'sheets','styles','active_sheet'}: same(model[key], defaults[key], 'workbook '+key)
    sheets = model['sheets']; require(type(sheets) is list and 1 <= len(sheets) <= 8, 'expected 1..8 sheets')
    require(type(model['active_sheet']) is int and 0 <= model['active_sheet'] < len(sheets), 'active sheet invalid')
    fields(model['styles'], ('styles',), 'style table'); styles = model['styles']['styles']
    require(type(styles) is list and 1 <= len(styles) <= 256, 'style table exceeds budget')
    for style in styles:
        base = copy.deepcopy(defaults['styles']['styles'][0]); fields(style, base, 'style'); fields(style['font'], base['font'], 'font')
        for key in ('bold','italic'):
            require(type(style['font'][key]) is bool, 'font flag is not boolean'); base['font'][key] = style['font'][key]
        require(type(style['num_fmt']) is str and style['num_fmt'] in FORMATS, 'number format is unsupported'); base['num_fmt'] = style['num_fmt']
        same(style, base, 'style')
    count = formulas = 0; names = set(); inventory = []
    for index, sheet in enumerate(sheets):
        base = defaults['sheets'][0]; fields(sheet, base, 'sheet')
        name = text(sheet['name'], 124, 'sheet name')
        require(1 <= len(name) <= 31 and not any(c in name for c in ':\\/?*[]') and not name.startswith("'") and not name.endswith("'"), 'sheet name invalid')
        # The native comparison is ASCII case-insensitive. Preserve Unicode names.
        folded = name.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))
        require(folded not in names and folded != 'history', 'sheet name duplicates or uses reserved name'); names.add(folded)
        for key in set(base)-{'name','cells'}: same(sheet[key], base[key], 'sheet '+key)
        store = sheet['cells']; fields(store, ('bands','len'), 'cell store')
        require(type(store['len']) is int and 0 <= store['len'] <= 10000 and type(store['bands']) is dict, 'cell store count/bands invalid')
        total = 0
        for band, body in store['bands'].items():
            require(re.fullmatch(r'[0-7]', band) is not None, 'cell band invalid'); fields(body, ('rows',), 'cell band')
            require(type(body['rows']) is dict and bool(body['rows']), 'cell band must contain rows')
            for row, columns in body['rows'].items():
                require(re.fullmatch(r'0|[1-9][0-9]{0,2}', row) is not None and int(row) < 512 and int(row)//64 == int(band), 'cell row/band differs')
                require(type(columns) is dict and bool(columns), 'cell row must contain cells')
                for col, cell in columns.items():
                    require(re.fullmatch(r'0|[1-9][0-9]?', col) is not None and int(col) < 64, 'cell column exceeds grid')
                    fields(cell, ('value','formula','style'), 'cell'); require(type(cell['style']) is int and 0 <= cell['style'] < len(styles), 'cell style invalid')
                    v = cell['value']; require(type(v) is dict and type(v.get('t')) is str, 'cell value tag invalid'); kind = v['t']
                    fields(v, ('t',) if kind == 'Empty' else ('t','v'), 'cell value')
                    if kind == 'Number': require(type(v['v']) is float and math.isfinite(v['v']), 'native numeric value must be finite binary64')
                    elif kind == 'Text': text(v['v'], 16384, 'cell text')
                    elif kind == 'Bool': require(type(v['v']) is bool, 'cell boolean invalid')
                    elif kind == 'Error': require(type(v['v']) is str and v['v'] in ERRORS, 'cell error invalid')
                    else: require(kind == 'Empty', 'array or unknown value is unsupported')
                    if cell['formula'] is not None:
                        f = cell['formula']; fields(f, ('text','array'), 'formula'); text(f['text'], 2048, 'formula'); require(f['array'] is None, 'array formula unsupported'); formulas += 1
                    require(not (kind == 'Empty' and cell['formula'] is None and cell['style'] == 0), 'default blank cell is not canonical sparse storage')
                    total += 1; count += 1; require(count <= 10000 and formulas <= 1024, 'cell/formula budget exceeded')
                    inventory.append((index, int(row), int(col), cell))
        require(total == store['len'], 'native cell count differs')
    return {'document': model, 'sha256': sha(data), 'bytes': len(data), 'cells': inventory, 'cell_count': count,
            'formula_count': formulas, 'sheet_names': [s['name'] for s in sheets], 'profile': 'cells-and-formulas-v1',
            'native_admission_required': True, 'calculation_verified': False}

BASE_SHA256 = 'e6eba99a981a063871ac6cfa5b40656f68a46f9c32c46cec7b2bfb4b6e815763'


def read_bytes(path, *, allow_empty=False):
    """Read an owned regular file without following its final symlink."""
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and (0 if allow_empty else 1) <= before.st_size <= MAX_JSON, 'native file exceeds regular-file byte budget')
            data = stream.read(MAX_JSON+1); after = os.fstat(stream.fileno())
            require(len(data) == before.st_size and (before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
                    (after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'native file changed during snapshot')
            return data
    except OSError as error: raise ValueError('Sheets native file cannot be read') from error
