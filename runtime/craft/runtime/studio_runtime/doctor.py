"""Report whether this installation can run creative work: sandbox, state and engines."""
import errno
import os
from pathlib import Path
import shutil
import socket
import tempfile

FAMILIES = ('image', 'photo', 'vector', 'motion', 'audio', 'video', 'animate', 'interface', 'layout',
            'pdf', 'write', 'slides', 'sheets', 'cad', 'inspect', 'texture', 'material')
# A policy refusal, as opposed to a closed port (ECONNREFUSED) or a timeout.
POLICY_ERRORS = (errno.EPERM, errno.EACCES)


def network_denied():
    """True when the OS refuses an outbound TCP connection by policy.

    The probe targets the loopback address, so nothing leaves the machine even
    when no sandbox is active.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(2)
    try:
        probe.connect(('127.0.0.1', 9))
    except OSError as error:
        return error.errno in POLICY_ERRORS
    finally:
        probe.close()
    return False


def state_writable(state):
    try:
        state.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=state, prefix='.doctor-'):
            pass
    except OSError:
        return False
    return True


def engine_present(family):
    name = 'dobe-' + family
    resources = os.environ.get('STUDIO_BUNDLE_RESOURCES')
    candidates = [Path(resources) / 'engines' / family / 'bin' / name] if resources else []
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    return any(path.is_file() and os.access(path, os.X_OK) for path in candidates)


def report(state):
    state = Path(os.path.abspath(state))
    denied = network_denied()
    writable = state_writable(state)
    engines = {family: engine_present(family) for family in FAMILIES}
    advice = []
    if not denied:
        advice.append('Network access is not denied. Run dope through its launcher, which applies the network-deny sandbox.')
    if not writable:
        advice.append(f'The state directory {state} is not writable. Choose another with --state or DOPE_STATE_DIR.')
    missing = [family for family, present in engines.items() if not present]
    if missing:
        advice.append('Engines missing or not executable: ' + ', '.join(missing) + '. Reinstall the package, or run scripts/setup in a source checkout.')
    # The launchers refuse with exit 78 before Python starts when an outer
    # sandbox blocks their own, so a running doctor is never nested.
    return {'schema_version': 1, 'sandboxed': False, 'network_denied': denied, 'state_dir': str(state),
            'state_writable': writable, 'engines': engines, 'advice': advice}
