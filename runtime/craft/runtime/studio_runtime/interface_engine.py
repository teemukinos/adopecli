"""Private bounded Interface transport for typed runtime adapters.

No arbitrary native command endpoint is registered. Font catalog checks verify
requested family/style availability; they do not establish shaped-glyph fidelity.
"""
import json
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading

from . import interface_document as document, interface_text, photo, vector

VERSION = '0.18.1'


class Engine(vector.Engine):
    label = 'Interface'

    def __init__(self, root, *, executable=None):
        self.root = Path(root).resolve()
        executable = executable if executable is not None else shutil.which('dobe-interface')
        if executable is None:
            raise ValueError('maintained Dobe Interface engine is not installed')
        self.home = tempfile.TemporaryDirectory(prefix='.interface-home-', dir=self.root)
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
            result = self.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                             'clientInfo': {'name': 'dobe-runtime', 'version': '0.1.0'}})
            if result.get('serverInfo') != {'name': 'dobe-interface', 'title': 'Dobe Interface', 'version': VERSION}:
                raise ValueError('Interface engine identity is not qualified')
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
                message = json.loads(line)
                if not isinstance(message, dict):
                    break
                self.messages.put(message)
        except (ValueError, UnicodeError):
            pass
        finally:
            self.messages.put(None)

    def tool(self, tool_name, **arguments):
        result = self.call('tools/call', {'name': tool_name, 'arguments': arguments})
        content = result.get('content', [])
        if result.get('isError'):
            raise ValueError('Interface engine refused ' + tool_name + ': ' + str(content)[:1200])
        if len(content) != 1 or content[0].get('type') != 'text':
            raise ValueError('Interface engine omitted its structured result')
        # Per-glyph evidence repeats field names. Its bounded native report can
        # exceed the document parser's item count while remaining below 6 MiB.
        # Keep the original limit for every other reply and every native file.
        diagnostics = tool_name == 'run_command' and arguments.get('command') == 'dobe.textDiagnostics'
        value = document.strict_json(content[0]['text'], max_items=1_000_000 if diagnostics else 200_000)
        if isinstance(value, dict) and (value.get('warnings') or value.get('repairs')):
            raise ValueError('Interface engine reported warnings or repairs: ' + str(value)[:1200])
        return value

    def command(self, command_name, **params):
        return self.tool('run_command', command=command_name, params=params)

    def relative(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ValueError('Interface input or output must not be a symbolic link')
        return str(path.resolve().relative_to(self.root))

    def check_fonts(self, profile):
        catalog = self.command('text.fonts')
        for family, style in profile['fonts']:
            if family not in catalog or style not in self.command('text.fonts', family=family):
                raise ValueError('Interface requires an exact bundled font family and style: ' + family + ' / ' + style)
        return {'requested': [list(f) for f in profile['fonts']], 'catalog_matches': True,
                'shaped_glyph_coverage_verified': False}

    def open(self, path):
        relative = self.relative(path)
        profile = document.read_native(path)
        self.check_fonts(profile)
        result = self.tool('open_file', path=relative)
        opened = result.get('opened')
        if not isinstance(opened, dict) or opened.get('repairs') or opened.get('warnings') or opened.get('stale'):
            raise ValueError('Interface native open reported repairs, warnings or stale content')
        return profile

    def inspect_text(self, profile, allowed_fallbacks=()):
        """Qualify shaping per native node; complete publication has further gates."""
        reports = []
        for node in profile['nodes'].values():
            if node['type'] != 'text':
                continue
            current = self.tool('get_node', id=node['id'], depth=0, fields=['characters'])
            if current.get('id') != node['id'] or current.get('characters') != node['characters'] or current.get('truncated'):
                raise ValueError('Interface text diagnostics require the current saved source text')
            reports.append(interface_text.inspect(self.command('dobe.textDiagnostics', id=node['id']), node, allowed_fallbacks))
        return reports

    def save(self, path, *, title=None):
        if title is not None and (not isinstance(title, str) or not 1 <= len(title) <= 1000):
            raise ValueError('Interface saved title must be a bounded string')
        self.tool('save_file', path=self.relative(path))
        profile = document.read_native(path)
        # Native Save As follows the filename when the title is Untitled or
        # matches the previous filename. Typed projects preserve their title.
        # The first save establishes the new native path, so an explicit rename
        # followed by saving that same path no longer follows the old filename.
        if title is not None and profile['document']['name'] != title:
            self.command('file.rename', name=title)
            self.tool('save_file', path=self.relative(path))
            profile = document.read_native(path)
            if profile['document']['name'] != title:
                raise ValueError('Interface native save changed the requested title')
        self.check_fonts(profile)
        return profile

    def render(self, path, node_id):
        self.tool('export', ids=[node_id], format='png', scale=1, path=self.relative(path))
        path = Path(path)
        if path.stat().st_size > document.MAX_ASSET:
            raise ValueError('Interface preview exceeds its file budget')
        size = document.raster_info(path.read_bytes())
        return {'pixels': size, 'sha256': photo.pixel_hash(path)}

    def close(self):
        try:
            super().close()
        finally:
            self.home.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
