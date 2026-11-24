"""Local execution budgets. Hosted backends must additionally enforce OS quotas."""
import json
import os
from pathlib import Path
import resource
import sys

DEFAULTS = {'memory_mib': 4096, 'attempt_mib': 4096, 'wall_seconds': 600, 'cpu_seconds': 600, 'processes': 64}
RANGES = {'memory_mib': (256, 65536), 'attempt_mib': (64, 32768), 'wall_seconds': (1, 86400),
          'cpu_seconds': (1, 86400), 'processes': (4, 256)}


def validate(value):
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys():
        raise ValueError('unsupported execution limit')
    for key, limit in value.items():
        low, high = RANGES[key]
        if type(limit) is not int or not low <= limit <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
    return {**DEFAULTS, **value}


def load(root):
    path = Path(root) / 'limits.json'
    return validate(json.loads(path.read_text()) if path.exists() else {})


def save(root, changes):
    from .store import Store
    import uuid
    value = validate({**load(root), **changes})
    pending = Path(root) / ('.limits-' + uuid.uuid4().hex)
    try:
        with open(pending, 'x') as stream:
            json.dump(value, stream); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        pending.replace(Path(root) / 'limits.json'); Store._sync_dir(root)
    finally:
        pending.unlink(missing_ok=True)
    return value


def apply_process_limits(value):
    # Inherited by engine children. Aggregate resident memory and workspace size
    # are monitored by the supervisor; these are not a hostile-process sandbox.
    resource.setrlimit(resource.RLIMIT_CPU, (value['cpu_seconds'], value['cpu_seconds']))
    maximum_file = min(value['attempt_mib'] << 20, 1 << 30)
    resource.setrlimit(resource.RLIMIT_FSIZE, (maximum_file, maximum_file))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def group_usage(group):
    count = 0; memory_kib = 0
    if sys.platform == 'darwin':
        # /bin/ps is setuid on macOS and cannot execute inside a sandbox.
        # Query our process group through the public libproc API instead.
        import ctypes
        import errno
        class TaskInfo(ctypes.Structure):
            _fields_ = [('virtual', ctypes.c_uint64), ('resident', ctypes.c_uint64),
                        ('times', ctypes.c_uint64 * 4), ('counters', ctypes.c_int32 * 12)]
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        needed = lib.proc_listpids(2, group, None, 0)  # PROC_PGRP_ONLY
        if needed < 0 or needed > (1 << 20):
            raise RuntimeError('cannot enumerate the engine process group')
        pids = (ctypes.c_int * (needed // 4 + 32))()
        size = lib.proc_listpids(2, group, pids, ctypes.sizeof(pids))
        if size < 0 or size >= ctypes.sizeof(pids):
            raise RuntimeError('engine process group enumeration failed or overflowed')
        for pid in pids[:size // 4]:
            if not pid:
                continue
            info = TaskInfo(); ctypes.set_errno(0)
            read = lib.proc_pidinfo(pid, 4, 0, ctypes.byref(info), ctypes.sizeof(info))  # PROC_PIDTASKINFO
            if read != ctypes.sizeof(info):
                if ctypes.get_errno() in (0, errno.ESRCH):
                    continue  # A child can exit between enumeration and inspection.
                raise OSError(ctypes.get_errno(), 'cannot inspect engine process memory')
            count += 1; memory_kib += info.resident // 1024
    else:
        pages_kib = os.sysconf('SC_PAGE_SIZE') // 1024
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            try:
                # comm may contain spaces and parentheses; the final ')' ends it.
                fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
                if int(fields[2]) == group:
                    count += 1; memory_kib += int(fields[21]) * pages_kib
            except (OSError, ValueError, IndexError):
                continue
    return count, memory_kib


def observe(group, root, value, measurements=None):
    count, memory = group_usage(group)
    if measurements is not None:
        measurements['samples']=measurements.get('samples',0)+1
        measurements['sampled_peak_processes']=max(count,measurements.get('sampled_peak_processes',0))
        measurements['sampled_peak_resident_kib']=max(memory,measurements.get('sampled_peak_resident_kib',0))
    if count > value['processes']:
        return 'process count exceeded'
    if memory > value['memory_mib'] * 1024:
        return 'resident memory budget exceeded'
    total = 0; files = 0
    for path in Path(root).rglob('*'):
        if path.is_symlink():
            continue
        try:
            if path.is_file():
                files += 1; total += path.stat().st_size
        except FileNotFoundError:
            continue
        if files > 10000 or total > value['attempt_mib'] << 20:
            return 'attempt storage budget exceeded'
    if measurements is not None:
        measurements['sampled_peak_files']=max(files,measurements.get('sampled_peak_files',0))
        measurements['sampled_peak_workspace_bytes']=max(total,measurements.get('sampled_peak_workspace_bytes',0))
    return None
