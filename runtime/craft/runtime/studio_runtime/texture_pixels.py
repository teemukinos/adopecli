"""Bounded sparse paint and dense bake payload checks for Texture snapshots.

The caller supplies archive-admitted member bytes and a structure-admitted
project. Resource decoding and native preservation remain separate gates.
"""
import hashlib
import re
import struct

from .texture_structure import BAKED_IDS, CHANNEL_IDS, MAX_ATLAS_SIDE, MAX_ATLAS_TEXELS, require

MAX_PIXEL_BYTES = 128 << 20
MAX_SPARSE_TILES = 16_384
PAINT = re.compile(r'pixels/layer_([1-9][0-9]{0,19})_([A-Za-z]+)\.bin\Z')
MASK = re.compile(r'pixels/mask_([1-9][0-9]{0,19})\.bin\Z')
BAKE = re.compile(r'baked/(0|[1-9][0-9]{0,3})_([A-Za-z]+)\.bin\Z')
BAKE_PAINT = re.compile(r'bake_paint/(0|[1-9][0-9]{0,3})_(cage|skew)\.bin\Z')


def header(data):
    require(isinstance(data, bytes) and 24 <= len(data) <= MAX_PIXEL_BYTES and data[:4] == b'TCTX', 'pixel payload has an invalid header')
    version, width, height, components, count = struct.unpack_from('<5I', data, 4)
    require(version == 1, 'pixel format version is not qualified')
    require(0 < width <= MAX_ATLAS_SIDE and 0 < height <= MAX_ATLAS_SIDE
            and width * height <= MAX_ATLAS_TEXELS, 'pixel dimensions exceed their budget')
    return width, height, components, count


def sparse(data, width, height, components):
    w, h, c, count = header(data)
    require((w, h, c) == (width, height, components), 'paint dimensions/components disagree with its owner')
    columns, rows = (w + 63) // 64, (h + 63) // 64
    require(count <= min(columns * rows, MAX_SPARSE_TILES), 'paint tile count exceeds its budget')
    stride = 8 + 4096 * c * 2
    require(len(data) == 24 + count * stride, 'paint payload length disagrees with its tile count')
    positions = set()
    for offset in range(24, len(data), stride):
        x, y = struct.unpack_from('<2I', data, offset)
        require(x < columns and y < rows and (x, y) not in positions, 'paint tile is duplicated or outside its atlas')
        positions.add((x, y))
    return {'width': w, 'height': h, 'components': c, 'allocated_tiles': count}


def dense(data, components):
    w, h, c, count = header(data)
    require(c == components and count == 0, 'baked components or reserved tile count are invalid')
    require(len(data) == 24 + w * h * c * 4, 'baked payload length disagrees with its dimensions')
    # Check exponent bits without allocating a Python float array or converting
    # the native f32 bytes. NaN and both infinities share this exponent mask.
    require(all(bits & 0x7f800000 != 0x7f800000 for (bits,) in struct.iter_unpack('<I', memoryview(data)[24:])),
            'baked payload contains nonfinite values')
    return {'width': w, 'height': h, 'components': c}


def inspect_members(members, structure):
    reports = {}; total = tiles = 0; baked_sizes = {}
    for name, data in members.items():
        if not name.startswith(('pixels/', 'baked/', 'bake_paint/')):
            continue
        require(isinstance(data, bytes), 'pixel member must be a byte snapshot')
        total += len(data)
        require(total <= MAX_PIXEL_BYTES, 'total pixel payload exceeds its byte budget')
        paint = PAINT.fullmatch(name); mask = MASK.fullmatch(name)
        bake = BAKE.fullmatch(name); bake_paint = BAKE_PAINT.fullmatch(name)
        if paint or mask:
            match = paint or mask; owner = structure['ids'].get(int(match[1]))
            require(owner is not None, 'pixel payload references an absent layer/effect')
            atlas = structure['atlases'][owner['texture_set']]
            if paint:
                require(paint[2] in CHANNEL_IDS, 'paint payload references an unknown channel')
                components = CHANNEL_IDS[paint[2]] + 1
            else:
                components = 2
            report = sparse(data, atlas['width'], atlas['height'], components)
            tiles += report['allocated_tiles']
            require(tiles <= MAX_SPARSE_TILES, 'total allocated paint tiles exceed their budget')
        elif bake or bake_paint:
            match = bake or bake_paint; index = int(match[1])
            require(index < len(structure['atlases']), 'baked payload references an absent texture set')
            if bake:
                require(bake[2] in BAKED_IDS, 'baked payload references an unknown map')
                components = BAKED_IDS[bake[2]]
            else:
                components = 1
            report = dense(data, components)
            if bake:
                size = report['width'], report['height']
                require(index not in baked_sizes or baked_sizes[index] == size, 'baked maps in one texture set have inconsistent dimensions')
                baked_sizes[index] = size
        else:
            raise ValueError('Texture pixel member has an unsupported or noncanonical name')
        reports[name] = {**report, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    return {'members': reports, 'bytes': total, 'allocated_tiles': tiles}
