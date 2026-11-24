#!/usr/bin/env python3
"""Compare independent and native Write picture decoders on original fixtures."""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_container as container, write_resources as resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; calls = []; comparisons = {}; started = time.monotonic()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def refuse(label, action):
        try: action()
        except ValueError as error: refusals.append({'case': label, 'error': str(error)}); checks.append(label+' refused')
        else: raise AssertionError('accepted '+label)

    def native(*arguments, fail=False):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=60)
        index = len(calls); calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        if fail:
            check(result.returncode != 0 and not result.stdout, 'native refusal emits no partial pixel packet: '+str(arguments[0]))
        elif result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def encoded(data): return base64.b64encode(data).decode('ascii')

    def packet(info, rgba):
        header = json.dumps(info).encode(); return b'DOBEPIC1'+struct.pack('<I', len(header))+header+rgba

    try:
        source = args.fixtures/'brief.json'; original = source.read_bytes(); doc = container.strict_json(original)
        before = copy.deepcopy(doc); report = resources.inspect(doc)
        check(report['pixels'] == 32*24 and report['decoded_bytes'] == 121, 'original embedded source inventory has independent dimensions and byte count')
        check(doc == before and not report['engine_admission_complete'], 'resource inventory preserves original model and does not authorize native execution')
        data = base64.b64decode(next(iter(doc['media'].values())))
        legacy = copy.deepcopy(doc); legacy['media'] = {'image1.png': list(data)}
        check(resources.inspect(legacy)['images']['image1.png']['sha256'] == report['images']['image1.png']['sha256'],
              'legacy byte arrays resolve to exact original bytes without rewriting their encoding')
        retained = copy.deepcopy(doc); retained['passthrough'] = {'word/fonts/original.odttf': encoded(b'opaque-font'), 'word/fontTable.xml': encoded(b'<retained/>')}
        retained_report = resources.inspect(retained)
        check('retained-package-and-embedded-fonts' in retained_report['pending_qualification'], 'retained fonts and package parts cannot pass as inert leftovers')
        for name in ('../escape', '/absolute', 'image/child.png', 'C:drive', 'image\\escape', 'image%2Fescape', 'image\nname'):
            refuse('unsafe media identity '+repr(name), lambda name=name: resources.decode_store({name: encoded(data)}, 'media'))
        refuse('case-fold collision', lambda: resources.decode_store({'Image.png': encoded(data), 'image.png': encoded(data)}, 'media'))
        refuse('noncanonical Unicode name', lambda: resources.decode_store({'e\u0301.png': encoded(data)}, 'media'))
        refuse('retained file ancestor collision', lambda: resources.decode_store({'word': '', 'word/fonts/a': ''}, 'retained', package=True))
        for bad in ('AB==', 'AA===', ' AA==', 'AA==\n', 'data:image/png;base64,AA==', [True], [-1], [256], [1.5], {}):
            refuse('invalid byte encoding '+repr(bad), lambda bad=bad: resources.decode_store({'image.png': bad}, 'media'))
        refuse('empty image', lambda: resources.decode_image(b''))
        refuse('truncated PNG', lambda: resources.decode_image(data[:45]))
        refuse('aggregate pixel admission', lambda: resources.decode_image(data, remaining_pixels=767))
        refuse('unknown image bytes', lambda: resources.decode_image(b'<svg/>'))

        image = Image.new('RGB', (32, 24))
        image.putdata([((x*7+y*3)%256, (x*2+y*9)%256, (x*5+y*5)%256) for y in range(24) for x in range(32)])
        cases = [('rgb.png', image, {}), ('rgb.jpg', image, {'quality': 95, 'subsampling': 0}),
                 ('rgb.gif', image.quantize(colors=32), {}), ('rgb.bmp', image, {}),
                 ('rgb.webp', image, {'lossless': True}), ('lossy.webp', image, {'quality': 92}),
                 ('rgb.tiff', image, {'compression': 'tiff_lzw'})]
        rgba = image.convert('RGBA'); rgba.putalpha(Image.new('L', image.size, 128)); cases.append(('alpha.png', rgba, {}))
        gray = Image.frombytes('I;16', (8, 1), struct.pack('<8H', 0, 128, 255, 256, 257, 32767, 32768, 65535))
        cases.extend([('gray16.png', gray, {}), ('gray16.tiff', gray, {'compression': 'tiff_lzw'})])
        exif = Image.Exif(); exif[274] = 3
        cases.append(('oriented.jpg', image, {'quality': 95, 'subsampling': 0, 'exif': exif}))
        snapshots = {}
        for name, picture, options in cases:
            path = out/name; picture.save(path, **options); payload = path.read_bytes(); snapshots[name] = hashlib.sha256(payload).hexdigest()
            decoded, _ = resources.decode_image(payload)
            response = native('picture', path)
            comparisons[name] = resources.compare_picture(response, payload)
            check(comparisons[name]['decoder_agreement'] and decoded['width'] == picture.width, 'full native/independent pixel agreement: '+name)
        check('sixteen-bit-source-fidelity' in comparisons['gray16.png']['pending_qualification'], 'RGBA8 agreement does not claim lossless sixteen-bit source fidelity')
        check('sixteen-bit-source-fidelity' in comparisons['gray16.tiff']['pending_qualification'], 'sixteen-bit TIFF retains the same source-fidelity gate')
        check('image-orientation' in comparisons['oriented.jpg']['pending_qualification'], 'decoder agreement does not silently authorize EXIF orientation handling')
        check(comparisons['rgb.webp']['max_channel_error'] == 0, 'lossless WebP has exact pixels without lossy tolerance')

        animated = out/'animated.gif'; image.save(animated, save_all=True, append_images=[image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)])
        refuse('animated image without frame policy', lambda: resources.decode_image(animated.read_bytes()))
        multi = out/'multi.tiff'; image.save(multi, save_all=True, append_images=[image])
        refuse('multipage TIFF without page policy', lambda: resources.decode_image(multi.read_bytes()))
        jpeg_tiff = out/'jpeg-compression.tiff'; image.save(jpeg_tiff, compression='jpeg')
        refuse('TIFF compression outside native bounded decoder', lambda: resources.decode_image(jpeg_tiff.read_bytes()))
        huge = out/'overwide.png'; Image.new('L', (8193, 1)).save(huge)
        refuse('oversized independent raster', lambda: resources.decode_image(huge.read_bytes()))
        native('picture', huge, fail=True)
        broken = out/'broken.png'; broken.write_bytes(data[:45]); native('picture', broken, fail=True)
        native('picture', fail=True); native('picture', out/'rgb.png', out/'rgb.jpg', fail=True)
        native('picture', out/'rgb.png', '--password', 'unused', fail=True)
        fifo = out/'picture.fifo'; os.mkfifo(fifo); native('picture', fifo, fail=True)

        raw = native('picture', out/'rgb.png'); n = struct.unpack_from('<I', raw, 8)[0]; info = json.loads(raw[12:12+n]); pixels = raw[12+n:]
        for key, value in [('width', True), ('height', 999), ('sourceBytes', 0), ('nativePeakBytes', 129 << 20), ('sampleType', 'unknown'), ('format', 'Jpeg')]:
            altered = dict(info); altered[key] = value
            refuse('native packet disagrees on '+key, lambda altered=altered: resources.compare_picture(packet(altered, pixels), (out/'rgb.png').read_bytes()))
        changed = bytearray(pixels); changed[0] ^= 1
        refuse('lossless native RGB mismatch', lambda: resources.compare_picture(packet(info, bytes(changed)), (out/'rgb.png').read_bytes()))
        changed = bytearray(pixels); changed[3] ^= 1
        refuse('native alpha mismatch', lambda: resources.compare_picture(packet(info, bytes(changed)), (out/'rgb.png').read_bytes()))
        refuse('truncated pixel packet', lambda: resources.compare_picture(raw[:-1], (out/'rgb.png').read_bytes()))
        check(all(hashlib.sha256((out/name).read_bytes()).hexdigest() == digest for name, digest in snapshots.items()), 'native decoder leaves every original raster byte-identical')
        check(source.read_bytes() == original, 'native document fixture remains byte-identical')
        (out/'comparisons.json').write_text(json.dumps(comparisons, indent=2)+'\n')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'scope': 'owned byte stores and independent/native raster decoding; fonts, retained package semantics and full runtime admission remain open',
                    'engine_admission_complete': False, 'remote_actions': False}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally: (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
