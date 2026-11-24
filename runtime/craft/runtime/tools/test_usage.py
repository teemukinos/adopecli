"""Usage accounting and OCR integration contracts. No provider calls or network."""
import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from studio_runtime import usage, native_ocr, mcp, erasure
from studio_runtime.__main__ import main
from studio_runtime.agent import Coordinator, specification
from studio_runtime.agent_store import Journal
from studio_runtime.store import Store, Conflict, NotFound


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.store = Store(Path(self.folder.name) / 'state')
        self.project = self.store.create_project('local', 'usage test')['id']
        self.start('baseline'); self.start('candidate')

    def start(self, key, **kwargs):
        return usage.start(self.store, 'local', self.project, key, kwargs.pop('scope', 'production'), 'same-brief', 'same-quality', **kwargs)

    def record(self, key, count=100, **extra):
        entry = dict(id=key, source='external:assistant', domain='assistant', evidence='fixture:call',
                     tokens={'input_tokens': count, 'output_tokens': 20, 'cached_input_tokens': 10, 'reasoning_tokens': 5},
                     cost_microusd=count * 10, cost_basis='usage_priced')
        entry.update(extra)
        return usage.record(self.store, 'local', self.project, key, entry)

    def receipt(self, key='candidate', **kwargs):
        return usage.receipt(self.store, 'local', self.project, key, **kwargs)

    def assess(self, key, quality='pass'):
        return usage.assess(self.store, 'local', self.project, key, quality, 'fixture:blind-review',
                            {'assistant': 'complete', 'generation': 'not_used', 'compute': 'not_used'})

    def png(self, color='white'):
        output = io.BytesIO(); Image.new('RGB', (320, 100), color).save(output, format='PNG'); return output.getvalue()

    def test_idempotency_and_tenant_isolation(self):
        first = self.record('candidate'); self.assertEqual(first, self.record('candidate'))
        self.assertEqual(self.receipt()['entries'], 1)
        with self.assertRaises(Conflict): self.record('candidate', count=101)
        with self.assertRaises(Conflict): self.record('baseline', id='candidate')
        with self.assertRaises(Conflict): self.start('candidate', scope='development')
        with self.assertRaises(NotFound): usage.receipt(self.store, 'another-workspace', self.project)
        other = self.store.create_project('local', 'other')['id']
        with self.assertRaises(NotFound): self.store.submit('local', other, 'image.create', {}, 'key', usage_workflow='candidate')

    def test_invalid_usage_is_not_accounted(self):
        for value in (-1, True, 1.2, float('nan')):
            with self.assertRaises(ValueError): self.record('candidate', cost_microusd=value)
        with self.assertRaises(ValueError): self.record('candidate', tokens={'input_tokens': 1, 'output_tokens': 2, 'reasoning_tokens': 3})
        with self.assertRaises(ValueError): self.record('candidate', cost_microusd=None)
        with self.assertRaises(ValueError): self.record('candidate', source='runtime:agent')
        self.assertEqual(self.receipt()['entries'], 0)

    def test_unknown_and_quoted_are_not_zero_or_charged(self):
        self.record('candidate', tokens=None, cost_microusd=None, cost_basis='unknown')
        self.record('candidate', id='quote', cost_microusd=5000, cost_basis='quoted')
        self.assess('candidate')
        result = self.receipt()
        self.assertEqual(result['known_cost_microusd'], 0)
        self.assertIsNone(result['total_cost_microusd'])
        self.assertEqual(result['unknown_assistant_entries'], 1)
        self.assertEqual(result['cost_by_basis_microusd']['quoted'], 5000)

    def test_comparison_requires_current_quality_and_coverage(self):
        self.record('baseline', 200); self.record('candidate', 100)
        compare = lambda: usage.compare(self.store, 'local', self.project, 'baseline', 'candidate')
        self.assertIsNone(compare()['assistant_tokens'])
        self.assess('baseline'); self.assess('candidate')
        result = compare()
        self.assertEqual(result['assistant_tokens']['saved'], 100)
        self.assertEqual(result['assistant_tokens']['candidate'], 120)  # Cache/reasoning are subsets.
        self.assertEqual(result['cost_microusd']['saved'], 1000)
        self.record('candidate', id='new-call')
        self.assertFalse(self.receipt()['assessment_current'])
        self.assertIsNone(compare()['assistant_tokens'])
        self.assess('candidate', 'fail')
        self.assertIsNone(compare()['assistant_tokens'])

    def test_scope_mismatch_and_unknown_external_coverage(self):
        self.start('development', scope='development'); self.record('development')
        self.record('baseline'); self.assess('development'); self.assess('baseline')
        result = usage.compare(self.store, 'local', self.project, 'baseline', 'development')
        self.assertIn('Different scope', result['unmeasured_reasons'])
        whole = self.receipt(None)
        self.assertEqual(whole['by_scope']['development']['assistant_tokens'], 120)
        self.assertIsNone(whole['total_cost_microusd'])

    def test_fewer_tokens_can_still_cost_more(self):
        self.record('baseline', 200, cost_microusd=1000)
        self.record('candidate', 100, cost_microusd=2000)
        self.assess('baseline'); self.assess('candidate')
        result = usage.compare(self.store, 'local', self.project, 'baseline', 'candidate')
        self.assertEqual(result['assistant_tokens']['saved'], 100)
        self.assertEqual(result['cost_microusd']['saved'], -1000)
        self.assertEqual(result['cost_microusd']['saved_percent'], -100)

    def test_interrupted_native_attempt_stays_unsettled(self):
        job = self.store.submit('local', self.project, 'image.create', {}, 'interrupted', usage_workflow='candidate')
        running = self.store.claim('local', 'fixture-worker', ['image.create'])
        self.store.interrupt('local', job['id'], running['token'], 'synthetic uncertainty')
        self.assertTrue(self.receipt()['pending'])
        with self.assertRaises(Conflict): self.assess('candidate')

    def test_automatic_agent_calls_and_uncertain_reservations(self):
        journal = Journal(self.store)
        spec = specification('Render text', 'image'); spec['usage_workflow'] = 'candidate'
        run = journal.create(self.project, spec, 1)['id']; owner = journal.claim(run)
        call = journal.reserve(run, owner, {}, 10000)
        journal.settle(run, owner, call, response={}, usage={'input_tokens': 100, 'output_tokens': 20,
            'input_tokens_details': {'cached_tokens': 10}, 'output_tokens_details': {'reasoning_tokens': 5}}, charge=5000)
        second = journal.reserve(run, owner, {}, 10000)
        journal.settle(run, owner, second, error='TimeoutError')
        result = self.receipt(details=True)
        self.assertEqual(result['assistant_tokens']['total_tokens'], 120)
        self.assertEqual(result['known_cost_microusd'], 5000)
        self.assertEqual(result['unknown_cost_entries'], 1)
        self.assertEqual(sum(v['reserved_microusd'] for v in result['ledger']), 20000)
        with self.assertRaises(Conflict): self.assess('candidate')

    def test_job_retries_and_explicit_compute_estimate(self):
        self.start('priced', compute_microusd_per_hour=3600000)
        job = self.store.submit('local', self.project, 'image.create', {}, 'job', usage_workflow='priced')
        self.assertEqual(job['request']['usage_workflow'], 'priced')
        with self.assertRaises(Conflict): self.store.submit('local', self.project, 'image.create', {}, 'job', usage_workflow='baseline')
        for number in (1, 2):
            running = self.store.claim('local', 'test-worker', ['image.create'])
            self.store.fail('local', job['id'], running['token'], 'fixture', 'synthetic failure')
            with self.store.transaction() as db:
                self.store._event(db, job['id'], 'execution_measurement', {'token': running['token'], 'wall_seconds': 2.5})
            if number == 1: self.store.retry('local', job['id'], 'retry', {'image.create'})
        result = self.receipt('priced', details=True)
        self.assertEqual(result['entries'], 2)
        self.assertEqual(result['known_cost_microusd'], 5000)
        self.assertEqual(result['measured_seconds_sum'], 5)
        self.assertFalse(result['pending'])
        self.assertEqual(self.receipt(None)['known_cost_microusd'], 5000)

    def test_native_cache_checks_and_byte_invalidation(self):
        observed = {'status': 'observed', 'lines': [{'text': 'STUD1O', 'confidence': .99, 'box': [0, 0, 1, 1]}], 'peak_rss_bytes': 1234}
        with patch.object(native_ocr, 'recognize', return_value=observed) as helper:
            first = native_ocr.inspect_bytes(self.store, 'local', self.project, self.png(), workflow='candidate', expected_text=['STUDIO'], expected_dimensions=[320, 100])
            second = native_ocr.inspect_bytes(self.store, 'local', self.project, self.png(), workflow='candidate', expected_text=['STUD1O'])
            native_ocr.inspect_bytes(self.store, 'local', self.project, self.png('black'), workflow='candidate')
            self.assertEqual(helper.call_count, 2)
        self.assertFalse(first['cache_hit']); self.assertTrue(second['cache_hit'])
        self.assertFalse(first['checks']['expected_text'][0]['observed_exact_line'])
        self.assertTrue(second['checks']['expected_text'][0]['observed_exact_line'])
        self.assertTrue(first['checks']['dimensions_match']); self.assertFalse(first['quality_approved'])
        self.assertEqual(self.receipt()['ocr_cache_hits'], 1)
        self.assertEqual(self.receipt()['unknown_cost_entries'], 3)
        with self.assertRaises(Conflict): self.assess('candidate')  # Cannot claim compute not used.

    def test_native_unavailable_is_explicit_and_not_cached(self):
        with patch.object(native_ocr.platform, 'system', return_value='Linux'):
            first = native_ocr.inspect_bytes(self.store, 'local', self.project, self.png(), workflow='candidate', expected_text=['STUDIO'])
            second = native_ocr.inspect_bytes(self.store, 'local', self.project, self.png(), workflow='candidate')
        self.assertEqual(first['result']['status'], 'unsupported')
        self.assertIsNone(first['checks']['expected_text'][0]['observed_exact_line'])
        self.assertFalse(second['cache_hit'])

    def test_native_cache_is_project_and_helper_scoped(self):
        other = self.store.create_project('local', 'other')['id']
        result = {'status': 'observed', 'lines': []}
        with patch.object(native_ocr, 'recognize', return_value=result) as helper:
            native_ocr.inspect_bytes(self.store, 'local', self.project, self.png())
            native_ocr.inspect_bytes(self.store, 'local', other, self.png())
            with patch.object(native_ocr, 'identity', return_value={'version': 'different'}):
                native_ocr.inspect_bytes(self.store, 'local', self.project, self.png())
            self.assertEqual(helper.call_count, 3)

    def test_archived_project_refuses_new_records(self):
        from studio_runtime.projects import set_state
        set_state(self.store, 'local', self.project, 'archived')
        with self.assertRaises(Conflict): self.record('candidate')
        with self.assertRaises(Conflict): native_ocr.inspect_bytes(self.store, 'local', self.project, self.png())
        self.assertEqual(self.receipt()['entries'], 0)

    def test_interrupted_ocr_remains_visible_and_erasure_is_fenced(self):
        def interrupted(*args):
            with self.assertRaises(Conflict): erasure.erase_project(self.store, 'local', self.project, True)
            raise SystemExit('synthetic client interruption')
        with patch.object(native_ocr, 'recognize', side_effect=interrupted):
            with self.assertRaises(SystemExit): native_ocr.inspect_bytes(self.store, 'local', self.project, self.png(), workflow='candidate')
        receipt = self.receipt(details=True)
        self.assertEqual(receipt['entries'], 1)
        self.assertEqual(receipt['ledger'][0]['status'], 'unsettled')
        self.assertEqual(receipt['unknown_cost_entries'], 1)
        with self.assertRaises(Conflict): self.assess('candidate')

    def test_project_erasure_removes_ledger_and_ocr_cache(self):
        self.record('candidate')
        with patch.object(native_ocr, 'recognize', return_value={'status': 'observed', 'lines': []}):
            native_ocr.inspect_bytes(self.store, 'local', self.project, self.png(), workflow='candidate')
        self.assertTrue(erasure.erase_project(self.store, 'local', self.project, True)['complete'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM project_events WHERE project=?', (self.project,)).fetchone()[0], 0)

    def test_cli_and_mcp_receipts_share_source(self):
        self.record('candidate')
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(main(['--state', str(self.store.root), 'usage', 'receipt', '--project', self.project, '--workflow', 'candidate']), 0)
        direct = mcp.invoke(self.store, 'studio_usage_receipt', {'project': self.project, 'workflow': 'candidate'})
        self.assertEqual(json.loads(output.getvalue()), direct)

    def test_ocr_low_preserves_explicit_high_detail_and_records_work(self):
        spec = specification('Keep STUDIO exact', 'image'); spec.update(usage_workflow='candidate', inspection_policy='native-ocr-low')
        journal = Journal(self.store); run = journal.create(self.project, spec, 1)['id']
        status = journal.status(run); status['context'] = {'revision': 'fixture-revision'}
        raw = self.png()
        observed = {'revision': 'fixture-revision', 'sources': {}, 'validation': {}, 'artifacts': [], 'technical_evidence': {},
                    'images': [{'path': 'exports/preview.png', 'sha256': 'fixture', 'dimensions': [320, 100],
                        'content': {'type': 'input_image', 'detail': 'high', 'image_url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}}]}
        result = {'status': 'observed', 'lines': [{'text': 'STUD1O', 'confidence': .99, 'box': [0, 0, 1, 1]}]}
        coordinator = Coordinator(self.store)
        with patch('studio_runtime.agent_evidence.collect', side_effect=lambda *a: copy.deepcopy(observed)), patch.object(native_ocr, 'recognize', return_value=result):
            request, _ = coordinator.request(status)
            self.assertEqual(request['input'][0]['content'][1]['detail'], 'low')
            self.assertIn('STUD1O', request['input'][0]['content'][0]['text'])
            status['context']['selection'] = ['exports/preview.png']
            request, _ = coordinator.request(status)
            self.assertEqual(request['input'][0]['content'][1]['detail'], 'high')
        self.assertEqual(self.receipt()['ocr_cache_hits'], 1)

    def test_completed_agent_workflow_exposes_ocr_and_metered_call(self):
        spec = specification('Keep STUDIO exact', 'image')
        spec.update(usage_workflow='candidate', inspection_policy='native-ocr-low', ocr_binding=native_ocr.identity())
        journal = Journal(self.store); run = journal.create(self.project, spec, 1)['id']
        owner = journal.claim(run)
        journal.set_state(run, owner, 'inspecting', {'revision': 'fixture-revision'})
        journal.release(run, owner)
        raw = self.png()
        observed = {'revision': 'fixture-revision', 'sources': {}, 'validation': {'passed': True}, 'artifacts': [], 'technical_evidence': {},
                    'images': [{'path': 'exports/preview.png', 'sha256': 'fixture', 'dimensions': [320, 100],
                        'content': {'type': 'input_image', 'detail': 'high', 'image_url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}}]}
        class Transport:
            def count(self, request): return 100, 'fixture-count'
            def generate(self, request):
                self.request = request
                answer = {'action': 'accept', 'checks': {'brief': True}, 'findings': ['Synthetic test only'], 'limitations': []}
                return {'status': 'completed', 'usage': {'input_tokens': 100, 'output_tokens': 20},
                        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer)}]}]}, 'fixture-response'
        transport = Transport()
        with patch('studio_runtime.agent_evidence.collect', return_value=observed), patch.object(native_ocr, 'recognize', return_value={'status': 'failed', 'reason': 'fixture failure'}):
            result = Coordinator(self.store, transport=transport).run(run)
        self.assertEqual(result['state'], 'completed', result['context'])
        self.assertEqual(transport.request['input'][0]['content'][1]['detail'], 'high')
        receipt = self.receipt(details=True)
        self.assertEqual(receipt['entries'], 2)
        self.assertEqual(receipt['assistant_tokens']['total_tokens'], 120)
        self.assertEqual(receipt['known_cost_microusd'], 2000)
        self.assertEqual(receipt['preflight_attempts'], 1)
        self.assertIsNone(receipt['total_cost_microusd'])
        self.assertFalse(receipt['assessment_current'])  # Agent acceptance is not an external coverage/quality attestation.


if __name__ == '__main__': unittest.main()
