"""Generate runtime identities from the pinned font Git objects embedded by Animate.

Run with the bundled Python/Pillow: --fonts <checkout> --source <native checkout>.
No font bytes are copied into the runtime catalog and no host fonts are consulted.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import subprocess

from PIL import ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fonts', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root/'craft/engines/animate.lock.json').read_text())
    source = (args.source/'crates/text/build.rs').read_text()
    files = re.findall(r'"([^"\n]+\.(?:ttf|otf))"', source)
    if len(files) != 20 or len(set(files)) != 20:
        raise ValueError('The maintained Animate font input list changed; qualify its catalog before generating')
    catalog = {}
    for name in files:
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Font input must stay within the pinned font tree')
        data = subprocess.check_output(['git', '-C', str(args.fonts), 'show', lock['fonts']['revision']+':fonts/'+name])
        if data[:4] not in (b'\x00\x01\x00\x00', b'OTTO'):
            raise ValueError('Font catalog requires a single SFNT face')
        tables = {}
        for index in range(struct.unpack_from('>H', data, 4)[0]):
            tag, _, offset, size = struct.unpack_from('>4sIII', data, 12 + index*16)
            if tag in tables or offset+size > len(data):
                raise ValueError('Invalid pinned SFNT table')
            tables[tag] = data[offset:offset+size]
        names = tables[b'name']; _, count, start = struct.unpack_from('>HHH', names)
        postscript = set()
        for index in range(count):
            platform, _, _, identity, length, offset = struct.unpack_from('>HHHHHH', names, 6+index*12)
            if identity == 6 and platform in (0, 3):
                postscript.add(names[start+offset:start+offset+length].decode('utf-16-be'))
        if len(postscript) != 1:
            raise ValueError('Pinned font has ambiguous PostScript identity')
        font = ImageFont.truetype(io.BytesIO(data), size=16)
        glyphs = struct.unpack_from('>H', tables[b'maxp'], 4)[0]
        if font.font.glyphs != glyphs:
            raise ValueError('Independent FreeType/SFNT glyph counts disagree')
        catalog[name] = {'family': font.getname()[0], 'bytes': len(data), 'index': 0,
            'postscript': postscript.pop(), 'weight': struct.unpack_from('>H', tables[b'OS/2'], 4)[0],
            'italic': bool(struct.unpack_from('>H', tables[b'OS/2'], 62)[0] & 1),
            'glyphs': glyphs, 'sha256': hashlib.sha256(data).hexdigest()}
    result = {'font_revision': lock['fonts']['revision'], 'faces': catalog}
    target = root/'craft/runtime/studio_runtime/animate_fonts.json'
    target.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print('PASS', len(catalog), 'pinned font identities;', target)


if __name__ == '__main__':
    main()
