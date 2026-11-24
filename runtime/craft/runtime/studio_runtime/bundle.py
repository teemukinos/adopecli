"""Bounded portable-bundle extraction and native validation inside a worker."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import unicodedata
import zipfile

from . import photo, vector
from .store import relative_path


ENGINES = {'photocraft': '0.23.1', 'vectorcraft': '0.24.1'}


def unpack(source, destination, maximum, *, replay_families=()):
    from . import bundle_replay
    engines = {**ENGINES, **bundle_replay.engine_versions(replay_families)}
    root = Path(destination)
    root.mkdir(mode=0o700)
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 2001:
            raise ValueError('bundle contains too many entries')
        names = {}; folded = set()
        for entry in entries:
            name = relative_path(entry.filename.rstrip('/'))
            if entry.orig_filename != entry.filename or entry.flag_bits & 1:
                raise ValueError('encrypted or ambiguous bundle entry')
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('bundle contains a non-regular entry')
            if (stat.S_ISDIR(mode) and not entry.is_dir()) or (stat.S_ISREG(mode) and entry.is_dir()):
                raise ValueError('bundle entry type disagrees with its path')
            key = unicodedata.normalize('NFC', name).casefold()
            if key in folded or name in names:
                raise ValueError('duplicate or non-portable bundle path')
            folded.add(key); names[name] = entry
        entry = names.get('project.json')
        if entry is None or entry.is_dir() or entry.file_size > 1048576:
            raise ValueError('bounded project.json is required')
        manifest_bytes = archive.read(entry)
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
            raise ValueError('unsupported bundle schema')
        files = manifest.get('files')
        if not isinstance(files, list) or not 1 <= len(files) <= 1000:
            raise ValueError('bundle requires 1 to 1000 declared files')
        engine = manifest.get('engine', {})
        if (not isinstance(engine, dict) or type(engine.get('name')) is not str
                or engine['name'] not in engines or engines[engine['name']] != engine.get('version')):
            raise ValueError('bundle engine is not qualified')
        declared = set(); portable_paths = set(); total = 0
        for item in files:
            name = relative_path(item['path'])
            portable = unicodedata.normalize('NFC', name).casefold()
            if name == 'project.json' or name.startswith('project.json/') or name in declared:
                raise ValueError('duplicate or reserved manifest path')
            if any(name.startswith(p + '/') or p.startswith(name + '/') for p in declared):
                raise ValueError('overlapping manifest paths')
            if any(portable.startswith(p + '/') or p.startswith(portable + '/') for p in portable_paths):
                raise ValueError('overlapping portable manifest paths')
            declared.add(name)
            portable_paths.add(portable)
            if item.get('role') not in ('native','asset','export','preview','recipe'):
                raise ValueError('invalid artifact role')
            if type(item.get('bytes')) is not int or not 0 <= item['bytes'] <= maximum:
                raise ValueError('invalid artifact size')
            if not isinstance(item.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', item['sha256']):
                raise ValueError('artifact hash required')
            total += item['bytes']
            entry = names.get(name)
            if total > maximum or entry is None or entry.is_dir() or entry.file_size != item['bytes']:
                raise ValueError('bundle exceeds its reservation or has missing/mis-sized files')
        if not {'native','export'} <= {f['role'] for f in files}:
            raise ValueError('native source and export required')
        if {n for n,e in names.items() if not e.is_dir()} != declared | {'project.json'}:
            raise ValueError('undeclared bundle files refused')
        for name,entry in names.items():
            if entry.is_dir() and not any(p.startswith(name+'/') for p in declared):
                raise ValueError('undeclared bundle directory')
        # All metadata is checked before any user file is extracted. Never use
        # extractall(), follow links, or trust ZIP compression-size declarations.
        for item in files:
            path = root / item['path']; path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(); count = 0
            with archive.open(names[item['path']]) as src, open(path, 'xb') as dst:
                while chunk := src.read(1024*1024):
                    count += len(chunk)
                    if count > item['bytes']:
                        raise ValueError('expanded artifact exceeds declared size')
                    digest.update(chunk); dst.write(chunk)
            if count != item['bytes'] or digest.hexdigest() != item['sha256']:
                raise ValueError('bundle artifact hash mismatch')
    return manifest, hashlib.sha256(manifest_bytes).hexdigest()


def png_dimensions(path):
    with open(path, 'rb') as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('qualified PNG export required')
    width,height = struct.unpack('>II', header[16:24])
    if not 1 <= width <= 8192 or not 1 <= height <= 8192:
        raise ValueError('export dimensions exceed qualification')
    return width,height


def execute(source, destination, maximum, *, replay_families=(), replay_authorizations=None, expected_engine=None):
    consent = {}
    if replay_authorizations is not None:
        from .inspect_bundle import authorizations
        consent = authorizations(replay_families, replay_authorizations)
    root = Path(destination)
    manifest, manifest_hash = unpack(source, root, maximum, replay_families=replay_families)
    if expected_engine is not None and expected_engine != {k: manifest['engine'].get(k) for k in ('name', 'version')}:
        raise ValueError('bundle engine differs from the requested import family')
    validation = {'passed': True, 'scope': 'bundle_and_native', 'native_cold_reopen': True,
                  'original_files_unchanged': True}
    name = manifest['engine']['name']
    dimensions = None
    with tempfile.TemporaryDirectory(prefix='native-reopen-', dir=root.parent) as temp:
        check = Path(temp)
        if name == 'photocraft':
            version_text = photo.run(['photocraft-cli','--version']).strip()
            if version_text.split()[1] != ENGINES[name]:
                raise ValueError('PhotoCraft engine version mismatch')
            native = root / 'native/document.pcraft'
            info = json.loads(photo.run(['photocraft-cli','info','--compact',str(native)]))
            if info.get('warnings') or info.get('depth') != 8 or not info.get('layers'):
                raise ValueError('native image has unsupported depth, missing layers or warnings')
            dimensions = png_dimensions(root / 'exports/document.png')
            if dimensions != (info.get('width'), info.get('height')):
                raise ValueError('native and export dimensions differ')
            reopened = check / 'reopened.png'
            photo.run(['photocraft-cli','convert','--no-gpu',str(native),str(reopened)])
            with zipfile.ZipFile(native) as archive:
                entry = archive.getinfo('composite/full.png')
                if entry.file_size > maximum:
                    raise ValueError('native composite exceeds reservation')
                with archive.open(entry) as src, open(check/'composite.png','xb') as dst:
                    shutil.copyfileobj(src,dst)
            if len({photo.pixel_hash(p) for p in (reopened,check/'composite.png',root/'exports/document.png')}) != 1:
                raise ValueError('imported native image does not reproduce its export')
            validation['pixel_roundtrip_equal'] = True
            engine = {'name': name,'version': ENGINES[name],'build': version_text}
        elif name == 'vectorcraft':
            dependencies = vector.inspect_native(root/'native/document.vectorcraft')
            objects = vector.read_objects(root/'native/objects.json')
            object_ids = {value['id'] for value in objects.values()}
            dimensions = png_dimensions(root/'exports/document.png')
            reopened = vector.Engine(root)
            try:
                reopened.command('file.open',{'path':str(root/'native/document.vectorcraft')})
                inspected = reopened.command('document.inspect', {'ids': sorted(object_ids), 'depth': 0})
                actual = {node['id']: node['kind'] for node in inspected['nodes']}
                if any(actual.get(value['id']) != vector.KINDS[value['type']] for value in objects.values()):
                    raise ValueError('editable mapping does not match native objects')
                # The engine write root is deliberately limited to the bundle.
                temporary = root/'__studio_reopen.svg'
                temporary_png = root/'__studio_reopen.png'
                if temporary.exists() or temporary_png.exists():
                    raise ValueError('reserved validation path present')
                reopened.command('document.export',{'path':str(temporary)})
                reopened.command('document.export',{'path':str(temporary_png),'scale':1})
            finally:
                reopened.close()
            if temporary.read_bytes() != (root/'exports/document.svg').read_bytes():
                raise ValueError('imported native vector does not reproduce its SVG')
            if photo.pixel_hash(temporary_png) != photo.pixel_hash(root/'exports/document.png'):
                raise ValueError('imported native vector does not reproduce its PNG')
            temporary.unlink(); temporary_png.unlink()
            validation['svg_roundtrip_equal'] = True
            validation['editable_object_ids_verified'] = True
            validation['pixel_roundtrip_equal'] = True
            engine = {'name': name,'version': ENGINES[name],'dependencies': dependencies}
        else:
            from .bundle_replay import replay
            engine, native_validation = replay(root, manifest, check, replay_families, authorizations=consent)
            validation.update(native_validation)
    # Inspection must not rewrite native files, dependencies or source assets.
    for file in manifest['files']:
        with open(root/file['path'],'rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest() != file['sha256']:
                raise ValueError('native validation changed imported bytes')
    if dimensions is not None:
        validation.update(png_width=dimensions[0],png_height=dimensions[1])
    return {'engine':engine,'validation':validation,
            'artifacts':[{'path':f['path'],'role':f['role']} for f in manifest['files']],
            'provenance':{'imported_revision':manifest.get('id'),'original_project':manifest.get('project'),
                          'source_manifest_sha256':manifest_hash}}
