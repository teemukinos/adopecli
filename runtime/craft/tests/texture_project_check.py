#!/usr/bin/env python3
"""Local project-setting admission, cold preservation and bounded CPU bake proof."""
import argparse
import copy
import io
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import time
from unittest.mock import patch
import zipfile
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from texture_structure_check import project
from studio_runtime import texture_project as settings, texture_structure, texture_document as document


def packed(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items(): archive.writestr(name, value)
    return out.getvalue()


def small_bake():
    bake = copy.deepcopy(settings.DEFAULT_BAKE); bake['common']['resolution'] = 'R16'
    bake['high_poly']['use_low_as_high'] = True
    for name, config in bake['maps'].items(): config['is_enabled'] = name in ('normal', 'ao')
    bake['maps']['ao']['parameters']['rays']['rays'] = 1
    return bake


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path); parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); root = args.output.resolve(); root.mkdir(); checks = []; native_checks = []; started = time.monotonic(); timings = []
    def check(label, valid, native=False):
        assert valid, label
        (native_checks if native else checks).append(label)
    def inspect(p): return settings.inspect(texture_structure.inspect_json(json.dumps(p).encode()))
    def budget(p, **kwargs):
        structure = texture_structure.inspect_json(json.dumps(p).encode())
        return settings.bake_budget(structure, settings.inspect(structure), **kwargs)
    def refused(label, action):
        try: action()
        except ValueError: checks.append(label)
        else: raise AssertionError('unexpected admission: ' + label)
    def base():
        p = project(); p['display'] = copy.deepcopy(settings.DEFAULT_DISPLAY); p['texture_sets'][0]['bake'] = copy.deepcopy(settings.DEFAULT_BAKE)
        return p
    def mutation(label, edit):
        p = base(); edit(p); refused(label, lambda: inspect(p))
    try:
        p = base(); original = copy.deepcopy(p); report = inspect(p)
        check('validation preserves input and does not authorize bake', p == original and not report['bake_authorized'])
        partial = project(); report = inspect(partial)
        check('missing native defaults are reported without editing source', report['missing_defaults'] and partial == project())
        for label, edit in [
            ('unknown root metadata', lambda p: p.update(future=True)),
            ('unknown display metadata', lambda p: p['display'].update(future=True)),
            ('unknown texture-set metadata', lambda p: p['texture_sets'][0].update(future=True)),
            ('unknown normal convention', lambda p: p.update(normal_format='Unknown')),
            ('unknown environment', lambda p: p['display'].update(environment='Unknown')),
            ('numeric display boolean', lambda p: p['display'].update(taa=1)),
            ('zero field of view', lambda p: p['display'].update(fov=0)),
            ('singular camera distance', lambda p: p.update(cameras=[{**settings.CAMERA_DEFAULT, 'distance': 0.}])),
            ('singular camera pole', lambda p: p.update(cameras=[{**settings.CAMERA_DEFAULT, 'pitch': math.pi/2}])),
            ('unknown camera metadata', lambda p: p.update(cameras=[{**settings.CAMERA_DEFAULT, 'future': 0}])),
            ('too many cameras', lambda p: p.update(cameras=[{}] * 65)),
            ('invalid material index', lambda p: p['texture_sets'][0].update(material=True)),
            ('unknown texture mixing', lambda p: p['texture_sets'][0].update(normal_mixing='Future')),
        ]: mutation(label, edit)
        for path, value in [
            (('common', 'resolution'), 'R17'), (('common', 'resolution_height'), False),
            (('common', 'antialiasing'), 'Subsampling16x16'), (('common', 'dilation'), 129),
            (('high_poly', 'match_mode'), 'Future'), (('cage', 'kind'), 'Future'),
            (('cage', 'max_frontal'), -1.), (('skew', 'edge_distance'), 2.),
            (('maps', 'normal', 'parameters'), {}), (('maps', 'ao', 'parameters', 'rays', 'rays'), 0),
            (('maps', 'ao', 'parameters', 'rays', 'rays'), 4097),
            (('maps', 'ao', 'parameters', 'rays', 'min_distance'), 2.),
            (('maps', 'ao', 'parameters', 'rays', 'distribution'), 'Future'),
            (('maps', 'curvature', 'parameters', 'normal_map', 'details'), -1.),
            (('maps', 'position', 'parameters', 'axis'), 'Future'),
            (('maps', 'height', 'parameters', 'scaling_divisor'), 0.),
            (('maps', 'thickness', 'parameters', 'normalization'), 'Future'),
        ]:
            p = base(); target = p['texture_sets'][0]['bake']
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            refused('invalid bake parameter ' + '/'.join(path) + repr(value), lambda p=p: inspect(p))
        p = base(); del p['texture_sets'][0]['bake']['maps']['ao']['parameters']
        refused('incomplete MapSettings cannot enter native recovery', lambda: inspect(p))
        p = base(); p['texture_sets'][0]['bake']['maps']['curvature']['parameters']['mesh'].update(auto_tonemapping=False, value_min=1., value_max=-1.)
        refused('manual curvature range reversed', lambda: inspect(p))
        p = base(); p['texture_sets'][0]['bake']['common']['resolution'] = 'R8192'
        check('large saved bake settings remain inert import metadata', inspect(p)['bakes'][0]['common']['resolution'] == 'R8192')
        refused('large unrequested metadata cannot authorize execution', lambda: budget(p))
        p = base(); p['texture_sets'][0]['bake'] = small_bake(); plan = budget(p)
        check('bounded bake counts output bytes samples and nominal rays',
              plan['output_bytes'] == 4144 and plan['samples'] == 256 and plan['nominal_ray_work'] == 512 and not plan['execution_authorized'])
        p['texture_sets'][0]['bake']['common']['antialiasing'] = 'Subsampling8x8'
        check('antialiasing squares its per-axis count', budget(p)['samples'] == 256 * 64)
        p['texture_sets'][0]['bake']['common'].update(antialiasing='None', resolution_height='R32')
        p['texture_sets'][0]['uv_tiles'] = [1001, 1003]; p['texture_sets'][0]['bake_excluded_tiles'] = [1003]
        plan = budget(p)
        check('rectangular bake includes atlas holes and excluded allocation', plan['outputs'][0]['width'] == 48 and plan['outputs'][0]['height'] == 32 and plan['samples'] == 1536)
        p['texture_sets'][0]['bake_excluded_tiles'] = [1001, 1003]
        refused('all excluded bake tiles produce no job', lambda: budget(p))
        p = base(); p['texture_sets'][0]['bake'] = small_bake(); p['texture_sets'][0]['bake']['cage']['kind'] = 'CustomFile'
        refused('custom cage must be available to bake', lambda: budget(p))
        check('admitted cage permits planning only', not budget(p, cage_available=True)['execution_authorized'])
        for selection in ([0, 0], [1], [True], []): refused('invalid bake selection ' + repr(selection), lambda selection=selection: budget(p, texture_sets=selection))
        p['texture_sets'][0]['bake']['cage']['kind'] = 'DistanceBased'
        with patch.object(settings, 'MAX_BAKE_WORK', 511): refused('bake work boundary enforced', lambda: budget(p))
        with patch.object(settings, 'MAX_BAKE_SAMPLES', 255): refused('bake sample boundary enforced', lambda: budget(p))
        with patch.object(settings, 'MAX_PIXEL_BYTES', 4143): refused('bake byte boundary enforced', lambda: budget(p))

        if args.engine:
            engine = args.engine.resolve(strict=True); home = root / 'home'; home.mkdir()
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(home), 'LANG': 'en_US.UTF-8', 'XDG_CONFIG_HOME': str(home), 'XDG_CACHE_HOME': str(home)}
            def run(*arguments):
                start = time.monotonic(); result = subprocess.run([str(engine), *map(str, arguments)], cwd=root, env=env, capture_output=True, text=True, timeout=60)
                timings.append({'operation': arguments[0], 'seconds': round(time.monotonic()-start, 5)})
                with (root/'commands.jsonl').open('a') as f: f.write(json.dumps({'args': list(map(str, arguments)), 'code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})+'\n')
                assert result.returncode == 0, result.stderr
                return json.loads(result.stdout) if arguments[0] in ('batch', 'bake') else result.stdout
            def roundtrip(source, target):
                recipe = target.with_suffix('.recipe.json'); recipe.write_text(json.dumps({'open': str(source), 'steps': [], 'save': str(target)}))
                reply = run('batch', recipe); assert reply['failed'] is None
                return document.read_native(target)
            seed = root/'seed.tcraft'; run('new', 'builtin:plane', seed, '--resolution', '128'); original = document.read_native(seed)
            native_project = original['structure']['project']
            check('pinned defaults match actual native writer', native_project['display'] == settings.DEFAULT_DISPLAY and native_project['texture_sets'][0]['bake'] == settings.DEFAULT_BAKE, True)
            check('actual native document has no missing setting defaults', not original['project_semantics']['missing_defaults'], True)
            updated = copy.deepcopy(native_project)
            updated['display'].update(environment='Night', env_opacity=.5, env_exposure=1., env_rotation=90., tone_mapping='Linear', fov=60.,
                                      dof={'enabled': True, 'focusDistance': 3., 'aperture': .025})
            updated['cameras'] = [{**settings.CAMERA_DEFAULT, 'name': 'Saved view', 'yaw': .5, 'pitch': .25, 'fov': 60., 'ortho': True}]
            updated['texture_sets'][0]['bake'] = small_bake()
            configured = root/'configured.tcraft'; configured.write_bytes(packed({**original['members'], 'project.json': json.dumps(updated).encode()}))
            admitted = document.read_native(configured); cold = roundtrip(configured, root/'configured-cold.tcraft')
            check('camera display and bake metadata survive cold native save', document.check_preservation(admitted, cold)['embedded_bytes_preserved'], True)
            previews = []
            for source, name in ((configured, 'preview'), (root/'configured-cold.tcraft', 'cold-preview')):
                path = root/(name+'.png'); run('render', source, path, '--size', '64x64', '--samples', '2', '--bounces', '2', '--cpu')
                with Image.open(path) as image: previews.append((image.size, image.convert('RGBA').tobytes()))
            check('bounded CPU preview pixels survive cold settings reopen', previews[0] == previews[1] and previews[0][0] == (64,64), True)
            plan = settings.bake_budget(admitted['structure'], admitted['project_semantics']); (root/'bake-plan.json').write_text(json.dumps(plan, indent=2)+'\n')
            baked_path = root/'baked.tcraft'; run('bake', configured, '-o', baked_path); baked = document.read_native(baked_path)
            names = {'baked/0_normal.bin', 'baked/0_ambientOcclusion.bin'}
            check('actual CPU bake produces exactly planned native map members', set(baked['members']) == set(admitted['members']) | names, True)
            expected = copy.deepcopy(updated); expected['texture_sets'][0]['baked'] = ['Normal', 'AmbientOcclusion']
            check('bake changes only predicted project metadata', baked['structure']['project'] == expected, True)
            for name in names:
                data = baked['members'][name]; version,w,h,components,reserved = struct.unpack_from('<5I',data,4)
                expected_values = (.5,.5,1.) if 'normal.bin' in name else (1.,)
                values = list(struct.unpack('<' + 'f'*((len(data)-24)//4), data[24:]))
                check(name+' exact bounded layout and analytic plane values', (version,w,h,components,reserved)==(1,16,16,len(expected_values),0)
                      and all(abs(value-expected_values[i%components]) < 1e-5 for i,value in enumerate(values)), True)
            check('actual map byte count agrees with admission budget', sum(len(baked['members'][n]) for n in names)==plan['output_bytes'], True)
            cold_baked = roundtrip(baked_path, root/'baked-cold.tcraft')
            check('cold reopen retains every baked float and field', document.check_preservation(baked,cold_baked)['embedded_bytes_preserved'], True)
            check('original configured source remains unchanged', configured.read_bytes()==admitted['source_bytes'], True)
            # Demonstrate why successful native open is not sufficient: the
            # pinned reader recovers this malformed enum using a default.
            malformed = copy.deepcopy(updated)
            malformed['texture_sets'][0]['bake']['maps']['ao']['parameters']['rays']['distribution'] = 'UnknownDistribution'
            bad_path = root/'recovery-input.tcraft'
            bad_path.write_bytes(packed({**original['members'], 'project.json': json.dumps(malformed).encode()}))
            bad_bytes = bad_path.read_bytes(); before_calls = len(timings)
            refused('malformed bake enum refused before native execution', lambda: document.read_native(bad_path))
            check('preflight refusal does not launch native engine', len(timings)==before_calls, True)
            recovered = roundtrip(bad_path, root/'native-recovered.tcraft')
            check('native success silently recovers invalid enum to default',
                  recovered['structure']['project']['texture_sets'][0]['bake']['maps']['ao']['parameters']['rays']['distribution']=='Cosine', True)
            check('recovery finding preserves original malformed input', bad_path.read_bytes()==bad_bytes, True)
        result={'passed': True,'checks':len(checks),'cases':checks,'native_checks':len(native_checks),'native_cases':native_checks,
                'timings':timings,'seconds':round(time.monotonic()-started,4),'runtime_available':False,'goal_complete':False}
        (root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps({k:result[k] for k in ('passed','checks','native_checks','seconds')}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'passed':False,'cases':checks,'native_cases':native_checks,'error':str(error)},indent=2)+'\n'); raise


if __name__=='__main__': main()
