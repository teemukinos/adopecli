"""Record an offline boundary established by a trusted launcher.

This is internal control-flow state, not kernel attestation. Only the sealed
bundle bootstrap, its admitted attempt, and the sandboxed construction bootstrap
enter this scope. Public requests and environment variables cannot select it.
Direct execution of private bootstrap scripts is outside the sealed entry-point
contract, just as direct execution of a bundled native engine is.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import sys

PROFILE = '(version 1)(allow default)(deny network*)'
_INHERITED = ContextVar('studio_inherited_network_denial', default=False)


def inherited():
    return _INHERITED.get()


@contextmanager
def trusted_scope():
    """Record established confinement; this function does not establish it."""
    token = _INHERITED.set(True)
    try:
        yield
    finally:
        _INHERITED.reset(token)


def command(argv):
    """Inherit known confinement, or require a fresh macOS sandbox."""
    if sys.platform != 'darwin':
        raise ValueError('Construction offline process boundary requires macOS')
    args = list(map(str, argv))
    return args if inherited() else ['/usr/bin/sandbox-exec', '-p', PROFILE, *args]
