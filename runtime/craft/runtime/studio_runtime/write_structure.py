"""Independent Write story, table, style and reference validation.

This layer neither repairs source nor runs native commands. Formatting-property
semantics, media decoding and source-format fidelity remain separate gates.
"""
from collections import Counter, deque
import hashlib
import math
import re

from .write_container import require

MAX_BLOCKS = 100_000
MAX_CELLS = 100_000
MAX_OBJECTS = 20_000
MAX_PARTS = 4096
MAX_STYLES = 4096
MAX_TEXT = 16 << 20
MAX_PARAGRAPH = 1 << 20
MAX_PAGE = 1584
MAX_DRAWING = 2000
PART_KINDS = {'header', 'footer', 'footnote', 'endnote', 'comment', 'textBox'}
DRAWINGS = {'image', 'shape', 'graphic', 'group'}
OBJECT_FIELDS = {
    'image': ({'media', 'w', 'h'}, {'alt', 'float', 'crop', 'fx', 'ole'}),
    'graphic': ({'w', 'h', 'graphic'}, {'alt', 'float'}),
    'shape': ({'kind', 'w', 'h', 'fill', 'stroke'}, {'stroke_width', 'float', 'story', 'freeform', 'effects', 'extra'}),
    'group': ({'w', 'h', 'ch_w', 'ch_h', 'children'}, {'float', 'canvas'}),
    'field': ({'instr'}, {'result', 'locked', 'dirty', 'code', 'form'}),
    'fieldStart': ({'instr'}, {'locked', 'dirty'}), 'fieldEnd': (set(), set()),
    'controlStart': ({'control'}, set()), 'controlEnd': (set(), set()),
    'noteRef': ({'kind', 'id'}, {'custom'}), 'bookmarkStart': ({'name'}, set()), 'bookmarkEnd': ({'name'}, set()),
    'commentStart': ({'id'}, set()), 'commentEnd': ({'id'}, set()),
    'permStart': ({'id'}, {'group', 'editor'}), 'permEnd': ({'id'}, set()),
    'equation': ({'linear'}, {'display', 'math'}),
    'ruby': ({'base', 'ruby', 'size', 'raise'}, {'align', 'base_size', 'lang', 'props'}),
    'positionalTab': (set(), {'align', 'relative_to', 'leader'}), 'opaque': ({'format', 'xml'}, {'text'}),
}


def record(value, required, optional, label):
    require(type(value) is dict and required <= set(value) <= required | optional, label+' has missing or unknown fields')
    return value


def number(value, low, high, label):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, label+' is out of range')
    return value


def uint(value, high, label):
    require(type(value) is int and 0 <= value <= high, label+' is not a bounded integer')
    return value


def text(value, label, maximum=MAX_PARAGRAPH):
    require(type(value) is str and not any(0xd800 <= ord(c) <= 0xdfff for c in value), label+' is not valid text')
    require(len(value.encode('utf-8')) <= maximum, label+' exceeds its byte budget')
    return value


def sequence(value, maximum, label, minimum=0):
    require(type(value) is list and minimum <= len(value) <= maximum, label+' has an invalid length')
    return value


def ids(value, maximum, label):
    require(type(value) is dict and len(value) <= maximum, label+' has an invalid inventory')
    for key in value:
        require(type(key) is str and re.fullmatch(r'0|[1-9][0-9]{0,9}', key) is not None
                and int(key) <= 2**32-1, label+' has an ambiguous or oversized ID')
    return value


def graph_order(edges, label):
    """Bottom-up order without recursive traversal or loss of repeated edges."""
    waiting = {key: len(set(children)) for key, children in edges.items()}
    parents = {key: set() for key in edges}
    for key, children in edges.items():
        for child in children:
            require(child in edges, label+' references a missing node')
            parents[child].add(key)
    ready = deque(key for key, count in waiting.items() if count == 0); ordered = []
    while ready:
        key = ready.popleft(); ordered.append(key)
        for parent in parents[key]:
            waiting[parent] -= 1
            if waiting[parent] == 0: ready.append(parent)
    require(len(ordered) == len(edges), label+' contains a cycle')
    return ordered


def inspect(document):
    required = {'body', 'lastSection', 'parts', 'styles', 'numbering', 'comments', 'revisions', 'settings', 'core', 'sources', 'customProps'}
    record(document, required, {'media', 'passthrough', 'footnoteSeparators', 'endnoteSeparators', 'glossary'}, 'document')
    parts = ids(document['parts'], MAX_PARTS, 'story parts')
    comments = ids(document['comments'], 8192, 'comments')
    revisions = sequence(document['revisions'], 16384, 'revisions')
    media = document.get('media', {})
    require(type(media) is dict and len(media) <= 4096, 'media inventory is invalid')
    for name in media: text(name, 'media identity', 512)
    for name in ('settings', 'core', 'passthrough'):
        require(type(document.get(name, {})) is dict, name+' must be an object')
    for name in ('sources', 'customProps'): sequence(document[name], 4096, name)
    pending = {'formatting-properties', 'media-and-font-decoding', 'source-format-fidelity', 'native-model-comparison'}
    from .write_properties import Validator
    from . import write_page_properties
    property_validator = Validator(media, pending)
    metadata_report = write_page_properties.metadata(document, property_validator)
    counts = Counter(); paragraphs = []; objects = []; references = []; style_refs = []; num_refs = []
    story_edges = {'body': []} | {'part/'+key: [] for key in parts}
    box_edges = {key: [] for key in story_edges}; chains = {key: [] for key in parts}
    bookmarks = set(); used_comments = set()

    def part_ref(identity, kind, owner, path, *, box=False, embed=True):
        uint(identity, 2**32-1, 'story reference'); key = str(identity)
        require(key in parts and parts[key].get('kind') == kind, 'story reference is missing or has the wrong kind')
        target = 'part/'+key
        if embed: story_edges[owner].append(target)
        if box: box_edges[owner].append(target)
        references.append({'path': path, 'kind': kind, 'part': key})

    def revision(identity, kind=None):
        uint(identity, len(revisions)-1, 'revision reference')
        require(kind is None or revisions[identity].get('kind') == kind, 'revision reference has the wrong kind')

    def props(value, kind, depth=0):
        require(type(value) is dict and depth <= 16, 'properties are invalid or nested too deeply')
        property_validator.check(value, kind)
        if value.get('style') is not None: style_refs.append((value['style'], kind))
        for key, target in (('ins', 'insert'), ('del', 'delete')):
            if value.get(key) is not None: revision(value[key], target)
        if value.get('fmtChange') is not None:
            change = record(value['fmtChange'], {'rev', 'old'}, set(), 'format revision')
            revision(change['rev'], 'format'); props(change['old'], kind, depth+1)
        if value.get('numChange') is not None:
            item = record(value['numChange'], {'rev', 'original'}, set(), 'numbering revision')
            revision(item['rev']); text(item['original'], 'original numbering')
        if value.get('numbering') is not None:
            item = record(value['numbering'], {'num', 'level'}, set(), 'paragraph numbering')
            num_refs.append((uint(item['num'], 2**32-1, 'numbering reference'), uint(item['level'], 8, 'numbering level')))
        if kind == 'row' and value.get('exceptions') is not None:
            props(value['exceptions'], 'table', depth+1)

    for item in revisions:
        record(item, {'kind', 'author', 'date'}, {'move_name'}, 'revision')
        require(item['kind'] in ('insert', 'delete', 'format'), 'revision kind is invalid')
        text(item['author'], 'revision author'); text(item['date'], 'revision date', 128)
    for key, part in parts.items():
        record(part, {'kind', 'blocks'}, {'body'}, 'story part')
        require(type(part['kind']) is str and part['kind'] in PART_KINDS, 'story kind is invalid')
        if 'body' in part:
            body = record(part['body'], set(), {'vert', 'anchor', 'next', 'inset', 'autoFit', 'autoColor'}, 'text-box body')
            require(part['kind'] == 'textBox', 'text-box options require a text-box story')
            if body.get('next') is not None:
                target = str(uint(body['next'], 2**32-1, 'text-box chain reference'))
                require(target in parts and parts[target].get('kind') == 'textBox', 'text-box chain target is missing or has wrong kind')
                chains[key].append(target)
    lengths = {}
    for key in graph_order(chains, 'text-box chain'):
        lengths[key] = 1+max((lengths[c] for c in chains[key]), default=0)
        require(lengths[key] <= 256, 'text-box chain exceeds native traversal budget')

    def section(value, owner, path, depth=0):
        require(type(value) is dict, 'section must be an object'); counts['sections'] += 1
        require(counts['sections'] <= 256 and depth <= 16, 'section count or history exceeds its budget')
        write_page_properties.section(value, pending)
        width = number(value.get('pageW'), 1, MAX_PAGE, 'page width')
        height = number(value.get('pageH'), 1, MAX_PAGE, 'page height')
        margins = [number(value.get(k), 0, MAX_PAGE, k) for k in ('marginLeft', 'marginRight', 'marginTop', 'marginBottom')]
        gutter = number(value.get('gutter', 0), 0, MAX_PAGE, 'gutter')
        require(margins[0]+margins[1]+gutter <= width-18 and margins[2]+margins[3] <= height-18,
                'section margins leave no bounded text area')
        columns = record(value.get('columns'), {'count', 'space', 'separator', 'widths'}, set(), 'columns')
        count = uint(columns['count'], 45, 'column count'); require(count >= 1, 'column count must be positive')
        space = number(columns['space'], 0, width, 'column spacing')
        require(type(columns['separator']) is bool, 'column separator must be boolean')
        widths = sequence(columns['widths'], 45, 'column widths')
        usable = width-margins[0]-margins[1]-gutter
        if widths:
            require(len(widths) == count, 'column widths do not match column count')
            total = 0
            for index, pair in enumerate(widths):
                sequence(pair, 2, 'column width/space', 2)
                total += number(pair[0], 18, width, 'column width')
                gap = number(pair[1], 0, width, 'column space')
                if index+1 < count: total += gap
            require(total <= usable+.05, 'column widths exceed the text area')
        else: require(space*(count-1)+18*count <= usable+.05, 'columns would require native minimum-width clamping')
        for name, kind in (('headers', 'header'), ('footers', 'footer')):
            links = record(value.get(name), {'default', 'first', 'even'}, set(), name)
            for label, identity in links.items():
                if identity is not None: part_ref(identity, kind, owner, path+'/'+name+'/'+label)
        if value.get('fmtChange') is not None:
            item = record(value['fmtChange'], {'rev', 'old'}, set(), 'section format revision')
            revision(item['rev'], 'format')
            section(item['old'], owner, path+'/fmtChange/old', depth+1)
            pending.add('section-format-revisions')

    for key, item in comments.items():
        record(item, {'author', 'initials', 'date', 'parent', 'resolved', 'part'}, {'durableId', 'dateUtc'}, 'comment')
        uint(item['part'], 2**32-1, 'comment story'); target = str(item['part'])
        require(target in parts and parts[target]['kind'] == 'comment', 'comment story is missing or has wrong kind')
        require(type(item['resolved']) is bool, 'comment resolved flag must be boolean')
        for name in ('author', 'initials', 'date'): text(item[name], 'comment '+name)
        if item['parent'] is not None:
            uint(item['parent'], 2**32-1, 'comment parent')
            require(str(item['parent']) in comments, 'comment parent is missing')
    graph_order({key: [] if item['parent'] is None else [str(item['parent'])] for key, item in comments.items()}, 'comment replies')

    def inline(item, owner, path, state, depth=0):
        require(type(item) is dict and type(item.get('type')) is str and item['type'] in OBJECT_FIELDS, 'inline object kind is unknown')
        kind = item['type']; required, optional = OBJECT_FIELDS[kind]
        record(item, required | {'type'}, optional, 'inline '+kind)
        counts['objects'] += 1; require(counts['objects'] <= MAX_OBJECTS and depth <= 16, 'inline objects exceed their budget')
        objects.append({'path': path, 'type': kind, 'story': owner})
        if kind in DRAWINGS:
            flat_connector = kind == 'shape' and item['kind'] in ('straightConnector', 'elbowConnector', 'curvedConnector')
            number(item['w'], .01, MAX_DRAWING, 'drawing width')
            number(item['h'], 0 if flat_connector else .01, MAX_DRAWING, 'drawing height')
            if kind == 'image':
                require(type(item['media']) is str and item['media'] in media, 'image references missing media')
                if item.get('ole') is not None: raise ValueError('Write embedded OLE content is not admitted')
            elif kind == 'shape':
                if item.get('story') is not None: part_ref(item['story'], 'textBox', owner, path+'/story', box=True)
                pending.add('shape-geometry')
            elif kind == 'graphic': pending.add('graphic-payload')
            else:
                number(item['ch_w'], .01, MAX_DRAWING, 'group coordinate width'); number(item['ch_h'], .01, MAX_DRAWING, 'group coordinate height')
                for index, child in enumerate(sequence(item['children'], 1000, 'group children')):
                    record(child, {'x', 'y', 'obj'}, set(), 'group child')
                    number(child['x'], -MAX_DRAWING, MAX_DRAWING, 'group child x'); number(child['y'], -MAX_DRAWING, MAX_DRAWING, 'group child y')
                    require(type(child['obj']) is dict and type(child['obj'].get('type')) is str
                            and child['obj']['type'] in DRAWINGS, 'group child must be a drawing')
                    inline(child['obj'], owner, path+'/children/'+str(index)+'/obj', state, depth+1)
        elif kind in ('field', 'fieldStart'):
            instruction = text(item['instr'], 'field instruction', 8192)
            code = instruction.strip().split(None, 1)[0].upper() if instruction.strip() else ''
            require(code and code not in ('DDE', 'DDEAUTO', 'INCLUDETEXT', 'INCLUDEPICTURE', 'LINK', 'DATABASE', 'RD', 'MACROBUTTON'),
                    'external or executable field is not admitted')
            counts['fields'] += 1; pending.add('field-semantics')
            if kind == 'fieldStart': state['fields'] += 1
            else: text(item.get('result', ''), 'field result')
        elif kind == 'fieldEnd':
            require(state['fields'] > 0, 'field end has no matching start'); state['fields'] -= 1
        elif kind in ('controlStart', 'controlEnd'):
            pending.add('content-controls')
        elif kind == 'noteRef':
            require(item['kind'] in ('footnote', 'endnote'), 'note kind is invalid')
            # A note's own reference mark labels the note; it does not expand
            # its story recursively. Other note references are labels too.
            part_ref(item['id'], item['kind'], owner, path+'/id', embed=False)
        elif kind in ('bookmarkStart', 'bookmarkEnd', 'commentStart', 'commentEnd', 'permStart', 'permEnd'):
            prefix = kind.removesuffix('Start').removesuffix('End'); start = kind.endswith('Start')
            identity = text(item['name'], 'bookmark name', 1024) if prefix == 'bookmark' else uint(item['id'], 2**32-1, 'range ID')
            if prefix == 'comment':
                require(str(identity) in comments, 'comment anchor references a missing comment'); used_comments.add(str(identity))
            if start:
                require(identity not in state[prefix], 'range has duplicate open marker')
                if prefix == 'bookmark':
                    scope = owner+'/'+identity if owner.startswith('glossary/') else identity
                    require(identity and scope not in bookmarks, 'bookmark name is empty or duplicated'); bookmarks.add(scope)
                state[prefix].add(identity)
            else:
                require(identity in state[prefix], 'range end has no matching start'); state[prefix].remove(identity)
        elif kind in ('opaque', 'equation', 'ruby'):
            pending.add(kind+'-payload')
            if kind == 'ruby': props(item.get('props', {}), 'character')

    def blocks(values, owner, path, state, depth=0):
        for index, block in enumerate(sequence(values, MAX_BLOCKS, 'story blocks', 1)):
            counts['blocks'] += 1; require(counts['blocks'] <= MAX_BLOCKS, 'aggregate block budget exceeded')
            location = path+'/'+str(index)
            require(type(block) is dict and block.get('kind') in ('para', 'table'), 'block kind is unknown')
            if block['kind'] == 'para':
                record(block, {'kind', 'text', 'runs'}, {'props', 'mark', 'objects', 'section'}, 'paragraph')
                value = text(block['text'], 'paragraph text'); data = value.encode('utf-8')
                counts['text_bytes'] += len(data); require(counts['text_bytes'] <= MAX_TEXT, 'aggregate text budget exceeded')
                runs = sequence(block['runs'], 100_000, 'paragraph runs'); cursor = 0
                for run in runs:
                    record(run, {'len'}, {'props'}, 'character run'); size = uint(run['len'], len(data), 'run byte length')
                    require(size > 0, 'empty character runs would be normalized away')
                    stop = cursor+size; require(stop <= len(data), 'character runs exceed paragraph text')
                    try: data[cursor:stop].decode('utf-8')
                    except UnicodeError as error: raise ValueError('Write character run splits a UTF-8 character') from error
                    props(run.get('props', {}), 'character'); cursor = stop
                require(cursor == len(data), 'character runs do not cover paragraph text')
                props(block.get('props', {}), 'paragraph'); props(block.get('mark', {}), 'character')
                items = sequence(block.get('objects', []), MAX_OBJECTS, 'paragraph objects')
                require(value.count('\ufffc') == len(items), 'object markers do not match inline objects')
                for i, item in enumerate(items): inline(item, owner, location+'/objects/'+str(i), state)
                if block.get('section') is not None:
                    require(owner == 'body' and depth == 0, 'section boundary must be in the main body')
                    section(block['section'], owner, location+'/section')
                paragraphs.append({'path': location, 'story': owner, 'utf8_bytes': len(data), 'text_sha256': hashlib.sha256(data).hexdigest(), 'runs': len(runs)})
            else:
                record(block, {'kind', 'grid', 'rows'}, {'props', 'controls'}, 'table')
                require(depth < 8, 'table nesting exceeds the managed byte/parser budget')
                props(block.get('props', {}), 'table'); grid = sequence(block['grid'], 63, 'table grid')
                for width in grid: number(width, 0, MAX_PAGE, 'table column width')
                previous = set()
                for row_index, row in enumerate(sequence(block['rows'], 8192, 'table rows', 1)):
                    record(row, {'cells'}, {'props', 'controls'}, 'table row'); row_props = row.get('props', {})
                    require(type(row_props) is dict, 'row properties must be an object')
                    props(row_props, 'row')
                    column = uint(row_props.get('gridBefore', 0), 63, 'row starting grid'); merges = set()
                    for cell_index, cell in enumerate(sequence(row['cells'], 63, 'row cells', 1)):
                        record(cell, {'blocks'}, {'props', 'controls'}, 'table cell')
                        counts['cells'] += 1; require(counts['cells'] <= MAX_CELLS, 'aggregate cell budget exceeded')
                        cell_props = cell.get('props', {}); require(type(cell_props) is dict, 'cell properties must be an object')
                        props(cell_props, 'cell')
                        span = uint(cell_props.get('span', 1), 63, 'cell span'); require(span >= 1, 'cell span would be clamped')
                        merge = cell_props.get('vmerge', 'none'); require(merge in ('none', 'restart', 'continue'), 'vertical merge mode is invalid')
                        segment = (column, column+span)
                        if merge == 'continue': require(segment in previous, 'vertical merge has no matching preceding cell')
                        if merge != 'none': merges.add(segment)
                        column += span; require(column <= 63, 'row spans exceed native column budget')
                        if cell.get('controls'): pending.add('content-controls')
                        blocks(cell['blocks'], owner, location+'/rows/'+str(row_index)+'/cells/'+str(cell_index)+'/blocks', state, depth+1)
                    column += uint(row_props.get('gridAfter', 0), 63, 'row ending grid')
                    require(column <= 63 and (not grid or column == len(grid)), 'row cells and skipped columns disagree with table grid')
                    previous = merges
                    if row.get('controls'): pending.add('content-controls')
                counts['tables'] += 1
                if block.get('controls'): pending.add('content-controls')

    def story(values, owner, path):
        state = {'fields': 0, 'bookmark': set(), 'comment': set(), 'perm': set()}
        blocks(values, owner, path, state)
        require(not any(state.values()), 'story contains unmatched field or range markers')

    story(document['body'], 'body', '/body')
    for key, part in parts.items(): story(part['blocks'], 'part/'+key, '/parts/'+key+'/blocks')
    section(document['lastSection'], 'body', '/lastSection')
    for name in ('footnoteSeparators', 'endnoteSeparators'):
        if name in document:
            data = record(document[name], set(), {'separator', 'continuationSeparator', 'continuationNotice'}, name)
            for key, value in data.items():
                if value is not None:
                    owner = name+'/'+key; story_edges[owner] = []; box_edges[owner] = []
                    story(value, owner, '/'+name+'/'+key)
    for index, entry in enumerate(sequence(document.get('glossary', []), 4096, 'glossary')):
        record(entry, {'name', 'gallery', 'category', 'blocks'}, {'description', 'guid', 'style', 'types', 'behaviors'}, 'glossary entry')
        owner = 'glossary/'+str(index); story_edges[owner] = []; box_edges[owner] = []
        story(entry['blocks'], owner, '/glossary/'+str(index)+'/blocks')
        pending.add('glossary-semantics')
    graph_order(story_edges, 'story references')
    expansion = {}; nesting = {}
    for key in graph_order(box_edges, 'nested text boxes'):
        is_box = key.startswith('part/') and parts[key[5:]]['kind'] == 'textBox'
        expansion[key] = int(is_box)+sum(expansion[child] for child in box_edges[key])
        nesting[key] = int(is_box)+max((nesting[child] for child in box_edges[key]), default=0)
        if is_box: require(expansion[key] <= 65 and nesting[key] <= 4, 'text-box expansion would exceed native rendering limits')

    from .write_structure_styles import inspect as styles_inspect
    styles_report = styles_inspect(document, style_refs, num_refs, props, property_validator)
    return {'counts': dict(counts), 'paragraphs': paragraphs, 'objects': objects, 'references': references,
            'bookmarks': sorted(bookmarks), 'unanchored_comments': sorted(set(comments)-used_comments),
            'styles': styles_report, 'pending_qualification': sorted(pending),
            'properties': property_validator.finish(bookmarks),
            'metadata': metadata_report,
            'structural_validation_complete': True, 'engine_admission_complete': False}
