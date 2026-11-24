"""Fixed distribution receipt resolution; project data cannot select code."""
from .write_binding import _component
from .sheets_project import PIN

VERSION = PIN['version']
VERSION_RESPONSE = 'dobe-sheets '+VERSION


def resolve():
    try: return {**_component('sheets',VERSION_RESPONSE,PIN['source_lock_sha256']), 'expected_pin':dict(PIN)}
    except ValueError as error: raise ValueError(str(error).replace('Write ', 'Sheets ', 1)) from error


def available():
    try: resolve(); return True
    except (OSError,ValueError): return False
