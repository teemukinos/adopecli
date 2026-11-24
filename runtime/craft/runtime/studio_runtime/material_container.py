"""Bounded, lossless SBS/MCraft snapshots before semantic or native admission.

No extraction, filesystem dependency resolution or native process occurs here.
Unknown XML/member content remains inventoried, not silently accepted for execution.
The shared ZIP primitives retain the already-qualified Texture header checks.
"""
import base64
import binascii
import hashlib
import os
from pathlib import Path
import stat
import struct
from xml.parsers import expat
import zipfile
import zlib

from . import texture_archive as zip_container

MAX_SOURCE = 256 << 20
MAX_XML = 32 << 20
MAX_XML_NODES = 250_000
MAX_XML_DEPTH = 64
MAX_ATTRIBUTES = 128
MAX_EMBEDDED = 64 << 20
MAX_EMBEDDED_TOTAL = 128 << 20


def require(condition, message):
    if not condition: raise ValueError('Material '+message)


def read_bytes(path):
    """Caller must own ancestors; the final file cannot be a link or device."""
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode) and 1 <= metadata.st_size <= MAX_SOURCE, 'source must be a bounded regular file')
            data = stream.read(MAX_SOURCE+1)
            require(len(data) == metadata.st_size, 'source changed size during its snapshot')
            return data
    except OSError as error:
        raise ValueError('Material source cannot be read') from error


def _name(info):
    raw = info.filename; directory = raw.endswith('/'); name = raw[:-1] if directory else raw
    require(name and raw == info.orig_filename and len(raw.encode('utf-8')) <= 512
            and not name.startswith('/') and '\\' not in name and ':' not in name
            and not any(ord(c)<32 or ord(c)==127 or 0xd800<=ord(c)<=0xdfff for c in name)
            and all(part not in ('','.','..') for part in name.split('/')), 'archive entry name is unsafe or ambiguous')
    mode = stat.S_IFMT(info.external_attr >> 16)
    require(mode in (0, stat.S_IFDIR if directory else stat.S_IFREG), 'archive entry is not an ordinary file or directory')
    require(not info.external_attr & 0x10 or directory, 'archive directory attributes disagree with its name')
    require(not directory or info.file_size == 0, 'archive directory contains hidden payload')
    return name, directory


def archive_members(data):
    """Decode every member after checking all allocations, headers and intervals."""
    require(type(data) is bytes and 22 <= len(data) <= MAX_SOURCE, 'archive byte budget exceeded')
    try:
        directory, count, end = zip_container._directory(data)
        entries = zip_container._entries(data, directory, count, end)
        names = {}; records = []; expanded = 0
        for info in entries:
            name, is_directory = _name(info); key = name.casefold()
            require(key not in names, 'archive has a duplicate or case-colliding entry')
            names[key] = is_directory
            limit = MAX_XML if name.lower().endswith('.sbs') else zip_container.MAX_ENTRY
            require(0 <= info.file_size <= limit and 0 <= info.compress_size <= MAX_SOURCE
                    and not info.volume and not info.flag_bits & 1, 'archive member exceeds its budget or uses unsupported flags')
            expanded += info.file_size
            require(expanded <= zip_container.MAX_EXPANDED, 'archive expansion exceeds its aggregate budget')
            start, stop, finish = zip_container._payload(data, info, directory)
            records.append((info, name, is_directory, start, stop, finish))
        for name in names:
            parts = name.split('/')
            require(all(names.get('/'.join(parts[:i]), True) for i in range(1,len(parts))), 'archive file conflicts with a descendant path')
        previous = 0
        for info, name, is_directory, start, stop, finish in sorted(records, key=lambda row: row[0].header_offset):
            require(info.header_offset == previous, 'archive payload intervals overlap or leave unaccounted bytes')
            previous = finish
        require(previous == directory, 'archive payload does not end at its directory')
        members = {}; directories = []
        for info, name, is_directory, start, stop, finish in records:
            payload = data[start:stop]
            if info.compress_type == zipfile.ZIP_DEFLATED:
                decoder = zlib.decompressobj(-15); payload = decoder.decompress(payload, info.file_size+1)
                require(decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data, 'archive compression is truncated or has trailing data')
            require(len(payload) == info.file_size and zlib.crc32(payload) == info.CRC, 'archive payload size or checksum differs')
            if is_directory: directories.append(name+'/')
            else: members[name] = payload
        return members, directories, expanded
    except (ValueError, OSError, RuntimeError, UnicodeError, struct.error, zlib.error, zipfile.BadZipFile) as error:
        raise ValueError('Material archive admission failed: '+str(error)) from error


def parse_xml(data):
    """Preserve ordered XML content while bounding parser callbacks before trees grow."""
    require(type(data) is bytes and 1 <= len(data) <= MAX_XML, 'SBS XML byte budget exceeded')
    try: text = data.decode('utf-8')
    except UnicodeError as error: raise ValueError('Material SBS must use UTF-8') from error
    parser = expat.ParserCreate(); parser.buffer_text = True
    stack = []; document = []; count = 0; characters = 0; roots = []; elements = []; spans = []; positions = []

    def reserve():
        nonlocal count
        count += 1; require(count <= MAX_XML_NODES, 'XML node budget exceeded')
    def name(value):
        require(':' not in value and len(value.encode('utf-8')) <= 256, 'XML namespaces or oversized names are unqualified')
    def append(item):
        reserve(); (stack[-1]['content'] if stack else document).append(item)
    def start(tag, attributes):
        name(tag); require(len(stack) < MAX_XML_DEPTH, 'XML nesting budget exceeded')
        require(len(attributes) <= MAX_ATTRIBUTES, 'XML attribute count exceeds its budget')
        for key in attributes:
            name(key); require(key != 'xmlns', 'XML namespaces are unqualified')
        item = {'tag':tag,'attributes':attributes,'content':[]}
        append(item); elements.append(item)
        # Expat reports UTF-8 byte positions even when fed decoded Unicode.
        # Keep spans separately so source edits never need to normalize XML.
        begin = parser.CurrentByteIndex; cursor = begin; quote = None
        while cursor < len(data):
            byte = data[cursor]; cursor += 1
            if quote is not None:
                if byte == quote: quote = None
            elif byte in (34,39): quote = byte
            elif byte == 62: break
        require(cursor <= len(data) and data[cursor-1:cursor] == b'>', 'XML opening span is incomplete')
        positions.append((len(spans),data[begin:cursor].rstrip().endswith(b'/>'),cursor))
        spans.append([begin,None])
        if not stack: roots.append(item)
        stack.append(item)
    def end(tag):
        require(stack and stack[-1]['tag'] == tag, 'XML closing element disagrees');stack.pop()
        index,closed,opening_end = positions.pop()
        finish = opening_end if closed else data.find(b'>',parser.CurrentByteIndex)+1
        require(spans[index][0]<finish<=len(data), 'XML closing span is incomplete')
        spans[index][1] = finish
    def content(value):
        nonlocal characters
        characters += len(value.encode('utf-8')); require(characters <= MAX_XML, 'XML expanded text budget exceeded')
        target=stack[-1]['content'] if stack else document
        if target and '_text_parts' in target[-1]:target[-1]['_text_parts'].append(value)
        else:append({'_text_parts':[value]})
    def declaration(version, encoding, standalone):
        require(version == '1.0' and (encoding is None or encoding.lower() in ('utf-8','utf8')), 'XML declaration is unsupported')
    def forbidden(*args): raise ValueError('Material XML DTDs and external entities are forbidden')
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.CharacterDataHandler=content
    parser.CommentHandler=lambda value:append({'comment':value})
    parser.ProcessingInstructionHandler=lambda target,value:append({'instruction':target,'data':value})
    parser.XmlDeclHandler=declaration;parser.StartDoctypeDeclHandler=forbidden
    parser.EntityDeclHandler=forbidden;parser.ExternalEntityRefHandler=forbidden
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:parser.Parse(text,True)
    except expat.ExpatError as error:raise ValueError('Material SBS XML is malformed: '+str(error)) from error
    require(len(roots) == 1 and roots[0]['tag'] == 'package', 'SBS root must be one package')
    pending=[document]
    while pending:
        for item in pending.pop():
            if '_text_parts' in item:item['text']=''.join(item.pop('_text_parts'))
            if 'content' in item:pending.append(item['content'])
    return {'document':document,'root':roots[0],'elements':elements,'spans':spans,'nodes':count,'text_bytes':characters}


def embedded_bytes(value):
    """Decode SBS's big-endian length plus one zlib stream, with no recovery."""
    require(type(value) is str and len(value) <= MAX_XML, 'embedded resource encoding exceeds its budget')
    # The native decoder permits whitespace, but no alternate base64 alphabet.
    encoded=''.join(value.split())
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error) as error:raise ValueError('Material embedded resource has invalid base64') from error
    require(base64.b64encode(raw).decode('ascii') == encoded, 'embedded resource base64 is not canonical')
    require(len(raw) >= 4, 'embedded resource length is missing')
    size=int.from_bytes(raw[:4],'big');require(size <= MAX_EMBEDDED, 'embedded resource expansion exceeds its budget')
    try:
        decoder=zlib.decompressobj();decoded=decoder.decompress(raw[4:],size+1)
    except zlib.error as error:raise ValueError('Material embedded resource compression is invalid') from error
    require(len(decoded)==size and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
            'embedded resource length or compression stream disagrees')
    return decoded


def inspect_bytes(data):
    """Inventory a byte snapshot only; this never authorizes native execution."""
    require(type(data) is bytes and 1 <= len(data) <= MAX_SOURCE, 'source byte budget exceeded')
    archive=data.startswith((b'PK\x03\x04',b'PK\x05\x06'))
    if archive:
        members,directories,expanded=archive_members(data)
        roots=[name for name in members if '/' not in name and name.lower().endswith('.sbs')]
        require(len(roots)==1, 'archive must have exactly one root SBS document')
        root=roots[0]
    else:members={'source.sbs':data};directories=[];expanded=len(data);root='source.sbs'
    xml={};embedded={};total_xml=0;total_nodes=0;total_embedded=0
    for name,payload in members.items():
        if not name.lower().endswith('.sbs'):continue
        total_xml+=len(payload);require(total_xml<=MAX_XML,'aggregate SBS XML byte budget exceeded')
        parsed=parse_xml(payload);total_nodes+=parsed['nodes'];require(total_nodes<=MAX_XML_NODES,'aggregate XML node budget exceeded')
        xml[name]=parsed
        for index,item in enumerate(parsed['elements']):
            if item['tag']=='strdata':
                require(set(item['attributes'])=={'v'} and not item['content'], 'embedded resource declaration is ambiguous')
                decoded=embedded_bytes(item['attributes']['v']);total_embedded+=len(decoded)
                require(total_embedded<=MAX_EMBEDDED_TOTAL,'aggregate embedded resource expansion exceeds its budget')
                embedded[name+':'+str(index)]=decoded
        element_indices={id(item):index for index,item in enumerate(parsed['elements'])}
        # Native decoding trusts the compressed prefix and ignores datalength.
        # Reject contradictory redundant metadata instead of normalizing it.
        for item in parsed['elements']:
            if item['tag'] != 'binembedded': continue
            lengths=[child for child in item['content'] if child.get('tag')=='datalength']
            encoded=[child for child in item['content'] if child.get('tag')=='strdata']
            require(len(lengths)<=1 and len(encoded)==1, 'embedded resource has duplicated or missing declarations')
            if lengths:
                declared=lengths[0]
                value=declared['attributes'].get('v','')
                require(set(declared['attributes'])=={'v'} and not declared['content']
                        and value.isascii() and value.isdecimal() and len(value)<=10,
                        'embedded resource datalength is invalid')
                # Look up the already decoded payload; never inflate it twice.
                index=element_indices[id(encoded[0])]
                require(int(value)==len(embedded[name+':'+str(index)]), 'embedded resource datalength contradicts its payload')
    return {'source_bytes':data,'source_sha256':hashlib.sha256(data).hexdigest(),'format':'mcraft' if archive else 'sbs',
            'root':root,'members':members,'directories':directories,'expanded_bytes':expanded,'xml':xml,
            'xml_bytes':total_xml,'xml_nodes':total_nodes,'embedded':embedded,'embedded_bytes':total_embedded,
            'engine_admission_complete':False}


def read_native(path):return inspect_bytes(read_bytes(path))


def check_preservation(before, after):
    """Require exact decoded members for unchanged native save/reopen operations.

    ZIP compression and timestamps may differ. Document conversions and edits need
    their own explicit predicted-member contract; this check never repairs them.
    """
    require(before['format']==after['format'], 'native save changed the container format')
    require(set(before['directories'])==set(after['directories']), 'native save changed directory inventory')
    require(set(before['members'])==set(after['members']), 'native save dropped or introduced archive members')
    for name,payload in before['members'].items():
        require(after['members'][name]==payload, 'native save changed original member bytes: '+name)
    return {'member_bytes_equal':True,'directory_inventory_equal':True,'engine_admission_complete':False}
