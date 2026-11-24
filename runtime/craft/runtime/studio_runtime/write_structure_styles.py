"""Write style inheritance and list ownership; formatting values remain separate."""
from .write_container import require
from .write_structure import MAX_STYLES, graph_order, number, record, sequence, text, uint
from .write_page_properties import list_level, list_metadata, style_metadata


def inspect(document, style_refs, num_refs, props, property_validator):
    sheet = record(document['styles'], {'defaultChr', 'defaultPara', 'defaultParaPresent', 'styles'}, {'latentStyles'}, 'style sheet')
    require(type(sheet['defaultParaPresent']) is bool, 'default paragraph marker must be boolean')
    styles = {}
    for style in sequence(sheet['styles'], MAX_STYLES, 'styles'):
        record(style, {'id', 'name', 'kind', 'basedOn', 'next', 'linked', 'para', 'chr', 'priority', 'quick', 'hidden', 'builtin', 'table'},
               {'locked', 'default'}, 'style')
        key = text(style['id'], 'style identity', 512)
        require(key and key not in styles and style['kind'] in ('paragraph', 'character', 'table', 'numbering'),
                'style identity is duplicated or its kind is invalid')
        text(style['name'], 'style name', 4096)
        style_metadata(style)
        styles[key] = style
    edges = {}
    for key, style in styles.items():
        parent = style['basedOn']; following = style['next']; linked = style['linked']
        edges[key] = []
        if parent is not None:
            require(type(parent) is str and parent in styles and styles[parent]['kind'] == style['kind'], 'style parent is missing or has wrong kind')
            edges[key].append(parent)
        if following is not None:
            require(type(following) is str and following in styles and styles[following]['kind'] == 'paragraph', 'following paragraph style is missing or has wrong kind')
        if linked is not None:
            require(type(linked) is str and linked in styles and {style['kind'], styles[linked]['kind']} == {'paragraph', 'character'},
                    'linked style is missing or has incompatible kind')
        props(style['para'], 'paragraph'); props(style['chr'], 'character')
        if style['table'] is not None:
            property_validator.table_style(style['table'], props)
    depth = {}
    for key in graph_order(edges, 'style inheritance'):
        depth[key] = 1+max((depth[parent] for parent in edges[key]), default=0)
        require(depth[key] <= 64, 'style inheritance exceeds its depth budget')
    props(sheet['defaultChr'], 'character'); props(sheet['defaultPara'], 'paragraph')
    if sheet.get('latentStyles') is not None:
        text(sheet['latentStyles'], 'latent style XML', 1 << 20)
        property_validator.pending.add('latent-style-xml')

    numbering = record(document['numbering'], {'abstracts', 'nums'}, set(), 'numbering')
    abstracts = {}; nums = {}

    def level(value):
        record(value, {'start', 'format', 'text', 'align', 'indent', 'hanging', 'suffix', 'chr', 'restart', 'legal', 'style'},
               {'restartAfter', 'tab'}, 'list level')
        uint(value['start'], 2**32-1, 'list start'); text(value['text'], 'list label', 4096)
        number(value['indent'], -1584, 1584, 'list indent'); number(value['hanging'], -1584, 1584, 'list hanging indent')
        list_level(value)
        props(value['chr'], 'character')
        if value['style'] is not None: style_refs.append((value['style'], 'paragraph'))
        if value.get('restartAfter') is not None: uint(value['restartAfter'], 9, 'list restart level')

    for item in sequence(numbering['abstracts'], 4096, 'abstract lists'):
        record(item, {'id', 'name', 'levels'}, {'nsid', 'tmpl', 'multi_level_type'}, 'abstract list')
        list_metadata(item)
        key = uint(item['id'], 2**32-1, 'abstract list ID')
        require(key not in abstracts, 'abstract list ID is duplicated'); abstracts[key] = item
        for item_level in sequence(item['levels'], 9, 'list levels', 1): level(item_level)
    for item in sequence(numbering['nums'], 4096, 'lists'):
        record(item, {'id', 'abstractId', 'startOverrides'}, {'levelOverrides'}, 'list')
        key = uint(item['id'], 2**32-1, 'list ID')
        require(key > 0 and key not in nums, 'list ID is zero or duplicated')
        abstract_id = uint(item['abstractId'], 2**32-1, 'list definition reference')
        require(abstract_id in abstracts, 'list definition is missing')
        nums[key] = item
        for name, limit in (('startOverrides', 9), ('levelOverrides', 9)):
            seen = set()
            for pair in sequence(item.get(name, []), limit, name):
                sequence(pair, 2, 'list override pair', 2)
                index = uint(pair[0], 8, 'list override level')
                require(index not in seen, 'list override level is duplicated'); seen.add(index)
                if name == 'startOverrides': uint(pair[1], 2**32-1, 'list start override')
                else: level(pair[1])
    for identity, index in num_refs:
        if identity == 0: continue  # Native zero explicitly cancels inherited numbering.
        require(identity in nums, 'paragraph references a missing list')
        item = nums[identity]; overridden = {pair[0] for pair in item.get('levelOverrides', [])}
        require(index < len(abstracts[item['abstractId']]['levels']) or index in overridden, 'paragraph references a missing list level')
    for identity, kind in style_refs:
        require(type(identity) is str and identity in styles and styles[identity]['kind'] == kind,
                'formatting references a missing or incompatible style')
    return {'style_count': len(styles), 'abstract_list_count': len(abstracts), 'list_count': len(nums),
            'maximum_inheritance_depth': max(depth.values(), default=0)}
