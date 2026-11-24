#!/usr/bin/env python3
"""Local real-engine thumbnail retention and compound preservation qualification.

Uses a supplied maintained binary, no editor or network. Writes only a new output
folder. This is a development probe, not a public runtime or full native CI gate.
"""
import argparse
import copy
import hashlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import texture_document as document, texture_images


def packed(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--image', action='append', default=[], type=Path, help='Additional independently decoded resources to cold-reopen')
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    root = args.output.resolve(); root.mkdir()
    home = root / 'home'; home.mkdir()
    environment = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'TMPDIR': str(home),
                   'XDG_CONFIG_HOME': str(home), 'XDG_CACHE_HOME': str(home), 'LANG': 'en_US.UTF-8'}
    checks = []; commands = []; started = time.monotonic()

    def check(label, valid=True):
        assert valid, label
        checks.append(label)

    def run(*arguments):
        process = subprocess.run([str(engine), *map(str, arguments)], cwd=root, env=environment,
                                 capture_output=True, text=True, timeout=60)
        record = {'args': list(map(str, arguments)), 'exit_code': process.returncode,
                  'stdout': process.stdout, 'stderr': process.stderr}
        commands.append(record)
        with (root / 'commands.jsonl').open('a') as output:
            output.write(json.dumps(record) + '\n')
        assert process.returncode == 0, record
        return json.loads(process.stdout)

    def batch(source, output, steps=()):
        recipe = root / (output.stem + '.recipe.json')
        recipe.write_text(json.dumps({'open': str(source), 'steps': list(steps), 'save': str(output)}) + '\n')
        result = run('batch', recipe)
        assert result['failed'] is None and result['completed'] == len(steps), result
        return document.read_native(output)

    try:
        base = root / 'base.tcraft'
        created = batch('builtin:plane', base, [
            {'id': 'project.new', 'params': {'name': 'Thumbnail preservation', 'mesh': 'plane', 'resolution': 128}},
            {'id': 'layer.add.fill', 'params': {'name': 'Blue finish', 'color': [0, 0, 1], 'roughness': 0.25}},
        ])
        check('new project starts without inherited thumbnail', created['thumbnail'] is None)
        image = io.BytesIO(); Image.new('RGB', (4, 2), (188, 0, 188)).save(image, format='PNG')
        thumbnail = image.getvalue()
        members = {**created['members'], 'thumbnail.png': thumbnail,
                   'resources/reference.png': thumbnail, 'resources/linked.mcraft': b'opaque package; never cook'}
        source = root / 'input.tcraft'; source.write_bytes(packed(members))
        before = document.read_native(source)
        original = source.read_bytes()
        check('complete compound inventory is retained', before['members'] == members and len(before['inventory']) == 4)
        check('thumbnail is source provenance, not an authorized render',
              before['inventory']['thumbnail.png']['role'] == 'source-thumbnail' and not before['engine_admission_complete'])
        rejected = root / 'unknown.tcraft'; rejected.write_bytes(packed({**members, 'unknown/future-data': b'canary'}))
        commands_before = len(commands)
        try:
            document.read_native(rejected)
        except ValueError as error:
            check('unknown archive member refused before any native invocation',
                  'not qualified for lossless native import' in str(error) and len(commands) == commands_before)
        else:
            raise AssertionError('unknown member was admitted')

        saved = batch(source, root / 'saved.tcraft')
        check('native save retains every project field and embedded byte',
              document.check_preservation(before, saved)['embedded_bytes_preserved'])
        cold = batch(root / 'saved.tcraft', root / 'cold.tcraft')
        check('cold native save retains complete source thumbnail and members',
              document.check_preservation(before, cold)['embedded_bytes_preserved'])
        check('cold serialization retains every decompressed byte', cold['members'] == saved['members'])
        for path, admitted in ((source, before), (root / 'cold.tcraft', cold)):
            result = run('run', path, 'resource.list', '{}')
            texture_images.check_native_resources(admitted['resources'], result)
            check('native image and opaque-package decoder agreement ' + path.name)

        expected = copy.deepcopy(before['structure']['project'])
        layer_id = max(int(key) for key in expected['layers'])
        expected['layers'][str(layer_id)]['kind']['Fill']['sources']['Roughness']['Uniform'] = [0.75] * 3
        edited = batch(source, root / 'edited.tcraft', [
            {'id': 'layer.fill.set', 'params': {'layer': layer_id, 'channel': 'roughness', 'value': 0.75}},
        ])
        check('precise revision retains thumbnail as imported source data',
              document.check_preservation(before, edited, expected_project=expected)['embedded_bytes_preserved'])
        edited_cold = batch(root / 'edited.tcraft', root / 'edited-cold.tcraft')
        check('cold revised project retains predicted edit and imported preview',
              document.check_preservation(before, edited_cold, expected_project=expected)['embedded_bytes_preserved'])
        reset = batch(source, root / 'reset.tcraft', [
            {'id': 'project.new', 'params': {'name': 'New unrelated project', 'mesh': 'plane', 'resolution': 128}},
        ])
        check('new project does not inherit source thumbnail or resources',
              reset['thumbnail'] is None and set(reset['members']) == {'project.json'})
        for index,image_path in enumerate(args.image):
            payload=image_path.read_bytes();name='reference'+image_path.suffix.lower();folder=root/f'additional-image-{index}';folder.mkdir()
            compound=folder/'input.tcraft';compound.write_bytes(packed({**created['members'],'resources/'+name:payload}))
            profile=document.read_native(compound)
            reply=run('run',compound,'resource.list','{}');texture_images.check_native_resources(profile['resources'],reply)
            check('additional native complete decoder agreement '+image_path.name)
            saved_path=folder/'saved.tcraft';saved=batch(compound,saved_path)
            check('additional native save retains every field and resource '+image_path.name,document.check_preservation(profile,saved)['embedded_bytes_preserved'])
            reply=run('run',saved_path,'resource.list','{}');texture_images.check_native_resources(saved['resources'],reply)
            check('additional cold native decoder agreement '+image_path.name)
            check('additional original resource unchanged '+image_path.name,image_path.read_bytes()==payload)
        check('original native bytes remain unchanged', source.read_bytes() == original)
        report = {'passed': True, 'checks': len(checks), 'cases': checks,
                  'seconds': round(time.monotonic() - started, 4), 'native_commands': len(commands),
                  'binary_sha256': hashlib.sha256(engine.read_bytes()).hexdigest(),
                  'source_sha256': before['source_sha256'], 'thumbnail_sha256': hashlib.sha256(thumbnail).hexdigest(),
                  'thumbnail_role': 'retained imported preview; not regenerated after revision',
                  'engine_admission_complete': False, 'runtime_available': False,
                  'full_native_ci_qualified': False, 'goal_complete': False}
        (root / 'evidence.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': True, 'checks': len(checks), 'evidence': str(root / 'evidence.json')}))
    except Exception as error:
        (root / 'failure.json').write_text(json.dumps({'passed': False, 'completed_checks': checks,
                                                     'error': str(error)}, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
