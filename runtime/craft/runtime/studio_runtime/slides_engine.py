"""Receipt-bound native preservation checks for controlled Slides projects.

This private observer compares independently predicted complete models, including
sidecar bytes, before and after native encoding and cold reopening. It supplies
bounded process execution, not complete imported-model admission, rendered
fidelity, a hostile-process sandbox or durable publication permission.
"""
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time

from . import slides_source as source, slides_revision as revision, slides_project as project
from .animate_process import run
from .write_container import read_bytes
from .write_engine import executable_digest, owned
from .slides_source import require


class Engine:
    def __init__(self, executable, root, *, expected_pin, expected_binary_sha256, seconds=120, cancelled=lambda: False):
        require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 600, 'native time budget is invalid')
        require(type(expected_binary_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_binary_sha256) is not None,
                'native observation needs a verified receipt binary hash')
        self.root = Path(root).resolve(strict=True); require(self.root.is_dir(), 'native observation needs an owned attempt directory')
        path = Path(executable).absolute()
        require(path.name == 'dobe-slides' and path.parent.name == 'bin', 'native executable layout differs')
        current = Path(path.anchor)
        for part in path.parts[1:]:
            require(part != '..', 'native executable path is ambiguous'); current /= part
            require(not current.is_symlink(), 'native executable cannot use symbolic links')
        self.executable = str(path); self.pin = project.pin(expected_pin); self.binary_sha256 = expected_binary_sha256
        self.deadline = time.monotonic()+seconds; self.cancelled = cancelled; self.calls = 0
        require(not cancelled(), 'native observation cancelled')
        metadata = source.strict_json(read_bytes(path.parent.parent/'engine.json'))
        require(type(metadata) is dict and metadata.get('product') == 'dobe-slides' and type(metadata.get('source_lock')) is dict,
                'native engine manifest is invalid')
        lock = metadata['source_lock']; lock_bytes = (json.dumps(lock, indent=2, sort_keys=True)+'\n').encode()
        require(type(lock.get('source')) is dict and type(metadata.get('files')) is dict, 'native source/file inventory is invalid')
        pin = {'product': metadata['product'], 'version': lock.get('engine_version'),
               'source_revision': lock['source'].get('revision'), 'source_lock_sha256': source.sha(lock_bytes)}
        require(project.pin(pin) == self.pin and metadata.get('source_lock_sha256') == self.pin['source_lock_sha256'],
                'native engine manifest differs from verified source pin')
        digest, size, identity = executable_digest(path)
        require(digest == expected_binary_sha256 and metadata['files'].get('bin/dobe-slides') == {'bytes': size, 'sha256': digest},
                'native executable differs from verified receipt')
        self.binary_identity = identity
        version = self._run('--version', limit=8192).strip()
        require(version == ('dobe-slides '+self.pin['version']+' ('+self.pin['source_revision']+')').encode(),
                'native executable version differs from verified receipt')

    def _unchanged_engine(self):
        # Recheck the complete path as well as the inode. A replaced ancestor
        # must not redirect execution after the receipt has been verified.
        path = Path(self.executable); owned(Path(path.anchor), path)
        now = path.stat(); original = self.binary_identity
        require((now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns, now.st_ctime_ns) ==
                (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns, original.st_ctime_ns),
                'native executable changed after receipt verification')

    def _run(self, *arguments, limit=source.MAX_JSON):
        self._unchanged_engine(); self.calls += 1
        try:
            result = run([self.executable, *map(str, arguments)], self.root, deadline=self.deadline, cancelled=self.cancelled,
                         stdout_limit=limit, stderr_limit=1 << 20, file_limit=source.MAX_SOURCE)
        except ValueError as error: raise ValueError(str(error).replace('Animate native', 'Slides native')) from error
        self._unchanged_engine(); return result

    def observe_picture(self, item):
        from . import slides_pictures as pictures
        data,_,_=pictures.decode(item)
        with tempfile.TemporaryDirectory(prefix='.picture-',dir=self.root) as temporary:
            folder=Path(temporary);image=folder/'source';image.write_bytes(data);packets=[]
            for index in range(2):
                output=folder/('pixels-'+str(index));reply=source.strict_json(self._run('picture',image,output,limit=8192))
                packet=read_bytes(output)
                require(type(reply) is dict and set(reply)=={'bytes'} and type(reply['bytes']) is int and reply['bytes']==len(packet),
                        'native picture packet size differs')
                packets.append(packet)
            require(packets[0]==packets[1] and read_bytes(image)==data,'cold native picture decoding changed bytes')
            return pictures.compare(packets[0],item)

    def _snapshot(self, data, expected):
        value = source.strict_json(data)
        require(type(value) is dict and set(value) == {'schemaVersion', 'document', 'usedFonts', 'missingFonts', 'sourceFidelityQualified'},
                'native snapshot envelope differs')
        require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['sourceFidelityQualified'] is False,
                'native snapshot version/fidelity flag differs')
        require(revision.canonical(value['document']) == revision.canonical(expected), 'native snapshot changed the complete predicted model')
        for name in ('usedFonts', 'missingFonts'):
            fonts = value[name]
            require(type(fonts) is list and len(fonts) <= 100_000
                    and all(type(font) is str and len(font.encode()) <= 4096 for font in fonts), 'native font inventory is invalid')
        return {'complete_model_equal': True, 'used_fonts': value['usedFonts'], 'missing_fonts': value['missingFonts']}

    def observe_native(self, path, expected):
        """Compare original container ownership and actual cold native decoding."""
        path = owned(self.root, path); profile = source.inspect_bytes(expected, 'deckcraft')
        require(read_bytes(path) == expected, 'native source changed before observation')
        result = self._snapshot(self._run('snapshot', path), profile['document'])
        require(read_bytes(path) == expected, 'native observation changed immutable source bytes')
        return {**result, 'source_sha256': source.sha(expected)}

    def observe_text(self, path, expected, slide, *, owned_fonts=()):
        """Observe actual placed text; do not infer full render coverage."""
        from . import slides_text
        path = owned(self.root, path); profile = source.inspect_bytes(expected, 'deckcraft')
        require(type(slide) is int and 0 <= slide < len(profile['document']['slides']), 'text observation slide is invalid')
        require(read_bytes(path) == expected, 'native source changed before text observation')
        packet = self._run('text-layout', path, slide, limit=(48 << 20)+12)
        report = slides_text.inspect(packet, owned_fonts)
        require(report['slide'] == slide and report['size'] == [profile['document']['slideSize'][key] for key in ('width', 'height')],
                'text observation returned another slide or canvas')
        require(read_bytes(path) == expected, 'text observation changed immutable source bytes')
        return report

    def observe(self, path, expected, *, cold_reopens=1):
        """Encode an exact model; inspect its sidecars and compare cold snapshots."""
        require(type(cold_reopens) is int and 1 <= cold_reopens <= 2, 'native cold reopen count is invalid')
        path = owned(self.root, path); profile = source.inspect_bytes(expected, 'json')
        require(read_bytes(path) == expected, 'native model changed before observation')
        with tempfile.TemporaryDirectory(prefix='.slides-observe-', dir=self.root) as temporary:
            destination = Path(temporary)/'model.deckcraft'
            encoded = self._snapshot(self._run('encode', path, destination), profile['document'])
            native_bytes = read_bytes(destination)
            reconstructed = source.inspect_bytes(native_bytes, 'deckcraft')
            require(revision.canonical(reconstructed['document']) == revision.canonical(profile['document']),
                    'native writer changed the independently reconstructed complete model')
            require(reconstructed['resources'] == profile['resources'], 'native writer changed resource ownership or bytes')
            for _ in range(cold_reopens):
                cold = self.observe_native(destination, native_bytes)
                require(all(cold[key] == encoded[key] for key in encoded), 'native cold reopening changed model or font inventory')
            require(read_bytes(path) == expected, 'native observation changed immutable model bytes')
            return {**encoded, 'model_sha256': source.sha(expected), 'native_sha256': source.sha(native_bytes),
                    'resource_bytes_equal': True, 'native_cold_reopens': cold_reopens,
                    'engine_admission_complete': False, 'pending_qualification': profile['pending_qualification']}

    def verify_project(self, data, destination):
        checked = project.inspect_bytes(data); project.require_engine(checked, self.pin)
        destination = owned(self.root, destination); created = False
        try:
            project.checkout(self.root, destination, data, cancelled=self.cancelled); created = True
            original = None
            if checked['manifest']['source_format'] == 'deckcraft':
                original = self.observe_native(destination/'original.deckcraft', checked['members']['original.deckcraft'])
            baseline = self.observe(destination/'baseline.json', checked['members']['baseline.json'])
            current = self.observe(destination/'document.json', checked['members']['document.json'], cold_reopens=2)
            require({p.name for p in destination.iterdir()} == set(checked['members']), 'native observation introduced unexpected project files')
            require(all(read_bytes(destination/name) == value for name, value in checked['members'].items()),
                    'native observation changed owned project files')
            require(not self.cancelled(), 'native project verification cancelled')
            return {'schema_version': 1, 'project_sha256': checked['sha256'], 'source_sha256': checked['source_sha256'],
                    'current_sha256': checked['current_sha256'], 'engine': self.pin, 'binary_sha256': self.binary_sha256,
                    'native_calls': self.calls, 'original_native_model_equal': original['complete_model_equal'] if original else None,
                    'baseline_model_equal': baseline['complete_model_equal'], 'current_model_equal': current['complete_model_equal'],
                    'native_cold_reopens': 3, 'original_bytes_unchanged': True, 'resource_bytes_equal': True,
                    'revision_count': checked['revision_count'], 'migration_count': checked['migration_count'],
                    'used_fonts': current['used_fonts'], 'missing_fonts': current['missing_fonts'],
                    'pending_qualification': [item for item in checked['pending_qualification'] if item != 'native-full-model-comparison'],
                    'engine_admission_complete': False, 'source_format_fidelity_qualified': False,
                    'rendered_fidelity_qualified': False, 'durable_publication_qualified': False}
        except BaseException:
            if created: shutil.rmtree(destination)
            raise
