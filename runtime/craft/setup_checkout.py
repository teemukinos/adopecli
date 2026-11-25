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
from contextlib import contextmanager
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

CRAFT = Path(__file__).resolve().parent
ENGINES = CRAFT / 'engines'
REQUIREMENTS = CRAFT / 'runtime/requirements.txt'
FAMILIES = ('vector', 'image', 'photo', 'video', 'motion', 'audio', 'pdf', 'layout', 'interface',
            'animate', 'texture', 'material', 'write', 'slides', 'cad', 'sheets', 'inspect')


class SetupError(Exception):
    def __init__(self, message, log=None):
        super().__init__(message)
        self.log = log


def duration(seconds):
    seconds = round(seconds)
    if seconds < 60:
        return f'{seconds} s'
    minutes, seconds = divmod(seconds, 60)
    return f'{minutes} min {seconds} s' if minutes < 60 else f'{minutes // 60} h {minutes % 60} min'


class Output:
    """Terminal output: a live line with a spinner on a terminal, plain lines elsewhere."""
    FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    def __init__(self, stream=sys.stdout):
        self.stream = stream
        self.live = stream.isatty() and os.environ.get('TERM') != 'dumb'
        self.color = self.live and 'NO_COLOR' not in os.environ
        self.lock = threading.Lock()

    def paint(self, code, text):
        return f'\033[{code}m{text}\033[0m' if self.color else text

    def bold(self, text): return self.paint('1', text)
    def dim(self, text): return self.paint('2', text)
    def green(self, text): return self.paint('32', text)
    def red(self, text): return self.paint('31', text)
    def cyan(self, text): return self.paint('36', text)

    def line(self, text=''):
        with self.lock:
            self.stream.write(text + '\n')
            self.stream.flush()

    @contextmanager
    def step(self, label):
        """Show a running step; the body may call status(text) and set result['done']."""
        state = {'text': label, 'done': None}
        started = time.monotonic()
        stop = threading.Event()

        def spin():
            frame = 0
            while not stop.wait(0.1):
                elapsed = time.monotonic() - started
                clock = f'{int(elapsed) // 60}:{int(elapsed) % 60:02d}'
                with self.lock:
                    self.stream.write(f'\r\033[K  {self.cyan(self.FRAMES[frame % len(self.FRAMES)])} '
                                      f'{state["text"]}  {self.dim(clock)}')
                    self.stream.flush()
                frame += 1

        def status(text):
            state['text'] = text
            if not self.live:
                self.line(f'  ... {text}')

        if self.live:
            spinner = threading.Thread(target=spin, daemon=True)
            spinner.start()
        else:
            self.line(f'  ... {label}')
        ok = False
        try:
            yield status, state
            ok = True
        finally:
            stop.set()
            if self.live:
                spinner.join()
                with self.lock:
                    self.stream.write('\r\033[K')
            mark = self.green('✓') if ok else self.red('✗')
            detail = state['done'] or ('' if ok else 'failed after ' + duration(time.monotonic() - started))
            self.line(f'  {mark} {label}' + (f'  {self.dim(detail)}' if detail else ''))


out = Output()


def run(command, log=None, **kwargs):
    """Run a command; with log, its output goes there and is shown if it fails."""
    if log is None:
        return subprocess.run(command, check=True, **kwargs)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('ab') as handle:
        result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, **kwargs)
    if result.returncode:
        raise SetupError(f'{shlex.join(str(part) for part in command[:3])} ... failed', log)
    return result


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


def rust_bin(version, log):
    run(['rustup', 'toolchain', 'install', version, '--profile', 'minimal'], log=log)
    rustc = subprocess.check_output(['rustup', 'which', '--toolchain', version, 'rustc'], text=True).strip()
    return Path(rustc).parent


def python_env(root):
    venv = root / '.venv'
    python = venv / 'bin/python'
    log = root / '.build' / 'python.log'
    with out.step('Python environment') as (status, state):
        if not python.exists():
            status('Python environment: creating .venv')
            try:
                run([os.path.realpath(sys.executable), '-m', 'venv', str(venv)], log=log)
            except SetupError:
                shutil.rmtree(venv, ignore_errors=True)
                raise SetupError(f'could not create .venv with {sys.executable}; '
                                 'install Python from Homebrew (brew install python) and run setup again', log)
        status('Python environment: installing packages')
        run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
             '-r', str(REQUIREMENTS)], log=log)
        state['done'] = '.venv'
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


def build(root, family, toolchains, jobs, label):
    lock_data, _ = lock(family)
    if installed(root, family, lock_data):
        out.line(f'  {out.green("✓")} {label}  {out.dim("already built")}')
        return 'kept'
    build_dir = root / '.build'
    sources = build_dir / 'src'
    sources.mkdir(parents=True, exist_ok=True)
    version = lock_data['rust_version']
    if version not in toolchains:
        with out.step(f'Rust {version}') as (status, state):
            toolchains[version] = rust_bin(version, build_dir / 'rust.log')
            state['done'] = 'ready'
    with out.step(label) as (status, state):
        status(f'{label}  fetching source')
        source = fetch(sources, lock_data['source']['url'], lock_data['source']['revision'])
        fonts = fetch(sources, lock_data['fonts']['url'], lock_data['fonts']['revision'])
        output = build_dir / 'out' / family
        if output.exists():
            shutil.rmtree(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        log = build_dir / f'{family}.log'
        log.unlink(missing_ok=True)
        status(f'{label}  compiling')
        started = time.monotonic()
        try:
            run([sys.executable, '-B', str(ENGINES / 'build_engine.py'), '--engine', family,
                 '--source', str(source), '--fonts', str(fonts),
                 '--rust-bin', str(toolchains[version]), '--output', str(output),
                 '--target-cache', str(build_dir / 'target'), '--fetch', '--public-paths',
                 '--jobs', str(jobs)], log=log)
        except SetupError as error:
            raise SetupError(f'the {family} engine failed to build', error.log) from None
        state['done'] = 'built in ' + duration(time.monotonic() - started)
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
    return 'built'


def show_failure(error, root):
    out.line()
    out.line(out.red(out.bold('Setup stopped: ')) + str(error))
    log = getattr(error, 'log', None)
    if log and log.is_file():
        lines = log.read_text(errors='replace').splitlines()[-15:]
        out.line(out.dim(f'Last lines of {log.relative_to(root) if log.is_relative_to(root) else log}:'))
        for text in lines:
            out.line(out.dim('  ' + text))
    out.line()
    out.line('Fix the problem and run scripts/setup again. Engines that finished are kept.')


def show_next_steps(root):
    dope = shlex.quote(str(root / 'bin' / 'dope'))
    out.line()
    out.line(out.bold('Next steps'))
    out.line(f'  1. Check the install      {out.cyan("bin/dope doctor")}')
    out.line(f'  2. Connect your agent')
    out.line(f'     Claude Code            {out.cyan(f"claude mcp add --scope user dope -- {dope} mcp")}')
    out.line(f'     Codex                  {out.cyan(f"codex mcp add dope -- {dope} mcp")}')
    out.line(f'  3. Restart the agent and ask it to run {out.cyan("dope_capabilities")}.')
    out.line()
    out.line(f'From the terminal: {out.cyan("bin/dope help")} lists the commands, '
             f'{out.cyan("bin/dope capabilities")} what it can make.')


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
    started = time.monotonic()
    pending = [family for family in families if not installed(root, family, lock(family)[0])]
    out.line()
    out.line(out.bold('A dope CLI setup'))
    if not pending:
        out.line(out.dim(f'All {len(families)} engines are already built. Checking the Python environment.'))
    else:
        if len(pending) == len(FAMILIES):
            estimate = ' The first full build takes about 40 minutes.'
        else:
            estimate = ''
        out.line(out.dim(f'Builds {len(pending)} of {len(families)} engines on this Mac from source.{estimate}'))
        out.line(out.dim('You can leave it running. Build logs go to .build/; '
                         'if you stop it, run scripts/setup again to continue.'))
    out.line()
    width = max(len(family) for family in families)
    try:
        with out.step('Mac and tools') as (status, state):
            check_host()
            state['done'] = f'macOS arm64, Python {platform.python_version()}'
        python_env(root)
        toolchains = {}
        if not pending:
            out.line(f'  {out.green("✓")} Engines  {out.dim(f"all {len(families)} already built")}')
            families = ()
        for number, family in enumerate(families, 1):
            label = f'{out.dim(f"[{number:>{len(str(len(families)))}}/{len(families)}]")} {family:<{width}}'
            build(root, family, toolchains, max(1, min(16, args.jobs)), label)
    except (SetupError, subprocess.CalledProcessError) as error:
        show_failure(error, root)
        return 1
    except KeyboardInterrupt:
        out.line()
        out.line('Stopped. Run scripts/setup again to continue; engines that finished are kept.')
        return 130
    if args.clean and (root / '.build').exists():
        shutil.rmtree(root / '.build')
        out.line(f'  {out.green("✓")} Removed the build cache (.build)')
    ready = [family for family in FAMILIES if (root / '.engines' / family / 'engine.json').is_file()]
    out.line()
    if len(ready) == len(FAMILIES):
        out.line(out.green(out.bold(f'Done in {duration(time.monotonic() - started)}.')) +
                 f' All {len(FAMILIES)} engines are ready.')
    else:
        missing = [family for family in FAMILIES if family not in ready]
        out.line(out.green(out.bold(f'Done in {duration(time.monotonic() - started)}.')) +
                 f' {len(ready)} of {len(FAMILIES)} engines are ready.')
        out.line(out.dim('Not built yet: ' + ', '.join(missing) + '. Run scripts/setup to build them.'))
    show_next_steps(root)
    return 0


if __name__ == '__main__':
    sys.exit(main())
