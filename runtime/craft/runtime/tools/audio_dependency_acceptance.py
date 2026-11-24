"""Qualify missing media and unsupported plugin refusals on an installed package.

Creates only synthetic audio and private state. Each collection runs once.
Verification reads ended evidence and never repeats native jobs. No network,
editor, plugin loading, global configuration or direct application database writes.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import time
import wave


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in folder.rglob('*') if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--expect-verification', required=True, type=Path)
    parser.add_argument('--stage', required=True, choices=['collect', 'verify'])
    args = parser.parse_args()
    package, out = args.package.resolve(strict=True), args.output.absolute()
    out.mkdir(mode=0o700, exist_ok=args.stage == 'verify')
    lock = (out / 'fixture.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = out / 'state'
    env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
    cases, commands, jobs = [], [], []

    def save(name, value):
        p = out / (name + '.tmp')
        p.write_text(json.dumps(value, indent=2) + '\n')
        p.replace(out / name)

    def check(value, label):
        if not value:
            raise AssertionError(label)
        cases.append(label)
        save(args.stage + '-cases.json', cases)

    def command(label, arguments):
        start = time.monotonic()
        process = subprocess.run(list(map(str, arguments)), env=env, stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=180)
        commands.append({'label': label, 'command': list(map(str, arguments)), 'exit': process.returncode,
                         'stdout': process.stdout, 'stderr': process.stderr, 'seconds': time.monotonic() - start})
        save(args.stage + '-commands.json', commands)
        if process.returncode:
            raise AssertionError((label, process.returncode, process.stderr))
        return json.loads(process.stdout) if process.stdout.strip() else None

    def cli(label, *arguments):
        return command(label, [package / 'bin/a-dope-cli', '--state', state, *arguments])

    def receipt(folder):
        result = json.loads((folder / 'project.json').read_text())
        for item in result['files']:
            p = folder / item['path']
            if p.stat().st_size != item['bytes'] or sha(p) != item['sha256']:
                raise AssertionError('changed receipt: ' + item['path'])
        return result

    def job(label, project, operation, parameters, source=None, expected_error=None):
        save(label + '-request.json', parameters)
        arguments = ['submit', project, operation, '--parameters', out / (label + '-request.json'),
                     '--key', label, '--timeout', '60']
        if source:
            arguments += ['--source', source]
        submitted = cli(label + ' submit', *arguments)
        item = {'label': label, 'id': submitted['id'], 'project': project, 'operation': operation,
                'parameters': parameters, 'source': source}
        jobs.append(item)
        save('jobs.json', jobs)
        cli(label + ' worker', 'worker', '--once')
        result = cli(label + ' result', 'job', submitted['id'])
        item['result'] = result
        save('jobs.json', jobs)
        check(result['attempt'] == 1, label + ' uses exactly one bounded attempt')
        if expected_error is not None:
            check(result['state'] == 'failed' and result['result_revision'] is None,
                  label + ' fails without publishing an edit revision')
            check(result['error']['code'] == 'engine_failure'
                  and expected_error in result['error']['message'], label + ' reports the expected dependency refusal')
            check(cli(label + ' head', 'project', project)['head'] == source,
                  label + ' leaves the imported project head unchanged')
            return result
        check(result['state'] == 'succeeded', label + ' succeeds')
        folder = out / label
        cli(label + ' checkout', 'checkout', result['result_revision'], folder)
        v = receipt(folder)['validation']
        check(v['native_cold_reopen'] and v['native_state_equal']
              and v['editable_audio_unchanged_on_reopen'] and v['source_audio_hashes_preserved'],
              label + ' validates complete editable state and source audio through cold reopening')
        return folder

    verification = command('verify package', [package / 'bin/a-dope-guard', 'verify'])
    check(verification == json.loads(args.expect_verification.read_text()) and verification['verified'],
          'exact expected package seal and guard verify')
    if args.stage == 'collect':
        (out / 'home').mkdir()
        source = out / 'source.wav'
        with wave.open(str(source), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(48000)
            audio.writeframes(b''.join(struct.pack('<h', 4096 if i % 48 < 24 else -4096) for i in range(4800)))
        project = cli('create control project', 'create-project', 'Audio dependency control')['id']
        asset = cli('import control source', 'import-asset', project, source)['id']
        control = job('control', project, 'audio.create', {'sample_rate': 48000, 'frames': 4800,
            'tracks': [{'name': 'track', 'clips': [{'name': 'clip', 'asset': asset, 'start': 0, 'frames': 4800}]}]})
        original = inventory(control)
        model = json.loads((control / 'native/document.scraft').read_text())
        check(len(model['sources']) == 1, 'control has one explicit packaged source dependency')
        missing_path = 'native/' + model['sources'][0]['path']
        requests = []
        for label in ('missing-media', 'unavailable-plugin'):
            folder = out / (label + '-input')
            shutil.copytree(control, folder)
            manifest = receipt(folder)
            if label == 'missing-media':
                (folder / missing_path).unlink()
                manifest['files'] = [f for f in manifest['files'] if f['path'] != missing_path]
                expected = 'No such file or directory'
            else:
                document = json.loads((folder / 'native/document.scraft').read_text())
                document['tracks'][0]['mixer']['inserts'][0] = {'fixture_unavailable_plugin': True}
                path = folder / 'native/document.scraft'
                path.write_text(json.dumps(document, sort_keys=True) + '\n')
                entry = next(f for f in manifest['files'] if f['path'] == 'native/document.scraft')
                entry.update(bytes=path.stat().st_size, sha256=sha(path))
                expected = 'native audio contains unsupported mixer routing, automation or plugins'
            (folder / 'project.json').write_text(json.dumps(manifest, indent=2) + '\n')
            receipt(folder)
            before = inventory(folder)
            imported = cli(label + ' import', 'import-project', folder, label)
            check(not imported['revision']['validation']['native_cold_reopen'],
                  label + ' import claims integrity only before dependency validation')
            result = job(label, imported['project']['id'], 'audio.edit',
                         {'edits': [{'type': 'clip', 'name': 'clip', 'gain_db': -3}]},
                         imported['revision']['id'], expected)
            if label == 'missing-media':
                check(Path(missing_path).name in result['error']['message'],
                      'missing-media diagnostic identifies the missing native WAV')
            check(inventory(folder) == before, label + ' refusal leaves the complete input bundle unchanged')
            requests.append({'label': label, 'input': before, 'import': imported,
                             'error': result['error'], 'refusal_stage': 'worker dependency admission'})
        # Repair the actual missing-media bundle, not a different substitute source.
        repaired = out / 'repaired-input'
        shutil.copytree(out / 'missing-media-input', repaired)
        shutil.copy2(control / missing_path, repaired / missing_path)
        shutil.copy2(control / 'project.json', repaired / 'project.json')
        check(inventory(repaired) == original, 'restoring the missing dependency restores the exact original portable bundle')
        imported = cli('repaired import', 'import-project', repaired, 'Repaired dependency')
        job('repaired', imported['project']['id'], 'audio.edit',
            {'edits': [{'type': 'clip', 'name': 'clip', 'gain_db': 0}]}, imported['revision']['id'])
        save('collection.json', {'passed': True, 'checks': len(cases), 'control': original,
                                'source_sha256': sha(source), 'refusals': requests, 'verification': verification})
    else:
        collection = json.loads((out / 'collection.json').read_text())
        jobs = json.loads((out / 'jobs.json').read_text())
        check(collection['passed'] and len(jobs) == 4, 'four ended Audio jobs are retained')
        check(inventory(out / 'control') == collection['control']
              and sha(out / 'source.wav') == collection['source_sha256'], 'all original control artifacts and source bytes remain unchanged')
        for item in collection['refusals']:
            check(inventory(out / (item['label'] + '-input')) == item['input'], item['label'] + ' input remains unchanged')
        control, repaired = out / 'control', out / 'repaired'
        for folder in (control, repaired):
            receipt(folder)
        check(json.loads((control / 'native/document.scraft').read_text())
              == json.loads((repaired / 'native/document.scraft').read_text()),
              'repaired project retains the complete original editable model')
        check((control / 'exports/document.wav').read_bytes() == (repaired / 'exports/document.wav').read_bytes(),
              'native repair reopens and delivers byte-identical original WAV, including PCM')
        check(inventory(control / 'native/Audio Files') == inventory(repaired / 'native/Audio Files'),
              'repair preserves exact packaged media bytes')
        database = state / 'studio.sqlite3'
        check(not Path(str(database) + '-wal').exists(), 'ended journal has no pending WAL')
        before = sha(database)
        snapshot = out / 'journal-snapshot.sqlite3'
        snapshot.write_bytes(database.read_bytes())
        with sqlite3.connect(snapshot.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            db.row_factory = sqlite3.Row
            check(tuple(db.execute('PRAGMA quick_check').fetchone()) == ('ok',), 'journal integrity passes')
            tables = {name: [dict(row) for row in db.execute('SELECT * FROM ' + name)]
                      for name in ('jobs', 'revisions', 'projects', 'attempts', 'attempt_executions')}
        check(sha(database) == before == sha(snapshot), 'read-only snapshot leaves original journal bytes unchanged')
        save('journal.json', {'sha256': before, 'tables': tables})
        actual = {job['id']: job for job in tables['jobs']}
        transfers = [job for job in actual.values() if job['operation'] == 'project.import']
        check(len(actual) == 7 and len(transfers) == 3 and
              all(job['state'] == 'succeeded' and job['attempt'] == 0 for job in transfers),
              'three separate project imports retain integrity-only records without native attempts')
        for item in jobs:
            job_record = actual[item['id']]
            check(job_record['state'] == item['result']['state'] and job_record['attempt'] == 1,
                  item['label'] + ' terminal state and single attempt agree with durable journal')
            if job_record['state'] == 'failed':
                check(not any(revision['job'] == item['id'] for revision in tables['revisions']),
                      item['label'] + ' has no published revision in the journal')
        groups = [entry['process_group'] for entry in tables['attempt_executions']]
        check(len(groups) == len(set(groups)) == 4 and all(groups), 'four attempt process groups are recorded')
        for group in groups:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('owned attempt group remains: ' + str(group))
        check(True, 'all attempt process groups are absent')
        check(command('verify package after', [package / 'bin/a-dope-guard', 'verify']) == verification,
              'complete sealed package remains unchanged')
        save('evidence.json', {'passed': True, 'collection_checks': collection['checks'],
             'verification_checks': len(cases), 'audio_jobs': 4, 'successful_audio_jobs': 2,
             'expected_refused_audio_jobs': 2, 'integrity_only_imports': 3,
             'groups': groups, 'all_groups_absent': True, 'verification': verification,
             'production_code_changed': False, 'plugin_support_qualified': False,
             'listening_approval': False, 'linux_cloud_qualified': False, 'full_release_qualified': False})
    print(json.dumps({'stage': args.stage, 'passed': True, 'checks': len(cases)}))


if __name__ == '__main__':
    main()
