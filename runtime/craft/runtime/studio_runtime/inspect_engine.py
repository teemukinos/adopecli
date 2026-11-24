"""Receipt-bound static analysis and exact full-report replay, never target execution."""
import json
import math
from pathlib import Path
import tempfile
import time

from . import inspect_source as source, inspect_project as project, inspect_host
from .inspect_source import require
from .write_engine import owned, executable_digest
from .animate_process import run


class Engine:
    def __init__(self,executable,root,*,expected_pin,expected_binary_sha256,seconds=120,cancelled=lambda:False):
        require(type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=600,'native time budget invalid');source.digest(expected_binary_sha256)
        self.root=Path(root).resolve(strict=True);require(self.root.is_dir(),'native attempt root missing')
        path=Path(executable).absolute();owned(Path(path.anchor),path)
        require(path.name=='dobe-inspect' and path.parent.name=='bin','native executable layout differs')
        self.executable=str(path);self.pin=source.pin(expected_pin);self.binary_sha256=expected_binary_sha256
        self.cancelled=cancelled;self.deadline=time.monotonic()+seconds;self.calls=0;self._active()
        metadata=source.strict_json(source.read_bytes(path.parent.parent/'engine.json'))
        require(type(metadata) is dict and metadata.get('product')=='dobe-inspect' and type(metadata.get('source_lock')) is dict
                and type(metadata.get('files')) is dict,'native receipt invalid')
        lock=metadata['source_lock'];require(type(lock.get('source')) is dict,'source receipt invalid')
        digest=source.sha((json.dumps(lock,indent=2,sort_keys=True)+'\n').encode())
        declared={'product':metadata['product'],'version':lock.get('engine_version'),'source_revision':lock['source'].get('revision'),'source_lock_sha256':digest}
        require(declared==self.pin and metadata.get('source_lock_sha256')==digest,'native receipt differs from qualified source')
        digest,size,self.identity=executable_digest(path)
        require(digest==self.binary_sha256 and metadata['files'].get('bin/dobe-inspect')=={'sha256':digest,'bytes':size},'native executable differs from receipt')
        require(self._run('--version').strip()==b'dobe-inspect 0.6.1','native version differs')

    def _active(self):require(not self.cancelled() and time.monotonic()<self.deadline,'native operation cancelled or timed out')

    def _unchanged(self):
        path=Path(self.executable);owned(Path(path.anchor),path);now=path.stat();before=self.identity
        require((now.st_dev,now.st_ino,now.st_size,now.st_mtime_ns,now.st_ctime_ns)==
                (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns),'native executable changed after verification')

    def _run(self,*args):
        self._active();self._unchanged();self.calls+=1
        try:result=run([self.executable,*map(str,args)],self.root,deadline=self.deadline,cancelled=self.cancelled,
                       stdout_limit=8192,stderr_limit=1<<20,file_limit=source.MAX_REPORT)
        except ValueError as error:raise ValueError(str(error).replace('Animate native','Inspect native')) from error
        self._unchanged();self._active();return result

    def analyze(self,original,kind,expected_sha256):
        self._active();source.input_bytes(original,kind,expected_sha256)
        with tempfile.TemporaryDirectory(prefix='.inspect-native-',dir=self.root) as directory:
            root=Path(directory);path=root/'input.bin';path.write_bytes(original);reports=[]
            for index in range(2):
                output=root/f'report-{index}.json'
                require(self._run('inspect',kind,'--owned-or-authorized',expected_sha256,path,output)==b'','native file command emitted unexpected output')
                data=source.read_bytes(owned(self.root,output),source.MAX_REPORT);source.report_bytes(data,original,kind)
                require(inspect_host.environment(source.strict_json(data)['evidence']['environment'])==inspect_host.current(),
                        'native report host differs from execution host')
                require(source.read_bytes(owned(self.root,path),source.MAX_INPUT)==original,'native inspection changed source bytes');reports.append(data)
            require(reports[0]==reports[1],'independent native cold reports differ')
            self._active();return reports[0]

    def verify_project(self,data):
        self._active();checked=project.inspect_bytes(data);require(checked['manifest']['engine']==self.pin,'project pin differs')
        observed=self.analyze(checked['members']['source.bin'],checked['manifest']['input_format'],checked['source_sha256'])
        migration=inspect_host.compare(checked['members']['report.json'],observed)
        self._active()
        return {'project_sha256':checked['sha256'],'source_sha256':checked['source_sha256'],'report_sha256':source.sha(observed),
                'native_cold_reopens':2,'complete_report_equal':migration is None,'annotation_history_replayed':checked['revision_count'],
                'input_executed':False,'external_references_resolved':False,'carries_target_content':True,
                'engine':dict(self.pin),'binary_sha256':self.binary_sha256,
                **({'host_migration':migration} if migration is not None else {})}
