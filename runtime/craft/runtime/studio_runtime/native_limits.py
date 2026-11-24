"""Private exec trampoline: tighten inherited limits before a native engine starts.

Invoked with the bundled Python in isolated mode. Keeping this in a fresh process
avoids preexec_fn and process-wide limit changes in a potentially threaded caller.
This is resource enforcement for owned jobs, not a hostile-process sandbox.
"""
import os
import resource
import signal
import sys


def tighten(kind, maximum):
    soft, hard = resource.getrlimit(kind)
    bounded = min([maximum] + [value for value in (soft, hard) if value != resource.RLIM_INFINITY])
    resource.setrlimit(kind, (bounded, bounded))


def main(arguments):
    if len(arguments) < 4 or arguments[2] != '--':
        raise ValueError('invalid native resource launch')
    file_bytes, cpu_seconds = int(arguments[0]), int(arguments[1])
    command = arguments[3:]
    if not 1 <= file_bytes <= 512 << 20 or not 1 <= cpu_seconds <= 86400 or not os.path.isabs(command[0]):
        raise ValueError('invalid native resource bounds or executable')
    tighten(resource.RLIMIT_FSIZE, file_bytes)
    tighten(resource.RLIMIT_CPU, cpu_seconds)
    tighten(resource.RLIMIT_CORE, 0)
    # Python ignores this signal. Restore it before exec so an oversized native
    # write terminates at the kernel boundary rather than relying on error handling.
    signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
    signal.signal(signal.SIGXCPU, signal.SIG_DFL)
    os.execv(command[0], command)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (OSError, ValueError) as error:
        print('Native resource launch failed: '+str(error), file=sys.stderr)
        sys.exit(1)
