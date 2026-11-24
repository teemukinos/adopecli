"""Compound Texture preflight and complete archive inventory.

Other mesh formats and operation policies need qualification.
A preflight result is not authorization to execute the native engine. No public
operation is registered here. Original bytes and all member bytes are retained.
"""
import hashlib
import json

from . import texture_archive, texture_structure, texture_pixels, texture_images, texture_mesh, texture_layers, texture_project
from .texture_structure import require

MESH_EXTENSIONS = {'gltf', 'glb', 'fbx', 'dae', 'usd', 'usda', 'usdc', 'usdz', 'abc', 'obj', 'ply', 'stl'}
BUILTINS = {'material_ball', 'materialball', 'ball', 'sphere', 'cube', 'rounded_cube', 'roundedcube', 'box',
            'cylinder', 'torus', 'plane', 'crate', 'udim_plane', 'udimplane', 'preview_orb'}


def _mesh_name(name):
    require(type(name) is str and 1 <= len(name) <= 120 and not name.startswith('.')
            and all(c.isascii() and (c.isalnum() or c in '_.-') for c in name),
            'embedded mesh name would be changed by the native writer')
    require('.' in name and name.rsplit('.', 1)[1].lower() in MESH_EXTENSIONS, 'embedded mesh extension is unsupported')


def inspect_bytes(data):
    snapshot = texture_archive.inspect_bytes(data)
    members = snapshot['members']
    structure = texture_structure.inspect_json(members['project.json'])
    metadata = texture_project.inspect(structure)
    layers = texture_layers.inspect(structure)
    pixels = texture_pixels.inspect_members(members, structure)
    resources = texture_images.inspect_resources(members, structure)
    inventory = {}; meshes = []; primary = []; cages = []; thumbnail = None
    for name, member in members.items():
        if name == 'project.json':
            role = 'project'
        elif name == 'thumbnail.png':
            thumbnail = texture_images.inspect_bytes(member)
            require(thumbnail['format'] == 'PNG', 'native thumbnail must contain a PNG image')
            role = 'source-thumbnail'
        elif name in pixels['members']:
            role = 'pixels'
        elif name.startswith('resources/'):
            leaf = name[len('resources/'):]
            require(leaf in resources['images'] or leaf in resources['packages'], 'resource has no admission record')
            role = 'image' if leaf in resources['images'] else 'opaque-material-package'
        elif name.startswith('mesh.') and name[5:] in MESH_EXTENSIONS:
            primary.append(name); meshes.append(name); role = 'primary-mesh'
        elif name.startswith(('highpoly/', 'cage/')):
            directory, leaf = name.split('/', 1); _mesh_name(leaf)
            require(member, 'embedded mesh is empty')
            meshes.append(name); role = 'high-poly-mesh' if directory == 'highpoly' else 'cage-mesh'
            if directory == 'cage':
                cages.append(name)
        else:
            raise ValueError('Texture archive member is not qualified for lossless native import: ' + name)
        inventory[name] = {'role': role, 'bytes': len(member), 'sha256': hashlib.sha256(member).hexdigest()}
    require(len(primary) <= 1 and len(cages) <= 1, 'multiple primary meshes or cages would be overwritten by the native reader')
    project = structure['project']; mesh = project.get('mesh')
    require(type(mesh) is str, 'project mesh reference must be a string')
    if mesh.startswith('builtin:'):
        require(mesh[len('builtin:'):] in BUILTINS and not primary, 'built-in mesh is unknown or conflicts with an embedded mesh')
    else:
        require(primary == [mesh] and members[mesh], 'project must reference exactly one nonempty embedded primary mesh')
    for field in ('mesh_file', 'mesh_path'):
        value = project.get(field, '')
        require(type(value) is str and len(value) <= 4096 and '\x00' not in value, 'mesh provenance metadata is malformed')
    image_texels = resources['texels'] + (thumbnail['width'] * thumbnail['height'] if thumbnail else 0)
    require(image_texels <= texture_images.MAX_TOTAL_TEXELS, 'images and thumbnail exceed the aggregate texel budget')
    mesh_reports = texture_mesh.inspect_members(members, meshes)
    if primary:
        material_count = len(mesh_reports['members'][primary[0]]['materials'])
        require(all(item['material'] < material_count for item in project['texture_sets']),
                'texture set references a material absent from the embedded mesh')
    # mesh_path is inert provenance in a byte-based native open. Never resolve it
    # or call the trusted-local remembered-path reimport command. External files
    # referenced INSIDE mesh bodies must pass the separate mesh admission gate.
    return {**snapshot, 'structure': structure, 'project_semantics': metadata, 'layer_semantics': layers, 'pixels': pixels, 'resources': resources,
            'inventory': inventory, 'mesh_members': meshes, 'thumbnail': thumbnail,
            'meshes': mesh_reports,
            'image_texels': image_texels,
            'engine_admission_complete': False}


def read_native(path):
    return inspect_bytes(texture_archive.read_bytes(path))


def check_preservation(before, after, *, expected_project=None):
    """Require complete inventory/payload preservation across a native save.

    A typed edit supplies its independently predicted project. Embedded changes
    require a separate explicit contract; they are never hidden by this check.
    This check does not establish mesh safety, codec agreement or visual quality.
    """
    require(set(before['members']) == set(after['members']), 'native save dropped or introduced archive members')
    project = before['structure']['project'] if expected_project is None else expected_project
    # Python equality treats True == 1 and 1 == 1.0. Compare canonical JSON so
    # type changes cannot masquerade as field preservation. Object order alone
    # is irrelevant; array order, signed zero and scalar types remain significant.
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    require(canonical(after['structure']['project']) == canonical(project), 'native save changed unapproved project fields')
    for name, value in before['members'].items():
        if name != 'project.json':
            require(after['members'][name] == value, 'native save changed unapproved embedded bytes: ' + name)
    return {'members': len(before['members']), 'project_fields_preserved': True, 'embedded_bytes_preserved': True}
