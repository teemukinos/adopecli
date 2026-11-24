"""Kernel identity and launch registration for local attempt reconciliation.

A registered process group is only inspected with signal zero. Reconciliation
never signals a remembered PID or guesses that a reused process belongs to us.
"""
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import sys
import time
from uuid import UUID


def identity():
    if sys.platform == 'darwin':
        library = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        class Timeout(ctypes.Structure):
            _fields_ = [('seconds', ctypes.c_long), ('nanoseconds', ctypes.c_long)]
        timeout = Timeout(1, 0); host = ctypes.create_string_buffer(16)
        library.gethostuuid.argtypes = [ctypes.c_void_p, ctypes.POINTER(Timeout)]
        library.gethostuuid.restype = ctypes.c_int
        if library.gethostuuid(host, ctypes.byref(timeout)):
            raise OSError(ctypes.get_errno(), 'cannot establish local machine identity')
        size = ctypes.c_size_t(128); boot = ctypes.create_string_buffer(128)
        library.sysctlbyname.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
        library.sysctlbyname.restype = ctypes.c_int
        if library.sysctlbyname(b'kern.bootsessionuuid', boot, ctypes.byref(size), None, 0):
            raise OSError(ctypes.get_errno(), 'cannot establish local boot identity')
        machine = str(UUID(bytes=host.raw)); boot_id = str(UUID(boot.value.decode()))
    elif sys.platform == 'linux':
        machine = str(UUID(Path('/etc/machine-id').read_text().strip()))
        boot_id = str(UUID(Path('/proc/sys/kernel/random/boot_id').read_text().strip()))
    else:
        raise ValueError('local execution identity is not supported on this platform')
    return {'machine': hashlib.sha256(('studio-local:' + sys.platform + ':' + machine).encode()).hexdigest(),
            'boot': boot_id}


def group_absent(group):
    if type(group) is not int or not 1 < group < 2147483648:
        raise ValueError('invalid recorded process group')
    try:
        os.killpg(group, 0)
    except OSError as error:
        if error.errno == errno.ESRCH:
            return True
        # EPERM, an unavailable inspection facility, and every other error are
        # uncertainty, not absence. No termination signal is sent here.
        raise
    return False


def wait_group_absent(group, timeout=2.0):
    """Wait briefly for kernel teardown, without treating denied probes as proof.

    Reaping the attempt leader does not reap its native children. On macOS a
    signal-zero probe can return EPERM while those children finish exiting.
    Only ESRCH establishes absence; persistent denial or presence remains
    uncertain and requires reconciliation. Never send another termination
    signal to a group whose leader has already exited.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            if group_absent(group):
                return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def prepare(db, token):
    observed = identity()
    db.execute("INSERT INTO attempt_executions(token,machine,boot,phase,prepared) VALUES(?,?,?,'prepared',?)",
               (token, observed['machine'], observed['boot'], time.time()))


def register(store, workspace, job, token, group):
    if type(group) is not int or group <= 1:
        raise ValueError('invalid execution process group')
    observed = identity()
    with store.transaction() as db:
        store._lease(db, workspace, job, token)
        row = db.execute('SELECT * FROM attempt_executions WHERE token=?', (token,)).fetchone()
        if row is None or row['phase'] != 'prepared' or row['machine'] != observed['machine'] or row['boot'] != observed['boot']:
            raise ValueError('execution registration does not match its prepared launch')
        db.execute("UPDATE attempt_executions SET phase='registered',process_group=?,registered=? WHERE token=?",
                   (group, time.time(), token))
