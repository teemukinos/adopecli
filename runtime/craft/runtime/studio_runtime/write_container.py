"""Immutable, bounded Write source containers; never permission to run an engine.

JSON is inventoried without normalizing it. DOCX members are checked without
extraction using the shared strict ZIP header primitives. Semantic admission,
resource decoding and native preservation checks belong to subsequent layers.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import unicodedata
import xml.etree.ElementTree as ET
from xml.parsers import expat
import zipfile
import zlib

from . import animate_format, texture_archive

MAX_SOURCE = 128 << 20
MAX_EXPANDED = 256 << 20
MAX_MEMBER = 64 << 20
MAX_XML = 32 << 20
MAX_JSON = 32 << 20
MAX_NODES = 250_000
MAX_DEPTH = 64
MAX_ATTRIBUTES = 128


def require(condition, message):
    if not condition:
        raise ValueError('Write '+message)


def read_bytes(path):
    """The caller owns all ancestors. Refuse a final symlink or nonregular file."""
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode) and 1 <= metadata.st_size <= MAX_SOURCE,
                    'source must be a bounded regular file')
            data = stream.read(MAX_SOURCE+1)
            require(len(data) == metadata.st_size, 'source changed size during its snapshot')
            return data
    except OSError as error:
        raise ValueError('Write source cannot be read') from error


def strict_json(data):
    require(type(data) is bytes and 1 <= len(data) <= MAX_JSON, 'JSON exceeds its byte budget')
    try:
        animate_format._preflight(data, 2_000_000)
    except ValueError as error:
        raise ValueError(str(error).replace('Animate JSON', 'Write JSON')) from error

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'JSON contains a duplicate key')
            result[key] = value
        return result

    def integer(token):
        require(len(token.lstrip('-')) <= 20 and -2**63 <= int(token) < 2**64,
                'JSON integer exceeds its supported range')
        return int(token)

    def floating(token):
        value = float(token)
        require(math.isfinite(value) and abs(value) <= 3.4028234663852886e38,
                'JSON number exceeds finite binary32')
        return value

    def constant(_):
        raise ValueError('Write JSON contains a nonfinite number')

    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_int=integer,
                           parse_float=floating, parse_constant=constant)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Write JSON is malformed or nested too deeply') from error
    pending = [value]
    while pending:
        node = pending.pop()
        if type(node) is dict:
            pending.extend(node); pending.extend(node.values())
        elif type(node) is list:
            pending.extend(node)
        elif type(node) is str:
            require(not any(0xd800 <= ord(c) <= 0xdfff for c in node), 'JSON contains invalid Unicode')
    return value


def archive_members(data):
    require(type(data) is bytes and 22 <= len(data) <= MAX_SOURCE, 'archive exceeds its byte budget')
    try:
        directory, count, end = texture_archive._directory(data)
        entries = texture_archive._entries(data, directory, count, end)
        names = {}; records = []; expanded = 0
        for info in entries:
            raw = info.filename; is_directory = raw.endswith('/'); name = raw[:-1] if is_directory else raw
            require(name and raw == info.orig_filename and len(raw.encode('utf-8')) <= 512
                    and not name.startswith('/') and '\\' not in name and ':' not in name
                    and not any(ord(c) < 32 or ord(c) == 127 for c in name)
                    and all(part not in ('', '.', '..') for part in name.split('/')),
                    'archive entry name is unsafe or ambiguous')
            mode = stat.S_IFMT(info.external_attr >> 16)
            require(mode in (0, stat.S_IFDIR if is_directory else stat.S_IFREG)
                    and (not info.external_attr & 0x10 or is_directory)
                    and (not is_directory or info.file_size == 0), 'archive entry has unsupported file attributes')
            key = unicodedata.normalize('NFC', name).casefold()
            require(key not in names, 'archive has duplicate or normalized/case-colliding entries')
            names[key] = is_directory
            require(not info.volume and not info.flag_bits & 1 and 0 <= info.file_size <= MAX_MEMBER,
                    'archive member exceeds its budget or uses unsupported flags')
            expanded += info.file_size
            require(expanded <= MAX_EXPANDED, 'archive expansion exceeds its aggregate budget')
            start, stop, finish = texture_archive._payload(data, info, directory)
            records.append((info, name, is_directory, start, stop, finish))
        for name in names:
            parts = name.split('/')
            require(all(names.get('/'.join(parts[:i]), True) for i in range(1, len(parts))),
                    'archive file conflicts with a descendant path')
        previous = 0
        for info, name, is_directory, start, stop, finish in sorted(records, key=lambda row: row[0].header_offset):
            require(info.header_offset == previous, 'archive payload intervals overlap or leave unaccounted bytes')
            previous = finish
        require(previous == directory, 'archive payload does not end at its directory')
        members = {}; directories = []
        for info, name, is_directory, start, stop, finish in records:
            payload = data[start:stop]
            if info.compress_type == zipfile.ZIP_DEFLATED:
                decoder = zlib.decompressobj(-15)
                payload = decoder.decompress(payload, info.file_size+1)
                require(decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data,
                        'archive compression is truncated or has trailing data')
            require(len(payload) == info.file_size and zlib.crc32(payload) == info.CRC,
                    'archive member size or checksum differs')
            if is_directory:
                directories.append(name+'/')
            else:
                members[name] = payload
        return members, directories, expanded
    except (ValueError, UnicodeError, struct.error, zlib.error, zipfile.BadZipFile) as error:
        raise ValueError('Write archive admission failed: '+str(error).replace('Texture ', '')) from error


def parse_xml(data):
    """Build a namespace-aware tree with limits enforced before each allocation.

Original bytes stay authoritative; the tree is not used to rewrite source XML.
Both UTF-8 and UTF-16 Office XML are accepted. DTDs, entities and processing
instructions are not permitted to provide alternate or external content.
"""
    require(type(data) is bytes and 1 <= len(data) <= MAX_XML, 'XML exceeds its byte budget')
    parser = expat.ParserCreate(namespace_separator='}')
    parser.buffer_text = True
    builder = ET.TreeBuilder(insert_comments=True)
    stack = []; nodes = 0; text_bytes = 0; namespace_count = 0

    def reserve():
        nonlocal nodes
        nodes += 1
        require(nodes <= MAX_NODES, 'XML exceeds its node budget')

    def characters(value):
        nonlocal text_bytes
        text_bytes += len(value.encode('utf-8'))
        require(text_bytes <= MAX_XML, 'XML text exceeds its byte budget')

    def name(value):
        require(len(value.encode('utf-8')) <= 2048, 'XML name exceeds its byte budget')
        return '{'+value if '}' in value else value

    def start(tag, attributes):
        reserve(); require(len(stack) < MAX_DEPTH, 'XML exceeds its depth budget')
        require(len(attributes) <= MAX_ATTRIBUTES, 'XML element has too many attributes')
        for key, value in attributes.items():
            name(key); characters(value)
        tag = name(tag); stack.append(tag)
        builder.start(tag, {name(key): value for key, value in attributes.items()})

    def end(tag):
        require(stack and stack[-1] == name(tag), 'XML end tag differs')
        builder.end(stack.pop())

    def text(value):
        characters(value); builder.data(value)

    def comment(value):
        reserve(); characters(value); builder.comment(value)

    def namespace(prefix, uri):
        nonlocal namespace_count
        namespace_count += 1
        require(namespace_count <= MAX_NODES, 'XML namespace declarations exceed their budget')
        characters(uri or ''); name(prefix or '')

    def declaration(version, encoding, standalone):
        require(version == '1.0' and (encoding is None or encoding.lower() in ('utf-8', 'utf8', 'utf-16', 'utf-16le', 'utf-16be')),
                'XML declaration is unsupported')

    def forbidden(*arguments):
        raise ValueError('Write XML DTDs, entities and processing instructions are forbidden')

    parser.StartElementHandler = start; parser.EndElementHandler = end
    parser.CharacterDataHandler = text; parser.CommentHandler = comment
    parser.StartNamespaceDeclHandler = namespace; parser.XmlDeclHandler = declaration
    parser.StartDoctypeDeclHandler = forbidden; parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden; parser.ProcessingInstructionHandler = forbidden
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True); root = builder.close()
    except (expat.ExpatError, ET.ParseError) as error:
        raise ValueError('Write XML is malformed: '+str(error)) from error
    return {'root': root, 'nodes': nodes, 'text_bytes': text_bytes, 'namespace_declarations': namespace_count}


def inspect_bytes(data, kind):
    """Read a declared format without content sniffing or extension fallback."""
    require(type(data) is bytes and 1 <= len(data) <= MAX_SOURCE, 'source exceeds its byte budget')
    require(kind in ('json', 'docx'), 'source format requires an explicit qualified reader')
    result = {'format': kind, 'source_bytes': data, 'source_sha256': hashlib.sha256(data).hexdigest(),
              'engine_admission_complete': False}
    if kind == 'json':
        value = strict_json(data)
        require(type(value) is dict, 'native document JSON must be an object')
        result['document'] = value
    else:
        members, directories, expanded = archive_members(data)
        from .write_opc import inspect
        result.update(inspect(members))
        result.update({'members': members, 'directories': directories, 'expanded_bytes': expanded})
    return result


def read_source(path, kind):
    return inspect_bytes(read_bytes(path), kind)


def check_preservation(before, after):
    """Import and checkout retain source bytes, not merely equivalent ZIP members.

Edits and format exports need a separate predicted-change contract. This check
never repairs a document or silently accepts a reserialized source container.
"""
    require(before['format'] == after['format'], 'preservation changed the declared format')
    require(before['source_bytes'] == after['source_bytes'], 'preservation changed original source bytes')
    if before['format'] == 'docx':
        require(before['members'] == after['members'] and before['directories'] == after['directories'],
                'preservation changed the original member inventory')
    else:
        require(before['document'] == after['document'], 'preservation changed the original JSON inventory')
    return {'source_bytes_equal': True, 'engine_admission_complete': False}
