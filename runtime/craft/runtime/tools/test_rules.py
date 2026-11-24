import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from studio_runtime import descriptors, mcp, rules
from studio_runtime.__main__ import main
from studio_runtime.store import Store

CREATE = {'width': 240, 'height': 80, 'objects': [
    {'name': 'label', 'type': 'text', 'x': 12, 'y': 48, 'text': 'Rules', 'size': 18, 'font': 'Inter', 'color': '#FFFFFF'}]}
WRITE_FILES = [
    {'path': 'native/project.dobewrite', 'role': 'native', 'sha256': 'a' * 64},
    {'path': 'native/document.json', 'role': 'native', 'sha256': 'b' * 64},
    {'path': 'exports/document.pdf', 'role': 'export', 'sha256': 'c' * 64},
]


class FakeStore:
    def __init__(self, head=None, files=(), keys=()):
        self.head, self.files, self.keys = head, list(files), set(keys)

    def has_job_key(self, workspace, project, key):
        return key in self.keys

    def get_project(self, workspace, project):
        return {'id': project, 'head': self.head}

    def get_revision(self, workspace, revision):
        return {'id': revision, 'project': 'p', 'files': self.files}


def check(store, operation, parameters, source=None, key='k'):
    with mock.patch.object(rules.capabilities, 'validate_for_project') as validate:
        rules.check_submit(store, 'local', 'p', operation, parameters, source, key)
    return validate


class RulesTest(unittest.TestCase):
    def violation(self, rule, *args, **kwargs):
        with self.assertRaises(rules.RuleViolation) as caught:
            check(*args, **kwargs)
        self.assertEqual(caught.exception.rule, rule)
        payload = caught.exception.payload()
        self.assertEqual(sorted(payload), ['details', 'error', 'fix', 'message', 'rule'])
        self.assertGreaterEqual(len(payload['fix']), 10)
        return payload

    def test_vocabulary_matches_descriptor_rules(self):
        described = rules.describe()
        self.assertEqual(described['schema_version'], 1)
        self.assertEqual([r['id'] for r in described['rules']], list(rules.RULE_IDS))
        for rule in described['rules']:
            self.assertEqual(sorted(rule), ['example', 'fix', 'id', 'summary'])
        used = {r for op in descriptors.describe_all()['operations'] for r in op['rules']}
        self.assertEqual(used, set(rules.RULE_IDS))
        self.assertEqual(json.dumps(described), json.dumps(described, sort_keys=True))

    def test_create_on_a_project_with_a_head_is_refused(self):
        payload = self.violation('one_create_per_project', FakeStore(head='h1'), 'vector.create', CREATE)
        self.assertEqual(payload['details'], {'head': 'h1'})
        check(FakeStore(), 'vector.create', CREATE)

    def test_missing_source_is_refused_before_validation(self):
        with mock.patch.object(rules.capabilities, 'validate_for_project') as validate:
            with self.assertRaises(rules.RuleViolation) as caught:
                rules.check_submit(FakeStore(head='h1'), 'local', 'p', 'vector.revise_text', {'text': {}}, None, 'k')
        self.assertEqual(caught.exception.rule, 'source_required')
        validate.assert_not_called()

    def test_stale_source_names_the_head(self):
        payload = self.violation('revise_from_head', FakeStore(head='h2'), 'vector.revise_text', {'text': {'label': 'x'}}, source='h1')
        self.assertEqual(payload['details']['head'], 'h2')
        check(FakeStore(head='h2'), 'vector.revise_text', {'text': {'label': 'x'}}, source='h2')

    def test_wrong_hash_gives_the_current_value(self):
        store = FakeStore(head='h1', files=WRITE_FILES)
        edit = {'expected_sha256': '0' * 64, 'edits': []}
        payload = self.violation('edit_requires_previous_hash', store, 'write.edit', edit, source='h1')
        self.assertEqual(payload['details'], {'parameter': 'expected_sha256', 'provided': '0' * 64, 'current': 'a' * 64})
        check(store, 'write.edit', {**edit, 'expected_sha256': 'a' * 64}, source='h1')

    def test_hash_is_left_to_the_engine_for_other_documents(self):
        files = [{'path': 'native/document.tcraft', 'role': 'native', 'sha256': 'a' * 64}]
        check(FakeStore(head='h1', files=files), 'texture.material', {'expected_sha256': '0' * 64}, source='h1')

    def test_repeated_key_skips_the_rules(self):
        validate = check(FakeStore(head='h2', keys={'k'}), 'vector.revise_text', {'text': {}}, source='h1')
        validate.assert_called_once()

    def test_native_document(self):
        self.assertEqual(rules.native_document({'files': WRITE_FILES}), {'path': 'native/project.dobewrite', 'sha256': 'a' * 64})
        two = WRITE_FILES + [{'path': 'native/original.input', 'role': 'native', 'sha256': 'd' * 64}]
        self.assertIsNone(rules.native_document({'files': two}))
        manifest = {'files': two}
        self.assertIs(rules.with_native_document(manifest), manifest)


def cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = main(list(args), product='dobe')
    return status, out.getvalue(), err.getvalue()


class RulesCliTest(unittest.TestCase):
    def test_rules_command_and_mcp_agree(self):
        status, out, _ = cli('--state', '/nonexistent/state', 'rules')
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out), rules.describe())
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(mcp.invoke(Store(root), 'studio_rules', {}), rules.describe())

    def test_submit_refusals_and_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as root:
            state = str(Path(root) / 'state')
            project = json.loads(cli('--state', state, 'create-project', 'Rules')[1])['id']
            edit = str(Path(root) / 'edit.json'); Path(edit).write_text(json.dumps({'text': {'label': 'x'}}))
            status, out, err = cli('--state', state, 'submit', project, 'vector.revise_text', '--parameters', edit, '--key', 'e')
            self.assertEqual((status, out), (1, ''))
            self.assertEqual(json.loads(err)['rule'], 'source_required')
            create = str(Path(root) / 'create.json'); Path(create).write_text(json.dumps(CREATE))
            first = cli('--state', state, 'submit', project, 'vector.create', '--parameters', create, '--key', 'c')
            self.assertEqual(first[0], 0, first[2])
            again = cli('--state', state, 'submit', project, 'vector.create', '--parameters', create, '--key', 'c')
            self.assertEqual(json.loads(again[1])['id'], json.loads(first[1])['id'])
            store = Store(state)
            with mock.patch.object(store, 'get_project', return_value={'id': project, 'head': 'h1'}):
                with self.assertRaises(rules.RuleViolation) as caught:
                    mcp.invoke(store, 'studio_submit_job', {'project': project, 'operation': 'vector.create',
                                                            'parameters': CREATE, 'idempotency_key': 'c2'})
            self.assertEqual(caught.exception.rule, 'one_create_per_project')


if __name__ == '__main__':
    unittest.main()
