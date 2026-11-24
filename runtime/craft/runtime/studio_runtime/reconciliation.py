"""Explicit reconciliation of local execution uncertainty; never replay or publish.

The worker must be stopped. A missing legacy registration remains held unless
an operator records its local origin and a later boot proves termination.
"""
import fcntl
import json
import os
import re
import time
from . import capabilities, capacity, execution, job_routing
from .store import Conflict, NotFound, canonical

UNSETTLED = ('running', 'validating', 'interrupted')


def attempt(db, store, workspace, job, number):
    if type(number) is not int or number < 1:
        raise ValueError('attempt must be a positive integer')
    current = store._job(db, workspace, job)
    row = db.execute('SELECT * FROM attempts WHERE job=? AND number=?', (job, number)).fetchone()
    if row is None:
        raise NotFound('attempt not found')
    launch = db.execute('SELECT * FROM attempt_executions WHERE token=?', (row['token'],)).fetchone()
    receipt = db.execute('SELECT * FROM attempt_reconciliations WHERE token=?', (row['token'],)).fetchone()
    return dict(current), dict(row), dict(launch) if launch else None, dict(receipt) if receipt else None


def proof(job, row, launch, observed):
    if row['state'] not in UNSETTLED:
        return {'eligible': False, 'reason': 'attempt_already_settled'}
    if job['operation'] not in job_routing.supported_operations(capabilities.RETRY_SAFE):
        return {'eligible': False, 'reason': 'external_operation_requires_separate_reconciliation'}
    if launch is None:
        return {'eligible': False, 'reason': 'legacy_origin_and_reboot_required'}
    if launch['machine'] != observed['machine']:
        return {'eligible': False, 'reason': 'different_machine'}
    if launch['boot'] != observed['boot']:
        return {'eligible': True, 'reason': 'later_boot_on_same_machine',
                'recorded_boot': launch['boot'], 'observed_boot': observed['boot'],
                'origin': 'operator_confirmed' if launch['phase'] == 'legacy' else 'registered_by_runtime'}
    if launch['phase'] == 'legacy':
        return {'eligible': False, 'reason': 'waiting_for_later_boot', 'origin': 'operator_confirmed'}
    if launch['phase'] == 'prepared' and launch['process_group'] is None and launch['registered'] is None:
        return {'eligible': True, 'reason': 'engine_never_admitted'}
    if launch['phase'] == 'registered':
        try:
            absent = execution.group_absent(launch['process_group'])
        except (OSError, ValueError) as error:
            return {'eligible': False, 'reason': 'process_group_inspection_unavailable', 'detail': str(error)[:500]}
        return {'eligible': absent, 'reason': 'registered_group_absent' if absent else 'process_group_still_present'}
    return {'eligible': False, 'reason': 'execution_record_invalid'}


def receipt_view(receipt):
    return {key: json.loads(value) if key == 'evidence' else value for key, value in receipt.items() if key != 'token'}


def recovery_headroom(db, store, observed):
    """Release reserved journal space only when no uncertain engine can use it."""
    if capacity.configuration(store.root) is None:
        return
    space = os.statvfs(store.root)
    if space.f_bavail * space.f_frsize >= capacity.RESERVE_BYTES // 2:
        return
    for candidate in db.execute("""SELECT j.workspace,a.job,a.number FROM attempts a JOIN jobs j ON j.id=a.job
            WHERE a.state IN ('running','validating','interrupted')"""):
        current, row, launch, _ = attempt(db, store, candidate['workspace'], candidate['job'], candidate['number'])
        if not proof(current, row, launch, observed)['eligible']:
            raise Conflict('cannot release recovery space while another execution remains uncertain')
    capacity.check(store.root, store.storage_generation, recovery=True)


def list_holds(store, workspace, after=None):
    cursor_job, cursor_number = '', 0
    if after is not None:
        if not isinstance(after, str) or not re.fullmatch(r'[a-f0-9]{32}:[1-9][0-9]{0,8}', after):
            raise ValueError('invalid attempt cursor')
        cursor_job, cursor_number = after.split(':'); cursor_number = int(cursor_number)
    with store.connect() as db:
        rows = db.execute("""SELECT a.job,a.number,j.project,a.state FROM attempts a JOIN jobs j ON j.id=a.job
            WHERE j.workspace=? AND a.state IN ('running','validating','interrupted')
            AND (a.job>? OR (a.job=? AND a.number>?)) ORDER BY a.job,a.number LIMIT 100""",
            (workspace, cursor_job, cursor_job, cursor_number)).fetchall()
        entries = [{'job': r['job'], 'attempt': r['number'], 'project': r['project'], 'state': r['state']} for r in rows]
    return {'attempts': entries, 'next_cursor': f"{rows[-1]['job']}:{rows[-1]['number']}" if len(rows) == 100 else None,
            'instruction': 'Stop the worker, then preview reconciliation for a selected attempt.'}


def reconcile(store, workspace, job, number, apply=False, confirm_local_origin=False):
    if type(apply) is not bool or type(confirm_local_origin) is not bool:
        raise ValueError('apply and confirm_local_origin must be booleans')
    with open(store.root / 'worker.lock', 'a+') as worker, open(store.root / 'artifacts.lock', 'a+') as artifacts:
        try:
            fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('stop the local worker before reconciling attempts')
        fcntl.flock(artifacts, fcntl.LOCK_EX)
        observed = execution.identity()
        with store.transaction() as db:
            current, row, launch, receipt = attempt(db, store, workspace, job, number)
            result = {'job': job, 'attempt': number, 'state': row['state'], 'applied': apply,
                      'artifacts_removed': False, 'result_published': False}
            if receipt:
                return {**result, 'reconciled': True, 'receipt': receipt_view(receipt)}
            evidence = proof(current, row, launch, observed)
            result.update(reconciled=False, evidence=evidence)
            if not apply:
                return result
            if evidence['reason'] == 'legacy_origin_and_reboot_required' and confirm_local_origin:
                db.execute("INSERT INTO attempt_executions(token,machine,boot,phase,prepared) VALUES(?,?,?,'legacy',?)",
                           (row['token'], observed['machine'], observed['boot'], time.time()))
                store._event(db, job, 'reconciliation_baseline', {'attempt': number, 'origin': 'operator_confirmed_local', 'boot': observed['boot']})
                return {**result, 'baseline_recorded': True, 'evidence': {'eligible': False, 'reason': 'waiting_for_later_boot', 'origin': 'operator_confirmed'}}
            if not evidence['eligible']:
                return result
            # A late historical attempt can be settled without changing a newer
            # job attempt or a successful revision. Current leases are fenced by
            # the transaction and the exclusive worker lock.
            settle_job = current['attempt'] == number and current['state'] in UNSETTLED
            if current['attempt'] == number:
                if current['result_revision'] is not None:
                    raise Conflict('current job state does not match the unresolved attempt')
                if not settle_job and not (current['state'] in ('queued', 'failed', 'cancelled')
                        and current['token'] is None and row['state'] == 'interrupted'
                        and db.execute('SELECT 1 FROM retries WHERE job=? LIMIT 1', (job,)).fetchone()):
                    raise Conflict('current job state does not match the unresolved attempt')
                if current['state'] in ('running', 'validating') and current['token'] != row['token']:
                    raise Conflict('current execution token does not match its attempt')
            recovery_headroom(db, store, observed)
            now = time.time()
            evidence = {**evidence, 'observed_machine': observed['machine'], 'observed_boot': observed['boot'],
                        'launch_phase': launch['phase'], 'process_group': launch['process_group']}
            db.execute('INSERT INTO attempt_reconciliations VALUES(?,?,?,?,?,?)',
                       (row['token'], row['state'], row['error'], row['finished'], canonical(evidence), now))
            error = {'code': 'execution_reconciled', 'message': 'Execution is stopped or was never admitted; no result was published'}
            db.execute("UPDATE attempts SET state='failed',error=?,finished=? WHERE token=?", (canonical(error), now, row['token']))
            store._event(db, job, 'attempt_reconciled', {'attempt': number, 'evidence': evidence})
            if settle_job:
                db.execute("UPDATE jobs SET state='failed',token=NULL,lease_until=NULL,error=?,updated=? WHERE id=?",
                           (canonical(error), now, job))
                store._event(db, job, 'failed', {**error, 'attempt': number, 'reconciled': True})
            receipt = dict(db.execute('SELECT * FROM attempt_reconciliations WHERE token=?', (row['token'],)).fetchone())
            return {**result, 'state': 'failed', 'reconciled': True, 'receipt': receipt_view(receipt)}
