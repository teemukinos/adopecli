"""Local-only SDK transport fixtures. No credentials or external requests."""
import argparse
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import httpx2
from openai import OpenAI

import measure_image_api as measured


def fixture_png():
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0\xff\xff\xff')) + chunk(b'IEND', b''))


class MeasurementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text("Fixture only. Quotes ' and $ and ` retained.")
        self.usage = {'input_tokens': 12, 'output_tokens': 34, 'total_tokens': 46,
                      'input_tokens_details': {'text_tokens': 12, 'image_tokens': 0},
                      'future_field': {'retained': True}}
        self.calls = []

    def invoke(self, handler, folder='attempt-01'):
        def factory(**kwargs):
            self.assertEqual(kwargs['max_retries'], 0)
            self.assertEqual(kwargs['base_url'], 'https://api.openai.com/v1')
            def capture(request):
                self.calls.append(json.loads(request.content))
                return handler(request)
            return OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(capture)))
        args = argparse.Namespace(attempt_dir=str(self.root / folder), prompt_file=str(self.prompt),
                                  cli=str(measured.CLI_PATH), key_file=str(self.root / 'unused'),
                                  model='gpt-image-2.6-sunburst')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-not-a-real-key'}):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return measured.generate(args, factory)

    def success(self, request, image=None):
        return httpx2.Response(200, headers={'x-request-id': 'fixture-request'}, json={
            'created': 1, 'usage': self.usage,
            'data': [{'b64_json': base64.b64encode(image if image is not None else fixture_png()).decode()}],
        })

    def result(self, name='api-result.json'):
        return json.loads((self.root / 'attempt-01' / name).read_text())

    def test_success_preserves_usage_and_exact_image(self):
        self.assertEqual(self.invoke(self.success), 0)
        self.assertEqual(self.result()['usage'], self.usage)
        self.assertEqual(self.result()['request_id'], 'fixture-request')
        self.assertEqual((self.root / 'attempt-01/original.png').read_bytes(), fixture_png())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['quality'], 'high')
        self.assertEqual(self.calls[0]['size'], '1024x1024')
        self.assertEqual(self.calls[0]['prompt'], self.prompt.read_text())
        self.assertNotIn('fixture-not-a-real-key', ''.join(p.read_text() for p in (self.root / 'attempt-01').glob('*.json')))

    def test_server_failure_is_counted_without_retry(self):
        self.assertEqual(self.invoke(lambda _: httpx2.Response(500, headers={'x-request-id': 'failure-id'},
                         json={'error': {'message': 'Fixture failure', 'type': 'server_error'}})), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.result()['http_status'], 500)
        self.assertEqual(self.result()['billing_status'], 'unknown')

    def test_timeout_keeps_attempt_and_unknown_billing(self):
        def timeout(request):
            raise httpx2.ReadTimeout('Fixture timeout', request=request)
        self.assertEqual(self.invoke(timeout), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.result()['billing_status'], 'unknown')
        self.assertEqual(self.result('attempt-result.json')['api_calls'], 1)

    def test_invalid_png_retains_paid_usage(self):
        self.assertEqual(self.invoke(lambda request: self.success(request, b'invalid PNG')), 1)
        self.assertEqual(self.result()['usage'], self.usage)
        self.assertEqual(self.result('attempt-result.json')['status'], 'failed')

    def test_missing_usage_stays_unknown(self):
        self.usage = None
        self.assertEqual(self.invoke(self.success), 0)
        self.assertEqual(self.result()['billing_status'], 'unknown')

    def test_existing_attempt_refused_before_api(self):
        (self.root / 'attempt-01').mkdir()
        with self.assertRaises(FileExistsError):
            self.invoke(self.success)
        self.assertEqual(len(self.calls), 0)

    def test_key_setup_permissions_and_no_overwrite(self):
        path = self.root / 'private' / 'key'
        with patch('sys.stdin.isatty', return_value=True), patch('getpass.getpass', return_value='fixture-key'):
            with contextlib.redirect_stdout(io.StringIO()):
                measured.configure_key(path)
            with self.assertRaises(FileExistsError):
                measured.configure_key(path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(measured.read_key(path), 'fixture-key')
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                measured.read_key(path)


if __name__ == '__main__':
    unittest.main()
