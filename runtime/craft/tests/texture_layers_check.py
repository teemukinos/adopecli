#!/usr/bin/env python3
"""Local Texture layer schema checks with optional native cold-save/export probes."""
import argparse
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
import zipfile
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from texture_structure_check import project
from studio_runtime import texture_structure as structure, texture_layers as layers, texture_document as document

UV = {'Uv': {'scale': [1., 1.], 'rotation': 0., 'offset': [0., 0.]}}
PATTERNS = 'Clouds Perlin Noise Cells Grunge Scratches Checker Stripes Gradient Wood Bricks Tiles Weave Twill Leather Hammered Brushed Marble Voronoi Streaks Smudges Pores Chips'.split()
FILTERS = {
    'Blur': {'radius': 64.}, 'Sharpen': {'amount': .5}, 'Threshold': {'level': .5},
    'Hsl': {'hue': .25, 'saturation': .25, 'lightness': .1},
    'ContrastLuminosity': {'contrast': .25, 'luminosity': .1},
    'ColorBalance': {'shadows': [.1, 0., 0.], 'midtones': [0., .1, 0.], 'highlights': [0., 0., .1]},
    'GradientMap': {'colors': [[0., 0., 0.], [1., .5, .25]]}, 'Posterize': {'levels': 4.},
    'Clamp': {'min': .1, 'max': .9}, 'HistogramScan': {'position': .5, 'contrast': .5},
    'HistogramRange': {'range': .5, 'position': .5}, 'HistogramShift': {'offset': .25},
    'Warp': {'intensity': 32., 'scale': 4., 'seed': 7}, 'DirectionalBlur': {'radius': 32., 'angle': 45.},
    'SlopeBlur': {'radius': 32., 'scale': 4., 'seed': 7}, 'HighPass': {'radius': 32.},
    'EdgeDetect': {'width': 32.}, 'DirectionalWarp': {'intensity': 32., 'angle': 45., 'scale': 4., 'seed': 7},
    'Bevel': {'width': 32.}, 'Mosaic': {'size': 32.}, 'Glow': {'radius': 32., 'amount': .5},
    'BakedLighting': {'azimuth': 45., 'elevation': 45., 'light': .5, 'ambient': .25, 'occlusion': .5},
    'ReplaceColor': {'from': [.25, .5, .75], 'to': [.75, .5, .25], 'tolerance': .1, 'softness': .1},
}
PROJECTIONS = {
    **UV, 'Triplanar': {'scale': 1., 'sharpness': 4., 'offset': [0., 0., 0.]},
    'Planar': {'scale': 1., 'axis': 2, 'offset': [0., 0., 0.]}, 'Spherical': {'scale': 1.},
    'Cylindrical': {'scale': 1., 'axis': 1},
    'Decal': {'center': [0., 0., 0.], 'normal': [0., 1., 0.], 'up': [0., 0., 1.],
              'size': [2., 2.], 'rotation': 0., 'offset': [0., 0.], 'depth': 1.},
}


def source(name='Checker'):
    return {'Procedural': {'pattern': {'kind': name, 'scale': 4., 'seed': 7, 'contrast': 1., 'balance': 0., 'invert': False},
                           'low': [1., 0., 0.], 'high': [0., 0., 1.]}}


def effect(kind, eid=2):
    return {'id': eid, 'name': 'Effect', 'visible': True, 'kind': kind, 'blend': 'Normal', 'opacity': 1.}


def base():
    p = project(); p['layers']['1']['kind'] = {'Fill': {'sources': {'BaseColor': {'Uniform': [.25, .5, .75]}}, 'projection': copy.deepcopy(UV)}}
    p['layers']['1']['channels']['BaseColor']['opacity'] = 1.
    return p


def packed(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items(): archive.writestr(name, value)
    return out.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); root = args.output.resolve(); root.mkdir(); checks = []; native_checks = []; started = time.monotonic()
    def inspect(p): return layers.inspect(structure.inspect_json(json.dumps(p).encode()))
    def check(label, value, native=False):
        assert value, label
        (native_checks if native else checks).append(label)
    def refused(label, action):
        try: action()
        except ValueError: checks.append(label)
        else: raise AssertionError('unexpected admission: ' + label)
    def mutation(label, change):
        p = base(); change(p); refused(label, lambda: inspect(p))
    cases = [('uniform', base())]
    try:
        for name in PATTERNS:
            p = base(); p['layers']['1']['kind']['Fill']['sources']['BaseColor'] = source(name)
            cases.append(('pattern-' + name, p))
        for name, params in PROJECTIONS.items():
            p = base(); p['layers']['1']['kind']['Fill']['projection'] = {name: params}
            p['layers']['1']['kind']['Fill']['sources']['BaseColor'] = source()
            cases.append(('projection-' + name, p))
        for name, params in [*FILTERS.items(), ('Invert', None), ('Grayscale', None), ('NormalInvert', None)]:
            p = base(); p['layers']['1']['content_effects'] = [effect(name if params is None else {'Filter': {name: params}})]
            if params is None: p['layers']['1']['content_effects'][0]['kind'] = {'Filter': name}
            p['next_id'] = 3; cases.append(('filter-' + name, p))
        for name in ('EdgeWear', 'Dirt', 'ThinAreas', 'Curvature', 'AmbientOcclusion', 'Position', 'Direction'):
            p = base(); body = {'kind': name, 'level': .5, 'softness': .25, 'noise_amount': .25, 'noise_scale': 4.,
                               'seed': 7, 'direction': [0., 1., 0.], 'invert': False,
                               'detail': {'mode': 'Edges', 'weights': [1., .5, .25, .125, 0., 0., 0.]}}
            p['layers']['1']['mask'] = {'enabled': True, 'background': 'White', 'effects': [effect({'Generator': body})]}
            p['next_id'] = 3; cases.append(('generator-' + name, p))
        for name, kind, mask in [
            ('levels', {'Levels': {'in_low': 0., 'in_high': 1., 'gamma': 2., 'out_low': 0., 'out_high': 1.}}, False),
            ('mask-fill', {'Fill': {'source': source(), 'projection': UV}}, True),
            ('color-selection', {'ColorSelection': {'colors': [[1., 0., 0.]], 'tolerance': .1}}, True),
            ('compare', {'Compare': {'op': 'GreaterThan', 'value': .5, 'tolerance': .1}}, True),
            ('anchor', 'Anchor', False),
            ('material', {'Material': {'sources': {'BaseColor': {'Uniform': [.75, .5, .25]}}, 'projection': UV}}, False),
            ('stored-path', {'Path': [{'points': [[0., 0., 0.], [1., 1., 0.]], 'uv': True, 'closed': False,
                                      'fill': False, 'viewport': [128., 128.], 'paint': {}}]}, False),
        ]:
            p = base(); p['next_id'] = 3
            if mask: p['layers']['1']['mask'] = {'enabled': True, 'background': 'White', 'effects': [effect(kind)]}
            else: p['layers']['1']['content_effects'] = [effect(kind)]
            cases.append((name, p))
        p = base(); p['layers']['1']['content_effects'] = [effect('Anchor')]
        reader = copy.deepcopy(base()['layers']['1']); reader.update(id=3, name='Anchor reader')
        reader['kind']['Fill']['sources']['BaseColor'] = {'Anchor': {'anchor': 2, 'channel': 'BaseColor'}}
        p['layers']['3'] = reader; p['texture_sets'][0]['stack'] = [1, 3]; p['next_id'] = 4
        cases.append(('anchor-reader', p))
        for label, p in cases:
            result = inspect(p)
            check('accepted ' + label, not result['project_admission_complete'] and not result['path_replay_authorized'])
        for label, change in [
            ('unknown layer field', lambda p: p['layers']['1'].update(future=True)),
            ('numeric boolean', lambda p: p['layers']['1'].update(visible=1)),
            ('invalid blend', lambda p: p['layers']['1']['channels']['BaseColor'].update(mode='Future')),
            ('opacity clamp', lambda p: p['layers']['1']['channels']['BaseColor'].update(opacity=2.)),
            ('zero projection scale', lambda p: p['layers']['1']['kind']['Fill'].update(projection={'Uv': {'scale': [0., 1.], 'rotation': 0., 'offset': [0., 0.]}})),
            ('unknown projection field', lambda p: p['layers']['1']['kind']['Fill']['projection']['Uv'].update(future=True)),
            ('invalid projection axis', lambda p: p['layers']['1']['kind']['Fill'].update(projection={'Planar': {'scale': 1., 'axis': 3, 'offset': [0., 0., 0.]}})),
            ('oversized uniform', lambda p: p['layers']['1']['kind']['Fill']['sources'].update(BaseColor={'Uniform': [1e30, 0., 0.]})),
            ('boolean uniform', lambda p: p['layers']['1']['kind']['Fill']['sources'].update(BaseColor={'Uniform': [True, 0., 0.]})),
        ]: mutation(label, change)
        for kind in ({'Filter': {'Blur': None}}, {'Filter': {'Blur': {'radius': -1.}}}, {'Filter': {'Blur': {'radius': 1., 'future': 2}}},
                     {'Levels': {'in_low': 1., 'in_high': 0., 'gamma': 1., 'out_low': 0., 'out_high': 1.}},
                     {'Filter': {'GradientMap': {'colors': []}}}, {'Filter': {'Clamp': {'min': 1., 'max': 0.}}},
                     {'Filter': {'Warp': {'intensity': 32., 'scale': 4., 'seed': -1}}}):
            p = base(); p['layers']['1']['content_effects'] = [effect(kind)]; p['next_id'] = 3
            refused('invalid effect ' + json.dumps(kind), lambda p=p: inspect(p))
        p = base(); p['layers']['1']['mask'] = {'enabled': True, 'background': 'White', 'effects': [effect('Anchor')]}; p['next_id'] = 3
        refused('content-only effect in mask', lambda: inspect(p))
        p = copy.deepcopy(dict(cases)['mask-fill']); p['layers']['1']['content_effects'] = p['layers']['1'].pop('mask')['effects']
        refused('mask-only effect in content', lambda: inspect(p))
        with patch.object(layers, 'MAX_SAMPLE_WORK', 1): refused('sampling work budget', lambda: inspect(base()))
        with patch.object(layers, 'MAX_SAMPLE_WORK', 1_000_000):
            refused('anchor prefix work exceeds the simple layer-node counter', lambda: inspect(dict(cases)['anchor-reader']))
        p = copy.deepcopy(dict(cases)['stored-path'])
        with patch.object(layers, 'MAX_PATH_POINTS', 1): refused('aggregate stored path points', lambda: inspect(p))

        if args.engine:
            engine = args.engine.resolve(strict=True); home = root / 'home'; home.mkdir()
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(home), 'LANG': 'en_US.UTF-8',
                   'XDG_CONFIG_HOME': str(home), 'XDG_CACHE_HOME': str(home)}
            def run(*arguments):
                result = subprocess.run([str(engine), *map(str, arguments)], env=env, cwd=root, capture_output=True, text=True, timeout=60)
                with (root / 'commands.jsonl').open('a') as f:
                    f.write(json.dumps({'args': list(map(str, arguments)), 'code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
                assert result.returncode == 0, result.stderr
                return json.loads(result.stdout) if arguments[0] == 'batch' else result.stdout
            seed = root / 'seed.tcraft'; run('new', 'builtin:plane', seed, '--resolution', '128')
            template = document.read_native(seed)
            def export(path, target):
                run('export', path, target, '--preset', 'glTF PBR Metal Roughness', '--format', 'png', '--size', '128', '--padding', 'none')
                images = {}
                for p in target.glob('*.png'):
                    with Image.open(p) as image: images[p.name] = (image.size, image.convert('RGBA').tobytes())
                assert images
                return images
            for label, p in cases:
                folder = root / label; folder.mkdir(); project_value = copy.deepcopy(template['structure']['project'])
                defaults = project_value['layers']['1']; project_value['layers'] = {}
                for lid, case_layer in p['layers'].items():
                    layer = copy.deepcopy(defaults); layer.update(copy.deepcopy(case_layer)); project_value['layers'][lid] = layer
                project_value['texture_sets'][0]['stack'] = p['texture_sets'][0]['stack']
                project_value['next_id'] = p['next_id']
                inp = folder / 'input.tcraft'; inp.write_bytes(packed({**template['members'], 'project.json': json.dumps(project_value).encode()}))
                before = document.read_native(inp); saved = folder / 'saved.tcraft'; cold = folder / 'cold.tcraft'
                for original, target in ((inp, saved), (saved, cold)):
                    recipe = target.with_suffix('.recipe.json'); recipe.write_text(json.dumps({'open': str(original), 'steps': [], 'save': str(target)}))
                    reply = run('batch', recipe); assert reply['failed'] is None
                    document.check_preservation(before, document.read_native(target))
                check(label + ' complete native cold field/payload preservation', True, native=True)
                # Stored paint is deliberately inert; the existing pixel payload
                # renders, and no path replay or external-alpha lookup is invoked.
                images = export(saved, folder / 'maps'); cold_images = export(cold, folder / 'cold-maps')
                check(label + ' cold exported pixels agree', images == cold_images, native=True)
                if label in ('uniform', 'filter-Invert', 'anchor-reader'):
                    expected = (225, 188, 137, 255) if label == 'filter-Invert' else (137, 188, 225, 255)
                    rgba = next(value[1] for name, value in images.items() if name.endswith('_BaseColor.png'))
                    check(label + ' analytic linear-to-sRGB oracle', all(abs(v-expected[i % 4]) <= 1 for i, v in enumerate(rgba)), native=True)
                if label == 'pattern-Checker':
                    rgba = next(value[1] for name, value in images.items() if name.endswith('_BaseColor.png'))
                    check('procedural checker produces spatial variation', len({rgba[i:i+4] for i in range(0, len(rgba), 4)}) > 1, native=True)
                check(label + ' input bytes unchanged', inp.read_bytes() == before['source_bytes'], native=True)
        result = {'passed': True, 'checks': len(checks), 'cases': checks, 'native_checks': len(native_checks),
                  'native_cases': native_checks, 'seconds': round(time.monotonic()-started, 4),
                  'path_replay_authorized': False, 'project_admission_complete': False, 'goal_complete': False}
        (root / 'evidence.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: result[k] for k in ('passed', 'checks', 'native_checks', 'seconds')}))
    except Exception as error:
        (root / 'failure.json').write_text(json.dumps({'passed': False, 'cases': checks, 'native_cases': native_checks, 'error': str(error)}, indent=2) + '\n')
        raise


if __name__ == '__main__': main()
