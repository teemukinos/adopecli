"""Explicit local project archival and resumable artifact deletion.

Metadata and event history are retained. Shared blobs remain while another
project references them. Unknown processing files and uncertain attempts are
never inferred to be safe deletion targets.
"""
import fcntl
import json
import re
import shutil
import stat
import time
from .store import Conflict, artifact_write, canonical


def references(db, project=None, excluding=None):
    """Return hashes retained by projects, including archived/deleting projects."""
    where = "p.state!='deleted'"
    values = []
    if project is not None:
        where += ' AND p.id=?'; values.append(project)
    if excluding is not None:
        where += ' AND p.id!=?'; values.append(excluding)
    hashes = {row[0] for row in db.execute('SELECT a.sha256 FROM assets a JOIN projects p ON p.id=a.project WHERE ' + where, values)}
    for row in db.execute('SELECT r.manifest FROM revisions r JOIN projects p ON p.id=r.project WHERE ' + where, values):
        hashes.update(entry['sha256'] for entry in json.loads(row[0])['files'])
    if any(not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha) for sha in hashes):
        raise ValueError('invalid stored artifact reference; deletion refused')
    return hashes


def idle(db, project, uncertain_history=False):
    if db.execute("SELECT 1 FROM jobs WHERE project=? AND state IN ('queued','running','validating','interrupted') LIMIT 1", (project,)).fetchone():
        raise Conflict('settle all project jobs before changing retention')
    if uncertain_history and db.execute("""SELECT 1 FROM attempts a JOIN jobs j ON j.id=a.job
        WHERE j.project=? AND a.state NOT IN ('succeeded','failed','cancelled') LIMIT 1""", (project,)).fetchone():
        raise Conflict('uncertain attempt history must be reconciled before deleting project artifacts')


def event(db, project, kind, detail):
    db.execute('INSERT INTO project_events(project,kind,detail,created) VALUES(?,?,?,?)',
               (project, kind, canonical(detail), time.time()))


@artifact_write
def set_state(store, workspace, project, state):
    if state not in ('active', 'archived'):
        raise ValueError('project state must be active or archived')
    with store.transaction() as db:
        row = store._project(db, workspace, project)
        if row['state'] in ('deleting', 'deleted'):
            raise Conflict('project artifact deletion cannot be reversed')
        idle(db, project)
        if row['state'] != state:
            db.execute('UPDATE projects SET state=? WHERE id=?', (state, project))
            event(db, project, 'project_' + state, {})
    return store.get_project(workspace, project)


def inspect_file(path, directory=False):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or (directory and not stat.S_ISDIR(info.st_mode)):
        raise ValueError('project deletion refuses unsafe processing paths')
    if not directory:
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('project deletion only removes regular blobs')
        return info.st_size
    size = 0
    for child in path.rglob('*'):
        child_info = child.lstat()
        if stat.S_ISDIR(child_info.st_mode):
            continue
        if not stat.S_ISREG(child_info.st_mode):
            raise ValueError('project deletion refuses symlinks and special files')
        size += child_info.st_size
    return size


def delete_artifacts(store, workspace, project, apply=False):
    if type(apply) is not bool:
        raise ValueError('apply must be a boolean')
    # Exclude the supervisor as well as blob writers/readers. Keep this order
    # consistent with general retention cleanup to avoid lock inversion.
    with open(store.root / 'worker.lock', 'a+') as worker, open(store.root / 'artifacts.lock', 'a+') as artifacts:
        if apply:
            try:
                fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Conflict('stop the local worker before deleting project artifacts')
        fcntl.flock(artifacts, fcntl.LOCK_EX)
        for directory in (store.blobs, store.root / 'attempts'):
            if directory.is_symlink():
                raise ValueError('project deletion refuses symlinked storage directories')
        with store.transaction() as db:
            row = store._project(db, workspace, project)
            idle(db, project, uncertain_history=True)
            if row['state'] == 'deleted':
                return {'project': project, 'state': 'deleted', 'applied': apply, 'entries': [],
                        'removed_bytes' if apply else 'reclaimable_bytes': 0, 'metadata_retained': True}
            owned = references(db, project=project)
            shared = owned & references(db, excluding=project)
            paths = []
            for sha in sorted(owned - shared):
                path = store.blobs / sha
                if path.exists() or path.is_symlink():
                    paths.append(('project_blob', path, inspect_file(path)))
            for attempt in db.execute('''SELECT a.token FROM attempts a JOIN jobs j ON j.id=a.job
                WHERE j.project=? ORDER BY a.token''', (project,)):
                token = attempt[0]
                if not re.fullmatch('[a-f0-9]{32}', token):
                    raise ValueError('invalid attempt token; deletion refused')
                path = store.root / 'attempts' / token
                if path.exists() or path.is_symlink():
                    paths.append(('project_attempt', path, inspect_file(path, directory=True)))
            plan = [{'kind': kind, 'path': str(path.relative_to(store.root)), 'bytes': size} for kind, path, size in paths]
            result = {'project': project, 'state': row['state'], 'applied': apply, 'entries': plan,
                      'shared_blobs_retained': len(shared), 'metadata_retained': True,
                      'removed_bytes' if apply else 'reclaimable_bytes': sum(item['bytes'] for item in plan)}
            if not apply:
                return result
            if row['state'] != 'deleting':
                db.execute("UPDATE projects SET state='deleting' WHERE id=?", (project,))
                event(db, project, 'artifact_deletion_requested', {'entries': plan, 'shared_blobs_retained': len(shared)})
        # Intent is durable before unlink. A crash may leave partial removal; a
        # fresh call recomputes shared references before continuing. No old plan
        # can remove a blob that another project imported after the crash.
        for kind, path, _ in paths:
            if kind == 'project_attempt':
                shutil.rmtree(path)
            else:
                path.unlink()
            store._sync_dir(path.parent)
        with store.transaction() as db:
            db.execute("UPDATE projects SET state='deleted',files_deleted_at=? WHERE id=?", (time.time(), project))
            event(db, project, 'artifacts_deleted', {'removed_bytes': result['removed_bytes'], 'shared_blobs_retained': len(shared)})
        result['state'] = 'deleted'
        return result
