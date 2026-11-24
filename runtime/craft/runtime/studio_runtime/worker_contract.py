"""Image-declared native capabilities, not evidence of platform qualification.

Both the trusted coordinator and the credential-free worker bind the same Python
adapter/boot bytes. An immutable image identifier binds the native payload; its
actual execution and dependency closure still need separate release evidence.
"""
import hashlib
import json
from pathlib import Path
import stat

from .native_contracts import OPERATIONS
from . import portable_contract

LABEL = 'io.adope.worker.contract'
PROFILE = 'native-v2'
IMPLEMENTED = (*OPERATIONS, 'project.import')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def source_digest(boot, runtime=None):
    runtime = Path(runtime) if runtime is not None else Path(__file__).resolve().parent
    boot = Path(boot)
    if runtime.is_symlink() or not runtime.is_dir():
        raise ValueError('worker runtime must be a regular source directory')
    inventory = {}
    for path in sorted(runtime.rglob('*')):
        if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('worker runtime links and special files are refused')
        inventory['runtime/' + path.relative_to(runtime).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not inventory or not stat.S_ISREG(boot.lstat().st_mode):
        raise ValueError('worker boot and runtime source are required')
    inventory['container_boot.py'] = hashlib.sha256(boot.read_bytes()).hexdigest()
    return hashlib.sha256(canonical(inventory).encode()).hexdigest()


def declaration(boot, runtime=None):
    return {'schema_version': 2, 'profile': PROFILE,
            'source_sha256': source_digest(boot, runtime), 'operations': list(IMPLEMENTED), 'import_families': list(portable_contract.FAMILIES)}


def validate(value, expected):
    if (not isinstance(value, dict) or set(value) != set(expected)
            or type(value.get('schema_version')) is not int or value['schema_version'] != 2
            or value.get('profile') != PROFILE or value.get('source_sha256') != expected['source_sha256']):
        raise ValueError('worker image source contract differs from this runtime')
    operations = value.get('operations')
    if (not isinstance(operations, list) or not operations
            or any(type(op) is not str for op in operations)
            or len(set(operations)) != len(operations)
            or set(operations) - set(expected['operations'])):
        raise ValueError('worker image must declare unique implemented native operations')
    imported = portable_contract.families(value.get('import_families'))
    if set(imported)-set(expected['import_families']) or ('project.import' in operations and not imported):
        raise ValueError('worker image requires supported nonempty import families')
    return tuple(operations)


def decode(raw, expected):
    if type(raw) is not str or not 1 <= len(raw.encode()) <= 65536:
        raise ValueError('bounded worker image contract label required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate worker contract field')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    validate(value, expected)
    return value


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot', type=Path, required=True)
    args = parser.parse_args()
    print(canonical(declaration(args.boot)))
