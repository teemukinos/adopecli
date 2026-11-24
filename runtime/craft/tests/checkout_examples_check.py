#!/usr/bin/env python3
"""Run every built engine's documented examples through bin/dope in a source checkout.

For each operation that creates new work (no source revision needed) and whose
engine `bin/dope doctor` reports as built, this submits the example from
`bin/dope describe` and waits for the job. It uses a new temporary state folder,
so your projects are not touched. Examples that name an imported asset get a small
generated input file (audio, photo, image, video still, script) where one fits.

Run from the repository root:  .venv/bin/python -B runtime/craft/tests/checkout_examples_check.py
Options: --only vector,image   --keep (keep the state folder and print its path)
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(os.path.abspath(__file__)).parents[3]
DOPE = ROOT / 'bin/dope'
TERMINAL = ('succeeded', 'failed', 'cancelled')


def dope(env, *args, timeout=300):
    result = subprocess.run([str(DOPE), *args], env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'dope {" ".join(args)} failed ({result.returncode}): {result.stderr.strip()[-400:]}')
    return json.loads(result.stdout.strip().splitlines()[-1])


def synthetic_input(family, folder):
    """A small generated input file for examples that name an imported asset."""
    from PIL import Image
    if family == 'audio':
        path = folder / 'tone.wav'
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(44100)
            out.writeframes(b''.join(int(8000 * math.sin(2 * math.pi * 440 * n / 44100)).to_bytes(2, 'little', signed=True)
                                     for n in range(88200)))
        return path
    if family == 'photo':
        path = folder / 'photo.jpg'
        Image.new('RGB', (96, 64), (120, 160, 200)).save(path, quality=90)
        return path
    if family in ('image', 'video'):
        path = folder / 'still.png'
        Image.new('RGBA', (96, 64), (200, 120, 60, 255)).save(path)
        return path
    if family == 'inspect':
        path = folder / 'example.js'
        path.write_text('export function greet(name) { return "hello " + name; }\n')
        return path
    return None


def with_asset(value, asset, digest):
    if isinstance(value, dict):
        return {key: (asset if key == 'asset' and isinstance(item, str) else
                      digest if key == 'input_sha256' else with_asset(item, asset, digest))
                for key, item in value.items()}
    if isinstance(value, list):
        return [with_asset(item, asset, digest) for item in value]
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--only', help='comma-separated families')
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--job-timeout', type=int, default=900, help='seconds per job')
    args = parser.parse_args(argv)
    state = Path(tempfile.mkdtemp(prefix='dope-examples-')) / 'state'
    env = dict(os.environ, DOPE_STATE_DIR=str(state))
    only = set(args.only.split(',')) if args.only else None
    worker = None
    try:
        state.mkdir(parents=True)
        # Own the worker, so it stops with this check. The worker that bin/dope
        # submit starts exits at once because this one holds the state lock.
        worker = subprocess.Popen([str(DOPE), 'worker'], env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=open(state.parent / 'worker.log', 'wb'))
        time.sleep(1)
        built = {family for family, ok in dope(env, 'doctor')['engines'].items() if ok}
        operations = dope(env, 'capabilities')['operations']
        jobs, skipped, needs_asset, refused = {}, [], [], {}
        for operation in operations:
            info = dope(env, 'describe', operation)
            family = info.get('family')
            if only and family not in only:
                continue
            if family not in built or info.get('source_required') or not isinstance(info.get('example'), dict):
                skipped.append(operation)
                continue
            try:
                # A create runs only on an empty project, so each example gets its own.
                project = dope(env, 'create-project', 'Example ' + operation)['id']
                job = dope(env, 'submit', project, operation, '--parameters', json.dumps(info['example']),
                           '--key', 'example-' + operation)
            except RuntimeError as error:
                if 'asset not found' not in str(error):
                    refused[operation] = str(error)[-300:]
                    continue
                # The example names an imported asset: import a generated file and retry.
                # Imports expect the family's own portable bundle, which a generated file is not.
                source = None if operation.endswith('.import') else synthetic_input(family, state.parent)
                if source is None:
                    needs_asset.append(operation)
                    continue
                try:
                    asset = dope(env, 'import-asset', project, str(source))['id']
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()
                    job = dope(env, 'submit', project, operation, '--parameters',
                               json.dumps(with_asset(info['example'], asset, digest)), '--key', 'example-' + operation)
                except RuntimeError as retry_error:
                    refused[operation] = str(retry_error)[-300:]
                    continue
            jobs[operation] = job['id']
        results = {op: ('refused', message) for op, message in refused.items()}
        deadline = time.monotonic() + args.job_timeout * max(1, len(jobs))
        while len(results) < len(jobs) + len(refused) and time.monotonic() < deadline:
            for operation, job_id in jobs.items():
                if operation in results:
                    continue
                job = dope(env, 'job', job_id)
                if job['state'] in TERMINAL:
                    error = job.get('error') or ''
                    results[operation] = (job['state'], (error if isinstance(error, str) else json.dumps(error))[:300])
            time.sleep(2)
        for operation in jobs:
            results.setdefault(operation, ('timeout', ''))
        failed = {op: r for op, r in results.items() if r[0] != 'succeeded'}
        for operation in sorted(results):
            state_name, error = results[operation]
            print(f'{"PASS" if state_name == "succeeded" else "FAIL"} {operation} {state_name} {error}'.rstrip())
        print(json.dumps({'built_families': sorted(built), 'submitted': len(jobs),
                          'passed': len(results) - len(failed), 'failed': sorted(failed),
                          'skipped_needs_input_asset': sorted(needs_asset),
                          'skipped_without_example_or_engine': len(skipped)}))
        return 1 if failed or not jobs else 0
    finally:
        if worker:
            worker.terminate()
            try:
                worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                worker.kill()
        if args.keep:
            print('state kept at ' + str(state), file=sys.stderr)
        else:
            shutil.rmtree(state.parent, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
