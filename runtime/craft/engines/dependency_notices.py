"""Preserve declared notices for Cargo packages observed in one offline build.

This records build inputs, including build scripts and proc macros. It neither
infers exact binary linkage nor interprets license terms or approves distribution.
Registry notices come from the checksum-pinned crate archive, not a mutable web
page or a guessed license template. Git notices come from locally stored pinned
objects after checkout verification. Git commands permit no transport, hooks,
replacement objects or lazy fetching. No network operation occurs.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tomllib
from urllib.parse import unquote, urlsplit


# These excerpts were inspected in the exact checksum-locked source archives.
# They are original notice bytes, not inferred license text. New package versions
# need their own source inspection and pins; no filename/content heuristic applies.
REGISTRY_SOURCE_NOTICES = {
    ('qrcodegen', '1.8.0', '4339fc7a1021c9c1621d87f5e3505f2805c8c105420ba2f2a4df86814590c142'): {
        'SOURCE-NOTICES/src/lib.rs.header.txt': {
            'source_path': 'src/lib.rs',
            'source_bytes': 46056,
            'source_sha256': 'a4546464799faaea27393dd60a24be08349618fb98333decbaf686d4c98ca410',
            'offset': 0,
            'bytes': 1238,
            'sha256': 'b8764c4b987eeec9d0ceb4a958b531dc60fa79b3930125dd0d6552b1ecd08901',
        },
    },
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_path(value):
    path = PurePosixPath(value)
    if (not value or '\\' in value or path.is_absolute() or '..' in path.parts
            or path.as_posix() != value or '\x00' in value):
        raise ValueError('unsafe dependency notice path')
    return path


def notice_name(value):
    name = PurePosixPath(value).name.upper()
    return (name.startswith(('LICENSE', 'LICENCE', 'NOTICE', 'COPYING', 'COPYRIGHT', 'OFL'))
            or name in ('ATTRIBUTION.MD', 'ASSETS.MD')
            or any(part.upper() in ('LICENSES', 'LICENCES') for part in PurePosixPath(value).parts[:-1]))


def regular(path, maximum=8 << 20, allow_empty=False):
    if (path.is_symlink() or not path.is_file()
            or not (0 if allow_empty else 1) <= path.stat().st_size <= maximum):
        raise ValueError('dependency input must be a bounded regular file')
    data = path.read_bytes()
    if len(data) != path.stat().st_size:
        raise ValueError('dependency input changed during reading')
    return data


def owned(root, path):
    path = path.absolute()
    relative = path.relative_to(root.absolute())
    if '..' in relative.parts:
        raise ValueError('dependency input escapes its explicit root')
    current = root.absolute()
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('dependency input traverses a symlink')
    return path


def declaration(package, workspace=None):
    def field(name):
        value = package.get(name)
        if value == {'workspace': True}:
            value = (workspace or {}).get(name)
        if value is not None and (not isinstance(value, str) or not value or len(value) > 4096):
            raise ValueError('unsupported dependency declaration')
        return value
    return {name: field(name) for name in ('name', 'version', 'license', 'license-file')}


def registry_package(event, lock, cargo_home):
    identifier = event['package_id']
    origin, identity = identifier.rsplit('#', 1)
    name, version = identity.rsplit('@', 1)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not re.fullmatch(r'[A-Za-z0-9.+_-]+', version):
        raise ValueError('invalid registry identity')
    if origin != 'registry+https://github.com/rust-lang/crates.io-index':
        return None, 'registry_requires_explicit_provenance'
    matches = [p for p in lock['package'] if (p['name'], p['version'], p.get('source')) == (name, version, origin)]
    if len(matches) != 1 or not re.fullmatch('[a-f0-9]{64}', str(matches[0].get('checksum', ''))):
        raise ValueError('compiled registry package is not uniquely checksum-locked')
    checksum = matches[0]['checksum']
    manifest_path = owned(cargo_home, Path(event['manifest_path']))
    location = manifest_path.relative_to(cargo_home).parts
    if (len(location) != 5 or location[:2] != ('registry', 'src')
            or location[3:] != (name + '-' + version, 'Cargo.toml')):
        raise ValueError('compiled registry manifest is outside its package source')
    archive_name = name + '-' + version + '.crate'
    archive_path = cargo_home / 'registry/cache' / location[2] / archive_name
    candidates = [archive_path] if archive_path.exists() else []
    matching = []
    for path in candidates:
        owned(cargo_home, path)
        data = regular(path, 512 << 20)
        if sha(data) == checksum:
            matching.append(data)
    if not matching:
        if candidates:
            raise ValueError('cached registry archive checksum differs from Cargo.lock')
        return {'name': name, 'version': version, 'source': origin, 'checksum': checksum}, 'cached_registry_archive_missing'
    members, total = {}, 0
    prefix = name + '-' + version + '/'
    # Parse exactly the bytes whose checksum was verified, even if the cache is
    # modified concurrently after reading it.
    with tarfile.open(fileobj=io.BytesIO(matching[0]), mode='r:gz') as archive:
        for index, entry in enumerate(archive):
            if index >= 100000:
                raise ValueError('registry archive exceeds entry budget')
            if entry.isdir():
                continue
            if not entry.name.startswith(prefix):
                raise ValueError('registry archive identity differs')
            relative = entry.name[len(prefix):]
            strict_path(relative)
            if relative in members:
                raise ValueError('duplicate registry archive member')
            members[relative] = entry
        manifest = members.get('Cargo.toml')
        if manifest is None or not manifest.isfile() or not 0 < manifest.size <= 1 << 20:
            raise ValueError('registry archive has no bounded manifest')
        manifest_bytes = archive.extractfile(manifest).read()
        if regular(manifest_path) != manifest_bytes:
            raise ValueError('compiled registry manifest differs from the pinned archive')
        declared = declaration(tomllib.loads(manifest_bytes.decode())['package'])
        if (declared['name'], declared['version']) != (name, version):
            raise ValueError('registry declaration differs from locked identity')
        selected = {p for p in members if notice_name(p)}
        if declared['license-file'] is not None:
            selected.add(str(strict_path(declared['license-file'])))
        notices, missing, excerpts = {}, [], {}
        for relative in sorted(selected):
            member = members.get(relative)
            if member is None or not member.isfile():
                missing.append(relative)
                continue
            total += member.size
            if not 0 < member.size <= 8 << 20 or total > 32 << 20:
                raise ValueError('registry notices exceed byte budget')
            notices[relative] = archive.extractfile(member).read()
        for relative, facts in REGISTRY_SOURCE_NOTICES.get((name, version, checksum), {}).items():
            strict_path(relative)
            member = members.get(str(strict_path(facts['source_path'])))
            if member is None or not member.isfile() or not 0 < member.size <= 8 << 20:
                raise ValueError('pinned source notice needs a bounded regular archive member')
            source_bytes = archive.extractfile(member).read()
            if len(source_bytes) != facts['source_bytes'] or sha(source_bytes) != facts['source_sha256']:
                raise ValueError('source notice member differs from its exact source pin')
            offset, length = facts['offset'], facts['bytes']
            if (type(offset) is not int or type(length) is not int or offset < 0
                    or length < 1 or offset + length > len(source_bytes)):
                raise ValueError('source notice excerpt is outside its pinned member')
            excerpt = source_bytes[offset:offset + length]
            if sha(excerpt) != facts['sha256']:
                raise ValueError('source notice excerpt differs from its exact byte pin')
            if relative in notices or relative in members:
                raise ValueError('source notice destination collides with an archive member')
            total += length
            if total > 32 << 20:
                raise ValueError('registry notices exceed byte budget')
            notices[relative] = excerpt
            excerpts[relative] = dict(facts)
    record = {'name': name, 'version': version, 'source': origin, 'checksum': checksum,
            'declaration': declared, 'manifest_sha256': sha(manifest_bytes),
            'notices': notices, 'missing_notices': missing}
    if excerpts:
        record['source_notice_excerpts'] = excerpts
    return record, None


def local_package(event, roots, lock):
    path = Path(event['manifest_path']).absolute()
    selected = [(label, root) for label, root in roots.items() if path.is_relative_to(root)]
    if len(selected) != 1 or path.name != 'Cargo.toml':
        raise ValueError('compiled local manifest is outside its explicit source roots')
    label, root = selected[0]
    owned(root, path)
    package_bytes = regular(path)
    workspace_bytes = regular(root / 'Cargo.toml')
    workspace = tomllib.loads(workspace_bytes.decode()).get('workspace', {}).get('package', {})
    package = tomllib.loads(package_bytes.decode())['package']
    declared = declaration(package, workspace)
    if not declared['name'] or not declared['version']:
        raise ValueError('local package identity is unresolved')
    source_id = event['package_id'].split('#', 1)[0]
    url = urlsplit(source_id.removeprefix('path+'))
    if url.scheme != 'file' or url.netloc or Path(unquote(url.path)) != path.parent:
        raise ValueError('artifact path does not match its Cargo package identity')
    if not any(p['name'] == declared['name'] and p['version'] == declared['version'] and 'source' not in p for p in lock['package']):
        raise ValueError('local compiled package is absent from Cargo.lock')
    chosen = set()
    for parent, directories, names in os.walk(path.parent, followlinks=False):
        # Cargo outputs can have names such as notice-tool. They are not source
        # notices, even when their basename resembles a conventional notice.
        directories[:] = [name for name in directories if name not in ('target', '.git')]
        for name in names:
            item = Path(parent) / name
            if item.is_file() and notice_name(item.relative_to(path.parent).as_posix()):
                chosen.add(item)
    chosen.update(p for p in root.iterdir() if p.is_file() and notice_name(p.name))
    if declared['license-file'] is not None:
        origin = root if package.get('license-file') == {'workspace': True} else path.parent
        chosen.add(origin / strict_path(declared['license-file']))
    notices, missing = {}, []
    for item in sorted(chosen):
        owned(root, item)
        relative = item.relative_to(root).as_posix()
        if not item.is_file():
            missing.append(relative)
        else:
            notices[relative] = regular(item)
    return {'name': declared['name'], 'version': declared['version'], 'source': label,
            'source_path': path.parent.relative_to(root).as_posix(), 'declaration': declared,
            'manifest_sha256': sha(package_bytes), 'workspace_manifest_sha256': sha(workspace_bytes),
            'notices': notices, 'missing_notices': missing}


def git_read(checkout, *arguments):
    environment = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent',
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_NO_LAZY_FETCH': '1'}
    return subprocess.check_output(['/usr/bin/git', '-c', 'protocol.allow=never',
        '-c', 'protocol.file.allow=never', '-c', 'core.hooksPath=/dev/null', *arguments],
        cwd=checkout, env=environment, stderr=subprocess.PIPE, timeout=60)


def git_blob_id(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def git_relative(base, value):
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value or '\0' in value:
        raise ValueError('unsafe Git declaration path')
    parts = [] if base == '.' else list(PurePosixPath(base).parts)
    for part in value.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                raise ValueError('Git declaration escapes its pinned repository')
            parts.pop()
        else:
            parts.append(part)
    return '/'.join(parts) or '.'


def git_snapshot(checkout, revision):
    if git_read(checkout, 'rev-parse', '--verify', 'HEAD').decode().strip() != revision:
        raise ValueError('compiled Git checkout differs from the locked revision')
    tree = git_read(checkout, 'rev-parse', revision + '^{tree}').decode().strip()
    entries = {}; total = 0
    for raw in git_read(checkout, 'ls-tree', '-rz', '--full-tree', revision).split(b'\0'):
        if not raw:
            continue
        metadata, path_bytes = raw.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split(); name = str(strict_path(path_bytes.decode()))
        if (kind != 'blob' or mode not in ('100644', '100755', '120000')
                or not re.fullmatch('[0-9a-f]{40}', oid) or name in entries or len(entries) >= 100000):
            raise ValueError('unsupported pinned Git tree entry')
        path = checkout / name
        # A symlink leaf is verified as a link. Parent traversal is never allowed.
        owned(checkout, path.parent)
        if mode == '120000':
            if not path.is_symlink() or not path.resolve(strict=True).is_relative_to(checkout):
                raise ValueError('Git checkout link is absent or leaves its repository')
            data = os.readlink(path).encode()
        else:
            data = regular(path, 512 << 20, allow_empty=True)
            if bool(path.stat().st_mode & stat.S_IXUSR) != (mode == '100755'):
                raise ValueError('Git checkout executable mode differs')
        total += len(data)
        if total > 2 << 30 or git_blob_id(data) != oid:
            raise ValueError('Git checkout bytes differ from the pinned tree')
        entries[name] = {'mode': mode, 'oid': oid}
    if not entries or not re.fullmatch('[0-9a-f]{40}', tree):
        raise ValueError('empty or invalid pinned Git tree')
    return {'revision': revision, 'tree': tree, 'entries': entries, 'bytes': total, 'blobs': {}}


def git_blob(checkout, snapshot, name, follow_links=False):
    seen = set()
    while True:
        if name in seen or len(seen) >= 16:
            raise ValueError('cyclic Git notice link')
        seen.add(name); entry = snapshot['entries'].get(name)
        if entry is None:
            return None, name
        oid = entry['oid']
        if oid not in snapshot['blobs']:
            data = git_read(checkout, 'cat-file', 'blob', oid)
            if len(data) > 8 << 20 or git_blob_id(data) != oid:
                raise ValueError('Git declaration or notice object differs or exceeds its limit')
            snapshot['blobs'][oid] = data
        data = snapshot['blobs'][oid]
        if entry['mode'] != '120000':
            return data, name
        if not follow_links:
            raise ValueError('Git package manifests must be regular pinned files')
        name = git_relative(str(PurePosixPath(name).parent), data.decode())


def git_package(event, lock, cargo_home, snapshots):
    origin, identity = event['package_id'].rsplit('#', 1)
    name, version = identity.rsplit('@', 1)
    matches = [p for p in lock['package'] if p['name'] == name and p['version'] == version
               and p.get('source', '').rsplit('#', 1)[0] == origin]
    if len(matches) != 1:
        raise ValueError('compiled Git package is not uniquely revision-locked')
    locked = matches[0]['source']; revision = locked.rsplit('#', 1)[-1]
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Git dependency needs an exact locked revision')
    manifest = owned(cargo_home, Path(event['manifest_path']))
    location = manifest.relative_to(cargo_home).parts
    if len(location) < 5 or location[:2] != ('git', 'checkouts') or location[-1] != 'Cargo.toml':
        raise ValueError('compiled Git manifest is outside its Cargo checkout')
    checkout = cargo_home.joinpath(*location[:4])
    key = (str(checkout), revision)
    if key not in snapshots:
        snapshots[key] = git_snapshot(checkout, revision)
    snapshot = snapshots[key]; relative = manifest.relative_to(checkout).as_posix()
    package_bytes, _ = git_blob(checkout, snapshot, relative)
    if package_bytes is None or regular(manifest) != package_bytes:
        raise ValueError('compiled Git manifest differs from its pinned object')
    package = tomllib.loads(package_bytes.decode())['package']
    directory = str(PurePosixPath(relative).parent)
    if 'workspace' in package:
        workspace_directory = git_relative(directory, package['workspace'])
        candidates = [git_relative(workspace_directory, 'Cargo.toml')]
    else:
        candidates = [str(parent / 'Cargo.toml') for parent in PurePosixPath(relative).parents]
    workspace = {}; workspace_bytes = None; workspace_path = None
    for candidate in candidates:
        data, _ = git_blob(checkout, snapshot, candidate)
        if data is not None:
            document = tomllib.loads(data.decode())
            if 'workspace' in document:
                workspace = document['workspace'].get('package', {}); workspace_bytes = data; workspace_path = candidate
                break
    declared = declaration(package, workspace)
    if (declared['name'], declared['version']) != (name, version):
        raise ValueError('Git package declaration differs from its compiler identity')
    workspace_directory = str(PurePosixPath(workspace_path).parent) if workspace_path else '.'
    selected = {p for p in snapshot['entries'] if notice_name(p) and (
        directory == '.' or p.startswith(directory + '/') or '/' not in p
        or str(PurePosixPath(p).parent) == workspace_directory
        or PurePosixPath(p).parts[0].upper() in ('LICENSES', 'LICENCES'))}
    if declared['license-file'] is not None:
        base = workspace_directory if package.get('license-file') == {'workspace': True} else directory
        selected.add(git_relative(base, declared['license-file']))
    notices = {}; missing = []; paths = {}; total = 0
    for relative in sorted(selected):
        data, resolved = git_blob(checkout, snapshot, relative, follow_links=True)
        if not data:
            missing.append(relative); continue
        total += len(data)
        if total > 32 << 20:
            raise ValueError('Git notices exceed byte budget')
        notices[relative] = data
        paths[relative] = {'path': resolved, 'blob': snapshot['entries'][resolved]['oid']}
    return {'name': name, 'version': version, 'source': locked, 'source_path': directory,
        'source_revision': revision, 'source_tree': snapshot['tree'], 'declaration': declared,
        'manifest_sha256': sha(package_bytes), 'workspace_manifest_path': workspace_path,
        'workspace_manifest_sha256': sha(workspace_bytes) if workspace_bytes else None,
        'tracked_checkout_files_verified': len(snapshot['entries']), 'tracked_checkout_bytes_verified': snapshot['bytes'],
        'untracked_inputs_qualified': False, 'git_notice_paths': paths,
        'notice_scope': 'package subtree, workspace/repository root notices and repository notice directories',
        'notices': notices, 'missing_notices': missing}


def collect(messages, source, fonts, cargo_home, output, product):
    source, fonts, cargo_home = (Path(p).absolute() for p in (source, fonts, cargo_home))
    if any(p.is_symlink() or not p.is_dir() or p.resolve() != p for p in (source, fonts, cargo_home)):
        raise ValueError('dependency source roots must be real directories without symlink traversal')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('dependency inventory needs a new output directory')
    lock_bytes = regular(source / 'Cargo.lock', 32 << 20)
    lock = tomllib.loads(lock_bytes.decode())
    artifacts, finished, own_binary = {}, False, False
    with Path(messages).open() as stream:
        for line in stream:
            if len(line) > 8 << 20:
                raise ValueError('Cargo message exceeds byte budget')
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get('reason') == 'build-finished':
                finished = event.get('success') is True
            if event.get('reason') != 'compiler-artifact':
                continue
            key = event['package_id']
            item = artifacts.setdefault(key, {'event': event, 'features': set(), 'target_kinds': set()})
            if len(artifacts) > 10000:
                raise ValueError('Cargo package count exceeds inventory budget')
            if item['event']['manifest_path'] != event['manifest_path']:
                raise ValueError('one package identity has differing manifests')
            item['features'].update(event['features'])
            item['target_kinds'].update(event['target']['kind'])
            if event['target']['name'] == product and 'bin' in event['target']['kind'] and event.get('executable'):
                own_binary = True
    if not finished or not own_binary or not artifacts:
        raise ValueError('Cargo messages do not establish a successful product build')
    records, copied, issues = [], {}, []
    git_snapshots = {}
    for identifier, item in sorted(artifacts.items()):
        if identifier.startswith('registry+'):
            record, issue = registry_package(item['event'], lock, cargo_home)
        elif identifier.startswith('path+'):
            record = local_package(item['event'], {'source': source, 'fonts': fonts}, lock)
            issue = None
        elif identifier.startswith('git+'):
            record = git_package(item['event'], lock, cargo_home, git_snapshots)
            issue = None
        else:
            record, issue = None, 'dependency_source_requires_explicit_provenance'
        if record is None:
            issues.append({'package_id_sha256': sha(identifier.encode()), 'reason': issue})
            continue
        origin = {key: record[key] for key in ('source', 'source_path', 'checksum') if key in record}
        identity = record['name'] + '-' + record['version'] + '-' + sha(json.dumps(origin, sort_keys=True).encode())[:12]
        record['features'] = sorted(item['features'])
        record['target_kinds'] = sorted(item['target_kinds'])
        notices = record.pop('notices', {})
        record['notice_files'] = {}
        for relative, data in notices.items():
            destination = 'packages/' + identity + '/' + str(strict_path(relative))
            copied[destination] = data
            record['notice_files'][destination] = {'bytes': len(data), 'sha256': sha(data)}
        if issue:
            issues.append({'package': identity, 'reason': issue})
        if not record.get('declaration', {}).get('license') and not record.get('declaration', {}).get('license-file'):
            issues.append({'package': identity, 'reason': 'license_declaration_missing'})
        if not notices or record.get('missing_notices'):
            issues.append({'package': identity, 'reason': 'notice_files_missing'})
        records.append(record)
    report = {'schema_version': 1, 'product': product, 'cargo_lock_sha256': sha(lock_bytes),
              'compiler_packages': len(artifacts), 'packages': records, 'issues': issues,
              'notice_collection_complete': not issues, 'binary_linkage_determined': False,
              'redistribution_approved': False, 'network': False,
              'scope': 'Cargo compiler artifacts, including build-time packages; declared notices and explicitly checksum-pinned source notice excerpts only'}
    output.mkdir(parents=True)
    for relative, data in copied.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (output / 'inventory.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def require_inventory(package, manifest):
    """Require complete collected build notices, without approving their terms."""
    package = Path(package).absolute()
    if not package.is_dir() or package.resolve() != package:
        raise ValueError('engine package must be a real directory without symlink traversal')
    metadata = manifest.get('dependencies')
    expected_path = 'notices/dependencies/inventory.json'
    if not isinstance(metadata, dict) or metadata.get('inventory') != expected_path:
        raise ValueError('rebuild the engine with dependency notice capture')
    path = owned(package, package / expected_path)
    data = regular(path, 32 << 20)
    if manifest.get('files', {}).get(expected_path) != {'bytes': len(data), 'sha256': sha(data)}:
        raise ValueError('dependency inventory differs from engine receipt')
    report = json.loads(data)
    if (report.get('schema_version') != 1 or report.get('product') != manifest.get('product')
            or report.get('cargo_lock_sha256') != manifest['source_lock']['cargo_lock_sha256']
            or report.get('notice_collection_complete') is not True or report.get('issues') != []
            or metadata.get('notice_collection_complete') is not True
            or any(record.get(flag) is not False for record in (report, metadata)
                   for flag in ('binary_linkage_determined', 'redistribution_approved'))
            or report.get('network') is not False
            or type(report.get('compiler_packages')) is not int or report['compiler_packages'] < 1
            or metadata.get('compiler_packages') != report['compiler_packages']
            or not isinstance(report.get('packages'), list) or len(report['packages']) != report['compiler_packages']):
        raise ValueError('dependency notice inventory is incomplete or belongs to another build')
    for item in report['packages']:
        if item.get('missing_notices') or not item.get('notice_files') or not (item.get('declaration', {}).get('license') or item.get('declaration', {}).get('license-file')):
            raise ValueError('dependency notice inventory lacks declarations or notice files')
        excerpt_pins = {}
        if item.get('source') == 'registry+https://github.com/rust-lang/crates.io-index':
            excerpt_pins = REGISTRY_SOURCE_NOTICES.get(
                (item.get('name'), item.get('version'), item.get('checksum')), {})
        if item.get('source_notice_excerpts', {}) != excerpt_pins:
            raise ValueError('source notice inventory differs from its pinned provenance')
        excerpts_seen = set()
        git_source = isinstance(item.get('source'), str) and item['source'].startswith('git+')
        if git_source:
            if (not re.fullmatch('[0-9a-f]{40}', item.get('source_revision', ''))
                    or item['source'].rsplit('#', 1)[-1] != item['source_revision']
                    or not re.fullmatch('[0-9a-f]{40}', item.get('source_tree', ''))
                    or type(item.get('tracked_checkout_files_verified')) is not int or item['tracked_checkout_files_verified'] < 1
                    or type(item.get('tracked_checkout_bytes_verified')) is not int or item['tracked_checkout_bytes_verified'] < 1
                    or item.get('untracked_inputs_qualified') is not False
                    or not isinstance(item.get('git_notice_paths'), dict)
                    or set(item['git_notice_paths']) != {'/'.join(strict_path(p).parts[2:]) for p in item['notice_files']}):
                raise ValueError('Git notice inventory lacks exact source provenance')
        for relative, facts in item['notice_files'].items():
            relative = strict_path(relative)
            if relative.parts[0] != 'packages':
                raise ValueError('dependency notice is outside its inventory')
            notice = owned(package, path.parent / relative)
            contents = regular(notice)
            if facts != {'bytes': len(contents), 'sha256': sha(contents)}:
                raise ValueError('dependency notice bytes differ from their inventory')
            source_relative = '/'.join(relative.parts[2:])
            if source_relative in excerpt_pins:
                pin = excerpt_pins[source_relative]
                if facts != {'bytes': pin['bytes'], 'sha256': pin['sha256']}:
                    raise ValueError('source notice bytes differ from their exact byte pin')
                excerpts_seen.add(source_relative)
            if git_source:
                origin = item['git_notice_paths']['/'.join(relative.parts[2:])]
                strict_path(origin['path'])
                if git_blob_id(contents) != origin.get('blob'):
                    raise ValueError('Git notice bytes differ from the pinned blob identity')
        if excerpts_seen != set(excerpt_pins):
            raise ValueError('source notice inventory omits a pinned excerpt')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('messages', 'source', 'fonts', 'cargo-home', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--product', required=True)
    args = parser.parse_args()
    result = collect(args.messages, args.source, args.fonts, args.cargo_home, args.output, args.product)
    print(json.dumps({'compiler_packages': result['compiler_packages'], 'issues': len(result['issues']),
                      'notice_collection_complete': result['notice_collection_complete'],
                      'redistribution_approved': False, 'network': False}))


if __name__ == '__main__':
    main()
