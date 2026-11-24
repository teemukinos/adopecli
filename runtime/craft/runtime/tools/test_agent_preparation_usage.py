"""History accounting must include cached tokens without double counting."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from agent_preparation_usage import measure


class PreparationUsageTests(unittest.TestCase):
    def write(self, counters, model='gpt-6-astra'):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        path=Path(temporary.name)/'history.jsonl'
        records=[{'timestamp':'2026-11-19T00:00:00Z','type':'turn_context',
                  'payload':{'model':model,'effort':'high'}}]
        for minute,inputs,cached,outputs,reasoning in counters:
            records.append({'timestamp':f'2026-11-19T00:{minute:02d}:00Z','type':'event_msg',
                'payload':{'type':'token_count','info':{'last_usage_includes_reasoning':True,'total_token_usage':{
                    'input_tokens':inputs,'cached_input_tokens':cached,'output_tokens':outputs,
                    'reasoning_output_tokens':reasoning,'total_tokens':inputs+outputs}}}})
        path.write_text(''.join(json.dumps(x)+'\n' for x in records))
        return path

    def test_cached_input_and_reasoning_are_counted_once_with_duplicate_events(self):
        path=self.write([(0,1000,900,100,50),(2,2000,1700,200,130),(3,2000,1700,200,130)])
        result=measure(path,datetime(2026,11,19,0,1,tzinfo=timezone.utc))
        self.assertEqual(result['measured_tokens']['total_tokens'],1100)
        self.assertEqual(result['measured_tokens']['reasoning_output_tokens'],80)
        self.assertEqual(result['api_equivalent_observed_cache_usd'],.0078)
        self.assertEqual(result['api_equivalent_uncached_normalized_usd'],.015)
        self.assertEqual(result['uncached_input_plus_output_tokens'],300)

    def test_unknown_model_does_not_inherit_an_astra_price(self):
        path=self.write([(0,1000,900,100,50),(2,2000,1700,200,130)],model='unknown')
        result=measure(path,datetime(2026,11,19,0,1,tzinfo=timezone.utc))
        self.assertIsNone(result['api_equivalent_observed_cache_usd'])
        self.assertEqual(result['measured_tokens']['total_tokens'],1100)

    def test_reset_counters_cannot_silently_understate_usage(self):
        path=self.write([(0,1000,900,100,50),(2,20,0,2,0)])
        with self.assertRaisesRegex(ValueError,'reset'):
            measure(path,datetime(2026,11,19,0,1,tzinfo=timezone.utc))


if __name__=='__main__':unittest.main()
