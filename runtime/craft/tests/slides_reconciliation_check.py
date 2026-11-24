#!/usr/bin/env python3
"""Recover a real interrupted Slides job with the qualified-contract fix.

The supplied state must belong to a stopped, isolated qualification installation.
The original package remains unchanged. Current source performs reconciliation;
the immutable package executes the explicitly retried native export.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'state', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--job', required=True)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir()
    package = args.package.resolve(); state = args.state.resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
    from studio_runtime import capabilities, reconciliation
    from studio_runtime.store import Store
    store = Store(state); checks = []
    before = store.get_job('local', args.job)
    assert before['state'] == 'interrupted' and before['operation'] == 'slides.export' and before['attempt'] == 1
    (out / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
    head = store.get_project('local', before['project'])['head']
    store.checkout('local', head, out / 'before-source')
    old_runtime = package / 'lib/dobe/runtime'
    python = package / 'lib/dobe/python/bin/python3'
    env = {'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin'}
    code = "import sys,json;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.reconciliation import reconcile;print(json.dumps(reconcile(Store(sys.argv[2]),'local',sys.argv[3],1)))"
    old = subprocess.run([str(python), '-I', '-B', '-c', code, str(old_runtime), str(state), args.job],
                         env=env, capture_output=True, text=True, timeout=30)
    assert old.returncode == 0, old.stderr
    rejected = json.loads(old.stdout)
    assert rejected['evidence'] == {'eligible': False, 'reason': 'external_operation_requires_separate_reconciliation'}
    checks.append('immutable dev52 reproduces the refusal on the actual interrupted native PDF attempt')
    preview = reconciliation.reconcile(store, 'local', args.job, 1)
    assert preview['evidence'] == {'eligible': True, 'reason': 'registered_group_absent'}
    assert store.get_job('local', args.job) == before
    applied = reconciliation.reconcile(store, 'local', args.job, 1, apply=True)
    assert applied['reconciled'] and not applied['result_published'] and not applied['artifacts_removed']
    assert reconciliation.reconcile(store, 'local', args.job, 1, apply=True)['receipt'] == applied['receipt']
    assert store.get_project('local', before['project'])['head'] == head
    checks.append('current source admits only the qualified contract, proves group absence and records an idempotent receipt without publication')
    queued = store.retry('local', args.job, 'qualified-reconciliation-retry', capabilities.RETRY_SAFE)
    assert queued['state'] == 'queued' and queued['attempt'] == 1
    code = "import sys,json;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.worker import Worker;s=Store(sys.argv[2]);print(json.dumps({'ran':Worker(s).run_one(),'job':s.get_job('local',sys.argv[3])}))"
    result = subprocess.run([str(python), '-I', '-B', '-c', code, str(old_runtime), str(state), args.job],
                            env=env, capture_output=True, text=True, timeout=660)
    assert result.returncode == 0, result.stderr
    result = json.loads(result.stdout); finished = result['job']
    assert result['ran'] and finished['state'] == 'succeeded' and finished['attempt'] == 2, finished
    revision = store.get_revision('local', finished['result_revision'])
    assert revision['validation']['render_qualified'] and revision['validation']['native_model_equal']
    store.checkout('local', revision['id'], out / 'recovered')
    for name in ('original.json', 'document.json', 'project.dobeslides'):
        assert (out / 'recovered/native' / name).read_bytes() == (out / 'before-source/native' / name).read_bytes()
    checks.append('explicit retry completes the same native PDF job with exact editable source and original image history')
    isolated = Store(out / 'unknown-contract-state')
    owner = isolated.create_project('local', 'Unknown contract')['id']
    submitted = isolated.submit('local', owner, 'slides.create', {}, 'future-contract')
    claimed = isolated.claim('local', 'owned-prepared-attempt', ('slides.create',))
    isolated.interrupt('local', submitted['id'], claimed['token'], 'Prepared-only qualification fixture')
    with isolated.transaction() as db:
        db.execute('UPDATE jobs SET operation=? WHERE id=?', ('slides.create@unknown-future', submitted['id']))
    refused = reconciliation.reconcile(isolated, 'local', submitted['id'], 1, apply=True)
    assert not refused['reconciled'] and not refused['evidence']['eligible']
    assert refused['evidence']['reason'] == 'external_operation_requires_separate_reconciliation'
    assert isolated.get_job('local', submitted['id'])['state'] == 'interrupted'
    checks.append('an unknown future contract remains held even when its public request names a safe local operation')
    with store.connect() as db:
        groups = [row[0] for row in db.execute('SELECT e.process_group FROM attempt_executions e JOIN attempts a ON a.token=e.token WHERE a.job=? AND e.process_group IS NOT NULL', (args.job,))]
    for group in groups:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            continue
        raise AssertionError('native process group still present: ' + str(group))
    evidence = {'passed': True, 'checks': checks, 'before': before, 'previous_refusal': rejected,
                'preview': preview, 'reconciliation': applied, 'completed_job': finished,
                'unknown_contract_refusal': refused, 'registered_groups_absent': groups,
                'immutable_package': str(package), 'source_fix_qualified': True,
                'fixed_runtime_packaged': False, 'remote_actions': False}
    (out / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': len(checks), 'same_native_job_recovered': True, 'fixed_runtime_packaged': False}))


if __name__ == '__main__':
    main()
