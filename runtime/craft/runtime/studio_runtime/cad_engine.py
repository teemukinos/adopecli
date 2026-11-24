"""Receipt-bound CAD source binding and complete native history observation.

This private observer executes only fixed native commands in an owned attempt.
It verifies actual models and solver results. It is not public model admission,
a hostile-process sandbox, source-format fidelity or durable publication.
"""
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time

from . import cad_source as source, cad_revision as revision, cad_project as project, cad_parametric
from .animate_process import run
from .write_container import read_bytes
from .write_engine import executable_digest, owned
from .cad_source import require


class Engine:
    def __init__(self, executable, root, *, expected_pin, expected_binary_sha256, seconds=120, cancelled=lambda: False):
        require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 600, 'native time budget is invalid')
        require(type(expected_binary_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_binary_sha256),
                'native observation needs a verified receipt binary hash')
        self.root = Path(root).resolve(strict=True); require(self.root.is_dir(), 'native observation needs an owned attempt directory')
        path = Path(executable).absolute()
        require(path.name == 'dobe-cad' and path.parent.name == 'bin', 'native executable layout differs')
        owned(Path(path.anchor), path)
        self.executable = str(path); self.pin = project.pin(expected_pin); self.binary_sha256 = expected_binary_sha256
        self.deadline = time.monotonic()+seconds; self.cancelled = cancelled; self.calls = 0
        require(not cancelled(), 'native observation cancelled')
        metadata = source.strict_json(read_bytes(path.parent.parent/'engine.json'))
        require(type(metadata) is dict and metadata.get('product') == 'dobe-cad' and type(metadata.get('source_lock')) is dict,
                'native engine manifest is invalid')
        lock = metadata['source_lock']; lock_bytes = (json.dumps(lock, indent=2, sort_keys=True)+'\n').encode()
        require(type(lock.get('source')) is dict and type(metadata.get('files')) is dict, 'native source/file inventory is invalid')
        declared_pin = {'product': metadata['product'], 'version': lock.get('engine_version'),
                        'source_revision': lock['source'].get('revision'), 'source_lock_sha256': source.sha(lock_bytes)}
        require(project.pin(declared_pin) == self.pin and metadata.get('source_lock_sha256') == self.pin['source_lock_sha256'],
                'native engine manifest differs from verified source pin')
        digest, size, self.binary_identity = executable_digest(path)
        require(digest == expected_binary_sha256 and metadata['files'].get('bin/dobe-cad') == {'bytes': size, 'sha256': digest},
                'native executable differs from verified receipt')
        version = self._run('--version').strip()
        require(version == ('dobe-cad '+self.pin['version']).encode(), 'native version differs from verified receipt')

    def _active(self):
        require(not self.cancelled() and time.monotonic() < self.deadline, 'native operation cancelled or timed out')

    def _unchanged_engine(self):
        path = Path(self.executable); owned(Path(path.anchor), path)
        now = path.stat(); original = self.binary_identity
        require((now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns, now.st_ctime_ns) ==
                (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns, original.st_ctime_ns),
                'native executable changed after receipt verification')

    def _run(self, *arguments):
        self._active(); self._unchanged_engine(); self.calls += 1
        try:
            result = run([self.executable, *map(str, arguments)], self.root, deadline=self.deadline, cancelled=self.cancelled,
                         stdout_limit=8192, stderr_limit=1 << 20, file_limit=source.MAX_JSON)
        except ValueError as error: raise ValueError(str(error).replace('Animate native', 'CAD native')) from error
        self._unchanged_engine(); self._active(); return result

    def _command(self, *arguments):
        require(self._run(*arguments) == b'', 'native file command emitted unexpected output')

    def _input(self, path, expected, kind):
        self._active(); path = owned(self.root, path); profile = source.inspect_bytes(expected, kind)
        require(read_bytes(path) == expected, 'native source changed before observation')
        return path, profile

    def _same_model(self, path, expected):
        data = read_bytes(owned(self.root, path)); profile = source.inspect_bytes(data, 'json')
        require(revision.canonical(profile['document']) == revision.canonical(expected), 'native changed the complete predicted model')
        return data

    def observe(self, path, expected, *, cold_reopens=1):
        """Compare each complete model with one or two actual cold native encodes."""
        require(type(cold_reopens) is int and 1 <= cold_reopens <= 2, 'native cold reopen count is invalid')
        path, profile = self._input(path, expected, 'json')
        with tempfile.TemporaryDirectory(prefix='.cad-observe-', dir=self.root) as temporary:
            current = path
            for index in range(cold_reopens):
                destination = Path(temporary)/f'cold-{index}.json'
                self._command('encode', current, destination); self._same_model(destination, profile['document']); current = destination
            require(read_bytes(path) == expected, 'native observation changed immutable source bytes')
            self._active()
            return {'model_sha256': source.sha(expected), 'complete_model_equal': True, 'native_cold_reopens': cold_reopens,
                    'resource_bytes_equal': True, 'engine_admission_complete': False}

    def observe_dxf(self, path, expected, baseline):
        """Bind exact original DXF to the candidate by actual full native parsing.

        No DXF re-export or normalization replaces the original or baseline.
        A successful comparison proves this pinned parser's model, not all DXF
        semantics or the fidelity of a future format export.
        """
        path, profile = self._input(path, expected, 'dxf'); model = source.inspect_bytes(baseline, 'json')['document']
        with tempfile.TemporaryDirectory(prefix='.cad-observe-', dir=self.root) as temporary:
            parsed = Path(temporary)/'parsed.json'; cold = Path(temporary)/'cold.json'
            self._command('snapshot', 'dxf', path, parsed); self._same_model(parsed, model)
            self._command('encode', parsed, cold); self._same_model(cold, model)
            require(read_bytes(path) == expected, 'native DXF observation changed immutable source bytes'); self._active()
            return {'source_sha256': profile['source_sha256'], 'baseline_sha256': source.sha(baseline),
                    'complete_model_equal': True, 'native_baseline_bound': True, 'native_cold_reopens': 1,
                    'source_format_fidelity_qualified': False, 'engine_admission_complete': False}

    def verify_project(self, data, destination):
        self._active(); checked = project.inspect_bytes(data); project.require_engine(checked, self.pin)
        destination = owned(self.root, destination); created = False
        try:
            project.checkout(self.root, destination, data, cancelled=self.cancelled); created = True
            kind = checked['manifest']['source_format']; original = None
            if kind == 'dxf':
                original = self.observe_dxf(destination/'original.dxf', checked['members']['original.dxf'], checked['members']['baseline.json'])
            baseline = checked['members']['baseline.json']; self.observe(destination/'baseline.json', baseline)
            # Observe every intermediate, including states later edited away. A
            # final model match cannot prove that earlier source was retained.
            replay = baseline; observed_revisions = []; recipe_observations = []; history_reopens = 0; solve_verified = False; solid_verified = False
            with tempfile.TemporaryDirectory(prefix='.cad-history-', dir=self.root) as temporary:
                for index, entry in enumerate(checked['manifest']['history']):
                    before = replay; change = revision.revise_bytes(before, entry['before'], entry['edits']); replay = change['data']
                    path = Path(temporary)/f'revision-{index}.json'; path.write_bytes(replay)
                    edit = entry['edits'][0]
                    if edit['kind'] in ('panel.solid', 'panel.solve'):
                        prior = Path(temporary)/f'source-{index}.json'; prior.write_bytes(before)
                        options = {key:edit[key] for key in ('width','height','mesh_handle')}
                        if edit['kind']=='panel.solid':
                            produced = self.extrude_panel(prior,before,edit['recipe'],depth=edit['depth'],**options); solid_verified = True
                        else:
                            produced = self.solve_panel(prior,before,edit['recipe'],**options); solve_verified = True
                            if edit['mesh_handle'] is not None: solid_verified = False
                        require(produced['data']==replay, 'native recipe replay differs from exact recorded geometry')
                        history_reopens += produced['native_cold_reopens']
                        recipe_observations.append({'revision':index,'kind':edit['kind'],'source_sha256':source.sha(before),
                                                    'result_sha256':source.sha(replay),'native_cold_reopens':produced['native_cold_reopens']})
                    else:
                        report = self.observe(path,replay); history_reopens += report['native_cold_reopens']
                        if any(e['kind'] in ('parameter.expression','geometry.set') for e in entry['edits']): solve_verified = False; solid_verified = False
                    observed_revisions.append(source.sha(replay))
            current = self.observe(destination/'document.json', checked['members']['document.json'], cold_reopens=2)
            require({p.name for p in destination.iterdir()} == set(checked['members']), 'native observation introduced unexpected project files')
            require(all(read_bytes(destination/name) == value for name, value in checked['members'].items()), 'native observation changed owned project files')
            self._active()
            pending = set(checked['pending_qualification'])-{'native-full-model-comparison', 'native-baseline-binding', 'native-recipe-replay'}
            if solve_verified: pending.discard('native-constraint-solve')
            if solid_verified: pending.discard('native-solid-regeneration')
            return {'schema_version': 1, 'project_sha256': checked['sha256'], 'source_sha256': checked['source_sha256'],
                    'current_sha256': checked['current_sha256'], 'engine': self.pin, 'binary_sha256': self.binary_sha256,
                    'native_calls': self.calls, 'original_native_model_equal': original['complete_model_equal'] if original else None,
                    'native_baseline_bound': kind == 'json' or original['native_baseline_bound'],
                    'baseline_model_equal': True, 'current_model_equal': current['complete_model_equal'],
                    'observed_revision_sha256': observed_revisions, 'revision_count': checked['revision_count'],
                    'original_bytes_unchanged': True, 'resource_bytes_equal': True, 'native_cold_reopens': 3+history_reopens+(1 if original else 0),
                    'recipe_observations': recipe_observations, 'native_constraint_solve_verified': solve_verified, 'native_solid_regeneration_verified': solid_verified,
                    'migration': checked['migration'], 'native_migration_verified': checked['migration'] is not None,
                    'pending_qualification': sorted(pending), 'engine_admission_complete': False,
                    'source_format_fidelity_qualified': False, 'rendered_fidelity_qualified': False, 'durable_publication_qualified': False}
        except BaseException:
            if created: shutil.rmtree(destination)
            raise

    def solve_panel(self, path, expected, recipe, *, width, height, mesh_handle=None):
        """Return verified solved bytes, without mutating source or publishing them."""
        path, profile = self._input(path, expected, 'json')
        cad_parametric.dimension(width); cad_parametric.dimension(height)
        with tempfile.TemporaryDirectory(prefix='.cad-solve-', dir=self.root) as temporary:
            target = Path(temporary)/'report.json'; self._command('solve', path, target)
            report = source.strict_json(read_bytes(target))
            if mesh_handle is None:
                measurements = cad_parametric.verify(profile['document'], report, recipe, width=width, height=height)
            else:
                from . import cad_solid
                measurements = cad_solid.verify_solve(profile['document'], report, recipe, mesh_handle, width=width, height=height)
            data = revision.encoded(report['document']); source.inspect_bytes(data, 'json')
            solved = Path(temporary)/'solved.json'; solved.write_bytes(data); observed = self.observe(solved, data, cold_reopens=2)
            require(read_bytes(path) == expected, 'native solve changed immutable input'); self._active()
            return {'data': data, 'document': report['document'], 'source_sha256': source.sha(expected), 'solved_sha256': source.sha(data),
                    'report': report, 'measurements': measurements, 'native_cold_reopens': observed['native_cold_reopens'],
                    'engine': self.pin, 'binary_sha256': self.binary_sha256, 'engine_admission_complete': False,
                    'durable_publication_qualified': False, 'general_manufacturing_qualified': False}


    def extrude_panel(self, path, expected, recipe, *, width, height, depth, mesh_handle=None):
        """Construct or regenerate the native mesh; independently verify all changes."""
        from . import cad_solid
        path, profile = self._input(path, expected, 'json')
        request = cad_solid.request(profile['document'], recipe, width=width, height=height, depth=depth, mesh_handle=mesh_handle)
        with tempfile.TemporaryDirectory(prefix='.cad-solid-', dir=self.root) as temporary:
            request_path = Path(temporary)/'request.json'; target = Path(temporary)/'report.json'
            request_path.write_bytes(revision.encoded(request)); self._command('panel-solid', path, request_path, target)
            report = source.strict_json(read_bytes(target)); measured = cad_solid.verify(profile['document'], report, request)
            data = revision.encoded(report['document']); solved = Path(temporary)/'solid.json'; solved.write_bytes(data)
            self.observe(solved, data, cold_reopens=2)
            require(read_bytes(path) == expected, 'native extrusion changed immutable input'); self._active()
            return {'data': data, 'document': report['document'], 'source_sha256': source.sha(expected), 'solid_sha256': source.sha(data),
                    'request': request, 'measurements': measured, 'report': report, 'mesh_handle': report['mesh_handle'],
                    'engine': self.pin, 'binary_sha256': self.binary_sha256, 'native_cold_reopens': 2,
                    'engine_admission_complete': False, 'durable_publication_qualified': False}

    def export_panel_obj(self, path, expected, mesh_handle, *, width, height, depth):
        """Export fixed native OBJ geometry and independently check the actual file."""
        from . import cad_solid
        path, profile = self._input(path, expected, 'json')
        require(type(mesh_handle) is int and 0 < mesh_handle < 2**64, 'mesh export selector invalid')
        selected = [entity for entity in profile['document']['model'] if entity['handle'] == mesh_handle]
        require(len(selected) == 1, 'mesh export owner is absent')
        cad_solid.inspect_mesh(selected[0]['kind'], width=width, height=height, depth=depth)
        with tempfile.TemporaryDirectory(prefix='.cad-mesh-', dir=self.root) as temporary:
            target = Path(temporary)/'panel.obj'; self._command('panel-obj', path, mesh_handle, target)
            data = read_bytes(target); checked = cad_solid.inspect_obj(data, width=width, height=height, depth=depth)
            require(checked['mesh_handle'] == mesh_handle and revision.canonical(checked['mesh']) == revision.canonical(selected[0]['kind']),
                    'OBJ geometry differs from native source mesh')
            require(read_bytes(path) == expected, 'mesh export changed immutable input'); self._active()
            return {'data': data, 'sha256': checked['sha256'], 'measurements': checked['measurements'], 'units': 'mm',
                    'native_mesh_equal': True, 'geometry_only': True, 'general_manufacturing_qualified': False}
