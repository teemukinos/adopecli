"""Declarative fill authoring and compare-and-set Texture layer revisions.

Native execution renders and saves the authored project. Only explicitly authored
floating-point fields may round to native f32 values; all other saved fields and
embedded bytes must remain exact. No native command is accepted from the caller.
"""
import copy
import io
import json
from pathlib import Path
import struct
import zipfile

from . import texture_document as document, texture_layers as layers, texture_project as settings
from . import texture_structure as structure, texture_workflow as workflow
from .texture_structure import require, integer

DEFAULT_CHANNELS = ['BaseColor', 'Metallic', 'Roughness', 'Normal', 'Height']
UV = {'Uv': {'scale': [1., 1.], 'rotation': 0., 'offset': [0., 0.]}}
PROPERTIES = ('name', 'visible', 'source', 'projection', 'blend')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def floating(value):
    if type(value) is list:
        require(1 <= len(value) <= 3, 'authored vector exceeds its dimension budget')
        for item in value: layers.number(item)
        return [float(item) for item in value]
    layers.number(value)
    return float(value)


def source_value(value):
    require(type(value) is dict and len(value) == 1, 'authored fill source must have one kind')
    result = copy.deepcopy(value)
    if 'Uniform' in result:
        result['Uniform'] = floating(result['Uniform'])
    elif 'Procedural' in result:
        body = result['Procedural']
        require(type(body) is dict and type(body.get('pattern')) is dict, 'authored procedural source is malformed')
        for key in ('low', 'high'):
            require(key in body, 'authored procedural source is incomplete')
            body[key] = floating(body[key])
        for key in ('scale', 'contrast', 'balance'):
            require(key in body['pattern'], 'authored procedural pattern is incomplete')
            body['pattern'][key] = floating(body['pattern'][key])
    return result


def projection_value(value):
    layers.projection(value)
    result = copy.deepcopy(value)
    body = next(iter(result.values()))
    for key in body:
        if key != 'axis': body[key] = floating(body[key])
    return result


def blend_value(value):
    layers.fields(value, ('mode', 'opacity')); layers.choice(value['mode'], layers.BLENDS); layers.unit(value['opacity'])
    return {'mode': value['mode'], 'opacity': float(value['opacity'])}


def validate_creation(params):
    layers.fields(params, ('name', 'mesh', 'resolution', 'layers'))
    layers.text(params['name'], 128)
    require(params['name'].strip(), 'authored project name cannot be empty')
    layers.choice(params['mesh'], document.BUILTINS)
    structure.resolution(params['resolution'])
    require(type(params['layers']) is list and 1 <= len(params['layers']) <= 128, 'creation needs 1 to 128 fill layers')
    for item in params['layers']:
        layers.fields(item, ('name', 'sources'), ('texture_set', 'projection', 'channels', 'visible'))
        layers.text(item['name'], 128)
        require(integer(item.get('texture_set', 0), 0, 15), 'authored texture-set index is invalid')
        require(type(item['sources']) is dict and item['sources'], 'authored fill needs channel sources')
        for channel, value in item['sources'].items():
            layers.choice(channel, structure.CHANNELS); source_value(value)
            require(next(iter(value)) in ('Uniform', 'Procedural'), 'creation sources require uniform values or procedural patterns')
        if 'projection' in item: projection_value(item['projection'])
        if 'channels' in item:
            require(type(item['channels']) is dict, 'authored blend channels must be an object')
            for channel, value in item['channels'].items():
                layers.choice(channel, structure.CHANNELS); blend_value(value)
        layers.boolean(item.get('visible', True))
    # Validate all source schemas and budget the actual layers before requesting
    # even a built-in mesh report. Placeholder materials cover requested indices.
    count = max(item.get('texture_set', 0) for item in params['layers']) + 1
    project = creation_project(params, ['Material '+str(i) for i in range(count)])
    checked = structure.inspect_json(canonical(project).encode())
    layers.inspect(checked); settings.inspect(checked)


def creation_project(params, materials):
    require(type(materials) is list and 1 <= len(materials) <= 16 and all(type(name) is str for name in materials),
            'built-in mesh material inventory is invalid')
    sets = []; authored = {}
    for index, name in enumerate(materials):
        channels = set(DEFAULT_CHANNELS)
        for item in params['layers']:
            if item.get('texture_set', 0) == index: channels.update(item['sources']); channels.update(item.get('channels', {}))
        formats = []
        for channel in structure.CHANNELS:
            if channel not in channels: continue
            fmt = 'Rgb16F' if channel in ('Normal', 'CoatNormal') else 'L16F' if channel == 'Height' else 'Srgb8' if structure.CHANNELS[channel] == 3 else 'L8'
            formats.append([channel, fmt])
        sets.append({'name': name, 'description': '', 'material': index, 'resolution': params['resolution'],
                     'channels': formats, 'stack': [], 'normal_mixing': 'Combine', 'ao_mixing': 'Multiply',
                     'height_strength': 1., 'bake': copy.deepcopy(settings.DEFAULT_BAKE), 'baked': [], 'visible': True})
        if params['mesh'] in ('udim_plane', 'udimplane'):
            # Pinned built-in mesh has the two adjacent UV tiles. A plain
            # one-tile project would wrap its second panel rather than author it.
            sets[-1]['uv_tiles'] = [1001, 1002]
    for identity, item in enumerate(params['layers'], 1):
        index = item.get('texture_set', 0)
        require(index < len(sets), 'authored texture-set index is absent from the built-in mesh')
        sources = {name: source_value(value) for name, value in item['sources'].items()}
        channels = {name: {'mode': 'Normal', 'opacity': 1.} for name in sources}
        channels.update({name: blend_value(value) for name, value in item.get('channels', {}).items()})
        authored[str(identity)] = {'id': identity, 'name': item['name'], 'visible': item.get('visible', True),
                                  'kind': {'Fill': {'sources': sources, 'projection': projection_value(item.get('projection', UV))}},
                                  'channels': channels, 'mask': None, 'content_effects': [], 'color_tag': None,
                                  'height_mask': {'enabled': False, 'contrast': 1., 'offset': 0.}, 'geometry_mask': None}
        sets[index]['stack'].append(identity)
    return {'format_version': 2, 'name': params['name'], 'mesh': 'builtin:'+params['mesh'], 'normal_format': 'OpenGl',
            'texture_sets': sets, 'layers': authored, 'next_id': len(authored)+1,
            'display': copy.deepcopy(settings.DEFAULT_DISPLAY), 'cameras': []}


def write_project(path, members, project):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in {**members, 'project.json': canonical(project).encode()}.items(): archive.writestr(name, data)
    data = output.getvalue()
    admitted = document.inspect_bytes(data)
    require(not path.exists() and not path.is_symlink(), 'authored destination already exists')
    path.write_bytes(data)
    return admitted


def native_float_equivalence(expected, actual, path='', changes=None):
    """Only f32-equivalent float serialization is allowed; no defaults or repair."""
    changes = [] if changes is None else changes
    require(type(expected) is type(actual), 'authored native value changed type at '+path)
    if type(expected) is dict:
        require(expected.keys() == actual.keys(), 'authored native fields changed at '+path)
        for key in expected: native_float_equivalence(expected[key], actual[key], path+'/'+key, changes)
    elif type(expected) is list:
        require(len(expected) == len(actual), 'authored native array changed at '+path)
        for index, value in enumerate(expected): native_float_equivalence(value, actual[index], path+'/'+str(index), changes)
    elif type(expected) is float:
        require(struct.pack('<f', expected) == struct.pack('<f', actual), 'authored native float changed beyond f32 precision at '+path)
        if canonical(expected) != canonical(actual): changes.append({'path': path, 'requested': expected, 'native': actual})
    else:
        require(expected == actual, 'authored native value changed at '+path)
    return changes


def create(root, params, executable):
    validate_creation(params)
    root = Path(root); root.mkdir()
    process = workflow.Engine(executable, root)
    mesh = process.value('info', 'builtin:'+params['mesh'])
    project = creation_project(params, mesh.get('materials') if type(mesh) is dict else None)
    source = root/'authored.tcraft'; before = write_project(source, {}, project)
    workflow.admission(before)
    saved_path = root/'canonical.tcraft'; saved = process.save(source, saved_path)
    rounding = native_float_equivalence(project, saved['structure']['project'])
    document.check_preservation(before, saved, expected_project=saved['structure']['project'])
    require(source.read_bytes() == before['source_bytes'], 'native creation changed its declarative source')
    return saved_path, {'authored_project': project, 'native_float_rounding': rounding,
                        'requested_state_verified': True, 'native_fields_verified': True}


def validate_edits(edits):
    require(type(edits) is list and 1 <= len(edits) <= 128, 'revision needs 1 to 128 targeted edits')
    seen = set()
    for edit in edits:
        require(type(edit) is dict, 'revision edit must be an object')
        layers.fields(edit, ('layer', 'property', 'expected', 'value'), ('channel',))
        require(integer(edit['layer'], 1), 'revision layer identity must be a positive integer')
        layers.choice(edit['property'], PROPERTIES)
        if edit['property'] in ('source', 'blend'):
            require('channel' in edit, 'source and blend revisions require a channel')
            layers.choice(edit['channel'], structure.CHANNELS)
        else:
            require('channel' not in edit, 'this revision property does not accept a channel')
        key = (edit['layer'], edit['property'], edit.get('channel'))
        require(key not in seen, 'revision targets the same property twice'); seen.add(key)
        if edit['property'] == 'name': layers.text(edit['value'], 128)
        elif edit['property'] == 'visible': layers.boolean(edit['value'])
        elif edit['property'] == 'projection': projection_value(edit['value'])
        elif edit['property'] == 'source': source_value(edit['value'])
        elif edit['property'] == 'blend': blend_value(edit['value'])
    require(len(canonical(edits).encode()) <= 1 << 20, 'revision parameters exceed their byte budget')


def target(project, edit):
    key = str(edit['layer']); require(key in project['layers'], 'revision layer is absent')
    layer = project['layers'][key]; prop = edit['property']
    if prop in ('source', 'projection'):
        require(type(layer['kind']) is dict and 'Fill' in layer['kind'], 'revision requires a fill layer')
        fill = layer['kind']['Fill']
        if prop == 'source': return fill['sources'], edit['channel']
        return fill, 'projection'
    if prop == 'blend': return layer['channels'], edit['channel']
    return layer, prop


def revise(root, source, edits, executable, *, accept_generated_uvs=False):
    validate_edits(edits)
    root = Path(root); root.mkdir()
    before = document.read_native(source); workflow.admission(before, accept_generated_uvs=accept_generated_uvs)
    expected = copy.deepcopy(before['structure']['project']); changes = []
    for edit in edits:
        container, key = target(expected, edit)
        require(key in container, 'revision cannot add an absent property; author it explicitly first')
        require(canonical(container[key]) == canonical(edit['expected']), 'revision precondition differs from the current native value')
        value = {'source': source_value, 'blend': blend_value, 'projection': projection_value}.get(edit['property'], copy.deepcopy)(edit['value'])
        container[key] = value
        changes.append({'layer': edit['layer'], 'property': edit['property'], 'channel': edit.get('channel'),
                        'before': edit['expected'], 'requested': value})
    candidate = root/'authored.tcraft'; proposed = write_project(candidate, before['members'], expected)
    workflow.admission(proposed, accept_generated_uvs=accept_generated_uvs)
    process = workflow.Engine(executable, root)
    saved_path = root/'canonical.tcraft'; saved = process.save(candidate, saved_path)
    # Only requested slots admit f32 serialization. Every unrequested field is
    # compared strictly, including its JSON scalar type and signed zero.
    predicted = copy.deepcopy(expected); rounding = []
    for edit, change in zip(edits, changes):
        planned, key = target(predicted, edit); actual, actual_key = target(saved['structure']['project'], edit)
        rounding.extend(native_float_equivalence(planned[key], actual[actual_key], '/layers/'+str(edit['layer'])+'/'+edit['property']))
        planned[key] = actual[actual_key]; change['native'] = actual[actual_key]
    document.check_preservation(before, saved, expected_project=predicted)
    require(source.read_bytes() == before['source_bytes'], 'revision changed original native source bytes')
    return saved_path, {'source_sha256': before['source_sha256'], 'edits': changes, 'native_float_rounding': rounding,
                        'requested_state_verified': True, 'unrequested_native_fields_verified': True,
                        'embedded_bytes_preserved': True}


def compare_maps(before, after, profile, edits):
    """Preserve maps outside changed sets; instances/anchors widen dependencies."""
    rendering = [edit for edit in edits if edit['property'] != 'name']
    affected = {profile['structure']['ids'][edit['layer']]['texture_set'] for edit in rendering}
    instances = any(type(layer['kind']) is dict and 'Instance' in layer['kind'] for layer in profile['structure']['layers'].values())
    if rendering and (instances or profile['layer_semantics']['anchor_reads']):
        affected = set(range(len(profile['structure']['project']['texture_sets'])))
    expected = [item for item in before['maps'] if item['texture_set'] not in affected]
    actual = [item for item in after['maps'] if item['texture_set'] not in affected]
    require(expected == actual, 'revision changed maps outside the conservative affected texture sets')
    return {'affected_texture_sets': sorted(affected), 'unchanged_map_files': [item['file'] for item in expected],
            'unaffected_maps_verified': True}
