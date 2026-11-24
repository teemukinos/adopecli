"""Qualify explicit construction image sampling through a sealed public CLI.

Legacy repeat rendering stays unchanged. An explicit clip revision removes edge
wrapping without changing the original source or unrelated objects. Native-only
sampling changes must fail without publication. No owner approval is inferred.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('source', type=Path)
parser.add_argument('--expect-verification', type=Path, required=True)
parser.add_argument('--baseline-png', type=Path, required=True)
parser.add_argument('--baseline-sha256', required=True)
parser.add_argument('--clipped-png', type=Path, required=True)
parser.add_argument('--clipped-sha256', required=True)
parser.add_argument('--resume', action='store_true')
a = parser.parse_args()
package = a.package.resolve(strict=True)
source = a.source.resolve(strict=True)
out = a.output.absolute()
out.mkdir(mode=0o700, exist_ok=a.resume)
lock = (out / 'fixture.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
(out / 'home').mkdir(exist_ok=a.resume)
state = out / 'state'
env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}

def load(name, default=None):
    p = out / name
    return json.loads(p.read_text()) if p.exists() else default

def save(name, value):
    (out / name).write_text(json.dumps(value, indent=2) + '\n')

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

checks, commands, jobs = load('checks.json', []), load('commands.json', []), load('jobs.json', [])

def check(value, label):
    assert value, label
    if label not in checks:
        checks.append(label)
        save('checks.json', checks)

def run(label, command, timeout=180):
    command = list(map(str, command))
    p = subprocess.run(command, stdin=subprocess.DEVNULL, env=env,
                       capture_output=True, text=True, timeout=timeout)
    commands.append({'label': label, 'command': command, 'exit': p.returncode,
                     'stdout': p.stdout, 'stderr': p.stderr})
    save('commands.json', commands)
    check(p.returncode == 0, label + ' succeeds')
    return json.loads(p.stdout) if p.stdout.strip() else None

def cli(label, *args):
    return run(label, [package / 'bin/a-dope-cli', '--state', state, *args])

def receipt(folder):
    d = json.loads((folder / 'project.json').read_text())
    for row in d['files']:
        p = folder / row['path']
        check(p.is_file() and not p.is_symlink() and p.stat().st_size == row['bytes']
              and sha(p) == row['sha256'], 'receipt ' + folder.name + ' ' + row['path'])
    return d

def imported(label, folder):
    p = load(label + '-import.json')
    if p is None:
        p = cli(label + ' import', 'import-project', folder, 'Image sampling ' + label)
        save(label + '-import.json', p)
    return p['project']['id'], p['revision']['id']

def job(label, project, revision, operation, parameters, error=None):
    path = out / (label + '-request.json')
    encoded = json.dumps(parameters, sort_keys=True) + '\n'
    if path.exists():
        check(path.read_text() == encoded, label + ' request remains identical')
    else:
        path.write_text(encoded)
    row = next((x for x in jobs if x['label'] == label), None)
    if row is None:
        args = ['submit', project, operation, '--parameters', path, '--key', label, '--timeout', '180']
        if revision:
            args += ['--source', revision]
        admitted = cli(label + ' submit', *args)
        row = {'label': label, 'id': admitted['id'], 'operation': operation}
        jobs.append(row)
        save('jobs.json', jobs)
    observed = cli(label + ' observe', 'job', row['id'])
    if observed['state'] == 'queued' and observed['attempt'] == 0:
        cli(label + ' worker', 'worker', '--once')
        observed = cli(label + ' result', 'job', row['id'])
    check(observed['attempt'] == 1 and observed['state'] == ('failed' if error else 'succeeded'), label + ' has one expected terminal attempt')
    row['result'] = observed
    save('jobs.json', jobs)
    if error:
        check(observed['result_revision'] is None and error in observed['error']['message'], label + ' refuses the exact mismatch')
        check(cli(label + ' project', 'project', project)['head'] == revision, label + ' preserves the source head')
        return revision, None
    destination = out / label
    if not destination.exists():
        cli(label + ' checkout', 'checkout', observed['result_revision'], destination)
    receipt(destination)
    check(json.loads((destination / 'construction/components/hero/native/inspection.json').read_text())['native_image_sampling_verified'], label + ' has fresh native sampling proof')
    return observed['result_revision'], destination

def pixels(p):
    with Image.open(p) as image:
        return image.size, image.convert('RGBA').tobytes()

expected = json.loads(a.expect_verification.read_text())
check(run('verify package', [package / 'bin/a-dope-guard', 'verify']) == expected, 'exact sealed package before qualification')
check(sha(a.baseline_png) == a.baseline_sha256 and sha(a.clipped_png) == a.clipped_sha256, 'independent reference images match their digests')
check(pixels(a.baseline_png) != pixels(a.clipped_png), 'controlled sampling changes real pixels')
manifest = receipt(source)
original = {x['path']: x['sha256'] for x in manifest['files']}
original['project.json'] = sha(source / 'project.json')
save('input-hashes.json', original)
support = json.loads((package / 'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text())
blender = Path('/Applications/Blender.app/Contents/MacOS/Blender')
check(sha(blender) == support['engines']['blender']['sha256'], 'native mutation tool matches the pinned Blender')
cli('resource limits', 'limits', '--wall-seconds', '180', '--cpu-seconds', '600', '--memory-mib', '4096', '--attempt-mib', '1024')
project, revision = imported('legacy', source)
revision, _ = job('legacy-verify', project, revision, 'construct.verify', {})
revision, control = job('legacy-render', project, revision, 'construct.render', {'outputs': [{'component': 'hero', 'format': 'png', 'frame': 0}]})
check(pixels(control / 'construction/components/hero/exports/still.png') == pixels(a.baseline_png), 'legacy repeat keeps every original pixel')
document = json.loads((control / 'construction/document.json').read_text())
objects = document['components'][0]['parameters']['objects']
index = next(i for i, obj in enumerate(objects) if obj['id'] == 'supplied_logo')
old = objects[index]
check(old['kind'] == 'image' and 'image_extension' not in old, 'legacy logo has no explicit sampling field')
new = {**old, 'image_extension': 'clip'}
digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
revision, edited = job('explicit-clip', project, revision, 'construct.edit', {'document_sha256': digest, 'edits': [{'component': 'hero', 'action': 'set', 'path': ['parameters', 'objects', index], 'before': old, 'value': new}]})
revision, fixed = job('clip-render', project, revision, 'construct.render', {'outputs': [{'component': 'hero', 'format': 'png', 'frame': 0}]})
revision, _ = job('clip-verify', project, revision, 'construct.verify', {})
check(pixels(fixed / 'construction/components/hero/exports/still.png') == pixels(a.clipped_png), 'explicit revision equals every independently controlled clip pixel')
proof = json.loads((edited / 'construction/components/hero/native/revision-proof.json').read_text())
check(proof['before']['camera'] == proof['after']['camera'], 'camera remains unchanged')
before, after = proof['before']['objects'], proof['after']['objects']
check(before.keys() == after.keys() and all(before[n] == after[n] for n in before if n != 'supplied_logo'), 'every untargeted object remains unchanged')
logo = copy.deepcopy(after['supplied_logo'])
del logo['construction']['image_extension']
check(logo == before['supplied_logo'], 'targeted logo retains geometry and all other declared properties')


# New source creation must honor the same explicit mode, not only revision.
fresh = load('fresh-project.json')
if fresh is None:
    fresh = cli('fresh project', 'create-project', 'Explicit clip creation')
    save('fresh-project.json', fresh)
asset = load('fresh-asset.json')
if asset is None:
    asset = cli('fresh logo', 'import-asset', fresh['id'], source / 'construction/assets' / old['asset'])
    save('fresh-asset.json', asset)
fresh_document = copy.deepcopy(document)
fresh_document['components'][0]['parameters']['objects'][index] = {**new, 'asset': asset['id']}
fresh_revision, _ = job('clip-create', fresh['id'], None, 'construct.create', {'document': fresh_document})
fresh_revision, fresh_output = job('clip-create-render', fresh['id'], fresh_revision, 'construct.render', {'outputs': [{'component': 'hero', 'format': 'png', 'frame': 0}]})
check(pixels(fresh_output / 'construction/components/hero/exports/still.png') == pixels(a.clipped_png), 'new explicit clip creation matches the independent reference')

MUTATOR = """import bpy,json,sys
from pathlib import Path
q=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text());p=Path(q['root'])
bpy.ops.wm.open_mainfile(filepath=str(p/'native/scene.blend'),load_ui=False,use_scripts=False)
bpy.context.preferences.filepaths.save_version=0
obj=bpy.data.objects['supplied_logo'];tree=obj.data.materials[0].node_tree;n=tree.nodes['Image'];assert n.extension=='CLIP'
if q['variant']=='extension':n.extension='REPEAT'
elif q['variant']=='interpolation':n.interpolation='Closest'
elif q['variant']=='uv':obj.data.uv_layers.active.data[0].uv.x=.25
elif q['variant']=='coordinates':tree.links.remove(n.inputs['Vector'].links[0])
else:raise AssertionError('unknown native mutation')
bpy.ops.wm.save_as_mainfile(filepath=str(p/'native/scene.blend'))
"""
mutator = out / 'mutate.py'
mutator.write_text(MUTATOR)
for variant, error in [('extension', 'Native image extension differs'), ('interpolation', 'Native image sampling differs'), ('uv', 'Native image UV mapping differs'), ('coordinates', 'Native image coordinates differ')]:
    bundle = out / (variant + '-bundle')
    ready = out / (variant + '-ready.json')
    if not ready.exists():
        check(not bundle.exists(), variant + ' has no unresolved partial mutation')
        shutil.copytree(fixed, bundle)
        request = out / (variant + '-mutation.json')
        request.write_text(json.dumps({'root': str(bundle / 'construction/components/hero'), 'variant': variant}))
        p = subprocess.run(['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', str(blender), '-b', '--factory-startup', '--disable-autoexec', '--python-exit-code', '1', '-P', str(mutator), '--', str(request)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90)
        (out / (variant + '-mutation.log')).write_text(p.stdout + p.stderr)
        check(p.returncode == 0, variant + ' controlled native mutation succeeds')
        cm = bundle / 'construction/manifest.json'
        d = json.loads(cm.read_text())
        native = bundle / 'construction/components/hero/native/scene.blend'
        d['components']['hero']['files']['native/scene.blend'] = {'sha256': sha(native), 'bytes': native.stat().st_size}
        cm.write_text(json.dumps(d, sort_keys=True, indent=2) + '\n')
        d = json.loads((bundle / 'project.json').read_text())
        for row in d['files']:
            p = bundle / row['path']
            row.update(sha256=sha(p), bytes=p.stat().st_size)
        (bundle / 'project.json').write_text(json.dumps(d, sort_keys=True, indent=2) + '\n')
        save(variant + '-ready.json', {'manifest_sha256': sha(bundle / 'project.json')})
    check(sha(bundle / 'project.json') == load(variant + '-ready.json')['manifest_sha256'], variant + ' retained mutation remains identical')
    receipt(bundle)
    bad_project, bad_revision = imported(variant, bundle)
    for operation in ('verify', 'render'):
        params = {} if operation == 'verify' else {'outputs': [{'component': 'hero', 'format': 'png', 'frame': 0}]}
        job(variant + '-' + operation, bad_project, bad_revision, 'construct.' + operation, params, error + ': supplied_logo')
for name, digest in original.items():
    check(sha(source / name) == digest, 'original input retained ' + name)
with sqlite3.connect((state / 'studio.sqlite3').as_uri() + '?mode=rw', uri=True) as db:
    db.execute('PRAGMA query_only=ON')
    db.row_factory = sqlite3.Row
    durable = {t: [dict(x) for x in db.execute('SELECT * FROM ' + t)] for t in ['jobs', 'attempts', 'attempt_executions', 'revisions']}
check(len(durable['attempts']) == 15 and len(durable['jobs']) == 20, 'seven successful native jobs, eight refusals and five separate imports')
for row in durable['attempt_executions']:
    try:
        os.killpg(row['process_group'], 0)
    except ProcessLookupError:
        row['group_absent'] = True
    else:
        raise AssertionError('Native process group remains')
save('durable-records.json', durable)
check(run('verify package afterward', [package / 'bin/a-dope-guard', 'verify']) == expected, 'sealed package remains unchanged')
save('evidence.json', {'passed': True, 'checks': len(checks), 'native_jobs': 15, 'native_successes': 7, 'native_expected_failures': 8, 'separate_imports': 5, 'original_pixels_preserved': True, 'explicit_clip_pixels_match_independent_reference': True, 'all_native_groups_absent': True, 'runtime_overlays': False, 'owner_approval': False, 'full_release_qualified': False})
print(json.dumps(load('evidence.json')))
