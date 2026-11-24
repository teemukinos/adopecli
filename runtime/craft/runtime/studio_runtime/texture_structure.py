"""Texture JSON structure and conservative allocation preflight.

This is not full document admission. Resources, native recovery/preservation and
operation-specific semantics must also pass before an engine opens the document.
All source fields are retained, including fields not interpreted at this stage.
"""
from . import animate_format, texture_archive

MAX_ITEMS = 100_000
MAX_SETS = 16
MAX_LAYERS = 4096
MAX_IDS = 8192
MAX_DEPTH = 16
MAX_ATLAS_SIDE = 8192
MAX_ATLAS_TEXELS = 16_777_216
MAX_COMPONENT_TEXELS = 268_435_456
MAX_RENDER_WORK = 1_073_741_824
MAX_EXPANDED_NODES = 65_536
MAX_ID = (1 << 64) - 1
CHANNELS = {name: (3 if name in ('BaseColor', 'Normal', 'Emissive', 'Specular', 'SheenColor', 'CoatNormal') else 1)
            for name in ('BaseColor', 'Metallic', 'Roughness', 'Normal', 'Height', 'Emissive', 'Opacity',
                         'AmbientOcclusion', 'SpecularLevel', 'Specular', 'Glossiness', 'CoatWeight',
                         'CoatRoughness', 'SheenWeight', 'SheenColor', 'SheenRoughness', 'AnisotropyLevel',
                         'AnisotropyAngle', 'ScatterWeight', 'Transmission', 'CoatNormal')}
CHANNEL_IDS = {name[0].lower() + name[1:]: components for name, components in CHANNELS.items()}
FORMATS = ('Srgb8', 'L8', 'Rgb8', 'L16', 'Rgb16', 'L16F', 'Rgb16F', 'L32F', 'Rgb32F')
BAKED = {name: (3 if name in ('Normal', 'WorldNormal', 'Id', 'Position', 'BentNormal') else 1)
         for name in ('Normal', 'WorldNormal', 'Id', 'AmbientOcclusion', 'Curvature', 'Position',
                      'Thickness', 'Height', 'BentNormal', 'Opacity')}
BAKED_IDS = {name[0].lower() + name[1:]: components for name, components in BAKED.items()}


def require(condition, message):
    if not condition:
        raise ValueError('Texture ' + message)


def integer(value, low=0, high=MAX_ID):
    return type(value) is int and low <= value <= high


def object_value(value, label):
    require(type(value) is dict, label + ' must be an object')
    return value


def list_value(value, maximum, label):
    require(type(value) is list and len(value) <= maximum, label + ' must be a bounded list')
    return value


def enum_value(value, choices, label):
    require(type(value) is str and value in choices, label + ' is unsupported')
    return value


def identifier(value):
    require(integer(value, 1, MAX_ID - 1), 'IDs must be nonzero unsigned integers with allocation headroom')
    return value


def resolution(value):
    require(integer(value, 128, 8192) and value & (value - 1) == 0, 'resolution must be a power of two from 128 to 8192')
    return value


def variant(value, strings, objects, label):
    if type(value) is str:
        return enum_value(value, strings, label), None
    require(type(value) is dict and len(value) == 1, label + ' must have exactly one variant')
    kind, body = next(iter(value.items()))
    enum_value(kind, objects, label)
    return kind, body


def inspect_json(data):
    require(isinstance(data, bytes) and len(data) <= texture_archive.MAX_JSON, 'project JSON exceeds its byte budget')
    # Reuse the already-qualified UTF-8, depth, item, duplicate-key and finite
    # numeric decoder. Its limits are independent of native serde recovery.
    try:
        project = animate_format.strict_json(data, max_items=MAX_ITEMS)
    except ValueError as error:
        raise ValueError(str(error).replace('Animate', 'Texture')) from error
    object_value(project, 'project')
    require(type(project.get('format_version')) is int and project['format_version'] == 2, 'native format version is not qualified')
    sets = list_value(project.get('texture_sets'), MAX_SETS, 'texture sets')
    require(bool(sets), 'project must contain at least one texture set')
    raw_layers = object_value(project.get('layers'), 'layers')
    require(len(raw_layers) <= MAX_LAYERS, 'layer count exceeds its budget')
    layers = {}; ids = {}; children = {}; edges = {}; node_weights = {}; anchors = set(); references = []
    resources = set(); image_references = set(); linked_packages = set()

    def allocate(value, owner, role):
        value = identifier(value)
        require(value not in ids, 'layer/effect ID is duplicated')
        require(len(ids) < MAX_IDS, 'layer/effect count exceeds its budget')
        ids[value] = {'layer': owner, 'role': role}
        return value

    def resource(value, *, image=True):
        require(type(value) is str and 1 <= len(value) <= 120 and not value.startswith('.')
                and all(c.isascii() and (c.isalnum() or c in '_.-') for c in value), 'resource reference is not a native resource name')
        resources.add(value)
        if image:
            image_references.add(value)

    def source(value):
        kind, body = variant(value, (), ('Uniform', 'Procedural', 'Image', 'Anchor'), 'fill source')
        if kind == 'Uniform':
            require(type(body) is list and len(body) == 3 and all(animate_format.number(x, -MAX_ID, MAX_ID) for x in body),
                    'uniform source must contain three finite numbers')
        else:
            object_value(body, 'fill source parameters')
            if kind == 'Image':
                resource(body.get('name'))
            elif kind == 'Anchor':
                references.append(identifier(body.get('anchor')))
                enum_value(body.get('channel'), CHANNELS, 'anchor channel')

    def fill(value):
        value = object_value(value, 'fill')
        sources = object_value(value.get('sources'), 'fill sources')
        for channel, item in sources.items():
            enum_value(channel, CHANNELS, 'fill channel'); source(item)
        link = value.get('link')
        if link is not None:
            object_value(link, 'linked material')
            resource(link.get('package'), image=False); linked_packages.add(link['package'])
            # This module records the dependency only. The maintained native
            # engine refuses recooking it through host executables.

    def effects(value, owner, role):
        result = list_value(value, MAX_IDS, role + ' effects')
        for effect in result:
            object_value(effect, 'effect')
            eid = allocate(effect.get('id'), owner, role)
            kind, body = variant(effect.get('kind'), ('Paint', 'Anchor'),
                                 ('Path', 'Fill', 'Generator', 'Levels', 'Filter', 'ColorSelection', 'Compare', 'Material'), 'effect kind')
            if kind == 'Anchor':
                anchors.add(eid)
            elif kind == 'Material':
                fill(body)
            elif kind == 'Fill':
                source(object_value(body, 'fill effect').get('source'))
            elif kind == 'Path':
                list_value(body, 4096, 'paint paths')
        return len(result)

    for key, layer in raw_layers.items():
        require(type(key) is str and key.isascii() and key.isdecimal() and len(key) <= 20 and str(int(key)) == key,
                'layer map keys must be canonical decimal IDs')
        lid = identifier(int(key)); object_value(layer, 'layer')
        require(type(layer.get('id')) is int and layer['id'] == lid, 'layer ID disagrees with its map key')
        allocate(lid, lid, 'layer'); layers[lid] = layer
    for lid, layer in layers.items():
        kind, body = variant(layer.get('kind'), ('Paint',), ('Fill', 'Group', 'Instance'), 'layer kind')
        children[lid] = []
        if kind == 'Group':
            body = object_value(body, 'group')
            children[lid] = [identifier(x) for x in list_value(body.get('children'), MAX_LAYERS, 'group children')]
        elif kind == 'Fill':
            fill(body)
        edges[lid] = list(children[lid])
        if kind == 'Instance':
            edges[lid].append(identifier(object_value(body, 'instance').get('source')))
        for channel in object_value(layer.get('channels'), 'layer channels'):
            enum_value(channel, CHANNELS, 'layer channel')
        weight = 1 + effects(layer.get('content_effects', []), lid, 'content')
        mask = layer.get('mask')
        if mask is not None:
            mask = object_value(mask, 'mask')
            weight += 1 + effects(mask.get('effects'), lid, 'mask')
        node_weights[lid] = weight
    require(all(target in layers for targets in edges.values() for target in targets), 'graph references a missing layer')
    require(all(anchor in anchors for anchor in references), 'fill references a missing anchor effect')
    next_id = project.get('next_id')
    require(integer(next_id, 1, MAX_ID - 1) and next_id > max(ids, default=0), 'next ID collides with existing IDs or cannot allocate')

    owners = {}; atlases = []; atlas_texels = component_texels = 0
    for index, texture_set in enumerate(sets):
        item = object_value(texture_set, 'texture set')
        size = resolution(item.get('resolution'))
        tiles = list_value(item.get('uv_tiles', []), 1000, 'UV tiles')
        require(all(integer(t, 1001, 2000) for t in tiles) and all(a < b for a, b in zip(tiles, tiles[1:])),
                'UV tiles must be unique, sorted UDIM numbers from 1001 to 2000')
        overrides = object_value(item.get('tile_resolutions', {}), 'tile resolutions')
        tile_keys = {str(tile) for tile in tiles}
        require(all(type(key) is str and key in tile_keys for key in overrides), 'resolution override references an absent tile')
        for value in overrides.values():
            resolution(value)
        block = max((overrides.get(str(tile), size) for tile in tiles), default=size)
        columns = [(t - 1001) % 10 for t in tiles]; rows = [(t - 1001) // 10 for t in tiles]
        width = block * (max(columns) - min(columns) + 1 if tiles else 1)
        height = block * (max(rows) - min(rows) + 1 if tiles else 1)
        require(width <= MAX_ATLAS_SIDE and height <= MAX_ATLAS_SIDE, 'atlas side exceeds its budget')
        atlas_texels += width * height
        require(atlas_texels <= MAX_ATLAS_TEXELS, 'total atlas area exceeds its budget')
        channels = list_value(item.get('channels'), len(CHANNELS), 'set channels')
        seen = set(); components = 0
        for pair in channels:
            require(type(pair) is list and len(pair) == 2, 'set channel must contain a channel and format')
            channel = enum_value(pair[0], CHANNELS, 'set channel'); enum_value(pair[1], FORMATS, 'channel format')
            require(channel not in seen, 'set channel is duplicated'); seen.add(channel)
            components += CHANNELS[channel] + 1
        require(bool(seen), 'texture set has no channels')
        component_texels += width * height * components
        require(component_texels <= MAX_COMPONENT_TEXELS, 'composite allocation exceeds its component budget')
        baked = list_value(item.get('baked', []), len(BAKED), 'baked maps')
        for value in baked:
            enum_value(value, BAKED, 'baked map')
        require(len(baked) == len(set(baked)), 'baked map is duplicated')
        excluded = list_value(item.get('bake_excluded_tiles', []), 1000, 'excluded bake tiles')
        require(all(integer(t, 1001, 2000) and t in tiles for t in excluded) and len(excluded) == len(set(excluded)),
                'excluded bake tiles must name distinct existing UV tiles')
        stack = [identifier(x) for x in list_value(item.get('stack'), MAX_LAYERS, 'layer stack')]
        pending = [(lid, 0) for lid in stack]
        while pending:
            lid, depth = pending.pop()
            require(depth <= MAX_DEPTH and lid in layers and lid not in owners, 'layer ownership is missing, cyclic, duplicated or too deep')
            owners[lid] = index
            pending.extend((child, depth + 1) for child in children[lid])
        atlases.append({'width': width, 'height': height, 'block': block, 'components': components, 'roots': stack})
    require(len(owners) == len(layers), 'orphan layers are not qualified')
    # Memoized DAG expansion counts repeated instances without expanding them.
    # Count depth through group AND instance edges, including cached subgraphs.
    active = set(); costs = {}; heights = {}
    def cost(lid):
        if lid in costs:
            return costs[lid], heights[lid]
        require(lid not in active and len(active) <= MAX_DEPTH, 'render graph is cyclic or too deep')
        active.add(lid); weight = node_weights[lid]; height = 0
        for target in edges[lid]:
            child_cost, child_height = cost(target)
            weight += child_cost; height = max(height, child_height + 1)
            require(weight <= MAX_EXPANDED_NODES and height <= MAX_DEPTH, 'instance expansion exceeds its budget')
        active.remove(lid); costs[lid] = weight; heights[lid] = height
        return weight, height
    for lid in layers:
        cost(lid)
    work = 0
    for atlas in atlases:
        expanded = sum(costs[lid] for lid in atlas['roots'])
        require(expanded <= MAX_EXPANDED_NODES, 'set expansion exceeds its budget')
        work += atlas['width'] * atlas['height'] * atlas['components'] * max(1, expanded)
        require(work <= MAX_RENDER_WORK, 'expanded render work exceeds its budget')
        atlas['expanded_nodes'] = expanded
    for entry in ids.values():
        entry['texture_set'] = owners[entry['layer']]
    display = object_value(project.get('display'), 'display')
    environment = display.get('environment')
    if type(environment) is str and environment.startswith('resource:'):
        resource(environment[len('resource:'):])
    return {'project': project, 'layers': layers, 'ids': ids, 'atlases': atlases,
            'resource_references': sorted(resources), 'image_references': sorted(image_references), 'linked_packages': sorted(linked_packages),
            'budgets': {'atlas_texels': atlas_texels, 'component_texels': component_texels, 'render_work': work}}
