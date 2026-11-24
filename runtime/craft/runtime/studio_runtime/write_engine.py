"""Receipt-bound, cancellable native observation of owned Write project models.

The observer uses fixed version/snapshot commands. The typed export adapter also
uses this private transport for bounded picture/glyph diagnostics and strict
page delivery. This is not a hostile-process sandbox, full source-format
admission or durable publication boundary.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time

from . import write_container as container, write_project as project, write_revision
from .animate_process import run
from .write_container import require


def owned(root, path):
    path = Path(path).absolute()
    try: relative = path.relative_to(root)
    except ValueError as error: raise ValueError('Write native path must stay inside its attempt') from error
    require(relative.parts and '..' not in relative.parts, 'native path must name an attempt descendant')
    current = root
    for part in relative.parts:
        current /= part; require(not current.is_symlink(), 'native paths cannot contain symbolic links')
    return path


def executable_digest(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 512 << 20, 'native executable is not a bounded regular file')
        digest = hashlib.sha256(); total = 0
        while True:
            chunk = stream.read(1 << 20)
            if not chunk: break
            total += len(chunk); require(total <= before.st_size, 'native executable changed during verification'); digest.update(chunk)
        after = os.fstat(stream.fileno())
        require(total == before.st_size and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                'native executable changed during verification')
    return digest.hexdigest(), total, after


class Engine:
    def __init__(self, executable, root, *, expected_pin, expected_binary_sha256, seconds=120, cancelled=lambda: False):
        require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 600, 'native observation time budget is invalid')
        require(type(expected_binary_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_binary_sha256) is not None,
                'native observation needs a verified receipt binary hash')
        self.root = Path(root).resolve(strict=True); require(self.root.is_dir(), 'native observation needs an owned attempt directory')
        path = Path(executable).absolute()
        require(path.name == 'dobe-write' and path.parent.name == 'bin', 'native executable layout differs')
        current = Path(path.anchor)
        for part in path.parts[1:]:
            require(part != '..', 'native executable path is ambiguous'); current /= part
            require(not current.is_symlink(), 'native executable cannot use symbolic links')
        self.executable = str(path); self.pin = project.engine_pin(expected_pin); self.binary_sha256 = expected_binary_sha256
        self.deadline = time.monotonic()+seconds; self.cancelled = cancelled; self.calls = 0
        require(not cancelled(), 'native observation cancelled')
        metadata = container.strict_json(container.read_bytes(path.parent.parent/'engine.json'))
        require(type(metadata) is dict and metadata.get('product') == 'dobe-write' and type(metadata.get('source_lock')) is dict,
                'native engine manifest is invalid')
        lock = metadata['source_lock']; encoded_lock = (json.dumps(lock, indent=2, sort_keys=True)+'\n').encode()
        require(type(lock.get('source')) is dict and type(metadata.get('files')) is dict, 'native engine source/file inventory is invalid')
        pin = {'product': metadata['product'], 'version': lock.get('engine_version'),
               'source_revision': lock.get('source', {}).get('revision'), 'source_lock_sha256': project.sha(encoded_lock)}
        require(project.engine_pin(pin) == self.pin and metadata.get('source_lock_sha256') == self.pin['source_lock_sha256'],
                'native engine manifest differs from verified source pin')
        observed, size, identity = executable_digest(path)
        require(observed == expected_binary_sha256 and metadata.get('files', {}).get('bin/dobe-write') == {'bytes': size, 'sha256': observed},
                'native executable differs from verified receipt')
        self.binary_identity = identity
        version = self._run('--version', limit=8192).strip()
        require(version == ('dobe-write '+self.pin['version']+' ('+self.pin['source_revision']+')').encode(), 'native executable version differs from verified receipt')

    def _unchanged_engine(self):
        path = Path(self.executable); require(not path.is_symlink(), 'native executable became a symbolic link')
        now = path.stat(); original = self.binary_identity
        require((now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns, now.st_ctime_ns) ==
                (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns, original.st_ctime_ns), 'native executable changed after receipt verification')

    def _run(self, *arguments, limit=container.MAX_JSON):
        self._unchanged_engine(); self.calls += 1
        try:
            output = run([self.executable, *map(str, arguments)], self.root, deadline=self.deadline, cancelled=self.cancelled,
                         stdout_limit=limit, stderr_limit=1 << 20, file_limit=container.MAX_SOURCE)
        except ValueError as error: raise ValueError(str(error).replace('Animate native', 'Write native')) from error
        self._unchanged_engine(); return output

    def observe(self, path, expected):
        """Reinspect exact native JSON bytes before starting the fixed snapshot route."""
        path = owned(self.root, path); profile = project.native_profile(expected)
        require(container.read_bytes(path) == expected, 'native model changed before observation')
        value = container.strict_json(self._run('snapshot', path))
        require(type(value) is dict and set(value) == {'schemaVersion', 'encrypted', 'sourceState', 'document'}, 'native snapshot envelope differs')
        require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['encrypted'] is False, 'native snapshot version/encryption differs')
        state = {'keptMarkup': None, 'missingPictures': {'total': 0, 'truncated': False, 'pictures': []}}
        require(write_revision.canonical(value['sourceState']) == write_revision.canonical(state), 'native JSON snapshot has omitted read-time state')
        require(write_revision.canonical(value['document']) == write_revision.canonical(profile['document']), 'native snapshot changed the complete predicted model')
        require(container.read_bytes(path) == expected, 'native observation changed immutable model bytes')
        return {'model_sha256': project.sha(expected), 'complete_model_equal': True, 'source_state': state,
                'pending_qualification': profile['pending_qualification'], 'engine_admission_complete': False}

    def verify_project(self, data, destination):
        checked = project.inspect_bytes(data); project.require_engine(checked, self.pin)
        destination = owned(self.root, destination); created = False
        try:
            project.checkout(self.root, destination, data, cancelled=self.cancelled); created = True
            baseline = self.observe(destination/'baseline.json', checked['members']['baseline.json'])
            first = self.observe(destination/'document.json', checked['members']['document.json'])
            second = self.observe(destination/'document.json', checked['members']['document.json'])
            require({p.name for p in destination.iterdir()} == set(checked['members']), 'native observation introduced unexpected project files')
            require(all(container.read_bytes(destination/name) == value for name, value in checked['members'].items()), 'native observation changed owned project files')
            require(not self.cancelled(), 'native project verification cancelled')
            return {'schema_version': 1, 'project_sha256': checked['sha256'], 'source_sha256': checked['source_sha256'],
                    'current_sha256': checked['current_sha256'], 'engine': self.pin, 'binary_sha256': self.binary_sha256,
                    'native_calls': self.calls, 'baseline_model_equal': baseline['complete_model_equal'],
                    'current_model_equal': first['complete_model_equal'] and second['complete_model_equal'], 'native_cold_reopen': True,
                    'original_bytes_unchanged': True, 'revision_count': checked['revision_count'],
                    'pending_qualification': [item for item in checked['pending_qualification']
                                              if item not in ('native-full-model-comparison', 'native-model-comparison')],
                    'engine_admission_complete': False,
                    'source_format_fidelity_qualified': False, 'durable_publication_qualified': False}
        except BaseException:
            if created: shutil.rmtree(destination)
            raise
