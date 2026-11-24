"""Receipt-bound Sheets execution and full original-to-current native replay.

Only fixed native commands execute, with bounded pipes/files/CPU and owned
paths. The existing attempt supervisor owns cancellation groups. This is not a
hostile-process sandbox, a public endpoint or permission to publish artifacts.
"""
import copy
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from . import sheets_source as source, sheets_project as project
from .sheets_source import require
from .animate_process import run
from .sheets_source import read_bytes
from .write_engine import owned, executable_digest


def authored_state(profile, touched=()):
    """Complete model except formula caches and explicitly targeted cells."""
    model = copy.deepcopy(profile['document']); targets = set(touched)
    for index, sheet in enumerate(model['sheets']):
        cells = []
        for si, row, col, original in profile['cells']:
            if si != index or (si,row,col) in targets: continue
            cell = copy.deepcopy(original)
            if cell['formula'] is not None: cell['value'] = {'t':'Empty'}
            cells.append([row,col,cell])
        sheet['cells'] = sorted(cells, key=lambda item:(item[0],item[1]))
    return model


class Engine:
    def __init__(self, executable, root, *, expected_pin, expected_binary_sha256, seconds=120, cancelled=lambda:False):
        require(type(seconds) in (int,float) and math.isfinite(seconds) and 0 < seconds <= 600, 'native time budget invalid')
        require(type(expected_binary_sha256) is str and len(expected_binary_sha256) == 64
                and all(c in '0123456789abcdef' for c in expected_binary_sha256), 'verified binary hash required')
        self.root = Path(root).resolve(strict=True); require(self.root.is_dir(), 'native attempt root missing')
        path = Path(executable).absolute(); require(path.name == 'dobe-sheets' and path.parent.name == 'bin', 'native executable layout differs')
        owned(Path(path.anchor), path); self.pin = project.pin(expected_pin); self.executable = str(path)
        self.deadline = time.monotonic()+seconds; self.cancelled = cancelled; self.calls = 0
        self.binary_sha256 = expected_binary_sha256; self._active()
        metadata = source.strict_json(read_bytes(path.parent.parent/'engine.json'))
        require(type(metadata) is dict and metadata.get('product') == 'dobe-sheets' and type(metadata.get('source_lock')) is dict
                and type(metadata.get('files')) is dict, 'native receipt fields invalid')
        lock = metadata['source_lock']; require(type(lock.get('source')) is dict, 'native source receipt invalid')
        digest = source.sha((json.dumps(lock, indent=2, sort_keys=True)+'\n').encode())
        declared = {'product':metadata['product'], 'version':lock.get('engine_version'), 'source_revision':lock['source'].get('revision'), 'source_lock_sha256':digest}
        require(declared == self.pin and metadata.get('source_lock_sha256') == digest, 'native receipt differs from qualified source pin')
        digest, size, self.binary_identity = executable_digest(path)
        require(digest == expected_binary_sha256 and metadata['files'].get('bin/dobe-sheets') == {'bytes':size,'sha256':digest}, 'native executable differs from verified binary receipt')
        require(self._run('--version').strip() == b'dobe-sheets 0.19.1', 'native executable version differs')

    def _active(self): require(not self.cancelled() and time.monotonic() < self.deadline, 'native operation cancelled or timed out')

    def _unchanged(self):
        path = Path(self.executable); owned(Path(path.anchor), path); now = path.stat(); old = self.binary_identity
        require((now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns,now.st_ctime_ns) ==
                (old.st_dev,old.st_ino,old.st_size,old.st_mtime_ns,old.st_ctime_ns), 'native executable changed after receipt verification')

    def _run(self, *args):
        self._active(); self._unchanged(); self.calls += 1
        try: result = run([self.executable,*map(str,args)], self.root, deadline=self.deadline, cancelled=self.cancelled,
                          stdout_limit=8192, stderr_limit=1<<20, file_limit=source.MAX_JSON)
        except ValueError as error: raise ValueError(str(error).replace('Animate native','Sheets native')) from error
        self._unchanged(); self._active(); return result

    def _command(self, *args): require(self._run(*args) == b'', 'native file command emitted unexpected output')

    def _input(self, path, expected):
        self._active(); profile = source.inspect_bytes(expected); path = owned(self.root,path)
        require(read_bytes(path) == expected, 'native input changed before execution'); return path,profile

    def observe(self, path, expected):
        path, profile = self._input(path, expected)
        with tempfile.TemporaryDirectory(prefix='.sheets-cold-', dir=self.root) as temporary:
            output = Path(temporary)/'cold.json'; self._command('encode',path,output)
            data = read_bytes(owned(self.root,output)); current = source.inspect_bytes(data)
            source.same(current['document'], profile['document'], 'native cold complete model')
            require(read_bytes(path) == expected, 'native observation changed immutable source')
        return {'model_sha256':source.sha(expected), 'native_cold_reopens':1, 'complete_model_equal':True,
                'native_admission_complete':True, 'calculation_verified':False}

    def produce(self, path, expected, change):
        change = project.operation(change); path, before = self._input(path,expected)
        self.observe(path,expected)
        with tempfile.TemporaryDirectory(prefix='.sheets-change-', dir=self.root) as temporary:
            root = Path(temporary); output = root/'result.json'
            touched = []
            if change['kind'] == 'calculate': self._command('recalc',path,output)
            else:
                for item in change['edits']:
                    require(item['sheet'] < len(before['document']['sheets']), 'edit sheet index outside workbook')
                    touched.append((item['sheet'],*source.address(item['cell'])))
                request = root/'request.json'; request.write_bytes(source.encoded(change['edits']))
                self._command('edit',path,request,output)
            data = read_bytes(owned(self.root,output)); after = source.inspect_bytes(data)
            original = authored_state(before,touched); revised = authored_state(after,touched)
            if change['kind'] == 'cells.edit':
                old_styles = original.pop('styles')['styles']; new_styles = revised.pop('styles')['styles']
                source.same(new_styles[:len(old_styles)],old_styles,'retained native styles')
            source.same(revised, original, 'unrelated authored model state')
            cold = self.observe(output,data)
            # Re-evaluate the emitted caches in a separate process. Publication
            # cannot rely solely on a successful edit process or caller hashes.
            check = root/'recalculated.json'; self._command('recalc',output,check)
            require(read_bytes(owned(self.root,check)) == data, 'fresh native calculation differs from emitted cached values')
            require(read_bytes(path) == expected, 'native production changed immutable source')
            self._active()
            return {'data':data, 'before_sha256':source.sha(expected), 'after_sha256':source.sha(data), 'operation':change,
                    'native_cold_reopens':2, 'calculation_verified':True, 'unrelated_state_preserved':True,
                    'engine':dict(self.pin), 'binary_sha256':self.binary_sha256, 'cold_model':cold}

    def verify_project(self, data, destination):
        self._active(); checked = project.inspect_bytes(data); require(checked['manifest']['engine'] == self.pin, 'project engine differs from installed receipt')
        destination = owned(self.root,destination); created = False
        try:
            project.checkout(self.root,destination,data,cancelled=self.cancelled); created = True
            current = checked['members']['original.json']; self.observe(destination/'original.json',current)
            observations = []
            with tempfile.TemporaryDirectory(prefix='.sheets-replay-', dir=self.root) as temporary:
                for index, step in enumerate(checked['manifest']['history']):
                    prior = Path(temporary)/f'input-{index}.json'; prior.write_bytes(current)
                    actual = self.produce(prior,current,step['operation'])
                    require(actual['data'] == checked['members'][step['state']], 'native history replay differs from recorded complete result')
                    observations.append({'index':index,'before_sha256':actual['before_sha256'],'after_sha256':actual['after_sha256'],'calculation_verified':True})
                    current = actual['data']
            self.observe(destination/'document.json',current)
            require({p.name for p in destination.iterdir()} == set(checked['members']) and
                    all(read_bytes(destination/name) == payload for name,payload in checked['members'].items()), 'native verification changed portable members')
            self._active()
            return {'project_sha256':checked['sha256'], 'source_sha256':checked['source_sha256'], 'current_sha256':checked['current_sha256'],
                    'native_admission_complete':True, 'history_replayed':len(observations), 'revisions':observations,
                    'calculation_verified':bool(observations), 'engine':dict(self.pin), 'binary_sha256':self.binary_sha256}
        except BaseException:
            if created: shutil.rmtree(destination)
            raise

    def export(self, path, expected, kind):
        require(kind in ('csv','html'), 'export format unsupported'); path, _ = self._input(path,expected)
        self.observe(path,expected)
        with tempfile.TemporaryDirectory(prefix='.sheets-export-',dir=self.root) as temporary:
            output = Path(temporary)/('output.'+kind); self._command('export',kind,path,output)
            data = read_bytes(owned(self.root,output), allow_empty=kind == 'csv'); require(len(data) <= source.MAX_JSON, 'export exceeds byte budget')
            require(read_bytes(path) == expected, 'native export changed immutable source')
            return {'data':data, 'sha256':source.sha(data), 'source_sha256':source.sha(expected), 'format':kind,
                    'calculation_verified':True, 'pinned_font_rendering_verified':False}
