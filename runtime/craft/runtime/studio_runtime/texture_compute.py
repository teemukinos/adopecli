"""Bounded CPU preview and mesh-map baking with independent preservation plans.

Counters are admission estimates, not CPU-time, memory or price guarantees.
Inputs cannot select a GPU, executable, command, filesystem path or output name.
"""
import copy
import io
import json
from pathlib import Path
import struct
import time

from PIL import Image

from . import texture_authoring as authoring, texture_document as document, texture_images
from . import texture_layers as layers, texture_pixels, texture_project as settings, texture_workflow as workflow
from .texture_structure import require, integer, BAKED

MAX_PREVIEW_PIXELS = 4_194_304
MAX_PREVIEW_WORK = 268_435_456
MAPS = dict(zip(('normal', 'worldNormal', 'id', 'ambientOcclusion', 'curvature', 'position', 'thickness', 'height', 'bentNormal', 'opacity'),
                zip(('normal', 'world_normal', 'id', 'ao', 'curvature', 'position', 'thickness', 'height', 'bent_normal', 'opacity'), BAKED)))


def validate_render(value):
    layers.fields(value, ('width', 'height', 'samples', 'bounces'), ('yaw', 'pitch', 'camera'))
    require(all(integer(value[key], 16, 4096) for key in ('width', 'height')), 'preview dimensions must be 16 to 4096')
    require(integer(value['samples'], 1, 256) and integer(value['bounces'], 1, 32), 'preview samples or bounces exceed their limits')
    pixels = value['width'] * value['height']; work = pixels * value['samples'] * value['bounces']
    require(pixels <= MAX_PREVIEW_PIXELS and work <= MAX_PREVIEW_WORK, 'CPU preview exceeds its pixel or sample-bounce budget')
    for key, limit in (('yaw', 360), ('pitch', 89)):
        if key in value: layers.number(value[key], -limit, limit)
    if 'camera' in value:
        layers.text(value['camera'], 128); require(value['camera'], 'saved camera name cannot be empty')
    return {'pixels': pixels, 'sample_bounce_work': work}


def render(root, source, request, executable, *, accept_generated_uvs=False):
    budget = validate_render(request)
    profile = document.read_native(source); workflow.admission(profile, accept_generated_uvs=accept_generated_uvs)
    if 'camera' in request:
        cameras = profile['structure']['project'].get('cameras', [])
        require(sum(camera['name'] == request['camera'] for camera in cameras) == 1, 'preview requires a unique saved camera name')
    root = Path(root); root.mkdir(); snapshot = root/'source.tcraft'; snapshot.write_bytes(profile['source_bytes'])
    process = workflow.Engine(executable, root); process.observe(snapshot, profile)
    saved_path = root/'cold.tcraft'; saved = process.save(snapshot, saved_path); document.check_preservation(profile, saved)
    outputs = []; timings = []
    for current, name in ((snapshot, 'preview.png'), (saved_path, 'cold-preview.png')):
        target = root/name
        arguments = ['render', str(current), str(target), '--size', str(request['width'])+'x'+str(request['height']),
                     '--samples', str(request['samples']), '--bounces', str(request['bounces']), '--cpu']
        for key in ('yaw', 'pitch', 'camera'):
            if key in request: arguments += ['--'+key, str(request[key])]
        started = time.monotonic(); process.invoke(*arguments); timings.append(time.monotonic()-started)
        require(target.is_file() and not target.is_symlink() and target.stat().st_size <= 32 << 20, 'CPU preview is not a bounded regular PNG')
        data = target.read_bytes(); metadata = texture_images.inspect_bytes(data)
        require(metadata['format'] == 'PNG' and (metadata['width'], metadata['height']) == (request['width'], request['height']),
                'CPU preview dimensions disagree with the request')
        with Image.open(io.BytesIO(data)) as image: pixels = image.convert('RGBA').tobytes()
        outputs.append({'bytes': len(data), 'sha256': workflow.digest(data), 'pixel_sha256': workflow.digest(pixels)})
    require(outputs[0] == outputs[1], 'cold CPU preview differs in encoded bytes or decoded pixels')
    require(source.read_bytes() == profile['source_bytes'], 'CPU preview changed its native source')
    return root/'preview.png', {'backend': 'CPU', 'request': request, 'budget': budget, **outputs[0],
                              'source_sha256': profile['source_sha256'], 'cold_preview_equal': True,
                              'source_bytes_unchanged': True, 'native_command_seconds': timings,
                              'timing_scope': 'two local native preview commands; not a production benchmark'}


def validate_bake(value):
    layers.fields(value, ('texture_sets', 'resolution', 'maps', 'rays', 'use_low_as_high'), ('antialiasing',))
    selected = value['texture_sets']
    require(type(selected) is list and 1 <= len(selected) <= 16 and all(integer(i, 0, 15) for i in selected)
            and len(set(selected)) == len(selected), 'bake selection requires distinct texture-set indices')
    require(integer(value['resolution'], 16, 8192) and value['resolution'] & (value['resolution']-1) == 0,
            'bake resolution must be a power of two from 16 to 8192')
    maps = value['maps']
    require(type(maps) is list and 1 <= len(maps) <= len(MAPS) and all(type(m) is str and m in MAPS for m in maps)
            and len(set(maps)) == len(maps), 'bake map selection is invalid or duplicated')
    require(integer(value['rays'], 1, 256), 'bake rays must be 1 to 256')
    layers.boolean(value['use_low_as_high'])
    require(type(value.get('antialiasing', 1)) is int and value.get('antialiasing', 1) in (1, 2, 4, 8),
            'bake antialiasing must be 1, 2, 4 or 8 samples per axis')


def bake_plan(profile, request):
    validate_bake(request)
    expected = copy.deepcopy(profile['structure']['project']); selected = request['texture_sets']
    require(all(i < len(expected['texture_sets']) for i in selected), 'bake texture set is absent')
    if not request['use_low_as_high']:
        require(any(item['role'] == 'highpoly' for item in profile['meshes']['members'].values()),
                'bake requires admitted high-poly geometry or explicit low-as-high selection')
    for index in selected:
        bake = expected['texture_sets'][index]['bake']
        bake['common'].update(is_enabled=True, resolution='R'+str(request['resolution']), resolution_height=None,
                              antialiasing={1:'None',2:'Subsampling2x2',4:'Subsampling4x4',8:'Subsampling8x8'}[request.get('antialiasing',1)])
        bake['high_poly']['use_low_as_high'] = request['use_low_as_high']
        for identity, (name, _) in MAPS.items():
            config = bake['maps'][name]; config['is_enabled'] = identity in request['maps']
            if identity in request['maps']:
                if name in ('ao', 'thickness', 'bent_normal'): config['parameters']['rays']['rays'] = request['rays']
                if name == 'curvature': config['parameters']['mesh']['rays'] = request['rays']
    proposed_structure = {**profile['structure'], 'project': expected}
    metadata = settings.inspect(proposed_structure)
    cage = any(item['role'] == 'cage' for item in profile['meshes']['members'].values())
    budget = settings.bake_budget(proposed_structure, metadata, texture_sets=selected, cage_available=cage)
    require([row['texture_set'] for row in budget['outputs']] == selected, 'bake selection includes a set with no enabled tiles')
    changed = {}; total = profile['pixels']['bytes']
    for output in budget['outputs']:
        index = output['texture_set']; item = expected['texture_sets'][index]
        for name, record in profile['pixels']['members'].items():
            if not name.startswith('baked/'+str(index)+'_'): continue
            identity = name.split('_',1)[1][:-4]
            resized = (record['width'], record['height']) != (output['width'], output['height'])
            require(not resized or identity in request['maps'], 'resizing baked maps requires selecting every existing map')
            require(not resized or not item.get('bake_excluded_tiles'), 'resizing retained excluded bake tiles needs separate qualification')
        existing = set(item['baked']); requested = {MAPS[name][1] for name in request['maps']}
        item['baked'] = [name for name in BAKED if name in existing | requested]
        for identity in request['maps']:
            _, kind = MAPS[identity]; name = 'baked/'+str(index)+'_'+identity+'.bin'
            size = 24 + output['width']*output['height']*BAKED[kind]*4
            total += size - len(profile['members'].get(name,b''))
            changed[name] = {'width': output['width'], 'height': output['height'], 'components': BAKED[kind], 'bytes': size,
                             'texture_set': index, 'kind': kind}
    require(total <= texture_pixels.MAX_PIXEL_BYTES, 'retained and requested bake payloads exceed the aggregate pixel byte budget')
    return expected, budget, changed


def excluded_tiles(before, after, project, planned):
    verified = 0
    for name, record in planned.items():
        item = project['texture_sets'][record['texture_set']]; excluded = item.get('bake_excluded_tiles', [])
        if not excluded: continue
        tiles = item['uv_tiles']; min_col = min((tile-1001)%10 for tile in tiles); min_row = min((tile-1001)//10 for tile in tiles)
        columns = max((tile-1001)%10 for tile in tiles)-min_col+1; rows = max((tile-1001)//10 for tile in tiles)-min_row+1
        width, height, components = record['width'], record['height'], record['components']
        tile_width, tile_height = width//columns, height//rows
        neutral = (.5,.5,1.) if record['kind'] in ('Normal','WorldNormal','BentNormal') else (1.,) if record['kind'] in ('AmbientOcclusion','Thickness') else (.5,) if record['kind'] in ('Curvature','Height') else (0.,)*components
        previous = before['members'].get(name)
        for tile in excluded:
            x = ((tile-1001)%10-min_col)*tile_width; y = ((tile-1001)//10-min_row)*tile_height
            for row in range(y,y+tile_height):
                start = 24+(row*width+x)*components*4; end = start+tile_width*components*4
                expected = previous[start:end] if previous else struct.pack('<'+'f'*components,*neutral)*tile_width
                require(after['members'][name][start:end] == expected, 'bake changed an excluded tile')
            verified += 1
    return verified


def check_bake(before, after, expected_project, planned):
    require(set(after['members']) == set(before['members']) | set(planned), 'bake dropped or introduced unplanned members')
    require(authoring.canonical(after['structure']['project']) == authoring.canonical(expected_project), 'bake changed unrequested project fields')
    for name, data in before['members'].items():
        if name != 'project.json' and name not in planned:
            require(after['members'][name] == data, 'bake changed unrequested embedded bytes: '+name)
    for name, dimensions in planned.items():
        observed = after['pixels']['members'].get(name, {})
        require(all(observed.get(key) == dimensions[key] for key in ('width','height','components','bytes')),
                'bake map dimensions or byte count differ from the plan')
    return excluded_tiles(before, after, expected_project, planned)


def bake(root, source, request, executable, *, accept_generated_uvs=False):
    validate_bake(request)
    original = document.read_native(source); workflow.admission(original, accept_generated_uvs=accept_generated_uvs)
    expected, budget, planned = bake_plan(original, request)
    root = Path(root); root.mkdir(); snapshot = root/'source.tcraft'; snapshot.write_bytes(original['source_bytes'])
    # The pre-bake candidate retains the previous map inventory. Only the new
    # settings change before execution; new baked identities appear on success.
    candidate_project = copy.deepcopy(expected)
    for index in request['texture_sets']:
        candidate_project['texture_sets'][index]['baked'] = original['structure']['project']['texture_sets'][index]['baked']
    candidate = root/'configured.tcraft'; profile = authoring.write_project(candidate, original['members'], candidate_project)
    process = workflow.Engine(executable, root); process.observe(snapshot, original)
    saved = process.save(snapshot, root/'before-cold.tcraft'); document.check_preservation(original,saved)
    timings=[]; outputs=[]; excluded=0
    for name in ('baked.tcraft', 'repeated.tcraft'):
        target = root/name; started = time.monotonic()
        reply = process.value('run', candidate, 'bake.run', json.dumps({'ts':request['texture_sets'],'cpu':True}), '-o', target)
        timings.append(time.monotonic()-started)
        require(type(reply) is dict and reply.get('baked') == request['texture_sets']
                and reply.get('tracer') == ['CPU']*len(request['texture_sets']), 'native bake did not execute the selected sets on CPU')
        current = document.read_native(target); excluded = check_bake(original,current,expected,planned); outputs.append(current)
    document.check_preservation(outputs[0],outputs[1])
    cold = process.save(root/'baked.tcraft',root/'baked-cold.tcraft');document.check_preservation(outputs[0],cold)
    require(source.read_bytes() == original['source_bytes'], 'bake changed original source bytes')
    return root/'baked.tcraft', {'backend':'CPU','request':request,'budget':budget,'maps':planned,
                              'source_sha256':original['source_sha256'],'requested_state_verified':True,
                              'unrequested_native_fields_verified':True,'unrequested_embedded_bytes_verified':True,
                              'excluded_map_tiles_verified':excluded,'repeated_bake_equal':True,'native_cold_reopen':True,
                              'native_command_seconds':timings,'timing_scope':'two local native bake commands; not a production benchmark'}
