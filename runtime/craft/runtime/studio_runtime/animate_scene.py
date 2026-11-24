"""Closed scene authoring with actual native drawing and text layout.

The engine creates geometry and outlines. Complete readback must match requested
state before object continuity and explicit tween spans are assembled. No input
can supply native commands, paths or executable scripts.
"""
import copy
import json
from pathlib import Path

from . import animate_document as document, animate_format as format, animate_semantics as semantics
from .animate_graph import fields, sequence
from .animate_native_probe import NativeInspector
from .animate_process import run
from .animate_properties import easing, f32
from .animate_unicode import trim
from . import video

MAX_OBJECTS = 512


def text(value, maximum):
    return (isinstance(value, str) and len(value) <= maximum
            and not any(0xd800 <= ord(c) <= 0xdfff or c == '\0' for c in value))


def color(value):
    if not isinstance(value, str) or not video.COLOR.fullmatch(value):
        raise ValueError('Animate authoring colors require #rrggbb')
    return {**{key: f32(int(value[i:i+2], 16) / 255) for key, i in zip(('r', 'g', 'b'), (1, 3, 5))}, 'a': 1}


def node_params(node):
    fields(node, ('name', 'type', 'x', 'y'),
           ('width', 'height', 'fill', 'stroke', 'stroke_width', 'radius', 'text', 'font', 'size',
            'bold', 'italic', 'color', 'align', 'letter_spacing', 'line_spacing'), 'authored object')
    if not video.named(node['name']) or len(node['name']) > 128 or node['type'] not in ('rectangle', 'ellipse', 'text'):
        raise ValueError('Animate authoring requires named rectangle, ellipse or text objects')
    if any(not format.number(node[key], -8192, 8192) for key in ('x', 'y')):
        raise ValueError('Animate object position exceeds the authoring budget')
    if node['type'] == 'text':
        allowed = {'name', 'type', 'x', 'y', 'width', 'text', 'font', 'size', 'bold', 'italic',
                   'color', 'align', 'letter_spacing', 'line_spacing'}
        if node.keys() - allowed or not {'text', 'font', 'size', 'color'} <= node.keys():
            raise ValueError('Animate text requires explicit content, font, size and color')
        if (not text(node['text'], 8192) or not trim(node['text']) or len(node['text'].encode('utf-8')) > 32768
                or not text(node['font'], 128) or not trim(node['font']) or len(node['font'].encode('utf-8')) > 256):
            raise ValueError('Animate authored text or font exceeds its budget or is blank')
        if not format.number(node['size'], 1, 2000):
            raise ValueError('Animate text size must be between 1 and 2000')
        if any(type(node.get(key, False)) is not bool for key in ('bold', 'italic')):
            raise ValueError('Animate text style flags must be booleans')
        if node.get('align', 'left') not in ('left', 'center', 'right'):
            raise ValueError('Animate text alignment is invalid')
        if any(not format.number(node.get(key, 0), -1000, 1000) for key in ('letter_spacing', 'line_spacing')):
            raise ValueError('Animate text spacing exceeds its budget')
        if node.get('width') is not None and not format.number(node['width'], .001, 100000):
            raise ValueError('Animate text wrapping width exceeds its budget')
        color(node['color'])
        return {**{key: node[key] for key in ('text', 'font', 'size', 'color', 'x', 'y')},
                **{key: node.get(key, default) for key, default in
                   [('bold', False), ('italic', False), ('align', 'left'), ('letter_spacing', 0),
                    ('line_spacing', 0), ('width', None)]}}
    allowed = {'name', 'type', 'x', 'y', 'width', 'height', 'fill', 'stroke', 'stroke_width'}
    if node['type'] == 'rectangle':
        allowed.add('radius')
    if node.keys() - allowed or not {'width', 'height', 'fill'} <= node.keys():
        raise ValueError('Animate shapes require dimensions and explicit fill')
    if any(not format.number(node[key], .5, 8192) for key in ('width', 'height')):
        raise ValueError('Animate shape dimensions exceed the authoring budget')
    for key in ('fill', 'stroke'):
        if node.get(key) is not None:
            color(node[key])
    width = node.get('stroke_width', 1)
    if not format.number(width, .001, 1000) or ('stroke_width' in node and node.get('stroke') is None):
        raise ValueError('Animate stroke width requires an explicit bounded stroke')
    if node.get('fill') is None and node.get('stroke') is None:
        raise ValueError('Animate shape requires a fill or stroke')
    if not format.number(node.get('radius', 0), 0, min(node['width'], node['height']) / 2):
        raise ValueError('Animate corner radius exceeds the shape')
    result = {'x': node['x'], 'y': node['y'], 'w': node['width'], 'h': node['height'],
              'fill': node['fill'], 'stroke': node.get('stroke'), 'stroke_width': width, 'object': True}
    if node['type'] == 'rectangle':
        result['radius'] = node.get('radius', 0)
    return result


def plan(params):
    fields(params, ('stage', 'scenes'), (), 'scene request')
    stage = params['stage']; fields(stage, ('width', 'height', 'fps', 'background'), (), 'authored stage')
    native_stage = {**stage, 'background': color(stage['background'])}
    scenes = sequence(params['scenes'], 64, 'authored scenes')
    if not scenes:
        raise ValueError('Animate authoring requires at least one scene')
    seed = {'format': 'anicraft', 'version': 3, 'generator': 'DobeCLI', 'paths': [],
            'document': {'stage': native_stage, 'scenes': [], 'library': [], 'next_id': 1}}
    objects = []; changes = []; layers = keys = characters = 0
    for si, scene in enumerate(scenes):
        fields(scene, ('name', 'layers'), (), 'authored scene')
        if not text(scene['name'], 256) or not trim(scene['name']) or len(scene['name'].encode('utf-8')) > 256:
            raise ValueError('Animate scene name must be nonblank bounded text')
        target = {'name': scene['name'], 'timeline': {'layers': []}}
        seed['document']['scenes'].append(target)
        for li, layer in enumerate(sequence(scene['layers'], 128, 'authored layers')):
            fields(layer, ('name', 'keyframes'), ('visible', 'locked'), 'authored layer')
            if not text(layer['name'], 128):
                raise ValueError('Animate layer name exceeds its budget')
            if any(type(layer.get(key, default)) is not bool for key, default in [('visible', True), ('locked', False)]):
                raise ValueError('Animate authored layer flags must be booleans')
            layers += 1
            if layers > 128:
                raise ValueError('Animate authored scene exceeds its aggregate layer budget')
            native = {'id': layers, 'name': layer['name'], 'keyframes': []}
            target['timeline']['layers'].append(native); continuity = {}
            for ki, key in enumerate(sequence(layer['keyframes'], 512, 'authored keyframes')):
                fields(key, ('start', 'duration', 'objects'), ('tween', 'easing', 'label'), 'authored keyframe')
                keys += 1; seen = set()
                if keys > 512:
                    raise ValueError('Animate authored scene exceeds its aggregate keyframe budget')
                frame = {'start': key['start'], 'duration': key['duration'], 'elements': []}
                if 'label' in key:
                    if not text(key['label'], 128):
                        raise ValueError('Animate frame label exceeds its budget')
                    frame['label'] = key['label']
                native['keyframes'].append(frame)
                tween = key.get('tween')
                if tween not in (None, 'classic', 'shape') or 'easing' in key and tween is None:
                    raise ValueError('Animate tween must be classic or shape with explicit easing')
                if tween is not None:
                    easing(key.get('easing', 'Linear'))
                    if ki + 1 == len(layer['keyframes']):
                        raise ValueError('Animate tween requires a following keyframe')
                changes.append((si, li, ki,
                                None if tween is None else {'kind': tween.title(), 'easing': key.get('easing', 'Linear')}))
                for node in sequence(key['objects'], MAX_OBJECTS, 'authored objects'):
                    if len(objects) >= MAX_OBJECTS:
                        raise ValueError('Animate authored scene exceeds its aggregate object budget')
                    command = node_params(node)
                    if node['name'] in seen:
                        raise ValueError('Animate object names must be unique within a keyframe')
                    seen.add(node['name']); category = 'Text' if node['type'] == 'text' else 'Shape'
                    if node['name'] in continuity and continuity[node['name']][1] != category:
                        raise ValueError('Animate object continuity cannot change between text and shape')
                    continuity.setdefault(node['name'], (len(objects), category))
                    objects.append({'scene': si, 'layer_index': li, 'key_index': ki, 'layer': layers,
                                    'frame': key['start'], 'node': node, 'params': command,
                                    'continuity': continuity[node['name']][0]})
                    characters += len(node.get('text', '').encode('utf-8'))
                    if characters > 1 << 20:
                        raise ValueError('Animate authored scene exceeds its aggregate text budget')
    if layers > 128 or keys > 512 or len(objects) > MAX_OBJECTS or characters > 1 << 20:
        raise ValueError('Animate authored scene exceeds its aggregate budget')
    seed['document']['next_id'] = layers + 1
    document.inspect_bytes(json.dumps(seed, allow_nan=False).encode())
    for si, li, ki, tween in changes:
        keyframes = seed['document']['scenes'][si]['timeline']['layers'][li]['keyframes']
        if tween is not None and keyframes[ki]['start'] + keyframes[ki]['duration'] != keyframes[ki+1]['start']:
            raise ValueError('Animate tween spans must end at the following keyframe')
    return seed, objects, changes


def shape_path(node):
    """Expected primitive geometry, with the pinned native f32 arithmetic."""
    w, h = f32(node['width']), f32(node['height']); x, y = f32(-w/2), f32(-h/2)
    x1, y1 = f32(x+w), f32(y+h); r = f32(node.get('radius', 0)); commands = []
    def emit(kind, *values):
        commands.append(kind + ' '.join(str(f32(v)) for v in values))
    if node['type'] == 'ellipse':
        rx, ry = f32(w/2), f32(h/2); kx, ky = f32(rx*f32(.5522848)), f32(ry*f32(.5522848))
        emit('M', rx, 0); emit('C', rx, ky, kx, ry, 0, ry)
        emit('C', -kx, ry, -rx, ky, -rx, 0); emit('C', -rx, -ky, -kx, -ry, 0, -ry)
        emit('C', kx, -ry, rx, -ky, rx, 0)
    elif r == 0:
        emit('M', x,y); emit('L', x1,y); emit('L', x1,y1); emit('L', x,y1)
    else:
        k = f32(r*f32(1-f32(.5522848)))
        emit('M', x+r,y); emit('L', x1-r,y); emit('C', x1-k,y,x1,y+k,x1,y+r)
        emit('L', x1,y1-r); emit('C', x1,y1-k,x1-k,y1,x1-r,y1)
        emit('L', x+r,y1); emit('C', x+k,y1,x,y1-k,x,y1-r)
        emit('L', x,y+r); emit('C', x,y+k,x+k,y,x+r,y)
    emit('Z'); return ''.join(commands)


def expected_element(item, identity, actual, paths):
    node = item['node']; p = item['params']; x,y = f32(p['x']),f32(p['y'])
    if node['type'] == 'text':
        body = actual['kind'].get('Text')
        if body is None:
            raise ValueError('Animate text creation returned a different element kind')
        outline = body['outline']; outline = paths[outline] if type(outline) is int else outline
        # Only these three native layout outputs are derived. The stored-text
        # inspector checks their exact outline and metrics against real shaping.
        content = {key: p[key] for key in ('text', 'font', 'size', 'bold', 'italic', 'align',
                                           'letter_spacing', 'line_spacing', 'width')}
        content.update(color=color(p['color']), outline=outline, box_width=body['box_width'], box_height=body['box_height'])
        kind = {'Text': content}
    else:
        x,y = f32(x+f32(f32(p['w'])/2)),f32(y+f32(f32(p['h'])/2))
        kind = {'Shape': {'path': shape_path(node), 'fill': None if p['fill'] is None else {'Solid':color(p['fill'])},
                         'stroke': None if p['stroke'] is None else {'color':color(p['stroke']), 'width':p['stroke_width']},
                         'merge': False}}
    return {'id':identity, 'name':node['name'], 'transform':{'m':[1,0,0,1,x,y]}, 'kind':kind}


def create(root, params, executable, *, cancelled=lambda: False, seconds=120):
    """Author into a fresh owned directory and return the admitted native source."""
    seed, objects, changes = plan(params)
    root = Path(root).absolute(); root.mkdir()
    inspector = NativeInspector(executable, root, cancelled=cancelled, seconds=seconds)
    source = root/'seed.anicraft'; source.write_text(json.dumps(seed))
    saved = root/'drawn.anicraft'; steps = []; replies_at = []
    first_id = seed['document']['next_id']
    for item in objects:
        steps.extend([{'cmd':'scene.select','params':{'scene':item['scene']}},
                      {'cmd':'layer.select','params':{'layer':item['layer']}},
                      {'cmd':'timeline.goto','params':{'frame':item['frame']}}])
        replies_at.append(len(steps))
        command = {'rectangle':'draw.rect','ellipse':'draw.ellipse','text':'text.create'}[item['node']['type']]
        steps.extend([{'cmd':command,'params':item['params']}, {'cmd':'element.rename','params':{'name':item['node']['name']}}])
    steps.append({'cmd':'file.save','params':{'path':str(saved)}})
    script = root/'create.json'; data = json.dumps(steps).encode()
    if len(data) > 4 << 20:
        raise ValueError('Animate authoring batch exceeds its native script budget')
    script.write_bytes(data)
    command = [str(inspector.executable),'run',str(source),str(script),
               '--automation-read-root',str(inspector.root),'--automation-write-root',str(inspector.root)]
    replies = format.strict_json(run(command, inspector.root, deadline=inspector.deadline,
        cancelled=cancelled, stdout_limit=1 << 20))
    if not isinstance(replies,list) or len(replies)!=len(steps) or replies[-1]!={'saved':str(saved)}:
        raise ValueError('Animate authoring returned an incomplete native batch')
    actual = document.read_native(saved)
    expected = copy.deepcopy(seed)
    for index,(item,at) in enumerate(zip(objects,replies_at)):
        identity = first_id+index
        if (not isinstance(replies[at],dict) or type(replies[at].get('element')) is not int
                or replies[at]['element']!=identity or replies[at+1]!={'name':item['node']['name']}):
            raise ValueError('Animate authoring returned an unexpected object identity')
        layer = actual['envelope']['document']['scenes'][item['scene']]['timeline']['layers'][item['layer_index']]
        elements = layer['keyframes'][item['key_index']]['elements']
        matching = [e for e in elements if e['id']==identity]
        if len(matching)!=1:
            raise ValueError('Animate authored object is missing from its requested keyframe')
        target = expected['document']['scenes'][item['scene']]['timeline']['layers'][item['layer_index']]['keyframes'][item['key_index']]
        target['elements'].append(expected_element(item,identity,matching[0],actual['envelope']['paths']))
    expected['document']['next_id'] = first_id+len(objects)
    wanted = document.inspect_bytes(json.dumps(expected).encode())
    semantics.compare(wanted,actual)
    text_report = inspector.text(actual)
    if not text_report['glyph_coverage_verified'] or not text_report['native_layout_reproduced']:
        raise ValueError('Animate authored text failed native glyph or layout qualification')
    # Explicit object continuity drives native interpolation. Only newly authored
    # shapes/text are reidentified; no imported references or library items exist.
    for item in objects:
        key = expected['document']['scenes'][item['scene']]['timeline']['layers'][item['layer_index']]['keyframes'][item['key_index']]
        element = next(e for e in key['elements'] if e['name']==item['node']['name'])
        element['id'] = first_id+item['continuity']
    for si, requested_scene in enumerate(params['scenes']):
        for li, requested_layer in enumerate(requested_scene['layers']):
            expected['document']['scenes'][si]['timeline']['layers'][li].update(
                visible=requested_layer.get('visible', True), locked=requested_layer.get('locked', False))
    for si,li,ki,tween in changes:
        layer = expected['document']['scenes'][si]['timeline']['layers'][li]
        if tween is not None:
            layer['keyframes'][ki]['tween']=tween
    document.inspect_bytes(json.dumps(expected).encode())
    final = root/'authored.anicraft'; final.write_text(json.dumps(expected))
    return final, {'objects':len(objects),'native_drawing_verified':True,'requested_state_verified':True,
                   'text':text_report,'continuity':'Names within each layer identify the same object across keys.'}
