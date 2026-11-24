"""Qualify editable Photo libraries through a sealed package's public CLI.

Run with bundled Python: photo_acceptance.py PACKAGE NEW_OUTPUT --photo PNG.
The supplied PNG is owned photographic source material, read without modification.
Numeric fixtures are generated locally. No network, services or editor windows.
--resume checks inputs and reuses completed jobs; admitted running work is never
replayed. Keep the native library, originals and receipt together when importing.
"""
import argparse
import array
import copy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
import zlib
from PIL import Image, ImageOps

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--photo', type=Path, required=True)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
package = args.package.resolve(strict=True)
out = args.output.absolute()
photo = args.photo.resolve(strict=True)
out.mkdir(parents=True, exist_ok=args.resume, mode=0o700)
lock = (out / 'fixture.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
for folder in ('home', 'sources'):
    (out / folder).mkdir(exist_ok=args.resume, mode=0o700)
cli = package / 'bin/a-dope-cli'
state = out / 'state'
env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
logs = json.loads((out / 'commands.json').read_text()) if args.resume else []
jobs = json.loads((out / 'jobs.json').read_text()) if args.resume and (out / 'jobs.json').exists() else []
cases = []


def save(name, value):
    (out / name).write_text(json.dumps(value, indent=2) + '\n')


def check(value, label):
    assert value, label
    cases.append(label)
    save('cases.json', cases)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def immutable(path, data):
    if path.exists():
        assert path.read_bytes() == data, 'fixture input changed: ' + str(path)
    else:
        path.write_bytes(data)


def run(label, arguments, expected=0, fresh=False):
    arguments = list(map(str, arguments))
    files = {p: digest(p) for p in arguments if Path(p).is_file()}
    prior = next((r for r in logs if r['label'] == label), None)
    if prior and not fresh:
        assert (prior['args'], prior['files'], prior['exit']) == (arguments, files, expected), label
        return json.loads(prior['stdout']) if prior['stdout'].strip() else None
    start = time.monotonic()
    process = subprocess.run(arguments, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    logs.append({'label': label, 'args': arguments, 'files': files, 'exit': process.returncode,
                 'seconds': time.monotonic() - start, 'stdout': process.stdout, 'stderr': process.stderr})
    save('commands.json', logs)
    assert process.returncode == expected, (label, process.returncode, process.stderr)
    return json.loads(process.stdout) if process.stdout.strip() else None


def call(label, *arguments, fresh=False):
    return run(label, [cli, '--state', state, *arguments], fresh=fresh)


def verify_checkout(directory):
    receipt = json.loads((directory / 'project.json').read_text())
    for item in receipt['files']:
        p = directory / item['path']
        assert p.stat().st_size == item['bytes'] and digest(p) == item['sha256'], item['path']
    return receipt


def job(label, project, operation, parameters, source=None, success=True):
    request = out / (label + '-request.json')
    immutable(request, (json.dumps(parameters, sort_keys=True) + '\n').encode())
    old = next((j for j in jobs if j['label'] == label), None)
    if old:
        assert (old['project'], old['operation'], old['parameters'], old['source']) == (project, operation, parameters, source), label
    arguments = ['submit', project, operation, '--parameters', request, '--key', label]
    if source:
        arguments += ['--source', source]
    submitted = call(label + ' submit', *arguments)
    if not old:
        old = {'label': label, 'project': project, 'operation': operation, 'parameters': parameters,
               'source': source, 'stateDirectory': str(state), 'id': submitted['id']}
        jobs.append(old)
        save('jobs.json', jobs)
    if 'result' not in old:
        observed = call(label + ' admitted state', 'job', submitted['id'], fresh=True)
        if observed['state'] == 'queued':
            call(label + ' worker', 'worker', '--once')
        elif observed['state'] not in ('succeeded', 'failed'):
            raise RuntimeError('Reconcile admitted job before resuming: ' + json.dumps(observed))
        old['result'] = call(label + ' result', 'job', submitted['id'], fresh=True)
        save('jobs.json', jobs)
    result = old['result']
    assert result['state'] == ('succeeded' if success else 'failed'), result
    if not success:
        check(result.get('result_revision') is None, label + ' publishes no revision')
        return result
    destination = out / label
    call(label + ' checkout', 'checkout', result['result_revision'], destination)
    receipt = verify_checkout(destination)
    v = receipt['validation']
    check(v['native_cold_reopen'] and v['pixel_roundtrip_equal'] and v['source_hashes_preserved']
          and v['editable_photo_ids_and_history_preserved'], label + ' preserves editable source through native cold reopening')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def decode_png(path):
    """Decode scanlines independently, retaining 16-bit samples without Pillow truncation."""
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    cursor = 8
    packed = []
    header = None
    ended = False
    while cursor < len(data):
        length = struct.unpack_from('>I', data, cursor)[0]
        tag = data[cursor + 4:cursor + 8]
        body = data[cursor + 8:cursor + 8 + length]
        assert len(body) == length
        assert zlib.crc32(tag + body) & 0xffffffff == struct.unpack_from('>I', data, cursor + 8 + length)[0]
        if tag == b'IHDR':
            assert header is None
            header = struct.unpack('>IIBBBBB', body)
        elif tag == b'IDAT':
            packed.append(body)
        elif tag == b'IEND':
            ended = True
        cursor += length + 12
    assert ended and cursor == len(data)
    width, height, depth, color, compression, filtering, interlace = header
    assert 0 < width <= 8192 and 0 < height <= 8192 and depth in (8, 16) and color in (2, 6)
    assert (compression, filtering, interlace) == (0, 0, 0)
    channels = 3 if color == 2 else 4
    bpp = channels * (depth // 8)
    stride = width * bpp
    raw = zlib.decompress(b''.join(packed))
    assert len(raw) == height * (stride + 1)
    previous = bytearray(stride)
    pixels = bytearray()
    for y in range(height):
        filter_type = raw[y * (stride + 1)]
        assert filter_type <= 4
        row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            left = row[i - bpp] if i >= bpp else 0
            above = previous[i]
            corner = previous[i - bpp] if i >= bpp else 0
            p = left + above - corner
            distances = (abs(p - left), abs(p - above), abs(p - corner))
            paeth = (left, above, corner)[distances.index(min(distances))]
            predictor = (0, left, above, (left + above) // 2, paeth)[filter_type]
            row[i] = (row[i] + predictor) & 255
        pixels.extend(row)
        previous = row
    values = array.array('H' if depth == 16 else 'B')
    values.frombytes(pixels)
    if depth == 16 and sys.byteorder == 'little':
        values.byteswap()
    return {'width': width, 'height': height, 'depth': depth, 'channels': channels,
            'values': values, 'pixelSHA256': hashlib.sha256(pixels).hexdigest()}


def native(directory):
    return json.loads((directory / 'native/library/catalog.snap').read_text())


def mapping(directory):
    return json.loads((directory / 'native/objects.json').read_text())


def entry(directory, name):
    return native(directory)['catalog']['photos'][str(mapping(directory)['photos'][name]['id'])]


def originals(directory):
    return {p.name: digest(p) for p in (directory / 'assets').iterdir() if p.is_file()}


def exact_revision(before, after, requests):
    """Independently compare requested settings, identities, metadata and old history."""
    old = native(before)['catalog']
    new = native(after)['catalog']
    names = mapping(before)['photos']
    assert names == mapping(after)['photos']
    assert {k: v for k, v in old.items() if k != 'photos'} == {k: v for k, v in new.items() if k != 'photos'}
    selected = {str(names[r['name']]['id']): r for r in requests}
    for identity, previous in old['photos'].items():
        current = new['photos'][identity]
        if identity not in selected:
            assert previous == current
            continue
        specification = selected[identity]
        expected = copy.deepcopy(previous['develop'])
        for control, value in specification.get('adjustments', {}).items():
            section, field = control.split('.')
            expected[section][field] = value
            if section == 'wb':
                expected['wb']['mode'] = 'custom'
        if 'crop' in specification:
            expected['crop']['geometry']['rect'] = dict(zip(('x0', 'y0', 'x1', 'y1'), specification['crop']))
        assert current['develop'] == expected
        assert {k: v for k, v in previous.items() if k not in ('develop', 'history', 'versions', 'edited')} == {
            k: v for k, v in current.items() if k not in ('develop', 'history', 'versions', 'edited')}
        for key in ('history', 'versions'):
            assert current[key][:len(previous[key])] == previous[key]
    assert originals(before) == originals(after)


def encode_image(path, image, format, **options):
    buffer = io.BytesIO()
    image.save(buffer, format=format, **options)
    immutable(path, buffer.getvalue())


def synthetic_dng(path):
    """Owned uncompressed RGGB samples with no embedded camera preview."""
    width, height = 120, 80
    samples = [64 + int((x / (width - 1) * .5 + y / (height - 1) * .3 + .1) * 2700)
               for y in range(height) for x in range(width)]
    pixels = struct.pack('<' + 'H' * len(samples), *samples)
    entries = []
    def tag(number, kind, values):
        if kind in (1, 2):
            raw, count = values, len(values)
        elif kind in (3, 4):
            count = len(values)
            raw = struct.pack('<' + ('H' if kind == 3 else 'I') * count, *values)
        else:
            count = len(values)
            raw = b''.join(struct.pack('<II' if kind == 5 else '<ii', *v) for v in values)
        entries.append((number, kind, count, raw))
    for number, value in ((256, width), (257, height), (278, height), (279, len(pixels)), (273, 0)):
        tag(number, 4, [value])
    for number, value in ((258, 16), (259, 1), (262, 32803), (277, 1), (284, 1), (274, 1), (50778, 21)):
        tag(number, 3, [value])
    tag(33421, 3, [2, 2]); tag(33422, 1, bytes([0, 1, 1, 2]))
    tag(50706, 1, bytes([1, 4, 0, 0])); tag(50707, 1, bytes([1, 1, 0, 0]))
    tag(50708, 2, b'A dope CLI synthetic RGGB\0'); tag(50713, 3, [1, 1])
    tag(50714, 5, [(64, 1)]); tag(50717, 4, [4095])
    tag(50721, 10, [(1 if i % 4 == 0 else 0, 1) for i in range(9)])
    tag(50728, 5, [(1, 1)] * 3)
    entries.sort()
    offset = 8 + 2 + 12 * len(entries) + 4
    extra = bytearray()
    encoded = []
    for number, kind, count, raw in entries:
        if len(raw) > 4:
            field = struct.pack('<I', offset + len(extra)); extra.extend(raw)
            if len(extra) % 2:
                extra.append(0)
        else:
            field = raw.ljust(4, b'\0')
        encoded.append((number, kind, count, field))
    strip = offset + len(extra)
    body = b''.join(struct.pack('<HHI', n, k, c) + (struct.pack('<I', strip) if n == 273 else v)
                    for n, k, c, v in encoded)
    immutable(path, b'II' + struct.pack('<HIH', 42, 8, len(entries)) + body + bytes(4) + extra + pixels)


verification = run('verify payload before', [package / 'bin/a-dope-guard', 'verify'], fresh=True)
check(verification['verified'], 'sealed package verifies before Photo acceptance')
save('verification-before.json', verification)
# Photographic delivery is separate from numeric format fixtures.
with Image.open(photo) as image:
    assert image.format == 'PNG' and image.mode in ('RGB', 'RGBA') and max(image.size) <= 2048
    if image.mode == 'RGBA':
        assert image.getchannel('A').getextrema() == (255, 255), 'photographic source must be opaque'
    source_size = image.size
    source_rgb = image.convert('RGB').tobytes()
hero = out / 'sources/photograph.png'
immutable(hero, photo.read_bytes())
project = call('photographic project', 'create-project', 'A dope CLI / Editable photographic set')['id']
asset = call('photographic source', 'import-asset', project, hero)['id']
creation = {'photos': [{'name': 'photograph', 'asset': asset, 'format': 'png'}], 'bit_depth': 16}
r0, d0 = job('original', project, 'photo.create', creation)
base = decode_png(d0 / 'exports/photograph.png')
check((base['width'], base['height'], base['depth']) == (*source_size, 16), 'photographic baseline retains full dimensions at 16-bit output precision')
error = max(abs(base['values'][i * base['channels'] + k] - source_rgb[i * 3 + k] * 257)
            for i in range(source_size[0] * source_size[1]) for k in range(3))
# The source is eight-bit sRGB. Native working-space conversion uses floats;
# require exact reconstruction at source precision, not invented 16-bit input
# fidelity. Separate PNG/TIFF ramps below qualify genuinely 16-bit sources.
check(all(round(base['values'][i * base['channels'] + k] / 257) == source_rgb[i * 3 + k]
          for i in range(source_size[0] * source_size[1]) for k in range(3)),
      'neutral photographic import reconstructs every original eight-bit RGB value')
crop = [0.1875, 0.15625, 0.8125, 0.9375]
requests = [{'name': 'photograph', 'crop': crop}]
r1, d1 = job('editorial', project, 'photo.edit', {'photos': requests}, r0)
exact_revision(d0, d1, requests)
check(True, 'editorial crop preserves all unrequested settings, native metadata, prior history and source bytes')
editorial = decode_png(d1 / 'exports/photograph.png')
expected_size = (round(source_size[0] * .625), round(source_size[1] * .78125))
check((editorial['width'], editorial['height']) == expected_size, 'editorial crop has the exact requested pixel dimensions')
requests = [{'name': 'photograph', 'adjustments': {'color.saturation': -100}}]
r2, d2 = job('monochrome', project, 'photo.edit', {'photos': requests}, r1)
exact_revision(d1, d2, requests)
mono = decode_png(d2 / 'exports/photograph.png')
check((mono['width'], mono['height']) == expected_size, 'monochrome revision preserves the editorial crop')
# Native desaturation zeros OkLab chroma; its floating-point conversion back
# to sRGB is approximately neutral. Bound visible channel imbalance to one
# eight-bit display level and record the actual sixteen-bit spread.
mono_spread = max(max(mono['values'][i:i+3]) - min(mono['values'][i:i+3])
                  for i in range(0, len(mono['values']), mono['channels']))
check(mono_spread <= 257, 'monochrome channel spread stays within one eight-bit display level')
check(originals(d0) == originals(d1) == originals(d2), 'all photographic revisions retain the exact original image')
state = out / 'portable-state'
imported = call('portable import', 'import-project', d2, 'Portable photographic set')
check(imported['revision']['validation']['scope'] == 'bundle_integrity'
      and not imported['revision']['validation']['native_cold_reopen'], 'portable import reports integrity only before native reopening')
restore = [{'name': 'photograph', 'adjustments': {'color.saturation': 0}, 'crop': [0, 0, 1, 1]}]
r3, d3 = job('portable-restored', imported['project']['id'], 'photo.edit', {'photos': restore}, imported['revision']['id'])
exact_revision(d2, d3, restore)
check(entry(d3, 'photograph')['develop'] == entry(d0, 'photograph')['develop'], 'portable revision restores original development settings')
check(decode_png(d3 / 'exports/photograph.png')['pixelSHA256'] == base['pixelSHA256'], 'portable restoration reproduces every original 16-bit pixel')
# Reuse the established precision/orientation/sensor fixture with the guarded CLI.
state = out / 'state'
fp = call('format project', 'create-project', 'Photo numeric format acceptance')['id']
specifications = []
for format in ('png', 'tiff'):
    values = [(i * 5 + 1000 + (100 if format == 'tiff' else 0)) % 65536 for i in range(300 * 32)]
    image = Image.frombytes('I;16', (300, 32), struct.pack('<' + 'H' * len(values), *values))
    path = out / 'sources' / ('precision.' + format)
    encode_image(path, image, format.upper())
    a = call(format + ' source', 'import-asset', fp, path)['id']
    specifications.append({'name': format, 'asset': a, 'format': format})
image = Image.new('RGB', (120, 80))
image.putdata([((180, 40, 30), (40, 170, 50), (30, 60, 190), (190, 160, 30))[(y >= 40) * 2 + (x >= 60)]
               for y in range(80) for x in range(120)])
exif = Image.Exif(); exif[274] = 6
oriented_source = out / 'sources/oriented.jpeg'
encode_image(oriented_source, image, 'JPEG', quality=95, exif=exif)
a = call('oriented source', 'import-asset', fp, oriented_source)['id']
specifications.append({'name': 'oriented', 'asset': a, 'format': 'jpeg'})
raw = out / 'sources/sensor.dng'; synthetic_dng(raw)
a = call('sensor source', 'import-asset', fp, raw)['id']
specifications.append({'name': 'sensor', 'asset': a, 'format': 'dng',
                       'adjustments': {'light.exposure': .75, 'wb.temp': 7200, 'wb.tint': 8}, 'crop': [.1, .1, .9, .9]})
f0, fd0 = job('formats', fp, 'photo.create', {'photos': specifications, 'bit_depth': 16})
precision = {}
for name in ('png', 'tiff'):
    decoded = decode_png(fd0 / 'exports' / (name + '.png'))
    distinct = len(set(decoded['values'][::decoded['channels']]))
    check((decoded['width'], decoded['height'], decoded['depth']) == (300, 32, 16)
          and distinct > 256, name + ' retains more than 256 distinct levels in 16-bit source/output')
    precision[name] = distinct
oriented = decode_png(fd0 / 'exports/oriented.png')
check((oriented['width'], oriented['height']) == (80, 120), 'native JPEG decode honors EXIF orientation six')
with Image.open(oriented_source) as image:
    reference = ImageOps.exif_transpose(image).convert('RGB')
    for x, y in ((15, 20), (65, 20), (15, 100), (65, 100)):
        expected = reference.getpixel((x, y));index = (y * 80 + x) * oriented['channels']
        check(max(abs(oriented['values'][index + k] - expected[k] * 257) for k in range(3)) <= 3 * 257,
              'oriented JPEG retains the correct corner color at ' + str((x, y)))
sensor = decode_png(fd0 / 'exports/sensor.png')
check((sensor['width'], sensor['height'], sensor['depth']) == (96, 64, 16), 'synthetic sensor RAW uses the requested crop and 16-bit export')
check(entry(fd0, 'sensor')['kind'] == 'raw' and not entry(fd0, 'sensor').get('preview_only'), 'synthetic DNG is decoded as sensor RAW without a preview fallback')
requests = [{'name': 'sensor', 'adjustments': {'light.exposure': 1.25}}]
f1, fd1 = job('raw-revised', fp, 'photo.edit', {'photos': requests}, f0)
exact_revision(fd0, fd1, requests)
check(True, 'RAW exposure revision preserves every untargeted native photo and prior history')
for name in ('png', 'tiff', 'oriented'):
    check((fd0 / 'exports' / (name + '.png')).read_bytes() == (fd1 / 'exports' / (name + '.png')).read_bytes(),
          'RAW revision preserves exact untargeted ' + name + ' export bytes')
check(sum(decode_png(fd1 / 'exports/sensor.png')['values']) > sum(sensor['values']), 'higher RAW exposure produces a brighter rendered sensor fixture')
requests = [{'name': 'oriented', 'adjustments': {'color.saturation': -100}, 'crop': [.25, .25, .75, .75]}]
f2, fd2 = job('eight-bit', fp, 'photo.edit', {'photos': requests, 'bit_depth': 8}, f1)
exact_revision(fd1, fd2, requests)
for name in ('png', 'tiff', 'oriented', 'sensor'):
    check(decode_png(fd2 / 'exports' / (name + '.png'))['depth'] == 8, 'output-depth revision re-exports ' + name + ' at eight bits')
check((decode_png(fd2 / 'exports/oriented.png')['width'], decode_png(fd2 / 'exports/oriented.png')['height']) == (40, 60),
      'crop applies in the oriented JPEG coordinate system')
# Refusals must leave their source heads intact, including a valid earlier edit in a batch.
head = call('format head before refusals', 'project', fp)
failed = job('partial-batch', fp, 'photo.edit', {'photos': [
    {'name': 'sensor', 'adjustments': {'light.exposure': 0}},
    {'name': 'missing', 'adjustments': {'light.exposure': 0}}]}, f2, False)
check('unknown photo' in json.dumps(failed), 'a bad later target refuses the complete edit batch')
check(call('format head after refusal', 'project', fp) == head, 'partial batch refusal preserves the project head')
wrong = call('wrong format project', 'create-project', 'Wrong declared source format')['id']
a = call('wrong format source', 'import-asset', wrong, hero)['id']
wrong_head = call('wrong format head before', 'project', wrong)
failed = job('wrong-format', wrong, 'photo.create', {'photos': [{'name': 'wrong', 'asset': a, 'format': 'jpeg'}]}, success=False)
check('source format differs' in json.dumps(failed), 'a false source format declaration is refused')
check(call('wrong format head after', 'project', wrong) == wrong_head, 'failed import publishes no project head')
malformed = out / 'external-profile-project'
if not malformed.exists():
    shutil.copytree(fd2, malformed)
model = native(fd2)
identity = str(mapping(fd2)['photos']['sensor']['id'])
model['catalog']['photos'][identity]['develop']['profile']['id'] = 'file:///outside/photo-profile.json'
changed = malformed / 'native/library/catalog.snap'
changed.write_text(json.dumps(model, sort_keys=True) + '\n')
receipt = json.loads((fd2 / 'project.json').read_text())
record = next(f for f in receipt['files'] if f['path'] == 'native/library/catalog.snap')
record.update(bytes=changed.stat().st_size, sha256=digest(changed))
(malformed / 'project.json').write_text(json.dumps(receipt, indent=2) + '\n')
verify_checkout(malformed)
imported = call('external profile import', 'import-project', malformed, 'Unsupported external profile')
bad_head = call('external profile head before', 'project', imported['project']['id'])
failed = job('external-profile', imported['project']['id'], 'photo.edit', {'photos': [
    {'name': 'sensor', 'adjustments': {'light.exposure': 0}}]}, imported['revision']['id'], False)
check('unqualified profiles' in json.dumps(failed), 'internally consistent portable receipts do not admit an external native profile')
check(call('external profile head after', 'project', imported['project']['id']) == bad_head, 'native profile refusal preserves its imported head')
groups = []
for directory in (out / 'state', out / 'portable-state'):
    with sqlite3.connect('file:' + str(directory / 'studio.sqlite3') + '?mode=ro', uri=True) as db:
        check(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], directory.name + ' database integrity passes')
        groups += [r[0] for r in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
for group in groups:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('native execution group remains: ' + str(group))
check(len(groups) == len(jobs), 'every durable job has an execution record and all execution groups are absent')
for record in jobs:
    if 'checkout' in record:
        verify_checkout(Path(record['checkout']))
check(True, 'all final portable receipts and original source hashes remain exact')
check(run('verify payload after', [package / 'bin/a-dope-guard', 'verify'], fresh=True) == verification,
      'Photo acceptance leaves the complete sealed payload unchanged')
save('context.json', {'original': str(d0), 'editorial': str(d1), 'monochrome': str(d2), 'portable': str(d3),
                     'photoSourceSHA256': digest(hero), 'sourceSize': source_size, 'neutralMaximum16BitError': error,
                     'monochromeMaximum16BitChannelSpread': mono_spread,
                     'precisionLevels': precision, 'creationParameters': creation,
                     'editorialParameters': {'photos': [{'name': 'photograph', 'crop': crop}]},
                     'monochromeParameters': {'photos': [{'name': 'photograph', 'adjustments': {'color.saturation': -100}}]},
                     'restorationParameters': {'photos': restore}})
save('evidence.json', {'passed': True, 'checks': len(cases), 'cases': cases, 'nativeJobs': len(jobs),
                      'successfulNativeJobs': sum(j['result']['state'] == 'succeeded' for j in jobs),
                      'expectedFailedNativeJobs': sum(j['result']['state'] == 'failed' for j in jobs),
                      'groups': groups, 'allNativeGroupsAbsent': True, 'package': str(package), 'verification': verification,
                      'inputFormats': ['PNG', 'JPEG', 'TIFF', 'DNG'], 'outputDepths': [8, 16],
                      'ownerVisualApproval': False, 'generalCameraRawFidelityQualified': False,
                      'completeReleaseQualified': False, 'network': False})
print(json.dumps({'passed': True, 'checks': len(cases), 'nativeJobs': len(jobs), 'editorial': str(d1)}))
