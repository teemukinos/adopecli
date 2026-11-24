"""Verify native production results and refuse stale success through the public CLI.

Usage: production_result_acceptance.py PACKAGE NEW_OUTPUT
Runs only an owned synthetic scene and isolated local durable state.
"""
from pathlib import Path
import hashlib, json, os, shutil, sqlite3, subprocess, sys, time
from PIL import Image

package = Path(sys.argv[1]).resolve(strict=True)
out = Path(sys.argv[2]).absolute()
out.mkdir(exist_ok=False)
report = out
(out / 'home').mkdir()
state = out / 'state'
env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
commands, jobs = [], []

def write(name, value):
    (report / name).write_text(json.dumps(value, indent=2) + '\n')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def hashes(path):
    return {str(p.relative_to(path)): sha(p) for p in path.rglob('*') if p.is_file()}

def call(label, *args):
    command = [str(package / 'bin/a-dope-cli'), '--state', str(state), *map(str, args)]
    p = subprocess.run(command, stdin=subprocess.DEVNULL, env=env, capture_output=True, text=True, timeout=600)
    commands.append({'label': label, 'args': command, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
    write('commands.json', commands)
    assert p.returncode == 0, (label, p.stderr[-1500:])
    return json.loads(p.stdout) if p.stdout.strip() else None

def job(label, project, operation, parameters, source=None, success=True):
    request = out / (label + '-request.json')
    request.write_text(json.dumps(parameters) + '\n')
    args = ['submit', project, operation, '--parameters', request, '--key', label, '--timeout', '600']
    if source:
        args += ['--source', source]
    submitted = call(label + ' submit', *args)
    row = {'label': label, 'id': submitted['id'], 'operation': operation}
    jobs.append(row)
    write('jobs.json', jobs)
    call(label + ' worker', 'worker', '--once')
    result = call(label + ' result', 'job', submitted['id'])
    row['result'] = result
    write('jobs.json', jobs)
    assert result['state'] == ('succeeded' if success else 'failed'), (label, result)
    if not success:
        assert result['result_revision'] is None, result
        return result, None, None
    destination = out / label
    call(label + ' checkout', 'checkout', result['result_revision'], destination)
    manifest = json.loads((destination / 'project.json').read_text())
    for f in manifest['files']:
        p = destination / f['path']
        assert p.stat().st_size == f['bytes'] and sha(p) == f['sha256']
    assert manifest['validation']['passed'] and manifest['validation']['native_cold_reopen']
    row['checkout'] = str(destination)
    write('jobs.json', jobs)
    return result, destination, manifest

document = {
    'schema_version': 1, 'profile': 'product-scene-v1',
    'policy': {'network': 'offline', 'media_generation': 'disabled'},
    'render': {'width': 256, 'height': 256, 'samples': 8, 'seed': 417},
    'camera': {'location': [3, -4, 3], 'target': [0, 0, .5], 'lens': 50, 'fstop': 8},
    'materials': [
        {'id': 'blue', 'color': '#2455CC', 'roughness': .35, 'metallic': 0, 'transmission': 0, 'ior': 1.45},
        {'id': 'floor', 'color': '#D9D9D9', 'roughness': .7, 'metallic': 0, 'transmission': 0, 'ior': 1.45}],
    'objects': [
        {'id': 'box', 'kind': 'box', 'material': 'blue', 'location': [0, 0, .5], 'rotation': [0, 0, 15], 'size': [1, 1, 1], 'bevel': .04},
        {'id': 'ground', 'kind': 'box', 'material': 'floor', 'location': [0, 0, -.1], 'rotation': [0, 0, 0], 'size': [8, 8, .2], 'bevel': 0}],
    'lights': [{'id': 'key', 'location': [2, -3, 5], 'target': [0, 0, .5], 'color': '#FFFFFF', 'power': 700, 'size': 3, 'size_y': 3}],
    'world': {'color': '#FFFFFF', 'strength': .2}}
verified = json.loads(subprocess.check_output([package/'bin/a-dope-guard', 'verify'], stdin=subprocess.DEVNULL, env=env))
assert verified['verified']
write('verification-before.json', verified)
write('document.json', document)
project = call('create project', 'create-project', 'Production result boundary')['id']
original_result, original, original_manifest = job('original', project, 'production.create', {'document': document})
original_hashes = hashes(original)
write('original-hashes.json', original_hashes)
control_result, control, control_manifest = job('control', project, 'production.verify', {}, original_result['result_revision'])
assert control_manifest['validation'].get('reproduced_pixels') is True, control_manifest['validation']
inner_original = json.loads((original/'production/manifest.json').read_text())
revision_result, revision, revision_manifest = job('revised', project, 'production.edit', {'recipe_sha256': inner_original['recipe_sha256'], 'edits': [{'collection': 'materials', 'id': 'blue', 'field': 'color', 'before': '#2455CC', 'value': '#CC4524'}]}, control_result['result_revision'])
assert revision_manifest['validation']['composition_preserved'] is True
proof = json.loads((revision/'production/revision-proof.json').read_text())
assert proof['geometry_preserved'] and proof['camera_preserved']
with Image.open(original/'production/exports/photograph.png') as a, Image.open(revision/'production/exports/photograph.png') as b:
    assert a.size == b.size == (256, 256) and a.convert('RGBA').tobytes() != b.convert('RGBA').tobytes()
render_result, rendered, render_manifest = job('rendered', project, 'production.render', {}, revision_result['result_revision'])
with Image.open(revision/'production/exports/photograph.png') as a, Image.open(rendered/'production/exports/photograph.png') as b:
    assert a.convert('RGBA').tobytes() == b.convert('RGBA').tobytes()
modified = out / 'modified-copy'
shutil.copytree(original, modified)
png = modified / 'production/exports/photograph.png'
with Image.open(png) as im:
    pixels = im.convert('RGBA')
    pixels.putpixel((0, 0), (255, 0, 255, 255))
    pixels.save(png)
assert sha(png) != sha(original / 'production/exports/photograph.png')
inner_path = modified / 'production/manifest.json'
inner = json.loads(inner_path.read_text())
item = inner['files']['exports/photograph.png']
item.update(sha256=sha(png), bytes=png.stat().st_size)
inner_path.write_text(json.dumps(inner, indent=2) + '\n')
outer_path = modified / 'project.json'
outer = json.loads(outer_path.read_text())
for item in outer['files']:
    p = modified / item['path']
    item.update(sha256=sha(p), bytes=p.stat().st_size)
outer_path.write_text(json.dumps(outer, indent=2) + '\n')
changed = [name for name, value in original_hashes.items() if sha(modified / name) != value]
assert set(changed) == {'project.json', 'production/manifest.json', 'production/exports/photograph.png'}, changed
write('mutation.json', {'changed_files': changed, 'native_scene_unchanged': True, 'original_manifest': original_manifest, 'modified_manifest': outer})
imported = call('import modified copy', 'import-project', modified, 'Production altered export')
head = call('head before refusal', 'project', imported['project']['id'])
bad_result, _, _ = job('altered-verify', imported['project']['id'], 'production.verify', {}, imported['revision']['id'], success=False)
assert 'Reopened render pixels differ' in str(bad_result['error']), bad_result
assert call('head after refusal', 'project', imported['project']['id']) == head
assert hashes(original) == original_hashes
groups = []
with sqlite3.connect('file:' + str(state / 'studio.sqlite3') + '?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    records = {table: [dict(row) for row in db.execute('SELECT * FROM ' + table)] for table in ['jobs', 'revisions', 'attempt_executions']}
    groups = [row['process_group'] for row in records['attempt_executions'] if row['process_group'] is not None]
write('durable-records.json', records)
for group in groups:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('Native group remains: ' + str(group))
assert json.loads(subprocess.check_output([package/'bin/a-dope-guard', 'verify'], stdin=subprocess.DEVNULL, env=env)) == verified
write('evidence.json', {
    'passed': True, 'verification': verified, 'native_jobs': len(jobs),
    'successful_native_jobs': 4, 'expected_failed_native_jobs': 1, 'separate_imports': 1,
    'valid_original_pixel_verification': True, 'targeted_material_revision': True,
    'native_geometry_and_camera_preserved': True, 'repeated_render_pixels_equal': True,
    'altered_export_verification_refused': True, 'refusal_publishes_no_revision': True,
    'refusal_preserves_project_head': True, 'original_bytes_unchanged': True,
    'all_native_groups_absent': True, 'groups': groups, 'source_overlays': False,
    'owner_visual_approval': False, 'remote_actions': False, 'full_release_qualified': False})
print(json.dumps({'passed': True, 'native_jobs': len(jobs), 'output': str(out)}))
