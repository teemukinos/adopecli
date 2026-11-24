"""Resolve DOCX package ownership without extracting, opening links or rendering.

This is structural admission. XML document semantics, image/font decoders and
native round-trip fidelity still require their own checks before execution.
"""
import hashlib
import re
from urllib.parse import unquote_to_bytes, urlsplit

from . import write_container as container
from .write_container import require

TYPES = 'http://schemas.openxmlformats.org/package/2006/content-types'
RELS = 'http://schemas.openxmlformats.org/package/2006/relationships'
OFFICE = ('http://schemas.openxmlformats.org/officeDocument/2006/relationships',
          'http://purl.oclc.org/ooxml/officeDocument/relationships')
WORD = ('http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'http://purl.oclc.org/ooxml/wordprocessingml/main')
REL_MIME = 'application/vnd.openxmlformats-package.relationships+xml'
DOC_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
MAX_RELATIONSHIPS = 16_384
HYPERLINK_TYPES = frozenset(base+'/hyperlink' for base in OFFICE)
MAIN_TYPES = frozenset(base+'/officeDocument' for base in OFFICE)
ACTIVE_ELEMENTS = frozenset('{'+ns+'}'+tag for ns in WORD for tag in ('altChunk', 'object', 'control', 'subDoc'))
VML_RELATIONSHIP = '{urn:schemas-microsoft-com:office:office}relid'


def elements(root):
    return [child for child in root if isinstance(child.tag, str)]


def plain(root):
    """Manifest elements may contain comments and whitespace, never hidden text."""
    require(not (root.text or '').strip() and all(not (child.tail or '').strip() for child in root),
            'package manifest contains unexpected text')


def part_uri(target, source='', *, fragment=False):
    require(type(target) is str and 1 <= len(target.encode('utf-8')) <= 2048
            and '\\' not in target and not any(ord(c) < 32 or ord(c) == 127 for c in target),
            'package target is invalid')
    try:
        url = urlsplit(target)
    except ValueError as error:
        raise ValueError('Write package target is not a valid URI') from error
    require(not url.scheme and not url.netloc and not url.query and not target.startswith('//')
            and (fragment or not url.fragment), 'package target must be an owned part URI')
    path = url.path
    require(not re.search(r'%(?![0-9A-Fa-f]{2})', path) and not re.search(r'%(?:2f|5c|00)', path, re.I),
            'package target has ambiguous URI encoding')
    try:
        decoded = unquote_to_bytes(path).decode('utf-8')
    except UnicodeError as error:
        raise ValueError('Write package target has invalid UTF-8 encoding') from error
    require('\\' not in decoded and ':' not in decoded and '%' not in decoded
            and not any(ord(c) < 32 or ord(c) == 127 for c in decoded), 'package target has an unsafe decoded path')
    if not decoded:
        require(fragment and bool(url.fragment) and source, 'package target omits its part')
        return source, url.fragment
    stack = [] if decoded.startswith('/') else source.split('/')[:-1]
    pieces = decoded.lstrip('/').split('/')
    for piece in pieces:
        require(piece != '', 'package target has an empty path segment')
        if piece == '.':
            continue
        if piece == '..':
            require(stack, 'package target escapes its archive')
            stack.pop()
        else:
            stack.append(piece)
    require(stack, 'package target names the archive root')
    return '/'.join(stack), url.fragment


def external_hyperlink(target):
    require(type(target) is str and 1 <= len(target.encode('utf-8')) <= 2048
            and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in target)
            and '\\' not in target, 'external hyperlink URI is invalid')
    try:
        url = urlsplit(target)
        if url.scheme in ('http', 'https'):
            require(bool(url.hostname) and url.username is None and url.password is None,
                    'external hyperlink must name a host without credentials')
            _ = url.port  # Force malformed port validation without resolving anything.
        else:
            require(url.scheme == 'mailto' and bool(url.path) and not url.netloc,
                    'external relationship is not a passive web or mail hyperlink')
    except ValueError as error:
        raise ValueError('Write external hyperlink URI is invalid') from error
    return target


def relationship_source(name):
    if name == '_rels/.rels':
        return ''
    parent, separator, leaf = name.rpartition('/')
    require(separator and (parent == '_rels' or parent.endswith('/_rels'))
            and leaf.endswith('.rels') and len(leaf) > 5, 'relationship part has an invalid location')
    prefix = '' if parent == '_rels' else parent[:-6]+'/'
    return prefix+leaf[:-5]


def inspect(members):
    """Inspect a DOCX package using the shared bounded OPC graph reader."""
    return inspect_package(members, main_mime=DOC_MIME,
                           main_tags={'{'+ns+'}document' for ns in WORD},
                           label='DOCX', active_elements=ACTIVE_ELEMENTS)


def inspect_package(members, *, main_mime, main_tags, label, active_elements):
    """Internal reader shared by fixed Word and Slides format profiles.

    Callers provide code-owned format constants, never values from source data.
    This function neither extracts members nor resolves external resources.
    """
    require('[Content_Types].xml' in members and '_rels/.rels' in members,
            label+' requires its content types and package relationships')
    parsed = {}; xml_bytes = 0; xml_nodes = 0

    def xml(name):
        nonlocal xml_bytes, xml_nodes
        if name not in parsed:
            xml_bytes += len(members[name])
            require(xml_bytes <= container.MAX_XML, 'aggregate XML byte budget exceeded')
            item = container.parse_xml(members[name]); xml_nodes += item['nodes']
            require(xml_nodes <= container.MAX_NODES, 'aggregate XML node budget exceeded')
            parsed[name] = item
        return parsed[name]['root']

    root = xml('[Content_Types].xml')
    require(root.tag == '{'+TYPES+'}Types' and not root.attrib, 'content-types root is unsupported')
    plain(root); defaults = {}; overrides = {}
    for item in elements(root):
        plain(item); require(not elements(item), 'content-type declaration has child elements')
        if item.tag == '{'+TYPES+'}Default':
            require(set(item.attrib) == {'Extension', 'ContentType'}, 'default content type has unexpected fields')
            extension = item.get('Extension')
            require(bool(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', extension)), 'default content extension is invalid')
            key = extension.lower(); table = defaults
        else:
            require(item.tag == '{'+TYPES+'}Override' and set(item.attrib) == {'PartName', 'ContentType'},
                    'content-type declaration is unsupported')
            require(item.get('PartName').startswith('/'), 'content-type override must name an absolute package part')
            key, _ = part_uri(item.get('PartName'))
            require(key in members and key != '[Content_Types].xml', 'content-type override names a missing or reserved part')
            table = overrides
        require(key not in table, 'content-type declaration is duplicated')
        mime = item.get('ContentType')
        require(bool(re.fullmatch(r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+', mime)) and len(mime) <= 256,
                'content type is invalid')
        require(not any(word in mime.lower() for word in ('macroenabled', 'vbaproject', 'activex', 'oleobject')),
                'active Office content is not admitted')
        table[key] = mime
    types = {}
    for name in members:
        if name == '[Content_Types].xml':
            continue
        extension = name.rsplit('/', 1)[-1].rsplit('.', 1)[-1].lower()
        mime = overrides.get(name, defaults.get(extension))
        require(mime is not None, 'archive member has no declared content type: '+name)
        require(not any(part in name.casefold().split('/') for part in ('activex', 'embeddings'))
                and 'vbaproject' not in name.casefold(), 'embedded active Office content is not admitted')
        types[name] = mime
        if mime.lower().endswith('+xml') or mime.lower() in ('application/xml', 'text/xml') or extension in ('xml', 'rels'):
            xml(name)

    relationships = {}; external = []; count = 0; main_targets = []
    for name, mime in types.items():
        if not name.endswith('.rels') and mime != REL_MIME:
            continue
        require(name.endswith('.rels') and mime == REL_MIME, 'relationship part name and content type disagree')
        source = relationship_source(name)
        require(source == '' or source in members and source != '[Content_Types].xml' and not source.endswith('.rels'),
                'relationship part has no ordinary source member')
        require(source not in relationships, 'relationship source is duplicated')
        root = xml(name)
        require(root.tag == '{'+RELS+'}Relationships' and not root.attrib, 'relationship root is unsupported')
        plain(root); found = {}
        for item in elements(root):
            count += 1; require(count <= MAX_RELATIONSHIPS, 'relationship count exceeds its budget')
            require(item.tag == '{'+RELS+'}Relationship' and {'Id', 'Type', 'Target'} <= set(item.attrib)
                    and set(item.attrib) <= {'Id', 'Type', 'Target', 'TargetMode'} and not elements(item),
                    'relationship declaration is unsupported')
            plain(item)
            identity = item.get('Id'); kind = item.get('Type'); target = item.get('Target')
            require(1 <= len(identity.encode('utf-8')) <= 256 and not any(c.isspace() or ord(c) < 32 for c in identity)
                    and identity not in found, 'relationship ID is invalid or duplicated')
            require(1 <= len(kind) <= 512 and kind.startswith(('http://', 'https://')) and not any(c.isspace() for c in kind),
                    'relationship type is invalid')
            require(kind.rsplit('/', 1)[-1].lower() not in ('vbaproject', 'activexcontrol', 'control', 'oleobject', 'afchunk', 'attachedtemplate'),
                    'active, alternative-format or template relationship is not admitted')
            mode = item.get('TargetMode', 'Internal')
            hyperlink = kind in HYPERLINK_TYPES
            if mode == 'External':
                require(hyperlink, 'external resources are not admitted')
                external_hyperlink(target)
                entry = {'type': kind, 'target': target, 'external': True}
                external.append({'source': source, 'id': identity, 'target': target})
            else:
                require(mode == 'Internal', 'relationship target mode is invalid')
                target_part, fragment = part_uri(target, source, fragment=hyperlink)
                require(target_part in types and not target_part.endswith('.rels'), 'relationship target is missing or reserved')
                entry = {'type': kind, 'target': target_part, 'fragment': fragment, 'external': False}
                if source == '' and kind in MAIN_TYPES:
                    main_targets.append(target_part)
            found[identity] = entry
        relationships[source] = found
    require(len(main_targets) == 1, 'package must have exactly one main Office document relationship')
    main = main_targets[0]
    require(types[main] == main_mime and [name for name, mime in types.items() if mime == main_mime] == [main],
            'package must contain exactly one non-macro '+label+' main document')
    require(xml(main).tag in main_tags, 'main part is not a '+label+' document')
    # References in every XML part, including otherwise unreferenced content,
    # must bind to that part's own relationship table.
    for name, item in parsed.items():
        for element in item['root'].iter():
            if not isinstance(element.tag, str):
                continue
            require(element.tag not in active_elements,
                    'active or alternative document content is not admitted')
            for attribute, identity in element.attrib.items():
                if attribute == VML_RELATIONSHIP:
                    require(identity in relationships.get(name, {}), 'VML relationship reference is missing')
                for namespace in OFFICE:
                    if attribute.startswith('{'+namespace+'}'):
                        require(attribute.rsplit('}', 1)[-1] in ('id', 'embed', 'link')
                                and identity in relationships.get(name, {}), 'XML relationship reference is missing or unsupported')
    return {'root': main, 'content_types': types, 'relationships': relationships,
            'external_hyperlinks': external, 'xml': parsed, 'xml_bytes': xml_bytes, 'xml_nodes': xml_nodes,
            'member_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in members.items()},
            'relationship_count': count, 'engine_admission_complete': False}
