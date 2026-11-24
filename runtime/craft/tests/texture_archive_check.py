#!/usr/bin/env python3
"""Local adversarial checks for Texture container admission; no engine is launched.

Run with Python 3. Add --native PATH for archives produced by the maintained
native engine, and --evidence PATH to retain the machine-readable result.
This checks ZIP admission only, not document semantics or runtime availability.
"""
import argparse
import hashlib
import io
import json
import os
import random
from pathlib import Path
import stat
import struct
import sys
import tempfile
import time
import warnings
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import texture_archive as archive


def fixture(entries, *, stream=False, zip64=False, compression=zipfile.ZIP_DEFLATED):
    class Stream(io.BytesIO):
        def seek(self, *args):
            raise io.UnsupportedOperation('streaming fixture')
    sink = Stream() if stream else io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(sink, 'w', compression=compression) as output:
            for name, payload in entries:
                info = zipfile.ZipInfo(name)
                info.compress_type = compression
                with output.open(info, 'w', force_zip64=zip64) as entry:
                    entry.write(payload)
    return sink.getvalue()


def crafted(*, name=b'project.json', payload=b'{}', method=8, flags=0,
            declared=None, crc=None, encoded=None, local_extra=b'', central_extra=b'',
            local_name=None, attributes=0, version=20, descriptor=b'',
            local_values=None, central_values=None):
    """Independent raw writer for inconsistent headers and compression streams."""
    if encoded is None:
        compressor = zlib.compressobj(wbits=-15)
        encoded = compressor.compress(payload) + compressor.flush() if method == 8 else payload
    values = (zlib.crc32(payload) if crc is None else crc, len(encoded), len(payload) if declared is None else declared)
    local_values = values if local_values is None else local_values
    central_values = values if central_values is None else central_values
    local_name = name if local_name is None else local_name
    local = struct.pack('<IHHHHHIIIHH', 0x04034b50, version, flags, method, 0, 0,
                        *local_values, len(local_name), len(local_extra)) + local_name + local_extra + encoded + descriptor
    central = struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 0x314, version, flags, method, 0, 0,
                          *central_values, len(name), len(central_extra), 0, 0, 0, attributes, 0) + name + central_extra
    end = struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, 1, 1, len(central), len(local), 0)
    return local + central + end


def change(data, position, layout, value):
    output = bytearray(data)
    struct.pack_into(layout, output, position, value)
    return bytes(output)


def directory(data):
    return struct.unpack_from('<I', data, len(data) - 6)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, action='append', default=[])
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    checks = []
    started = time.monotonic()

    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    def refused(label, data):
        try:
            archive.inspect_bytes(data)
        except ValueError:
            checks.append(label)
        else:
            raise AssertionError(f'accepted invalid archive: {label}')

    contents = [('project.json', b'{"format_version":2}'), ('resources/palette.png', bytes(range(256)) * 8)]
    for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        for stream in (False, True):
            for zip64 in (False, True):
                data = fixture(contents, compression=method, stream=stream, zip64=zip64)
                decoded = archive.inspect_bytes(data)
                check(f'exact bytes retained: method={method}, stream={stream}, zip64={zip64}',
                      decoded['source_bytes'] is data and decoded['members'] == dict(contents)
                      and decoded['expanded_bytes'] == sum(len(value) for _, value in contents)
                      and decoded['source_sha256'] == hashlib.sha256(data).hexdigest())
                with zipfile.ZipFile(io.BytesIO(data)) as reader:
                    check(f'independent decoder agrees: method={method}, stream={stream}, zip64={zip64}',
                          {name: reader.read(name) for name in reader.namelist()} == decoded['members'])

    data = crafted(); central = directory(data); end = len(data) - 22
    for label, position, layout, value in [
        ('multi-disk end', end + 4, '<H', 1), ('foreign directory disk', end + 6, '<H', 1),
        ('inconsistent disk count', end + 8, '<H', 2), ('entry budget', end + 10, '<H', 4097),
        ('zero entries', end + 10, '<H', 0), ('directory byte budget', end + 12, '<I', archive.MAX_DIRECTORY + 1),
        ('directory offset mismatch', end + 16, '<I', central + 1), ('missing comment bytes', end + 20, '<H', 1),
        ('wrong central signature', central, '<I', 0), ('central wrong disk', central + 34, '<H', 1),
        ('central invalid version', central + 6, '<H', 46), ('central invalid filename size', central + 28, '<H', 65535),
        ('central nonexistent local header', central + 42, '<I', central), ('wrong local signature', 0, '<I', 0),
        ('local mismatched version', 4, '<H', 10), ('local mismatched flags', 6, '<H', 8),
        ('local mismatched method', 8, '<H', 0), ('local mismatched CRC', 14, '<I', 0),
        ('local mismatched compressed size', 18, '<I', 0), ('local mismatched expanded size', 22, '<I', 0),
        ('local oversized name', 26, '<H', 65535), ('local oversized extra', 28, '<H', 65535),
    ]:
        refused(label, change(data, position, layout, value))
    refused('truncated archive', data[:-1])
    refused('ignored trailing bytes', data + b'x')
    refused('archive preamble', b'x' + data)
    refused('non-byte snapshot', bytearray(data))
    refused('no native project', fixture([('other.json', b'{}')]))
    refused('duplicate member', fixture([('project.json', b'{}'), ('project.json', b'{}')]))
    for name in (b'', b'/project.json', b'../project.json', b'a/../project.json', b'a//b', b'./project.json',
                 b'C:project.json', b'a\\project.json', b'project.json\x00ignored', b'a\n', b'a\x7f', b'a/', b'a' * 513):
        refused('unsafe member name ' + repr(name[:40]), crafted(name=name))
    refused('invalid UTF-8 name', crafted(name=b'\xff', flags=0x800))
    refused('local filename substitution', crafted(local_name=b'projects.json'))
    for mode in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK):
        refused(f'non-regular entry {mode:o}', crafted(attributes=(mode | 0o600) << 16))
    refused('DOS directory attribute', crafted(attributes=0x10))
    for flags in (1, 0x10, 0x20, 0x40, 0x2000):
        refused(f'unsupported flag {flags:x}', crafted(flags=flags))
    refused('store with deflate option', crafted(method=0, flags=2))
    refused('unsupported method', crafted(method=12))
    refused('stored size mismatch', crafted(method=0, declared=1))
    refused('invalid CRC in both headers', crafted(crc=0))
    refused('deflate understated expansion', crafted(payload=b'A' * (1 << 20), declared=1))
    refused('deflate overstated expansion', crafted(declared=3))
    refused('truncated deflate stream', crafted(encoded=b'\xab\xae'))
    refused('deflate trailing garbage', crafted(encoded=b'\xab\xae\x05\x00garbage'))
    refused('project JSON byte budget', crafted(declared=archive.MAX_JSON + 1))
    refused('member byte budget', crafted(name=b'resources/image', declared=archive.MAX_ENTRY + 1))
    refused('truncated local extra', crafted(local_extra=b'\x01'))
    refused('truncated central extra', crafted(central_extra=b'\x01'))
    for field in ('local_extra', 'central_extra'):
        for kind in (1, 0x9901, 0x7075, 0xffff):
            refused(f'unqualified or unrequested {field} {kind:x}', crafted(**{field: struct.pack('<HH', kind, 0)}))
        refused('overlong ' + field, crafted(**{field: struct.pack('<HH', 1, 8) + b'x'}))
    # ZIP64 member fields are supported; ZIP64 directory records are not.
    native_extra = struct.pack('<HHQQ', 1, 16, 2, 4)
    native = crafted(version=45, local_values=(zlib.crc32(b'{}'), 0xffffffff, 0xffffffff),
                     central_values=(zlib.crc32(b'{}'), 0xffffffff, 0xffffffff),
                     local_extra=native_extra, central_extra=native_extra)
    check('native-style ZIP64 size fields', archive.inspect_bytes(native)['members'] == {'project.json': b'{}'})
    redundant = crafted(local_extra=native_extra, central_extra=native_extra)
    check('native parallel writer redundant size fields agree', archive.inspect_bytes(redundant)['members'] == {'project.json': b'{}'})
    refused('redundant ZIP64 local size disagrees', change(redundant, 30 + 12 + 4, '<Q', 3))
    refused('redundant ZIP64 central size disagrees', change(redundant, directory(redundant) + 46 + 12 + 4, '<Q', 3))
    refused('ZIP64 member wrong version', change(native, 4, '<H', 20))
    refused('ZIP64 central wrong version', change(native, directory(native) + 6, '<H', 20))
    refused('ZIP64 size exceeds budget', change(native, directory(native) + 46 + 12 + 4, '<Q', 1 << 40))
    refused('ZIP64 duplicated field', crafted(version=45, local_values=(0, 0xffffffff, 0xffffffff),
                                           local_extra=native_extra * 2))
    # Standard unsigned descriptors are valid too, independent of Python's writer.
    crc = zlib.crc32(b'{}')
    descriptor = struct.pack('<III', crc, 4, 2)
    unsigned = crafted(flags=8, local_values=(0, 0, 0), descriptor=descriptor)
    check('unsigned streaming descriptor', archive.inspect_bytes(unsigned)['members'] == {'project.json': b'{}'})
    refused('stream descriptor missing', crafted(flags=8, local_values=(0, 0, 0)))
    refused('stream descriptor bad CRC', crafted(flags=8, local_values=(0, 0, 0), descriptor=b'\x00' * 12))
    refused('stream descriptor disagrees with nonzero header', crafted(flags=8, local_values=(1, 4, 2), descriptor=descriptor))
    refused('payload gap before directory', crafted(descriptor=b'x'))
    # Two directory records aliasing one local payload must not amplify it.
    second = fixture(contents, compression=zipfile.ZIP_STORED)
    first_central = directory(second)
    second_central = first_central + 46 + len(contents[0][0])
    refused('aliased payload header', change(second, second_central + 42, '<I', 0))
    # Force the total limit below two individually allowed members.
    old_limit = archive.MAX_EXPANDED
    try:
        archive.MAX_EXPANDED = 2048
        refused('aggregate expanded-byte budget', fixture(contents))
    finally:
        archive.MAX_EXPANDED = old_limit
    with tempfile.TemporaryDirectory(prefix='dobe-texture-archive-') as temporary:
        root = Path(temporary); path = root / 'native.tcraft'; path.write_bytes(data)
        check('regular file snapshot', archive.read_native(path)['source_bytes'] == data)
        for label, path in [('symlink input', root / 'link'), ('directory input', root), ('FIFO input', root / 'pipe')]:
            if label == 'symlink input':
                path.symlink_to(root / 'native.tcraft')
            elif label == 'FIFO input':
                os.mkfifo(path)
            try:
                archive.read_native(path)
            except ValueError:
                checks.append(label)
            else:
                raise AssertionError(label)
        check('original input unchanged', (root / 'native.tcraft').read_bytes() == data)
    # Deterministic mutations cover mixed directory/payload failures. Every
    # accepted mutation must agree with an independent decoder; malformed input
    # must produce ValueError, not an uncaught parser exception.
    generator = random.Random(0x746372616674)
    seeds = [data, native, redundant, unsigned, fixture(contents),
             fixture(contents, stream=True, zip64=True)]
    accepted = 0
    for _ in range(3000):
        mutated = bytearray(generator.choice(seeds))
        for _ in range(generator.randint(1, 3)):
            position = generator.randrange(len(mutated))
            mutated[position] ^= 1 << generator.randrange(8)
        mutated = bytes(mutated)
        try:
            admitted = archive.inspect_bytes(mutated)
        except ValueError:
            continue
        with zipfile.ZipFile(io.BytesIO(mutated)) as independent:
            expected = {name: independent.read(name) for name in independent.namelist()}
        assert admitted['members'] == expected, 'accepted mutation disagrees with independent decoder'
        assert admitted['source_bytes'] == mutated, 'snapshot changed'
        accepted += 1
    check('3000 deterministic mutations fail cleanly or match independent decoder', True)
    native_files = []
    for path in args.native:
        before = path.read_bytes(); decoded = archive.read_native(path)
        with zipfile.ZipFile(io.BytesIO(before)) as reader:
            expected = {name: reader.read(name) for name in reader.namelist()}
        check('native writer exact snapshot: ' + path.name,
              decoded['source_bytes'] == before and decoded['members'] == expected and path.read_bytes() == before)
        native_files.append({'path': str(path), 'sha256': decoded['source_sha256'],
                             'members': len(expected), 'expanded_bytes': decoded['expanded_bytes']})
    report = {'passed': True, 'checks': len(checks), 'cases': checks, 'native_archives': native_files,
              'mutations': {'count': 3000, 'accepted': accepted, 'refused': 3000 - accepted},
              'seconds': round(time.monotonic() - started, 4), 'scope': 'container admission only',
              'runtime_texture_available': False, 'goal_complete': False}
    if args.evidence:
        args.evidence.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'checks', 'seconds', 'scope')}))


if __name__ == '__main__':
    main()
