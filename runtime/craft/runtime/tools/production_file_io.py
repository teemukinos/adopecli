"""Validated artifact paths and exclusive, staged delivery for local production."""
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import zlib


def inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Artifact path escapes the private run folder')
    return path


def png_bytes(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('PNG path must name an existing regular file')
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Invalid PNG signature')
    offset, dimensions, ended = 8, None, False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError('Truncated PNG chunk')
        length = struct.unpack('>I', data[offset:offset+4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError('Truncated PNG data')
        kind, body = data[offset+4:offset+8], data[offset+8:end-4]
        if zlib.crc32(kind + body) & 0xffffffff != struct.unpack('>I', data[end-4:end])[0]:
            raise ValueError('PNG checksum mismatch')
        if dimensions is None:
            if kind != b'IHDR' or length != 13:
                raise ValueError('PNG must begin with IHDR')
            dimensions = struct.unpack('>II', body[:8])
            if not all(dimensions):
                raise ValueError('PNG dimensions must be positive')
        if kind == b'IEND':
            if length or end != len(data):
                raise ValueError('Invalid PNG end')
            ended = True
            break
        offset = end
    if not ended:
        raise ValueError('PNG is missing IEND')
    return data, dimensions


def image_path_from_hint(hint):
    if not isinstance(hint, str):
        raise ValueError('Expected the original image output_hint string')
    matches = re.findall(r'\bas (/[^\r\n]+?\.png) by default\.', hint)
    if len(matches) != 1:
        raise ValueError('Image output hint must expose exactly one original PNG path')
    return Path(matches[0]).resolve()


def publish_files(root, files):
    """Validate and stage all bytes, then install without overwriting any target.

    On failure, remove only files installed by this invocation. Existing targets,
    including dangling symlinks, remain unchanged. No render retry occurs here.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Publication root must already exist')
    for name, data in files.items():
        if Path(name).name != name or name in ('', '.', '..'):
            raise ValueError('Delivery names must be plain filenames')
        if not isinstance(data, bytes):
            raise TypeError('Delivery contents must be bytes')
        if os.path.lexists(root / name):
            raise FileExistsError('Refusing to overwrite ' + name)
    stage = Path(tempfile.mkdtemp(prefix='.delivery-', dir=root))
    installed = []
    try:
        for name, data in files.items():
            with (stage / name).open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for name in files:
            target = root / name
            os.link(stage / name, target)
            installed.append((target, target.stat().st_ino))
    except BaseException:
        for path, inode in installed:
            if path.exists() and path.stat().st_ino == inode:
                path.unlink()
        raise
    finally:
        shutil.rmtree(stage)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
