"""Transactional jobs and immutable, content-addressed project revisions.

This storage layer is shared by the local supervisor and tenant-scoped services.
Callers supply the authorized workspace; it never comes from job parameters.
The directory is private runtime state, not an engine-writable work directory.
"""
from contextlib import contextmanager
from functools import wraps
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import time
import uuid
from . import capacity, job_routing
from .agent_store import SCHEMA as AGENT_SCHEMA, TABLES as AGENT_TABLES


class Conflict(ValueError):
    """The requested state transition would overwrite or repeat different work."""


class NotFound(ValueError):
    """The resource does not exist in the authorized workspace."""


class LeaseLost(Conflict):
    """An expired or superseded worker must not publish results."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identifier(value):
    if not isinstance(value, str) or not value or len(value) > 200 or "\0" in value:
        raise ValueError("invalid identifier")
    return value


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ValueError("invalid artifact path")
    parts = value.split("/")
    if any(p in ("", ".", "..") for p in parts) or PurePosixPath(value).is_absolute():
        raise ValueError("artifact path must be relative, without dot components")
    return value


def validate_source_artifacts(files, engine):
    """Keep native source mandatory except for the explicit raster inference profile."""
    if engine == {'name': 'open-weight-synthesis', 'version': '1.0'}:
        required = {('synthesis/recipe.json', 'recipe'), ('synthesis/exports/photograph.png', 'export')}
        if not required <= {(f['path'], f['role']) for f in files}:
            raise ValueError('synthesis revisions require a generation recipe and raster export')
        if any(f['role'] == 'native' for f in files):
            raise ValueError('synthesis does not claim an editable native scene')
    elif not any(f['role'] == 'native' for f in files) or not any(f['role'] == 'export' for f in files):
        raise ValueError('a revision requires editable native source and an export')


def artifact_write(method):
    """Keep blob creation and its metadata commit indivisible with respect to GC."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        capacity.check(self.root, self.storage_generation)
        with open(self.root / 'artifacts.lock', 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            capacity.check(self.root, self.storage_generation)
            return method(self, *args, **kwargs)
    return locked


SCHEMA = """
CREATE TABLE IF NOT EXISTS project_erasures (
 key TEXT PRIMARY KEY CHECK(length(key)=64),
 phase TEXT NOT NULL CHECK(phase IN ('files','database','complete')),
 started REAL NOT NULL, finished REAL, settled_attempts INTEGER NOT NULL,
 shared_blobs INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, name TEXT NOT NULL,
 head TEXT, created REAL NOT NULL,
 state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','archived','deleting','deleted')),
 files_deleted_at REAL
);
CREATE TABLE IF NOT EXISTS project_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL REFERENCES projects(id),
 kind TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
 workspace TEXT NOT NULL, idempotency_key TEXT NOT NULL, request TEXT NOT NULL,
 operation TEXT NOT NULL, source_revision TEXT, state TEXT NOT NULL,
 cancel_requested INTEGER NOT NULL DEFAULT 0, deadline REAL NOT NULL,
 worker TEXT, token TEXT, lease_until REAL, attempt INTEGER NOT NULL DEFAULT 0,
 result_revision TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL,
 UNIQUE(project, idempotency_key)
);
CREATE INDEX IF NOT EXISTS job_queue ON jobs(workspace, state, created);
CREATE TABLE IF NOT EXISTS attempts (
 job TEXT NOT NULL REFERENCES jobs(id), number INTEGER NOT NULL, token TEXT NOT NULL UNIQUE,
 worker TEXT NOT NULL, state TEXT NOT NULL, started REAL NOT NULL, finished REAL, error TEXT,
 PRIMARY KEY(job, number)
);
CREATE TABLE IF NOT EXISTS attempt_executions (
 token TEXT PRIMARY KEY REFERENCES attempts(token), machine TEXT NOT NULL, boot TEXT NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('prepared','registered','legacy')),
 process_group INTEGER, prepared REAL NOT NULL, registered REAL,
 CHECK((phase IN ('prepared','legacy') AND process_group IS NULL AND registered IS NULL) OR
       (phase='registered' AND process_group>1 AND registered IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS attempt_reconciliations (
 token TEXT PRIMARY KEY REFERENCES attempts(token), previous_state TEXT NOT NULL,
 previous_error TEXT, previous_finished REAL, evidence TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
 id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id), workspace TEXT NOT NULL,
 parent TEXT, job TEXT NOT NULL UNIQUE REFERENCES jobs(id), manifest TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id), workspace TEXT NOT NULL,
 name TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS retries (
 job TEXT NOT NULL REFERENCES jobs(id), idempotency_key TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(job, idempotency_key)
);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL REFERENCES jobs(id),
 kind TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL
);
"""
SCHEMA += AGENT_SCHEMA
SCHEMA_VERSION = 7


def project_erasure_key(workspace, project):
    return hashlib.sha256(('studio-local-erasure:' + canonical([workspace, project])).encode()).hexdigest()



class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().absolute()
        self.storage_generation = capacity.check(self.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError("runtime state root must not be a symlink")
        os.chmod(self.root, 0o700)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(exist_ok=True, mode=0o700)
        self.staging = self.root / "staging"
        self.staging.mkdir(exist_ok=True, mode=0o700)
        self.db = self.root / "studio.sqlite3"
        migration_lock = None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2, 3, 4, 5, 6, 7):
                    raise ValueError(f"unsupported runtime schema version {version}")
                if version < SCHEMA_VERSION:
                    migration_lock = open(self.root / 'worker.lock', 'a+')
                    try:
                        fcntl.flock(migration_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise Conflict('stop the local worker before upgrading the runtime schema')
                if version < SCHEMA_VERSION:
                    for statement in SCHEMA.split(';'):
                        if statement.strip():
                            db.execute(statement)
                    # Both older schema-6 branches migrate here without losing data.
                    if 'retired_microusd' not in {row[1] for row in db.execute('PRAGMA table_info(agent_budgets)')}:
                        db.execute('ALTER TABLE agent_budgets ADD COLUMN retired_microusd INTEGER NOT NULL DEFAULT 0 CHECK(retired_microusd>=0)')
                    columns = {row[1] for row in db.execute('PRAGMA table_info(projects)')}
                    if 'state' not in columns:
                        db.execute("ALTER TABLE projects ADD state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','archived','deleting','deleted'))")
                        db.execute('ALTER TABLE projects ADD files_deleted_at REAL')
                    # Old, already-open MCP processes must not write after storage
                    # migration. They lack this connection-local guard function.
                    for table in ('projects', 'project_events', 'jobs', 'attempts', 'revisions', 'assets', 'retries', 'events', 'attempt_executions', 'attempt_reconciliations', 'project_erasures') + AGENT_TABLES:
                        for action in ('INSERT', 'UPDATE', 'DELETE'):
                            db.execute(f'DROP TRIGGER IF EXISTS writer_guard_{table}_{action.lower()}')
                            db.execute(f'''CREATE TRIGGER writer_guard_{table}_{action.lower()}
                                BEFORE {action} ON {table} BEGIN
                                SELECT CASE WHEN studio_writer_version()!=7 THEN RAISE(ABORT,'unsupported runtime writer') END;
                                SELECT CASE WHEN studio_erasure_authority()='' AND EXISTS(
                                  SELECT 1 FROM project_erasures WHERE phase!='complete')
                                  THEN RAISE(ABORT,'local project erasure cleanup is pending') END;
                                END''')
                    from .erasure import install_guards
                    install_guards(db)
                    db.execute("""CREATE TRIGGER IF NOT EXISTS execution_registration_only BEFORE UPDATE ON attempt_executions
                        WHEN OLD.phase!='prepared' OR NEW.phase!='registered' OR NEW.token!=OLD.token
                        OR NEW.machine!=OLD.machine OR NEW.boot!=OLD.boot OR NEW.prepared!=OLD.prepared
                        OR NEW.process_group IS NULL OR NEW.process_group<=1 OR NEW.registered IS NULL
                        BEGIN SELECT RAISE(ABORT,'execution identity is immutable after registration'); END""")
                    db.execute("PRAGMA user_version = 7")
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                if migration_lock:
                    migration_lock.close()
        os.chmod(self.db, 0o600)

    @contextmanager
    def connect(self):
        with self._connect() as db:
            yield db

    @contextmanager
    def _connect(self, erasure_key=''):
        # Only the explicit erasure service uses a scoped key. Normal public
        # store operations always use connect(), which has no erasure authority.
        capacity.check(self.root, self.storage_generation)
        db = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        def writer_version():
            capacity.check(self.root, self.storage_generation)
            return SCHEMA_VERSION
        db.create_function('studio_writer_version', 0, writer_version)
        db.create_function('studio_erasure_authority', 0, lambda: erasure_key)
        db.create_function('studio_project_erasure_key', 2, project_erasure_key, deterministic=True)
        try:
            if self.storage_generation is not None:
                space = os.statvfs(self.root)
                if space.f_bavail * space.f_frsize < capacity.RESERVE_BYTES // 2:
                    # At ENOSPC, recreating SQLite's shared-memory WAL index can
                    # fail even for inspection. Exclusive locking uses an
                    # in-memory index while still reading committed WAL frames.
                    # It does not release recovery space or bypass SQLite locks;
                    # an existing reader must close before this access proceeds.
                    db.execute('PRAGMA locking_mode = EXCLUSIVE')
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = FULL")
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _project(self, db, workspace, project, write=False, files=False):
        row = db.execute("SELECT * FROM projects WHERE id=? AND workspace=?", (project, workspace)).fetchone()
        if row is None:
            raise NotFound("project not found")
        if write and row['state'] != 'active':
            raise Conflict('project is not active')
        if files and row['state'] in ('deleting', 'deleted'):
            raise Conflict('project files are unavailable')
        return row

    def _job(self, db, workspace, job):
        row = db.execute("SELECT * FROM jobs WHERE id=? AND workspace=?", (job, workspace)).fetchone()
        if row is None:
            raise NotFound("job not found")
        return row

    def _lease(self, db, workspace, job, token):
        row = self._job(db, workspace, job)
        if (not token or row["token"] != token or row["state"] not in ("running", "validating")
                or row["lease_until"] <= time.time()):
            raise LeaseLost("worker lease is expired or no longer owns the job")
        return row

    def _event(self, db, job, kind, detail=None):
        db.execute("INSERT INTO events(job,kind,detail,created) VALUES(?,?,?,?)",
                   (job, kind, canonical(detail or {}), time.time()))

    def create_project(self, workspace, name):
        capacity.admit(self.root, self.storage_generation)
        identifier(workspace); identifier(name)
        project = uuid.uuid4().hex
        with self.transaction() as db:
            db.execute("INSERT INTO projects(id,workspace,name,created) VALUES(?,?,?,?)",
                       (project, workspace, name, time.time()))
        return self.get_project(workspace, project)

    def get_project(self, workspace, project):
        with self.connect() as db:
            return dict(self._project(db, workspace, project))

    def has_job_key(self, workspace, project, idempotency_key):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM jobs WHERE workspace=? AND project=? AND idempotency_key=?",
                              (workspace, project, idempotency_key)).fetchone() is not None

    def projects(self, workspace, after=None):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM projects WHERE workspace=? AND (? IS NULL OR id>?) ORDER BY id LIMIT 100',
                              (workspace, after, after)).fetchall()
            return {'projects': [dict(row) for row in rows], 'next_project': rows[-1]['id'] if len(rows) == 100 else None}

    def submit(self, workspace, project, operation, parameters, idempotency_key,
               source_revision=None, timeout_seconds=600, *, admission=None, usage_workflow=None):
        identifier(operation); identifier(idempotency_key)
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object")
        if type(timeout_seconds) not in (int, float) or not 1 <= timeout_seconds <= 86400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        request_data = {"operation": operation, "parameters": parameters,
                        "source_revision": source_revision, "timeout_seconds": timeout_seconds}
        if usage_workflow is not None: request_data['usage_workflow'] = usage_workflow
        request = canonical(request_data)
        now = time.time(); job = uuid.uuid4().hex
        with self.transaction() as db:
            # Internal callers may fence their durable coordinator state in the
            # same transaction as job admission. Public CLI/MCP behavior is unchanged.
            if admission is not None: admission(db)
            self._project(db, workspace, project, write=True)
            if usage_workflow is not None:
                from .usage import workflow
                workflow(db, project, usage_workflow)
            old = db.execute("SELECT * FROM jobs WHERE project=? AND idempotency_key=?",
                             (project, idempotency_key)).fetchone()
            if old:
                if old["request"] != request:
                    raise Conflict("idempotency key already identifies a different request")
                return self._decode_job(old)
            capacity.admit(self.root, self.storage_generation)
            if source_revision is not None:
                if not db.execute("SELECT 1 FROM revisions WHERE id=? AND project=? AND workspace=?",
                                  (source_revision, project, workspace)).fetchone():
                    raise NotFound("source revision not found in project")
            db.execute("""INSERT INTO jobs(id,project,workspace,idempotency_key,request,operation,
                          source_revision,state,deadline,created,updated) VALUES(?,?,?,?,?,?,?,'queued',?,?,?)""",
                       (job, project, workspace, idempotency_key, request, job_routing.dispatch_key(operation), source_revision,
                        now + timeout_seconds, now, now))
            self._event(db, job, "queued")
        return self.get_job(workspace, job)

    @staticmethod
    def _decode_job(row):
        out = dict(row); out["request"] = json.loads(out["request"])
        # The persisted column is a worker dispatch key. Public clients and
        # reconciliation use the immutable request's original operation name.
        out["operation"] = out["request"].get("operation", out["operation"])
        out["cancel_requested"] = bool(out["cancel_requested"])
        if out["error"]:
            out["error"] = json.loads(out["error"])
        # Fencing tokens are only returned to workers by claim, never to clients.
        out.pop("token", None)
        return out

    def get_job(self, workspace, job):
        with self.connect() as db:
            return self._decode_job(self._job(db, workspace, job))

    def events(self, workspace, job, after=0):
        with self.connect() as db:
            self._job(db, workspace, job)
            return [{**dict(r), "detail": json.loads(r["detail"])} for r in db.execute(
                "SELECT * FROM events WHERE job=? AND seq>? ORDER BY seq LIMIT 200", (job, after))]

    def _terminal(self, db, row, state, error=None):
        now = time.time(); encoded = canonical(error) if error else None
        db.execute("UPDATE jobs SET state=?,error=?,token=NULL,lease_until=NULL,updated=? WHERE id=?",
                   (state, encoded, now, row["id"]))
        # A queued retry retains the previous attempt number until it is
        # claimed. Cancelling or expiring that queue entry must not settle the
        # previous execution, whose termination can still be unknown.
        db.execute("UPDATE attempts SET state=?,error=?,finished=? WHERE token=?",
                   (state, encoded, now, row["token"]))
        self._event(db, row["id"], state, error)

    def _recover(self, db, workspace):
        now = time.time()
        rows = db.execute("""SELECT * FROM jobs WHERE workspace=? AND
            ((state IN ('running','validating') AND lease_until<=?) OR
             (state='queued' AND deadline<=?))""", (workspace, now, now)).fetchall()
        for row in rows:
            if row["state"] == "queued":
                self._terminal(db, row, "failed", {"code": "deadline_exceeded", "message": "Job expired before execution"})
            else:
                # The process may still exist. Fence its output and require explicit reconciliation.
                self._terminal(db, row, "interrupted", {"code": "lease_expired", "message": "Worker result is uncertain; not automatically retried"})
        return len(rows)

    def recover(self, workspace):
        with self.transaction() as db:
            return self._recover(db, workspace)

    def claim(self, workspace, worker, operations, lease_seconds=30, max_running=1):
        identifier(worker)
        if not operations or any(not isinstance(o, str) or not o for o in operations):
            raise ValueError("worker must declare supported operations")
        if not 1 <= lease_seconds <= 300 or type(max_running) is not int or max_running < 1:
            raise ValueError("invalid worker limits")
        operations = job_routing.supported_operations(operations)
        with self.transaction() as db:
            self._recover(db, workspace)
            active = db.execute("SELECT count(*) FROM jobs WHERE workspace=? AND state IN ('running','validating')",
                                (workspace,)).fetchone()[0]
            if active >= max_running:
                return None
            placeholders = ','.join('?' for _ in operations)
            row = db.execute(f"SELECT * FROM jobs WHERE workspace=? AND state='queued' AND operation IN ({placeholders}) ORDER BY created,id LIMIT 1",
                             (workspace, *operations)).fetchone()
            if row is None:
                return None
            try:
                capacity.admit(self.root, self.storage_generation)
            except capacity.CapacityError:
                return None
            token = uuid.uuid4().hex; now = time.time(); attempt = row["attempt"] + 1
            db.execute("""UPDATE jobs SET state='running',worker=?,token=?,lease_until=?,attempt=?,updated=?
                          WHERE id=?""", (worker, token, now + lease_seconds, attempt, now, row["id"]))
            db.execute("INSERT INTO attempts(job,number,token,worker,state,started) VALUES(?,?,?,?,'running',?)",
                       (row["id"], attempt, token, worker, now))
            from .execution import prepare
            prepare(db, token)
            self._event(db, row["id"], "running", {"attempt": attempt})
            out = self._decode_job(self._job(db, workspace, row["id"]))
            out["token"] = token
            return out

    def heartbeat(self, workspace, job, token, lease_seconds=30):
        if not 1 <= lease_seconds <= 300:
            raise ValueError("invalid lease duration")
        with self.transaction() as db:
            row = self._lease(db, workspace, job, token)
            now = time.time()
            db.execute("UPDATE jobs SET lease_until=?,updated=? WHERE id=?", (now + lease_seconds, now, job))
            return {"cancel_requested": bool(row["cancel_requested"]), "deadline_exceeded": now >= row["deadline"]}

    def cancel(self, workspace, job):
        with self.transaction() as db:
            row = self._job(db, workspace, job)
            if row["state"] == "queued":
                db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job,))
                self._terminal(db, row, "cancelled")
            elif row["state"] in ("running", "validating", "interrupted") and not row["cancel_requested"]:
                db.execute("UPDATE jobs SET cancel_requested=1,updated=? WHERE id=?", (time.time(), job))
                self._event(db, job, "cancellation_requested")
        return self.get_job(workspace, job)

    def fail(self, workspace, job, token, code, message, cancelled=False):
        with self.transaction() as db:
            row = self._lease(db, workspace, job, token)
            self._terminal(db, row, "cancelled" if cancelled else "failed", {"code": code, "message": message})
        return self.get_job(workspace, job)

    def interrupt(self, workspace, job, token, message):
        with self.transaction() as db:
            row = self._lease(db, workspace, job, token)
            self._terminal(db, row, 'interrupted', {'code': 'execution_uncertain', 'message': message})
        return self.get_job(workspace, job)

    def validating(self, workspace, job, token):
        with self.transaction() as db:
            row = self._lease(db, workspace, job, token)
            if row["cancel_requested"] or row["deadline"] <= time.time():
                raise Conflict("job cancelled or deadline exceeded")
            db.execute("UPDATE jobs SET state='validating',updated=? WHERE id=?", (time.time(), job))
            db.execute("UPDATE attempts SET state='validating' WHERE job=? AND number=?", (job, row["attempt"]))
            self._event(db, job, "validating")

    def _blob(self, source):
        temporary = self.staging / uuid.uuid4().hex
        digest = hashlib.sha256(); size = 0
        try:
            source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(source_fd, "rb") as src, open(temporary, "xb") as dst:
                info = os.fstat(src.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > (1 << 30):
                    raise ValueError("artifact must be a regular file of at most 1 GiB")
                while chunk := src.read(1 << 20):
                    size += len(chunk)
                    if size > (1 << 30):
                        raise ValueError("artifact exceeds 1 GiB")
                    dst.write(chunk); digest.update(chunk)
                dst.flush(); os.fsync(dst.fileno())
            sha = digest.hexdigest(); target = self.blobs / sha
            try:
                os.link(temporary, target)
                os.chmod(target, 0o400)
            except FileExistsError:
                if self._hash(target) != sha:
                    raise Conflict("existing content-addressed artifact is corrupt")
            self._sync_dir(self.blobs)
            return {"sha256": sha, "bytes": size}
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _hash(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _sync_dir(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @artifact_write
    def publish(self, workspace, job, token, output_root, artifacts, engine, validation):
        # Validate files outside the DB transaction, then recheck ownership before committing.
        with self.connect() as db:
            current = self._job(db, workspace, job)
            if current["state"] == "succeeded":
                return self.get_revision(workspace, current["result_revision"])
            self._lease(db, workspace, job, token)
        if not isinstance(engine, dict) or not engine.get("name") or not engine.get("version"):
            raise ValueError("engine name and version are required")
        if not isinstance(validation, dict) or validation.get("passed") is not True:
            raise ValueError("passing output validation is required")
        root = Path(output_root).resolve(); files = []; paths = set()
        for entry in artifacts:
            path = relative_path(entry["path"])
            if path.split("/")[0] == "project.json":
                raise ValueError("project.json is reserved for the bundle manifest")
            if any(path.startswith(other + "/") or other.startswith(path + "/") for other in paths):
                raise ValueError("artifact file and directory paths overlap")
            if path in paths:
                raise ValueError("duplicate artifact path")
            paths.add(path)
            source = root / path
            if any((root.joinpath(*PurePosixPath(path).parts[:i])).is_symlink()
                   for i in range(1, len(PurePosixPath(path).parts) + 1)):
                raise ValueError("artifact symlinks are not allowed")
            if not source.is_file() or not source.resolve().is_relative_to(root):
                raise ValueError("artifact is missing or outside the output root")
            role = entry.get("role")
            if role not in ("native", "asset", "export", "preview", "recipe"):
                raise ValueError("invalid artifact role")
            files.append({"path": path, "role": role, **self._blob(source)})
        validate_source_artifacts(files, engine)
        revision = uuid.uuid4().hex; now = time.time()
        with self.transaction() as db:
            row = self._lease(db, workspace, job, token)
            if row["state"] != "validating" or row["cancel_requested"] or row["deadline"] <= now:
                raise Conflict("job is not eligible to publish")
            project = self._project(db, workspace, row["project"], write=True)
            if project["head"] != row["source_revision"]:
                raise Conflict("project head changed; revise from the latest explicit source")
            manifest = {"schema_version": 1, "id": revision, "project": row["project"],
                        "parent": row["source_revision"], "job": job, "engine": engine,
                        "operation": json.loads(row["request"]), "files": sorted(files, key=lambda f: f["path"]),
                        "validation": validation, "created": now}
            db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?)",
                       (revision, row["project"], workspace, row["source_revision"], job, canonical(manifest), now))
            db.execute("UPDATE projects SET head=? WHERE id=?", (revision, row["project"]))
            db.execute("UPDATE jobs SET result_revision=? WHERE id=?", (revision, job))
            self._terminal(db, row, "succeeded")
        return manifest

    def get_revision(self, workspace, revision):
        with self.connect() as db:
            row = db.execute("SELECT manifest FROM revisions WHERE id=? AND workspace=?", (revision, workspace)).fetchone()
            if row is None:
                raise NotFound("revision not found")
            return json.loads(row[0])

    @artifact_write
    def checkout(self, workspace, revision, destination):
        manifest = self.get_revision(workspace, revision)
        with self.connect() as db:
            self._project(db, workspace, manifest['project'], files=True)
        destination = Path(destination).absolute()
        # Fresh destination only. Copy bytes, never hard-link engine files to immutable blobs.
        destination.mkdir(parents=True, exist_ok=False, mode=0o700)
        try:
            for entry in manifest["files"]:
                source = self.blobs / entry["sha256"]
                if self._hash(source) != entry["sha256"]:
                    raise Conflict("stored artifact hash mismatch")
                path = destination / relative_path(entry["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(source, "rb") as src, open(path, "xb") as dst:
                    shutil.copyfileobj(src, dst)
            (destination / "project.json").write_text(canonical(manifest) + "\n")
        except BaseException:
            shutil.rmtree(destination)
            raise
        return manifest

    def retry(self, workspace, job, idempotency_key, safe_operations):
        identifier(idempotency_key)
        with self.transaction() as db:
            row = self._job(db, workspace, job)
            if db.execute("SELECT 1 FROM retries WHERE job=? AND idempotency_key=?", (job, idempotency_key)).fetchone():
                return self._decode_job(row)
            if row["operation"] not in job_routing.supported_operations(safe_operations):
                raise Conflict("this operation requires external reconciliation before retry")
            if row["state"] not in ("failed", "cancelled", "interrupted"):
                raise Conflict("only failed, cancelled or interrupted jobs can be retried")
            if row["attempt"] >= 3:
                raise Conflict("job attempt limit reached; create a new explicit submission")
            project = self._project(db, workspace, row["project"], write=True)
            if project["head"] != row["source_revision"]:
                raise Conflict("project changed; submit a revision from its current head")
            capacity.admit(self.root, self.storage_generation)
            now = time.time()
            timeout = json.loads(row["request"])["timeout_seconds"]
            db.execute("INSERT INTO retries VALUES(?,?,?)", (job, idempotency_key, now))
            db.execute("""UPDATE jobs SET state='queued',cancel_requested=0,worker=NULL,token=NULL,
                          lease_until=NULL,error=NULL,deadline=?,updated=? WHERE id=?""", (now + timeout, now, job))
            self._event(db, job, "retry_requested", {"previous_attempt": row["attempt"]})
        return self.get_job(workspace, job)

    @artifact_write
    def import_asset(self, workspace, project, source, name=None):
        capacity.admit(self.root, self.storage_generation)
        with self.connect() as db:
            self._project(db, workspace, project, write=True)
        source = Path(source)
        name = identifier(name or source.name)
        if "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError("asset name must be a filename")
        blob = self._blob(source)
        asset = uuid.uuid4().hex
        with self.transaction() as db:
            self._project(db, workspace, project, write=True)
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?)", (asset, project, workspace, name, blob["sha256"], blob["bytes"], time.time()))
        return self.get_asset(workspace, project, asset)

    def get_asset(self, workspace, project, asset):
        with self.connect() as db:
            self._project(db, workspace, project, files=True)
            row = db.execute("SELECT * FROM assets WHERE id=? AND workspace=? AND project=?", (asset, workspace, project)).fetchone()
            if row is None:
                raise NotFound("asset not found in project")
            return dict(row)

    @artifact_write
    def materialize_asset(self, workspace, project, asset, destination, *, allow_existing=False):
        row = self.get_asset(workspace, project, asset)
        source = self.blobs / row["sha256"]
        if self._hash(source) != row["sha256"]:
            raise Conflict("asset hash mismatch")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            target = open(destination, "xb")
        except FileExistsError:
            if not allow_existing:
                raise
            # A Video replacement may reuse media already in its immutable
            # source revision. Authorization still comes from this project's
            # asset record; a retained filename or receipt never grants access.
            descriptor = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != row['bytes']:
                    raise Conflict("retained asset is not a matching regular file")
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
                if (digest.hexdigest() != row['sha256']
                        or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                    raise Conflict("retained asset differs from the authorized imported asset")
            return row
        with target as dst, open(source, "rb") as src:
            shutil.copyfileobj(src, dst)
        return row

    @artifact_write
    def import_project(self, workspace, bundle, name):
        capacity.admit(self.root, self.storage_generation)
        identifier(workspace); identifier(name)
        root = Path(bundle).absolute()
        if root.is_symlink():
            raise ValueError("bundle root must not be a symlink")
        root = root.resolve()
        manifest_path = root / "project.json"
        fd = os.open(manifest_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > (1 << 20):
                raise ValueError("bundle manifest is unsafe or too large")
            data = stream.read((1 << 20) + 1)
        if len(data) > (1 << 20):
            raise ValueError("bundle manifest exceeds 1 MiB")
        manifest = json.loads(data)
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("unsupported project bundle schema")
        files = manifest.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 1000:
            raise ValueError("bundle must contain 1 to 1000 declared files")
        checked = []; paths = set(); total = 0
        for entry in files:
            path = relative_path(entry["path"])
            if path.split("/")[0] == "project.json" or path in paths:
                raise ValueError("duplicate or reserved bundle path")
            if any(path.startswith(p + "/") or p.startswith(path + "/") for p in paths):
                raise ValueError("overlapping bundle file paths")
            paths.add(path)
            if entry.get("role") not in ("native", "asset", "export", "preview", "recipe"):
                raise ValueError("invalid artifact role")
            if type(entry.get("bytes")) is not int or not 0 <= entry["bytes"] <= (1 << 30):
                raise ValueError("invalid artifact size")
            total += entry["bytes"]
            if total > (4 << 30):
                raise ValueError("bundle exceeds 4 GiB")
            source = root / path
            if any(root.joinpath(*PurePosixPath(path).parts[:i]).is_symlink() for i in range(1, len(PurePosixPath(path).parts) + 1)):
                raise ValueError("bundle symlinks are not allowed")
            blob = self._blob(source)
            if blob["sha256"] != entry.get("sha256") or blob["bytes"] != entry["bytes"]:
                raise ValueError("bundle artifact hash or size mismatch")
            checked.append({"path": path, "role": entry["role"], **blob})
        engine = manifest.get("engine")
        if not isinstance(engine, dict) or not isinstance(engine.get("name"), str) or not isinstance(engine.get("version"), str):
            raise ValueError("bundle requires an engine identity")
        validate_source_artifacts(checked, engine)
        project = uuid.uuid4().hex; job = uuid.uuid4().hex; revision = uuid.uuid4().hex; now = time.time()
        imported = {"schema_version": 1, "id": revision, "project": project, "parent": None, "job": job,
                    "engine": engine, "files": checked, "created": now,
                    "operation": {"operation": "project.import"},
                    "validation": {"passed": True, "scope": "bundle_integrity", "native_cold_reopen": False},
                    "provenance": {"imported_revision": manifest.get("id"), "original_project": manifest.get("project")}}
        with self.transaction() as db:
            db.execute("INSERT INTO projects(id,workspace,name,head,created) VALUES(?,?,?,?,?)", (project, workspace, name, revision, now))
            db.execute("""INSERT INTO jobs(id,project,workspace,idempotency_key,request,operation,state,deadline,
                          result_revision,created,updated) VALUES(?,?,?,?,?,'project.import','succeeded',?,?,?,?)""",
                       (job, project, workspace, "import", canonical({"operation": "project.import"}), now, revision, now, now))
            db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?)", (revision, project, workspace, None, job, canonical(imported), now))
            self._event(db, job, "imported", {"scope": "bundle_integrity"})
        return {"project": self.get_project(workspace, project), "revision": imported}
