"""Own PPTX packages and ordered slide relationships without native execution.

All original members, XML and unsupported semantics remain available for later
qualification. This inspector does not import a native model, fetch relationships,
rewrite XML, grant execution admission or establish presentation fidelity.
"""
import re

from . import write_container as container, write_opc as opc
from .slides_source import require, sha

PRESENTATION = ('http://schemas.openxmlformats.org/presentationml/2006/main',
                'http://purl.oclc.org/ooxml/presentationml/main')
DRAWING = ('http://schemas.openxmlformats.org/drawingml/2006/main',
           'http://purl.oclc.org/ooxml/drawingml/main')
MAIN_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'
PART_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.'
ACTIVE = opc.ACTIVE_ELEMENTS | frozenset('{'+ns+'}'+tag for ns in PRESENTATION
                                       for tag in ('oleObj', 'control', 'controls', 'contentPart'))
MAX_SLIDES = 256


def integer(value, low, high, label):
    require(type(value) is str and re.fullmatch(r'[0-9]{1,20}', value) is not None
            and low <= int(value) <= high, 'PPTX '+label+' is not a bounded unsigned integer')
    return int(value)


def owned_text(root):
    """Retain source text order and run boundaries without resolving styles."""
    result = []
    for element in root.iter():
        if element.tag in {'{'+ns+'}t' for ns in DRAWING}:
            require(not opc.elements(element), 'PPTX text run contains nested elements')
            result.append(element.text or '')
    return result


def inspect_bytes(data):
    members, directories, expanded = container.archive_members(data)
    graph = opc.inspect_package(members, main_mime=MAIN_MIME,
                                main_tags={'{'+ns+'}presentation' for ns in PRESENTATION},
                                label='PPTX', active_elements=ACTIVE)
    main = graph['root']; roots = {name: item['root'] for name, item in graph['xml'].items()}
    root = roots[main]; namespace = root.tag[1:].split('}', 1)[0]
    p = '{'+namespace+'}'; office = opc.OFFICE[PRESENTATION.index(namespace)]
    rid = '{'+office+'}id'

    def only(parent, tag, required=True):
        found = [node for node in opc.elements(parent) if node.tag == p+tag]
        require(len(found) == 1 if required else len(found) <= 1, 'PPTX '+tag+' owner is missing or ambiguous')
        return found[0] if found else None

    def relation(owner, identity, kind, root_tag, mime_suffix):
        require(type(identity) is str, 'PPTX relationship identity is missing')
        item = graph['relationships'].get(owner, {}).get(identity)
        require(item is not None and not item['external'] and not item.get('fragment')
                and item['type'] == office+'/'+kind, 'PPTX '+kind+' relationship differs from its owner')
        target = item['target']
        require(graph['content_types'][target] == PART_MIME+mime_suffix+'+xml'
                and target in roots and roots[target].tag == p+root_tag,
                'PPTX '+kind+' target has a different content type or XML root')
        return target

    def related(owner, kind):
        return [key for key, item in graph['relationships'].get(owner, {}).items()
                if item['type'] == office+'/'+kind]

    def single_relation(owner, kind, root_tag, mime_suffix):
        found = related(owner, kind)
        require(len(found) == 1, 'PPTX '+kind+' relationship is missing or ambiguous')
        return relation(owner, found[0], kind, root_tag, mime_suffix)

    masters = []; master_ids = set(); master_targets = set(); layouts = {}; layout_ids = set()
    master_list = only(root, 'sldMasterIdLst', False)
    master_entries = [] if master_list is None else opc.elements(master_list)
    require(len(master_entries) <= 256, 'PPTX master count exceeds ownership budget')
    for entry in master_entries:
        require(entry.tag == p+'sldMasterId' and not opc.elements(entry) and set(entry.attrib) == {'id', rid},
                'PPTX master list contains an unsupported declaration')
        identity = integer(entry.get('id'), 2**31, 2**32-1, 'master ID')
        require(identity not in master_ids, 'PPTX master ID is duplicated'); master_ids.add(identity)
        target = relation(main, entry.get(rid), 'slideMaster', 'sldMaster', 'slideMaster')
        require(target not in master_targets, 'PPTX master target has multiple ordered owners'); master_targets.add(target)
        owned_layouts = []; layout_list = only(roots[target], 'sldLayoutIdLst', False)
        for item in ([] if layout_list is None else opc.elements(layout_list)):
            require(item.tag == p+'sldLayoutId' and not opc.elements(item) and set(item.attrib) == {'id', rid},
                    'PPTX layout list contains an unsupported declaration')
            layout_id = integer(item.get('id'), 2**31, 2**32-1, 'layout ID')
            require(layout_id not in layout_ids, 'PPTX layout ID is duplicated'); layout_ids.add(layout_id)
            layout = relation(target, item.get(rid), 'slideLayout', 'sldLayout', 'slideLayout')
            require(layout not in layouts and len(layouts) < 4096, 'PPTX layout ownership is duplicated or exceeds budget')
            require(single_relation(layout, 'slideMaster', 'sldMaster', 'slideMaster') == target,
                    'PPTX layout backlink differs from its owning master')
            layouts[layout] = {'id': layout_id, 'master': target}; owned_layouts.append(layout)
        masters.append({'id': identity, 'part': target, 'layouts': owned_layouts})
    auxiliary = {}
    for list_name, item_name, kind, root_tag in (
            ('notesMasterIdLst', 'notesMasterId', 'notesMaster', 'notesMaster'),
            ('handoutMasterIdLst', 'handoutMasterId', 'handoutMaster', 'handoutMaster')):
        listing = only(root, list_name, False); entries = [] if listing is None else opc.elements(listing)
        require(len(entries) <= 1, 'PPTX '+kind+' has ambiguous presentation ownership')
        if entries:
            item = entries[0]
            require(item.tag == p+item_name and set(item.attrib) == {rid} and not opc.elements(item),
                    'PPTX '+kind+' declaration is unsupported')
            auxiliary[kind] = relation(main, item.get(rid), kind, root_tag, kind)

    dimensions = only(root, 'sldSz')
    size = {key: integer(dimensions.get(key), 1, 51_206_400, 'slide dimension') for key in ('cx', 'cy')}
    slide_list = only(root, 'sldIdLst', False)
    entries = [] if slide_list is None else opc.elements(slide_list)
    require(len(entries) <= MAX_SLIDES, 'PPTX slide count exceeds ownership budget')
    slides = []; slide_ids = set(); targets = set(); notes_targets = set()
    for index, entry in enumerate(entries):
        require(entry.tag == p+'sldId' and not opc.elements(entry)
                and set(entry.attrib) == {'id', rid}, 'PPTX slide list contains an unsupported declaration')
        identity = integer(entry.get('id'), 256, 2**31-1, 'slide ID')
        require(identity not in slide_ids, 'PPTX slide ID is duplicated'); slide_ids.add(identity)
        target = relation(main, entry.get(rid), 'slide', 'sld', 'slide')
        require(target not in targets, 'PPTX slide target has multiple ordered owners'); targets.add(target)
        layout = single_relation(target, 'slideLayout', 'sldLayout', 'slideLayout')
        require(layout in layouts, 'PPTX slide layout has no declared master owner')
        tree = only(only(roots[target], 'cSld'), 'spTree')
        shape_ids = set(); shape_inventory = []
        for node in tree.iter():
            if node.tag != p+'cNvPr': continue
            shape_id = integer(node.get('id'), 0, 2**32-1, 'shape ID')
            require(shape_id not in shape_ids, 'PPTX slide has duplicate shape IDs'); shape_ids.add(shape_id)
            shape_inventory.append({'id': shape_id, 'name': node.get('name'), 'description': node.get('descr')})
        notes = related(target, 'notesSlide')
        require(len(notes) <= 1, 'PPTX slide has ambiguous notes')
        notes_target = None; notes_text = []
        if notes:
            notes_target = relation(target, notes[0], 'notesSlide', 'notes', 'notesSlide')
            require(notes_target not in notes_targets, 'PPTX notes have multiple slide owners'); notes_targets.add(notes_target)
            require(single_relation(notes_target, 'slide', 'sld', 'slide') == target,
                    'PPTX notes refer to a different slide')
            require(single_relation(notes_target, 'notesMaster', 'notesMaster', 'notesMaster') == auxiliary.get('notesMaster'),
                    'PPTX notes master differs from presentation ownership')
            notes_text = owned_text(roots[notes_target])
        slides.append({'index': index+1, 'id': identity, 'relationship': entry.get(rid), 'part': target, 'layout': layout, 'master': layouts[layout]['master'],
                       'shape_identifiers': shape_inventory, 'text_runs': owned_text(tree),
                       'notes_part': notes_target, 'notes_text_runs': notes_text})
    # Reachability is evidence, not deletion: orphan parts can carry information
    # which a later native parser would discard. Preserve them and leave a gate.
    reachable = set(); pending = ['']
    while pending:
        owner = pending.pop()
        for item in graph['relationships'].get(owner, {}).values():
            if not item['external'] and item['target'] not in reachable:
                reachable.add(item['target']); pending.append(item['target'])
    ordinary = set(graph['content_types']) - {name for name in members if name.endswith('.rels')}
    unreferenced = sorted(ordinary-reachable)
    return {**graph, 'format': 'pptx', 'source_bytes': data, 'source_sha256': sha(data),
            'members': members, 'directories': directories, 'expanded_bytes': expanded,
            'presentation_namespace': namespace, 'slide_size_emu': size, 'slides': slides,
            'masters': masters, 'layouts': layouts, 'auxiliary_masters': auxiliary,
            'unreferenced_parts': unreferenced, 'engine_admission_complete': False,
            'native_model_reconstructed': False, 'source_format_fidelity_qualified': False,
            'pending_qualification': ['complete-presentation-semantics', 'masters-and-layout-inheritance',
                                     'resources-and-fonts', 'unsupported-and-opaque-content',
                                     'native-model-comparison', 'rendered-fidelity', 'external-hyperlink-policy']}
