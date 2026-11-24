"""Local retention maintenance; never deletes a project, revision or imported asset."""
import fcntl
import json
from pathlib import Path
import re
import shutil
import stat
import time
from .store import Conflict


def file_bytes(path):
    if path.is_symlink():
        raise ValueError('maintenance refuses symlinks')
    if path.is_dir():
        return sum(p.lstat().st_size for p in path.rglob('*') if stat.S_ISREG(p.lstat().st_mode))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('maintenance only removes regular files or attempt directories')
    return info.st_size


def collect(store, apply=False, older_than_hours=24):
    if type(older_than_hours) not in (int, float) or not 1 <= older_than_hours <= 87600:
        raise ValueError('retention age must be between 1 and 87600 hours')
    cutoff = time.time() - older_than_hours * 3600
    for directory in (store.blobs, store.staging, store.root / 'attempts'):
        if directory.is_symlink():
            raise ValueError('maintenance refuses symlinked storage directories')
    # Applying requires the local worker to be stopped. This prevents attempts
    # from being created/claimed while their processing directories are removed.
    with open(store.root / 'worker.lock', 'a+') as worker, open(store.root / 'artifacts.lock', 'a+') as artifacts:
        if apply:
            try:
                fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Conflict('stop the local worker before applying cleanup')
        fcntl.flock(artifacts, fcntl.LOCK_EX)
        with store.transaction() as db:
            from .projects import references
            referenced = references(db)
            if any(not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha) for sha in referenced):
                raise ValueError('invalid stored artifact reference; cleanup refused')
            candidates = []
            for path in store.blobs.iterdir():
                if re.fullmatch('[a-f0-9]{64}', path.name) and path.name not in referenced and path.lstat().st_mtime < cutoff:
                    candidates.append(('unreferenced_blob', path))
            for path in store.staging.iterdir():
                if re.fullmatch('[a-f0-9]{32}', path.name) and path.lstat().st_mtime < cutoff:
                    candidates.append(('abandoned_staging_file', path))
            # Interrupted attempts contain uncertain evidence and are retained.
            # Unknown directories and all database/event records are retained too.
            for row in db.execute("SELECT token FROM attempts WHERE state IN ('succeeded','failed','cancelled') AND finished < ?", (cutoff,)):
                token = row[0]
                if not re.fullmatch('[a-f0-9]{32}', token):
                    raise ValueError('invalid stored attempt token; cleanup refused')
                path = store.root / 'attempts' / token
                if path.exists() or path.is_symlink():
                    candidates.append(('terminal_attempt', path))
            # Inspect every candidate before deleting any, including symlink checks.
            plan = [{'kind': kind, 'path': str(path.relative_to(store.root)), 'bytes': file_bytes(path)} for kind, path in candidates]
            if apply:
                for _, path in candidates:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    store._sync_dir(path.parent)
    return {'applied': apply, 'older_than_hours': older_than_hours, 'entries': plan,
            'removed_bytes' if apply else 'reclaimable_bytes': sum(item['bytes'] for item in plan),
            'projects_retained': True, 'interrupted_attempts_retained': True}
