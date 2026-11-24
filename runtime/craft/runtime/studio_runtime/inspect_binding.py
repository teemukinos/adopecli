"""Resolve the Inspect executable only from the current distribution receipt."""
from .write_binding import _component
from .inspect_source import PIN

VERSION=PIN['version']
VERSION_RESPONSE='dobe-inspect '+VERSION


def resolve():
    return {**_component('inspect',VERSION_RESPONSE,PIN['source_lock_sha256']),'expected_pin':dict(PIN)}


def available():
    try:resolve();return True
    except (OSError,ValueError):return False
