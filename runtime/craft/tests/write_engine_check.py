#!/usr/bin/env python3
"""Qualify receipt-bound Write snapshots and real-process cancellation locally."""
import argparse
import copy
import json
import os
from pathlib import Path
import select
import shutil
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import animate_process, write_engine, write_project as project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    executable = args.engine.resolve(); data = args.project.read_bytes(); checked = project.inspect_bytes(data)
    pin = checked['manifest']['engine']; digest = project.sha(executable.read_bytes())
    checks = []; refusals = []; children = []; started = time.monotonic()
    real_popen = animate_process.subprocess.Popen; state = {'cancel_after_output': False, 'native_alive': False}

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def popen(command, *values, **keywords):
        child = real_popen(command, *values, **keywords)
        children.append({'pid': child.pid, 'command': list(command), 'process': child})
        if state['cancel_after_output'] and 'snapshot' in command:
            # Wait without consuming output. A large real snapshot fills its pipe,
            # keeping the native executable alive until the transport cancels it.
            ready, _, _ = select.select([child.stdout], [], [], 10)
            if not ready: child.kill(); child.wait(); raise AssertionError('native snapshot produced no output')
            with real_popen(['/bin/ps', '-p', str(child.pid), '-o', 'comm='], stdout=animate_process.subprocess.PIPE) as probe:
                name = probe.communicate(timeout=5)[0].decode().strip()
            check(name == str(executable) and child.poll() is None, 'cancellation observes actual live native executable after snapshot output')
            state['native_alive'] = True
        return child

    def engine(**overrides):
        values = {'expected_pin': pin, 'expected_binary_sha256': digest, **overrides}
        return write_engine.Engine(executable, out, **values)

    def refused(label, operation, expected, *, launches=0):
        before = len(children)
        try: operation()
        except ValueError as error:
            check(expected in str(error), label+' refuses at intended boundary')
            check(len(children)-before == launches, label+' has exact child launch count')
            refusals.append({'case': label, 'error': str(error), 'children': launches})
        else: raise AssertionError('accepted '+label)

    try:
        with patch.object(animate_process.subprocess, 'Popen', popen):
            native = engine(); report = native.verify_project(data, out/'verified')
            (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            check(report['native_calls'] == 4, 'one version and three independent native snapshots verify project')
            check(report['baseline_model_equal'] and report['current_model_equal'] and report['native_cold_reopen'], 'complete baseline and revised models survive cold native observation')
            check(all((out/'verified'/name).read_bytes() == value for name, value in checked['members'].items()), 'all source, model, history and manifest bytes remain exact')
            check(not report['engine_admission_complete'] and not report['source_format_fidelity_qualified'] and not report['durable_publication_qualified'], 'observation does not claim full admission or durable publication')
            check(not {'native-full-model-comparison', 'native-model-comparison'} & set(report['pending_qualification'])
                  and 'document-source-fidelity' in report['pending_qualification'], 'completed comparison is distinguished from remaining fidelity gate')
            refused('wrong receipt binary', lambda: engine(expected_binary_sha256='0'*64), 'differs from verified receipt')
            refused('wrong source revision', lambda: engine(expected_pin={**pin, 'source_revision': '0'*40}), 'differs from verified source pin')
            refused('wrong dependency lock', lambda: engine(expected_pin={**pin, 'source_lock_sha256': '0'*64}), 'differs from verified source pin')
            refused('invalid deadline', lambda: engine(seconds=float('inf')), 'time budget')
            refused('cancelled constructor', lambda: engine(cancelled=lambda: True), 'cancelled')
            refused('wrong executable layout', lambda: write_engine.Engine(out/'write', out, expected_pin=pin, expected_binary_sha256=digest), 'layout differs')
            alias = out/'linked-engine'; alias.symlink_to(executable.parent.parent, target_is_directory=True)
            refused('symlink engine ancestor', lambda: write_engine.Engine(alias/'bin/dobe-write', out, expected_pin=pin, expected_binary_sha256=digest), 'symbolic links')
            copied = out/'copied-engine'; (copied/'bin').mkdir(parents=True)
            shutil.copy2(executable, copied/'bin/dobe-write')
            metadata = json.loads((executable.parent.parent/'engine.json').read_bytes())
            for field in ('source', 'files'):
                invalid = copy.deepcopy(metadata)
                if field == 'source': invalid['source_lock']['source'] = []
                else: invalid['files'] = []
                (copied/'engine.json').write_text(json.dumps(invalid))
                refused('malformed manifest '+field, lambda: write_engine.Engine(copied/'bin/dobe-write', out, expected_pin=pin, expected_binary_sha256=digest), 'source/file inventory')
            invalid = copy.deepcopy(metadata); invalid['source_lock']['engine_version'] = '0.18.2'
            invalid['source_lock_sha256'] = project.sha((json.dumps(invalid['source_lock'], indent=2, sort_keys=True)+'\n').encode())
            (copied/'engine.json').write_text(json.dumps(invalid))
            forged_pin = {**pin, 'version': '0.18.2', 'source_lock_sha256': invalid['source_lock_sha256']}
            refused('manifest cannot replace native version proof', lambda: write_engine.Engine(copied/'bin/dobe-write', out, expected_pin=forged_pin, expected_binary_sha256=digest), 'version differs', launches=1)
            (copied/'engine.json').write_text(json.dumps(metadata))
            changed = write_engine.Engine(copied/'bin/dobe-write', out, expected_pin=pin, expected_binary_sha256=digest)
            with (copied/'bin/dobe-write').open('r+b') as stream:
                stream.seek(-1, os.SEEK_END); value = stream.read(1); stream.seek(-1, os.SEEK_END); stream.write(bytes([value[0]^1]))
            refused('changed receipt binary after construction', lambda: changed.observe(out/'verified/document.json', checked['members']['document.json']), 'changed after receipt verification')
            sentinel = out/'verified/owner.txt'; sentinel.write_bytes(b'owner evidence')
            refused('existing destination', lambda: native.verify_project(data, out/'verified'), 'new destination')
            check(sentinel.read_bytes() == b'owner evidence', 'failed verification preserves existing owner files')
            refused('outside destination', lambda: native.verify_project(data, out.parent/'outside'), 'inside its attempt')
            link = out/'linked-project'; link.symlink_to(out/'verified', target_is_directory=True)
            refused('symlink destination ancestor', lambda: native.verify_project(data, link/'child'), 'symbolic links')
            refused('stale observed bytes', lambda: native.observe(out/'verified/document.json', checked['members']['baseline.json']), 'changed before observation')
            refused('external observed source', lambda: native.observe(args.project, checked['members']['document.json']), 'inside its attempt')
            invalid = copy.deepcopy(checked['manifest']); invalid['engine']['source_revision'] = '0'*40
            foreign = project.pack(invalid, {k: v for k, v in checked['members'].items() if k != 'project.json'})
            refused('foreign project source pin', lambda: native.verify_project(foreign, out/'foreign'), 'pinned engine source')
            check(not (out/'foreign').exists(), 'foreign project refused before checkout')
            omitted = copy.deepcopy(checked['baseline']['document']); del omitted['core']['subject']
            omitted_project = project.create(json.dumps(omitted).encode(), 'json', engine=pin)
            refused('native default insertion is a complete model mismatch', lambda: native.verify_project(omitted_project, out/'mismatch'), 'changed the complete predicted model', launches=1)
            check(not (out/'mismatch').exists(), 'native model mismatch removes fresh checkout without normalizing original')
            native.deadline = time.monotonic()-1
            refused('expired shared deadline', lambda: native.verify_project(data, out/'expired'), 'timed out')
            check(not (out/'expired').exists(), 'deadline failure removes only fresh disposable checkout')

            large_model = copy.deepcopy(checked['baseline']['document'])
            large_model['body'].extend({'kind': 'para', 'text': 'x'*500, 'runs': [{'len': 500}], 'props': {}} for _ in range(1000))
            large_source = (json.dumps(large_model)+'\n').encode()
            large_project = project.create(large_source, 'json', engine=pin)
            cancellable = engine(); cancellable.cancelled = lambda: state['native_alive']
            state['cancel_after_output'] = True
            refused('cancel live native project observation', lambda: cancellable.verify_project(large_project, out/'cancelled'), 'cancelled', launches=1)
            state['cancel_after_output'] = False
            check(state['native_alive'] and not (out/'cancelled').exists(), 'real native cancellation removes disposable checkout')
            for child in children:
                check(child['process'].poll() is not None, 'native child '+str(child['pid'])+' reaped')
                try: os.killpg(child['pid'], 0)
                except ProcessLookupError: pass
                else: raise AssertionError('native process group survived '+str(child['pid']))
            check(args.project.read_bytes() == data and project.sha(executable.read_bytes()) == digest, 'original portable project and maintained engine remain byte-identical')
            evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(children),
                        'live_native_cancellation': state['native_alive'], 'process_groups_gone': True,
                        'binary_sha256': digest, 'engine': pin, 'project_sha256': project.sha(data),
                        'seconds': time.monotonic()-started, 'remote_actions': False,
                        'scope': 'private receipt-bound complete native JSON observation; public durable operations and full source fidelity remain pending'}
            (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
            print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(children), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally:
        (out/'children.json').write_text(json.dumps([{k: v for k, v in c.items() if k != 'process'} | {'exit_code': c['process'].poll()} for c in children], indent=2)+'\n')


if __name__ == '__main__': main()
