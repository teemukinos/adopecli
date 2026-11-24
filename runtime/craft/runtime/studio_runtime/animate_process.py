"""Bounded, cancellable transport for private Animate CLI operations.

The runtime supplies the executable, arguments and owned working directory.
This module is not a public command endpoint or an operating-system sandbox.
Both pipes are limited while reading, including after the leader exits: a child
holding a pipe cannot turn a decoder timeout into an unbounded cleanup wait.
An optional file limit uses an isolated exec trampoline to tighten kernel quotas
without changing the caller's limits or running a preexec callback in its process.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

_ATTEMPT_GROUP = ContextVar('animate_attempt_group', default=False)


@contextmanager
def attempt_group():
    """Keep native children inside the supervisor's registered process group.

    Only the attempt leader may enter this scope. Fixed Animate commands never
    launch external tools. The supervisor can therefore stop the complete job
    with its existing group kill, including when Python cannot run its finally.
    Standalone probes retain independent group ownership and cleanup.
    """
    if os.getpid() != os.getpgrp():
        raise ValueError('Animate attempt scope requires a process group leader')
    token = _ATTEMPT_GROUP.set(True)
    try:
        yield
    finally:
        _ATTEMPT_GROUP.reset(token)


def run(command, root, *, deadline, cancelled=lambda: False, stdout_limit=8192, stderr_limit=8192, file_limit=None):
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or any(type(n) is not int or not 1 <= n <= 64 << 20 for n in (stdout_limit, stderr_limit))
            or file_limit is not None and (type(file_limit) is not int or not 1 <= file_limit <= 512 << 20)):
        raise ValueError('Animate native process limits are invalid')

    def check():
        if cancelled() or time.monotonic() >= deadline:
            raise ValueError('Animate native operation cancelled or timed out')

    check()
    independent_group = not _ATTEMPT_GROUP.get()
    if file_limit is not None:
        if not command or not os.path.isabs(command[0]):
            raise ValueError('Animate limited native executable must be absolute')
        seconds = min(86400, max(1, math.ceil(deadline-time.monotonic())))
        command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('native_limits.py')),
                   str(file_limit), str(seconds), '--', *command]
    process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=independent_group,
        env={'HOME': str(root), 'TMPDIR': str(root), 'PATH': '/usr/bin:/bin'})
    output = [bytearray(), bytearray()]
    try:
        with selectors.DefaultSelector() as selector:
            for index, pipe in enumerate((process.stdout, process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, (index, (stdout_limit, stderr_limit)[index]))
            while selector.get_map():
                check()
                for key, _ in selector.select(min(.05, max(0, deadline - time.monotonic()))):
                    index, limit = key.data
                    try:
                        data = os.read(key.fd, min(65536, limit - len(output[index]) + 1))
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(key.fileobj)
                    elif len(output[index]) + len(data) > limit:
                        raise ValueError('Animate native operation exceeded its ' + ('stdout', 'stderr')[index] + ' budget')
                    else:
                        output[index].extend(data)
            while True:
                check()
                try:
                    code = process.wait(timeout=min(.05, max(.001, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    continue
        if code:
            if file_limit is not None and code == -signal.SIGXFSZ:
                raise ValueError('Animate native operation exceeded its file byte budget')
            if file_limit is not None and code == -signal.SIGXCPU:
                raise ValueError('Animate native operation exceeded its CPU budget')
            raise ValueError('Animate native operation failed: ' + output[1][:500].decode('utf-8', 'replace'))
        return bytes(output[0])
    finally:
        # Never kill the inherited attempt group here: that would kill Python
        # before it reports an error. The supervisor owns that group. Standalone
        # probes still kill their entire group, even after its leader exits.
        try:
            if independent_group:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.stdout.close()
        process.stderr.close()
        process.wait()
