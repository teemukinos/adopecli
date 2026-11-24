"""Cold-edit the campaign headline through an immutable public CLI package.

Inspect the still before resuming the full movie stage. Compare native source,
exact retained assets and every independently decoded frame. No failed or active
job is resubmitted; owner approval and actual billing remain separate.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import time
from PIL import Image, ImageChops, ImageStat

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('input', type=Path)
parser.add_argument('--expect-verification', type=Path, required=True)
parser.add_argument('--stage', choices=('still', 'movie'), required=True)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
package = args.package.resolve(strict=True)
original = args.input.resolve(strict=True)
out = args.output.absolute()
out.mkdir(parents=True, exist_ok=args.resume, mode=0o700)
lock = (out/'fixture.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
(out/'home').mkdir(exist_ok=args.resume)
env = {'HOME': str(out/'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
state = out/'state'
logs = json.loads((out/'commands.json').read_text()) if args.resume else []
jobs = json.loads((out/'jobs.json').read_text()) if args.resume and (out/'jobs.json').exists() else []
cases = json.loads((out/'cases.json').read_text()) if args.resume and (out/'cases.json').exists() else []


def save(name, value):
    (out/name).write_text(json.dumps(value, indent=2) + '\n')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def check(value, label):
    assert value, label
    if label not in cases:
        cases.append(label)
        save('cases.json', cases)


def run(label, command, *, fresh=False, timeout=3700):
    command = list(map(str, command))
    old = next((row for row in logs if row['label'] == label), None)
    if old is not None and not fresh:
        assert old['command'] == command and old['exit'] == 0, label
        return old['stdout']
    started = time.time()
    result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout)
    logs.append({'label': label, 'command': command, 'exit': result.returncode,
                 'stdout': result.stdout, 'stderr': result.stderr,
                 'seconds': time.time()-started})
    save('commands.json', logs)
    assert result.returncode == 0, (label, result.stderr[-1500:])
    return result.stdout


def cli(label, *arguments, fresh=False):
    value = run(label, [package/'bin/a-dope-cli', '--state', state, *arguments], fresh=fresh)
    return json.loads(value) if value.strip() else None


def receipt(folder):
    manifest = json.loads((folder/'project.json').read_text())
    for row in manifest['files']:
        path = folder/row['path']
        assert path.is_file() and not path.is_symlink()
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], path
    return manifest


def job(label, operation, parameters, source, *, project=None):
    project = project or owner
    path = out/(label+'-request.json')
    encoded = json.dumps(parameters, sort_keys=True) + '\n'
    if path.exists():
        assert path.read_text() == encoded
    else:
        path.write_text(encoded)
    row = next((row for row in jobs if row['label'] == label), None)
    if row is None:
        admitted = cli(label+' submit', 'submit', project, operation, '--parameters', path,
                       '--source', source, '--key', 'campaign-'+label, '--timeout', '3600')
        row = {'label': label, 'id': admitted['id'], 'project': project, 'operation': operation, 'source_revision': source}
        jobs.append(row)
        save('jobs.json', jobs)
    if 'result' not in row:
        observed = cli(label+' observed', 'job', row['id'], fresh=True)
        if observed['state'] == 'queued':
            cli(label+' worker', 'worker', '--once', fresh=True)
        elif observed['state'] not in ('failed', 'succeeded', 'cancelled'):
            raise RuntimeError('Existing attempt requires observation, not replay: '+observed['state'])
        row['result'] = cli(label+' result', 'job', row['id'], fresh=True)
        save('jobs.json', jobs)
    result = row['result']
    check(result['project'] == project and row['operation'] == operation and row['source_revision'] == source,
          label+' recorded request identity matches')
    check(result['state'] == 'succeeded', label+' succeeds')
    destination = out/(label+'-checkout')
    cli(label+' checkout', 'checkout', result['result_revision'], destination)
    receipt(destination)
    row['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


verification = json.loads(run('verify package', [package/'bin/a-dope-guard', 'verify']))
check(verification['verified'] and verification == json.loads(args.expect_verification.read_text()),
      'exact independently authenticated package matches')
input_receipt = receipt(original)
input_hashes = {row['path']: sha(original/row['path']) for row in input_receipt['files']}
input_hashes['project.json'] = sha(original/'project.json')
save('input-hashes.json', input_hashes)
document = json.loads((original/'construction/document.json').read_text())
check(len(document['components']) == 1 and document['components'][0]['engine'] == 'blender', 'retained movie has one native Blender component')
component = document['components'][0]['id']
parameters = document['components'][0]['parameters']
check((parameters['width'], parameters['height'], parameters['fps'], parameters['frames']) == (1920, 1080, 24, 288), 'retained movie canvas and timing match')
headlines = {'headline_one': 'Change one part.', 'headline_two': 'Keep the rest.'}
check(len(parameters['objects']) == 20, 'retained movie has twenty native objects')
cli('limits', 'limits', '--wall-seconds', '3600', '--cpu-seconds', '14400', '--memory-mib', '8192', '--attempt-mib', '4096')
imported = cli('cold import', 'import-project', original, 'Cold campaign headline revision')
owner, imported_revision = imported['project']['id'], imported['revision']['id']
verified_revision, verified = job('cold-native-verify', 'construct.verify', {}, imported_revision)
baseline_revision, baseline = job('original-frame', 'construct.render', {'outputs': [{'component': component, 'format': 'png', 'frame': 0}]}, verified_revision)
base = json.loads((baseline/'construction/components'/component/'native/inspection.json').read_text())
base_hash = json.loads((baseline/'construction/manifest.json').read_text())['document_sha256']
check(json.loads((baseline/'construction/document.json').read_text()) == document, 'cold reopening preserves complete original document')
expected = copy.deepcopy(parameters)
edits = []
for index, obj in enumerate(expected['objects']):
    if obj['id'] in headlines:
        text = headlines[obj['id']]
        edits.append({'component': component, 'action': 'set', 'path': ['parameters', 'objects', index, 'text'], 'before': obj['text'], 'value': text})
        obj['text'] = text
check(len(edits) == 2, 'request changes only two explicit headline strings')
changed_revision, changed = job('headline-edit', 'construct.edit', {'document_sha256': base_hash, 'edits': edits}, baseline_revision)
revised_revision, revised = job('headline-frame', 'construct.render', {'outputs': [{'component': component, 'format': 'png', 'frame': 0}]}, changed_revision)
actual = json.loads((revised/'construction/document.json').read_text())
expected_document = copy.deepcopy(document)
expected_document['components'][0]['parameters'] = expected
check(actual == expected_document, 'complete revised document differs only in requested text')
native = json.loads((revised/'construction/components'/component/'native/inspection.json').read_text())
check(native['native_geometry_and_keys_verified'], 'actual revised native geometry and keys verified')
check(native['camera'] == base['camera'], 'actual camera remains unchanged')
for name, before in base['objects'].items():
    after = native['objects'][name]
    if name in headlines:
        check(after['text'] == headlines[name] and after['construction']['text'] == headlines[name] and after['font_packed'], 'exact packed native headline '+name)
        check({k: v for k, v in before.items() if k not in ('text', 'construction', 'dimensions')} ==
              {k: v for k, v in after.items() if k not in ('text', 'construction', 'dimensions')}, 'headline native styling and transform unchanged '+name)
    else:
        check(after == before, 'complete unchanged native object '+name)
# Global action users include orphan materials that Blender drops on save. Bind
# the independent comparison to actual scene objects, data and material trees.
probe_source = r'''
import bpy, json, sys
from pathlib import Path
request=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
def animation(owner):
    data=getattr(owner,'animation_data',None)
    if not data or not data.action:return None
    action=data.action;curves=[]
    for layer in action.layers:
        for strip in layer.strips:
            for slot in action.slots:
                bag=strip.channelbag(slot)
                if bag:
                    for curve in bag.fcurves:
                        assert not curve.modifiers, 'Unexpected animation modifier'
                        curves.append({'path':curve.data_path,'index':curve.array_index,
                            'extrapolation':curve.extrapolation,'muted':curve.mute,
                            'keys':[{'co':list(k.co),'left':list(k.handle_left),'right':list(k.handle_right),
                                     'left_type':k.handle_left_type,'right_type':k.handle_right_type,
                                     'interpolation':k.interpolation,'easing':k.easing,
                                     'amplitude':k.amplitude,'back':k.back,'period':k.period}
                                    for k in curve.keyframe_points]})
    return {'action':action.name,'curves':curves}
result={}
for label,path in request['sources'].items():
    bpy.ops.wm.open_mainfile(filepath=path,load_ui=False,use_scripts=False)
    bindings={}
    for obj in bpy.context.scene.objects:
        bindings[obj.name+'/object']=animation(obj)
        if obj.data:bindings[obj.name+'/data']=animation(obj.data)
        for index,slot in enumerate(obj.material_slots):
            material=slot.material
            if material:
                key=obj.name+'/material/'+str(index)
                bindings[key]=animation(material)
                if material.node_tree:bindings[key+'/nodes']=animation(material.node_tree)
    result[label]={'bindings':bindings,'bound_actions':sorted({v['action'] for v in bindings.values() if v})}
Path(request['output']).write_text(json.dumps(result,indent=2)+'\n')
'''
probe_path = out/'animation-binding-probe.py'
probe_path.write_text(probe_source)
probe_output = out/'animation-bindings.json'
probe_request = out/'animation-binding-request.json'
probe_request.write_text(json.dumps({'sources': {
    'before': str(baseline/'construction/components'/component/'native/scene.blend'),
    'after': str(revised/'construction/components'/component/'native/scene.blend')},
    'output': str(probe_output)})+'\n')
blender = Path('/Applications/Blender.app/Contents/MacOS/Blender')
support = json.loads((package/'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text())
check(blender.is_file() and sha(blender) == support['engines']['blender']['sha256'], 'read-only native probe uses exact pinned Blender')
run('independent scene animation bindings', ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)',
    blender, '-b', '--factory-startup', '--disable-autoexec', '--python-exit-code', '1', '-P', probe_path, '--', probe_request])
bindings = json.loads(probe_output.read_text())
check(bindings['before'] == bindings['after'], 'all actual scene animation bindings and curve details remain unchanged')
removed_actions = sorted(base['actions'].keys()-native['actions'].keys())
check(not (native['actions'].keys()-base['actions'].keys()), 'headline edit adds no global animation action')
check(all(base['actions'][name] == native['actions'][name] for name in base['actions'].keys() & native['actions'].keys()),
      'all retained global animation curves remain unchanged')
check(not (set(removed_actions) & set(bindings['before']['bound_actions'])), 'removed actions were not bound to actual scene objects or materials')
save('animation-preservation.json', {'actual_scene_bindings_equal': True, 'removed_unbound_actions': removed_actions,
                                   'original_global_action_inventory_preserved': not removed_actions})
assets = [name for name in input_hashes if '/assets/' in name or '/fonts/' in name]
check(bool(assets), 'retained assets and fonts are present')
for name in assets:
    check(sha(revised/name) == input_hashes[name], 'retained asset or font bytes '+name)

headline_box = (100, 340, 880, 580)
fixed_boxes = [(0, 0, 1920, 340), (0, 580, 1920, 1080), (0, 340, 100, 580), (880, 340, 1920, 580)]
before_png = baseline/'construction/components'/component/'exports/still.png'
after_png = revised/'construction/components'/component/'exports/still.png'
with Image.open(before_png) as a, Image.open(after_png) as b:
    a, b = a.convert('RGB'), b.convert('RGB')
    check(a.size == b.size == (1920, 1080), 'actual still dimensions retained')
    difference = ImageChops.difference(a, b).getbbox()
    check(difference is not None and difference[0] >= headline_box[0] and difference[1] >= headline_box[1]
          and difference[2] <= headline_box[2] and difference[3] <= headline_box[3], 'actual changed pixels stay within headline region')
    for box in fixed_boxes:
        check(ImageChops.difference(a.crop(box), b.crop(box)).getbbox() is None, 'unchanged still pixels '+str(box))
save('still.json', {'passed': True, 'before': str(before_png), 'after': str(after_png), 'changed_bbox': difference,
                    'headline_box': headline_box, 'native_objects_unchanged': 18, 'asset_files_unchanged': len(assets),
                    'checkout': str(revised), 'owner_approval': False})

if args.stage == 'movie':
    rendered_revision, rendered = job('headline-movie', 'construct.render', {'outputs': [{'component': component, 'format': 'mp4'}]}, revised_revision)
    before_movie = original/'construction/components'/component/'exports/film.mp4'
    after_movie = rendered/'construction/components'/component/'exports/film.mp4'
    support = json.loads((package/'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text())
    binaries = {}
    for name in ('ffmpeg', 'ffprobe'):
        binary = Path(shutil.which(name) or '')
        check(binary.is_file() and sha(binary) == support['engines'][name]['sha256'], 'independent '+name+' matches supporting pin')
        binaries[name] = binary
    prefix = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)']
    for label, movie in [('original', before_movie), ('revised', after_movie)]:
        probe = json.loads(run(label+' probe', [*prefix, binaries['ffprobe'], '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', movie]))
        check(len(probe['streams']) == 1 and probe['streams'][0]['codec_type'] == 'video', label+' movie is silent')
        stream = probe['streams'][0]
        check((stream['codec_name'], stream['width'], stream['height'], stream['r_frame_rate'], int(stream['nb_read_frames'])) == ('h264', 1920, 1080, '24/1', 288), label+' movie has complete expected stream')
        check(abs(float(probe['format']['duration'])-12) < .001, label+' movie is exactly twelve seconds')
    deadline = time.monotonic()+360
    processes, selectors_by_stream, errors = [], [], []
    frame_results = []
    def block(process, selector, size):
        while time.monotonic() < deadline:
            if selector.select(min(1, max(0, deadline-time.monotonic()))):
                return os.read(process.stdout.fileno(), min(size, 1 << 20))
        raise TimeoutError('Independent paired decoding exceeded six minutes')
    try:
        for label, movie in [('original', before_movie), ('revised', after_movie)]:
            error = (out/(label+'-decode.log')).open('wb')
            errors.append(error)
            command = [*prefix, binaries['ffmpeg'], '-nostdin', '-v', 'error', '-i', movie, '-map', '0:v:0', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
            process = subprocess.Popen(list(map(str, command)), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=error)
            processes.append(process)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            os.set_blocking(process.stdout.fileno(), False)
            selectors_by_stream.append(selector)
        for index in range(288):
            images, hashes = [], []
            for process, selector in zip(processes, selectors_by_stream):
                data = bytearray()
                while len(data) < 1920*1080*3:
                    part = block(process, selector, 1920*1080*3-len(data))
                    assert part, 'Incomplete decoded frame '+str(index)
                    data.extend(part)
                images.append(Image.frombytes('RGB', (1920, 1080), bytes(data)))
                hashes.append(hashlib.sha256(data).hexdigest())
            total, area = 0., 0
            for box in fixed_boxes:
                difference_image = ImageChops.difference(images[0].crop(box), images[1].crop(box))
                size = difference_image.width*difference_image.height
                total += sum(ImageStat.Stat(difference_image).mean)/3*size
                area += size
            mean = total/area
            check(mean <= 1.5, 'decoded fixed-region preservation '+str(index))
            check(images[0].crop(headline_box).tobytes() != images[1].crop(headline_box).tobytes(), 'decoded headline actually changed '+str(index))
            frame_results.append({'frame': index, 'original_rgb_sha256': hashes[0], 'revised_rgb_sha256': hashes[1], 'fixed_region_rgb_mean_error': mean})
            if index in (0, 78, 287):images[1].save(out/f'revised-frame-{index:03d}.png')
        for process, selector in zip(processes, selectors_by_stream):
            check(not block(process, selector, 1), 'paired decoder has no extra frames '+str(process.pid))
            check(process.wait(timeout=30) == 0, 'paired decoder exits successfully '+str(process.pid))
    finally:
        for process in processes:
            if process.poll() is None:process.kill();process.wait()
            process.stdout.close()
        for selector in selectors_by_stream:selector.close()
        for error in errors:error.close()
    save('decoded-frames.json', frame_results)
    save('movie.json', {'passed': True, 'movie': str(after_movie), 'movie_sha256': sha(after_movie), 'checkout': str(rendered),
                       'frames_each_movie': 288, 'all_frames_decoded': True, 'audio': 'none; intentionally silent',
                       'maximum_fixed_region_rgb_mean_error': max(f['fixed_region_rgb_mean_error'] for f in frame_results),
                       'owner_approval': False})

check(json.loads(run('verify package after '+args.stage, [package/'bin/a-dope-guard', 'verify'], fresh=True)) == verification, 'complete seal unchanged after '+args.stage)
check(all(sha(original/name) == digest for name, digest in input_hashes.items()), 'all original input bytes unchanged after '+args.stage)
usage = []
for row in jobs:
    manifest = json.loads((Path(row['checkout'])/'construction/manifest.json').read_text())
    check(manifest['model_requests'] == 0, 'no media model requests '+row['label'])
    usage.append({'label': row['label'], 'job': row['id'], 'model_requests': 0, 'worker_seconds': manifest['worker_seconds']})
save('usage.json', {'native_jobs': usage, 'quoted_charge_established': False, 'actual_billing_known': False, 'agent_cost_known': False})
result = {'stage': args.stage, 'passed': True, 'checks': len(cases), 'native_jobs': len(jobs), 'headline': list(headlines.values()),
          'owner_approval': False, 'scene_replacement_complete': False, 'full_campaign_complete': False, 'clean_machine': False, 'cloud': False, 'published': False}
save(args.stage+'-result.json', result)
print(json.dumps(result))
