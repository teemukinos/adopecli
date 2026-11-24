"""Qualify explicit local erasure using disposable synthetic state only.

No native engines, owner projects, services or network are used. Optional CLI
prefix selects the exact installed executable; direct fault injection is marked
as synthetic and never represents an observed device failure.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--old-store', type=Path, required=True)
    parser.add_argument('--cli-json')
    args = parser.parse_args()
    sys.path.insert(0, str(args.runtime.resolve(strict=True)))
    from studio_runtime.store import Store, Conflict, NotFound, canonical, project_erasure_key
    from studio_runtime import erasure, execution
    out = args.output.absolute(); out.mkdir(parents=True, exist_ok=False)
    cases = []; commands = []
    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + '\n')
    def check(value, label):
        if not value:
            raise AssertionError(label)
        cases.append(label); save('cases.json', cases)
    def refuses(action, label):
        try:
            action()
        except (ValueError, OSError, sqlite3.Error):
            check(True, label); return
        raise AssertionError('unexpected acceptance: ' + label)
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def inventory(path):
        return {p.relative_to(path).as_posix(): digest(p) for p in path.rglob('*') if p.is_file()}
    env = dict(os.environ); env['PYTHONPATH'] = str(args.runtime); env['PYTHONDONTWRITEBYTECODE'] = '1'
    cli_prefix = json.loads(args.cli_json) if args.cli_json else [sys.executable, '-B', '-m', 'studio_runtime']
    def cli(store, *arguments, success=True):
        command = [*cli_prefix, '--state', str(store.root), *map(str, arguments)]
        p = subprocess.run(command, env=env, input='', capture_output=True, text=True, timeout=45)
        commands.append({'command': command, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        save('commands.json', commands)
        check((p.returncode == 0) == success, 'CLI ' + ' '.join(map(str, arguments[:1])) + (' succeeds' if success else ' refuses'))
        return json.loads(p.stdout) if p.stdout else None
    def mcp(store, tool, arguments):
        prefix = 'dobe' if args.cli_json else 'studio'
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                   'params': {'name': prefix + '_' + tool, 'arguments': arguments}}
        p = subprocess.run([*cli_prefix, '--state', str(store.root), 'mcp'], env=env,
                           input=json.dumps(request) + '\n', capture_output=True, text=True, timeout=45)
        check(p.returncode == 0, 'MCP process completes for ' + tool)
        result = json.loads(p.stdout)['result']
        return result if result.get('isError') else json.loads(result['content'][0]['text'])
    def snapshot(store, project):
        key = project_erasure_key('local', project)
        with store.connect() as db:
            return {table: [dict(row) for row in db.execute(
                f'SELECT * FROM {table} WHERE {erasure._row_key(table, table)}=?', (key,))] for table in erasure.TABLES}
    def fixture(name, marker):
        folder = out / name; folder.mkdir()
        bundle = folder / 'original-import'; bundle.mkdir()
        (bundle / 'source.native').write_text(marker + ' native source\n')
        (bundle / 'image.export').write_text(marker + ' exported output\n')
        files = [{'path': p.name, 'role': role, 'bytes': p.stat().st_size, 'sha256': digest(p)}
                 for p, role in [(bundle / 'source.native', 'native'), (bundle / 'image.export', 'export')]]
        (bundle / 'project.json').write_text(canonical({'schema_version': 1, 'id': marker + '-revision',
            'project': marker + '-original', 'engine': {'name': 'synthetic', 'version': '1'}, 'files': files}))
        store = Store(folder / 'state')
        imported = store.import_project('local', bundle, marker + ' project name')
        project = imported['project']['id']; revision = imported['revision']['id']
        unique = folder / (marker + '-asset'); unique.write_text(marker + ' unique asset')
        store.import_asset('local', project, unique)
        shared = folder / 'shared-input'; shared.write_text('separately shared synthetic bytes')
        store.import_asset('local', project, shared)
        other = store.create_project('local', 'untouched other project')['id']
        store.import_asset('local', other, shared)
        job = store.submit('local', project, 'vector.create', {'fixture_text': marker}, marker + '-key')
        claim = store.claim('local', 'synthetic worker', ['vector.create'])
        assert claim['id'] == job['id']; token = claim['token']
        store.fail('local', job['id'], token, 'synthetic_failure', marker + ' previous error')
        with store.transaction() as db:
            db.execute('INSERT INTO retries VALUES(?,?,?)', (job['id'], marker + '-retry', time.time()))
            db.execute('INSERT INTO project_events(project,kind,detail,created) VALUES(?,?,?,?)',
                       (project, 'synthetic', canonical({'text': marker}), time.time()))
            db.execute('INSERT INTO attempt_reconciliations VALUES(?,?,?,?,?,?)',
                       (token, 'interrupted', canonical({'message': marker}), time.time(), canonical({'synthetic': marker}), time.time()))
        attempt = store.root / 'attempts' / token; attempt.mkdir(parents=True)
        (attempt / 'request.json').write_text(canonical({'submitted_text': marker}))
        (attempt / 'engine.log').write_text(marker + ' prior engine output')
        export = folder / 'external-export'; store.checkout('local', revision, export)
        return {'store': store, 'project': project, 'other': other, 'revision': revision, 'job': job['id'],
                'token': token, 'bundle': bundle, 'export': export, 'shared': shared, 'unique': unique, 'marker': marker}

    # Exact previous Store source supplies the schema-5 connection, rather than
    # a hand-created imitation of its writer fence.
    spec = importlib.util.spec_from_file_location('studio_runtime.erasure_legacy_store', args.old_store)
    legacy = importlib.util.module_from_spec(spec); spec.loader.exec_module(legacy)
    old_store = legacy.Store(out / 'migration-state')
    before = old_store.create_project('local', 'migration preserved project')
    with old_store.connect() as old_connection:
        migrated = Store(old_store.root)
        check(migrated.get_project('local', before['id']) == before, 'schema-5 project survives migration byte-for-byte logically')
        refuses(lambda: old_connection.execute("UPDATE projects SET name='old writer' WHERE id=?", (before['id'],)), 'already-open schema-5 writer is fenced')
    refuses(lambda: old_store.create_project('local', 'stale writer'), 'stale Store object remains fenced on a new connection')
    check(Store(old_store.root).create_project('local', 'schema 6 writer')['name'] == 'schema 6 writer', 'schema-6 normal writes remain usable')

    locked_legacy = legacy.Store(out / 'migration-locked-state')
    with (locked_legacy.root / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        refuses(lambda: Store(locked_legacy.root), 'migration refuses while the legacy worker lock is held')
    with locked_legacy.connect() as db:
        check(db.execute('PRAGMA user_version').fetchone()[0] == 5, 'refused migration preserves schema 5')

    f = fixture('main', 'erase-secret-main-7de32815'); store = f['store']; project = f['project']
    original_other = snapshot(store, f['other']); external = {'bundle': inventory(f['bundle']), 'export': inventory(f['export'])}
    before = snapshot(store, project)
    preview = cli(store, 'erase-project', project)
    check(preview['phase'] == 'preview' and not preview['applied'] and all(preview['record_counts'][t] for t in erasure.TABLES), 'preview inventories all ten content-bearing tables')
    check(snapshot(store, project) == before, 'preview leaves selected logical rows unchanged')
    check(preview['shared_blobs_retained'] == 1 and f['marker'] not in json.dumps(preview['shared_blob_hashes_retained']), 'preview reports retained shared hashes without other project content')
    check(mcp(store, 'erase_project', {'project': project})['phase'] == 'preview', 'MCP exposes the same explicit preview')
    with store.connect() as db:
        refuses(lambda: db.execute('DELETE FROM attempt_reconciliations WHERE token=?', (f['token'],)), 'normal connection cannot delete reconciliation evidence')
        refuses(lambda: db.execute('DELETE FROM attempt_executions WHERE token=?', (f['token'],)), 'normal connection cannot delete execution identity')
        refuses(lambda: db.execute("INSERT INTO project_erasures VALUES(?,'files',1,NULL,0,0)", ('0'*64,)), 'normal connection cannot create erasure authority')
    for label, path, create in [
        ('unknown managed file', store.root / 'unknown.txt', lambda p: p.write_text('unknown')),
        ('unassigned staging', store.staging / ('a'*32), lambda p: p.write_text('unknown')),
        ('unknown attempt', store.root / 'attempts' / ('b'*32), lambda p: p.mkdir()),
        ('unassigned blob', store.blobs / ('c'*64), lambda p: p.write_text('unknown')),
        ('symlink attempt content', store.root / 'attempts' / f['token'] / 'link', lambda p: p.symlink_to(f['unique']))]:
        create(path)
        refuses(lambda: erasure.erase_project(store, 'local', project, True), label + ' refuses erasure')
        if path.is_dir() and not path.is_symlink(): path.rmdir()
        else: path.unlink()
    unique_blob = store.blobs / digest(f['unique']); hardlink = out / 'outside-hardlink'; os.link(unique_blob, hardlink)
    refuses(lambda: erasure.erase_project(store, 'local', project, True), 'hard-linked managed data refuses erasure')
    hardlink.unlink()
    with (store.root / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        refuses(lambda: erasure.erase_project(store, 'local', project, True), 'live worker lock refuses erasure')
    with patch.object(erasure, '_headroom', side_effect=Conflict('synthetic space exhaustion')):
        refuses(lambda: erasure.erase_project(store, 'local', project, True), 'low initial space refuses before durable intent')
    check(snapshot(store, project) == before, 'all preflight refusals preserve selected rows')

    reader = sqlite3.connect(store.db, isolation_level=None)
    reader.execute('BEGIN'); reader.execute('SELECT request FROM jobs').fetchall()
    result = cli(store, 'erase-project', project, '--apply')
    check(result['phase'] == 'database' and not result['complete'] and result['retry_same_erasure'], 'real open reader leaves database cleanup pending')
    check(f['marker'] not in json.dumps(result), 'unfinished result contains no erased content')
    cli(store, 'create-project', 'concurrent writer refused', success=False)
    check(snapshot(store, f['other']) == original_other, 'other project logical rows survive pending cleanup unchanged')
    reader.rollback(); reader.close()
    result = mcp(store, 'erase_project', {'project': project, 'apply': True})
    check(result['complete'] and result['phase'] == 'complete', 'MCP resumes pending database cleanup successfully')
    check(f['marker'] not in json.dumps(result), 'completion contains no erased content')
    check(not any(f['marker'].encode() in p.read_bytes() for p in store.root.rglob('*') if p.is_file()), 'managed active store and WAL contain no selected fixture secret after cleanup')
    check(snapshot(store, f['other']) == original_other, 'other project logical rows survive final cleanup unchanged')
    check((store.blobs / digest(f['shared'])).read_bytes() == f['shared'].read_bytes(), 'shared blob bytes remain identical')
    check(inventory(f['bundle']) == external['bundle'] and inventory(f['export']) == external['export'], 'original imports and external exports retain identical bytes')
    for arguments in [('project', project), ('job', f['job']), ('events', f['job']), ('retry', f['job'], '--key', 'old-key'), ('revision', f['revision']), ('checkout', f['revision'], out / 'must-not-export')]:
        cli(store, *arguments, success=False)
    refuses(lambda: store.submit('local', project, 'vector.create', {}, 'old-key'), 'stale project submission cannot resurrect erased work')
    with store.connect() as db:
        refuses(lambda: db.execute('INSERT INTO projects(id,workspace,name,created) VALUES(?,?,?,?)', (project, 'local', 'resurrection', time.time())), 'erased project identity cannot be reinserted')
    check(erasure.erase_project(store, 'local', project, True)['complete'], 'same erasure applies idempotently after completion')
    check(store.create_project('local', 'new normal project')['state'] == 'active', 'normal writes resume after cleanup')
    with store.connect() as db:
        check(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall(), 'completed active database passes integrity and foreign-key checks')
    with store._connect(erasure_key=project_erasure_key('local', project)) as db:
        refuses(lambda: db.execute('DELETE FROM project_erasures'), 'completed erasure tombstone remains immutable even to scoped cleanup')
    check(mcp(store, 'get_job', {'job': f['job']}).get('isError') is True, 'MCP consistently refuses erased job inspection')


    f = fixture('file-interruption', 'erase-secret-file-8b6e072a'); store = f['store']
    with patch.object(store, '_sync_dir', side_effect=OSError('synthetic interrupted unlink')):
        result = erasure.erase_project(store, 'local', f['project'], True)
    check(result['phase'] == 'files' and not result['complete'], 'injected unlink interruption retains durable file phase')
    with store.connect() as db:
        key = project_erasure_key('local', f['project'])
        check(db.execute('SELECT phase FROM project_erasures WHERE key=?', (key,)).fetchone()[0] == 'files', 'file intent is durable across reopened connections')
    with store._connect(erasure_key=key) as db:
        refuses(lambda: db.execute('DELETE FROM projects WHERE id=?', (f['other'],)), 'scoped erasure authority cannot delete another project')
    check(erasure.erase_project(Store(store.root), 'local', f['project'], True)['complete'], 'fresh Store resumes partial file removal')
    check(not any(f['marker'].encode() in p.read_bytes() for p in store.root.rglob('*') if p.is_file()), 'resumed erasure removes secret from managed bytes')

    f = fixture('space-interruption', 'erase-secret-space-e15d0826'); store = f['store']
    headroom = erasure._headroom; calls = [0]
    def second_failure(target):
        calls[0] += 1
        if calls[0] == 2: raise Conflict('synthetic late space exhaustion')
        return headroom(target)
    with patch.object(erasure, '_headroom', side_effect=second_failure):
        result = erasure.erase_project(store, 'local', f['project'], True)
    check(result['phase'] == 'database' and not result['complete'], 'injected late space failure retains database phase')
    check(erasure.erase_project(Store(store.root), 'local', f['project'], True)['complete'], 'database cleanup resumes after restored space')

    f = fixture('shared-after-preview', 'erase-secret-newshared-7f89a7b8'); store = f['store']
    preview = erasure.erase_project(store, 'local', f['project'])
    store.import_asset('local', f['other'], f['unique'])
    result = erasure.erase_project(store, 'local', f['project'], True)
    check(result['complete'] and result['shared_blobs_retained'] == preview['shared_blobs_retained'] + 1, 'apply recomputes sharing added after preview')
    check((store.blobs / digest(f['unique'])).read_bytes() == f['unique'].read_bytes(), 'newly shared bytes remain owned by another project')

    active = Store(out / 'active-state'); project = active.create_project('local', 'active probe')['id']
    job = active.submit('local', project, 'vector.create', {}, 'active')
    refuses(lambda: erasure.erase_project(active, 'local', project, True), 'queued work blocks erasure')
    claim = active.claim('local', 'synthetic worker', ['vector.create'])
    refuses(lambda: erasure.erase_project(active, 'local', project, True), 'running work blocks erasure')
    execution.register(active, 'local', job['id'], claim['token'], os.getpgrp())
    active.fail('local', job['id'], claim['token'], 'synthetic', 'terminal state is not process proof')
    refuses(lambda: erasure.erase_project(active, 'local', project, True), 'terminal job with present process group still blocks erasure')
    legacy_state = legacy.Store(out / 'legacy-uncertain-state'); project = legacy_state.create_project('local', 'legacy uncertain')['id']
    old_job = legacy_state.submit('local', project, 'vector.create', {}, 'legacy'); old_claim = legacy_state.claim('local', 'synthetic worker', ['vector.create'])
    legacy_state.fail('local', old_job['id'], old_claim['token'], 'synthetic', 'legacy missing launch')
    # A fixture-only raw connection models an older absent registration record.
    raw = sqlite3.connect(legacy_state.db); raw.execute('DROP TRIGGER execution_no_delete'); raw.create_function('studio_writer_version', 0, lambda: 5)
    raw.execute('DELETE FROM attempt_executions'); raw.commit(); raw.close()
    upgraded = Store(legacy_state.root)
    refuses(lambda: erasure.erase_project(upgraded, 'local', project, True), 'legacy terminal attempt without local proof remains held')

    save('result.json', {'passed': True, 'checks': len(cases), 'cases': cases,
        'runtime': str(args.runtime), 'cli_prefix': cli_prefix, 'native_jobs_executed': 0,
        'synthetic_direct_database_setup': True, 'synthetic_fault_injection': ['unlink interruption', 'initial and late space failure'],
        'observed_lock_cases': ['real SQLite open reader', 'real worker flock', 'CLI writer while cleanup pending'],
        'owner_state_used': False, 'physical_media_erasure_qualified': False})
    print(json.dumps({'passed': True, 'checks': len(cases), 'output': str(out)}))


if __name__ == '__main__':
    main()
