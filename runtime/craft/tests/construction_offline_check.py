"""Exercise inherited offline execution and standalone refusal on macOS.

Run directly, outside an additional sandbox: individual cases establish their
own real OS policies. No remote address, model service or creative engine runs.
"""
import errno
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUNTIME = Path(__file__).resolve().parents[1] / 'runtime'
sys.path.insert(0, str(RUNTIME))
from studio_runtime import offline, construction, construction_support, production


def network_probe():
    results = []
    for family, kind, address in ((socket.AF_INET, socket.SOCK_STREAM, ('127.0.0.1', 9)),
                                  (socket.AF_INET6, socket.SOCK_STREAM, ('::1', 9)),
                                  (socket.AF_INET, socket.SOCK_DGRAM, ('127.0.0.1', 9))):
        connection = None
        try:
            connection = socket.socket(family, kind)
            connection.settimeout(.5)
            if kind == socket.SOCK_DGRAM:
                connection.sendto(b'offline-boundary-probe', address)
            else:
                connection.connect(address)
        except OSError as error:
            if error.errno != errno.EPERM:
                raise AssertionError('Expected OS denial, received errno ' + str(error.errno))
            results.append({'family': int(family), 'kind': int(kind), 'errno': error.errno})
        else:
            raise AssertionError('Offline boundary permitted loopback network access')
        finally:
            if connection is not None:
                connection.close()
    print(json.dumps({'denied': results}))


def child(mode, directory):
    directory = Path(directory)
    argv = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--network-probe']
    def invoke():
        if mode.endswith('production'):
            (directory/'logs').mkdir(exist_ok=True)
            production.measured_run(directory, argv, 'network-probe')
        else:
            construction_support.run(directory, argv, 'network-probe')
        result = json.loads((directory/'logs/network-probe.log').read_text())
        assert len(result['denied']) == 3
        print(json.dumps({'passed': True, 'inherited': offline.inherited()}))
    if mode.startswith('inherited'):
        with offline.trusted_scope():
            invoke()
    else:
        invoke()


@unittest.skipUnless(sys.platform == 'darwin', 'macOS offline boundary')
class OfflineBoundary(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='construction-offline-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def launch(self, mode, policy=None, env=None):
        command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--child', mode, str(self.root)]
        if policy is not None:
            command = ['/usr/bin/sandbox-exec', '-p', policy, *command]
        return subprocess.run(command, capture_output=True, text=True, timeout=20,
                              env={**os.environ, **(env or {})}, stdin=subprocess.DEVNULL)

    def test_standalone_support_establishes_real_denial(self):
        result = self.launch('standalone-support', env={'DOBE_CONSTRUCTION_OFFLINE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['inherited'])

    def test_inherited_support_does_not_reapply_sandbox(self):
        result = self.launch('inherited-support', offline.PROFILE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['inherited'])

    def test_standalone_production_establishes_real_denial(self):
        result = self.launch('standalone-production', env={'DOBE_CONSTRUCTION_OFFLINE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inherited_production_does_not_reapply_sandbox(self):
        result = self.launch('inherited-production', offline.PROFILE)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_untrusted_partial_policy_refuses_without_fallback(self):
        policy = '(version 1)(allow default)(deny network*)(allow network-outbound (remote ip "localhost:9"))'
        result = self.launch('standalone-support', policy, {'DOBE_CONSTRUCTION_OFFLINE': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sandbox_apply: Operation not permitted', result.stderr)
        self.assertNotIn('"denied"', (self.root/'logs/network-probe.log').read_text())

    def test_environment_cannot_bypass_construction_wrapper(self):
        with mock.patch.dict(os.environ, {'DOBE_CONSTRUCTION_OFFLINE': '1'}), \
             mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, b'', b'boundary refusal')) as run:
            with self.assertRaisesRegex(ValueError, 'Offline construction failed: boundary refusal'):
                construction.execute(self.root, 'construct.inspect', {})
        self.assertEqual(run.call_args.args[0][:3], ['/usr/bin/sandbox-exec', '-p', offline.PROFILE])
        self.assertFalse((self.root/'construction').exists())

    def test_scope_restores_on_nested_exception(self):
        self.assertFalse(offline.inherited())
        with self.assertRaisesRegex(RuntimeError, 'scope failure'):
            with offline.trusted_scope():
                with offline.trusted_scope():
                    self.assertTrue(offline.inherited())
                self.assertTrue(offline.inherited())
                raise RuntimeError('scope failure')
        self.assertFalse(offline.inherited())

    def test_owned_admission_protocol(self):
        for admission in (b'1', b'O', b'', b'X'):
            with self.subTest(admission=admission):
                read_gate, write_gate = os.pipe()
                try:
                    if admission:
                        os.write(write_gate, admission)
                    os.close(write_gate)
                    result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                        '--admission-probe', str(self.root), str(read_gate)], pass_fds=(read_gate,),
                        capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
                        env={**os.environ, 'DOBE_CONSTRUCTION_OFFLINE': '1'})
                finally:
                    os.close(read_gate)
                if admission in (b'1', b'O'):
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['inherited'], admission == b'O')
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('execution was not admitted', result.stderr)
                    self.assertEqual(result.stdout, '')

    def test_scope_source_is_bound_to_adapter_receipts(self):
        self.assertIn('offline.py', construction.adapter_fingerprints())
        self.assertIn('offline.py', production.fingerprints())
        self.assertIn('construction_support.py', production.fingerprints())


if __name__ == '__main__':
    if sys.argv[1:2] == ['--network-probe']:
        network_probe()
    elif sys.argv[1:2] == ['--child']:
        child(*sys.argv[2:])
    elif sys.argv[1:2] == ['--admission-probe']:
        root, gate = sys.argv[2:]
        sys.argv = [str(RUNTIME/'studio_runtime/attempt_boot.py'), root, str(os.getppid()), gate]
        def observe(module, **kwargs):
            assert module == 'studio_runtime.engine_job'
            print(json.dumps({'inherited': offline.inherited()}))
        with mock.patch.object(runpy, 'run_module', side_effect=observe):
            runpy.run_path(sys.argv[0], run_name='__main__')
    else:
        unittest.main()
