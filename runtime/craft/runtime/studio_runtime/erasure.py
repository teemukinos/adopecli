"""Explicit, resumable local project erasure with scoped SQLite authority.

This removes managed application data. It does not promise physical media,
backup, snapshot, exported-copy or process-memory erasure.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time
from . import capacity, execution
from .store import Conflict, NotFound, project_erasure_key

TABLES = ('projects', 'project_events', 'jobs', 'attempts', 'attempt_executions',
          'attempt_reconciliations', 'revisions', 'assets', 'retries', 'events')
AGENT_PROJECT_TABLES = ('agent_runs', 'agent_calls', 'agent_steps')
EXTERNAL = ('hosted_records', 'original_imports', 'external_exports',
            'assistant_transcripts', 'device_backups', 'filesystem_snapshots', 'process_memory')


def _row_key(table, row):
    if table == 'project_erasures':
        return row + '.key'
    if table == 'projects':
        return f'studio_project_erasure_key({row}.workspace,{row}.id)'
    if table in ('jobs', 'assets', 'revisions', 'agent_runs'):
        return f'studio_project_erasure_key({row}.workspace,{row}.project)'
    if table in ('agent_calls', 'agent_steps'):
        return f'(SELECT studio_project_erasure_key(workspace,project) FROM agent_runs WHERE id={row}.run)'
    if table == 'project_events':
        return f'(SELECT studio_project_erasure_key(workspace,id) FROM projects WHERE id={row}.project)'
    if table in ('attempts', 'retries', 'events'):
        return f'(SELECT studio_project_erasure_key(workspace,project) FROM jobs WHERE id={row}.job)'
    return f'''(SELECT studio_project_erasure_key(j.workspace,j.project) FROM attempts a
        JOIN jobs j ON j.id=a.job WHERE a.token={row}.token)'''


def install_guards(db):
    """Install schema guards in the stopped-worker migration transaction."""
    for table in (*TABLES, *AGENT_PROJECT_TABLES, 'project_erasures'):
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            name = f'erasure_scope_{table}_{action.lower()}'
            db.execute(f'DROP TRIGGER IF EXISTS {name}')
            row = 'OLD' if action == 'DELETE' else 'NEW'
            old_scope = f" OR studio_erasure_authority() IS NOT {_row_key(table, 'OLD')}" if action == 'UPDATE' else ''
            db.execute(f'''CREATE TRIGGER {name} BEFORE {action} ON {table}
                WHEN studio_erasure_authority()!='' AND
                  (studio_erasure_authority() IS NOT {_row_key(table, row)}{old_scope})
                BEGIN SELECT RAISE(ABORT,'erasure authority is restricted to one project'); END''')
    # Shared budgets retain only aggregate spend when project receipts are erased.
    # Erasure authority cannot change another budget field or refund paid calls.
    for action in ('INSERT', 'DELETE'):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS erasure_budget_{action.lower()}
            BEFORE {action} ON agent_budgets WHEN studio_erasure_authority()!=''
            BEGIN SELECT RAISE(ABORT,'erasure cannot create or delete shared budgets'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS erasure_budget_update
        BEFORE UPDATE ON agent_budgets WHEN studio_erasure_authority()!='' AND (
          NEW.id IS NOT OLD.id OR NEW.workspace IS NOT OLD.workspace
          OR NEW.limit_microusd IS NOT OLD.limit_microusd OR NEW.created IS NOT OLD.created
          OR NOT EXISTS(SELECT 1 FROM project_erasures WHERE key=studio_erasure_authority() AND phase='files')
          OR NOT EXISTS(SELECT 1 FROM agent_runs WHERE budget=OLD.id
            AND studio_project_erasure_key(workspace,project)=studio_erasure_authority())
          OR NEW.retired_microusd-OLD.retired_microusd IS NOT (
            SELECT COALESCE(SUM(COALESCE(c.charged_microusd,c.reserved_microusd)),0)
            FROM agent_calls c JOIN agent_runs r ON r.id=c.run WHERE r.budget=OLD.id
              AND studio_project_erasure_key(r.workspace,r.project)=studio_erasure_authority()))
        BEGIN SELECT RAISE(ABORT,'erasure may only retain selected project spend'); END""")
    for action in ('INSERT', 'UPDATE', 'DELETE'):
        row = 'OLD' if action == 'DELETE' else 'NEW'
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS erasure_record_{action.lower()}
            BEFORE {action} ON project_erasures
            WHEN studio_erasure_authority()='' OR studio_erasure_authority()!={row}.key
            BEGIN SELECT RAISE(ABORT,'explicit local erasure authority required'); END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS erasure_record_no_delete
        BEFORE DELETE ON project_erasures
        BEGIN SELECT RAISE(ABORT,'erasure identity tombstones are retained'); END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS erasure_record_transition
        BEFORE UPDATE ON project_erasures WHEN OLD.phase='complete' OR NEW.key!=OLD.key
          OR NEW.started!=OLD.started OR NEW.settled_attempts!=OLD.settled_attempts
          OR NOT (NEW.phase=OLD.phase OR (OLD.phase='files' AND NEW.phase='database')
            OR (OLD.phase='database' AND NEW.phase='complete'))
        BEGIN SELECT RAISE(ABORT,'invalid erasure transition'); END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS erased_project_no_reinsert
        BEFORE INSERT ON projects WHEN EXISTS(SELECT 1 FROM project_erasures
          WHERE key=studio_project_erasure_key(NEW.workspace,NEW.id))
        BEGIN SELECT RAISE(ABORT,'project identity was erased'); END''')
    for table, prefix in (('attempt_reconciliations', 'reconciliation'), ('attempt_executions', 'execution')):
        db.execute(f'DROP TRIGGER IF EXISTS {prefix}_no_delete')
        db.execute(f'''CREATE TRIGGER {prefix}_no_delete BEFORE DELETE ON {table}
            WHEN studio_erasure_authority()='' OR studio_erasure_authority() IS NOT {_row_key(table, 'OLD')}
              OR NOT EXISTS(SELECT 1 FROM project_erasures
                WHERE key=studio_erasure_authority() AND phase='files')
            BEGIN SELECT RAISE(ABORT,'immutable execution evidence requires explicit settled-project erasure'); END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS reconciliation_no_update
        BEFORE UPDATE ON attempt_reconciliations
        BEGIN SELECT RAISE(ABORT,'reconciliation evidence is immutable'); END''')


@contextmanager
def _lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Conflict('erasure refuses unsafe lock files')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('stop the worker and finish artifact access before erasure')
        yield
    finally:
        os.close(fd)


@contextmanager
def _transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _inspect(path, directory=False):
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise Conflict('erasure refuses unsafe managed directories')
        total = 0
        for child in path.iterdir():
            entry = child.lstat()
            total += _inspect(child, stat.S_ISDIR(entry.st_mode))
        return total
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise Conflict('erasure refuses symlinks, hard links and special files')
    return info.st_size


def _references(db, project=None, excluding=None):
    condition, values = ('project=?', (project,)) if project is not None else ('1=1', ())
    if excluding is not None:
        condition += ' AND project!=?'; values += (excluding,)
    hashes = {row[0] for row in db.execute('SELECT sha256 FROM assets WHERE ' + condition, values)}
    for row in db.execute('SELECT manifest FROM revisions WHERE ' + condition, values):
        hashes.update(entry['sha256'] for entry in json.loads(row[0])['files'])
    if any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value) for value in hashes):
        raise Conflict('erasure refuses invalid stored artifact references')
    return hashes


def _ownership(store, db):
    known = {'blobs', 'staging', 'attempts', 'studio.sqlite3', 'studio.sqlite3-wal',
             'studio.sqlite3-shm', 'worker.lock', 'artifacts.lock', 'limits.json', capacity.RESERVE_NAME}
    for child in store.root.iterdir():
        if child.name not in known:
            raise Conflict('unrecognized managed-state files require separate inspection before erasure')
        directory = child.name in ('blobs', 'staging', 'attempts')
        if directory:
            if not stat.S_ISDIR(child.lstat().st_mode):
                raise Conflict('erasure refuses unsafe managed directories')
        else:
            _inspect(child)
    if any(store.staging.iterdir()):
        raise Conflict('unassigned staging content requires separate inspection before erasure')
    known_tokens = {row[0] for row in db.execute('SELECT token FROM attempts')}
    attempts = store.root / 'attempts'
    if attempts.exists():
        for child in attempts.iterdir():
            if child.name not in known_tokens or not re.fullmatch('[a-f0-9]{32}', child.name):
                raise Conflict('unrecognized attempt folders require separate inspection before erasure')
    referenced = _references(db)
    for child in store.blobs.iterdir():
        if child.name not in referenced or not re.fullmatch('[a-f0-9]{64}', child.name):
            raise Conflict('unassigned blob content requires separate inspection before erasure')
        _inspect(child)


def _settled(db, project):
    for run in db.execute('SELECT * FROM agent_runs WHERE project=?', (project,)):
        if run['state'] not in ('completed', 'failed', 'cancelled', 'budget_exhausted', 'quality_unmet'):
            raise Conflict('settle selected project agent runs before erasure')
        if run['owner'] and (run['lease_until'] or 0) > time.time():
            raise Conflict('stop selected project coordinators before erasure')
        if db.execute("SELECT 1 FROM agent_calls WHERE run=? AND (state IN ('sent','uncertain') OR charged_microusd IS NULL)", (run['id'],)).fetchone():
            raise Conflict('reconcile uncertain provider charges before erasure')
    jobs = db.execute('SELECT * FROM jobs WHERE project=?', (project,)).fetchall()
    count = 0
    observed = None
    for job in jobs:
        if job['state'] not in ('succeeded', 'failed', 'cancelled') or job['token'] is not None or job['lease_until'] is not None:
            raise Conflict('settle all selected project jobs before erasure')
        for attempt in db.execute('SELECT * FROM attempts WHERE job=?', (job['id'],)):
            if attempt['state'] not in ('succeeded', 'failed', 'cancelled') or attempt['finished'] is None:
                raise Conflict('reconcile uncertain selected project attempts before erasure')
            launch = db.execute('SELECT * FROM attempt_executions WHERE token=?', (attempt['token'],)).fetchone()
            if observed is None:
                observed = execution.identity()
            # Reuse the kernel-backed proof, not its already-settled shortcut.
            from . import reconciliation
            proof = reconciliation.proof(dict(job), {**dict(attempt), 'state': 'interrupted'},
                                         dict(launch) if launch else None, observed)
            if not proof['eligible']:
                raise Conflict('selected attempt lacks current local proof of stopped execution')
            count += 1
    return count


def _plan(store, db, workspace, project):
    row = store._project(db, workspace, project)
    settled = _settled(db, project)
    _ownership(store, db)
    owned = _references(db, project=project)
    shared = owned & _references(db, excluding=project)
    paths = []
    for sha in sorted(owned - shared):
        path = store.blobs / sha
        if path.exists() or path.is_symlink():
            paths.append(('project_blob', path, _inspect(path)))
    for attempt in db.execute('SELECT a.token FROM attempts a JOIN jobs j ON j.id=a.job WHERE j.project=? ORDER BY a.token', (project,)):
        if not re.fullmatch('[a-f0-9]{32}', attempt[0]):
            raise Conflict('erasure refuses invalid stored attempt identities')
        path = store.root / 'attempts' / attempt[0]
        if path.exists() or path.is_symlink():
            paths.append(('project_attempt', path, _inspect(path, True)))
    counts = {}
    for table in (*TABLES, *AGENT_PROJECT_TABLES):
        key = _row_key(table, table)
        counts[table] = db.execute(f'SELECT count(*) FROM {table} WHERE {key}=?',
                                  (project_erasure_key(workspace, project),)).fetchone()[0]
    return row, settled, shared, paths, counts


def _headroom(store):
    space = os.statvfs(store.root)
    database = store.db.stat().st_size
    wal = Path(str(store.db) + '-wal')
    if wal.exists():
        database = max(database, wal.stat().st_size)
    required = max(32 * 1024 * 1024, database * 3)
    if space.f_bavail * space.f_frsize < required:
        raise Conflict('database cleanup needs more free space; erasure remains unfinished')


def _checkpoint(db):
    result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
    if result[0] != 0 or result[1] != result[2]:
        raise Conflict('close open database readers before finishing erasure cleanup')


def _result(key, phase, settled, shared, applied):
    return {'erasure': key, 'phase': phase, 'applied': applied,
            'complete': phase == 'complete', 'settled_attempts': settled,
            'shared_blobs_retained': shared, 'external_locations_untouched': list(EXTERNAL),
            'physical_media_erasure_claimed': False}


def _erase_project(store, workspace, project, apply=False):
    if workspace != 'local':
        raise ValueError('project erasure is local only')
    if type(apply) is not bool or not isinstance(project, str) or not re.fullmatch('[a-f0-9]{32}', project):
        raise ValueError('erasure requires a generated local project identifier and a boolean apply flag')
    key = project_erasure_key(workspace, project)
    # Locks also prevent file writers from leaving new unassigned blobs while
    # database writes are fenced. No worker or installed service is stopped here.
    with _lock(store.root / 'worker.lock'), _lock(store.root / 'artifacts.lock'):
        with store._connect(erasure_key=key) as db:
            db.execute('PRAGMA busy_timeout=1000')
            db.execute('PRAGMA secure_delete=ON')
            pending = db.execute("SELECT key FROM project_erasures WHERE phase!='complete' AND key!=?", (key,)).fetchone()
            if pending:
                raise Conflict('finish the pending local project erasure before selecting another project')
            receipt = db.execute('SELECT * FROM project_erasures WHERE key=?', (key,)).fetchone()
            if receipt and receipt['phase'] == 'complete':
                return _result(key, 'complete', receipt['settled_attempts'], receipt['shared_blobs'], apply)
            if receipt and receipt['phase'] == 'database' and not apply:
                return _result(key, 'database', receipt['settled_attempts'], receipt['shared_blobs'], False)
            if not receipt or receipt['phase'] == 'files':
                with _transaction(db):
                    row, settled, shared, paths, counts = _plan(store, db, workspace, project)
                    if not apply:
                        return {**_result(key, 'preview', settled, len(shared), False),
                                'project': {'id': project, 'name': row['name']}, 'record_counts': counts,
                                'content_categories': ['project_and_asset_names', 'submitted_requests', 'errors',
                                    'revision_manifests', 'event_details', 'execution_and_reconciliation_records',
                                    'unshared_blobs', 'owned_attempt_folders', 'agent_prompts_decisions_and_receipts'],
                                'files': [{'kind': kind, 'path': str(path.relative_to(store.root)), 'bytes': size}
                                          for kind, path, size in paths],
                                'shared_blob_hashes_retained': sorted(shared)}
                    _headroom(store)
                    if receipt is None:
                        db.execute("INSERT INTO project_erasures VALUES(?,'files',?,NULL,?,?)",
                                   (key, time.time(), settled, len(shared)))
                    else:
                        db.execute('UPDATE project_erasures SET shared_blobs=? WHERE key=?', (len(shared), key))
                    db.execute("UPDATE projects SET state='deleting' WHERE id=? AND workspace=?", (project, workspace))
                receipt = db.execute('SELECT * FROM project_erasures WHERE key=?', (key,)).fetchone()
                try:
                    for kind, path, _ in paths:
                        _inspect(path, kind == 'project_attempt')
                        if kind == 'project_attempt':
                            shutil.rmtree(path)
                        else:
                            path.unlink()
                        store._sync_dir(path.parent)
                    with _transaction(db):
                        # Intent fences every normal writer. Recheck ownership
                        # and references anyway; no previously saved plan is used.
                        _plan(store, db, workspace, project)
                        for budget in db.execute('SELECT DISTINCT budget FROM agent_runs WHERE project=?', (project,)).fetchall():
                            charge = db.execute("""SELECT COALESCE(SUM(c.charged_microusd),0)
                                FROM agent_calls c JOIN agent_runs r ON r.id=c.run
                                WHERE r.project=? AND r.budget=?""", (project, budget[0])).fetchone()[0]
                            db.execute('UPDATE agent_budgets SET retired_microusd=retired_microusd+? WHERE id=?', (charge, budget[0]))
                        for table in ('agent_steps', 'agent_calls', 'agent_runs'):
                            db.execute(f'DELETE FROM {table} WHERE {_row_key(table, table)}=?', (key,))
                        for table in ('attempt_reconciliations', 'attempt_executions', 'events',
                                      'retries', 'revisions', 'assets', 'project_events', 'attempts', 'jobs', 'projects'):
                            db.execute(f'DELETE FROM {table} WHERE {_row_key(table, table)}=?', (key,))
                        db.execute("UPDATE project_erasures SET phase='database' WHERE key=?", (key,))
                except (OSError, sqlite3.Error, ValueError):
                    return {**_result(key, 'files', receipt['settled_attempts'], receipt['shared_blobs'], True),
                            'reason': 'managed_file_or_record_cleanup_unfinished', 'retry_same_erasure': True}
            receipt = db.execute('SELECT * FROM project_erasures WHERE key=?', (key,)).fetchone()
            try:
                _headroom(store)
                _checkpoint(db)
                db.execute('VACUUM')
                _checkpoint(db)
                with _transaction(db):
                    db.execute("UPDATE project_erasures SET phase='complete',finished=? WHERE key=?", (time.time(), key))
            except (OSError, sqlite3.Error, ValueError):
                return {**_result(key, 'database', receipt['settled_attempts'], receipt['shared_blobs'], True),
                        'reason': 'database_compaction_or_checkpoint_unfinished', 'retry_same_erasure': True}
            # Old content is already compacted and checkpointed. This final WAL
            # can contain only the minimal completion metadata.
            try:
                final_checkpoint = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
            except sqlite3.Error:
                final_checkpoint = False
            return {**_result(key, 'complete', receipt['settled_attempts'], receipt['shared_blobs'], True),
                    'completion_metadata_checkpointed': final_checkpoint}


def erase_project(store, workspace, project, apply=False):
    try:
        return _erase_project(store, workspace, project, apply)
    except sqlite3.Error as error:
        raise Conflict('database access is busy or unavailable; retry the same erasure after repair') from error
