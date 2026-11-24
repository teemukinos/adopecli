#!/usr/bin/env python3
"""Qualify real Slides receipts, complete native preservation and cancellation.

The distribution-layout fixture is local and unpublished. It is not an installed
release, an imported-model admission test or a rendering fidelity qualification.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'project', 'native-source', 'output'): parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--staged', action='store_true'); args = parser.parse_args()
    out = args.output.resolve(); resources = out/'fixture/DobeCLI/lib/dobe'; runtime = resources/'runtime'
    if not args.staged:
        import hashlib
        out.mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1]/'runtime/studio_runtime', runtime/'studio_runtime', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(args.engine.resolve().parent.parent, resources/'engines/slides')
        metadata_bytes = (resources/'engines/slides/engine.json').read_bytes(); metadata = json.loads(metadata_bytes)
        manifest = {'schema_version': 1, 'product': 'dobe', 'distribution': 'dobe-cli', 'platform': 'macos-arm64',
                    'qualification': 'test-layout-only-not-installed', 'release_signed': False,
                    'components': [{'name': 'dobe-slides', 'version': metadata['version'], 'source_lock_sha256': metadata['source_lock_sha256'],
                                    'engine_manifest_sha256': hashlib.sha256(metadata_bytes).hexdigest()}], 'files': {}}
        for path in resources.rglob('*'):
            if path.is_file(): manifest['files'][path.relative_to(resources.parent.parent).as_posix()] = {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (resources/'bundle.json').write_text(json.dumps(manifest, sort_keys=True)+'\n')
        command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--staged']
        for key in ('engine', 'project', 'native_source', 'output'): command.extend(['--'+key.replace('_', '-'), str(getattr(args, key).resolve())])
        raise SystemExit(subprocess.run(command, timeout=240).returncode)
    sys.path.insert(0, str(runtime))
    from studio_runtime import animate_process, slides_binding as binding, slides_engine, slides_project as project, slides_source as source, slides_revision as revision
    checks = []; refusals = []; children = []; started = time.monotonic(); work = out/'attempt'; work.mkdir()
    portable = args.project.read_bytes(); original = args.native_source.read_bytes(); checked = project.inspect_bytes(portable)
    real_popen = animate_process.subprocess.Popen; state = {'cancel': False, 'live': False}
    receipt = resources/'bundle.json'; receipt_bytes = receipt.read_bytes(); engine_bytes = args.engine.read_bytes()

    def check(label, value):
        if not value: raise AssertionError(label)
        checks.append(label)

    def popen(command, *values, **keywords):
        child = real_popen(command, *values, **keywords); children.append({'pid': child.pid, 'command': list(command), 'process': child})
        if state['cancel'] and 'encode' in command:
            ready, _, _ = select.select([child.stdout], [], [], 10)
            if not ready: child.kill(); child.wait(); raise AssertionError('native encode produced no output')
            with real_popen(['/bin/ps', '-p', str(child.pid), '-o', 'comm='], stdout=subprocess.PIPE) as probe:
                name = probe.communicate(timeout=5)[0].decode().strip()
            check('cancellation observes real live native executable with output pending', name == str(resources/'engines/slides/bin/dobe-slides') and child.poll() is None)
            state['live'] = True
        return child

    def refused(label, action, contains, launches=0):
        count = len(children)
        try: action()
        except ValueError as error:
            check(label+' refused at intended boundary', contains in str(error))
            check(label+' has exact process count', len(children)-count == launches)
            refusals.append({'case': label, 'error': str(error), 'children': launches})
        else: raise AssertionError('accepted '+label)

    def engine(**overrides): return slides_engine.Engine(root=work, **(binding.resolve() | overrides))

    try:
        with patch.object(animate_process.subprocess, 'Popen', popen):
            os.environ['PATH'] = str(out/'untrusted-bin'); os.environ['STUDIO_BUNDLE_RESOURCES'] = str(out/'untrusted-resources')
            bound = binding.resolve(); executable = bound['executable']; pin = bound['expected_pin']
            check('binding derives fixed runtime location and exact compiled source lock', executable == resources/'engines/slides/bin/dobe-slides'
                  and pin == checked['manifest']['engine'] and binding.available())
            native = engine(); report = native.verify_project(portable, work/'verified')
            (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            check('JSON baseline and revision survive native encoding and three cold reopens', report['native_calls'] == 6
                  and report['baseline_model_equal'] and report['current_model_equal'] and report['native_cold_reopens'] == 3)
            check('source/history/resources remain exact', report['original_bytes_unchanged'] and report['resource_bytes_equal']
                  and all((work/'verified'/name).read_bytes() == value for name,value in checked['members'].items()))
            check('native comparison does not grant admission, render fidelity or publication', not any(report[key] for key in (
                'engine_admission_complete', 'source_format_fidelity_qualified', 'rendered_fidelity_qualified', 'durable_publication_qualified'))
                  and 'native-full-model-comparison' not in report['pending_qualification'] and 'complete-model-semantics' in report['pending_qualification'])
            original_project = project.create(original, 'deckcraft', engine=pin)
            original_report = engine().verify_project(original_project, work/'original')
            check('native original is independently reconstructed and directly cold opened', original_report['native_calls'] == 7 and original_report['original_native_model_equal']
                  and (work/'original/original.deckcraft').read_bytes() == original)
            check('native intermediates never enter portable checkout', not list(work.glob('.slides-observe-*'))
                  and len(list((work/'verified').iterdir())) == 4)
            refused('wrong receipt binary', lambda: engine(expected_binary_sha256='0'*64), 'differs from verified receipt')
            refused('wrong source revision', lambda: engine(expected_pin={**pin, 'source_revision': '0'*40}), 'differs from verified source pin')
            refused('wrong source lock', lambda: engine(expected_pin={**pin, 'source_lock_sha256': '0'*64}), 'differs from verified source pin')
            refused('invalid time budget', lambda: engine(seconds=float('inf')), 'time budget')
            refused('pre-cancelled attempt', lambda: engine(cancelled=lambda: True), 'cancelled')
            refused('existing checkout', lambda: native.verify_project(portable, work/'verified'), 'fresh destination')
            refused('outside checkout', lambda: native.verify_project(portable, out/'outside'), 'inside its attempt')
            alias = work/'alias'; alias.symlink_to(work/'verified', target_is_directory=True)
            refused('symlink checkout', lambda: native.verify_project(portable, alias/'child'), 'symbolic links')
            refused('stale model bytes', lambda: native.observe(work/'verified/document.json', checked['members']['baseline.json']), 'changed before observation')
            refused('external observed model', lambda: native.observe(args.project, checked['members']['document.json']), 'inside its attempt')
            refused('boolean reopen count', lambda: native.observe(work/'verified/document.json', checked['members']['document.json'], cold_reopens=True), 'reopen count')
            changed_manifest = copy.deepcopy(checked['manifest']); changed_manifest['engine']['source_revision'] = '0'*40
            foreign = project.pack(changed_manifest, {k:v for k,v in checked['members'].items() if k != 'project.json'})
            refused('foreign project pin', lambda: native.verify_project(foreign, work/'foreign'), 'pinned engine')
            check('foreign source refused before checkout', not (work/'foreign').exists())
            model = copy.deepcopy(checked['current']['document']); model['futureProperty'] = 'must not disappear'
            unknown = project.create(revision.encoded(model), 'json', engine=pin)
            refused('native silently discarded field', lambda: native.verify_project(unknown, work/'unknown'), 'changed the complete predicted model', 1)
            check('model mismatch removes only disposable directories', not (work/'unknown').exists() and not list(work.glob('.slides-observe-*'))
                  and (work/'verified/document.json').read_bytes() == checked['members']['document.json'])
            native.deadline = time.monotonic()-1
            refused('expired shared deadline', lambda: native.verify_project(portable, work/'expired'), 'timed out')
            check('expired attempt removes fresh checkout', not (work/'expired').exists())
            for label, mutate in [
                ('binary receipt mismatch', lambda m: m['files']['lib/dobe/engines/slides/bin/dobe-slides'].update(sha256='0'*64)),
                ('component source lock mismatch', lambda m: m['components'][0].update(source_lock_sha256='0'*64)),
                ('duplicate engine component', lambda m: m['components'].append(copy.deepcopy(m['components'][0]))),
                ('unqualified distribution platform', lambda m: m.update(platform='linux-x86_64'))]:
                damaged = json.loads(receipt_bytes); mutate(damaged); receipt.write_text(json.dumps(damaged))
                try: check(label+' is unavailable without any launch', not binding.available())
                finally: receipt.write_bytes(receipt_bytes)
            check('restored receipt resolves original binary', binding.resolve() == bound)
            copied = work/'copied-engine'; (copied/'bin').mkdir(parents=True); shutil.copy2(executable, copied/'bin/dobe-slides')
            shutil.copy2(executable.parent.parent/'engine.json', copied/'engine.json')
            changed = engine(executable=copied/'bin/dobe-slides')
            with (copied/'bin/dobe-slides').open('r+b') as stream:
                stream.seek(-1, os.SEEK_END); byte = stream.read(1); stream.seek(-1, os.SEEK_END); stream.write(bytes([byte[0]^1]))
            refused('binary mutation after receipt verification', lambda: changed.observe(work/'verified/document.json', checked['members']['document.json']), 'changed after receipt verification')
            large = copy.deepcopy(checked['current']['document'])
            text_shape = next(shape for shape in large['slides'][0]['shapes'] if shape.get('text'))
            text_shape['text']['paragraphs'] = [{'level':0, 'runs':[{'text':'x'*500}]} for _ in range(1000)]
            large_project = project.create(revision.encoded(large), 'json', engine=pin)
            cancellable = engine(); cancellable.cancelled = lambda: state['live']; state['cancel'] = True
            refused('cancel active native encoding', lambda: cancellable.verify_project(large_project, work/'cancelled'), 'cancelled', 1)
            state['cancel'] = False
            check('live native cancellation removes scratch and checkout', state['live'] and not (work/'cancelled').exists() and not list(work.glob('.slides-observe-*')))
            for child in children:
                check('native child '+str(child['pid'])+' reaped', child['process'].poll() is not None)
                try: os.killpg(child['pid'], 0)
                except ProcessLookupError: pass
                else: raise AssertionError('process group survived '+str(child['pid']))
            check('original project, native source and maintained executable remain exact', args.project.read_bytes() == portable
                  and args.native_source.read_bytes() == original and args.engine.read_bytes() == engine_bytes)
            evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(children), 'engine': pin,
                        'live_native_cancellation': state['live'], 'process_groups_gone': True, 'distribution_layout_fixture': True,
                        'installed_qualification': False, 'remote_actions': False, 'seconds': time.monotonic()-started,
                        'scope': 'receipt-bound complete native preservation of controlled projects; no public admission or durable operations'}
            (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
            print(json.dumps({'checks':len(checks), 'refusals':len(refusals), 'native_calls':len(children), 'passed':True}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error), 'checks':checks, 'refusals':refusals}, indent=2)+'\n'); raise
    finally:
        receipt.write_bytes(receipt_bytes)
        (out/'children.json').write_text(json.dumps([{k:v for k,v in child.items() if k != 'process'} | {'exit_code':child['process'].poll()} for child in children], indent=2)+'\n')


if __name__ == '__main__': main()
