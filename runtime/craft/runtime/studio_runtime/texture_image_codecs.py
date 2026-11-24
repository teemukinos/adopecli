"""Bounded validation of Radiance RGBE and flat OpenEXR resources.

These readers preserve the source. They validate complete pixel streams without
allocating a full floating-point image. Native decoding still has to agree.
"""
import math
import re
import struct
import zlib

from .texture_structure import require

MAX_IMAGE_TEXELS = 16_777_216
MAX_SIDE = 8192
MAX_HEADER = 65_536


def dimensions(width, height):
    require(type(width) is int and type(height) is int and 0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE
            and width * height <= MAX_IMAGE_TEXELS, 'image dimensions exceed their budget')


def hdr(data):
    require(data.startswith(b'#?RADIANCE\n'), 'HDR signature is unsupported')
    position = 11; formats = 0
    while True:
        end = data.find(b'\n', position, min(len(data), MAX_HEADER))
        require(end >= position and end - position <= 1024, 'HDR header is incomplete or exceeds its budget')
        line = data[position:end].strip(); position = end + 1
        if not line:
            break
        require(all(32 <= c < 127 or c == 9 for c in line), 'HDR header is not bounded ASCII')
        if line.startswith(b'#'):
            continue
        require(b'=' in line, 'HDR header field is malformed')
        key, value = (part.strip() for part in line.split(b'=', 1))
        if key == b'FORMAT':
            formats += 1
            require(formats == 1 and value == b'32-bit_rle_rgbe', 'HDR color encoding is unsupported or ambiguous')
        if key in (b'EXPOSURE', b'PIXASPECT', b'GAMMA', b'COLORCORR'):
            try:
                numbers = [float(token) for token in value.split()]
            except ValueError as error:
                raise ValueError('Texture HDR numeric metadata is invalid') from error
            require(len(numbers) == (3 if key == b'COLORCORR' else 1) and all(math.isfinite(n) and 0 < n <= 1_000_000 for n in numbers),
                    'HDR numeric metadata is unsupported')
    end = data.find(b'\n', position, min(len(data), MAX_HEADER))
    require(formats == 1 and end >= position, 'HDR format or resolution is missing')
    match = re.fullmatch(rb'-Y ([1-9][0-9]{0,4}) \+X ([1-9][0-9]{0,4})', data[position:end])
    require(match is not None, 'HDR orientation or resolution is unsupported')
    height, width = int(match[1]), int(match[2]); dimensions(width, height); position = end + 1
    for _ in range(height):
        require(position + 4 <= len(data), 'HDR scanline is truncated')
        first = data[position:position + 4]; position += 4
        if first[0:2] == b'\x02\x02' and first[2] < 128:
            require(int.from_bytes(first[2:4], 'big') == width, 'HDR scanline width disagrees with its header')
            for _ in range(4):
                count = 0
                while count < width:
                    require(position < len(data), 'HDR RLE component is truncated')
                    code = data[position]; position += 1
                    length = code - 128 if code > 128 else code
                    require(length > 0 and count + length <= width, 'HDR RLE run is empty or exceeds its scanline')
                    position += 1 if code > 128 else length
                    require(position <= len(data), 'HDR RLE payload is truncated')
                    count += length
        else:
            require(first[:3] != b'\x01\x01\x01', 'HDR old-RLE scanline starts with a repeat')
            count = 1; multiplier = 1
            while count < width:
                require(position + 4 <= len(data), 'HDR old-RLE pixel is truncated')
                pixel = data[position:position + 4]; position += 4
                if pixel[:3] == b'\x01\x01\x01':
                    require(multiplier <= 65536, 'HDR old-RLE repeat chain exceeds its budget')
                    count += pixel[3] * multiplier; multiplier *= 256
                else:
                    count += 1; multiplier = 1
                require(count <= width, 'HDR old-RLE repeat exceeds its scanline')
    require(position == len(data), 'HDR has trailing pixel data')
    return {'format': 'HDR', 'width': width, 'height': height, 'sample_type': 'RGBE', 'linear': True}


def exr(data):
    require(len(data) >= 9 and data[:4] == b'\x76\x2f\x31\x01' and struct.unpack_from('<I', data, 4)[0] in (2, 0x202),
            'EXR requires a single flat scanline or tiled part without other version flags')
    tiled = struct.unpack_from('<I', data, 4)[0] == 0x202
    position = 8; attributes = {}
    def string(start):
        end = data.find(b'\x00', start, min(len(data), start + 32, MAX_HEADER))
        require(end >= start, 'EXR name is incomplete or exceeds its budget')
        raw = data[start:end]
        require(all(32 <= byte < 127 for byte in raw), 'EXR header name is not ASCII')
        return raw.decode('ascii'), end + 1
    while True:
        name, position = string(position)
        if not name:
            break
        kind, position = string(position)
        require(name not in attributes and len(attributes) < 128 and position + 4 <= len(data), 'EXR attributes are duplicated or unbounded')
        length = struct.unpack_from('<I', data, position)[0]; position += 4
        require(position + length <= min(len(data), MAX_HEADER), 'EXR attribute exceeds its header budget')
        attributes[name] = (kind, data[position:position + length]); position += length
    require(not ({'maxSamplesPerPixel', 'deepImageState'} & attributes.keys()) and ('tiles' in attributes) == tiled,
            'EXR deep metadata or inconsistent tile flags are not qualified')
    def attr(name, kind, length=None):
        value = attributes.get(name)
        require(value is not None and value[0] == kind and (length is None or len(value[1]) == length), 'EXR required attribute is missing or malformed: ' + name)
        return value[1]
    window = struct.unpack('<4i', attr('dataWindow', 'box2i', 16))
    display = struct.unpack('<4i', attr('displayWindow', 'box2i', 16))
    width, height = window[2] - window[0] + 1, window[3] - window[1] + 1
    dw, dh = display[2] - display[0] + 1, display[3] - display[1] + 1
    dimensions(width, height); dimensions(dw, dh)
    require(all(abs(value) <= 1_000_000 for value in (*window, *display)), 'EXR window offsets exceed their budget')
    compression = attr('compression', 'compression', 1)[0]
    require(compression in (0, 1, 2, 3), 'EXR compression is not qualified; use uncompressed, RLE, ZIPS or ZIP')
    require(attr('lineOrder', 'lineOrder', 1)[0] in (0, 1, 2), 'EXR line order is invalid')
    for name, kind, count in (('pixelAspectRatio', 'float', 1), ('screenWindowWidth', 'float', 1), ('screenWindowCenter', 'v2f', 2)):
        numbers = struct.unpack('<' + 'f' * count, attr(name, kind, count * 4))
        require(all(math.isfinite(value) for value in numbers), 'EXR screen metadata is nonfinite')
    if 'type' in attributes:
        require(attr('type', 'string') == (b'tiledimage' if tiled else b'scanlineimage'), 'EXR part type is unsupported')
    raw = attr('channels', 'chlist'); cursor = 0; channels = []
    while cursor < len(raw) and raw[cursor]:
        end = raw.find(b'\x00', cursor)
        require(end >= cursor and end + 17 <= len(raw), 'EXR channel record is truncated')
        name = raw[cursor:end]
        pixel_type, linear, reserved, xs, ys = struct.unpack_from('<IB3sii', raw, end + 1)
        require(name in (b'R', b'G', b'B', b'A') and pixel_type in (1, 2) and linear in (0, 1) and reserved == b'\0\0\0'
                and xs == ys == 1, 'EXR channel encoding is unsupported')
        require(not channels or channels[-1][0] < name, 'EXR channels must have unique sorted names')
        channels.append((name, 2 if pixel_type == 1 else 4)); cursor = end + 17
    require(cursor + 1 == len(raw) and raw[cursor:] == b'\x00' and {name for name, _ in channels} in ({b'R', b'G', b'B'}, {b'R', b'G', b'B', b'A'}),
            'EXR requires exactly RGB or RGBA channels')
    rows_per_block = 16 if compression == 3 else 1
    tile_width = tile_height = 0
    if tiled:
        tile_width, tile_height, mode = struct.unpack('<IIB', attr('tiles', 'tiledesc', 9))
        require(1 <= tile_width <= 256 and 1 <= tile_height <= 256 and mode in (0, 16),
                'EXR requires bounded single-level tiles without reserved flags')
        columns = (width + tile_width - 1) // tile_width
        block_rows = (height + tile_height - 1) // tile_height
        blocks = columns * block_rows
    else:
        blocks = (height + rows_per_block - 1) // rows_per_block
    require(blocks <= 65_536, 'EXR chunk count exceeds its budget')
    if 'chunkCount' in attributes:
        require(struct.unpack('<i', attr('chunkCount', 'int', 4))[0] == blocks, 'EXR chunk count disagrees with dimensions')
    table_end = position + blocks * 8
    require(table_end <= len(data), 'EXR chunk offset table is truncated')
    intervals = []; sample_bytes = sum(size for _, size in channels)
    for index in range(blocks):
        offset = struct.unpack_from('<Q', data, position + index * 8)[0]
        header_size = 20 if tiled else 8
        require(table_end <= offset and offset + header_size <= len(data), 'EXR chunk offset lies outside its payload area')
        if tiled:
            x, y, level_x, level_y, packed = struct.unpack_from('<4iI', data, offset)
            require((x, y) == (index % columns, index // columns) and level_x == level_y == 0,
                    'EXR tile coordinates or levels are invalid')
            row_width = min(tile_width, width - x * tile_width)
            rows = min(tile_height, height - y * tile_height)
        else:
            y, packed = struct.unpack_from('<iI', data, offset)
            require(y == window[1] + index * rows_per_block, 'EXR chunk coordinates are invalid')
            row_width = width
            rows = min(rows_per_block, height - index * rows_per_block)
        expected = row_width * rows * sample_bytes
        require(0 < packed <= expected and offset + header_size + packed <= len(data), 'EXR chunk byte count is invalid')
        intervals.append((offset, offset + header_size + packed, header_size, row_width, rows, expected))
    previous = table_end
    for start, end, _, _, _, _ in sorted(intervals):
        require(start == previous, 'EXR chunks overlap or contain unaccounted bytes')
        previous = end
    require(previous == len(data), 'EXR has trailing or missing chunk data')
    for start, end, header_size, row_width, rows, expected in intervals:
        decoded = exr_block(data[start + header_size:end], expected, compression)
        cursor = 0
        for _ in range(rows):
            for _, size in channels:
                mask = 0x7c00 if size == 2 else 0x7f800000
                channel = memoryview(decoded)[cursor:cursor + row_width * size]; cursor += row_width * size
                require(all(value & mask != mask for (value,) in struct.iter_unpack('<H' if size == 2 else '<I', channel)),
                        'EXR pixel contains NaN or infinity')
    return {'format': 'EXR', 'width': dw, 'height': dh, 'data_width': width, 'data_height': height,
            'sample_type': 'half/float', 'linear': True, 'compression': compression, 'chunks': blocks,
            'storage': 'tiles' if tiled else 'scanlines', 'tile_width': tile_width, 'tile_height': tile_height,
            'channels': [name.decode('ascii') for name, _ in channels], 'channel_sample_bytes': [size for _, size in channels]}


def exr_block(encoded, expected, compression):
    """Decode one size-checked flat chunk, without allocating a whole image."""
    if compression == 0 or len(encoded) == expected:
        require(len(encoded) == expected, 'EXR uncompressed chunk has an invalid size')
        return encoded
    if compression == 1:
        predicted = bytearray(); cursor = 0
        while cursor < len(encoded):
            code = encoded[cursor]; cursor += 1
            literal = code >= 128
            length = 256 - code if literal else code + 1
            stored = length if literal else 1
            require(cursor + stored <= len(encoded) and len(predicted) + length <= expected,
                    'EXR RLE run is truncated or exceeds its chunk')
            if literal:
                predicted.extend(encoded[cursor:cursor + length])
            else:
                predicted.extend(bytes([encoded[cursor]]) * length)
            cursor += stored
        require(len(predicted) == expected, 'EXR RLE chunk is incomplete')
    else:
        decoder = zlib.decompressobj()
        try:
            predicted = bytearray(decoder.decompress(encoded, expected + 1))
        except zlib.error as error:
            raise ValueError('Texture EXR ZIP chunk cannot be decoded') from error
        require(len(predicted) == expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
                'EXR ZIP stream is incomplete, oversized or has trailing data')
    for i in range(1, expected):
        predicted[i] = (predicted[i - 1] + predicted[i] - 128) & 255
    decoded = bytearray(expected); split = (expected + 1) // 2
    decoded[::2] = predicted[:split]; decoded[1::2] = predicted[split:]
    return decoded
