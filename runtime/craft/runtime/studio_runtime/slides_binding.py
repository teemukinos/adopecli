"""Bind Slides to the current CLI distribution, never to project-selected code.

The shared receipt reader checks installation consistency, not a code signature.
The shared reader admits the macOS ARM64 distribution and the prepared Linux
x86-64 worker receipt. Receipt consistency alone does not qualify execution.
"""
from .write_binding import _component

VERSION = '0.18.1'
REVISION = '7cc73ab1895ed2e30c8afbcada20c70b9ea0a440'
LOCK_SHA256 = '60614491e1c2f2194cfc1078d415cec9eaf9a4b4b8d1935875434ede7ec086ef'
PIN = {'product': 'dobe-slides', 'version': VERSION, 'source_revision': REVISION, 'source_lock_sha256': LOCK_SHA256}
VERSION_RESPONSE = 'dobe-slides '+VERSION+' ('+REVISION+')'


def resolve():
    return {**_component('slides', VERSION_RESPONSE, LOCK_SHA256), 'expected_pin': dict(PIN)}


def available():
    try: resolve(); return True
    except (OSError, ValueError): return False
