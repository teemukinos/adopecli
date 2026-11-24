"""Bounded, lossless Texture archive snapshots without extraction.

This is container admission only. Document semantics, graph/resource budgets,
native preservation and cold reopen must pass before an engine opens a snapshot.
No public operation is registered here. Inputs are never rewritten.
"""
import hashlib
import os
from pathlib import Path
import stat
import struct
import zipfile
import zlib

MAX_ARCHIVE = 256 << 20
MAX_EXPANDED = 256 << 20
MAX_ENTRY = 64 << 20
MAX_JSON = 8 << 20
MAX_ENTRIES = 4096
MAX_DIRECTORY = 2 << 20


def read_bytes(path):
    """The caller owns ancestor directories; refuse final symlinks and devices."""
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 22 <= metadata.st_size <= MAX_ARCHIVE:
                raise ValueError('Texture input must be a bounded regular native archive')
            data = stream.read(MAX_ARCHIVE + 1)
            if len(data) != metadata.st_size:
                raise ValueError('Texture input changed size while being read')
            return data
    except OSError as error:
        raise ValueError('Texture native archive cannot be read') from error


def _directory(data):
    # Check directory allocation before constructing member metadata.
    offset = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
    if offset < 0 or offset + 22 > len(data):
        raise ValueError('Texture archive has no complete ZIP directory')
    signature, disk, directory_disk, disk_count, count, size, start, comment = struct.unpack_from('<IHHHHIIH', data, offset)
    if (disk or directory_disk or disk_count != count or not 1 <= count <= MAX_ENTRIES
            or not 46 <= size <= MAX_DIRECTORY or start + size != offset
            or offset + 22 + comment != len(data) or start < 30):
        raise ValueError('Texture ZIP directory is ambiguous, unsupported or exceeds its budget')
    # ZIP64 directory records are unnecessary within these limits and have not
    # been qualified. Bounded ZIP64 member fields from the native writer are
    # supported separately; no locator may override this checked directory.
    if offset >= 20 and data[offset - 20:offset - 16] == b'PK\x06\x07':
        raise ValueError('Texture ZIP64 directory records are not qualified')
    return start, count, offset


def _extra(raw, values):
    """Resolve only the bounded ZIP64 sizes/offsets emitted by the native writer.

    Other extra-field interpretations have not been qualified. In particular,
    Unicode path and encryption overrides must not introduce a second name or
    payload interpretation. The original archive bytes remain untouched.
    """
    cursor = 0
    zip64 = None
    while cursor < len(raw):
        if cursor + 4 > len(raw):
            raise ValueError('Texture ZIP extra field is truncated')
        kind, length = struct.unpack_from('<HH', raw, cursor)
        cursor += 4
        if kind != 1 or zip64 is not None or cursor + length > len(raw):
            raise ValueError('Texture ZIP extra field is unsupported or duplicated')
        zip64 = raw[cursor:cursor + length]
        cursor += length
    needed = [(index, width) for index, (value, width) in enumerate(values)
              if value == (1 << (width * 8)) - 1]
    if not needed:
        # The native parallel saver copies compressed members, writes 32-bit
        # sizes, and retains their original pair of ZIP64 size fields. Admit
        # that exact redundant pair only when both interpretations agree.
        if zip64 is not None and (len(zip64) != 16 or struct.unpack('<QQ', zip64) != tuple(value for value, width in values[:2])):
            raise ValueError('Texture redundant ZIP64 sizes disagree with their header')
        return tuple(value for value, width in values)
    # ZIP64 sizes and offsets use eight bytes; the disk number uses four.
    widths = [4 if width == 2 else 8 for _, width in needed]
    if zip64 is None or len(zip64) != sum(widths):
        raise ValueError('Texture ZIP64 extra field does not match its sentinels')
    resolved = [value for value, width in values]
    cursor = 0
    for (index, _), width in zip(needed, widths):
        resolved[index] = int.from_bytes(zip64[cursor:cursor + width], 'little')
        cursor += width
    return tuple(resolved)


def _entries(data, directory, count, end):
    """Parse the exact bounded central directory, without a recovery parser."""
    cursor = directory
    entries = []
    for _ in range(count):
        if cursor + 46 > end:
            raise ValueError('Texture ZIP central directory is truncated')
        (signature, creator, version, flags, method, _, _, crc, compressed,
         expanded, name_size, extra_size, comment_size, disk, _, attributes,
         offset) = struct.unpack_from('<IHHHHHHIIIHHHHHII', data, cursor)
        start = cursor + 46
        finish = start + name_size + extra_size + comment_size
        if signature != 0x02014b50 or finish > end or version not in (10, 20, 45):
            raise ValueError('Texture ZIP central directory entry is unsupported')
        if (expanded == 0xffffffff or compressed == 0xffffffff or offset == 0xffffffff or disk == 0xffff) and version != 45:
            raise ValueError('Texture ZIP64 directory member has an incompatible version')
        name = data[start:start + name_size].decode('utf-8' if flags & 0x800 else 'cp437')
        expanded, compressed, offset, disk = _extra(
            data[start + name_size:start + name_size + extra_size],
            ((expanded, 4), (compressed, 4), (offset, 4), (disk, 2)))
        info = zipfile.ZipInfo(name)
        info.extract_version = version
        info.create_system = creator >> 8
        info.flag_bits = flags
        info.compress_type = method
        info.CRC = crc
        info.compress_size = compressed
        info.file_size = expanded
        info.header_offset = offset
        info.external_attr = attributes
        info.volume = disk
        entries.append(info)
        cursor = finish
    if cursor != end:
        raise ValueError('Texture ZIP directory has unaccounted entries or bytes')
    return entries


def _name(info):
    name = info.filename
    if (not name or name != info.orig_filename or len(name.encode('utf-8')) > 512
            or name.startswith('/') or '\\' in name or ':' in name
            or info.external_attr & 0x10
            or any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff for c in name)
            or any(part in ('', '.', '..') for part in name.split('/')) or info.is_dir()
            or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)):
        raise ValueError('Texture archive contains an unsafe or ambiguous entry name')
    return name


def _payload(data, info, directory):
    offset = info.header_offset
    if type(offset) is not int or offset < 0 or offset + 30 > directory:
        raise ValueError('Texture ZIP member header lies outside its payload area')
    signature, version, flags, method, _, _, crc, compressed, expanded, name_size, extra_size = struct.unpack_from('<IHHHHHIIIHH', data, offset)
    start = offset + 30 + name_size + extra_size
    end = start + info.compress_size
    if (signature != 0x04034b50 or version not in (10, 20, 45) or version != info.extract_version
            or flags != info.flag_bits or flags & ~0x080e or method != info.compress_type
            or method not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            or (method == zipfile.ZIP_STORED and (info.compress_size != info.file_size or flags & 6))
            or start > directory or end > directory):
        raise ValueError('Texture ZIP member header disagrees with its directory')
    raw_name = data[offset + 30:offset + 30 + name_size]
    try:
        name = raw_name.decode('utf-8' if flags & 0x0800 else 'cp437')
    except UnicodeError as error:
        raise ValueError('Texture ZIP filename encoding is invalid') from error
    if name != info.orig_filename:
        raise ValueError('Texture ZIP filename disagrees with its directory')
    zip64 = compressed == 0xffffffff or expanded == 0xffffffff
    expanded, compressed = _extra(data[offset + 30 + name_size:start],
                                  ((expanded, 4), (compressed, 4)))
    if zip64 and version != 45:
        raise ValueError('Texture ZIP64 member has an incompatible version')
    expected = (info.CRC, info.compress_size, info.file_size)
    if flags & 8:
        if any(actual not in (0, wanted) for actual, wanted in zip((crc, compressed, expanded), expected)):
            raise ValueError('Texture ZIP streaming header disagrees with its directory')
        layout = '<IQQ' if zip64 else '<III'
        descriptor_size = struct.calcsize(layout)
        if (end + 4 + descriptor_size <= directory and data[end:end + 4] == b'PK\x07\x08'
                and struct.unpack_from(layout, data, end + 4) == expected):
            finish = end + 4 + descriptor_size
        elif end + descriptor_size <= directory and struct.unpack_from(layout, data, end) == expected:
            finish = end + descriptor_size
        else:
            raise ValueError('Texture ZIP streaming descriptor is invalid')
    else:
        if (crc, compressed, expanded) != expected:
            raise ValueError('Texture ZIP member sizes or checksum disagree with its directory')
        finish = end
    return start, end, finish


def inspect_bytes(data):
    """Return the original snapshot and every exact decompressed member byte."""
    if not isinstance(data, bytes) or not 22 <= len(data) <= MAX_ARCHIVE:
        raise ValueError('Texture archive exceeds its byte budget or is not a byte snapshot')
    directory, count, directory_end = _directory(data)
    try:
        entries = _entries(data, directory, count, directory_end)
        if len(entries) != count:
            raise ValueError('Texture ZIP directory entry count is inconsistent')
        names = set(); records = []; total = 0
        for info in entries:
            name = _name(info)
            limit = MAX_JSON if name == 'project.json' else MAX_ENTRY
            if (name in names or not 0 <= info.file_size <= limit or not 0 <= info.compress_size <= MAX_ARCHIVE
                    or info.volume != 0 or info.flag_bits & 1 or info.extract_version not in (10, 20, 45)):
                raise ValueError('Texture ZIP member is duplicated, unsupported or exceeds its budget')
            names.add(name); total += info.file_size
            if total > MAX_EXPANDED:
                raise ValueError('Texture archive expansion exceeds its total budget')
            start, end, finish = _payload(data, info, directory)
            records.append((info, start, end, finish))
        if 'project.json' not in names:
            raise ValueError('Texture archive has no project.json')
        # No hidden preamble, overlapping entry, duplicate header, gap or
        # ignored trailer may disagree with the native reader's byte ranges.
        previous = 0
        for info, start, end, finish in sorted(records, key=lambda row: row[0].header_offset):
            if info.header_offset != previous:
                raise ValueError('Texture ZIP payload intervals overlap or contain unaccounted bytes')
            previous = finish
        if previous != directory:
            raise ValueError('Texture ZIP payload does not end at its directory')
        members = {}
        for info, start, end, finish in records:
            encoded = data[start:end]
            if info.compress_type == zipfile.ZIP_STORED:
                decoded = encoded
            else:
                decoder = zlib.decompressobj(-15)
                decoded = decoder.decompress(encoded, info.file_size + 1)
                if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
                    raise ValueError('Texture ZIP compression stream is incomplete or has trailing data')
            if len(decoded) != info.file_size or zlib.crc32(decoded) != info.CRC:
                raise ValueError('Texture ZIP member size or checksum is invalid')
            members[info.filename] = decoded
    except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error, NotImplementedError, UnicodeError) as error:
        raise ValueError('Texture archive cannot be decoded') from error
    return {'source_bytes': data, 'source_sha256': hashlib.sha256(data).hexdigest(),
            'members': members, 'expanded_bytes': total}


def read_native(path):
    return inspect_bytes(read_bytes(path))
