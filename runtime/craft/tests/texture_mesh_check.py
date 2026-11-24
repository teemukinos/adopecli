#!/usr/bin/env python3
"""Local bounded mesh admission checks and optional real native qualification."""
import argparse
import copy
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import texture_mesh as mesh, texture_document as document

OBJ = b'''o Panel
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 1
usemtl Panel
f 1/1/1 2/2/1 3/3/1 4/4/1
'''
POINTS = ((0., 0., 0.), (1., 0., 0.), (1., 1., 0.), (0., 1., 0.))
TRIANGLES = ((0, 1, 2), (0, 2, 3))
STL = b'local fixture'.ljust(80, b'\0') + struct.pack('<I', 2) + b''.join(
    struct.pack('<12fH', 0., 0., 1., *(c for i in face for c in POINTS[i]), 0) for face in TRIANGLES)
ASCII_STL = ('solid Panel\n' + ''.join('facet normal 0 0 1\nouter loop\n' + ''.join(
    'vertex ' + ' '.join(map(str, POINTS[i])) + '\n' for i in face) + 'endloop\nendfacet\n'
    for face in TRIANGLES) + 'endsolid Panel\n').encode()


def packed(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); root = args.output.resolve(); root.mkdir()
    checks = []; native_checks = []; started = time.monotonic()

    def check(label, valid, *, native=False):
        assert valid, label
        (native_checks if native else checks).append(label)

    def refused(label, action):
        try:
            action()
        except ValueError:
            checks.append(label)
        else:
            raise AssertionError('unexpected admission: ' + label)

    try:
        report = mesh.inspect_bytes('panel.obj', OBJ)
        check('OBJ quad preserves material and supplied UV policy', report['triangles'] == 2 and report['materials'] == ['Panel']
              and report['vertex_upper_bound'] == 4 and not report['uvs_generated'])
        negative = OBJ.replace(b'1/1/1 2/2/1 3/3/1 4/4/1', b'-4/-4/-1 -3/-3/-1 -2/-2/-1 -1/-1/-1')
        udim = OBJ + b'v 2 0 0\nv 3 0 0\nv 3 1 0\nv 2 1 0\nvt 2 0\nvt 3 0\nvt 3 1\nvt 2 1\nf 5/5/1 6/6/1 7/7/1 8/8/1\n'
        check('negative OBJ indices are bounded relative references', mesh.inspect_bytes('negative.obj', negative)['triangles'] == 2)
        simple = b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
        check('missing UVs require explicit generated-UV acceptance', mesh.inspect_bytes('simple.obj', simple)['requires_generated_uv_acceptance'])
        for label, data in [('ASCII', ASCII_STL), ('binary', STL), ('binary solid header', b'solid' + STL[5:])]:
            r = mesh.inspect_bytes('panel.stl', data)
            check(label + ' STL has two facets and declared generation policy', r['triangles'] == 2 and r['uvs_generated'] and r['normals_generated'])
        for label, data in [
            ('unknown external MTL', b'mtllib ../private.mtl\n' + OBJ), ('external call', b'call http://example.invalid/a.obj\n' + OBJ),
            ('ignored smoothing group', b's 1\n' + OBJ), ('ignored line primitive', OBJ + b'l 1 2\n'),
            ('invalid UTF8', OBJ + b'\xff'), ('control character', OBJ + b'\0'),
            ('inline comment ambiguity', OBJ.replace(b'usemtl Panel', b'usemtl Panel # comment')),
            ('native material scan tab mismatch', OBJ.replace(b'usemtl Panel', b'usemtl\tPanel')),
            ('empty face index', OBJ.replace(b'1/1/1', b'1/1/')),
            ('zero index', OBJ.replace(b'1/1/1', b'0/1/1')),
            ('positive absent index', OBJ.replace(b'1/1/1', b'5/1/1')),
            ('negative absent index', OBJ.replace(b'1/1/1', b'-5/1/1')),
            ('missing UV index', OBJ.replace(b'1/1/1', b'1/5/1')),
            ('mixed UV presence', OBJ.replace(b'1/1/1', b'1//1')),
            ('NaN', OBJ.replace(b'v 0 0 0', b'v NaN 0 0')),
            ('float overflow', OBJ.replace(b'v 0 0 0', b'v 1e100 0 0')),
            ('float lexical ambiguity', OBJ.replace(b'v 0 0 0', b'v 1_0 0 0')),
            ('zero normal', OBJ.replace(b'vn 0 0 1', b'vn 0 0 0')),
            ('UV outside supported tiles', OBJ.replace(b'vt 0 0', b'vt -1 0')),
            ('mixed vertex colors', OBJ.replace(b'v 0 0 0', b'v 0 0 0 1 0 0')),
            ('clamped color', simple.replace(b'v 0 0 0', b'v 0 0 0 2 0 0')),
            ('degenerate geometry', simple.replace(b'v 0 1 0', b'v 0 0 0')),
            ('nonplanar quad', OBJ.replace(b'v 0 1 0', b'v 0 1 1')),
            ('concave quad', OBJ.replace(b'v 1 1 0', b'v .25 .25 0')),
            ('self-crossing quad', OBJ.replace(b'1/1/1 2/2/1 3/3/1 4/4/1', b'1/1/1 3/3/1 2/2/1 4/4/1')),
            ('overlong record', b'#' + b'x' * mesh.MAX_LINE + b'\n' + OBJ),
        ]:
            refused(label, lambda data=data: mesh.inspect_bytes('bad.obj', data))
        for label, data in [
            ('binary trailing data', STL + b'x'), ('truncated binary', STL[:-1]),
            ('facet attribute data', STL[:-2] + b'\x01\0'), ('colored header', b'COLOR=' + STL[6:]),
            ('nonfinite position', STL[:96] + struct.pack('<f', float('nan')) + STL[100:]),
            ('ASCII missing end', ASCII_STL.replace(b'endsolid Panel', b'')),
            ('ASCII mismatched name', ASCII_STL.replace(b'endsolid Panel', b'endsolid Other')),
            ('ASCII ignored token', ASCII_STL.replace(b'outer loop', b'ignored token')),
            ('ASCII fourth corner', ASCII_STL.replace(b'endloop', b'vertex 2 2 2\nendloop')),
        ]:
            refused(label, lambda data=data: mesh.inspect_bytes('bad.stl', data))
        for extension in ('glb', 'gltf', 'fbx', 'dae', 'usdz', 'ply', 'abc'):
            refused('unqualified body ' + extension, lambda extension=extension: mesh.inspect_bytes('mesh.' + extension, OBJ))
        with patch.object(mesh, 'MAX_TRIANGLES', 1):
            refused('topology bound before native import', lambda: mesh.inspect_bytes('panel.obj', OBJ))
        with patch.object(mesh, 'MAX_AUTO_UV_TRIANGLES', 1):
            refused('automatic UV work bound', lambda: mesh.inspect_bytes('panel.stl', STL))
            check('bake geometry does not run automatic UV generation', mesh.inspect_bytes('high.stl', STL, role='highpoly')['triangles'] == 2)
        with patch.object(mesh, 'MAX_TOTAL_BYTES', len(OBJ)):
            refused('aggregate mesh bytes include bake meshes', lambda: mesh.inspect_members({'mesh.obj': OBJ, 'cage/c.obj': OBJ}, ['mesh.obj', 'cage/c.obj']))
        native = {'materials': ['Panel'], 'uv': {'triangles': 2, 'vertices': 4, 'materials': 1, 'uvsGenerated': False}}
        check('matching native report accepted', mesh.check_native(report, native)['triangles'] == 2)
        for field, value in [('triangles', 1), ('triangles', True), ('vertices', 5), ('materials', 2), ('uvsGenerated', True)]:
            changed = copy.deepcopy(native); changed['uv'][field] = value
            refused('native mismatch ' + field + repr(value), lambda changed=changed: mesh.check_native(report, changed))
        bake = mesh.inspect_members({'highpoly/detail.obj': OBJ, 'cage/cage.obj': OBJ}, ['highpoly/detail.obj', 'cage/cage.obj'])
        bake_reply = {'bakeMeshes': {'highPoly': [{'name': 'detail.obj', 'triangles': 2, 'parts': ['Panel']}],
                                    'cage': {'name': 'cage.obj', 'triangles': 2, 'parts': ['Panel']}}}
        check('complete native bake inventory accepted', mesh.check_native_bake(bake, bake_reply)['bake_meshes'] == 2)
        for label, edit in [
            ('skipped high-poly mesh', lambda v: v['bakeMeshes'].update(highPoly=[])),
            ('skipped cage', lambda v: v['bakeMeshes'].update(cage=None)),
            ('wrong cage topology', lambda v: v['bakeMeshes']['cage'].update(triangles=1)),
            ('renamed high-poly mesh', lambda v: v['bakeMeshes']['highPoly'][0].update(name='other.obj')),
            ('duplicated bake mesh', lambda v: v['bakeMeshes']['highPoly'].append(v['bakeMeshes']['highPoly'][0])),
        ]:
            changed = copy.deepcopy(bake_reply); edit(changed)
            refused(label, lambda changed=changed: mesh.check_native_bake(bake, changed))

        if args.engine:
            engine = args.engine.resolve(strict=True); home = root / 'home'; home.mkdir()
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(home), 'LANG': 'en_US.UTF-8',
                   'XDG_CONFIG_HOME': str(home), 'XDG_CACHE_HOME': str(home)}

            def run(*arguments):
                result = subprocess.run([str(engine), *map(str, arguments)], cwd=root, env=env,
                                        capture_output=True, text=True, timeout=60)
                with (root / 'commands.jsonl').open('a') as f:
                    f.write(json.dumps({'args': list(map(str, arguments)), 'exit_code': result.returncode,
                                        'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
                assert result.returncode == 0, result.stderr
                if arguments[0] == 'new':
                    assert not result.stdout.strip(), 'native new unexpectedly returned a response body'
                    return None
                return json.loads(result.stdout)

            def roundtrip(source, target):
                recipe = target.with_suffix('.recipe.json')
                recipe.write_text(json.dumps({'open': str(source), 'steps': [], 'save': str(target)}))
                reply = run('batch', recipe); assert reply['failed'] is None
                return document.read_native(target)

            def exported_geometry(source, target):
                run('run', source, 'file.exportMesh', json.dumps({'path': str(target), 'format': 'obj'}))
                positions = []; uv = []; normals = []; triangles = []
                for line in target.read_text().splitlines():
                    tokens = line.split()
                    if not tokens: continue
                    if tokens[0] == 'v': positions.append(tuple(map(float, tokens[1:4])))
                    if tokens[0] == 'vt': uv.append(tuple(map(float, tokens[1:3])))
                    if tokens[0] == 'vn': normals.append(tuple(map(float, tokens[1:4])))
                    if tokens[0] == 'f':
                        assert len(tokens) == 4
                        triangle = []
                        for token in tokens[1:]:
                            p, t, n = map(int, token.split('/'))
                            triangle.append((positions[p-1], uv[t-1], normals[n-1]))
                        triangles.append(triangle)
                return triangles

            for name, data in [('panel.obj', OBJ), ('negative.obj', negative), ('udim.obj', udim), ('binary.stl', STL), ('ascii.stl', ASCII_STL)]:
                source = root / name; source.write_bytes(data); preflight = mesh.inspect_bytes(name, data)
                info = run('info', source); mesh.check_native(preflight, info)
                check(name + ' actual topology/material/UV policy agrees', True, native=True)
                project = root / (source.stem + '.tcraft'); run('new', source, project, '--resolution', '128')
                admitted = document.read_native(project); embedded = 'mesh.' + source.suffix[1:]
                check(name + ' embeds exact original mesh bytes', admitted['members'][embedded] == data, native=True)
                if name == 'udim.obj':
                    check('imported OBJ retains UDIM hole in bounded atlas',
                          admitted['structure']['project']['texture_sets'][0]['uv_tiles'] == [1001, 1003]
                          and admitted['structure']['atlases'][0]['width'] == 384, native=True)
                mesh.check_native(preflight, run('info', project))
                cold_path = root / (source.stem + '-cold.tcraft'); cold = roundtrip(project, cold_path)
                check(name + ' cold project preserves all fields and mesh bytes',
                      document.check_preservation(admitted, cold)['embedded_bytes_preserved'], native=True)
                geometry = exported_geometry(project, root / (source.stem + '-export.obj'))
                expected = {tuple(sorted(POINTS[i] for i in face)) for face in TRIANGLES}
                if name == 'udim.obj':
                    expected |= {tuple(sorted((POINTS[i][0]+2, POINTS[i][1], POINTS[i][2]) for i in face)) for face in TRIANGLES}
                check(name + ' native geometry matches independent triangle oracle',
                      {tuple(sorted(c[0] for c in face)) for face in geometry} == expected, native=True)
                if name.endswith('.obj'):
                    check(name + ' supplied UVs and normals survive native import/export',
                          all(c[1] == c[0][:2] and c[2] == (0., 0., 1.) for face in geometry for c in face), native=True)
                cold_geometry = exported_geometry(cold_path, root / (source.stem + '-cold-export.obj'))
                check(name + ' cold geometry and generated/supplied attributes agree', geometry == cold_geometry, native=True)
                check(name + ' source remains unchanged', source.read_bytes() == data, native=True)

            base = document.read_native(root / 'panel.tcraft')
            source = root / 'bake-meshes.tcraft'
            source.write_bytes(packed({**base['members'], 'highpoly/detail.obj': OBJ, 'cage/cage.obj': OBJ}))
            admitted = document.read_native(source)
            cold = roundtrip(source, root / 'bake-meshes-cold.tcraft')
            check('primary, high-poly and cage bytes survive native cold save',
                  document.check_preservation(admitted, cold)['embedded_bytes_preserved'], native=True)
            check('compound mesh budget includes all three geometries', admitted['meshes']['triangles'] == 6, native=True)
            for path in (source, root / 'bake-meshes-cold.tcraft'):
                check('actual native bake mesh inventory agrees ' + path.name,
                      mesh.check_native_bake(admitted['meshes'], run('info', path))['bake_meshes'] == 2, native=True)

        result = {'passed': True, 'checks': len(checks), 'cases': checks, 'native_checks': len(native_checks),
                  'native_cases': native_checks, 'seconds': round(time.monotonic()-started, 4),
                  'qualified_formats': ['OBJ profile', 'binary STL profile', 'ASCII STL profile'],
                  'engine_admission_complete': False, 'runtime_available': False, 'goal_complete': False}
        (root / 'evidence.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: result[k] for k in ('passed', 'checks', 'native_checks', 'seconds')}))
    except Exception as error:
        (root / 'failure.json').write_text(json.dumps({'passed': False, 'cases': checks, 'native_cases': native_checks, 'error': str(error)}, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
