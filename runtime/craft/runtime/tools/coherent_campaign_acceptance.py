"""Qualify native campaign reframing and a complete silent announcement.

Use a verified sealed package, an empty private output, and the retained original
hero checkout. Public CLI jobs author all creative output. Checks inspect actual
native state and decoded media; they do not supply owner aesthetic approval.
Stages can resume recorded jobs but never resubmit a failed or active attempt.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import selectors
import subprocess
import time
from PIL import Image, ImageChops, ImageStat

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('hero', type=Path)
parser.add_argument('--stage', choices=('socials', 'announcement'), required=True)
parser.add_argument('--expect-verification', type=Path, required=True,
                    help='Previously authenticated complete guard verification record')
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
package = args.package.resolve(strict=True)
hero = args.hero.resolve(strict=True)
out = args.output.absolute()
out.mkdir(parents=True, exist_ok=args.resume, mode=0o700)
import fcntl
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
      'exact previously authenticated guard and seal match')
save('verification-before.json', verification)
receipt(hero)
original = json.loads((hero/'construction/document.json').read_text())
check(len(original['components']) == 1 and original['components'][0]['engine'] == 'blender', 'hero uses typed native Blender')
component = original['components'][0]['id']
parameters = original['components'][0]['parameters']
check((parameters['width'], parameters['height'], parameters['fps'], parameters['frames']) == (1920, 1080, 24, 288), 'retained hero canvas and timeline match brief')
check(len(parameters['objects']) == 20, 'retained hero has twenty named parts')
asset = next(o['asset'] for o in parameters['objects'] if o['id'] == 'supplied_logo')
logo = hero/'construction/assets'/asset
source_hashes = {'manifest': sha(hero/'project.json'), 'document': sha(hero/'construction/document.json'), 'logo': sha(logo)}
save('source-inputs.json', {'hero': str(hero), 'hashes': source_hashes, 'package': str(package)})
cli('limits', 'limits', '--wall-seconds', '3600', '--cpu-seconds', '14400', '--memory-mib', '8192', '--attempt-mib', '4096')
imported = cli('import hero', 'import-project', hero, 'Coherent campaign native variants')
owner, original_revision = imported['project']['id'], imported['revision']['id']
# Admission checks bytes. Explicit verification below establishes native reopening.
base_revision, base = job('base-native-verify', 'construct.verify', {}, original_revision)
base_document = json.loads((base/'construction/document.json').read_text())
check(base_document == original, 'fresh-state native reopening retains complete source document')
check((base/'construction/assets'/asset).read_bytes() == logo.read_bytes(), 'fresh-state native reopening retains exact supplied logo bytes')
base_hash = json.loads((base/'construction/manifest.json').read_text())['document_sha256']
base_native = json.loads((base/'construction/components'/component/'native/inspection.json').read_text())


def verify_variant(folder, expected, label):
    actual = json.loads((folder/'construction/document.json').read_text())
    check(actual['components'][0]['parameters'] == expected, label+' complete typed document equals requested reframing')
    native = json.loads((folder/'construction/components'/component/'native/inspection.json').read_text())
    check(native['ids'] == sorted(o['id'] for o in expected['objects']), label+' retains all native object identities')
    check(native['native_geometry_and_keys_verified'], label+' actual native geometry is checked')
    for obj in expected['objects']:
        check(native['objects'][obj['id']]['construction'] == obj, label+' native source '+obj['id'])
        if obj['kind'] == 'text':
            check(native['objects'][obj['id']]['font_packed'] and native['objects'][obj['id']]['text'] == obj['text'], label+' editable packed text '+obj['id'])
    check((folder/'construction/assets'/asset).read_bytes() == logo.read_bytes(), label+' original logo bytes unchanged')
    return native


def verify_placement(png, expected, label):
    """Check rendered positions independently of saved object metadata."""
    objects = {obj['id']: obj for obj in expected['objects']}
    samples = {}
    with Image.open(png) as opened:
        image = opened.convert('RGB')
        check(image.size == (expected['width'], expected['height']), label+' actual PNG dimensions')
        for name in ('frame_top', 'frame_bottom', 'frame_left', 'frame_right'):
            obj = objects[name]
            point = (round(obj['x']), round(obj['y']))
            rgb = image.getpixel(point)
            check(rgb[0] > 200 and rgb[1] > 200 and rgb[2] > 190, label+' rendered frame placement '+name)
            samples[name] = {'point': point, 'rgb': rgb}
        logo_object = objects['supplied_logo']
        box = (round(logo_object['x']-logo_object['width']/2), round(logo_object['y']-logo_object['height']/2),
               round(logo_object['x']+logo_object['width']/2), round(logo_object['y']+logo_object['height']/2))
        check(0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height, label+' supplied logo placement stays inside canvas')
        red, green, _ = image.crop(box).split()
        ink = ImageChops.multiply(red.point(lambda v: 255 if v > 150 else 0), green.point(lambda v: 255 if v > 150 else 0))
        ink_pixels = ink.histogram()[255]
        check(ink_pixels >= 300, label+' supplied logo actually renders at requested placement')
    return {'frame_samples': samples, 'logo_box': box, 'logo_visible_ink_pixels': ink_pixels}


if args.stage == 'socials':
    variants = {}
    layouts = [('square', 1080, 1080, 790, .75, 100, 380, 270, 80, 350, 60, 430, 25),
               ('portrait-feed', 1080, 1350, 930, 1., 110, 420, 320, 96, 420, 72, 520, 28),
               ('portrait-story', 1080, 1920, 1300, 1.25, 140, 420, 440, 110, 570, 86, 710, 32)]
    for name, width, height, center, scale, ly, lw, hy, hs, sy, ss, cy, cs in layouts:
        target = copy.deepcopy(parameters)
        target.update(width=width, height=height)
        for obj in target['objects']:
            key = obj['id']
            if key == 'background':
                obj.update(width=width, height=height, x=width/2, y=height/2)
            elif key == 'supplied_logo':
                obj.update(x=width/2, y=ly, width=lw, height=lw*70/471.2)
            elif key == 'headline_one':
                obj.update(x=width/2, y=hy, size=hs)
            elif key == 'headline_two':
                obj.update(x=width/2, y=sy, size=ss)
            elif key == 'supporting_copy':
                obj.update(x=width/2, y=cy, size=cs)
            else:
                obj['x'] = width/2+(obj['x']-1395)*scale
                obj['y'] = center+(obj['y']-540)*scale
                for field in ('width', 'height'):
                    obj[field] *= scale
        prior = next((j for j in jobs if j['label'] == name+'-reframe'
                      and j.get('result', {}).get('state') == 'succeeded'), None)
        if prior is not None:
            # Preserve the successful square from the first fixture version.
            # Its later stale-head refusal remains a distinct failed job.
            variant_owner, variant_source, edit_label = prior['result']['project'], prior['source_revision'], name+'-reframe'
        else:
            branch = cli(name+' independent project', 'import-project', hero, 'Campaign '+name)
            variant_owner, variant_source, edit_label = branch['project']['id'], branch['revision']['id'], name+'-native-reframe'
        changed, edited = job(edit_label, 'construct.edit', {'document_sha256': base_hash,
            'edits': [{'component': component, 'action': 'set', 'path': ['parameters'], 'before': parameters, 'value': target}]}, variant_source, project=variant_owner)
        rendered, final = job(name+'-render', 'construct.render', {'outputs': [{'component': component, 'format': 'png', 'frame': 0}]}, changed, project=variant_owner)
        verify_variant(final, target, name)
        png = final/'construction/components'/component/'exports/still.png'
        placement = verify_placement(png, target, name)
        variants[name] = {'revision': rendered, 'checkout': str(final), 'png': str(png), 'png_sha256': sha(png), 'size': [width, height], 'parameters': target, 'rendered_placement': placement}
    save('socials.json', {'passed': True, 'variants': variants, 'owner_visual_approval': False})
else:
    branch = cli('announcement independent project', 'import-project', hero, 'Campaign announcement')
    film_owner, film_source = branch['project']['id'], branch['revision']['id']
    target = copy.deepcopy(parameters)
    strip = next(o for o in target['objects'] if o['id'] == 'strip_6')
    strip['y'] = 540
    strip['keys'] = {'y': [[0, 540, 'CONSTANT'], [72, 540, 'LINEAR'], [84, 595, 'CONSTANT'], [287, 595, 'CONSTANT']]}
    animated, edited = job('announcement-animation', 'construct.edit', {'document_sha256': base_hash,
        'edits': [{'component': component, 'action': 'set', 'path': ['parameters'], 'before': parameters, 'value': target}]}, film_source, project=film_owner)
    native = verify_variant(edited, target, 'announcement')
    check(all(row == native['objects'][name] for name, row in base_native['objects'].items() if name != 'strip_6'), 'announcement preserves nineteen other complete native objects')
    rendered, final = job('announcement-movie', 'construct.render', {'outputs': [{'component': component, 'format': 'mp4'}]}, animated, project=film_owner)
    movie = final/'construction/components'/component/'exports/film.mp4'
    support = json.loads((package/'lib/dobe/runtime/studio_runtime/construction_data/support.json').read_text())
    binaries = {}
    for name in ('ffmpeg', 'ffprobe'):
        binary = Path(shutil.which(name) or '')
        check(binary.is_file() and sha(binary) == support['engines'][name]['sha256'], 'independent '+name+' matches exact supporting pin')
        binaries[name] = binary
    prefix = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)']
    probe = json.loads(run('independent film probe', [*prefix, binaries['ffprobe'], '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', movie]))
    check(len(probe['streams']) == 1 and probe['streams'][0]['codec_type'] == 'video', 'announcement is explicitly silent')
    stream = probe['streams'][0]
    check((stream['width'], stream['height'], stream['r_frame_rate'], int(stream['nb_read_frames'])) == (1920, 1080, '24/1', 288), 'actual announcement has all 288 full-size frames at 24 fps')
    check(abs(float(probe['format']['duration'])-12) < .001, 'actual announcement duration is twelve seconds')
    decode = [*prefix, binaries['ffmpeg'], '-nostdin', '-v', 'error', '-i', movie, '-map', '0:v:0', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
    reference = Image.open(hero/'construction/components'/component/'exports/still.png').convert('RGB').crop((0, 0, 1000, 1080))
    frames = []
    with (out/'decode.log').open('wb') as error_log:
        process = subprocess.Popen(list(map(str, decode)), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=error_log)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        os.set_blocking(process.stdout.fileno(), False)
        deadline = time.monotonic()+360
        def read_block(size):
            while time.monotonic() < deadline:
                if selector.select(min(1, max(0, deadline-time.monotonic()))):
                    return os.read(process.stdout.fileno(), min(size, 1 << 20))
            raise TimeoutError('Independent movie decoder exceeded six minutes')
        try:
            frame_bytes = 1920*1080*3
            for index in range(288):
                data = bytearray()
                while len(data) < frame_bytes:
                    block = read_block(frame_bytes-len(data))
                    assert block, 'Decoded frame is truncated: '+str(index)
                    data.extend(block)
                check(len(data) == frame_bytes, 'decoded frame '+str(index)+' is complete')
                image = Image.frombytes('RGB', (1920, 1080), bytes(data))
                fixed_error = sum(ImageStat.Stat(ImageChops.difference(image.crop((0, 0, 1000, 1080)), reference)).mean)/3
                red, green, blue = image.crop((1080, 200, 1720, 900)).split()
                mask = ImageChops.multiply(ImageChops.multiply(red.point(lambda v: 255 if v > 150 else 0), green.point(lambda v: 255 if v > 200 else 0)), blue.point(lambda v: 255 if v < 80 else 0))
                box = mask.getbbox()
                expected = 540 if index <= 72 else 595 if index >= 84 else 540+(index-72)*55/12
                center = (box[1]+box[3])/2+200 if box else None
                check(center is not None and abs(center-expected) <= 2, 'decoded selected strip position '+str(index))
                check(fixed_error <= 1.5, 'decoded fixed typography and logo region '+str(index))
                frames.append({'frame': index, 'rgb_sha256': hashlib.sha256(data).hexdigest(), 'selected_center_y': center, 'expected_center_y': expected, 'fixed_region_rgb_mean_error': fixed_error})
                if index in (0, 72, 78, 84, 287):
                    image.save(out/('announcement-frame-'+str(index).zfill(3)+'.png'))
            check(not read_block(1), 'decoded stream has no extra frames')
            check(process.wait(timeout=30) == 0, 'complete independent decoder exits successfully')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            selector.close()
    save('decoded-frames.json', frames)
    save('announcement.json', {'passed': True, 'revision': rendered, 'checkout': str(final), 'movie': str(movie), 'movie_sha256': sha(movie), 'frames': 288, 'duration_seconds': 12, 'audio': 'none; intentionally silent', 'all_frames_decoded': True, 'maximum_fixed_region_rgb_mean_error': max(f['fixed_region_rgb_mean_error'] for f in frames), 'owner_visual_approval': False})

check(json.loads(run('verify package after '+args.stage, [package/'bin/a-dope-guard', 'verify'], fresh=True)) == verification, 'sealed package unchanged after '+args.stage)
check(source_hashes == {'manifest': sha(hero/'project.json'), 'document': sha(hero/'construction/document.json'), 'logo': sha(logo)}, 'retained source hero remains unchanged after '+args.stage)
result = {'stage': args.stage, 'passed': True, 'checks': len(cases), 'durable_jobs': len(jobs),
          'successful_jobs': sum(j['result']['state'] == 'succeeded' for j in jobs),
          'preserved_failed_jobs': [j['id'] for j in jobs if j['result']['state'] == 'failed'],
          'owner_approval': False, 'complete_campaign': False, 'clean_machine': False, 'cloud': False, 'published': False}
save(args.stage+'-result.json', result)
print(json.dumps(result))
