"""Resolve Write only from the current runtime's fixed distribution receipt.

The local installer explicitly admits an unsigned development bundle. The Linux
worker assembler creates a separate receipt for an immutable worker image.
This module checks consistency with that receipt; it is not a signature verifier
or Linux execution qualification.
Neither project parameters, PATH nor environment variables select the executable.
"""
import json
from pathlib import Path
import platform

from . import write_container as container, write_project as project, write_engine
from .write_container import require

VERSION = '0.18.1'
REVISION = '079f478bd85df7bcc567e3bafa7d7219096f9c3c'
LOCK_SHA256 = 'e54589e6483c7958228df1136b0fd9e50a163dabe79c30c6dca3766e4e9c9d6b'
PIN = {'product': 'dobe-write', 'version': VERSION, 'source_revision': REVISION, 'source_lock_sha256': LOCK_SHA256}
VERSION_RESPONSE = 'dobe-write '+VERSION+' ('+REVISION+')'
PDF_LOCK_SHA256 = '4ec85a33847e624adfe2a8cbcaf8050c2742bd9c6db9a7bd80a2add4971c2bba'


CHECKOUT_HOSTS = {('Darwin', 'arm64'): 'aarch64-apple-darwin'}


def checkout_root():
    """The source checkout that contains this module, or None inside a package.

    Derived from this file's own location (ROOT/runtime/craft/runtime/studio_runtime),
    never from PATH, project parameters or environment variables.
    """
    root = Path(__file__).resolve().parents[4]
    if (root/'bin'/'dope').is_file() and (root/'scripts'/'setup').is_file() and (root/'.engines').is_dir():
        return root
    return None


def _checkout_component(root, name, version_response, lock_sha256):
    """Check an engine that scripts/setup built into ROOT/.engines/NAME against its own receipt."""
    host = CHECKOUT_HOSTS.get((platform.system(), platform.machine()))
    require(host is not None, 'source checkouts run on macOS Apple Silicon only')
    product = 'dobe-'+name
    engines = write_engine.owned(root, root/'.engines')
    engine_root = write_engine.owned(root, engines/name)
    require((engine_root/'engine.json').is_file(), f'the {name} engine is not built; run scripts/setup --only {name}')
    metadata = container.strict_json(container.read_bytes(write_engine.owned(root, engine_root/'engine.json')))
    require(type(metadata) is dict and type(metadata.get('source_lock')) is dict and type(metadata.get('files')) is dict,
            'engine receipt fields are invalid')
    lock_bytes = (json.dumps(metadata['source_lock'], indent=2, sort_keys=True)+'\n').encode()
    require(metadata.get('product') == product and metadata.get('host') == host
            and metadata.get('version') == version_response and metadata.get('source_lock_sha256') == lock_sha256
            and project.sha(lock_bytes) == lock_sha256,
            f'the {name} engine was built from a different lock; run scripts/setup --only {name}')
    executable = write_engine.owned(root, engine_root/'bin'/product)
    digest, size, _ = write_engine.executable_digest(executable)
    require(metadata['files'].get('bin/'+product) == {'bytes': size, 'sha256': digest},
            f'the {name} engine binary differs from its build receipt; run scripts/setup --only {name}')
    return {'executable': executable, 'expected_binary_sha256': digest}


def _component(name, version_response, lock_sha256):
    resources = Path(__file__).resolve().parents[2]
    if not (resources.name == 'dobe' and resources.parent.name == 'lib'):
        root = checkout_root()
        require(root is not None, 'requires the bundled Dobe runtime or a source checkout set up with scripts/setup')
        return _checkout_component(root, name, version_response, lock_sha256)
    package = resources.parent.parent
    manifest = container.strict_json(container.read_bytes(resources/'bundle.json'))
    require(type(manifest) is dict and type(manifest.get('schema_version')) is int and manifest['schema_version'] == 1
            and manifest.get('product') == 'dobe', 'bundle identity is invalid')
    target = (manifest.get('distribution'), manifest.get('platform'), platform.system(), platform.machine())
    hosts = {('dobe-cli','macos-arm64','Darwin','arm64'): 'aarch64-apple-darwin',
             ('dobe-worker','linux-amd64','Linux','x86_64'): 'x86_64-unknown-linux-gnu'}
    require(target in hosts, 'bundle identity/platform is not admitted')
    require(type(manifest.get('files')) is dict and type(manifest.get('components')) is list, 'bundle receipt inventory is invalid')
    product = 'dobe-'+name
    components = [entry for entry in manifest['components'] if type(entry) is dict and entry.get('name') == product]
    require(len(components) == 1, 'bundle must declare exactly one maintained engine')
    component = components[0]
    require(component.get('version') == version_response and component.get('source_lock_sha256') == lock_sha256,
            'component differs from the qualified source lock')
    engine_root = write_engine.owned(package, resources/'engines'/name)
    metadata_path = write_engine.owned(package, engine_root/'engine.json')
    metadata_bytes = container.read_bytes(metadata_path)
    require(manifest['files'].get(metadata_path.relative_to(package).as_posix()) == project.record(metadata_bytes)
            and component.get('engine_manifest_sha256') == project.sha(metadata_bytes), 'engine manifest differs from bundle receipt')
    metadata = container.strict_json(metadata_bytes)
    require(type(metadata) is dict and type(metadata.get('source_lock')) is dict and type(metadata.get('files')) is dict,
            'engine receipt fields are invalid')
    lock_bytes = (json.dumps(metadata['source_lock'], indent=2, sort_keys=True)+'\n').encode()
    require(metadata.get('product') == product and metadata.get('host') == hosts[target]
            and metadata.get('version') == version_response and metadata.get('source_lock_sha256') == lock_sha256
            and project.sha(lock_bytes) == lock_sha256, 'engine lock differs from qualified runtime')
    executable = write_engine.owned(package, engine_root/'bin'/product)
    digest, size, _ = write_engine.executable_digest(executable)
    record = {'bytes': size, 'sha256': digest}
    require(metadata['files'].get('bin/'+product) == record
            and manifest['files'].get(executable.relative_to(package).as_posix()) == record,
            'binary differs from bundle receipt')
    return {'executable': executable, 'expected_binary_sha256': digest}


def resolve():
    return {**_component('write', VERSION_RESPONSE, LOCK_SHA256), 'expected_pin': dict(PIN)}


def resolve_pdf():
    return _component('pdf', 'dobe-pdf 0.21.1', PDF_LOCK_SHA256)


def available():
    try: resolve(); return True
    except (OSError, ValueError): return False
