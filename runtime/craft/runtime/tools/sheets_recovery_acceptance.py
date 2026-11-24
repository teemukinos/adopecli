"""Qualify real Sheets child interruption, explicit retry and MCP cancellation.

Use a sealed package, new disposable output, and an exact guard-verification JSON.
Run each stage once. A started stage never restarts automatically after failure.
All application mutations use public CLI/MCP; SQLite access is query-only.
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--expect-verification', required=True, type=Path)
parser.add_argument('--stage', required=True, choices=['baseline', 'interrupt', 'retry', 'cancel', 'verify'])
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
package = args.package.resolve(strict=True)
out = args.output.absolute()
out.mkdir(mode=0o700, exist_ok=args.resume)
lock = (out / 'fixture.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
(out / 'home').mkdir(exist_ok=args.resume)
state = out / 'state'
env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
cases = json.loads((out / 'cases.json').read_text()) if (out / 'cases.json').exists() else []
commands = json.loads((out / 'commands.json').read_text()) if (out / 'commands.json').exists() else []


def save(name, value):
    temporary = out / (name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(out / name)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(value, label):
    if not value:
        raise AssertionError(label)
    if label not in cases:
        cases.append(label)
        save('cases.json', cases)


def command(label, arguments, timeout=600):
    started = time.time()
    arguments = list(map(str, arguments))
    result = subprocess.run(arguments, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout)
    commands.append({'label': label, 'command': arguments, 'exit': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr, 'seconds': time.time() - started})
    save('commands.json', commands)
    check(result.returncode == 0, label + ' succeeds')
    return json.loads(result.stdout) if result.stdout.strip() else None


def cli(label, *arguments):
    return command(label, [package / 'bin/a-dope-cli', '--state', state, *arguments])


def rows(sql, parameters=()):
    with sqlite3.connect((state / 'studio.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, parameters)]


def snapshot(label):
    tables = ['projects', 'jobs', 'attempts', 'attempt_executions', 'attempt_reconciliations',
              'revisions', 'retries', 'events', 'project_events', 'assets']
    result = {table: rows('SELECT * FROM ' + table) for table in tables}
    save(label + '.json', result)
    return result


def absent(group, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.killpg(group, 0)
        except OSError as error:
            if error.errno == errno.ESRCH:
                return True
            raise
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def start_worker(label):
    log = (out / (label + '.log')).open('wb')
    arguments = [str(package / 'bin/a-dope-cli'), '--state', str(state), 'worker', '--once']
    process = subprocess.Popen(arguments, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    save(label + '-process.json', {'pid': process.pid, 'command': arguments, 'started': time.time()})
    return process, log


def close_worker(label, process, log):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=30)
    record = json.loads((out / (label + '-process.json')).read_text())
    record.update(exit=process.returncode, completed=time.time())
    save(label + '-process.json', record)
    log.close()


def native_processes(group):
    expected = str(package / 'lib/dobe/engines/sheets/bin/dobe-sheets') + ' recalc '
    found = []
    for line in subprocess.check_output(['/bin/ps', '-axo', 'pid=,pgid=,command='], text=True).splitlines():
        values = line.strip().split(None, 2)
        if len(values) == 3 and values[1] == str(group) and values[2].startswith(expected):
            found.append({'pid': int(values[0]), 'group': group, 'command': values[2]})
    return found


def observe_native(job, worker, label):
    deadline = time.monotonic() + 180
    while worker.poll() is None and time.monotonic() < deadline:
        found = rows('''SELECT j.state,j.lease_until,a.token,e.process_group FROM jobs j
            JOIN attempts a ON a.job=j.id AND a.number=j.attempt
            JOIN attempt_executions e ON e.token=a.token WHERE j.id=?''', (job,))
        if found and found[0]['state'] == 'running' and found[0]['process_group']:
            observed = native_processes(found[0]['process_group'])
            if observed:
                record = dict(found[0], job=job, worker_pid=worker.pid,
                              native_processes=observed, observed_at=time.time())
                save(label + '-live.json', record)
                return record
        time.sleep(0.005)
    raise AssertionError('No real Sheets recalc child observed for ' + label)


def receipt(folder):
    result = json.loads((folder / 'project.json').read_text())
    for entry in result['files']:
        path = folder / entry['path']
        check(path.is_file() and not path.is_symlink() and path.stat().st_size == entry['bytes']
              and sha(path) == entry['sha256'], folder.name + ' exact receipt ' + entry['path'])
    return result


class Client:
    def __init__(self):
        self.log = (out / 'cancel-mcp.log').open('wb')
        self.process = subprocess.Popen([str(package / 'bin/a-dope-cli'), '--state', str(state), 'mcp'],
                                        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.log, bufsize=0)
        save('cancel-mcp-process.json', {'pid': self.process.pid, 'started': time.time()})
        self.sequence = 0

    def call(self, method, parameters):
        self.sequence += 1
        request = {'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': parameters}
        sent = time.time()
        self.process.stdin.write((json.dumps(request) + '\n').encode())
        response = bytearray()
        deadline = time.monotonic() + 30
        while not response.endswith(b'\n'):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise AssertionError('MCP response timeout; existing work is not restarted')
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                raise AssertionError('MCP closed before response')
            response.extend(data)
            if len(response) > 1 << 20:
                raise AssertionError('MCP response exceeds fixture bound')
        value = json.loads(response)
        commands.append({'label': 'persistent MCP ' + method, 'request': request,
                         'sent_at': sent, 'received_at': time.time(), 'response': value})
        save('commands.json', commands)
        check(value.get('id') == self.sequence and 'error' not in value, method + ' MCP response')
        result = value['result']
        check(not result.get('isError'), method + ' MCP tool succeeds')
        return result

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=30)
        check(self.process.returncode == 0, 'owned MCP session closes normally')
        save('cancel-mcp-process.json', {'pid': self.process.pid, 'exit': self.process.returncode,
                                        'completed': time.time()})
        self.process.stdout.close()
        self.log.close()


verification = command('exact package verification', [package / 'bin/a-dope-guard', 'verify'])
check(verification == json.loads(args.expect_verification.read_text()) and verification['verified'],
      'package matches the expected seal and guard')
marker = out / (args.stage + '-complete.json')
if marker.exists():
    check(json.loads(marker.read_text())['passed'], 'completed stage remains recorded')
    print(json.dumps({'stage': args.stage, 'already_complete': True, 'checks': len(cases)}))
    raise SystemExit(0)
started = out / (args.stage + '-started.json')
if started.exists():
    raise RuntimeError('Stage already started; inspect its durable jobs and live handles before continuing')
save(started.name, {'pid': os.getpid(), 'started': time.time()})
context = json.loads((out / 'context.json').read_text()) if (out / 'context.json').exists() else None

if args.stage == 'baseline':
    check(context is None, 'baseline creates new disposable state')
    model = json.loads((package / 'lib/dobe/runtime/studio_runtime/sheets_base.json').read_text())
    sheet = model['sheets'][0]
    sheet['name'] = 'Recovery proof'
    bands = {}
    for row in range(512):
        cells = {'0': {'value': {'t': 'Number', 'v': float(row + 1)}, 'formula': None, 'style': 0}}
        for column in range(1, 13):
            cells[str(column)] = {'value': {'t': 'Text', 'v': ('Synthetic recovery content ' * 20)
                                            + str(row) + '/' + str(column)}, 'formula': None, 'style': 0}
        for column in (13, 14):
            cells[str(column)] = {'value': {'t': 'Empty'},
                                  'formula': {'text': 'SUM(A1:A512)', 'array': None}, 'style': 0}
        bands.setdefault(str(row // 64), {'rows': {}})['rows'][str(row)] = cells
    sheet['cells'] = {'bands': bands, 'len': 7680}
    save('create-request.json', {'document': model})
    project = cli('create recovery project', 'create-project', 'Sheets recovery qualification')['id']
    context = {'project': project, 'cells': 7680, 'formulas': 1024}
    save('context.json', context)
    job = cli('submit baseline', 'submit', project, 'sheets.create', '--parameters', out / 'create-request.json',
              '--key', 'sheets-recovery-baseline', '--timeout', '600')
    save('baseline-job.json', job)
    cli('run baseline worker', 'worker', '--once')
    result = cli('baseline result', 'job', job['id'])
    check(result['state'] == 'succeeded' and result['attempt'] == 1, 'actual native baseline succeeds once')
    context['source_revision'] = result['result_revision']
    cli('checkout baseline', 'checkout', result['result_revision'], out / 'original')
    original = receipt(out / 'original')
    context['source_hashes'] = {entry['path']: entry['sha256'] for entry in original['files']}
    save('context.json', context)
    save('calculate-request.json', {'expected_sha256': sha(out / 'original/native/project.dobesheets')})
    observed = json.loads((out / 'original/native/document.json').read_text())
    formula_values = [cell['value'] for band in observed['sheets'][0]['cells']['bands'].values()
                      for row in band['rows'].values() for cell in row.values() if cell['formula']]
    check(len(formula_values) == 1024 and all(v == {'t': 'Number', 'v': 131328.0} for v in formula_values),
          'all 1024 actual formula results match independent integer sum')
elif args.stage == 'interrupt':
    check((out / 'baseline-complete.json').exists(), 'baseline completes before interruption')
    job = cli('submit interrupted calculation', 'submit', context['project'], 'sheets.calculate',
              '--parameters', out / 'calculate-request.json', '--source', context['source_revision'],
              '--key', 'sheets-recovery-interrupt', '--timeout', '600')
    save('interruption-job.json', job)
    process, log = start_worker('interrupted-worker')
    try:
        live = observe_native(job['id'], process, 'interrupted')
        check(process.poll() is None, 'owned supervisor remains live before intentional crash')
        process.kill()
        process.wait(timeout=10)
        check(process.returncode == -signal.SIGKILL, 'owned supervisor dies from deliberate SIGKILL')
        check(absent(live['process_group']), 'actual Sheets crash group becomes absent')
    finally:
        close_worker('interrupted-worker', process, log)
    current = cli('job after supervisor crash', 'job', job['id'])
    check(current['attempt'] == 1 and current['result_revision'] is None, 'crash publishes no partial revision')
    check(cli('head after crash', 'project', context['project'])['head'] == context['source_revision'],
          'crash preserves original project head')
    deadline = time.monotonic() + 50
    while current['lease_until'] and time.time() <= current['lease_until']:
        check(time.monotonic() < deadline, 'natural lease expiry stays bounded')
        time.sleep(0.1)
    cli('recover naturally expired lease', 'recover')
    current = cli('interrupted job state', 'job', job['id'])
    check(current['state'] == 'interrupted', 'natural recovery fences interrupted attempt')
    cli('idle worker cannot replay', 'worker', '--once')
    current = cli('job remains interrupted', 'job', job['id'])
    check(current['state'] == 'interrupted' and current['attempt'] == 1, 'no automatic replay after crash')
    preview = cli('preview stopped group reconciliation', 'reconcile-attempt', job['id'], '--attempt', '1')
    check(preview['evidence'] == {'eligible': True, 'reason': 'registered_group_absent'},
          'reconciliation independently proves registered group absent')
    applied = cli('reconcile stopped group', 'reconcile-attempt', job['id'], '--attempt', '1', '--apply')
    check(applied['reconciled'] and not applied['result_published'] and not applied['artifacts_removed'],
          'explicit reconciliation retains evidence without publication or deletion')
elif args.stage == 'retry':
    check((out / 'interrupt-complete.json').exists(), 'stopped-attempt reconciliation precedes retry')
    job = json.loads((out / 'interruption-job.json').read_text())
    first = cli('explicit calculation retry', 'retry', job['id'], '--key', 'sheets-recovery-retry')
    second = cli('repeat same retry key', 'retry', job['id'], '--key', 'sheets-recovery-retry')
    check(first == second and second['state'] == 'queued', 'explicit retry key is idempotent')
    cli('run retried native calculation', 'worker', '--once')
    result = cli('retried calculation result', 'job', job['id'])
    check(result['state'] == 'succeeded' and result['attempt'] == 2, 'explicit retry succeeds as second attempt')
    check(len(rows('SELECT id FROM revisions WHERE project=?', (context['project'],))) == 2,
          'retry publishes exactly one additional revision')
    cli('checkout recovered workbook', 'checkout', result['result_revision'], out / 'recovered')
    receipt(out / 'recovered')
    for name in ['document.json', 'original.json']:
        check((out / 'original/native' / name).read_bytes() == (out / 'recovered/native' / name).read_bytes(),
              'recovery preserves every native byte of ' + name)
    context['recovered_revision'] = result['result_revision']
    save('context.json', context)
    save('cancel-request.json', {'expected_sha256': sha(out / 'recovered/native/project.dobesheets')})
elif args.stage == 'cancel':
    check((out / 'retry-complete.json').exists(), 'successful recovery precedes cancellation')
    client = Client()
    process = log = None
    try:
        client.call('initialize', {'protocolVersion': '2025-06-18'})
        tools = client.call('tools/list', {})['tools']
        check(any(t['name'] == 'dope_cancel_job' for t in tools), 'public MCP exposes cancellation')
        job = cli('submit cancellation calculation', 'submit', context['project'], 'sheets.calculate',
                  '--parameters', out / 'cancel-request.json', '--source', context['recovered_revision'],
                  '--key', 'sheets-recovery-cancel', '--timeout', '600')
        save('cancellation-job.json', job)
        process, log = start_worker('cancelled-worker')
        live = observe_native(job['id'], process, 'cancelled')
        requested = client.call('tools/call', {'name': 'dope_cancel_job', 'arguments': {'job': job['id']}})
        reply = json.loads(requested['content'][0]['text'])
        check(reply['cancel_requested'], 'persistent public MCP records explicit cancellation')
        process.wait(timeout=30)
        check(absent(live['process_group']), 'cancelled actual Sheets process group becomes absent')
        result = cli('cancelled job result', 'job', job['id'])
        check(result['state'] == 'cancelled' and result['attempt'] == 1 and result['result_revision'] is None,
              'live-child cancellation publishes no result')
        check(cli('head after cancellation', 'project', context['project'])['head'] == context['recovered_revision'],
              'cancellation preserves previously recovered head')
        check(len(rows('SELECT id FROM revisions WHERE project=?', (context['project'],))) == 2,
              'cancelled calculation adds no revision')
    finally:
        if process is not None:
            close_worker('cancelled-worker', process, log)
        client.close()
else:
    check((out / 'cancel-complete.json').exists(), 'all controlled execution stages complete')
    for folder in ['original', 'recovered']:
        receipt(out / folder)
    for name, digest in context['source_hashes'].items():
        check(sha(out / 'original' / name) == digest, 'original checkout remains unchanged: ' + name)
    groups = rows('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')
    check(len(groups) == 4 and all(absent(row['process_group']) for row in groups),
          'all four actual attempt groups are absent')
    check(rows('PRAGMA integrity_check')[0]['integrity_check'] == 'ok', 'SQLite integrity remains intact')
    check(not rows('PRAGMA foreign_key_check'), 'SQLite foreign keys remain intact')
    check(len(rows('SELECT id FROM jobs')) == 3 and len(rows('SELECT * FROM attempts')) == 4,
          'exactly three jobs and four attempts; no implicit replay')
    check(command('final package verification', [package / 'bin/a-dope-guard', 'verify']) == verification,
          'complete package identity remains unchanged')

snapshot(args.stage + '-state')
save(marker.name, {'passed': True, 'stage': args.stage, 'checks': len(cases),
                   'package_verification': verification, 'completed': time.time(),
                   'lease_or_clock_changed': False, 'native_binary_changed': False,
                   'remote_actions': False, 'full_release_qualified': False})
print(json.dumps({'stage': args.stage, 'passed': True, 'checks': len(cases), 'evidence': str(out)}))
