import re
import unittest

from studio_runtime import mcp

WORKFLOW = ['dope_capabilities', 'dope_describe_operation', 'dope_create_project',
            'dope_submit_job', 'dope_get_job', 'dope_export_project']
WORKER_CHORE = re.compile(r'separate\w*\W+(?:\w+\W+){0,3}worker|run\W+(?:the\W+)?(?:local\W+)?dope\W+worker', re.I)


class CheckoutInstructions(unittest.TestCase):
    """In a source checkout, submitting starts the worker; the agent must not be told to run one."""

    def test_instructions_walk_the_workflow_in_order(self):
        text = mcp.instructions('dope', 'dope', starts_worker=True)
        positions = [text.find(name) for name in WORKFLOW]
        self.assertTrue(all(p >= 0 for p in positions), positions)
        self.assertEqual(positions, sorted(positions))
        self.assertIn('succeeded', text)
        self.assertIn('result_revision', text)
        self.assertIsNone(WORKER_CHORE.search(text))

    def test_no_tool_asks_for_a_separate_worker(self):
        tools = mcp.public_tools_for('dobe', starts_worker=True)
        self.assertEqual([t['name'] for t in tools if WORKER_CHORE.search(t['description'])], [])
        self.assertTrue(all(t['description'].strip() for t in tools))
        names = {t['name'] for t in tools}
        self.assertTrue(set(WORKFLOW) <= names, set(WORKFLOW) - names)

    def test_supervised_runtime_keeps_its_separate_worker_text(self):
        self.assertIn('worker separately', mcp.instructions('studio', 'Studio', starts_worker=False))
        submit = next(t for t in mcp.public_tools_for('studio', starts_worker=False) if t['name'] == 'studio_submit_job')
        self.assertIn('separate Studio worker', submit['description'])


if __name__ == '__main__':
    unittest.main()
