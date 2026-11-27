import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from studio_runtime import __main__ as cli


def run(argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with redirect_stdout(out), redirect_stderr(err), mock.patch('sys.stdin', io.StringIO(stdin or '')):
        try:
            code = cli.main(argv, product='dobe')
        except SystemExit as exit:
            code = exit.code
    return code, out.getvalue(), err.getvalue()


def mentions(text, name):
    return re.search(rf'(^|[^a-z-]){re.escape(name)}([^a-z-]|$)', text, re.M) is not None


class HelpTest(unittest.TestCase):
    def test_top_level_help_lists_user_commands_only(self):
        code, out, _ = run(['--help'])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('usage: dope '))
        listed = re.search(r'\{([a-z0-9,-]+)\}', out).group(1).split(',')
        self.assertEqual(listed, list(cli.USER_COMMANDS))
        body = out.replace('usage:', '')
        self.assertEqual([c for c in cli.ADVANCED_COMMANDS if mentions(body, c)], [])
        self.assertNotIn('dobe', out.lower())

    def test_help_command_matches_top_level_help(self):
        self.assertEqual(run(['help'])[:2], run(['--help'])[:2])
        code, out, _ = run(['help', 'submit'])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('usage: dope submit '))
        self.assertNotEqual(run(['help', 'no-such-topic'])[0], 0)

    def test_every_listed_command_has_help(self):
        code, out, _ = run(['help'])
        listed = re.search(r'\{([a-z,\-]+)\}', out).group(1).split(',')
        self.assertIn('help', listed)
        for name in listed:
            code, text, _ = run(['help', name])
            self.assertEqual(code, 0, name)
            self.assertTrue(text.startswith(f'usage: dope {name}'), name)

    def test_help_advanced_lists_every_advanced_command(self):
        code, out, _ = run(['help', 'advanced'])
        self.assertEqual(code, 0)
        for name in cli.ADVANCED_COMMANDS:
            self.assertTrue(mentions(out, name), name)
            self.assertEqual(run([name, '--help'])[0], 0, name)
        self.assertNotIn('dobe', out.lower())

    def test_every_command_is_user_or_advanced(self):
        self.assertEqual(set(cli.USER_COMMANDS) & set(cli.ADVANCED_COMMANDS), set())
        for name in [*cli.USER_COMMANDS, *cli.ADVANCED_COMMANDS]:
            code, out, _ = run([name, '--help'])
            self.assertEqual(code, 0, name)
            self.assertTrue(out.startswith(f'usage: dope {name}'), name)

    def test_argument_errors_use_the_dope_prog(self):
        code, _, err = run(['submit'])
        self.assertEqual(code, 2)
        self.assertIn('usage: dope submit', err)


class ParametersTest(unittest.TestCase):
    PARAMETERS = {'text': {'label': 'Inline PROBE'}}

    def submitted(self, value, stdin=None):
        with tempfile.TemporaryDirectory() as state, \
                mock.patch('studio_runtime.rules.check_submit'), \
                mock.patch('studio_runtime.store.Store.submit', return_value={'id': 'job'}) as submit:
            code, out, err = run(['--state', state, 'submit', 'p', 'vector.revise_text',
                                  '--parameters', value, '--key', 'k', '--source', 'r'], stdin)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out), {'id': 'job'})
        return submit.call_args.args[3]

    def test_file_inline_and_stdin_submit_the_same_parameters(self):
        text = json.dumps(self.PARAMETERS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'parameters.json'
            path.write_text(text)
            self.assertEqual(self.submitted(str(path)), self.PARAMETERS)
        self.assertEqual(self.submitted(text), self.PARAMETERS)
        self.assertEqual(self.submitted(' ' + text), self.PARAMETERS)
        self.assertEqual(self.submitted('-', stdin=text), self.PARAMETERS)

    def test_bad_inline_json_is_a_json_error(self):
        with tempfile.TemporaryDirectory() as state:
            code, _, err = run(['--state', state, 'submit', 'p', 'vector.revise_text',
                                '--parameters', '{not json', '--key', 'k'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)['error'], 'JSONDecodeError')


if __name__ == '__main__':
    unittest.main()
