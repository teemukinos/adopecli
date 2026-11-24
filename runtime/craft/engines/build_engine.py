#!/usr/bin/env python3
"""Build a private Dobe native engine from pinned source and a reviewed patch.

Inputs are existing local Git checkouts. The build uses archived commits, never
the checkout's working files. Cargo network access is disabled unless --fetch
is explicitly supplied. This command does not install or deploy its output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tarfile
import time
import sys
# Admit only the helper beside this trusted build script, including under -I.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dependency_notices import collect as collect_dependency_notices


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive_commit(checkout, revision, target):
    if subprocess.check_output(['git', 'rev-parse', revision + '^{commit}'], cwd=checkout, text=True).strip() != revision:
        raise ValueError('source revision must be an exact commit')
    target.mkdir()
    archive = target.parent / (target.name + '.tar')
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', '--format=tar', revision], cwd=checkout, stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(target, filter='data')
    archive.unlink()


def main():
    if sys.version_info < (3, 12):
        raise SystemExit('native engine builds require Python 3.12 or newer')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('image', 'video', 'motion', 'vector', 'audio', 'photo', 'pdf', 'layout', 'interface', 'animate', 'texture', 'material', 'write', 'slides', 'cad', 'sheets', 'inspect'), default='image')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fonts', type=Path, required=True)
    parser.add_argument('--rust-bin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-cache', type=Path)
    parser.add_argument('--profile', choices=('dev', 'release'), default='release')
    parser.add_argument('--jobs', type=int, choices=range(1, 17), default=4, help='Maximum concurrent Cargo jobs (1 reduces build memory pressure)')
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--link-map', action='store_true',
                        help='Capture private Apple linker evidence for the final macOS ARM64 binary')
    parser.add_argument('--public-paths', action='store_true',
                        help='Normalize compiler paths and refuse developer paths in the packaged executable')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    lock_path = here / (args.engine + '.lock.json')
    product = 'dobe-' + args.engine
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    lock_digest = hashlib.sha256(lock_bytes).hexdigest()
    patch = here / lock['patch']['file']
    if sha256(patch) != lock['patch']['sha256']:
        raise ValueError('engine patch checksum mismatch')
    rust_bin = args.rust_bin.resolve()
    compiler = subprocess.check_output([str(rust_bin / 'rustc'), '-vV'], text=True)
    if 'release: ' + lock['rust_version'] + '\n' not in compiler:
        raise ValueError('engine build requires the locked Rust version')
    host = next(line.removeprefix('host: ') for line in compiler.splitlines() if line.startswith('host: '))
    if host not in ('aarch64-apple-darwin', 'x86_64-unknown-linux-gnu'):
        raise ValueError('unsupported build host; use macOS ARM64 or Linux x86-64')
    output = args.output.resolve()
    extra_link_options = []
    if args.link_map:
        from link_map import collect as collect_link_map, rustc_options as link_map_options
        extra_link_options = link_map_options(host, output / 'link.map')
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    fonts = output / 'fonts'
    archive_commit(args.source.resolve(), lock['source']['revision'], source)
    archive_commit(args.fonts.resolve(), lock['fonts']['revision'], fonts)
    # A nested archive can otherwise inherit the caller's Git worktree prefix,
    # causing git apply to silently skip every path as outside that prefix.
    subprocess.run(['git', 'init', '--quiet', '--initial-branch=codex/dobe-build'], cwd=source, check=True)
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=source, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=source, check=True)
    for name, expected in lock['patched_files'].items():
        if sha256(source / name) != expected:
            raise ValueError('patched source checksum mismatch: ' + name)
    if sha256(source / 'Cargo.lock') != lock['cargo_lock_sha256']:
        raise ValueError('Cargo dependency lock checksum mismatch')
    target = args.target_cache.resolve() if args.target_cache else output / 'target'
    env = dict(os.environ)
    # Build inputs are explicit. Personal compiler wrappers and cargo flags must
    # not silently change the recorded artifact.
    for name in ('RUSTFLAGS', 'RUSTC', 'RUSTDOC', 'RUSTDOCFLAGS', 'CARGO_BUILD_TARGET',
                 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER',
                 'PHOTOCRAFT_OVERRIDE_VERSION', 'PHOTOCRAFT_BUILD_SHA', 'PHOTOCRAFT_BUILD_DATE', 'PDFCRAFT_BUILD_LABEL',
                 'TEXTURECRAFT_BUILD_SHA', 'TEXTURECRAFT_BUILD_DATE', 'MATERIALCRAFT_BUILD_SHA', 'MATERIALCRAFT_BUILD_DATE', 'WORDCRAFT_BUILD_SHA', 'CADCRAFT_BUILD_SHA',
                 'FIGCRAFT_EMBED_CJK', 'FIGCRAFT_EMBED_SCRIPTS', 'FIGCRAFT_WEB_FONTS'):
        env.pop(name, None)
    env.update({'PATH': str(rust_bin) + ':/usr/bin:/bin', 'CARGO_TARGET_DIR': str(target),
                'CARGO_NET_OFFLINE': 'false' if args.fetch else 'true', 'CARGO_BUILD_JOBS': str(args.jobs), 'CRAFT_FONTS_DIR': str(fonts),
                'PHOTOCRAFT_BUILD_SHA': lock['source']['revision'],
                'TEXTURECRAFT_BUILD_SHA': lock['source']['revision'],
                'MATERIALCRAFT_BUILD_SHA': lock['source']['revision'],
                'WORDCRAFT_BUILD_SHA': lock['source']['revision'],
                'CADCRAFT_BUILD_SHA': lock['source']['revision'],
                'SOURCE_DATE_EPOCH': str(lock['source_date_epoch'])})
    if args.public_paths:
        # Keep these flags equal across sibling engine builds so a shared target
        # cache can reuse dependencies. The most specific mapping is last.
        remaps = [(str(Path.home()), '/build/home'), (str(output.parent), '/build/work')]
        env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(
            ['--remap-path-prefix=' + before + '=' + after for before, after in remaps]
            + ['-C', 'debuginfo=0', '-C', 'strip=symbols'])
        native_flags = shlex.join('-ffile-prefix-map=' + before + '=' + after for before, after in remaps)
        env['CFLAGS'] = native_flags
        env['CXXFLAGS'] = native_flags
    if host == 'aarch64-apple-darwin':
        env['MACOSX_DEPLOYMENT_TARGET'] = '12.0'
        # rust-objcopy's macOS rpath does not find the toolchain's shared LLVM
        # library on this toolchain. Scope the lookup to build subprocesses.
        env['DYLD_FALLBACK_LIBRARY_PATH'] = str(rust_bin.parent / 'lib')
    if args.engine == 'write':
        # A personal language-pack checkout is not a pinned build input.
        for name in ('CRAFT_I18N_DIR', 'CRAFT_I18N_REQUIRED', 'CRAFT_PROOF_EMBED'):
            env.pop(name, None)
    if args.engine in ('video', 'motion', 'photo', 'pdf', 'layout', 'interface', 'animate', 'write', 'slides', 'cad'):
        env['CRAFT_FONTS_REQUIRED'] = '1'
    crate = {'image': 'photocraft-cli', 'video': 'filmcraft-cli', 'motion': 'effectcraft-cli', 'vector': 'vectorcraft-cli', 'audio': 'soundcraft-cli', 'photo': 'lightcraft-cli', 'pdf': 'pdfcraft-cli', 'layout': 'designcraft-cli', 'interface': 'figcraft-cli', 'animate': 'anicraft-cli', 'texture': 'texturecraft-cli', 'material': 'materialcraft-cli', 'write': 'wordcraft-cli', 'slides': 'deckcraft-cli', 'cad': 'cadcraft-cli', 'sheets': 'gridcraft-cli', 'inspect': 'dobe-inspect'}[args.engine]
    command = [str(rust_bin / 'cargo'), 'rustc' if args.link_map else 'build', '--locked', '-p', crate,
               '--no-default-features', '--features', 'dobe', '--bin', product,
               '--message-format=json-render-diagnostics']
    if not args.fetch:
        command.append('--offline')
    if args.profile == 'release':
        command.append('--release')
    command.extend(extra_link_options)
    started = time.monotonic()
    messages = output / 'cargo-messages.jsonl'
    with (output / 'build.log').open('w') as diagnostics, messages.open('w') as stream:
        subprocess.run(command, cwd=source, env=env, stdout=stream, stderr=diagnostics, check=True)
    package = output / product
    (package / 'bin').mkdir(parents=True)
    binary = target / ('release' if args.profile == 'release' else 'debug') / product
    shutil.copy2(binary, package / 'bin' / product)
    if args.public_paths:
        binary_bytes = (package / 'bin' / product).read_bytes()
        if any(value.encode() in binary_bytes for value in (str(Path.home()), str(output.parent))):
            raise ValueError('public executable still contains a developer path; retain this failed build and inspect its source')
    notices = package / 'notices'
    for root, label in ((source, args.engine + '-source'), (fonts, 'fonts')):
        for path in sorted(root.rglob('*')):
            if path.is_file() and (path.name.startswith(('LICENSE', 'OFL', 'NOTICE')) or path.name in ('ATTRIBUTION.md', 'ASSETS.md')):
                destination = notices / label / path.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    dependencies = collect_dependency_notices(messages, source, fonts,
        Path(env.get('CARGO_HOME', Path.home() / '.cargo')).resolve(), notices / 'dependencies', product)
    version = subprocess.check_output([str(package / 'bin' / product), '--version'], env=env, text=True).strip()
    if not (version == product + ' ' + lock['engine_version'] or version.startswith(product + ' ' + lock['engine_version'] + ' ')):
        raise ValueError('built engine identity differs from the lock')
    if args.link_map:
        linkage = collect_link_map(output / 'link.map', messages, binary, target, rust_bin.parent)
        if linkage['binary']['sha256'] != sha256(package / 'bin' / product):
            raise ValueError('link evidence differs from the distributed executable')
        (output / 'link-map.json').write_text(json.dumps(linkage, indent=2, sort_keys=True) + '\n')
    manifest = {'schema_version': 1, 'product': product, 'host': host,
                'profile': args.profile, 'qualification': 'development-not-release-qualified',
                'version': version, 'compiler': compiler, 'cargo_jobs': args.jobs, 'build_seconds': time.monotonic() - started,
                'source_lock': lock, 'source_lock_sha256': lock_digest,
                'dependencies': {'inventory': 'notices/dependencies/inventory.json',
                                 'compiler_packages': dependencies['compiler_packages'],
                                 'notice_collection_complete': dependencies['notice_collection_complete'],
                                 'binary_linkage_determined': False, 'redistribution_approved': False},
                'features': ['dobe'], 'gpu': False if args.engine in ('image', 'vector', 'audio', 'pdf', 'layout', 'interface', 'animate', 'texture', 'material', 'write', 'slides', 'cad', 'inspect') else 'native optional; runtime exports request CPU', 'files': {}}
    if args.public_paths:
        manifest['public_path_normalization'] = {'schema_version': 1,
            'rust_prefix_remapping': True, 'native_prefix_remapping': True,
            'debug_symbols_stripped': True, 'developer_paths_absent': True}
    for path in sorted(package.rglob('*')):
        if path.is_file():
            manifest['files'][path.relative_to(package).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha256(path)}
    (package / 'engine.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'package': str(package), 'version': version, 'profile': args.profile,
                      'binary_sha256': sha256(package / 'bin' / product)}))


if __name__ == '__main__':
    main()
