"""Portable original workbooks and exact native-operation replay candidates.

History stores native result bytes, not invented formula evaluation. A caller can
rewrite every hash in an archive. Only receipt-bound native replay can establish
that the recorded result follows from its source and typed request.
"""
import copy
import io
import zipfile

from . import sheets_source as source, write_container
from .sheets_source import require

PIN = {'product':'dobe-sheets', 'version':'0.19.1', 'source_revision':'476448d7d9f3a5f8e93fcf7d98b47fd52293fe7f',
       'source_lock_sha256':'81399b2284de6058022e531ee534a36ecd9d34b8b21a571128d1a4dd68a697e4'}
MAX_ARCHIVE = 64 << 20
MAX_MANIFEST = 1 << 20
MAX_HISTORY = 32
MAX_EDITS = 4096


def pin(value):
    source.same(value, PIN, 'engine pin'); return dict(PIN)


def record(data): return {'sha256':source.sha(data), 'bytes':len(data)}


def operation(value):
    require(type(value) is dict and type(value.get('kind')) is str, 'history operation invalid')
    if value['kind'] == 'calculate': source.fields(value, ('kind',), 'calculation operation')
    else:
        source.fields(value, ('kind','edits'), 'edit operation'); require(value['kind'] == 'cells.edit', 'history operation unsupported')
        source.edits(value['edits'])
    return copy.deepcopy(value)


def pack(manifest, members):
    require(type(members) is dict and 'project.json' not in members, 'portable members collide with manifest')
    metadata = source.encoded(manifest)
    require(len(metadata) <= MAX_MANIFEST and all(type(v) is bytes for v in members.values())
            and sum(map(len, members.values()))+len(metadata) <= MAX_ARCHIVE, 'portable payload exceeds byte budget')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data in sorted({**members,'project.json':metadata}.items()):
            info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0)); info.create_system = 3; info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    data = stream.getvalue(); require(len(data) <= MAX_ARCHIVE, 'portable archive exceeds byte budget'); return data


def inspect_bytes(data):
    require(type(data) is bytes and 22 <= len(data) <= MAX_ARCHIVE, 'portable archive exceeds byte budget')
    # Check total declared sizes before shared strict ZIP decoding allocates payloads.
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            rows = archive.infolist(); require(3 <= len(rows) <= MAX_HISTORY+3 and sum(r.file_size for r in rows) <= MAX_ARCHIVE, 'portable expanded inventory exceeds budget')
        members, directories, _ = write_container.archive_members(data)
    except (ValueError, OSError, zipfile.BadZipFile) as error: raise ValueError('Sheets portable archive refused: '+str(error)) from error
    require(not directories and 'project.json' in members and len(members['project.json']) <= MAX_MANIFEST, 'portable manifest/directory inventory invalid')
    manifest = source.strict_json(members['project.json']); source.fields(manifest, ('format','version','engine','original','current','history','members'), 'portable manifest')
    require(manifest['format'] == 'dobe-sheets-project' and type(manifest['version']) is int and manifest['version'] == 1, 'portable format/version invalid')
    pin(manifest['engine']); history = manifest['history']; require(type(history) is list and len(history) <= MAX_HISTORY, 'portable history exceeds budget')
    names = {'original.json','document.json'} | {f'state-{i+1:04}.json' for i in range(len(history))}
    require(type(manifest['members']) is dict and set(manifest['members']) == names and set(members) == names | {'project.json'}, 'portable member inventory differs')
    profiles = {}
    for name in sorted(names):
        item = manifest['members'][name]; source.fields(item, ('bytes','sha256'), 'portable member record')
        source.same(item, record(members[name]), 'portable member hash/size')
        profiles[name] = source.inspect_bytes(members[name])
    require(manifest['original'] == source.sha(members['original.json']) and manifest['current'] == source.sha(members['document.json']), 'portable root hashes differ')
    before = members['original.json']; count = 0
    for i, step in enumerate(history):
        source.fields(step, ('before','after','state','operation'), 'history step'); change = operation(step['operation'])
        count += len(change.get('edits', [])); require(count <= MAX_EDITS, 'portable aggregate edit budget exceeded')
        state = f'state-{i+1:04}.json'; require(step['state'] == state and step['before'] == source.sha(before) and step['after'] == source.sha(members[state]), 'portable history chain differs')
        before = members[state]
    require(before == members['document.json'], 'portable current bytes differ from final history state')
    return {'manifest':manifest, 'members':members, 'profiles':profiles, 'sha256':source.sha(data),
            'source_sha256':manifest['original'], 'current_sha256':manifest['current'], 'revision_count':len(history),
            'native_admission_required':True, 'history_native_replay_required':bool(history), 'calculation_verified':False}


def create(data, *, engine):
    source.inspect_bytes(data); members = {'original.json':data, 'document.json':data}
    manifest = {'format':'dobe-sheets-project', 'version':1, 'engine':pin(engine), 'original':source.sha(data), 'current':source.sha(data),
                'history':[], 'members':{k:record(v) for k,v in members.items()}}
    result = pack(manifest, members); inspect_bytes(result); return result


def append_candidate(data, expected_sha256, change, result):
    """Package candidate native result; caller must subsequently verify full replay."""
    require(source.sha(data) == expected_sha256, 'portable revision hash is stale')
    checked = inspect_bytes(data); source.inspect_bytes(result); change = operation(change)
    manifest = copy.deepcopy(checked['manifest']); require(len(manifest['history']) < MAX_HISTORY, 'portable history exceeds budget')
    name = f"state-{len(manifest['history'])+1:04}.json"
    members = {k:v for k,v in checked['members'].items() if k != 'project.json'}; members[name] = result; members['document.json'] = result
    manifest['history'].append({'before':manifest['current'], 'after':source.sha(result), 'state':name, 'operation':change})
    manifest['current'] = source.sha(result); manifest['members'] = {k:record(v) for k,v in members.items()}
    output = pack(manifest, members); inspect_bytes(output); return output


def checkout(root, destination, data, *, cancelled=lambda:False):
    import os
    from pathlib import Path
    from .write_engine import owned
    checked = inspect_bytes(data); root = Path(root).resolve(strict=True); destination = owned(root, destination)
    require(root.is_dir() and destination.parent.is_dir() and not destination.exists() and not cancelled(), 'checkout needs a fresh owned destination')
    destination.mkdir(mode=0o700); created = []
    try:
        for name, payload in checked['members'].items():
            require(not cancelled(), 'checkout cancelled'); path = destination/name
            with path.open('xb') as stream:
                created.append(path); stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            require(write_container.read_bytes(path) == payload, 'checkout changed member bytes')
        require(not cancelled(), 'checkout cancelled')
    except BaseException:
        for path in reversed(created): path.unlink()
        destination.rmdir(); raise
    return checked
