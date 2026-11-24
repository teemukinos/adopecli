"""Pinned Texture project/display/camera/bake metadata and execution budgets.

Default values below match the pinned v0.6.1 native writer. They are used for
validation and explicit operation planning only; source documents are not edited.
Schema admission never authorizes a bake or silently applies native recovery.
"""
import copy
import math

from .texture_layers import fields, number, vector, boolean, text, choice, unit, positive
from .texture_structure import require, integer, MAX_ATLAS_SIDE, MAX_ATLAS_TEXELS
from .texture_pixels import MAX_PIXEL_BYTES

DEFAULT_DISPLAY = {'environment': 'Studio Soft',
 'env_opacity': 0.0,
 'env_exposure': 0.0,
 'env_blur': 0.35,
 'env_rotation': 0.0,
 'shadows': False,
 'tone_mapping': 'AcesFilmic',
 'fov': 40.0,
 'post_effects': False,
 'bloom': 0.0,
 'vignette': 0.0,
 'sharpen': 0.0,
 'grain': 0.0,
 'ao_intensity': 0.75,
 'taa': True,
 'spec_gloss': False,
 'parallax': False,
 'displacement': False,
 'scatter_color': [1.0, 0.4, 0.25],
 'scatter_radius': 0.1,
 'ior': 1.5,
 'dof': {'enabled': False, 'focusDistance': 0.0, 'aperture': 0.05}}

DEFAULT_BAKE = {'common': {'is_enabled': True,
            'resolution': 'R2048',
            'resolution_height': None,
            'antialiasing': 'None',
            'dilation': 1,
            'apply_diffusion': True},
 'high_poly': {'use_low_as_high': False,
               'ignore_backface': True,
               'match_mode': 'Always',
               'low_suffix': '_low',
               'high_suffix': '_high',
               'ignore_backface_suffix': '_ignorebf'},
 'cage': {'kind': 'DistanceBased',
          'max_frontal': 0.01,
          'max_rear': 0.01,
          'relative_to_bounding_box': True,
          'average_normals': True},
 'skew': {'method': 'MeshNormalsBased',
          'edge_protection': False,
          'edge_distance': 0.15,
          'edge_contrast': 0.5},
 'maps': {'normal': {'is_enabled': True, 'parameters': None},
          'world_normal': {'is_enabled': True, 'parameters': None},
          'id': {'is_enabled': True, 'parameters': {'source': 'MaterialColor', 'generator': 'HueShift'}},
          'ao': {'is_enabled': True,
                 'parameters': {'rays': {'rays': 64,
                                         'min_distance': 1e-05,
                                         'max_distance': 1.0,
                                         'relative_to_bounding_box': True,
                                         'spread': 180.0,
                                         'distribution': 'Cosine'},
                                'ignore_backface': 'Never',
                                'self_occlusion': 'Always',
                                'attenuation': 'Linear',
                                'ground_plane': {'enabled': False, 'offset': 0.0}}},
          'curvature': {'is_enabled': True,
                        'parameters': {'method': 'Mesh',
                                       'normal_map': {'details': 0.5,
                                                      'enable_seams': True,
                                                      'seams_intensity': 1.0},
                                       'mesh': {'rays': 32,
                                                'sampling_radius': 0.001,
                                                'relative_to_bounding_box': True,
                                                'self_intersection': 'Always',
                                                'auto_tonemapping': True,
                                                'value_min': -1.0,
                                                'value_max': 1.0}}},
          'position': {'is_enabled': True,
                       'parameters': {'axis': 'All',
                                      'normalization': 'BoundingSphere',
                                      'scale': 'FullScene'}},
          'thickness': {'is_enabled': True,
                        'parameters': {'rays': {'rays': 64,
                                                'min_distance': 1e-05,
                                                'max_distance': 0.1,
                                                'relative_to_bounding_box': True,
                                                'spread': 180.0,
                                                'distribution': 'Cosine'},
                                       'self_occlusion': 'Always',
                                       'normalization': 'RelativeToMinMax'}},
          'height': {'is_enabled': False,
                     'parameters': {'normalization': 'RelativeToLowMesh', 'scaling_divisor': 1.0}},
          'bent_normal': {'is_enabled': False,
                          'parameters': {'rays': {'rays': 64,
                                                  'min_distance': 1e-05,
                                                  'max_distance': 1.0,
                                                  'relative_to_bounding_box': True,
                                                  'spread': 180.0,
                                                  'distribution': 'Cosine'},
                                         'ignore_backface': 'Never',
                                         'self_occlusion': 'Always'}},
          'opacity': {'is_enabled': False, 'parameters': None}}}

RESOLUTIONS = {'R' + str(2**power): 2**power for power in range(4, 14)}
ANTIALIASING = {'None': 1, 'Subsampling2x2': 2, 'Subsampling4x4': 4, 'Subsampling8x8': 8}
MAP_COMPONENTS = {'normal': 3, 'world_normal': 3, 'id': 3, 'ao': 1, 'curvature': 1,
                  'position': 3, 'thickness': 1, 'height': 1, 'bent_normal': 3, 'opacity': 1}
MAX_BAKE_SAMPLES = 16_777_216
MAX_BAKE_WORK = 536_870_912
CAMERA_DEFAULT = {'name': 'Camera', 'target': [0., 0., 0.], 'yaw': 0., 'pitch': 0.,
                  'distance': 5., 'fov': 40., 'ortho': False}


def enumeration(*values):
    return lambda value: choice(value, values)


def bounded(low, high):
    return lambda value: number(value, low, high)


def uint(low, high):
    return lambda value: require(integer(value, low, high), 'project integer parameter is outside its range')


def environment(value):
    text(value, 129)
    require(value in ('Studio Soft', 'Studio Contrast', 'Overcast', 'Sunset', 'Warehouse', 'Night')
            or (value.startswith('resource:') and len(value) > 9), 'project environment is unknown')


DISPLAY_SCHEMA = {
    'environment': environment, 'env_opacity': unit, 'env_exposure': bounded(-32, 32), 'env_blur': unit,
    'env_rotation': number, 'shadows': boolean, 'tone_mapping': enumeration('Linear', 'AcesFilmic'),
    'fov': bounded(5, 150), 'post_effects': boolean, 'bloom': unit, 'vignette': unit, 'sharpen': unit,
    'grain': unit, 'ao_intensity': unit, 'taa': boolean, 'spec_gloss': boolean, 'parallax': boolean,
    'displacement': boolean, 'scatter_color': lambda v: vector(v, 3, 0), 'scatter_radius': bounded(0, 100),
    'ior': bounded(1, 4), 'dof': {'enabled': boolean, 'focusDistance': bounded(0, 65504), 'aperture': bounded(0, 1)},
}
CAMERA_SCHEMA = {'name': text, 'target': vector, 'yaw': number, 'pitch': bounded(-math.radians(89), math.radians(89)),
                 'distance': positive, 'fov': bounded(5, 150), 'ortho': boolean}
RAY_SCHEMA = {'rays': uint(1, 4096), 'min_distance': bounded(0, 65504), 'max_distance': positive,
              'relative_to_bounding_box': boolean, 'spread': bounded(0, 180), 'distribution': enumeration('Cosine', 'Uniform')}
BACKFACE = enumeration('Never', 'Always', 'ByMeshName')
OCCLUSION = enumeration('Always', 'SameMeshName')
MAP_SCHEMAS = {
    'normal': None, 'world_normal': None, 'opacity': None,
    'id': {'source': enumeration('VertexColor', 'MaterialColor', 'FileId', 'MeshId', 'Submesh'),
           'generator': enumeration('Random', 'HueShift', 'Grayscale')},
    'ao': {'rays': RAY_SCHEMA, 'ignore_backface': BACKFACE, 'self_occlusion': OCCLUSION,
           'attenuation': enumeration('None', 'Smooth', 'Linear'), 'ground_plane': {'enabled': boolean, 'offset': bounded(0, 100)}},
    'curvature': {'method': enumeration('NormalMap', 'Mesh'),
                  'normal_map': {'details': unit, 'enable_seams': boolean, 'seams_intensity': unit},
                  'mesh': {'rays': uint(1, 4096), 'sampling_radius': positive, 'relative_to_bounding_box': boolean,
                           'self_intersection': OCCLUSION, 'auto_tonemapping': boolean, 'value_min': number, 'value_max': number}},
    'position': {'axis': enumeration('All', 'X', 'Y', 'Z'), 'normalization': enumeration('BoundingBox', 'BoundingSphere', 'None'),
                 'scale': enumeration('PerMaterial', 'FullScene')},
    'thickness': {'rays': RAY_SCHEMA, 'self_occlusion': OCCLUSION,
                  'normalization': enumeration('RelativeToRayDistances', 'RelativeToMinMax', 'None')},
    'height': {'normalization': enumeration('RelativeToRayDistances', 'RelativeToLowMesh', 'RelativeToMinMax', 'Manual'),
               'scaling_divisor': positive},
    'bent_normal': {'rays': RAY_SCHEMA, 'ignore_backface': BACKFACE, 'self_occlusion': OCCLUSION},
}
BAKE_SCHEMA = {
    'common': {'is_enabled': boolean, 'resolution': lambda v: choice(v, RESOLUTIONS),
               'resolution_height': lambda v: require(v is None or type(v) is str and v in RESOLUTIONS, 'bake height resolution is invalid'),
               'antialiasing': lambda v: choice(v, ANTIALIASING), 'dilation': uint(0, 128), 'apply_diffusion': boolean},
    'high_poly': {'use_low_as_high': boolean, 'ignore_backface': boolean, 'match_mode': enumeration('Always', 'ByMeshName'),
                  'low_suffix': text, 'high_suffix': text, 'ignore_backface_suffix': text},
    'cage': {'kind': enumeration('DistanceBased', 'CustomFile'), 'max_frontal': bounded(0, 65504),
             'max_rear': bounded(0, 65504), 'relative_to_bounding_box': boolean, 'average_normals': boolean},
    'skew': {'method': enumeration('MeshNormalsBased', 'FaceNormalsBased'), 'edge_protection': boolean,
             'edge_distance': unit, 'edge_contrast': unit},
    'maps': {name: {'is_enabled': boolean, 'parameters': schema} for name, schema in MAP_SCHEMAS.items()},
}


def _validate(value, schema, defaults, missing, path):
    if schema is None:
        require(value is None, 'parameterless bake map must have null parameters')
        return None
    if callable(schema):
        schema(value)
        return value
    fields(value, (), schema)
    # MapSettings<T> itself has no serde(default), unlike its typed parameters.
    if set(schema) == {'is_enabled', 'parameters'}:
        fields(value, schema)
    result = {}
    for key, check in schema.items():
        if key not in value:
            missing.append(path + '/' + key)
        result[key] = _validate(value.get(key, copy.deepcopy(defaults[key])), check, defaults[key], missing, path + '/' + key)
    return result


def inspect(structure):
    project = structure['project']; missing = []
    fields(project, ('format_version', 'name', 'mesh', 'normal_format', 'texture_sets', 'layers', 'next_id', 'display'),
           ('mesh_file', 'mesh_path', 'cameras'))
    text(project['name']); choice(project['normal_format'], ('OpenGl', 'DirectX'))
    display = _validate(project['display'], DISPLAY_SCHEMA, DEFAULT_DISPLAY, missing, '/display')
    cameras = project.get('cameras', [])
    if 'cameras' not in project: missing.append('/cameras')
    require(type(cameras) is list and len(cameras) <= 64, 'saved camera count exceeds its budget')
    for i, camera in enumerate(cameras): _validate(camera, CAMERA_SCHEMA, CAMERA_DEFAULT, missing, '/cameras/' + str(i))
    bakes = []; materials = set()
    for i, item in enumerate(project['texture_sets']):
        path = '/texture_sets/' + str(i)
        fields(item, ('name', 'material', 'resolution', 'channels', 'stack'),
               ('description', 'normal_mixing', 'ao_mixing', 'height_strength', 'bake', 'baked', 'visible',
                'uv_tiles', 'bake_excluded_tiles', 'tile_resolutions'))
        text(item['name']); require(integer(item['material'], 0, 15), 'texture set material index is invalid')
        require(item['material'] not in materials, 'multiple texture sets refer to the same material'); materials.add(item['material'])
        optional = {'description': (text, ''), 'normal_mixing': (enumeration('Combine', 'Replace'), 'Combine'),
                    'ao_mixing': (enumeration('Multiply', 'None'), 'Multiply'), 'height_strength': (number, 1.), 'visible': (boolean, True)}
        for key, (check, default) in optional.items():
            if key not in item: missing.append(path + '/' + key)
            check(item.get(key, default))
        for key in ('bake', 'baked'):
            if key not in item: missing.append(path + '/' + key)
        bake = _validate(item.get('bake', {}), BAKE_SCHEMA, DEFAULT_BAKE, missing, path + '/bake')
        for key in ('ao', 'thickness', 'bent_normal'):
            rays = bake['maps'][key]['parameters']['rays']
            require(rays['min_distance'] <= rays['max_distance'], 'bake ray distance range is reversed')
        curvature = bake['maps']['curvature']['parameters']['mesh']
        require(curvature['auto_tonemapping'] or curvature['value_min'] < curvature['value_max'], 'manual curvature range is reversed')
        bakes.append(bake)
    return {'display': display, 'bakes': bakes, 'saved_cameras': len(cameras), 'missing_defaults': missing,
            'source_modified': False, 'bake_authorized': False, 'project_admission_complete': False}


def bake_budget(structure, metadata, *, texture_sets=None, cage_available=False):
    """Plan a bake's allocation/sample counters; never launch it or edit settings.

    All settings overrides must be applied to a separately predicted project
    before this call. Inert imported metadata is not rejected merely because an
    unrequested bake would exceed the execution budget. Counts include atlas
    holes/excluded tiles conservatively and square the per-axis antialiasing.
    """
    sets = structure['project']['texture_sets']
    selected = list(range(len(sets))) if texture_sets is None else texture_sets
    require(type(selected) is list and len(selected) <= len(sets)
            and all(integer(i, 0, len(sets)-1) for i in selected) and len(set(selected)) == len(selected),
            'bake texture-set selection is invalid')
    outputs = []; output_bytes = samples = work = 0
    for i in selected:
        item = sets[i]; settings = metadata['bakes'][i]; common = settings['common']
        tiles = item.get('uv_tiles', [])
        if not common['is_enabled'] or tiles and set(tiles) <= set(item.get('bake_excluded_tiles', [])):
            continue
        enabled = [name for name, config in settings['maps'].items() if config['is_enabled']]
        if not enabled: continue
        require(settings['cage']['kind'] != 'CustomFile' or cage_available, 'bake requires an admitted custom cage')
        width = RESOLUTIONS[common['resolution']]; height = RESOLUTIONS[common['resolution_height'] or common['resolution']]
        if tiles:
            cols = [(t-1001) % 10 for t in tiles]; rows = [(t-1001) // 10 for t in tiles]
            width *= max(cols)-min(cols)+1; height *= max(rows)-min(rows)+1
        pixels = width * height
        require(width <= MAX_ATLAS_SIDE and height <= MAX_ATLAS_SIDE and pixels <= MAX_ATLAS_TEXELS,
                'bake output atlas exceeds its pixel budget')
        axis = ANTIALIASING[common['antialiasing']]; current_samples = pixels * axis * axis
        byte_count = pixels * sum(MAP_COMPONENTS[name] for name in enabled) * 4 + 24 * len(enabled)
        ray_factor = 1
        for name in enabled:
            params = settings['maps'][name]['parameters']
            if name in ('ao', 'thickness', 'bent_normal'): ray_factor += params['rays']['rays']
            if name == 'curvature' and params['method'] == 'Mesh': ray_factor += 2 * params['mesh']['rays']
        output_bytes += byte_count; samples += current_samples; work += current_samples * ray_factor
        require(output_bytes <= MAX_PIXEL_BYTES and samples <= MAX_BAKE_SAMPLES and work <= MAX_BAKE_WORK,
                'bake allocation or sampling exceeds its execution budget')
        outputs.append({'texture_set': i, 'width': width, 'height': height, 'maps': enabled,
                        'output_bytes': byte_count, 'samples': current_samples, 'nominal_ray_work': current_samples * ray_factor})
    require(outputs, 'bake selection has no enabled outputs')
    return {'outputs': outputs, 'output_bytes': output_bytes, 'samples': samples, 'nominal_ray_work': work,
            'execution_authorized': False}
