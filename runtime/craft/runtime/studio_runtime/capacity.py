"""Fail-closed identity checks for a macOS workspace on a bounded APFS image.

Mounting and provisioning belong to the trusted installation manager. Runtime
checks use the kernel attribute API and work inside the offline network sandbox.
"""
import ctypes
import json
import os
import re
from pathlib import Path
import stat
import struct
import sys
from uuid import UUID

CONFIG_VERSION = 2
UNSET = object()
RESERVE_BYTES = 16 * 1024 * 1024
RESERVE_NAME = '.studio-recovery-reserve'


class CapacityError(ValueError):
    pass


def configuration(root):
    root = Path(root)
    path = root.parent / 'capacity.json'
    if root.name != 'state' or (not path.exists() and not path.is_symlink()):
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise CapacityError('unsafe workspace capacity configuration')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value.get('schema_version') not in (1, CONFIG_VERSION) or type(value.get('capacity_mib')) is not int or not 256 <= value['capacity_mib'] <= 1048576:
        raise CapacityError('invalid workspace capacity configuration')
    if not isinstance(value.get('generation'), str) or not re.fullmatch('[a-f0-9]{32}', value['generation']):
        raise CapacityError('invalid workspace storage generation')
    if value.get('phase') not in ('preparing', 'activating', 'ready'):
        raise CapacityError('invalid workspace storage phase')
    return value


def volume_uuid(root):
    if sys.platform != 'darwin':
        raise CapacityError('managed workspace volumes require macOS')
    class Attributes(ctypes.Structure):
        _fields_ = [('bitmapcount', ctypes.c_uint16), ('reserved', ctypes.c_uint16),
                    ('common', ctypes.c_uint32), ('volume', ctypes.c_uint32),
                    ('directory', ctypes.c_uint32), ('file', ctypes.c_uint32), ('fork', ctypes.c_uint32)]
    # sys/attr.h: ATTR_VOL_INFO | ATTR_VOL_UUID. Result: length + uuid_t.
    attributes = Attributes(5, 0, 0, 0x80040000, 0, 0, 0)
    result = ctypes.create_string_buffer(20)
    library = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    library.getattrlist.argtypes = [ctypes.c_char_p, ctypes.POINTER(Attributes), ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
    library.getattrlist.restype = ctypes.c_int
    if library.getattrlist(os.fsencode(root), ctypes.byref(attributes), result, len(result), 0):
        raise CapacityError('cannot read workspace volume identity')
    if struct.unpack_from('I', result.raw)[0] != 20:
        raise CapacityError('unsupported workspace volume identity response')
    return str(UUID(bytes=result.raw[4:20]))


def check(root, expected=UNSET, recovery=False):
    root = Path(root)
    config = configuration(root)
    if config is None:
        if expected is not UNSET and expected is not None:
            raise CapacityError('workspace capacity configuration disappeared; reopen after repair')
        return None
    if config.get('phase') != 'ready':
        raise CapacityError('workspace storage transition needs repair before runtime access')
    if root.is_symlink() or not root.is_mount() or volume_uuid(root) != config.get('volume_uuid'):
        raise CapacityError('managed workspace volume is unavailable; mount it through Studio Local')
    info = os.statvfs(root)
    if info.f_blocks * info.f_frsize > config['capacity_mib'] * 1024 * 1024:
        raise CapacityError('workspace volume exceeds its configured capacity')
    generation = config.get('generation')
    if not isinstance(generation, str) or len(generation) != 32:
        raise CapacityError('workspace storage generation is invalid')
    if expected is not UNSET and expected != generation:
        raise CapacityError('workspace storage changed; restart this agent connection')
    if recovery and info.f_bavail * info.f_frsize < RESERVE_BYTES // 2:
        reserve = root / RESERVE_NAME
        try:
            entry = reserve.lstat()
        except FileNotFoundError:
            entry = None
        if entry:
            if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1 or entry.st_size != RESERVE_BYTES:
                raise CapacityError('recovery reserve is unsafe; manual storage repair required')
            # This file reserves space for journal settlement after ENOSPC. It
            # is not user data. Removing it cannot exceed the volume capacity.
            reserve.unlink()
            fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    return generation


def describe(root):
    """Report capacity without mounting, releasing reserves or opening SQLite."""
    config = configuration(root)
    if config is None:
        return {'managed': False, 'available': True, 'hard_limit_bytes': None}
    out = {'managed': True, 'available': False, 'phase': config['phase'],
           'hard_limit_bytes': config['capacity_mib'] * 1024 * 1024,
           'generation': config['generation']}
    try:
        check(root)
        info = os.statvfs(root)
        reserve = Path(root) / RESERVE_NAME
        entry = reserve.lstat() if reserve.exists() or reserve.is_symlink() else None
        ready = bool(entry and stat.S_ISREG(entry.st_mode) and entry.st_nlink == 1 and entry.st_size == RESERVE_BYTES)
        out.update(available=True, filesystem_bytes=info.f_blocks * info.f_frsize,
                   free_bytes=info.f_bavail * info.f_frsize, reserve_ready=ready)
        out['accepting_work'] = ready and out['free_bytes'] >= RESERVE_BYTES
    except (CapacityError, OSError) as error:
        out['message'] = str(error)
        out['accepting_work'] = False
    return out


def admit(root, expected=UNSET):
    """Preserve journal headroom; cleanup and settlement remain available."""
    check(root, expected)
    info = describe(root)
    if info['managed'] and not info['accepting_work']:
        raise CapacityError('workspace storage needs cleanup and storage-repair before accepting work')
