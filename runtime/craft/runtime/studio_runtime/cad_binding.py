"""Resolve CAD from the current fixed CLI receipt, never project-selected code.

Receipt consistency is not a signature or release qualification. CAD packaging
and public admission must be qualified separately before public jobs enable it.
"""
from .write_binding import _component

VERSION = '0.20.1'
REVISION = '7526dc62c14e71b3c8d46e73bbf1fa29ef506af1'
LOCK_SHA256 = '383362c1a5e33c1623563d3c407206d0a3669fc723af644dfebdbe0460835059'
PIN = {'product': 'dobe-cad', 'version': VERSION, 'source_revision': REVISION, 'source_lock_sha256': LOCK_SHA256}
VERSION_RESPONSE = 'dobe-cad '+VERSION


def resolve():
    try: return {**_component('cad', VERSION_RESPONSE, LOCK_SHA256), 'expected_pin': dict(PIN)}
    except ValueError as error: raise ValueError(str(error).replace('Write ', 'CAD ', 1)) from error


def available():
    try: resolve(); return True
    except (OSError, ValueError): return False
