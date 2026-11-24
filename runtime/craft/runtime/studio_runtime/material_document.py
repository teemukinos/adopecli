"""Lossless Material project preparation and bounded non-cooking inspection.

The admitted SBS bytes are authoritative. A native save is not a lossless import:
its display/linear color round trip can change values. Existing archives stay
byte-identical; bare SBS is wrapped without rewriting its XML or embedded data.
The durable worker owns final revision publication and aggregate job limits.
"""
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import time
import zipfile

from . import animate_format, material_container as container, material_resources as resources
from . import material_graphs as graphs, material_references as references, material_model as model
from . import material_dependencies as dependencies
from .animate_process import run
from .material_container import require

VERSION = '0.4.1'
REVISION = '65f7bfd3e5f40d695d03162285879f0f8079ff6c'
MAX_MODEL_BYTES = 64 << 20


def owned(root, path):
    path = Path(path).absolute()
    try: relative = path.relative_to(root)
    except ValueError as error: raise ValueError('Material path must stay inside the attempt') from error
    require(relative.parts and '..' not in relative.parts, 'path must name an attempt descendant')
    current = root
    for part in relative.parts:
        current /= part
        require(not current.is_symlink(), 'paths cannot contain symbolic links')
    return path


def inspect_bytes(data):
    snapshot = container.inspect_bytes(data); res = resources.inspect(snapshot)
    graph = graphs.inspect(snapshot,res); refs = references.inspect(snapshot,res,graph)
    return {'container':snapshot, 'resources':res, 'graphs':graph, 'references':refs,
            'model':model.inspect(snapshot,res,graph,refs), 'engine_admission_complete':False}


def read_native(path): return inspect_bytes(container.read_bytes(path))


def portable(profile):
    snapshot = profile['container']
    if snapshot['format'] == 'mcraft': return snapshot['source_bytes']
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as archive:
        entry = zipfile.ZipInfo(snapshot['root'],date_time=(1980,1,1,0,0,0))
        entry.create_system = 3; entry.external_attr = 0o100600 << 16
        archive.writestr(entry,snapshot['source_bytes'])
    data = stream.getvalue(); require(len(data)<=container.MAX_SOURCE, 'portable document exceeds its byte budget')
    return data


def preservation(before, after):
    """Only container wrapping is permitted; every original member stays exact."""
    first = before['container']; second = after['container']
    require(second['format']=='mcraft', 'managed native document must be an archive')
    require(first['root']==second['root'] and first['members']==second['members'] and first['directories']==second['directories'],
            'managed preparation changed original members or directory inventory')
    if first['format']=='mcraft': require(first['source_bytes']==second['source_bytes'], 'managed preparation changed archive bytes')
    require(before['model']['packages'].keys()==after['model']['packages'].keys(), 'managed package inventory changed')
    for package,expected in before['model']['packages'].items(): model.check_native(after['model'],package,expected)
    return {'source_members_equal':True, 'archive_bytes_equal':first['format']=='mcraft',
            'container_conversion':'none' if first['format']=='mcraft' else 'lossless-sbs-wrapper'}


def snapshot_json(data):
    """Bound native JSON without Animate's smaller numeric domain."""
    require(type(data) is bytes and len(data)<=MAX_MODEL_BYTES, 'native snapshot exceeds its byte budget')
    try: animate_format._preflight(data,2_000_000)
    except ValueError as error: raise ValueError(str(error).replace('Animate JSON','Material snapshot')) from error
    def pairs(items):
        result = {}
        for key,value in items:
            require(key not in result, 'native snapshot contains duplicate keys'); result[key] = value
        return result
    def integer(token):
        require(len(token.lstrip('-'))<=20 and -2**64<int(token)<2**64, 'native snapshot integer exceeds its range')
        return int(token)
    def floating(token):
        value = float(token)
        require(math.isfinite(value) and abs(value)<=3.4028234663852886e38, 'native snapshot number exceeds finite binary32')
        return value
    def constant(token): raise ValueError('Material native snapshot contains nonfinite numbers')
    try:
        value = json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_int=integer,parse_float=floating,parse_constant=constant)
    except (RecursionError,UnicodeError) as error: raise ValueError('Material native snapshot is invalid or nested too deeply') from error
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict: pending.extend(item); pending.extend(item.values())
        elif type(item) is list: pending.extend(item)
        elif type(item) is str: require(not any(0xd800<=ord(c)<=0xdfff for c in item), 'native snapshot contains invalid Unicode')
    return value


class Engine:
    """Only the fixed version and non-cooking snapshot routes are admitted here."""
    def __init__(self, executable, root, *, seconds=120, cancelled=lambda:False):
        require(type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=600, 'inspection time budget is invalid')
        self.executable = str(Path(executable).resolve(strict=True)); self.root = Path(root).resolve(strict=True)
        self.deadline = time.monotonic()+seconds; self.cancelled = cancelled; self.calls = 0
        require(self._run('--version').strip()==('dobe-material '+VERSION+' ('+REVISION+')').encode(), 'inspection requires the maintained engine revision')

    def _run(self, *arguments):
        self.calls += 1
        try:
            return run([self.executable,*map(str,arguments)],self.root,deadline=self.deadline,cancelled=self.cancelled,
                       stdout_limit=MAX_MODEL_BYTES,stderr_limit=1<<20,file_limit=container.MAX_SOURCE)
        except ValueError as error:
            raise ValueError(str(error).replace('Animate native','Material native')) from error

    def observe(self, path, profile):
        path = owned(self.root,path); expected = profile['container']['source_bytes']
        require(container.read_bytes(path)==expected, 'inspection input changed before native access')
        value = snapshot_json(self._run('snapshot',path))
        require(type(value) is dict and set(value)=={'nativePackage','loadWarnings','cookedNodeCount','pendingCook'} | dependencies.fields(profile), 'native snapshot envelope differs')
        require(value['loadWarnings']==[] and type(value['cookedNodeCount']) is int and value['cookedNodeCount']==0
                and value['pendingCook'] is True, 'native snapshot recovered content or performed a cook')
        comparison = dependencies.check_reply(profile,value)
        require(container.read_bytes(path)==expected, 'native inspection changed its immutable input')
        return comparison


def object_map(profile):
    return {'schema_version':1, 'root_package':profile['container']['root'], 'graphs':[
        {'package':package,'path':name,'kind':'function' if 'function' in graph else 'material',
         'nodes':[{'id':str(identity),'native_id':node['native_id'],'definition':node['definition']} for identity,node in graph['nodes'].items()]}
        for (package,name),graph in profile['graphs']['graphs'].items()]}


def prepare(root, source, destination, executable, *, seconds=120, cancelled=lambda:False):
    """Prepare a new private directory; no existing destination is overwritten.

This establishes lossless editable import and independent cold snapshots only.
It never cooks, exports pixels, grants linked-file access or publishes a revision.
"""
    root = Path(root).resolve(strict=True); source = owned(root,source); destination = owned(root,destination)
    require(root.is_dir() and destination.parent.is_dir() and not destination.exists(), 'preparation requires a new owned destination')
    original = container.read_bytes(source); profile = inspect_bytes(original)
    data = portable(profile); prepared = inspect_bytes(data); retained = preservation(profile,prepared)
    require(not cancelled(), 'preparation cancelled')
    destination.mkdir()
    try:
        native = destination/'native'; exports = destination/'exports'; native.mkdir(); exports.mkdir()
        document = native/'document.mcraft'; document.write_bytes(data)
        source_file = native/('source.'+profile['container']['format']); source_file.write_bytes(original)
        engine = Engine(executable,destination,seconds=seconds,cancelled=cancelled)
        first = engine.observe(document,prepared)
        # A second process reopens the bytes from disk, with no in-memory native
        # session or cache. It must produce the same full predicted state.
        reopened = read_native(document); preservation(prepared,reopened)
        second = engine.observe(document,reopened)
        require(container.read_bytes(source)==original and container.read_bytes(source_file)==original, 'preparation source changed')
        report = {'schema_version':1, 'source_sha256':profile['container']['source_sha256'],
                  'document_sha256':prepared['container']['source_sha256'], 'source_format':profile['container']['format'],
                  'source_file':'native/'+source_file.name, 'document_file':'native/document.mcraft', **retained,
                  'native_model_equal':first['serialized_native_model_equal'] and second['serialized_native_model_equal'],
                  'native_packages_compared':first['native_packages_compared'],
                  'immutable_archive_dependencies':first['immutable_archive_dependencies'],
                  'archive_package_sha256':{key:hashlib.sha256(prepared['container']['members'][key]).hexdigest() for key in first['native_packages_compared']},
                  'native_cold_reopen':True, 'cook_performed':False, 'native_calls':engine.calls,
                  'graph_count':len(prepared['graphs']['graphs']), 'image_nodes':prepared['graphs']['image_nodes'],
                  'resource_count':len(prepared['resources']['resources']), 'resource_bytes':prepared['resources']['resource_bytes'],
                  'engine_admission_complete':False, 'render_qualified':False}
        from .material_source import selectors
        source_index = json.dumps({'source_sha256':prepared['container']['source_sha256'],'packages':selectors(prepared)},sort_keys=True).encode()
        require(len(source_index)<=MAX_MODEL_BYTES, 'source selector index exceeds its byte budget')
        (native/'source-index.json').write_bytes(source_index+b'\n')
        (native/'objects.json').write_text(json.dumps(object_map(prepared),sort_keys=True,allow_nan=False)+'\n')
        encoded = json.dumps(prepared['model']['packages'][prepared['container']['root']],sort_keys=True,allow_nan=False).encode()
        require(len(encoded)<=MAX_MODEL_BYTES, 'retained native model exceeds its byte budget')
        (native/'model.json').write_bytes(encoded+b'\n')
        (exports/'inspection.json').write_text(json.dumps(report,sort_keys=True,allow_nan=False)+'\n')
        require(not cancelled(), 'preparation cancelled')
        return report
    except BaseException:
        # This directory was created exclusively by this call inside the owned
        # attempt. Failed preparation must not look like a completed revision.
        shutil.rmtree(destination)
        raise
