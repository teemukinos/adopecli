#!/usr/bin/env python3
"""Prepare a source checkout so bin/dope can run: Python environment and engines.

Run it through scripts/setup from the repository root. It builds every engine on
this Mac from the pinned public source commits and the maintained patches in
craft/engines/. Nothing prebuilt is downloaded. Finished engines are kept, so a
second run only builds what is missing or out of date.

Layout inside the checkout (all ignored by Git):
  .venv/              Python environment with the pinned packages
  .engines/<family>/  installed engine: bin/dobe-<family>, engine.json, notices
  .build/             fetched sources, Cargo target cache and build logs
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

CRAFT = Path(__file__).resolve().parent
ENGINES = CRAFT / 'engines'
REQUIREMENTS = CRAFT / 'runtime/requirements.txt'
FAMILIES = ('vector', 'image', 'photo', 'video', 'motion', 'audio', 'pdf', 'layout', 'interface',
            'animate', 'texture', 'material', 'write', 'slides', 'cad', 'sheets', 'inspect')


class SetupError(Exception):
    pass


def say(message):
    print('setup: ' + message, flush=True)


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def check_host():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SetupError('this version supports macOS on Apple Silicon only')
    if sys.version_info < (3, 12):
        raise SetupError('Python 3.12 or later is required (brew install python)')
    for tool in ('git', 'rustup'):
        if not shutil.which(tool):
            hint = 'brew install rustup' if tool == 'rustup' else 'xcode-select --install'
            raise SetupError(f'{tool} is missing; install it with: {hint}')
    if subprocess.run(['xcrun', '--find', 'clang'], capture_output=True).returncode:
        raise SetupError('the Xcode command line tools are missing; install them with: xcode-select --install')


def lock(family):
    path = ENGINES / f'{family}.lock.json'
    return json.loads(path.read_bytes()), path


def rust_bin(version):
    run(['rustup', 'toolchain', 'install', version, '--profile', 'minimal'], stdout=subprocess.DEVNULL)
    rustc = subprocess.check_output(['rustup', 'which', '--toolchain', version, 'rustc'], text=True).strip()
    return Path(rustc).parent


def python_env(root):
    venv = root / '.venv'
    python = venv / 'bin/python'
    if not python.exists():
        say('creating the Python environment in .venv')
        try:
            run([os.path.realpath(sys.executable), '-m', 'venv', str(venv)])
        except subprocess.CalledProcessError:
            shutil.rmtree(venv, ignore_errors=True)
            raise SetupError(f'could not create .venv with {sys.executable}; '
                             'install Python from Homebrew (brew install python) and run setup again')
    run([str(python), '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
         '-r', str(REQUIREMENTS)])
    return python


def fetch(source_dir, url, revision):
    repo = source_dir / url.rstrip('/').rsplit('/', 1)[1]
    if not (repo / '.git').exists():
        run(['git', 'init', '--quiet', str(repo)])
    present = subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', revision + '^{commit}'],
                             capture_output=True).returncode == 0
    if not present:
        run(['git', '-C', str(repo), 'fetch', '--quiet', '--depth', '1', url, revision])
    return repo


def installed(root, family, lock_data):
    manifest = root / '.engines' / family / 'engine.json'
    binary = root / '.engines' / family / 'bin' / f'dobe-{family}'
    if not (manifest.is_file() and binary.is_file() and os.access(binary, os.X_OK)):
        return False
    return json.loads(manifest.read_bytes()).get('source_lock') == lock_data


def build(root, family, toolchains, jobs):
    lock_data, _ = lock(family)
    if installed(root, family, lock_data):
        say(f'{family}: already built')
        return 'kept'
    build_dir = root / '.build'
    sources = build_dir / 'src'
    sources.mkdir(parents=True, exist_ok=True)
    say(f'{family}: fetching {lock_data["source"]["url"]} at {lock_data["source"]["revision"][:12]}')
    source = fetch(sources, lock_data['source']['url'], lock_data['source']['revision'])
    fonts = fetch(sources, lock_data['fonts']['url'], lock_data['fonts']['revision'])
    version = lock_data['rust_version']
    if version not in toolchains:
        say(f'installing Rust {version} with rustup')
        toolchains[version] = rust_bin(version)
    output = build_dir / 'out' / family
    if output.exists():
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    log = build_dir / f'{family}.log'
    say(f'{family}: building (log: .build/{family}.log)')
    started = time.monotonic()
    with log.open('wb') as handle:
        result = subprocess.run([sys.executable, '-B', str(ENGINES / 'build_engine.py'), '--engine', family,
                                 '--source', str(source), '--fonts', str(fonts),
                                 '--rust-bin', str(toolchains[version]), '--output', str(output),
                                 '--target-cache', str(build_dir / 'target'), '--fetch', '--public-paths',
                                 '--jobs', str(jobs)], stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SetupError(f'{family} failed to build; see .build/{family}.log')
    package = output / f'dobe-{family}'
    target = root / '.engines' / family
    staging = target.with_name(f'.{family}.new')
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(package, staging, symlinks=True)
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    shutil.rmtree(output)
    say(f'{family}: built in {round(time.monotonic() - started)} s')
    return 'built'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', type=Path, required=True, help='repository root')
    parser.add_argument('--only', help='comma-separated engine families, for example vector,image')
    parser.add_argument('--jobs', type=int, default=max(1, min(16, (os.cpu_count() or 4))),
                        help='parallel Cargo jobs (lower it if the Mac runs out of memory)')
    parser.add_argument('--clean', action='store_true',
                        help='after building, delete .build (fetched sources and the Cargo cache)')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    families = FAMILIES
    if args.only:
        families = tuple(name.strip() for name in args.only.split(',') if name.strip())
        unknown = sorted(set(families) - set(FAMILIES))
        if unknown:
            parser.error('unknown engine families: ' + ', '.join(unknown))
    try:
        check_host()
        python_env(root)
        toolchains, results = {}, {}
        for family in families:
            results[family] = build(root, family, toolchains, max(1, min(16, args.jobs)))
    except (SetupError, subprocess.CalledProcessError) as error:
        print('setup: ' + str(error), file=sys.stderr)
        return 1
    if args.clean and (root / '.build').exists():
        shutil.rmtree(root / '.build')
    ready = [family for family in FAMILIES if (root / '.engines' / family / 'engine.json').is_file()]
    say(f'ready: {len(ready)} of {len(FAMILIES)} engines ({", ".join(ready)})')
    say('next: bin/dope doctor, then connect your agent (see README)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
