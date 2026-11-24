"""Typed PDF production with static admission, editable files and cold reopen checks.

No PDF actions, arbitrary engine commands, converters or external paths are exposed.
Rendering checks cover the supported local contract, not general PDF conformance.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading

from . import audio, photo, vector, video

VERSION = '0.21.1'
OPERATIONS = ('pdf.create', 'pdf.import', 'pdf.inspect', 'pdf.merge', 'pdf.extract', 'pdf.edit')
TEXT_FIELDS = {'text', 'rect', 'font', 'size', 'bold', 'italic', 'color', 'align', 'char_spacing'}
SHAPE_FIELDS = {'rect', 'color', 'fill', 'width', 'opacity', 'contents'}
METADATA = {'Title', 'Author', 'Subject', 'Keywords'}
MAX_PAGES = 256
MAX_PIXELS = 128_000_000


def text(value, maximum=10000, empty=False):
    return (isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum
            and not any(ord(c) < 32 and c not in '\n\t' or 0xd800 <= ord(c) <= 0xdfff for c in value))


def rectangle(value):
    return (isinstance(value, list) and len(value) == 4 and all(video.finite(x, 0, 8192) for x in value)
            and value[0] < value[2] and value[1] < value[3])


def fields(values, kind, complete=False):
    allowed = TEXT_FIELDS if kind == 'text' else SHAPE_FIELDS
    if set(values) - allowed or complete and not {'rect'} <= set(values):
        raise ValueError('unsupported PDF placement fields or missing rectangle')
    for key, value in values.items():
        if key == 'rect': valid = rectangle(value)
        elif key == 'text': valid = text(value)
        elif key == 'contents': valid = text(value, empty=True)
        elif key in ('color', 'fill'):
            valid = isinstance(value, str) and (bool(re.fullmatch(r'#[0-9A-Fa-f]{6}', value)) or key == 'fill' and value == 'none')
        elif key == 'font': valid = value in ('helvetica', 'times', 'courier')
        elif key == 'align': valid = value in ('left', 'center', 'right')
        elif key in ('bold', 'italic'): valid = type(value) is bool
        elif key == 'size': valid = video.finite(value, 1, 500)
        elif key == 'width': valid = video.finite(value, 0, 100)
        elif key == 'opacity': valid = video.finite(value, 0, 1)
        else: valid = video.finite(value, -100, 100)
        if not valid:
            raise ValueError('invalid PDF placement value: ' + key)
    if kind == 'text' and complete and not text(values.get('text')):
        raise ValueError('PDF text placement requires text')


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError('unsupported PDF operation or parameters')
    new = operation in ('pdf.create', 'pdf.import', 'pdf.merge')
    if new and source_revision is not None or not new and not source_revision:
        raise ValueError('PDF creation/import/merge requires a new project; other operations require a source revision')
    if operation == 'pdf.create':
        if set(params) - {'pages', 'metadata'} or not isinstance(params.get('pages'), list) or not 1 <= len(params['pages']) <= MAX_PAGES:
            raise ValueError('PDF creation requires 1 to 256 pages')
        names = set(); pixels = 0
        for page in params['pages']:
            if (not isinstance(page, dict) or set(page) != {'width', 'height', 'objects'}
                    or not all(video.finite(page[k], 3, 8192) for k in ('width', 'height'))
                    or not isinstance(page['objects'], list)):
                raise ValueError('PDF pages require bounded width, height and objects')
            pixels += (int(page['width']) + 1) * (int(page['height']) + 1)
            if pixels > MAX_PIXELS:
                raise ValueError('PDF page rendering exceeds its aggregate pixel budget')
            for obj in page['objects']:
                if (not isinstance(obj, dict) or not video.named(obj.get('name')) or obj['name'] in names
                        or obj.get('type') not in ('text', 'rectangle', 'oval')):
                    raise ValueError('PDF objects require unique names and text, rectangle or oval type')
                names.add(obj['name'])
                if len(names) > 512:
                    raise ValueError('PDF supports at most 512 named objects')
                fields({k:v for k,v in obj.items() if k not in ('name', 'type')}, obj['type'], True)
                if obj['rect'][2] > page['width'] or obj['rect'][3] > page['height']:
                    raise ValueError('PDF placement must fit inside its page')
    elif operation in ('pdf.import', 'pdf.merge'):
        key = 'asset' if operation == 'pdf.import' else 'assets'
        if set(params) != {key}:
            raise ValueError('PDF import requires asset; merge requires assets')
        values = [params[key]] if key == 'asset' else params[key]
        if (not isinstance(values, list) or not 1 <= len(values) <= 32
                or any(not isinstance(v, str) or not video.ASSET.fullmatch(v) for v in values)):
            raise ValueError('PDF inputs require 1 to 32 imported asset identifiers')
    elif operation == 'pdf.inspect':
        if params: raise ValueError('PDF inspection takes no parameters')
    elif operation == 'pdf.extract':
        pages = params.get('pages')
        if (set(params) != {'pages'} or not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES
                or any(not video.integer(p, 1, MAX_PAGES) for p in pages) or len(set(pages)) != len(pages)):
            raise ValueError('PDF extraction requires ordered unique page numbers')
    else:
        if not params or set(params) - {'edits', 'additions', 'replacements', 'metadata'}:
            raise ValueError('PDF edit requires edits, additions, replacements or metadata')
        edits = params.get('edits', []); replacements = params.get('replacements', []); additions = params.get('additions', [])
        if not all(isinstance(v, list) for v in (edits, replacements, additions)) or len(edits) + len(replacements) + len(additions) > 128:
            raise ValueError('PDF edit supports at most 128 bounded changes')
        names = set()
        for edit in edits:
            if (not isinstance(edit, dict) or not video.named(edit.get('name')) or edit['name'] in names
                    or edit.get('type') not in ('text', 'annotation') or len(edit) <= 2):
                raise ValueError('PDF edit requires a unique named text or annotation target')
            names.add(edit['name']); fields({k:v for k,v in edit.items() if k not in ('name', 'type')}, edit['type'])
        for addition in additions:
            if (not isinstance(addition, dict) or not video.named(addition.get('name')) or addition['name'] in names
                    or addition.get('type') not in ('text','rectangle','oval') or not video.integer(addition.get('page'),1,MAX_PAGES)):
                raise ValueError('PDF additions require unique names, pages and supported placement types')
            names.add(addition['name'])
            fields({k:v for k,v in addition.items() if k not in ('name','type','page')}, addition['type'], True)
        for replacement in replacements:
            if (not isinstance(replacement, dict) or set(replacement) != {'find', 'replace', 'pages', 'expected_matches'}
                    or not text(replacement['find']) or not text(replacement['replace'], empty=True)
                    or not video.integer(replacement['expected_matches'], 1, 10000)):
                raise ValueError('PDF text replacement requires text and an exact expected match count')
            validate('pdf.extract', {'pages':replacement['pages']}, source_revision)
        if not edits and not replacements and not additions and not params.get('metadata'):
            raise ValueError('PDF edit requires a change')
    if 'metadata' in params:
        values = params['metadata']
        if not isinstance(values, dict) or set(values) - METADATA or any(not text(v, 2000, True) for v in values.values()):
            raise ValueError('PDF metadata supports bounded Title, Author, Subject and Keywords')


def assets(operation, params):
    values = [params['asset']] if operation == 'pdf.import' else params['assets'] if operation == 'pdf.merge' else []
    return {value:'assets/' + value + '.pdf' for value in values}


def engine():
    # The maintained structural inspector is mandatory. No upstream fallback.
    return 'dobe-pdf'


class Engine(vector.Engine):
    label = 'PDF'

    def __init__(self, root, *, executable=None):
        self.root = Path(root).resolve(); self.home = tempfile.TemporaryDirectory(prefix='.pdf-home-', dir=self.root)
        executable = str(executable) if executable is not None else shutil.which(engine())
        if executable is None:
            self.home.cleanup(); raise ValueError('maintained Dobe PDF engine is not installed')
        env = {'PATH':'/usr/bin:/bin', 'HOME':self.home.name, 'TMPDIR':self.home.name,
               'XDG_CONFIG_HOME':self.home.name, 'XDG_CACHE_HOME':self.home.name,
               'PDFCRAFT_SYSTEM_FONTS':'0', 'LANG':'en_US.UTF-8'}
        try:
            self.proc = subprocess.Popen([executable, 'mcp', '--root', str(self.root)], cwd=self.root,
                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except BaseException:
            self.home.cleanup(); raise
        self.messages = queue.Queue(maxsize=2); self.counter = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            reply = self.call('initialize', {'protocolVersion':'2025-06-18','capabilities':{},
                                            'clientInfo':{'name':'dobe-runtime','version':'0.1.0'}})
            if reply['serverInfo'] != {'name':'dobe-pdf','title':'Dobe PDF','version':VERSION}:
                raise ValueError('PDF engine identity is not qualified')
            self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
            if self.tool('js_enabled', enabled=False) != {'enabled':False}:
                raise ValueError('PDF document scripts could not be disabled')
        except BaseException:
            self.close(); raise

    def _reader(self):
        try:
            while True:
                line = self.proc.stdout.readline(96 << 20)
                if not line: break
                if not line.endswith('\n'): break
                try: value = json.loads(line)
                except ValueError: break
                self.messages.put(value)
        finally:
            self.messages.put(None)

    def tool(self, tool_name, **args):
        result = self.call('tools/call', {'name':tool_name,'arguments':args})
        if result.get('isError'):
            raise ValueError('PDF engine refused ' + tool_name + ': ' + str(result.get('content', []))[:1200])
        if 'structuredContent' not in result:
            raise ValueError('PDF engine omitted structured output for ' + tool_name)
        return result['structuredContent']

    def inspect(self, path):
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 << 20:
            raise ValueError('PDF input requires a regular file of at most 64 MiB')
        report = self.tool('dobe_inspect_pdf', path=str(path.relative_to(self.root)))
        if report.get('schema_version') != 1 or report.get('sha256') != digest(path) or report.get('document_actions_executed') is not False:
            raise ValueError('PDF admission profile does not match its immutable input')
        return report

    def open(self, path):
        profile = self.inspect(path)
        reply = self.tool('doc_open', path=str(Path(path).relative_to(self.root)))
        if not reply.get('editable') or reply.get('encrypted') or reply.get('pages') != len(profile['pages']):
            raise ValueError('PDF could not open as an editable document')
        return reply['doc'], profile

    def render(self, doc, page, path):
        reply = self.call('tools/call', {'name':'page_render','arguments':{'doc':doc,'page':page,'dpi':72}})
        parts = reply.get('content', [])
        # Native diagnostics accompany incomplete/approximate renders. Refuse them.
        if reply.get('isError') or len(parts) != 1 or parts[0].get('type') != 'image' or parts[0].get('mimeType') != 'image/png':
            raise ValueError('PDF rendering failed or reported incomplete/approximate output')
        raw = base64.b64decode(parts[0]['data'], validate=True)
        if len(raw) > 64 << 20: raise ValueError('PDF page PNG exceeds its byte limit')
        Path(path).write_bytes(raw)
        return photo.pixel_hash(path)

    def close(self):
        try: super().close()
        finally: self.home.cleanup()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(process, doc):
    info = process.tool('doc_info', doc=doc)
    for key in ('warnings', 'repairs', 'unreadable_objects', 'xfa_warnings'):
        if info.get(key): raise ValueError('PDF inspection reports ' + key)
    if info.get('has_javascript') or info.get('xfa') or info.get('attachments'):
        raise ValueError('PDF contains unsupported active content or attachments')
    for font in info.get('fonts', []):
        if not font.get('embedded') and 'metrics are exact' not in str(font.get('substitution', '')):
            raise ValueError('PDF requires an unavailable or approximate font substitution')
    extracted = process.tool('text_extract', doc=doc)
    if extracted.get('html_truncated') or any(p.get('truncated') for p in extracted['pages']):
        raise ValueError('PDF text extraction was truncated')
    content = process.tool('content_list', doc=doc)['items']
    if any(item.get('type') == 'text' and not {'precise_rect','rgb','align','paragraph_alignments'} <= set(item) for item in content):
        raise ValueError('PDF engine lacks precise native style evidence')
    comments = process.tool('comment_list', doc=doc)['comments']
    if any(not {'stroke_width','fill_rgb','stroke_rgb','restylable'} <= set(item) for item in comments):
        raise ValueError('PDF engine lacks annotation style evidence')
    if len(content) + len(comments) > 4096:
        raise ValueError('PDF exceeds its editable item budget')
    # Process-local paths, IDs, dirty state and save byte count are not portable state.
    info.pop('document', None); info.pop('file_size', None)
    return {'info':info, 'text':extracted['pages'], 'content':content, 'comments':comments}


def mapping_for(state):
    mapping = {}
    for kind, key in (('text', 'content'), ('annotation', 'comments')):
        for item in state[key]:
            if kind == 'text' and item['type'] != 'text': continue
            name = f"{kind}_{item['page']}_{item['index']}"
            mapping[name] = {'type':kind, 'page':item['page'], 'index':item['index']}
            if kind == 'annotation': mapping[name]['id'] = item['id']
    return mapping


def _record(item):
    return json.dumps({k: v for k, v in item.items() if k != 'index'}, sort_keys=True)


def rebind(mapping, previous, current, kind, page, changed=None):
    """Rebind names after one native change on one page and return the changed item.

    The engine lists text and annotations sorted by position and renumbers them after
    an insertion or a move, so a stored index (or "the last item") may now name a
    different object. Annotations are matched by their native id. Text is matched by
    its unchanged record; exactly one record may differ: the added object, or the
    edited object named by `changed`.
    """
    key = 'content' if kind == 'text' else 'comments'
    before = [v for v in previous[key] if v['page'] == page and (kind != 'text' or v['type'] == 'text')]
    after = [v for v in current[key] if v['page'] == page and (kind != 'text' or v['type'] == 'text')]
    if kind == 'annotation':
        old_ids = {v['id'] for v in before}
        by_id = {v['id']: v for v in after}
        if len(by_id) != len(after): raise ValueError('PDF engine reported duplicate annotation ids')
        for item in mapping.values():
            if item['type'] == 'annotation' and item['page'] == page:
                if item['id'] not in by_id: raise ValueError('PDF annotation disappeared during a revision')
                item['index'] = by_id[item['id']]['index']
        if changed is not None: return by_id[mapping[changed]['id']]
        new = [v for v in after if v['id'] not in old_ids]
        if len(new) != 1: raise ValueError('PDF addition did not create exactly one annotation')
        return new[0]
    changed_index = mapping[changed]['index'] if changed is not None else None
    names_by_index = {item['index']: name for name, item in mapping.items() if item['type'] == 'text' and item['page'] == page}
    pool = {}
    for v in after: pool.setdefault(_record(v), []).append(v)
    for v in before:
        if v['index'] == changed_index: continue
        matches = pool.get(_record(v))
        if not matches: raise ValueError('PDF revision changed an untargeted text object')
        match = matches.pop(0)
        if v['index'] in names_by_index: mapping[names_by_index[v['index']]]['index'] = match['index']
    left = [v for group in pool.values() for v in group]
    if len(left) != 1: raise ValueError('PDF change did not affect exactly one text object')
    if changed is not None: mapping[changed]['index'] = left[0]['index']
    return left[0]


def assert_untouched_records(before_mapping, mapping, before, after, params):
    """Every untargeted record must survive unchanged, matched by identity, not index.

    Insertions and moves renumber the engine's position-sorted lists, so records are
    compared without their index. Text on replacement pages keeps its position and is
    checked field by field; anything left over is an object nobody requested.
    """
    def target(m, name): return (m[name]['type'], m[name]['page'], m[name]['index'])
    edited_old = {target(before_mapping, e['name']) for e in params.get('edits', [])}
    touched_new = {target(mapping, e['name']) for e in params.get('edits', []) + params.get('additions', [])}
    replacement_pages = {p for r in params.get('replacements', []) for p in r['pages']}
    for kind, key in (('text', 'content'), ('annotation', 'comments')):
        def replaced(v): return kind == 'text' and v['type'] == 'text' and v['page'] in replacement_pages
        pool = {}
        for v in after[key]:
            if (kind, v['page'], v['index']) in touched_new and (kind == 'annotation' or v['type'] == 'text'): continue
            if not replaced(v): pool.setdefault(_record(v), []).append(v)
        for old in before[key]:
            if (kind, old['page'], old['index']) in edited_old and (kind == 'annotation' or old['type'] == 'text'): continue
            if replaced(old):
                assert_replacement_record(old, next((v for v in after[key] if (v['page'], v['index']) == (old['page'], old['index'])), None))
                continue
            matches = pool.get(_record(old))
            if not matches: raise ValueError('PDF revision changed an untargeted editable record')
            matches.pop(0)
        if any(pool.values()): raise ValueError('PDF revision added an unrequested editable record')


def check_mapping(mapping, state):
    if not isinstance(mapping, dict) or len(mapping) > 4096:
        raise ValueError('invalid PDF editable object mapping')
    targets = set()
    for name, item in mapping.items():
        if (not video.named(name) or not isinstance(item, dict) or item.get('type') not in ('text', 'annotation')
                or set(item) != ({'type','page','index'} if item['type'] == 'text' else {'type','page','index','id'})
                or not video.integer(item['page'], 1, MAX_PAGES) or not video.integer(item['index'], 1, 4096)):
            raise ValueError('invalid PDF object identity')
        target = (item['type'], item['page'], item['index'])
        if target in targets: raise ValueError('duplicate PDF object target')
        targets.add(target)
        candidates = state['content' if item['type'] == 'text' else 'comments']
        actual = next((v for v in candidates if (v['page'],v['index']) == (item['page'],item['index'])), None)
        if actual is None or item['type'] == 'annotation' and actual['id'] != item['id'] or item['type'] == 'text' and actual['type'] != 'text':
            raise ValueError('PDF object mapping does not match the native document')


def render_pages(process, doc, profile, folder):
    folder.mkdir(exist_ok=True)
    return [process.render(doc, i, folder / f'page-{i:03}.png') for i in range(1, len(profile['pages']) + 1)]



def assert_requested(mapping, state, requested, creation=False):
    """Check engine-observed state, including colour, rather than echoing requests."""
    for request in requested:
        identity = mapping[request['name']]
        candidates = state['content' if identity['type'] == 'text' else 'comments']
        actual = next(v for v in candidates if (v['page'],v['index']) == (identity['page'],identity['index']))
        for key, value in request.items():
            if key in ('name','type','page'): continue
            if key == 'rect':
                found = actual.get('precise_rect', actual['rect'])
                # Native text height follows measured lines; requested height is a maximum.
                indices = (0,1,2) if identity['type'] == 'text' else (0,1,2,3)
                if any(abs(found[i]-value[i]) > 0.011 for i in indices) or identity['type'] == 'text' and found[3] > value[3]+0.011:
                    raise ValueError('PDF placement differs from requested geometry or overflows its rectangle')
            elif key in ('color','fill'):
                field = 'rgb' if identity['type'] == 'text' else 'fill_rgb' if key == 'fill' else 'stroke_rgb'
                found = actual[field]
                expected = None if value == 'none' else [int(value[i:i+2],16)/255 for i in (1,3,5)]
                if expected is None and found is not None or expected is not None and (found is None or any(abs(a-b)>0.0001 for a,b in zip(found,expected))):
                    raise ValueError('PDF native ink differs from requested colour')
            else:
                found = actual.get('stroke_width' if key == 'width' else key)
                if key == 'font' and isinstance(found,str): found = found.lower()
                valid = abs(found-value) <= 0.0001 if type(value) in (int,float) and type(found) in (int,float) else found == value
                if not valid: raise ValueError('PDF native value differs from request: '+key)
        if creation and identity['type'] == 'annotation' and actual['type'] != {'rectangle':'Square','oval':'Circle'}[request['type']]:
            raise ValueError('PDF created the wrong vector annotation type')



def assert_untargeted_fields(mapping, before, after, edits, before_mapping=None):
    for edit in edits:
        item = mapping[edit['name']]; key = 'content' if item['type'] == 'text' else 'comments'
        origin = (before_mapping or mapping)[edit['name']]
        old = next(v for v in before[key] if (v['page'],v['index']) == (origin['page'],origin['index']))
        new = next(v for v in after[key] if (v['page'],v['index']) == (item['page'],item['index']))
        changes = set(edit)-{'name','type'}; allowed = set(changes)
        if item['type'] == 'text':
            if 'color' in changes: allowed.update(('rgb','gray','cmyk'))
            if 'align' in changes: allowed.add('paragraph_alignments')
            if changes & {'rect','text','size','font','bold','italic','align','char_spacing'}:
                allowed.update(('rect','precise_rect'))
                if 'rect' not in changes and any(abs(old['precise_rect'][i]-new['precise_rect'][i])>0.011 for i in (0,1,2)):
                    raise ValueError('PDF text edit moved or widened its untargeted box')
        else:
            allowed.add('modified')
            if 'width' in changes: allowed.add('stroke_width')
            if 'color' in changes: allowed.add('stroke_rgb')
            if 'fill' in changes: allowed.add('fill_rgb')
            if 'opacity' in changes: allowed.update(('fill_opacity','text_opacity'))
        if {k:v for k,v in old.items() if k not in allowed} != {k:v for k,v in new.items() if k not in allowed}:
            raise ValueError('PDF revision changed an untargeted property of its edited object')


def assert_replacement_record(old, new):
    """A counted text replacement may reflow words, but cannot change their styling."""
    if new is None or old.get('type') != 'text' or new.get('type') != 'text':
        raise ValueError('PDF replacement changed an editable item identity')
    if old['text'] == new['text']:
        if old != new:
            raise ValueError('PDF replacement changed an untargeted editable record')
        return
    allowed = {'text', 'paragraph_alignments', 'rect', 'precise_rect'}
    if {k:v for k,v in old.items() if k not in allowed} != {k:v for k,v in new.items() if k not in allowed}:
        raise ValueError('PDF replacement changed an untargeted text property')
    if any(abs(old['precise_rect'][i]-new['precise_rect'][i]) > 0.011 for i in (0,1,2)):
        raise ValueError('PDF replacement moved or widened its untargeted text box')


def assert_object_scope(before, after, touched, metadata_changes):
    """Keep every previously reachable object outside edited page dependencies exact."""
    objects = before['objects']; allowed = set(); pending = []
    for page in touched:
        record = before['pages'][page-1]
        allowed.add(record['reference']); pending.extend(record['direct_references'])
    permitted_keys = {name.encode('ascii').hex() for name in metadata_changes} | {b'ModDate'.hex()}
    old_info = before['info_entries']; new_info = after['info_entries']
    if {k:v for k,v in old_info.items() if k not in permitted_keys} != {k:v for k,v in new_info.items() if k not in permitted_keys}:
        raise ValueError('PDF save changed an untargeted metadata entry')
    if before['info_reference']:
        allowed.add(before['info_reference'])
    for key in permitted_keys:
        pending.extend(old_info.get(key, {}).get('references', []))
    if metadata_changes:
        pending.extend(ref for ref in before['metadata_references'] if ref != before['info_reference'])
    seen = set()
    while pending:
        reference = pending.pop()
        if reference in seen: continue
        seen.add(reference); value = objects[reference]
        # Parent/page-backlinks and navigation must not authorize another page or catalog.
        if value['dictionary_type'] in ('Page','Pages','Catalog'): continue
        allowed.add(reference); pending.extend(value['references'])
    changed = {key for key,value in objects.items() if after['objects'].get(key) != value}
    if changed - allowed:
        raise ValueError('PDF revision changed objects outside its requested page/metadata dependencies')
    return sorted(changed)


def execute(root, operation, params, *, executable=None):
    validate(operation, params, None if operation in ('pdf.create','pdf.import','pdf.merge') else 'source')
    root = Path(root).resolve(); native = root/'native'; exports = root/'exports'
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    document = native/'document.pdf'; pending = native/'pending.pdf'
    sources = {key:(root/path) for key,path in assets(operation, params).items()}
    source_hashes = {}
    before = None; before_profile = None; before_pixels = None; changed_pages = set(); mapping = {}
    expected_pixels = None; replacement_results = []
    with tempfile.TemporaryDirectory(prefix='.pdf-check-', dir=root) as scratch:
        scratch = Path(scratch)
        with Engine(root, executable=executable) as process:
            if operation == 'pdf.create':
                first = params['pages'][0]
                doc = process.tool('doc_create', **{'from':'blank','pages':1,'width':first['width'],'height':first['height'],'name':'document.pdf'})['doc']
                for page_number, page in enumerate(params['pages'], 1):
                    if page_number > 1:
                        process.tool('page_insert_blank', doc=doc, at=page_number, width=page['width'], height=page['height'])
                    current = snapshot(process, doc)
                    for obj in page['objects']:
                        values = {k:v for k,v in obj.items() if k not in ('name','type')}
                        tool = 'page_add_text' if obj['type'] == 'text' else 'comment_add'
                        if tool == 'comment_add':
                            values['type'] = obj['type']
                            # Native creation uses an omitted fill for transparency;
                            # only native comment_edit accepts the literal "none".
                            if values.get('fill') == 'none': values.pop('fill')
                        process.tool(tool, doc=doc, page=page_number, **values)
                        state = snapshot(process, doc)
                        item = rebind(mapping, current, state, 'text' if tool == 'page_add_text' else 'annotation', page_number)
                        current = state
                        mapping[obj['name']] = {'type':'text' if tool == 'page_add_text' else 'annotation',
                                                'page':page_number,'index':item['index']}
                        if tool == 'comment_add': mapping[obj['name']]['id'] = item['id']
                for key,value in params.get('metadata', {}).items(): process.tool('doc_set_info', doc=doc, key=key, value=value)
                process.tool('doc_save', doc=doc, path=str(pending.relative_to(root)))
            elif operation in ('pdf.import', 'pdf.merge'):
                profiles = {key:process.inspect(path) for key,path in sources.items()}
                source_hashes = {key:profile['sha256'] for key,profile in profiles.items()}
                order = [params['asset']] if operation == 'pdf.import' else params['assets']
                if sum(len(profiles[key]['pages']) for key in order) > MAX_PAGES:
                    raise ValueError('merged PDF exceeds its page limit')
                if sum(sum(p['width'] * p['height'] for p in profiles[key]['pages']) for key in order) > MAX_PIXELS:
                    raise ValueError('merged PDF exceeds its rendering budget')
                expected_pixels = []
                for n,key in enumerate(order):
                    source_doc, profile = process.open(sources[key]); snapshot(process, source_doc)
                    expected_pixels.extend(render_pages(process, source_doc, profile, scratch/f'input-{n}'))
                    process.tool('doc_close', doc=source_doc)
                if operation == 'pdf.import': shutil.copyfile(sources[params['asset']], pending)
                else: process.tool('doc_combine', paths=[str(sources[k].relative_to(root)) for k in order], out=str(pending.relative_to(root)))
                doc, _ = process.open(pending)
                mapping = mapping_for(snapshot(process, doc))
            else:
                doc, before_profile = process.open(document); before = snapshot(process, doc)
                original_bytes = document.read_bytes()
                mapping = audio.load_json(native/'objects.json', 1 << 20); check_mapping(mapping, before)
                before_mapping = copy.deepcopy(mapping); current = before
                before_pixels = render_pages(process, doc, before_profile, scratch/'before')
                if operation == 'pdf.extract':
                    if max(params['pages']) > len(before_profile['pages']): raise ValueError('PDF extraction page does not exist')
                    process.tool('page_extract', doc=doc, pages=params['pages'], out=str(pending.relative_to(root)))
                    doc, _ = process.open(pending)
                    expected_pixels = [before_pixels[p-1] for p in params['pages']]
                    remap = {old:new for new,old in enumerate(params['pages'], 1)}
                    mapping = {name:{**item,'page':remap[item['page']]} for name,item in mapping.items() if item['page'] in remap}
                elif operation == 'pdf.inspect': shutil.copyfile(document, pending)
                else:
                    for edit in params.get('edits', []):
                        item = mapping.get(edit['name'])
                        if item is None or item['type'] != edit['type']: raise ValueError('unknown PDF edit target or wrong type')
                        values = {k:v for k,v in edit.items() if k not in ('name','type')}
                        if 'rect' in values:
                            page = before_profile['pages'][item['page']-1]
                            if values['rect'][2] > page['width'] or values['rect'][3] > page['height']:
                                raise ValueError('PDF edit rectangle exceeds page bounds')
                        process.tool('content_update' if item['type'] == 'text' else 'comment_edit',
                                     doc=doc, page=item['page'], index=item['index'], **values)
                        changed = snapshot(process, doc)
                        rebind(mapping, current, changed, item['type'], item['page'], changed=edit['name'])
                        current = changed
                        changed_pages.add(item['page'])
                    for addition in params.get('additions', []):
                        if addition['name'] in mapping or addition['page'] > len(before_profile['pages']):
                            raise ValueError('PDF addition name already exists or page does not exist')
                        page = before_profile['pages'][addition['page']-1]
                        if addition['rect'][2] > page['width'] or addition['rect'][3] > page['height']:
                            raise ValueError('PDF addition must fit inside its page')
                        values = {k:v for k,v in addition.items() if k not in ('name','type','page')}
                        tool = 'page_add_text' if addition['type'] == 'text' else 'comment_add'
                        if tool == 'comment_add':
                            values['type'] = addition['type']
                            if values.get('fill') == 'none': values.pop('fill')
                        process.tool(tool, doc=doc, page=addition['page'], **values)
                        changed = snapshot(process, doc)
                        item = rebind(mapping, current, changed, 'text' if tool == 'page_add_text' else 'annotation', addition['page'])
                        current = changed
                        mapping[addition['name']] = {'type':'text' if tool == 'page_add_text' else 'annotation',
                                                     'page':addition['page'],'index':item['index']}
                        if tool == 'comment_add': mapping[addition['name']]['id'] = item['id']
                        changed_pages.add(addition['page'])
                    for replacement in params.get('replacements', []):
                        if changed_pages.intersection(replacement['pages']):
                            raise ValueError('separate named edits and text replacement on the same PDF page into two revisions')
                        if max(replacement['pages']) > len(before_profile['pages']): raise ValueError('PDF replacement page does not exist')
                        reply = process.tool('text_replace', doc=doc, find=replacement['find'], replace=replacement['replace'],
                                             pages=replacement['pages'], case_sensitive=True)
                        if reply.get('replaced') != replacement['expected_matches'] or reply.get('skipped'):
                            raise ValueError('PDF replacement did not complete the exact requested match count')
                        changed_pages.update(reply['pages']); replacement_results.append(reply)
                    for key,value in params.get('metadata', {}).items(): process.tool('doc_set_info', doc=doc, key=key, value=value)
                    saved = process.tool('doc_save', doc=doc, path=str(pending.relative_to(root)), full=False)
                    if not saved.get('incremental') or not pending.read_bytes().startswith(original_bytes):
                        raise ValueError('PDF edit did not preserve its original bytes in an incremental save')
            profile = process.inspect(pending)
            state = snapshot(process, doc); check_mapping(mapping, state)
            if operation == 'pdf.create':
                assert_requested(mapping, state, [obj for page in params['pages'] for obj in page['objects']], True)
            elif operation == 'pdf.edit':
                assert_requested(mapping, state, params.get('edits', []))
                assert_requested(mapping, state, params.get('additions', []), True)
                assert_untargeted_fields(mapping, before, state, params.get('edits', []), before_mapping)
                assert_object_scope(before_profile, profile, changed_pages, params.get('metadata', {}))
            pixels = render_pages(process, doc, profile, exports)
            if expected_pixels is not None and pixels != expected_pixels:
                raise ValueError('PDF import/merge/extraction changed page pixels')
            if before is not None and operation in ('pdf.edit','pdf.inspect'):
                if len(pixels) != len(before_pixels): raise ValueError('PDF revision changed page count')
                for i,(old,new) in enumerate(zip(before_pixels,pixels), 1):
                    if i not in changed_pages and old != new: raise ValueError('PDF revision changed an untargeted page')
                assert_untouched_records(before_mapping if operation == 'pdf.edit' else mapping, mapping, before, state, params)
                for key,value in params.get('metadata', {}).items():
                    if (state['info'].get(key.lower()) or '') != value:
                        raise ValueError('PDF metadata revision did not persist')
        # A different native process must reproduce the saved editable document.
        with Engine(root, executable=executable) as reopened:
            doc, cold_profile = reopened.open(pending)
            cold = snapshot(reopened, doc); check_mapping(mapping, cold)
            if cold_profile != profile or cold != state:
                raise ValueError('PDF cold reopen changed native structure or editable records')
            if render_pages(reopened, doc, cold_profile, scratch/'cold') != pixels:
                raise ValueError('PDF cold reopen changed page pixels')
        if source_hashes != {key:digest(path) for key,path in sources.items()}:
            raise ValueError('PDF production changed an imported source')
        if before_profile and digest(document) != before_profile['sha256']:
            raise ValueError('PDF production changed its source revision before publication')
        pending.replace(document)
    (native/'objects.json').write_text(json.dumps(mapping, sort_keys=True)+'\n')
    (native/'structure.json').write_text(json.dumps({'profile':profile,'snapshot':state}, sort_keys=True)+'\n')
    shutil.copyfile(document, exports/'document.pdf')
    (exports/'inspection.json').write_text(json.dumps({'objects':mapping,**state}, sort_keys=True)+'\n')
    artifacts = [{'path':path,'role':role} for path,role in (
        ('native/document.pdf','native'),('native/objects.json','native'),('native/structure.json','native'),
        ('exports/document.pdf','export'),('exports/inspection.json','export'))]
    artifacts += [{'path':f'exports/page-{i:03}.png','role':'preview'} for i in range(1,len(pixels)+1)]
    artifacts += photo.retained_assets(root)
    changes = [] if before_profile is None else [key for key,value in before_profile['objects'].items() if profile['objects'].get(key) != value]
    return {'engine':{'name':'pdfcraft','version':VERSION,'build':'dobe-pdf '+VERSION},'artifacts':artifacts,
            'validation':{'passed':True,'native_cold_reopen':True,'pixel_roundtrip_equal':True,
                'static_structure_admitted':True,'document_scripts_disabled':True,'page_count':len(pixels),
                'source_bytes_unchanged':True,'untargeted_page_pixels_verified':before is not None and operation in ('pdf.edit','pdf.inspect'),
                'changed_prior_object_references':changes,'replacement_results':replacement_results,
                'glyph_coverage_verified':False,'object_scope_preserved':operation == 'pdf.edit',
                'qualification':'bounded local PDF contract; no general PDF standards or fidelity claim'}}
