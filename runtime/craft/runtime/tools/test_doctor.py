import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from studio_runtime import doctor

RUNTIME = Path(__file__).resolve().parents[1]
DENY = '(version 1)(allow default)(deny network*)'


def run_doctor(state, sandbox=None, env=None):
    command = [sys.executable, '-I', '-B', '-c',
               'import sys; sys.path.insert(0, sys.argv[1]); from studio_runtime.__main__ import main; '
               'sys.exit(main(sys.argv[2:], product="dobe"))', str(RUNTIME), '--state', str(state), 'doctor']
    if sandbox:
        command = ['/usr/bin/sandbox-exec', '-p', sandbox, *command]
    return subprocess.run(command, capture_output=True, text=True, env=env or {'PATH': '/usr/bin:/bin'}, timeout=60)


class DoctorTest(unittest.TestCase):
    def test_report_shape_and_state(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / 'nested' / 'state'
            result = doctor.report(state)
            self.assertEqual(sorted(result), ['advice', 'engines', 'network_denied', 'sandboxed', 'schema_version',
                                              'state_dir', 'state_writable'])
            self.assertEqual(result['schema_version'], 1)
            self.assertIs(result['sandboxed'], False)
            self.assertEqual(result['state_dir'], os.path.abspath(state))
            self.assertIs(result['state_writable'], True)
            self.assertEqual(sorted(result['engines']), sorted(doctor.FAMILIES))
            self.assertEqual(len(doctor.FAMILIES), 17)
            self.assertEqual(list(state.iterdir()), [], 'the writability probe leaves no file')

    def test_unwritable_state_gives_advice(self):
        with tempfile.TemporaryDirectory() as root:
            blocker = Path(root) / 'file'
            blocker.write_text('PROBE')
            result = doctor.report(blocker / 'state')
            self.assertIs(result['state_writable'], False)
            self.assertTrue(any('not writable' in line for line in result['advice']))

    def test_engines_come_from_bundle_resources(self):
        with tempfile.TemporaryDirectory() as root:
            for family in doctor.FAMILIES:
                binary = Path(root) / 'engines' / family / 'bin' / ('dobe-' + family)
                binary.parent.mkdir(parents=True)
                binary.write_text('#!/bin/sh\n')
                binary.chmod(0o755 if family != 'cad' else 0o644)
            with mock.patch.dict(os.environ, {'STUDIO_BUNDLE_RESOURCES': root, 'PATH': '/usr/bin:/bin'}):
                engines = {family: doctor.engine_present(family) for family in doctor.FAMILIES}
                result = doctor.report(Path(root) / 'state')
        self.assertIs(engines['cad'], False, 'a binary that is not executable does not count')
        self.assertTrue(all(present for family, present in engines.items() if family != 'cad'))
        self.assertEqual([line for line in result['advice'] if 'Engines missing' in line],
                         ['Engines missing or not executable: cad. Reinstall the package, or run scripts/setup in a source checkout.'])

    def test_network_denied_follows_the_sandbox(self):
        with tempfile.TemporaryDirectory() as root:
            denied = run_doctor(Path(root) / 'a', sandbox=DENY)
            self.assertEqual(denied.returncode, 0, denied.stderr)
            self.assertIs(json.loads(denied.stdout)['network_denied'], True)
            open_net = run_doctor(Path(root) / 'b')
            self.assertEqual(open_net.returncode, 0, open_net.stderr)
            report = json.loads(open_net.stdout)
            self.assertIs(report['network_denied'], False)
            self.assertTrue(any('Network access is not denied' in line for line in report['advice']))

    def test_doctor_text_avoids_internal_name(self):
        with tempfile.TemporaryDirectory() as root:
            text = json.dumps(doctor.report(Path(root) / 'state')).lower()
        self.assertNotIn('dobe', text)


if __name__ == '__main__':
    unittest.main()
