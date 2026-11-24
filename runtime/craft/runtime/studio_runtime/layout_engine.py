"""Private headless Layout transport and native publication checks.

Only typed runtime adapters may use this transport. It is not an arbitrary
command endpoint, and does not register Layout as a finished capability.
"""
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading

from . import layout_document, photo, vector

VERSION = '0.20.1'


class Engine(vector.Engine):
    label = 'Layout'

    def __init__(self, root, *, executable=None):
        self.root = Path(root).resolve()
        executable = executable if executable is not None else shutil.which('dobe-layout')
        if executable is None:
            raise ValueError('maintained Dobe Layout engine is not installed')
        self.home = tempfile.TemporaryDirectory(prefix='.layout-home-', dir=self.root)
        env = {'PATH': '/usr/bin:/bin', 'HOME': self.home.name, 'TMPDIR': self.home.name,
               'XDG_CONFIG_HOME': self.home.name, 'XDG_CACHE_HOME': self.home.name, 'LANG': 'en_US.UTF-8'}
        try:
            self.proc = subprocess.Popen([executable, 'mcp', '--automation-read-root', str(self.root),
                                          '--automation-write-root', str(self.root)], cwd=self.root, env=env,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        except BaseException:
            self.home.cleanup()
            raise
        self.messages = queue.Queue(maxsize=2); self.counter = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            reply = self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                            'clientInfo': {'name': 'dobe-runtime', 'version': '0.1.0'}})
            if reply.get('serverInfo') != {'name': 'dobe-layout', 'title': 'Dobe Layout', 'version': VERSION}:
                raise ValueError('Layout engine identity is not qualified')
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            while True:
                line = self.proc.stdout.readline(16 << 20)
                if not line or not line.endswith('\n'):
                    break
                try:
                    value = json.loads(line)
                except ValueError:
                    break
                if not isinstance(value, dict):
                    break
                self.messages.put(value)
        finally:
            self.messages.put(None)

    def tool(self, name, **args):
        result = self.call('tools/call', {'name': name, 'arguments': args})
        content = result.get('content', [])
        if result.get('isError'):
            raise ValueError('Layout engine refused ' + name + ': ' + str(content)[:1200])
        if len(content) != 1 or content[0].get('type') != 'text':
            raise ValueError('Layout engine omitted its structured result')
        return layout_document.strict_json(content[0]['text'])

    def command(self, name, **params):
        result = self.tool('execute', command=name, params=params)
        if isinstance(result, dict) and result.get('warnings'):
            raise ValueError('Layout command reported warnings: ' + str(result['warnings'])[:1200])
        return result

    def relative(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ValueError('Layout output or input must not be a symbolic link')
        return str(path.resolve().relative_to(self.root))

    def open(self, path):
        profile = layout_document.read_native(path)
        self.command('file.open', path=self.relative(path))
        return profile

    def save(self, path):
        self.command('file.saveAs', path=self.relative(path))
        return layout_document.read_native(path)

    def preflight(self):
        result = self.tool('execute', command='preflight.run', params={'minPpi': 72})
        if result != {'errors': 0, 'warnings': 0, 'issues': []}:
            raise ValueError('Layout preflight refused incomplete output: ' + str(result)[:1600])
        fonts = self.command('font.list')
        if not isinstance(fonts, list) or any(f.get('matchStatus') != 'exact' or f.get('source') != 'bundled'
                                            or f.get('missing') or f.get('styleMissing') for f in fonts):
            raise ValueError('Layout publication requires exact bundled font matches')
        return {'preflight': result, 'fonts': fonts}

    def render(self, profile, folder):
        folder = Path(folder); folder.mkdir(exist_ok=True)
        pixels = []
        for i, page in enumerate(profile['pages']):
            path = folder / f'page-{i + 1:03}.png'
            self.tool('export_png', page=i, scale=1, path=self.relative(path))
            from PIL import Image
            with Image.open(path) as image:
                if image.size != (math.ceil(page['width']), math.ceil(page['height'])):
                    raise ValueError('Layout preview dimensions disagree with its native page')
            pixels.append(photo.pixel_hash(path))
        return pixels

    def close(self):
        try:
            super().close()
        finally:
            self.home.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
