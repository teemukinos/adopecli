"""Start a job worker when a source checkout (bin/dope) submits work.

The packaged product runs its worker as a managed service. A source checkout has no
service, so a submit or retry starts a worker if none is running. The worker runs
in its own session, so jobs finish even when the agent disconnects, and it stops
after IDLE_EXIT seconds without work. A second worker exits at once because the
first one holds the state lock, so starting one is always safe.
"""
import subprocess
import sys
from pathlib import Path

IDLE_EXIT = 900


def ensure(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    log = state.with_name(state.name + '.worker.log')
    with open(log, 'ab') as output:
        # The child inherits this process's network-deny sandbox from bin/dope.
        subprocess.Popen([sys.executable, '-B', '-m', 'studio_runtime.checkout', '--state', str(state),
                          'worker', '--idle-exit', str(IDLE_EXIT)],
                         stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
