"""Typed Interface scene authoring, with native readback of requested properties.

This is private adapter machinery. Export visibility, cold reopen, immutable
revision publication and durable jobs are separate gates.
"""
import hashlib
from pathlib import Path

from . import interface_document as document, video

TYPES = frozenset(('frame', 'component', 'instance', 'text', 'rectangle', 'ellipse', 'image'))
COMMON = {'name', 'type', 'parent', 'x', 'y', 'width', 'height', 'opacity'}
FRAME = {'color', 'clip', 'radius', 'layout', 'gap', 'padding', 'sizing_h', 'sizing_v', 'main_align', 'cross_align'}
TEXT = {'text', 'font_family', 'font_style', 'font_size', 'color', 'text_resize'}
RESIZE = {'fixed': 'none', 'height': 'height', 'content': 'widthAndHeight'}


def text(value, maximum, empty=False):
    return (isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum
            and not any(0xd800 <= ord(c) <= 0xdfff or ord(c) < 32 and c not in '\n\t' for c in value))


def validate(params):
    if (not isinstance(params, dict) or set(params) != {'title', 'nodes'} or not text(params['title'], 200)
            or not isinstance(params['nodes'], list) or not 1 <= len(params['nodes']) <= 512):
        raise ValueError('Interface scene requires a title and 1 to 512 named nodes')
    known = {}; total_text = 0; pixels = 0
    for node in params['nodes']:
        if (not isinstance(node, dict) or not video.named(node.get('name')) or node['name'] in known
                or not isinstance(node.get('type'), str) or node['type'] not in TYPES):
            raise ValueError('Interface nodes require unique names and supported types')
        kind = node['type']
        fields = COMMON | (FRAME if kind in ('frame', 'component') else TEXT if kind == 'text'
                           else {'asset', 'fit'} if kind == 'image' else {'component'} if kind == 'instance'
                           else {'color', 'radius'} if kind == 'rectangle' else {'color'})
        if set(node) - fields or not all(document.number(node.get(k), -8192, 8192) for k in ('x', 'y')):
            raise ValueError('Interface node has unsupported fields or coordinates')
        if not all(document.number(node.get(k), 1, 8192) for k in ('width', 'height')):
            raise ValueError('Interface node requires bounded width and height')
        if not document.number(node.get('opacity', 1), 0, 1):
            raise ValueError('Interface opacity must be between zero and one')
        pixels += node['width'] * node['height']
        if pixels > document.MAX_PIXELS:
            raise ValueError('Interface scene exceeds its rectangular pixel budget')
        parent = node.get('parent')
        if parent is not None and (not isinstance(parent, str) or parent not in known
                                   or known[parent]['type'] not in ('frame', 'component')):
            raise ValueError('Interface parent must name an earlier frame or component')
        if 'color' in node and (not isinstance(node['color'], str) or not video.COLOR.fullmatch(node['color'])):
            raise ValueError('Interface color requires #rrggbb')
        if 'radius' in node and not document.number(node['radius'], 0, min(node['width'], node['height']) / 2):
            raise ValueError('Interface radius exceeds its node geometry')
        if kind in ('frame', 'component'):
            if type(node.get('clip', True)) is not bool:
                raise ValueError('Interface clip must be a boolean')
            if node.get('layout') not in (None, 'horizontal', 'vertical'):
                raise ValueError('Interface layout must be horizontal or vertical')
            layout_fields = {'gap', 'padding', 'sizing_h', 'sizing_v', 'main_align', 'cross_align'}
            if not node.get('layout') and layout_fields & node.keys():
                raise ValueError('Interface layout properties require an explicit layout')
            if not all(document.number(node.get(k, 0), 0, 8192) for k in ('gap', 'padding')):
                raise ValueError('Interface layout spacing exceeds its budget')
            if any(node.get(k, 'fixed') not in ('fixed', 'hug') for k in ('sizing_h', 'sizing_v')):
                raise ValueError('Interface frame sizing must be fixed or hug')
            if any(node.get(k, 'min') not in ('min', 'center', 'max') for k in ('main_align', 'cross_align')):
                raise ValueError('Interface alignment must be min, center or max')
        elif kind == 'text':
            if (not text(node.get('text'), 16_384, True)
                    or not all(text(node.get(k), 128) for k in ('font_family', 'font_style'))
                    or not document.number(node.get('font_size'), 1, 500)
                    or not isinstance(node.get('text_resize', 'fixed'), str)
                    or node.get('text_resize', 'fixed') not in RESIZE):
                raise ValueError('Interface text requires bounded content and explicit typography')
            total_text += len(node['text'].encode('utf-8'))
        elif kind == 'image':
            if (not isinstance(node.get('asset'), str) or not video.ASSET.fullmatch(node['asset'])
                    or node.get('fit', 'cover') not in ('cover', 'contain')):
                raise ValueError('Interface artwork requires an imported asset and cover or contain fitting')
        elif kind == 'instance':
            component = node.get('component')
            if not isinstance(component, str) or component not in known or known[component]['type'] != 'component':
                raise ValueError('Interface instance must reference an earlier component')
        known[node['name']] = node
    if total_text > document.MAX_TEXT:
        raise ValueError('Interface scene exceeds its text budget')
    # Acyclic parent names do not rule out a component instantiating itself.
    edges = {name: [] for name in known}
    for name, node in known.items():
        if node.get('parent') is not None:
            edges[node['parent']].append(name)
        if node['type'] == 'instance':
            edges[name].append(node['component'])
    active = set(); expanded = {}
    def visit(name, at_depth=0):
        if name in active or at_depth >= 32:
            raise ValueError('Interface scene has recursive or excessive component nesting')
        if name in expanded:
            if at_depth + expanded[name][1] > 32:
                raise ValueError('Interface scene exceeds its expanded depth budget')
            return expanded[name]
        active.add(name)
        children = [visit(child, at_depth + 1) for child in edges[name]]
        # An instance replaces the referenced component root, rather than
        # inserting that root below itself. Descendants are native copies.
        instance = known[name]['type'] == 'instance'
        count = (0 if instance else 1) + sum(row[0] for row in children)
        depth = 1 + max((row[1] for row in children), default=0)
        if depth > 32 or count > document.MAX_NODES:
            raise ValueError('Interface scene exceeds its expanded node or depth budget')
        active.remove(name); expanded[name] = (count, depth)
        return expanded[name]
    for name in known:
        visit(name)
    if 1 + sum(expanded[name][0] for name, node in known.items() if node.get('parent') is None) > document.MAX_NODES:
        raise ValueError('Interface scene exceeds its expanded node budget')


def assets(params):
    return {node['asset']: 'assets/' + node['asset'] + '.image'
            for node in params['nodes'] if node['type'] == 'image'}


def properties(node):
    result = {'opacity': node.get('opacity', 1)}
    kind = node['type']
    if kind == 'instance':
        result.update(sizingH='fixed', sizingV='fixed')
    if kind not in ('instance', 'image'):
        result['fill'] = node.get('color', '#FFFFFF' if kind in ('frame', 'component') else '#111111')
    if 'radius' in node:
        result['cornerRadius'] = node['radius']
    if kind in ('frame', 'component'):
        result['clip'] = node.get('clip', True)
        if node.get('layout'):
            result.update(layout=node['layout'], gap=node.get('gap', 0), padding=node.get('padding', 0),
                          sizingH=node.get('sizing_h', 'fixed'), sizingV=node.get('sizing_v', 'fixed'),
                          mainAlign=node.get('main_align', 'min'), crossAlign=node.get('cross_align', 'min'))
    elif kind == 'text':
        result.update(fontFamily=node['font_family'], fontStyle=node['font_style'], fontSize=node['font_size'],
                      textAutoResize=RESIZE[node.get('text_resize', 'fixed')])
    return result


def create(process, params, inputs, pending):
    """Create a saved native scene. The caller owns final qualification/publication."""
    validate(params)
    pending = Path(pending)
    process.relative(pending)
    if pending.exists() or pending.is_symlink():
        raise ValueError('Interface scene output must be a new attempt-owned file')
    if set(inputs) != set(assets(params)):
        raise ValueError('Interface scene artwork inputs do not match its request')
    hashes = {}; pixels = 0
    for key, path in inputs.items():
        path = Path(path)
        process.relative(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > document.MAX_ASSET:
            raise ValueError('Interface artwork requires a bounded regular file')
        data = path.read_bytes(); size = document.raster_info(data)
        pixels += size[0] * size[1]
        hashes[key] = hashlib.sha256(data).hexdigest()
    if pixels > document.MAX_PIXELS:
        raise ValueError('Interface artwork exceeds its decoded pixel budget')
    # Validate every requested face before changing the native session.
    process.check_fonts({'fonts': sorted({(n['font_family'], n['font_style'])
                                         for n in params['nodes'] if n['type'] == 'text'})})
    process.command('file.new', name=params['title'])
    mapping = {}
    for request in params['nodes']:
        kind = request['type']
        args = {k: request[k] for k in ('name', 'x', 'y', 'width', 'height')}
        if request.get('parent') is not None:
            args['parent'] = mapping[request['parent']]['id']
        if kind == 'instance':
            result = process.command('instance.create', component=mapping[request['component']]['id'],
                                     **{k: v for k, v in args.items() if k in ('x', 'y', 'parent')})
            process.tool('set_properties', ids=[result['id']], props={
                'name': request['name'], 'width': request['width'], 'height': request['height'], **properties(request)})
        elif kind == 'image':
            result = process.command('image.place', path=process.relative(inputs[request['asset']]),
                                     mode='fit' if request.get('fit', 'cover') == 'contain' else 'fill', **args)
            process.tool('set_properties', ids=[result['id']], props=properties(request))
        else:
            if kind == 'text':
                args['text'] = request['text']
            result = process.tool('create_node', type=kind, props=properties(request), **args)
            # Native creation initially auto-sizes text before applying props.
            # Set fixed axes after selecting the requested resize mode.
            if kind == 'text' and request.get('text_resize', 'fixed') != 'content':
                dimensions = {'width': request['width']}
                if request.get('text_resize', 'fixed') == 'fixed':
                    dimensions['height'] = request['height']
                process.tool('set_properties', ids=[result['id']], props=dimensions)
        mapping[request['name']] = {'id': result['id'], 'type': kind}
    profile = process.save(pending, title=params['title'])
    requested(profile, params, mapping, hashes)
    if any(hashlib.sha256(Path(inputs[key]).read_bytes()).hexdigest() != value for key, value in hashes.items()):
        raise ValueError('Interface authoring changed an input asset')
    return profile, mapping


def requested(profile, params, mapping, hashes):
    """Check requested semantic fields against saved native data, not MCP echoes."""
    if profile['document']['name'] != params['title'] or len(profile['pages']) != 1:
        raise ValueError('Interface scene title or page count differs from the request')
    by_name = {node['name']: node for node in params['nodes']}
    if (set(mapping) != set(by_name) or len({row['id'] for row in mapping.values()}) != len(mapping)
            or set(profile['assets']) != set(hashes.values())):
        raise ValueError('Interface scene mapping or embedded artwork differs from the request')
    children = {name: [] for name in by_name}; children[None] = []
    for request in params['nodes']:
        children[request.get('parent')].append(mapping[request['name']]['id'])
    if profile['nodes'][str(profile['pages'][0])].get('children', []) != children[None]:
        raise ValueError('Interface scene root paint order differs from the request')
    mapped = {row['id'] for row in mapping.values()} | set(profile['pages'])
    for request in params['nodes']:
        node = profile['nodes'][str(mapping[request['name']]['id'])]
        kind = request['type']
        parent = mapping[request['parent']]['id'] if request.get('parent') is not None else profile['pages'][0]
        if node['type'] != ('rectangle' if kind == 'image' else kind) or node['name'] != request['name'] or node['parent'] != parent:
            raise ValueError('Interface scene node identity or hierarchy differs from the request')
        if kind != 'instance' and node.get('children', []) != children[request['name']]:
            raise ValueError('Interface scene child paint order differs from the request')
        if abs(node.get('opacity', 1) - request.get('opacity', 1)) > 1e-6:
            raise ValueError('Interface scene opacity differs from the request')
        parent_request = by_name.get(request.get('parent'), {})
        transform = node.get('transform', document.IDENTITY)
        if (transform[:4] != document.IDENTITY[:4] or not parent_request.get('layout')
                and any(abs(a - b) > 1e-6 for a, b in zip(transform[4:], (request['x'], request['y'])))):
            raise ValueError('Interface scene position differs from the request')
        for dimension, sizing in (('width', 'sizing_h'), ('height', 'sizing_v')):
            derived = request.get(sizing) == 'hug' or kind == 'text' and (
                request.get('text_resize') == 'content' or dimension == 'height' and request.get('text_resize') == 'height')
            if not derived and abs(node[dimension] - request[dimension]) > 1e-6:
                raise ValueError('Interface scene fixed dimensions differ from the request')
        if kind == 'text':
            if node['characters'] != request['text'] or any(node['style'][k] != request[k] for k in ('font_family', 'font_style', 'font_size')):
                raise ValueError('Interface scene text or typography differs from the request')
            if node.get('auto_resize', 'widthAndHeight') != RESIZE[request.get('text_resize', 'fixed')]:
                raise ValueError('Interface scene text resizing differs from the request')
        if kind == 'instance' and node.get('component') != mapping[request['component']]['id']:
            raise ValueError('Interface instance lost its main component')
        if kind == 'instance':
            main = profile['nodes'][str(node['component'])]
            appearance = ('fills', 'strokes', 'stroke', 'effects', 'corners', 'clip', 'layout', 'visible', 'blend', 'constraints')
            if any(node.get(k) != main.get(k) for k in appearance):
                raise ValueError('Interface instance appearance differs from its component')
            pending = [(main, node)]
            while pending:
                source, clone = pending.pop()
                source_children, clone_children = source.get('children', []), clone.get('children', [])
                if len(source_children) != len(clone_children):
                    raise ValueError('Interface instance lost native component children')
                for source_id, clone_id in zip(source_children, clone_children):
                    child = profile['nodes'][str(source_id)]; copied = profile['nodes'][str(clone_id)]
                    if copied.get('source') != source_id:
                        raise ValueError('Interface instance child source or order differs from its component')
                    # Geometry is derived from the instance dimensions and native
                    # constraints. Identity and override bookkeeping belong to
                    # each copy. All authored content and appearance must remain.
                    derived = {'id', 'parent', 'children', 'source', 'overrides', 'transform', 'width', 'height'}
                    if {k: v for k, v in child.items() if k not in derived} != {k: v for k, v in copied.items() if k not in derived}:
                        raise ValueError('Interface instance child content differs from its component')
                    mapped.add(clone_id); pending.append((child, copied))
        if kind == 'image':
            fills = node.get('fills', [])
            mode = 'fit' if request.get('fit', 'cover') == 'contain' else 'fill'
            if len(fills) != 1 or fills[0].get('image') != hashes[request['asset']] or fills[0].get('scale_mode') != mode:
                raise ValueError('Interface scene embedded artwork or fitting differs from the request')
        elif kind != 'instance':
            color = properties(request)['fill']
            expected = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1]
            fills = node.get('fills', [])
            if (len(fills) != 1 or fills[0].get('type') != 'solid'
                    or any(abs(fills[0]['color'][k] - v) > 1e-6 for k, v in zip(('r', 'g', 'b', 'a'), expected))):
                raise ValueError('Interface scene fill differs from the request')
        if kind in ('frame', 'component'):
            if node.get('clip', False) != request.get('clip', True):
                raise ValueError('Interface scene clipping differs from the request')
            if request.get('layout'):
                layout = node.get('layout', {})
                expected = {'mode': request['layout'], 'gap': request.get('gap', 0), 'padding': [request.get('padding', 0)] * 4,
                            'main_align': request.get('main_align', 'min'), 'cross_align': request.get('cross_align', 'min')}
                if any(layout.get(k) != v for k, v in expected.items()):
                    raise ValueError('Interface scene auto layout differs from the request')
                sizing = node.get('child_layout', {})
                if any(sizing.get(k, 'fixed') != request.get(k, 'fixed') for k in ('sizing_h', 'sizing_v')):
                    raise ValueError('Interface scene layout sizing differs from the request')
        if 'radius' in request and node.get('corners', {}).get('radii', [0] * 4) != [request['radius']] * 4:
            raise ValueError('Interface scene corner radius differs from the request')
    if mapped != {node['id'] for node in profile['nodes'].values()}:
        raise ValueError('Interface authoring introduced an unrequested native node')
