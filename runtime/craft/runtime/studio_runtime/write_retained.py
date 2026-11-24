"""Owned retained-package relationships and pre-load embedded-font extraction.

The native reader silently skips malformed manifests and font references. This
layer refuses those cases and checks exact de-obfuscated bytes with the bounded
TrueType profile, without loading fonts. Outline/program validation, native glyph
identity and full retained-content semantics remain prerequisites for execution.
"""
import hashlib
import re

from .write_container import MAX_NODES, MAX_XML, parse_xml, require
from .write_opc import external_hyperlink
from .write_resources import CONTROL_PARTS, decode_store
from .write_fonts import inspect as inspect_font

MANIFEST = 'wordcraft:embedded.parts'
FONT_TABLE = 'word/fonttable.xml'
WORD = ('http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'http://purl.oclc.org/ooxml/wordprocessingml/main')
OFFICE = ('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'http://purl.oclc.org/ooxml/officeDocument/relationships')
SLOTS = ('embedRegular', 'embedBold', 'embedItalic', 'embedBoldItalic')
MAX_FONT_BYTES = 64 << 20


def lines(data, label):
    require(len(data) <= 4 << 20, label+' exceeds its byte budget')
    try: value = data.decode('utf-8')
    except UnicodeError as error: raise ValueError('Write '+label+' is not UTF-8') from error
    require('\r' not in value and '\x00' not in value, label+' has noncanonical line endings or NUL')
    rows = value.split('\n')
    if rows[-1] == '': rows.pop()
    require(len(rows) <= 20_480, label+' exceeds its line budget')
    for row in rows:
        fields = row.split('\t')
        require(all(field and len(field.encode('utf-8')) <= 4096 and not any(ord(c) < 32 or ord(c) == 127 for c in field) for field in fields),
                label+' contains an empty or invalid field')
        yield fields


def manifest(data, members):
    parts = {}; relations = 0
    for fields in lines(data, 'retained manifest'):
        if fields[0] == 'P':
            require(len(fields) == 3, 'retained part declaration has wrong field count')
            _, name, mime = fields
            require(name in members and name not in CONTROL_PARTS and name not in parts and len(parts) < 4096,
                    'retained part is missing, reserved or duplicated')
            require(re.fullmatch(r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+', mime) is not None and len(mime) <= 256,
                    'retained content type is invalid')
            require(not any(x in mime.lower() for x in ('macroenabled', 'vbaproject', 'activex', 'oleobject')),
                    'retained active content is not admitted')
            parts[name] = {'content_type': mime, 'relationships': {}}
        else:
            require(fields[0] == 'R' and len(fields) == 6, 'retained manifest has an unknown or malformed row')
            _, owner, identity, kind, target, mode = fields
            require(owner in parts and identity not in parts[owner]['relationships'], 'retained relationship owner is missing or ID is duplicated')
            require(len(parts[owner]['relationships']) < 1024 and relations < 16_384, 'retained relationships exceed their budget')
            relations += 1
            require(any(kind.startswith(ns+'/') and re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', kind[len(ns)+1:]) for ns in OFFICE)
                    and mode in ('I', 'E'), 'retained relationship type or mode is invalid')
            require(kind.rsplit('/', 1)[-1] not in ('oleObject', 'control', 'aFChunk', 'attachedTemplate', 'vbaProject'),
                    'retained active relationship is not admitted')
            if mode == 'E':
                require(kind in tuple(ns+'/hyperlink' for ns in OFFICE), 'retained external resource is not admitted')
                external_hyperlink(target)
            else:
                require(target in members and target not in CONTROL_PARTS, 'retained relationship target is not an owned part')
            parts[owner]['relationships'][identity] = {'type': kind, 'target': target, 'external': mode == 'E'}
    return parts


def font_key(value):
    require(type(value) is str and re.fullmatch(r'(?:\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})', value),
            'embedded font key is not a GUID')
    return bytes.fromhex(value.strip('{}').replace('-', ''))[::-1]


def inspect(document):
    members = decode_store(document.get('passthrough', {}), 'retained package part', package=True)
    for name in members:
        require('vbaproject' not in name.casefold() and not any(p in ('activex', 'embeddings') for p in name.casefold().split('/')),
                'retained active package part is not admitted')
    parts = manifest(members[MANIFEST]['data'], members) if MANIFEST in members else {}
    parsed = {}; xml_bytes = 0; xml_nodes = 0; pending = set()
    for name, part in parts.items():
        if name.lower().endswith(('.xml', '.rels')) or part['content_type'].lower().endswith('+xml') or part['content_type'].lower() in ('application/xml', 'text/xml'):
            data = members[name]['data']; xml_bytes += len(data)
            require(xml_bytes <= MAX_XML, 'retained XML exceeds aggregate byte budget')
            item = parse_xml(data); xml_nodes += item['nodes']; require(xml_nodes <= MAX_NODES, 'retained XML exceeds aggregate node budget')
            parsed[name] = item['root']
    table_keys = [name for name in members if name.lower() == FONT_TABLE]
    fonts = []; seen = set(); bytes_total = 0; slots = []; slot_targets = {}
    for table_name in table_keys:
        require(table_name in parts and table_name in parsed, 'retained font table lacks a declared XML owner')
        root = parsed[table_name]
        require(root.tag in tuple('{'+ns+'}fonts' for ns in WORD), 'retained font table has the wrong namespace or root')
        ns = root.tag[1:].split('}', 1)[0]
        for font in root:
            if not isinstance(font.tag, str): continue
            if font.tag != '{'+ns+'}font':
                pending.add('font-table-extension-content'); continue
            family = font.get('{'+ns+'}name')
            require(type(family) is str and family == family.strip() and 0 < len(family) <= 128
                    and not any(ord(c) < 32 or ord(c) == 127 for c in family), 'embedded font family would be normalized or is invalid')
            for embed in font:
                if embed.tag not in tuple('{'+ns+'}'+slot for slot in SLOTS): continue
                ids = [embed.get('{'+uri+'}id') for uri in OFFICE if embed.get('{'+uri+'}id') is not None]
                require(len(ids) == 1 and ids[0] in parts[table_name]['relationships'], 'embedded font relationship is missing or ambiguous')
                relation = parts[table_name]['relationships'][ids[0]]
                require(not relation['external'] and relation['type'] in tuple(uri+'/font' for uri in OFFICE), 'embedded font relationship has wrong kind')
                target = relation['target']; key_text = embed.get('{'+ns+'}fontKey')
                key = font_key(key_text) if key_text is not None else bytes(16)
                slot = embed.tag.split('}', 1)[1]; slot_id = (family.casefold(), slot)
                require(slot_id not in slot_targets or slot_targets[slot_id] == (target, key), 'embedded font slot has conflicting targets')
                slot_targets[slot_id] = (target, key)
                require(len(slots) < 4096, 'embedded font references exceed their budget')
                slots.append({'family': family, 'slot': embed.tag.split('}', 1)[1], 'part': target, 'relationship': ids[0]})
                identity = (target, key, family)
                if identity in seen: continue
                seen.add(identity); source = members[target]['data']; bytes_total += len(source)
                require(len(fonts) < 64 and 0 < len(source) <= 32 << 20 and bytes_total <= MAX_FONT_BYTES,
                        'embedded font copies exceed their budget')
                prefix = bytes(value ^ key[i % 16] for i, value in enumerate(source[:32]))
                data = prefix+source[32:]
                font_report = inspect_font(data)
                fonts.append({'family': family, 'part': target, 'bytes': len(data), 'source_sha256': members[target]['sha256'],
                              'decoded_sha256': hashlib.sha256(data).hexdigest(), 'data': data, 'font_profile': font_report})
                pending.update(font_report['pending_qualification'])
    other_controls = sorted(set(members) & CONTROL_PARTS - {MANIFEST})
    if other_controls: pending.add('retained-control-semantics')
    if set(members)-set(parts)-CONTROL_PARTS: pending.add('undeclared-retained-parts')
    if parts: pending.add('retained-package-source-fidelity')
    return {'parts': parts, 'control_parts': other_controls, 'embedded_fonts': fonts, 'font_slots': slots,
            'font_bytes': bytes_total, 'xml_bytes': xml_bytes, 'xml_nodes': xml_nodes,
            'pending_qualification': sorted(pending), 'engine_admission_complete': False}
