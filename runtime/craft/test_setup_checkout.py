#!/usr/bin/env python3
"""Unit tests for what setup shows when an engine fails to build.

Run from the repository root:  .venv/bin/python -B runtime/craft/test_setup_checkout.py
"""
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_checkout  # noqa: E402

TRACEBACK = '''Traceback (most recent call last):
  File "build_engine.py", line 146, in main
    subprocess.run(command, cwd=source, env=env, stdout=stream, stderr=diagnostics, check=True)
subprocess.CalledProcessError: Command '['/toolchain/bin/cargo', 'build']' returned non-zero exit status 101.
'''
COMPILER = '''   Compiling soundcraft-core v0.20.1
error[E0425]: cannot find value `gain` in this scope
  --> crates/core/src/mix.rs:12:5
error: could not compile `soundcraft-core` (lib) due to 1 previous error
'''


class FailureDisplay(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.setup_log = self.root / '.build/audio.log'
        self.compiler_log = self.root / '.build/out/audio/build.log'
        self.compiler_log.parent.mkdir(parents=True)
        self.setup_log.write_text(TRACEBACK)

    def shown(self, error):
        stream = io.StringIO()
        saved, setup_checkout.out = setup_checkout.out, setup_checkout.Output(stream)
        try:
            setup_checkout.show_failure(error, self.root)
        finally:
            setup_checkout.out = saved
        return stream.getvalue()

    def test_compiler_log_is_shown_when_cargo_failed(self):
        self.compiler_log.write_text(COMPILER)
        log, more = setup_checkout.failure_logs(self.setup_log, self.compiler_log)
        self.assertEqual((log, more), (self.compiler_log, self.setup_log))
        text = self.shown(setup_checkout.SetupError('the audio engine failed to build', log, more))
        self.assertIn('error[E0425]: cannot find value `gain` in this scope', text)
        self.assertIn('Last lines of .build/out/audio/build.log:', text)
        self.assertIn('More detail: .build/audio.log', text)
        self.assertNotIn('Traceback', text)
        self.assertIn('run scripts/setup again', text)

    def test_setup_log_is_shown_when_cargo_never_ran(self):
        self.setup_log.write_text('ValueError: engine patch checksum mismatch\n')
        log, more = setup_checkout.failure_logs(self.setup_log, self.compiler_log)
        self.assertEqual((log, more), (self.setup_log, None))
        self.assertIn('engine patch checksum mismatch', self.shown(setup_checkout.SetupError('failed', log, more)))

    def test_first_error_line_is_kept_above_a_long_tail(self):
        self.compiler_log.write_text('error: the first cause\n' + ''.join(f'note: line {n}\n' for n in range(40)))
        lines = setup_checkout.last_lines(self.compiler_log)
        self.assertEqual(lines[:2], ['error: the first cause', '...'])
        self.assertEqual(lines[-1], 'note: line 39')


if __name__ == '__main__':
    unittest.main()
