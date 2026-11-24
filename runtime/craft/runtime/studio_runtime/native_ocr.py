"""Optional Apple Vision checks. No network, regeneration or quality approval."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from . import usage
from .agent_crops import dimensions
from .agent_evidence import blob
from .store import artifact_write


SOURCE = Path(__file__).with_suffix('.swift')


def run_process(command, timeout, data=None):
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
        return stdout


def identity():
    return {'version': 1, 'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'platform': platform.platform(), 'machine': platform.machine(), 'languages': ['en-US']}


def recognize(store, raw):
    if platform.system() != 'Darwin': return {'status': 'unsupported', 'reason': 'Apple Vision requires macOS'}
    compiler = shutil.which('swiftc')
    if compiler is None: return {'status': 'unavailable', 'reason': 'swiftc is required; no toolchain is installed automatically'}
    key = hashlib.sha256(usage.canonical(identity()).encode()).hexdigest()
    helpers = store.root / 'helpers'; helpers.mkdir(mode=0o700, exist_ok=True)
    executable = helpers / ('native-ocr-' + key)
    with tempfile.TemporaryDirectory(prefix='ocr-', dir=store.root / 'staging') as folder:
        folder = Path(folder)
        if not executable.exists():
            target = folder / 'native-ocr'
            run_process([compiler, '-O', str(SOURCE), '-o', str(target)], 90)
            target.chmod(0o700); os.replace(target, executable)
        output = run_process([str(executable)], 30, raw)
        if len(output) > 220000: raise ValueError('OCR output exceeds 220000 bytes')
        return {'status': 'observed', **json.loads(output)}


@artifact_write
def inspect_bytes(store, workspace, project, raw, *, workflow=None, expected_text=None, expected_dimensions=None, provenance=None):
    start = time.monotonic()
    expected_text = [] if expected_text is None else expected_text
    if not isinstance(expected_text, list) or len(expected_text) > 50 or any(not isinstance(v, str) or not v or len(v) > 1000 for v in expected_text):
        raise ValueError('expected_text requires at most 50 nonempty strings of at most 1000 characters')
    if len(usage.canonical(expected_text).encode()) > 32768:
        raise ValueError('Expected text exceeds 32 KiB when serialized')
    if expected_dimensions is not None and (not isinstance(expected_dimensions, list) or len(expected_dimensions) != 2 or any(type(v) is not int or v < 1 for v in expected_dimensions)):
        raise ValueError('expected_dimensions must be two positive integers')
    if len(raw) > 16 << 20: raise ValueError('OCR image exceeds 16 MiB')
    size = dimensions(raw)
    digest = hashlib.sha256(raw).hexdigest(); helper = identity()
    cache_key = hashlib.sha256(usage.canonical({'image': digest, 'helper': helper}).encode()).hexdigest()
    with store.connect() as db:
        store._project(db, workspace, project, write=True)
        if workflow is not None: usage.workflow(db, project, workflow)
        cached = next((v for v in usage.events(db, project, 'inspection', reverse=True)
                       if v['cache_key'] == cache_key and v['result']['status'] == 'observed'), None)
    inspection_id = uuid.uuid4().hex
    with store.transaction() as db:
        store._project(db, workspace, project, write=True)
        usage.append(db, project, 'inspection_started', {'id': inspection_id, 'workflow': workflow, 'cache_key': cache_key})
    try:
        result = cached['result'] if cached else recognize(store, raw)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        # Do not expose subprocess stderr or local paths to the model.
        result = {'status': 'failed', 'reason': type(exc).__name__}
    if len(usage.canonical(result).encode()) > 131072:
        result = {**result, 'lines': result.get('lines', [])[:40], 'truncated': True}
    observed = [' '.join(v['text'].split()) for v in result.get('lines', [])]
    checks = {'sha256': digest, 'dimensions': size,
              'dimensions_match': size == expected_dimensions if expected_dimensions else None,
              'expected_text': [{'text': text, 'observed_exact_line': ' '.join(text.split()) in observed if result['status'] == 'observed' and not result.get('truncated') else None}
                                for text in expected_text]}
    value = dict(id=inspection_id, workflow=workflow, cache_key=cache_key, helper=helper, result=result,
                 checks=checks, cache_hit=cached is not None, elapsed_seconds=time.monotonic() - start, provenance=provenance,
                 timing_basis='Validation, lookup, compilation when needed, recognition and deterministic checks; excludes final journal write.',
                 memory_basis='OCR process peak RSS; excludes compiler and parent. Cached results retain original observation memory, not cache-hit memory.')
    with store.transaction() as db:
        store._project(db, workspace, project, write=True)
        if workflow is not None: usage.workflow(db, project, workflow)
        usage.append(db, project, 'inspection', value)
    return {**value, 'quality_approved': False,
            'limitation': 'OCR can miss or misread text. Exact-line checks are observations, not semantic or visual quality approval. Video frames do not establish temporal quality.'}


def inspect_revision(store, workspace, project, revision, path, **options):
    manifest = store.get_revision(workspace, revision)
    # Validate both ownership and the revision's project before reading any blob.
    with store.connect() as db:
        store._project(db, workspace, project)
        if not db.execute('SELECT 1 FROM revisions WHERE id=? AND project=? AND workspace=?', (revision, project, workspace)).fetchone():
            raise ValueError('Revision does not belong to project')
    entry = next((e for e in manifest['files'] if e['path'] == path), None)
    if entry is None: raise ValueError('Published artifact not found')
    return inspect_bytes(store, workspace, project, blob(store, entry), provenance={'revision': revision, 'path': path}, **options)
