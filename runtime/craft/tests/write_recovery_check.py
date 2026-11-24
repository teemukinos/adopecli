#!/usr/bin/env python3
"""Cancel and crash real Write jobs, then qualify explicit durable recovery.

Requires a distribution layout containing the current runtime and native pack.
Lease expiry is controlled locally after actual process-group absence is proven.
This does not qualify reboot, clean-machine or hosted isolation behavior.
"""
import argparse
import copy
import ctypes
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('resources', 'project', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--operation', choices=('import', 'png', 'pdf'), default='import')
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    runtime = args.resources.resolve()/'runtime'; sys.path.insert(0, str(runtime))
    from studio_runtime import capabilities, execution, write_binding, write_project
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    executable = write_binding.resolve_pdf()['executable'] if args.operation == 'pdf' else write_binding.resolve()['executable']
    native_command = 'mcp' if args.operation == 'pdf' else 'render' if args.operation == 'png' else 'snapshot'
    original = args.project.read_bytes(); model = write_project.inspect_bytes(original)['baseline']['document']
    paragraph = copy.deepcopy(model['body'][1]); paragraph['text'] = 'x'*800; paragraph['runs'] = [{'len': 800}]
    model['body'].extend(copy.deepcopy(paragraph) for _ in range(4000 if args.operation == 'import' else 80))
    source = out/'large.json'; data = (json.dumps(model)+'\n').encode(); source.write_bytes(data)
    write_project.native_profile(data)
    records = []; processes = []
    code = "import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.worker import Worker;Worker(Store(sys.argv[2])).run_one()"
    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    library.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]

    def hold_snapshot(group):
        # Group-local libproc inspection catches short snapshot processes that
        # repeated global ps scans can miss. Pause only the confirmed native
        # child; keep the attempt's parent-death watcher running normally.
        pids = (ctypes.c_int * 256)(); size = library.proc_listpids(2, group, pids, ctypes.sizeof(pids))
        assert 0 <= size < ctypes.sizeof(pids), 'cannot inspect owned recovery group'
        for candidate in pids[:size//4]:
            if candidate <= 1: continue
            path = ctypes.create_string_buffer(4096)
            if library.proc_pidpath(candidate, path, len(path)) <= 0 or path.value.decode() != str(executable): continue
            try:
                if os.getpgid(candidate) != group: continue
                os.kill(candidate, signal.SIGSTOP)
                command = subprocess.run(['/bin/ps', '-p', str(candidate), '-o', 'command='], capture_output=True, text=True).stdout.strip()
                if command.startswith(str(executable)+' '+native_command+' '): return candidate
                os.kill(candidate, signal.SIGCONT)
            except ProcessLookupError: pass
        return None
    try:
        for action in ('cancel', 'crash'):
            state = out/action; store = Store(state); identity = store.create_project('local', 'Write recovery')['id']
            asset = store.import_asset('local', identity, source)['id']
            baseline = None
            if args.operation == 'import':
                submitted = store.submit('local', identity, 'write.import', {'asset': asset, 'format': 'json'}, action)
            else:
                initial = store.submit('local', identity, 'write.import', {'asset': asset, 'format': 'json'}, 'initial')
                Worker(store).run_one(); initial = store.get_job('local', initial['id']); assert initial['state'] == 'succeeded', initial
                baseline = initial['result_revision']
                params = {'format': args.operation, 'font_substitutions': [{'requested':name,'actual':'Source Sans 3'} for name in ('Aptos','Aptos Display')]}
                if args.operation == 'png': params.update(pages=[1], scale=4)
                submitted = store.submit('local', identity, 'write.export', params, action, baseline)
            group = None; child = None
            with (out/(action+'.log')).open('wb') as log:
                worker = subprocess.Popen([sys.executable, '-I', '-B', '-c', code, str(runtime), str(state)], stdout=log, stderr=log)
                processes.append(worker)
                try:
                    deadline = time.monotonic()+120
                    while time.monotonic() < deadline and worker.poll() is None:
                        with store.connect() as db:
                            row = db.execute('SELECT e.process_group FROM attempt_executions e JOIN jobs j ON e.token=j.token WHERE j.id=?', (submitted['id'],)).fetchone()
                        if row and row['process_group']:
                            group = row['process_group']
                            child = hold_snapshot(group)
                        if child: break
                        time.sleep(.001)
                    assert child and group and worker.poll() is None, 'no confirmed live native '+native_command+' child'
                    if action == 'cancel':
                        store.cancel('local', submitted['id']); worker.wait(timeout=20)
                        result = store.get_job('local', submitted['id']); assert result['state'] == 'cancelled', result
                    else: worker.kill(); worker.wait(timeout=5)
                    assert execution.wait_group_absent(group, timeout=10), 'native Write process group did not terminate'
                    assert store.get_project('local', identity)['head'] == baseline, 'cancelled/interrupted job published a revision'
                    record = {'action': action, 'live_native_pid': child, 'registered_group': group, 'native_child_held_with_sigstop': True,
                              'attempt_watcher_not_stopped': True, 'group_absent': True, 'no_revision_published': True, 'preserved_head': baseline}
                    if action == 'crash':
                        with store.transaction() as db: db.execute('UPDATE jobs SET lease_until=? WHERE id=?', (time.time()-1, submitted['id']))
                        assert store.recover('local') == 1
                        assert store.get_job('local', submitted['id'])['state'] == 'interrupted'
                        assert Worker(store).run_one() is False, 'interrupted Write work replayed automatically'
                        store.retry('local', submitted['id'], 'explicit-retry', capabilities.RETRY_SAFE)
                        Worker(store).run_one(); result = store.get_job('local', submitted['id'])
                        assert result['state'] == 'succeeded' and result['attempt'] == 2, result
                        revision = store.get_revision('local', result['result_revision'])
                        recovered = out/'recovered'; store.checkout('local', revision['id'], recovered)
                        assert (recovered/'native/original.json').read_bytes() == data
                        assert revision['validation']['native_model_equal'] and revision['validation']['native_cold_reopen']
                        if args.operation != 'import': assert revision['validation']['render_qualified']
                        record.update(lease_expiry='controlled local test', automatic_replay=False, explicit_retry_succeeded=True,
                                      exact_original_preserved=True, complete_native_model_verified=True)
                    records.append(record)
                finally:
                    if worker.poll() is None: worker.kill(); worker.wait(timeout=5)
                    if group: assert execution.wait_group_absent(group, timeout=10), 'attempt cleanup remains uncertain'
        assert source.read_bytes() == data and args.project.read_bytes() == original
        evidence = {'passed': True, 'records': records, 'operation': args.operation, 'native_command': native_command,
                    'real_native_children': True, 'source_bytes': len(data),
                    'source_sha256': hashlib.sha256(data).hexdigest(), 'all_workers_terminal': all(p.poll() is not None for p in processes),
                    'installed_qualification': False, 'reboot_qualified': False, 'hosted_isolation_qualified': False, 'remote_actions': False}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n'); print(json.dumps(evidence))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'passed': False, 'records': records, 'error': str(error)}, indent=2)+'\n'); raise


if __name__ == '__main__': main()
