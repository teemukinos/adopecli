"""Bounded, self-contained OBJ and STL mesh admission for Texture.

Other native mesh formats remain unqualified. Original mesh bytes are retained.
Native import must agree with the geometry/material/UV report; successful parsing
alone does not establish fidelity or authorize a public runtime operation.
"""
import hashlib
import math
import re
import struct

from .texture_structure import require

MAX_BYTES = 32 << 20
MAX_TOTAL_BYTES = 64 << 20
MAX_TRIANGLES = 100_000
MAX_VERTICES = 300_000
MAX_AUTO_UV_TRIANGLES = 10_000
MAX_MESHES = 64
MAX_MATERIALS = 16
MAX_PARTS = 4096
MAX_LINE = 4096
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')
INDEX = re.compile(r'[+-]?[0-9]+\Z')


def _number(value, limit=1_000_000):
    require(len(value) <= 48 and NUMBER.fullmatch(value), 'mesh number syntax is unsupported')
    number = float(value)
    require(math.isfinite(number) and abs(number) <= limit, 'mesh number exceeds its finite range')
    return struct.unpack('<f', struct.pack('<f', number))[0]


def _text(data):
    try:
        text = data.decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError('Texture mesh text must use the qualified ASCII encoding') from error
    require(all(c in '\t\r\n' or 32 <= ord(c) <= 126 for c in text), 'mesh contains control characters')
    return text


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _polygon(points):
    """Refuse collapsed geometry and non-convex/non-planar fan triangulation."""
    normal = _cross(_sub(points[1], points[0]), _sub(points[2], points[0]))
    area = math.sqrt(_dot(normal, normal))
    require(area > 1e-12, 'mesh contains a degenerate triangle')
    if len(points) == 3:
        return
    scale = max(math.dist(p, points[0]) for p in points)
    require(all(abs(_dot(_sub(p, points[0]), normal)) <= area * max(scale * 1e-5, 1e-7) for p in points),
            'nonplanar mesh polygons require explicit triangulation')
    # Every other vertex must lie strictly inside every directed polygon edge.
    # This also rejects repeated vertices, collinear corners and self crossings.
    for i, point in enumerate(points):
        nxt = (i + 1) % len(points); edge = _sub(points[nxt], point)
        require(all(_dot(_cross(edge, _sub(other, point)), normal) > 0
                    for j, other in enumerate(points) if j not in (i, nxt)),
                'non-convex mesh polygons require explicit triangulation')


def _obj(data):
    positions = []; uvs = []; normals = []; colors = []
    materials = []; parts = set(); triangles = corners = faces = 0
    material = 'Default'; part = ''; corner_layout = None; declared_materials = set()

    def index(value, count):
        require(len(value) <= 12 and INDEX.fullmatch(value), 'OBJ index syntax is invalid')
        number = int(value); result = number - 1 if number > 0 else count + number
        require(number != 0 and 0 <= result < count, 'OBJ index references an absent vertex attribute')
        return result

    for line in _text(data).splitlines():
        require(len(line) <= MAX_LINE, 'mesh line exceeds its budget')
        if line.lstrip().startswith('#'):
            continue
        require('#' not in line, 'inline OBJ comments are not qualified')
        tokens = line.split('#', 1)[0].split()
        if not tokens:
            continue
        key, values = tokens[0], tokens[1:]
        if key in ('v', 'vt', 'vn'):
            expected = {'v': (3, 6), 'vt': (2,), 'vn': (3,)}[key]
            require(len(values) in expected, 'OBJ vertex attribute arity is unsupported')
            target = {'v': positions, 'vt': uvs, 'vn': normals}[key]
            require(len(target) < MAX_VERTICES, 'mesh vertex attributes exceed their budget')
            numbers = [_number(value) for value in values]
            if key == 'v':
                colors.append(len(values) == 6)
                require(len(values) == 3 or all(0 <= value <= 1 for value in numbers[3:]), 'OBJ vertex color would be clamped')
            if key == 'vn':
                require(_dot(numbers, numbers) > 1e-12, 'OBJ normal is zero or too small')
            if key == 'vt':
                require(0 <= numbers[0] <= 10 and 0 <= numbers[1] <= 100, 'OBJ UVs lie outside qualified UDIM bounds')
            target.append(tuple(numbers[:3] if key != 'vt' else numbers))
        elif key in ('o', 'g', 'usemtl'):
            require(len(values) == 1 and len(values[0]) <= 120, 'OBJ part/material name is unsupported')
            if key == 'usemtl':
                # The pinned native synthetic-MTL name scan requires a literal
                # space after usemtl. Refuse tab-only syntax it would misread.
                require(line.strip().startswith('usemtl '), 'OBJ material separator disagrees with native name scanning')
                material = values[0]; declared_materials.add(material)
                require(len(declared_materials) <= MAX_MATERIALS, 'mesh material declarations exceed their budget')
            else:
                part = values[0]
        elif key == 'f':
            require(3 <= len(values) <= 64, 'OBJ polygon corner count is unsupported')
            triangles += len(values) - 2; corners += len(values); faces += 1
            require(triangles <= MAX_TRIANGLES and corners <= MAX_VERTICES, 'mesh topology exceeds its budget')
            face = []
            for value in values:
                fields = value.split('/')
                require(1 <= len(fields) <= 3 and fields[0], 'OBJ corner syntax is invalid')
                layout = (len(fields) > 1 and bool(fields[1]), len(fields) > 2 and bool(fields[2]))
                require(fields[-1] and (len(fields) != 2 or fields[1]), 'OBJ corner has an empty trailing index')
                if corner_layout is None:
                    corner_layout = layout
                require(layout == corner_layout, 'mixed OBJ UV/normal presence would trigger native recovery')
                face.append(positions[index(fields[0], len(positions))])
                if layout[0]:
                    index(fields[1], len(uvs))
                if layout[1]:
                    index(fields[2], len(normals))
            _polygon(face)
            if material not in materials:
                materials.append(material)
            parts.add((material, part))
            require(len(materials) <= MAX_MATERIALS and len(parts) <= MAX_PARTS, 'mesh materials or parts exceed their budget')
        else:
            # Includes mtllib/maplib/call/csh, points/lines, smoothing groups and
            # freeform surfaces: native import ignores or changes these semantics.
            raise ValueError('Texture OBJ record is not qualified: ' + key)
    require(faces > 0, 'OBJ has no faces')
    require(not any(colors) or all(colors), 'mixed OBJ vertex colors would trigger native recovery')
    return {'format': 'OBJ', 'triangles': triangles, 'vertex_upper_bound': corners if corner_layout[0] else 3 * triangles,
            'materials': materials, 'parts': len(parts), 'uvs_generated': not corner_layout[0],
            'normals_generated': not corner_layout[1], 'vertex_colors': any(colors)}


def _stl(data):
    count = struct.unpack_from('<I', data, 80)[0] if len(data) >= 84 else None
    if count is not None and 84 + count * 50 == len(data):
        require(0 < count <= MAX_TRIANGLES, 'STL triangle count exceeds its budget')
        require(b'COLOR=' not in data[:80], 'colored binary STL is not qualified')
        for i in range(count):
            values = struct.unpack_from('<12fH', data, 84 + i * 50)
            require(all(math.isfinite(v) and abs(v) <= 1_000_000 for v in values[:12]), 'STL contains invalid finite geometry')
            require(values[12] == 0, 'STL facet attributes would be ignored')
            _polygon([values[3:6], values[6:9], values[9:12]])
        encoding = 'binary'
    else:
        # Native ASCII STL skips arbitrary words and accepts unfinished facets.
        # Admit an exact grammar instead, without silently repairing the source.
        lines = []
        for line in _text(data).splitlines():
            require(len(line) <= MAX_LINE, 'mesh line exceeds its budget')
            if line.strip():
                lines.append(line.strip().split())
        require(len(lines) >= 2 and lines[0][0] == 'solid' and lines[-1][0] == 'endsolid', 'ASCII STL solid is incomplete')
        require(lines[0][1:] == lines[-1][1:], 'ASCII STL solid names disagree')
        require((len(lines) - 2) % 7 == 0, 'ASCII STL facets are incomplete')
        count = (len(lines) - 2) // 7
        require(0 < count <= MAX_TRIANGLES, 'STL triangle count exceeds its budget')
        for i in range(count):
            facet = lines[1 + 7*i:8 + 7*i]
            require(len(facet[0]) == 5 and facet[0][:2] == ['facet', 'normal'] and facet[1] == ['outer', 'loop']
                    and facet[5:] == [['endloop'], ['endfacet']], 'ASCII STL facet grammar is invalid')
            for value in facet[0][2:]:
                _number(value)
            points = []
            for row in facet[2:5]:
                require(len(row) == 4 and row[0] == 'vertex', 'ASCII STL vertex grammar is invalid')
                points.append(tuple(_number(v) for v in row[1:]))
            _polygon(points)
        encoding = 'ascii'
    return {'format': 'STL', 'encoding': encoding, 'triangles': count, 'vertex_upper_bound': count * 3,
            'materials': ['Default'], 'parts': 1, 'uvs_generated': True, 'normals_generated': True, 'vertex_colors': False}


def inspect_bytes(name, data, *, role='primary'):
    require(type(name) is str and type(data) is bytes and 0 < len(data) <= MAX_BYTES, 'mesh bytes exceed their budget')
    require(role in ('primary', 'highpoly', 'cage'), 'mesh role is invalid')
    extension = name.rsplit('.', 1)[-1].lower()
    require(extension in ('obj', 'stl'), 'mesh format has not passed body admission: ' + extension)
    report = _obj(data) if extension == 'obj' else _stl(data)
    if role == 'primary' and report['uvs_generated']:
        require(report['triangles'] <= MAX_AUTO_UV_TRIANGLES, 'automatic UV generation exceeds its triangle budget')
    return {**report, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'role': role,
            'external_references': [], 'requires_generated_uv_acceptance': role == 'primary' and report['uvs_generated']}


def inspect_members(members, names):
    require(len(names) <= MAX_MESHES, 'embedded mesh count exceeds its budget')
    reports = {}; total_bytes = triangles = vertices = 0
    for name in names:
        role = 'primary' if name.startswith('mesh.') else name.split('/', 1)[0]
        report = inspect_bytes(name, members[name], role=role)
        total_bytes += report['bytes']; triangles += report['triangles']; vertices += report['vertex_upper_bound']
        require(total_bytes <= MAX_TOTAL_BYTES and triangles <= MAX_TRIANGLES and vertices <= MAX_VERTICES,
                'aggregate embedded meshes exceed their budget')
        reports[name] = report
    return {'members': reports, 'bytes': total_bytes, 'triangles': triangles, 'vertex_upper_bound': vertices}


def check_native(preflight, inspection):
    """Compare actual private CLI info with admitted topology and UV policy.

Warnings, bounds, attribute fidelity and native cold preservation still need
their own checks. This is not a general authorization for generated UVs.
"""
    uv = inspection.get('uv') if type(inspection) is dict else None
    require(type(uv) is dict, 'native mesh inspection has no UV report')
    for key, expected in (('triangles', preflight['triangles']), ('materials', len(preflight['materials']))):
        require(type(uv.get(key)) is int and uv[key] == expected, 'native mesh topology disagrees with admission')
    require(type(uv.get('vertices')) is int and 0 < uv['vertices'] <= preflight['vertex_upper_bound'],
            'native mesh vertices exceed the admitted bound')
    require(type(uv.get('uvsGenerated')) is bool and uv['uvsGenerated'] == preflight['uvs_generated'],
            'native UV generation disagrees with admission')
    mesh = inspection.get('mesh', inspection)
    require(type(mesh) is dict and mesh.get('materials') == preflight['materials'], 'native mesh material names disagree with admission')
    return {'triangles': uv['triangles'], 'vertices': uv['vertices'], 'materials': uv['materials'],
            'uvs_generated': uv['uvsGenerated']}


def check_native_bake(preflight, inspection):
    """Reject native recovery that logs and skips an unreadable bake mesh."""
    bake = inspection.get('bakeMeshes') if type(inspection) is dict else None
    require(type(bake) is dict and type(bake.get('highPoly')) is list, 'native bake mesh report is malformed')
    expected = {name: value for name, value in preflight['members'].items() if value['role'] != 'primary'}
    reported = {}; high = bake['highPoly']; cage = bake.get('cage')
    require(len(high) <= MAX_MESHES, 'native bake mesh report exceeds its budget')
    for directory, records in (('highpoly', high), ('cage', [] if cage is None else [cage])):
        for record in records:
            require(type(record) is dict and type(record.get('name')) is str, 'native bake mesh entry is malformed')
            name = directory + '/' + record['name']
            require(name not in reported and name in expected, 'native bake mesh inventory disagrees with admission')
            admitted = expected[name]
            require(type(record.get('triangles')) is int and record['triangles'] == admitted['triangles']
                    and type(record.get('parts')) is list and len(record['parts']) == admitted['parts'],
                    'native bake mesh topology disagrees with admission')
            reported[name] = record
    require(set(reported) == set(expected), 'native reader skipped an admitted bake mesh')
    return {'bake_meshes': len(reported)}
