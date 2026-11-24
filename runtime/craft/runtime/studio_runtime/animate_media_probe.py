"""Private, cancellable native sound inspection in an owned attempt directory."""
import json
from pathlib import Path
import tempfile
import time

from .animate_media import MAX_ENCODED, MAX_SAMPLES
from .animate_format import strict_json
from .animate_process import run


class NativeSoundInspector:
    """Use a verified maintained executable selected by the runtime, never input.

    Each sound gets a fresh short-lived process. The native command is fixed,
    read-only and allocation-bounded. No imported project or its scripts are
    opened. This is a process/resource contract, not an OS security sandbox.
    """
    def __init__(self, executable, root, *, cancelled=lambda: False, seconds=120):
        self.executable = Path(executable).resolve(strict=True)
        self.root = Path(root).resolve(strict=True)
        if not self.executable.is_file() or not self.root.is_dir() or not 0 < seconds <= 120:
            raise ValueError('Animate sound inspection requires a qualified engine and owned directory')
        self.cancelled = cancelled
        self.deadline = time.monotonic() + seconds

    def __call__(self, data, max_samples):
        if (not isinstance(data, bytes) or not 0 < len(data) <= MAX_ENCODED
                or type(max_samples) is not int or not 1 <= max_samples <= MAX_SAMPLES):
            raise ValueError('Animate sound inspection exceeds its input budget')
        if self.cancelled() or time.monotonic() >= self.deadline:
            raise ValueError('Animate sound inspection cancelled or timed out')
        with tempfile.TemporaryDirectory(prefix='animate-sound-', dir=self.root) as folder:
            owned = Path(folder); source = owned / 'sound.bin'; source.write_bytes(data)
            native = owned / 'empty.anicraft'
            native.write_text(json.dumps({'format': 'anicraft', 'version': 3, 'generator': 'DobeCLI', 'paths': [],
                'document': {'stage': {'width': 1, 'height': 1, 'fps': 24,
                    'background': {'r': 1, 'g': 1, 'b': 1, 'a': 1}},
                    'scenes': [{'name': 'Media inspection', 'timeline': {'layers': []}}], 'library': [], 'next_id': 1}}))
            params = json.dumps({'path': str(source), 'max_samples': max_samples})
            command = [str(self.executable), 'exec', str(native), 'file.inspect_sound', params,
                       '--automation-read-root', str(owned), '--automation-write-root', str(owned)]
            stdout = run(command, owned, deadline=min(self.deadline, time.monotonic() + 30),
                         cancelled=self.cancelled)
            return strict_json(stdout, max_items=256)
