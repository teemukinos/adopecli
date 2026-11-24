"""Portable CAD originals, candidate baselines and exact typed revision replay.

DXF baseline documents are explicitly unbound candidates. Neither their hashes
nor user-supplied engine pins prove native parsing, admission or execution rights.
A receipt-bound observer must read the original with the pinned installed binary.
"""
import io
import re
import zipfile

from . import cad_source as source, cad_revision as revision, write_container
from .cad_source import require

MAX_HISTORY = 32
MAX_EDITS = 128
MAX_REPLAY = 256 << 20
MAX_MANIFEST = 1 << 20
# Exact maintained transition; project-provided digests cannot invent an edge.
MIGRATION_EDGES = {('0.20.1', '7526dc62c14e71b3c8d46e73bbf1fa29ef506af1',
                    '46620256f0d0de9e29a4275df32af29f2809885efa8631243ce4a7ff821d60d9',
                    '383362c1a5e33c1623563d3c407206d0a3669fc723af644dfebdbe0460835059')}


def migration_edge(before, after):
    before=pin(before);after=pin(after)
    require(before['version']==after['version'] and before['source_revision']==after['source_revision']
            and (before['version'],before['source_revision'],before['source_lock_sha256'],after['source_lock_sha256']) in MIGRATION_EDGES,
            'portable migration does not name a qualified maintained transition')



def record(data): return {'sha256': source.sha(data), 'bytes': len(data)}


def pin(value):
    require(type(value) is dict and set(value) == {'product', 'version', 'source_revision', 'source_lock_sha256'}, 'engine pin fields differ')
    require(value['product'] == 'dobe-cad' and type(value['version']) is str
            and re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', value['version']), 'engine product/version invalid')
    for key, length in (('source_revision', 40), ('source_lock_sha256', 64)):
        require(type(value[key]) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}', value[key]), 'engine pin digest invalid')
    return dict(value)


def pack(manifest, members):
    require('project.json' not in members, 'manifest collides with payload')
    metadata = revision.encoded(manifest)
    require(len(metadata) <= MAX_MANIFEST and sum(map(len, members.values()))+len(metadata) <= source.MAX_SOURCE, 'portable payload exceeds byte budget')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, data in sorted({**members, 'project.json': metadata}.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)); info.create_system = 3; info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    result = stream.getvalue(); require(len(result) <= source.MAX_SOURCE, 'portable archive exceeds byte budget'); return result


def inspect_bytes(data, *, _predecessor=False, _replay_budget=None):
    budget=MAX_REPLAY if _replay_budget is None else min(MAX_REPLAY,_replay_budget)
    require(type(budget) is int and budget>0, 'portable replay exceeds byte budget')
    try: members, directories, _ = write_container.archive_members(data)
    except ValueError as error: raise ValueError('CAD portable archive refused: '+str(error)) from error
    require(not directories and 'project.json' in members and len(members['project.json']) <= MAX_MANIFEST, 'portable manifest/directory inventory invalid')
    require(sum(map(len, members.values())) <= source.MAX_SOURCE, 'portable expanded payload exceeds byte budget')
    manifest = source.strict_json(members['project.json'])
    require(type(manifest) is dict and type(manifest.get('version')) is int and manifest['version'] in (1,2), 'portable format/version invalid')
    migrated=manifest['version']==2
    require(not (_predecessor and migrated), 'portable nested migration needs separate qualification')
    fields={'format','version','engine','source_format','baseline_binding','members','history'}|({'migration'} if migrated else set())
    require(set(manifest)==fields and manifest['format']=='dobe-cad-project', 'portable manifest fields differ')
    pin(manifest['engine']); kind = manifest['source_format']; require(kind in ('json', 'dxf'), 'portable source format unsupported')
    binding = 'exact-source-json' if kind == 'json' else 'pending-native-observation'
    require(manifest['baseline_binding'] == binding, 'portable baseline cannot assert native verification')
    original = 'original.'+kind; names = {original, 'baseline.json', 'document.json'}|({'predecessor.dobecad'} if migrated else set())
    require(set(members) == names | {'project.json'} and type(manifest['members']) is dict and set(manifest['members']) == names, 'portable member inventory differs')
    for name in names:
        item = manifest['members'][name]
        require(type(item) is dict and set(item) == {'bytes', 'sha256'} and type(item['bytes']) is int
                and type(item['sha256']) is str and item == record(members[name]), 'portable member hash/size differs')
    original_profile = source.inspect_bytes(members[original], kind); baseline = members['baseline.json']
    source.inspect_bytes(baseline, 'json')
    if kind == 'json': require(baseline == members[original], 'portable JSON baseline differs from exact source')
    history = source.sequence(manifest['history'], 'portable history', MAX_HISTORY)
    replay = baseline; replayed = len(replay); count = 0; pending = set(original_profile['pending_qualification'])
    require(replayed<=budget, 'portable replay exceeds byte budget')
    for entry in history:
        require(type(entry) is dict and set(entry) == {'before', 'after', 'edits'} and type(entry['edits']) is list, 'portable history entry invalid')
        if manifest['engine']['source_lock_sha256']=='46620256f0d0de9e29a4275df32af29f2809885efa8631243ce4a7ff821d60d9':
            require(not any(type(e) is dict and e.get('kind') in ('panel.solid','panel.solve') for e in entry['edits']),
                    'predecessor pin does not support typed panel production history')
        count += len(entry['edits']); require(count <= MAX_EDITS, 'portable edit history exceeds aggregate budget')
        # Bound work before copying, parsing or encoding the next whole document.
        require(replayed+len(replay) <= budget, 'portable replay exceeds byte budget')
        change = revision.revise_bytes(replay, entry['before'], entry['edits']); replay = change['data']
        require(entry['after'] == source.sha(replay), 'portable history result differs')
        pending.update(change['pending_qualification']); replayed += len(replay)
        require(replayed <= budget, 'portable replay exceeds byte budget')
    require(replay == members['document.json'], 'portable current model differs from exact typed replay')
    predecessor=None
    if migrated:
        transition=manifest['migration']
        require(type(transition) is dict and set(transition)=={'from_engine','to_engine','predecessor_sha256','revision_count','current_sha256'},
                'portable migration fields differ')
        predecessor=inspect_bytes(members['predecessor.dobecad'],_predecessor=True,_replay_budget=budget-replayed)
        replayed+=predecessor['replayed_bytes'];require(replayed<=budget, 'portable migration replay exceeds aggregate byte budget')
        old=predecessor['manifest'];migration_edge(old['engine'],manifest['engine'])
        require(transition['from_engine']==old['engine'] and transition['to_engine']==manifest['engine']
                and transition['predecessor_sha256']==predecessor['sha256'] and type(transition['revision_count']) is int
                and transition['revision_count']==len(old['history']) and transition['current_sha256']==predecessor['current_sha256'],
                'portable migration differs from exact predecessor')
        require(kind==old['source_format'] and members[original]==predecessor['members'][original]
                and baseline==predecessor['members']['baseline.json'], 'portable migration replaced original or baseline')
        require(len(history)>=len(old['history']) and revision.canonical(history[:len(old['history'])])==revision.canonical(old['history']),
                'portable migration replaced predecessor edit history')
    current = source.inspect_bytes(replay, 'json'); pending.update(current['pending_qualification'])
    return {'manifest': manifest, 'members': members, 'source': original_profile, 'current': current, 'sha256': source.sha(data),
            'source_sha256': source.sha(members[original]), 'current_sha256': source.sha(replay), 'revision_count': len(history),
            'replayed_edits': count, 'replayed_bytes': replayed, 'native_baseline_binding_required': kind == 'dxf',
            'pending_qualification': sorted(pending), 'migration':manifest.get('migration'), 'predecessor':predecessor, 'engine_admission_complete': False}


def create(data, kind, *, engine, baseline=None):
    source.inspect_bytes(data, kind)
    if kind == 'json':
        require(baseline is None or baseline == data, 'JSON baseline must be exact original bytes'); baseline = data
    else:
        require(type(baseline) is bytes, 'DXF requires an explicit candidate native baseline')
        source.inspect_bytes(baseline, 'json')
    members = {'original.'+kind: data, 'baseline.json': baseline, 'document.json': baseline}
    manifest = {'format': 'dobe-cad-project', 'version': 1, 'engine': pin(engine), 'source_format': kind,
                'baseline_binding': 'exact-source-json' if kind == 'json' else 'pending-native-observation',
                'members': {name: record(value) for name, value in members.items()}, 'history': []}
    result = pack(manifest, members); inspect_bytes(result); return result


def revise(data, expected_sha256, edits):
    require(type(data) is bytes and type(expected_sha256) is str and source.sha(data) == expected_sha256, 'portable revision hash is stale')
    before = inspect_bytes(data); manifest = before['manifest']
    require(len(manifest['history']) < MAX_HISTORY, 'portable history exceeds budget')
    current = before['members']['document.json']; change = revision.revise_bytes(current, source.sha(current), edits)
    members = {name: value for name, value in before['members'].items() if name != 'project.json'}; members['document.json'] = change['data']
    manifest['members']['document.json'] = record(change['data'])
    manifest['history'].append({'before': source.sha(current), 'after': source.sha(change['data']), 'edits': change['edits']})
    result = pack(manifest, members); inspect_bytes(result); return result


def migrate(data, expected_sha256, *, engine):
    """Retain the exact old archive/history; native source comparison stays required."""
    require(type(data) is bytes and type(expected_sha256) is str and source.sha(data)==expected_sha256, 'portable migration hash is stale')
    before=inspect_bytes(data);old=before['manifest'];target=pin(engine)
    require(old['version']==1, 'portable nested migration needs separate qualification');migration_edge(old['engine'],target)
    members={name:value for name,value in before['members'].items() if name!='project.json'};members['predecessor.dobecad']=data
    manifest={**old,'version':2,'engine':target,'members':{name:record(value) for name,value in members.items()},
              'migration':{'from_engine':old['engine'],'to_engine':target,'predecessor_sha256':before['sha256'],
                           'revision_count':len(old['history']),'current_sha256':before['current_sha256']}}
    result=pack(manifest,members);after=inspect_bytes(result)
    require(after['current_sha256']==before['current_sha256'], 'portable migration changed authored model')
    return result


def require_engine(checked, installed_pin):
    require(checked['manifest']['engine'] == pin(installed_pin), 'portable source requires its pinned engine and source lock')


def checkout(root, destination, data, *, cancelled=lambda: False):
    """Copy fixed verified members into a new directory in a caller-owned attempt.

    The caller exclusively owns ancestors for the entire operation. Cancellation
    removes only files created by this checkout, never an existing destination.
    """
    import os
    from pathlib import Path
    from .write_engine import owned
    checked = inspect_bytes(data); root = Path(root).resolve(strict=True)
    destination = owned(root, destination)
    require(root.is_dir() and destination.parent.is_dir() and not destination.exists() and not cancelled(),
            'checkout needs a fresh destination and active owned attempt')
    destination.mkdir(mode=0o700); created = []
    try:
        for name, data in checked['members'].items():
            require(not cancelled(), 'checkout cancelled'); path = destination/name
            with path.open('xb') as stream:
                created.append(path); stream.write(data); stream.flush(); os.fsync(stream.fileno())
            require(write_container.read_bytes(path) == data, 'checkout differs from owned member bytes')
        require(not cancelled(), 'checkout cancelled')
    except BaseException:
        for path in reversed(created): path.unlink()
        destination.rmdir(); raise
    return {'project_sha256': checked['sha256'], 'source_sha256': checked['source_sha256'],
            'current_sha256': checked['current_sha256'], 'engine_admission_complete': False}
