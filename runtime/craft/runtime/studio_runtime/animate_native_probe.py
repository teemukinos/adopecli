"""Private native state checks on already-admitted, attempt-owned snapshots."""
import hashlib
import json
from pathlib import Path
import tempfile
import time

from .animate_format import MAX_JSON, read_bytes, strict_json
from .animate_graph import fields
from .animate_media_probe import NativeSoundInspector
from .animate_process import run
from . import animate_diagnostics, animate_semantics, animate_text


class NativeInspector(NativeSoundInspector):
    """Share one deadline across media decoding and native state inspection."""

    def reconciliation(self, profile):
        """Cold-save only into owned scratch space and compare all stored meaning."""
        from .animate_document import inspect_bytes
        if profile.get('native_state', {}).get('save_load_preserved') is not True:
            raise ValueError('Animate semantic reconciliation requires native preservation first')
        if self.cancelled() or time.monotonic() >= self.deadline:
            raise ValueError('Animate semantic reconciliation cancelled or timed out')
        # Reuse only complete decodes of identical bytes from this admission.
        # Changed or additional sound payloads cannot inherit that evidence.
        sounds = {item['sha256']: {key:value for key,value in item.items() if key != 'sha256'}
                  for item in profile['media']['sounds'].values()}

        def decoded_sound(data, max_samples):
            report = sounds.get(hashlib.sha256(data).hexdigest())
            if report is None or report['samples'] > max_samples:
                raise ValueError('Animate native cold save changed embedded sound data')
            return report

        with tempfile.TemporaryDirectory(prefix='animate-semantics-', dir=self.root) as folder:
            owned = Path(folder)
            source = owned / 'input.anicraft'; source.write_bytes(profile['source_bytes'])
            output = owned / 'saved.anicraft'
            command = [str(self.executable), 'exec', str(source), 'file.save',
                       json.dumps({'path': str(output)}), '--automation-read-root', str(owned),
                       '--automation-write-root', str(owned)]
            report = strict_json(run(command, owned, deadline=self.deadline, cancelled=self.cancelled), max_items=32)
            fields(report, ('saved',), (), 'native cold save report')
            if report['saved'] != str(output):
                raise ValueError('Animate native cold save reported an unexpected path')
            saved = inspect_bytes(read_bytes(output), inspect_sound=decoded_sound)
            result = animate_semantics.compare(profile, saved)
            if self.cancelled() or time.monotonic() >= self.deadline:
                raise ValueError('Animate semantic reconciliation cancelled or timed out')
            return result

    def text(self, profile):
        targets = animate_text.targets(profile); summaries = []
        if targets:
            if self.cancelled() or time.monotonic() >= self.deadline:
                raise ValueError('Animate text diagnostics cancelled or timed out')
            with tempfile.TemporaryDirectory(prefix='animate-text-', dir=self.root) as folder:
                owned = Path(folder)
                source = owned / 'input.anicraft'; source.write_bytes(profile['source_bytes'])
                script = owned / 'checks.json'
                for batch in animate_text.batches(targets):
                    script.write_text(json.dumps([{'cmd': 'text.inspect_stored', 'params': item['selector']} for item in batch]))
                    command = [str(self.executable), 'run', str(source), str(script),
                               '--automation-read-root', str(owned), '--automation-write-root', str(owned)]
                    reports = strict_json(run(command, owned, deadline=self.deadline, cancelled=self.cancelled,
                                              stdout_limit=16 << 20), max_items=1_000_000)
                    if not isinstance(reports, list) or len(reports) != len(batch):
                        raise ValueError('Animate text diagnostics returned an incomplete batch')
                    summaries.extend(animate_text.inspect(report, item) for report, item in zip(reports, batch))
        return {'source_sha256': profile['source_sha256'], 'stored_text_instances': len(targets), 'records': summaries,
                'glyph_coverage_verified': all(item['glyph_coverage_verified'] for item in summaries),
                'native_layout_reproduced': all(item['native_layout_reproduced'] for item in summaries),
                'bidirectional_itemization_verified': False, 'publication_authorized': False}

    def diagnostics(self, profile, *, frames=(), soundtrack=None):
        """Run a generated read-only batch; no caller command or path is accepted."""
        requested = animate_diagnostics.request(profile, frames, soundtrack)
        steps = [{'cmd': 'file.inspect_frame', 'params': {'frame': frame}} for frame in requested['frames']]
        if requested['soundtrack'] is not None:
            steps.append({'cmd': 'file.inspect_soundtrack', 'params': requested['soundtrack']})
        if not steps:
            return animate_diagnostics.interpret([], requested, profile)
        if self.cancelled() or time.monotonic() >= self.deadline:
            raise ValueError('Animate native diagnostics cancelled or timed out')
        with tempfile.TemporaryDirectory(prefix='animate-diagnostics-', dir=self.root) as folder:
            owned = Path(folder)
            source = owned / 'input.anicraft'; source.write_bytes(profile['source_bytes'])
            script = owned / 'checks.json'; script.write_text(json.dumps(steps))
            command = [str(self.executable), 'run', str(source), str(script),
                       '--automation-read-root', str(owned), '--automation-write-root', str(owned)]
            reports = strict_json(run(command, owned, deadline=self.deadline, cancelled=self.cancelled,
                                      stdout_limit=4 << 20))
            return animate_diagnostics.interpret(reports, requested, profile)

    def preservation(self, data):
        # Call only after complete stored-document admission. Native comparison
        # starts after serde, so it cannot replace the exact JSON schema checks.
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_JSON:
            raise ValueError('Animate native state inspection requires an admitted byte snapshot')
        if self.cancelled() or time.monotonic() >= self.deadline:
            raise ValueError('Animate native state inspection cancelled or timed out')
        with tempfile.TemporaryDirectory(prefix='animate-state-', dir=self.root) as folder:
            owned = Path(folder)
            source = owned / 'input.anicraft'; source.write_bytes(data)
            empty = owned / 'empty.anicraft'
            empty.write_text(json.dumps({'format': 'anicraft', 'version': 3, 'generator': 'DobeCLI', 'paths': [],
                'document': {'stage': {'width': 1, 'height': 1, 'fps': 24,
                    'background': {'r': 1, 'g': 1, 'b': 1, 'a': 1}},
                    'scenes': [{'name': 'State inspection', 'timeline': {'layers': []}}], 'library': [], 'next_id': 1}}))
            command = [str(self.executable), 'exec', str(empty), 'file.inspect_preservation',
                       json.dumps({'path': str(source)}), '--automation-read-root', str(owned),
                       '--automation-write-root', str(owned)]
            report = strict_json(run(command, owned, deadline=min(self.deadline, time.monotonic() + 30),
                                     cancelled=self.cancelled), max_items=128)
            fields(report, ('format', 'version', 'input_bytes', 'canonical_bytes', 'load_sanitization_preserved',
                            'save_load_preserved', 'raw_json_preservation_verified', 'document_changed'), (), 'native state report')
            if (report['format'] != 'anicraft' or type(report['version']) is not int or report['version'] != 3
                    or type(report['input_bytes']) is not int or report['input_bytes'] != len(data)
                    or type(report['canonical_bytes']) is not int or not 1 <= report['canonical_bytes'] <= MAX_JSON
                    or report['load_sanitization_preserved'] is not True or report['save_load_preserved'] is not True
                    or report['raw_json_preservation_verified'] is not False or report['document_changed'] is not False):
                raise ValueError('Animate native state preservation report is inconsistent')
            return report
