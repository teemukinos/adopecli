"""Accounting gate checks; failures and incomplete samples cannot pass."""
import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from agent_report import compare, WORKFLOWS, ARMS, atomic_text


def fixture():
    return [{'workflow': w, 'pair': pair, 'arm': arm, 'state': 'completed',
             'coding_tokens': 1000 if arm == 'baseline' else 400,
             'observed_cache_usd': .1 if arm == 'baseline' else .04,
             'uncached_normalized_usd': .1 if arm == 'baseline' else .04,
             'uncertain_reserved_usd': 0, 'local_cost_assumption_usd': .01}
            for w in WORKFLOWS for pair in (1, 2) for arm in ARMS]


class ComparisonTests(unittest.TestCase):
    def test_report_keeps_job_submitted_before_its_step_link_was_saved(self):
        from studio_runtime.store import Store
        from studio_runtime.agent_store import Journal
        from studio_runtime.agent import specification
        from agent_benchmark import report
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);store=Store(root/'state');journal=Journal(store)
            project=store.create_project('local','Accounting crash fixture')['id']
            status=journal.create(project,specification('Synthetic fixture.','image'),1);run=status['id']
            params={'width':64,'height':64,'background':'#FFFFFF','layers':[{'name':'fill','type':'solid','color':'#FFFFFF'}]}
            job=store.submit('local',project,'image.create',params,'agent-'+run+'-1',None,7200)
            registry={'budget':status['budget'],'runs':[{'run':run,'project':project,'workflow':'image','pair':1,'arm':'baseline'}]}
            result=report(store,journal,registry,root)
            self.assertEqual(len(result['runs'][0]['jobs']),1)
            saved=result['runs'][0]['jobs'][0]
            self.assertEqual(saved['id'],job['id'])
            self.assertTrue(saved['recovered_from_idempotency_key'])
            self.assertIsNone(saved['agent_step'])

    def test_partial_write_and_alias_preserve_existing_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'report.json'
            atomic_text(path, 'original')
            with patch('agent_report.os.fsync', side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError):atomic_text(path, 'replacement')
            self.assertEqual(path.read_text(), 'original')
            self.assertEqual(list(path.parent.iterdir()), [path])
            alias = path.with_name('alias.json'); alias.symlink_to(path)
            with self.assertRaises(ValueError):atomic_text(alias, 'replacement')
            self.assertEqual(path.read_text(), 'original')

    def test_complete_paired_fixture_passes_numerical_gates(self):
        self.assertTrue(all(compare(fixture())['gates'].values()))

    def test_missing_and_duplicate_pairs_cannot_pass(self):
        rows = fixture()
        self.assertFalse(compare(rows[:-1])['gates']['two_pairs_each_workflow'])
        rows[-1] = copy.deepcopy(rows[-2])
        result = compare(rows)
        self.assertFalse(result['gates']['two_pairs_each_workflow'])
        self.assertTrue(result['duplicate_pair_entries'])

    def test_failed_attempts_keep_tokens_and_cost(self):
        rows = fixture(); rows[1].update(state='failed', coding_tokens=4000, observed_cache_usd=4)
        result = compare(rows)
        self.assertFalse(result['gates']['all_runs_completed'])
        self.assertFalse(result['gates']['no_workflow_mean_token_increase'])
        self.assertFalse(result['gates']['mean_production_cost_does_not_increase'])
        self.assertEqual(result['workflows']['image']['optimized']['coding_tokens'], 4400)

    def test_unknown_charge_or_missing_local_measurement_never_zero(self):
        for field, value in (('uncertain_reserved_usd', .4), ('local_cost_assumption_usd', None)):
            rows = fixture(); rows[1][field] = value
            result = compare(rows)
            self.assertIsNone(result['mean_production_usd']['optimized'])
            self.assertFalse(result['gates']['mean_production_cost_does_not_increase'])


if __name__ == '__main__':
    unittest.main()
