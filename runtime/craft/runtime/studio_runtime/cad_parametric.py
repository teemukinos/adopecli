"""Editable rectangular CAD sketch recipe and independent dimension verification.

The caller supplies a pristine metric model from the receipt-bound native engine.
This module does not invoke the solver, render, open files or admit arbitrary CAD
sources. Runtime ownership, execution admission and publication remain separate.
"""
import copy
import json
import math

RECIPE = 'rectangular_panel_sketch'
VERSION = 1
TOLERANCE_MM = 1e-6


def require(condition, message):
    if not condition:
        raise ValueError('CAD panel '+message)


def dimension(value):
    require(type(value) in (int, float) and math.isfinite(value) and .1 <= value <= 10_000,
            'dimension must be finite, between 0.1 and 10000 millimetres')
    return value


def point(x, y):
    return {'x': float(x), 'y': float(y), 'z': 0.0}


def constraints(handles):
    def ref(handle, part): return {'handle': handle, 'sub': {'kind': part}}
    rows = []
    def add(kind, refs, name='', expr=''):
        rows.append({'id': len(rows)+1, 'kind': kind, 'refs': refs, 'name': name, 'expr': expr})
    for index in range(4):
        add('coincident', [ref(handles[index], 'end'), ref(handles[(index+1) % 4], 'start')])
    for index in (0, 2): add('horizontal', [ref(handles[index], 'whole')])
    for index in (1, 3): add('vertical', [ref(handles[index], 'whole')])
    add('fix', [ref(handles[0], 'start')])
    add({'distance': 'horizontal'}, [ref(handles[0], 'whole')], 'panel_width', 'width')
    add({'distance': 'vertical'}, [ref(handles[1], 'whole')], 'panel_height', 'height')
    return rows


def create(base, width, height):
    """Return complete editable native geometry and stable recipe selectors."""
    width = dimension(width); height = dimension(height)
    require(type(base) is dict and base.get('model') == [] and base.get('blocks') == {}
            and base.get('constraints') == [] and base.get('parametric', {}).get('parameters') == [],
            'requires an empty native metric drawing')
    require(base.get('header', {}).get('vars', {}).get('INSUNITS') == 4, 'requires millimetre units')
    start = base.get('handseed')
    require(type(start) is int and 0 < start < 2**64-4, 'native handle seed is invalid')
    handles = list(range(start, start+4)); drawing = copy.deepcopy(base)
    common = {'layer': '0', 'color': {'kind': 'byLayer'}, 'linetype': 'ByLayer', 'lineweight': 'byLayer',
              'ltscale': 1.0, 'transparency': 'byLayer', 'visible': True, 'thickness': 0.0,
              'extrusion': point(0.0, 0.0), 'plotStyle': 'ByLayer'}
    common['extrusion']['z'] = 1.0
    vertices = [point(0.0, 0.0), point(width, 0.0), point(width, height), point(0.0, height)]
    drawing['model'] = [{'handle': handle, 'common': copy.deepcopy(common),
                         'kind': {'type': 'line', 'a': copy.deepcopy(vertices[index]),
                                  'b': copy.deepcopy(vertices[(index+1) % 4])}}
                        for index, handle in enumerate(handles)]
    drawing['constraints'] = constraints(handles)
    drawing['parametric']['parameters'] = [
        {'name': 'width', 'expr': str(width), 'description': 'Panel width in millimetres'},
        {'name': 'height', 'expr': str(height), 'description': 'Panel height in millimetres'}]
    drawing['handseed'] = start+4
    return {'document': drawing, 'recipe': {'id': RECIPE, 'version': VERSION, 'units': 'mm',
            'entities': dict(zip(('bottom', 'right', 'top', 'left'), handles)),
            'fixed_origin': [0.0, 0.0], 'parameters': ['width', 'height']}}


def parameter_edit(document, name, value, *, expected_expression):
    """Change only the selected expression. A subsequent native solve is required."""
    value = dimension(value)
    require(name in ('width', 'height') and type(expected_expression) is str, 'parameter selector is invalid')
    drawing = copy.deepcopy(document)
    rows = drawing.get('parametric', {}).get('parameters', [])
    selected = [p for p in rows if p.get('name') == name]
    require(len(selected) == 1 and selected[0].get('expr') == expected_expression, 'parameter changed since inspection')
    selected[0]['expr'] = str(value)
    return drawing


def _same(before, after):
    options={'sort_keys':True,'ensure_ascii':True,'allow_nan':False,'separators':(',',':')}
    return json.dumps(before,**options)==json.dumps(after,**options)


def verify_geometry(document, solved, recipe, *, width, height):
    """Verify candidate geometry independently, without asserting native execution."""
    width = dimension(width); height = dimension(height)
    require(type(recipe) is dict and recipe.get('id') == RECIPE and type(recipe.get('version')) is int and recipe['version'] == VERSION
            and recipe.get('units') == 'mm' and recipe.get('fixed_origin') == [0.0, 0.0], 'recipe identity differs')
    owners = recipe.get('entities', {})
    require(type(owners) is dict and set(owners) == {'bottom', 'right', 'top', 'left'}, 'entity selectors differ')
    handles = [owners[name] for name in ('bottom', 'right', 'top', 'left')]
    require(all(type(h) is int and 0 < h < 2**64 for h in handles) and len(set(handles)) == 4, 'entity identities differ')
    require(type(solved) is dict and set(solved) == set(document), 'complete model fields differ')
    require(document.get('constraints') == constraints(handles), 'constraint inventory differs from recipe')
    for key in document:
        if key != 'model': require(_same(solved.get(key), document[key]), 'native solve changed unrelated '+key)
    require(document.get('header', {}).get('vars', {}).get('INSUNITS') == 4, 'model units changed')
    parameters = document.get('parametric', {}).get('parameters')
    require(type(parameters) is list and len(parameters) == 2
            and all(type(row) is dict for row in parameters) and [row.get('name') for row in parameters] == ['width', 'height'], 'parameter inventory differs')
    for row, expected in zip(parameters, (width, height)):
        expression = row.get('expr')
        require(type(expression) is str and len(expression) <= 64, 'recipe parameter must be a numeric literal')
        try: value = float(expression)
        except ValueError as error: raise ValueError('CAD panel parameter is not a numeric literal') from error
        require(math.isfinite(value) and value == expected, 'source parameter differs from requested dimension')
    original = document.get('model'); actual = solved.get('model')
    require(type(original) is list and type(actual) is list and len(original) == len(actual) == 4,
            'model entity inventory differs')
    corners = [point(0.0, 0.0), point(width, 0.0), point(width, height), point(0.0, height)]
    maximum = 0.0
    for index, (before, after, handle) in enumerate(zip(original, actual, handles)):
        require(type(before) is dict and type(after) is dict and type(before.get('handle')) is int and type(after.get('handle')) is int
                and before['handle'] == after['handle'] == handle, 'entity order or handle changed')
        require(set(before) == set(after) and set(after.get('kind', {})) == {'type', 'a', 'b'}
                and after['kind']['type'] == 'line', 'entity shape differs')
        for key in before:
            if key != 'kind': require(_same(before[key], after[key]), 'unrelated entity property changed')
        for end, expected in (('a', corners[index]), ('b', corners[(index+1) % 4])):
            value = after['kind'][end]
            require(type(value) is dict and set(value) == {'x', 'y', 'z'}, 'endpoint fields differ')
            for axis in ('x', 'y', 'z'):
                number = value[axis]
                require(type(number) in (int, float) and math.isfinite(number), 'endpoint is not finite')
                delta = abs(number-expected[axis]); maximum = max(maximum, delta)
                require(delta <= TOLERANCE_MM, 'independent endpoint measurement exceeds tolerance')
    require(_same(original[0]['kind']['a'], actual[0]['kind']['a']), 'fixed origin changed')
    changed_handles = [after['handle'] for before, after in zip(original, actual) if not _same(before['kind'], after['kind'])]
    return {'profile': RECIPE, 'version': VERSION, 'units': 'mm', 'width': width, 'height': height,
            'fixed_origin': [0.0, 0.0], 'changed_entities': changed_handles, 'maximum_endpoint_error_mm': maximum,
            'tolerance_mm': TOLERANCE_MM, 'unrelated_state_exact': True, 'closed_rectangle_verified': True,
            'general_manufacturing_qualified': False}


def verify(document, report, recipe, *, width, height):
    """Combine independent geometry checks with actual native solve observations."""
    require(type(report) is dict and type(report.get('schema_version')) is int and report['schema_version'] == 1
            and report.get('skipped') == [] and report.get('fixed_geometry_unchanged') is True
            and report.get('complete_native_cold_equal') is True, 'native solve is incomplete')
    measured = verify_geometry(document, report.get('document'), recipe, width=width, height=height)
    residuals = report.get('residuals')
    require(type(residuals) is list and len(residuals) == 11, 'residual inventory differs')
    require(all(type(row) is list and len(row) == 2 and type(row[0]) is int for row in residuals)
            and {row[0] for row in residuals} == set(range(1, 12)), 'residual identities differ')
    require(all(type(row[1]) in (int, float) and math.isfinite(row[1]) and abs(row[1]) <= TOLERANCE_MM for row in residuals),
            'constraint residual exceeds tolerance')
    moved = report.get('moved')
    require(type(moved) is list and all(type(handle) is int for handle in moved)
            and len(moved) == len(set(moved)) and set(moved) == set(measured['changed_entities']),
            'changed-entity report differs from complete geometry')
    dimensions = report.get('dimensions'); require(type(dimensions) is list and len(dimensions) == 2, 'dimension inventory differs')
    wanted = {10: ('panel_width', width), 11: ('panel_height', height)}
    require(all(type(row) is dict and type(row.get('id')) is int for row in dimensions)
            and {row['id'] for row in dimensions} == set(wanted), 'dimension identities differ')
    for row in dimensions:
        name, expected = wanted[row['id']]
        require(row.get('name') == name, 'dimension name differs')
        for key in ('target', 'measured'):
            value = row.get(key)
            require(type(value) in (int, float) and math.isfinite(value) and abs(value-expected) <= TOLERANCE_MM,
                    'reported dimension differs from independently requested value')
    return measured
