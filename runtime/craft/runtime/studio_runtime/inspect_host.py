"""Explicit host-only reconstruction of otherwise byte-exact native reports.

The pinned native evidence implementation hashes host metadata into its ID.
Preserve number tokens from its actual output instead of approximating Rust's
float formatter in Python. Reconstruction changes only host and evidence ID.
It does not authenticate historical execution or qualify a Linux engine.
"""
import copy
import json
import platform

from . import inspect_source as source
from .inspect_source import require

HOSTS = {('Darwin', 'arm64'): 'macos-aarch64', ('Linux', 'x86_64'): 'linux-x86_64'}
PROFILE = 'exact-report-host-v1'


def current():
    host = HOSTS.get((platform.system(), platform.machine()))
    require(host is not None, 'replay host is unsupported')
    return host


def environment(value):
    require(type(value) is dict and value.get('host') in HOSTS.values()
            and source.encoded(value) == source.encoded({
                'clean_room': False, 'engine': 'builtin', 'engine_version': source.PIN['version'],
                'host': value['host']}), 'report environment is unsupported')
    return value['host']


class Number(str):
    """A validated JSON number token copied verbatim from a native report."""


def encode(value, *, canonical=False):
    if type(value) is Number:
        return str(value)
    if type(value) is dict:
        keys = sorted(value, key=lambda k: k.encode('utf-16-be')) if canonical else value
        return '{'+','.join(encode(k)+':'+encode(value[k],canonical=canonical) for k in keys)+'}'
    if type(value) is list:
        return '['+','.join(encode(v,canonical=canonical) for v in value)+']'
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def rehost(data, host):
    """Rebuild pinned native serialization; never rewrite the supplied bytes."""
    parsed = source.strict_json(data)
    environment(parsed.get('evidence', {}).get('environment'))
    require(host in HOSTS.values(), 'requested report host is unsupported')
    value = json.loads(data.decode('utf-8'), parse_int=Number, parse_float=Number)
    require(encode(value).encode() == data, 'report is not exact native serialization')
    evidence = value['evidence']; evidence['environment']['host'] = host
    identity = copy.deepcopy(evidence)
    for key in ('id', 'summary', 'carries_target_content'):
        identity.pop(key)
    identity['subject'].pop('name', None)
    evidence['id'] = 'ev_'+source.sha(encode(identity, canonical=True).encode())
    return encode(value).encode()


def compare(original, observed):
    before = environment(source.strict_json(original)['evidence']['environment'])
    after = environment(source.strict_json(observed)['evidence']['environment'])
    if before == after:
        require(original == observed, 'complete native report replay differs')
        return None
    require(original == rehost(observed, before), 'complete native report host reconstruction differs')
    return {'profile': PROFILE, 'source_host': before, 'replay_host': after,
            'replayed_report_sha256': source.sha(observed)}


def retained_receipt(current_receipt, retained, original_report):
    """Reconstruct the old operation receipt without authenticating old execution.

    Only a different declared execution host may carry a different binary hash.
    A migration receipt must match the exact host-reconstructed report digest.
    All other fields are compared by the caller against fresh native replay.
    """
    expected = copy.deepcopy(current_receipt)
    expected.pop('host_migration', None)
    original_host = environment(source.strict_json(original_report)['evidence']['environment'])
    migration = retained.get('host_migration')
    execution_host = original_host
    if migration is not None:
        require(type(migration) is dict and migration.get('replay_host') in HOSTS.values(),
                'retained host migration is invalid')
        execution_host = migration['replay_host']
        require(execution_host != original_host, 'retained host migration must change host')
        reconstructed = rehost(original_report, execution_host)
        require(migration == compare(original_report, reconstructed), 'retained host migration differs')
        expected['host_migration'] = migration
    expected['complete_report_equal'] = migration is None
    if execution_host != current():
        source.digest(retained.get('binary_sha256'))
        expected['binary_sha256'] = retained['binary_sha256']
    return expected
