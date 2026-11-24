"""Private Apple linker evidence, not a complete linkage or rights decision."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

MAX_BYTES = 256 * 1024 * 1024
MAX_LINE = 2 * 1024 * 1024


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(path, root):
    path, root = Path(path), Path(root).resolve()
    if not path.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('link evidence file escapes its declared root or is a symlink')
    if not path.is_file():
        raise ValueError('link evidence file is missing')
    return path.resolve()


def rustc_options(host, path):
    if host != 'aarch64-apple-darwin':
        raise ValueError('link-map capture currently requires macOS ARM64')
    path = str(Path(path).resolve())
    if any(char in path for char in (',', '\n', '\r', '\x00')):
        raise ValueError('link-map output path cannot contain commas or line breaks')
    # cargo rustc applies these arguments only to the selected final target.
    # Global RUSTFLAGS would also overwrite the map from build-script links.
    return ['--', '-C', 'link-arg=-Wl,-map,' + path]


def parse_map(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('link map exceeds the supported byte limit')
    objects, headers, seen = {}, {}, []
    live, dead = Counter(), Counter()
    state = None
    transitions = {b'# Object files:': 'objects', b'# Sections:': 'sections',
                   b'# Symbols:': 'live', b'# Dead Stripped Symbols:': 'dead'}
    with path.open('rb') as stream:
        while line := stream.readline(MAX_LINE + 1):
            if len(line) > MAX_LINE:
                raise ValueError('link-map line exceeds the supported byte limit')
            line = line.removesuffix(b'\n')
            if not line:
                continue
            if line.startswith((b'# Path: ', b'# Arch: ')):
                key, value = line[2:].split(b': ', 1)
                if state is not None or key in headers:
                    raise ValueError('duplicate or misplaced link-map header')
                headers[key] = value.decode('utf-8')
            elif line in transitions:
                state = transitions[line]
                expected = ['objects', 'sections', 'live', 'dead']
                if len(seen) >= len(expected) or state != expected[len(seen)]:
                    raise ValueError('unexpected link-map section order')
                seen.append(state)
            elif line.startswith(b'#'):
                allowed = {
                    'sections': b'# Address\tSize    \tSegment\tSection',
                    'live': b'# Address\tSize    \tFile  Name',
                    'dead': b'#        \tSize    \tFile  Name',
                }
                if line != allowed.get(state):
                    raise ValueError('unknown link-map header')
            elif state == 'objects':
                match = re.fullmatch(rb'\[\s*(\d+)\] (.+)', line)
                if not match or int(match[1]) in objects:
                    raise ValueError('malformed or duplicate link-map object')
                objects[int(match[1])] = match[2].decode('utf-8')
            elif state == 'sections':
                if not re.fullmatch(rb'0x[\dA-Fa-f]+\s+0x[\dA-Fa-f]+\s+\S+\s+\S+', line):
                    raise ValueError('malformed link-map section')
            elif state in ('live', 'dead'):
                # Apple ld emits arbitrary literal bytes as symbol labels. Read
                # the structural prefix as bytes; never decode or reinterpret
                # opaque labels as paths, headers or license text.
                prefix = rb'0x[\dA-Fa-f]+' if state == 'live' else rb'<<dead>>'
                match = re.match(prefix + rb'\s+0x[\dA-Fa-f]+\s+\[\s*(\d+)\] ', line)
                if not match or int(match[1]) not in objects:
                    raise ValueError('malformed symbol or unknown object reference')
                (live if state == 'live' else dead)[int(match[1])] += 1
            else:
                raise ValueError('link-map data appears before its section')
    if (set(headers) != {b'Path', b'Arch'} or headers[b'Arch'] != 'arm64'
            or seen[:3] != ['objects', 'sections', 'live']
            or objects.get(0) != 'linker synthesized' or not live):
        raise ValueError('incomplete or unsupported Apple link map')
    return {'binary_path': headers[b'Path'], 'architecture': headers[b'Arch'],
            'objects': objects, 'live': live, 'dead': dead}


def collect(map_path, messages_path, binary, target, toolchain):
    """Bind one final binary and selected archive paths to compiler evidence.

    The report retains local paths and belongs outside the distributed pack.
    Unmapped objects, toolchain archives and SDK stubs remain explicit.
    """
    target, toolchain = Path(target).resolve(), Path(toolchain).resolve()
    binary = regular(binary, target)
    parsed = parse_map(map_path)
    linked_binary = regular(parsed['binary_path'], target)
    binary_hash = digest(binary)
    if digest(linked_binary) != binary_hash or linked_binary.stat().st_size != binary.stat().st_size:
        raise ValueError('link map does not describe the packaged binary bytes')
    messages_path = Path(messages_path)
    if not 0 < messages_path.stat().st_size <= MAX_BYTES:
        raise ValueError('compiler evidence exceeds the supported byte limit')
    artifacts, packages, finals = {}, set(), []
    finished = False
    with messages_path.open('rb') as stream:
        while line := stream.readline(MAX_LINE + 1):
            if len(line) > MAX_LINE:
                raise ValueError('compiler evidence line exceeds the supported byte limit')
            event = json.loads(line)
            if event.get('reason') == 'build-finished':
                if finished or event.get('success') is not True:
                    raise ValueError('compiler evidence has a failed or duplicate finish')
                finished = True
            elif event.get('reason') == 'compiler-artifact':
                if finished:
                    raise ValueError('compiler artifact appears after build completion')
                package = event['package_id']
                packages.add(package)
                for name in event.get('filenames', []):
                    if Path(name).suffix not in ('.rlib', '.a'):
                        continue
                    path = str(regular(name, target))
                    if path in artifacts and artifacts[path] != package:
                        raise ValueError('ambiguous compiler artifact ownership')
                    artifacts[path] = package
                if event.get('executable') and Path(event['executable']).resolve() == binary:
                    if event.get('target', {}).get('kind') != ['bin'] or event.get('fresh') is not False:
                        raise ValueError('link-map capture requires a freshly linked binary target')
                    finals.append(package)
    if not finished or len(finals) != 1:
        raise ValueError('compiler evidence does not bind exactly one completed binary')
    rows, archives = [], {}
    selected, live_packages = set(), set()
    for index, name in parsed['objects'].items():
        row = {'index': index, 'linker_input': name,
               'live_symbol_records': parsed['live'][index],
               'dead_symbol_records': parsed['dead'][index]}
        member = re.fullmatch(r'(.*\.(?:rlib|a))\((.+)\)', name)
        if member:
            path = Path(member[1])
            canonical = str(path.resolve())
            row['archive_member'] = member[2]
            if canonical in artifacts:
                regular(path, target)
                row.update(kind='cargo_archive_member', package_id=artifacts[canonical])
                selected.add(artifacts[canonical])
                if parsed['live'][index]:
                    live_packages.add(artifacts[canonical])
            elif path.is_absolute() and path.resolve().is_relative_to(toolchain):
                regular(path, toolchain)
                row['kind'] = 'toolchain_archive_member'
            elif path.is_absolute() and path.resolve().is_relative_to(target):
                regular(path, target)
                row['kind'] = 'unattributed_build_archive_member'
            else:
                row['kind'] = 'unresolved_archive_member'
            if row['kind'] != 'unresolved_archive_member':
                if canonical not in archives:
                    archives[canonical] = {'path': canonical, 'bytes': path.stat().st_size,
                                           'sha256': digest(path)}
                row['archive_path'] = canonical
        elif index == 0:
            row['kind'] = 'linker_synthesized'
        elif name.endswith('.tbd'):
            row['kind'] = 'linker_stub'
        else:
            # Cargo may remove temporary .o files before emitting build-finished.
            # Do not infer their crate ownership from a filename resemblance.
            row['kind'] = 'unattributed_object'
        rows.append(row)
    for entry in archives.values():
        if digest(Path(entry['path'])) != entry['sha256']:
            raise ValueError('archive changed during link evidence capture')
    if digest(binary) != binary_hash or digest(linked_binary) != binary_hash:
        raise ValueError('binary changed during link evidence capture')
    return {'schema_version': 1, 'format': 'apple-ld-map',
            'scope': 'Partial private link evidence; not complete linkage or a distribution decision.',
            'binary': {'path': str(binary), 'bytes': binary.stat().st_size, 'sha256': binary_hash},
            'linker_output_path': str(linked_binary),
            'map': {'bytes': Path(map_path).stat().st_size, 'sha256': digest(Path(map_path))},
            'compiler_messages_sha256': digest(messages_path),
            'final_binary_package_id': finals[0], 'compiler_packages': len(packages),
            'objects': rows, 'archives': sorted(archives.values(), key=lambda x: x['path']),
            'summary': {'object_records': len(rows), 'live_symbol_records': sum(parsed['live'].values()),
                        'dead_symbol_records': sum(parsed['dead'].values()),
                        'object_kinds': dict(sorted(Counter(x['kind'] for x in rows).items())),
                        'cargo_packages_with_archive_members': len(selected),
                        'cargo_packages_with_live_archive_symbols': len(live_packages)},
            'packages_without_mapped_archive_members': sorted(packages - selected),
            'limitations': ['Unmapped package IDs are not proof of absence from the binary.',
                            'Archive hashes bind containers; member bytes and symbol ranges are not extracted.',
                            'Toolchain archives, SDK stubs, LTO and temporary objects need separate provenance.',
                            'This map does not capture runtime-loaded libraries or complete source/asset obligations.',
                            'Symbol counts are records, not nonoverlapping byte coverage.',
                            'Notice requirements are not reduced by this report.'],
            'binary_linkage_determined': False, 'redistribution_approved': False}
