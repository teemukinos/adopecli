#!/usr/bin/env python3
"""Measure one Images API attempt through the unchanged bundled image CLI.

No automatic retries, image edits, prior images, or price estimates. Each invocation
requires a new attempt directory. Provider usage is saved before image decoding.
"""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace

from production_file_io import png_bytes

KEY_PATH = Path.home() / '.config/adopecli-benchmark/openai-api-key'
CLI_PATH = Path.home() / '.codex/skills/.system/imagegen/scripts/image_gen.py'


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    """Exclusive, durable evidence; never replace an earlier attempt."""
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def configure_key(path):
    if not sys.stdin.isatty():
        raise ValueError('Run configure-key in your own interactive Terminal.')
    path = Path(path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise ValueError('Key directory must not be a symlink.')
    if path.parent.stat().st_mode & 0o077:
        raise ValueError('Key directory must have permissions 700.')
    if os.path.lexists(path):
        raise FileExistsError('Key file already exists; it has not been changed.')
    key = getpass.getpass('OpenAI API key (hidden): ').strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError('Key must be nonempty and contain no whitespace.')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(key + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    print('Key saved locally with permissions 600. No API request made.')


def read_key(path):
    if os.environ.get('OPENAI_API_KEY'):
        return os.environ['OPENAI_API_KEY']
    fd = os.open(Path(path).expanduser(), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Key must be an owner-only regular file owned by this user.')
        key = stream.read(16385).strip()
    if not key or len(key) > 16384 or any(c.isspace() for c in key):
        raise ValueError('Invalid local key file.')
    return key


class MeteredImages:
    """Keep raw response usage even if parsing or downstream file handling fails."""

    def __init__(self, client, folder):
        self.client = client
        self.folder = Path(folder)
        self.calls = 0

    def generate(self, **payload):
        if self.calls:
            raise RuntimeError('Only one API call is allowed per attempt directory.')
        save(self.folder / 'request.json', payload)
        save(self.folder / 'api-start.json', {
            'started_at': now(), 'automatic_retries': 0,
            'endpoint': 'https://api.openai.com/v1/images/generations',
            'billing_status': 'unknown_until_response_or_provider_reconciliation',
        })
        self.calls += 1
        started = time.monotonic()
        evidence = {'usage': None, 'request_id': None, 'http_status': None}
        try:
            raw = self.client.images.with_raw_response.generate(**payload)
            evidence.update(http_status=raw.status_code, request_id=raw.headers.get('x-request-id'))
            body = raw.http_response.json()
            # Preserve the provider's complete usage object, including unknown future fields.
            evidence.update(usage=body.get('usage'), model=body.get('model'),
                            created=body.get('created'), quality=body.get('quality'),
                            size=body.get('size'), output_format=body.get('output_format'),
                            returned_images=len(body.get('data', [])))
            evidence['billing_status'] = 'usage_returned' if evidence['usage'] is not None else 'unknown'
            evidence['status'] = 'response_received'
            return raw.parse()
        except BaseException as exc:
            evidence['status'] = 'failed'
            evidence['error_class'] = type(exc).__name__
            response = getattr(exc, 'response', None)
            if response is not None:
                evidence.update(http_status=response.status_code,
                                request_id=response.headers.get('x-request-id'))
                try:
                    body = response.json()
                    evidence['usage'] = body.get('usage', evidence['usage'])
                except (ValueError, AttributeError):
                    pass
            evidence['billing_status'] = 'usage_returned' if evidence['usage'] is not None else 'unknown'
            # Do not log exception text, request headers, credentials, or echoed error bodies.
            raise
        finally:
            evidence.update(finished_at=now(), elapsed_seconds=time.monotonic() - started)
            save(self.folder / 'api-result.json', evidence)


def generate(args, client_factory=None):
    folder = Path(args.attempt_dir).expanduser().absolute()
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.monotonic()
    save(folder / 'attempt-start.json', {'started_at': now(), 'status': 'started'})
    result = {'status': 'failed', 'api_calls': 0, 'actual_billed_cost': None}
    meter = client = None
    old_args = sys.argv
    old_key = os.environ.get('OPENAI_API_KEY')
    try:
        key = read_key(args.key_file)
        prompt = Path(args.prompt_file).read_text(encoding='utf-8')
        if not prompt.strip():
            raise ValueError('Prompt is empty.')
        (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
        cli = Path(args.cli).expanduser().resolve(strict=True)
        result['bundled_cli_sha256'] = hashlib.sha256(cli.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location('bundled_image_cli', cli)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if client_factory is None:
            from openai import OpenAI
            client_factory = OpenAI
        client = client_factory(api_key=key, base_url='https://api.openai.com/v1',
                                max_retries=0, timeout=600.0)
        meter = MeteredImages(client, folder)
        module._create_client = lambda: SimpleNamespace(images=meter)
        # Only this process receives the key; the bundled CLI checks this variable.
        os.environ['OPENAI_API_KEY'] = key
        output = folder / 'original.png'
        sys.argv = [str(cli), 'generate', '--model', args.model, '--quality', 'high',
                    '--size', '1024x1024', '--n', '1', '--output-format', 'png',
                    '--prompt-file', str(folder / 'prompt.txt'), '--no-augment',
                    '--out', str(output)]
        exit_code = module.main()
        if exit_code:
            raise RuntimeError('Bundled CLI returned failure.')
        data, dimensions = png_bytes(output)
        result.update(status='succeeded', preview_path=str(output), dimensions=dimensions,
                      image_sha256=hashlib.sha256(data).hexdigest())
    except BaseException as exc:
        result['error_class'] = type(exc).__name__
    finally:
        sys.argv = old_args
        if old_key is None:
            os.environ.pop('OPENAI_API_KEY', None)
        else:
            os.environ['OPENAI_API_KEY'] = old_key
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                result['client_close_error_class'] = type(exc).__name__
        result.update(api_calls=meter.calls if meter else 0,
                      finished_at=now(), elapsed_seconds=time.monotonic() - started)
        save(folder / 'attempt-result.json', result)
    print(json.dumps({'status': result['status'], 'attempt_dir': str(folder),
                      'api_calls': result['api_calls'], 'preview_path': result.get('preview_path'),
                      'error_class': result.get('error_class')}))
    return 0 if result['status'] == 'succeeded' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    key = sub.add_parser('configure-key', help='Store a key privately without exposing it in shell history.')
    key.add_argument('--key-file', default=str(KEY_PATH))
    run = sub.add_parser('generate', help='One paid generation, without automatic retries.')
    run.add_argument('--attempt-dir', required=True)
    run.add_argument('--prompt-file', required=True)
    run.add_argument('--key-file', default=str(KEY_PATH))
    run.add_argument('--cli', default=str(CLI_PATH))
    run.add_argument('--model', default='gpt-image-2.6-sunburst',
                     choices=['gpt-image-2.6-sunburst', 'gpt-image-2.6-flare'])
    args = parser.parse_args()
    if args.command == 'configure-key':
        configure_key(args.key_file)
        return 0
    return generate(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        # Setup errors are local and never contain the supplied key.
        print(f'Local setup failed ({type(exc).__name__}). Check paths and permissions.', file=sys.stderr)
        raise SystemExit(1)
