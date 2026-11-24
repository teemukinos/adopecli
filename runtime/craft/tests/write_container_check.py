#!/usr/bin/env python3
"""Exercise immutable Write source ownership using real native fixtures and mutations."""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import time
import warnings
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_container as container, write_opc as opc


@contextmanager
def limit(module, name, value):
    original = getattr(module, name); setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; started = time.monotonic()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def refuse(label, callback):
        try: callback()
        except ValueError as error:
            refusals.append({'case': label, 'error': str(error)})
            checks.append(label+' refused')
        else: raise AssertionError('accepted '+label)

    def archive(items, *, compression=zipfile.ZIP_DEFLATED):
        stream = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(stream, 'w', compression=compression) as handle:
                for name, data in (items.items() if isinstance(items, dict) else items):
                    handle.writestr(name, data)
        return stream.getvalue()

    def inspect(data): return container.inspect_bytes(data, 'docx')

    try:
        source = (args.fixtures/'brief.docx').read_bytes()
        native = (args.fixtures/'brief.json').read_bytes()
        first = inspect(source); members = first['members']
        (out/'source.docx').write_bytes(source); (out/'source.json').write_bytes(native)
        check(first['source_bytes'] == source and first['source_sha256'] == hashlib.sha256(source).hexdigest(), 'exact original archive retained')
        with zipfile.ZipFile(io.BytesIO(source)) as handle:
            check(members == {name: handle.read(name) for name in handle.namelist()}, 'all decoded member bytes match independent ZIP reader')
        check(first['root'] == 'word/document.xml' and first['relationship_count'] == 12, 'native package has one owned main document and twelve resolved relationships')
        check(not first['engine_admission_complete'], 'structural admission never authorizes native execution')
        check(container.check_preservation(first, container.read_source(out/'source.docx', 'docx'))['source_bytes_equal'],
              'fresh disk source retains exact container and member inventory')
        check(container.inspect_bytes(native, 'json')['document'] == json.loads(native), 'complete native JSON inventoried without normalization')
        texts = ''.join(first['xml'][first['root']]['root'].itertext())
        check(all(text in texts for text in ('Ceramic production brief', 'Original', 'Native graph')), 'namespace-aware main XML retains body and table text')
        check(any(data == (args.fixtures/'original-tile.png').read_bytes() for name, data in members.items() if name.startswith('word/media/')),
              'owned image retains original bytes')
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            rebuilt = inspect(archive(members, compression=compression))
            check(rebuilt['members'] == members and rebuilt['relationships'] == first['relationships'], 'compression preserves exact members and ownership: '+str(compression))
            refuse('reserialized import '+str(compression), lambda: container.check_preservation(first, rebuilt))
        directory = zipfile.ZipInfo('word/'); directory.external_attr = (stat.S_IFDIR | 0o700) << 16 | 0x10
        check(inspect(archive([(directory, b''), *members.items()]))['directories'] == ['word/'], 'ordinary empty directory records retained')

        def mutated(name, payload, **extra):
            return archive({**members, name: payload, **extra})

        def xml_change(name, mutate):
            root = ET.fromstring(members[name]); mutate(root)
            return mutated(name, ET.tostring(root, encoding='utf-8', xml_declaration=True))

        relations = 'word/_rels/document.xml.rels'; types = '[Content_Types].xml'
        def relationship(**values): return ET.Element('{'+opc.RELS+'}Relationship', values)
        web = xml_change(relations, lambda root: root.append(relationship(Id='web', Type=opc.OFFICE[0]+'/hyperlink', Target='https://example.invalid/design#source', TargetMode='External')))
        observed = inspect(web)
        check(observed['external_hyperlinks'] == [{'source': 'word/document.xml', 'id': 'web', 'target': 'https://example.invalid/design#source'}],
              'passive hyperlink recorded as metadata without fetching')
        for target in ('file:///tmp/private', 'javascript:alert(1)', 'https://user:password@example.invalid', 'https://example.invalid:bad', 'https://example.invalid/\nsecret'):
            altered = xml_change(relations, lambda root: root.append(relationship(Id='web', Type=opc.OFFICE[0]+'/hyperlink', Target=target, TargetMode='External')))
            refuse('unsafe external hyperlink '+repr(target), lambda data=altered: inspect(data))
        for kind in ('image', 'styles', 'attachedTemplate', 'oleObject', 'aFChunk', 'control'):
            altered = xml_change(relations, lambda root: root.append(relationship(Id='extra', Type=opc.OFFICE[0]+'/'+kind, Target='https://example.invalid/payload', TargetMode='External')))
            refuse('external or active '+kind, lambda data=altered: inspect(data))
        for target in ('../../private.xml', '//host/private.xml', '/absent.xml', 'media%2fimage1.png', 'media%5cimage1.png', 'media/%00image.png', '%ZZ', '%252e%252e/secret.xml', 'styles.xml?query=1', 'styles.xml#fragment'):
            altered = xml_change(relations, lambda root: root.append(relationship(Id='extra', Type=opc.OFFICE[0]+'/styles', Target=target)))
            refuse('unsafe or missing part '+target, lambda data=altered: inspect(data))
        # OPC-relative parents are legal when the resulting member remains owned.
        relative = xml_change(relations, lambda root: root.append(relationship(Id='custom', Type=opc.OFFICE[0]+'/custom-properties', Target='../docProps/custom.xml')))
        check(inspect(relative)['relationships']['word/document.xml']['custom']['target'] == 'docProps/custom.xml', 'owned parent-relative target resolved without filesystem access')
        absolute = xml_change(relations, lambda root: root.append(relationship(Id='same', Type=opc.OFFICE[0]+'/styles', Target='/word/styles.xml')))
        check(inspect(absolute)['relationships']['word/document.xml']['same']['target'] == 'word/styles.xml', 'absolute package part remains archive-relative')
        refuse('duplicate relationship ID', lambda: inspect(xml_change(relations, lambda root: root.append(relationship(Id='rId1', Type=opc.OFFICE[0]+'/image', Target='media/image1.png')))))
        refuse('wrong relationship target mode', lambda: inspect(xml_change(relations, lambda root: root[0].set('TargetMode', 'external'))))
        refuse('missing relationship source', lambda: inspect(mutated('word/_rels/absent.xml.rels', members[relations])))
        refuse('relationship in wrong directory', lambda: inspect(mutated('word/bad.rels', members[relations])))
        refuse('missing image member', lambda: inspect(archive({name: value for name, value in members.items() if not name.startswith('word/media/')})))
        refuse('undeclared member', lambda: inspect(mutated('word/unqualified.blob', b'opaque')))
        refuse('duplicate main relationship', lambda: inspect(xml_change('_rels/.rels', lambda root: root.append(relationship(Id='extra', Type=opc.OFFICE[0]+'/officeDocument', Target='word/document.xml')))))
        refuse('duplicate content override', lambda: inspect(xml_change(types, lambda root: root.append(ET.fromstring(ET.tostring(next(child for child in root if child.get('PartName') == '/word/document.xml')))))))
        refuse('case-colliding default extension', lambda: inspect(xml_change(types, lambda root: root.append(ET.Element('{'+opc.TYPES+'}Default', Extension='XML', ContentType='application/xml')))))
        refuse('macro document type', lambda: inspect(xml_change(types, lambda root: next(child for child in root if child.get('PartName') == '/word/document.xml').set('ContentType', 'application/vnd.ms-word.document.macroEnabled.main+xml'))))
        refuse('macro payload even without relationship', lambda: inspect(mutated('word/vbaProject.xml', b'<payload/>')))
        refuse('embedded package even without relationship', lambda: inspect(mutated('word/embeddings/hidden.xml', b'<payload/>')))
        for tag in ('altChunk', 'object', 'control', 'subDoc'):
            altered = xml_change('word/document.xml', lambda root: root[0].append(ET.Element('{'+opc.WORD[0]+'}'+tag)))
            refuse('active XML '+tag, lambda data=altered: inspect(data))
        refuse('dangling XML relationship', lambda: inspect(xml_change('word/document.xml', lambda root: root[0].set('{'+opc.OFFICE[0]+'}id', 'not-owned'))))
        refuse('dangling VML relationship', lambda: inspect(xml_change('word/document.xml', lambda root: root[0].set(opc.VML_RELATIONSHIP, 'not-owned'))))
        refuse('spoofed manifest namespace', lambda: inspect(mutated(types, members[types].replace(opc.TYPES.encode(), b'https://example.invalid/types'))))
        refuse('spoofed main namespace', lambda: inspect(mutated('word/document.xml', members['word/document.xml'].replace(opc.WORD[0].encode(), b'https://example.invalid/word'))))
        # Unknown inert content remains exact but does not become engine-qualified.
        extra = inspect(mutated('customXml/original.xml', b'<original vendor="fixture">retained</original>'))
        check(extra['members']['customXml/original.xml'] == b'<original vendor="fixture">retained</original>' and not extra['engine_admission_complete'],
              'unknown inert XML inventoried without silent semantic admission')

        for raw in (b'<!DOCTYPE x [<!ENTITY a "expanded">]><x>&a;</x>', b'<!DOCTYPE x SYSTEM "file:///tmp/private"><x/>',
                    b'<?xml-stylesheet href="https://example.invalid/style"?><x/>', b'<x a="1" a="2"/>', b'<x/><x/>', b'<x>'):
            refuse('malformed or active XML '+raw[:35].decode(), lambda data=raw: container.parse_xml(data))
        for encoding in ('utf-8', 'utf-16', 'utf-16le', 'utf-16be'):
            raw=('<?xml version="1.0" encoding="'+encoding+'"?><x xmlns="urn:fixture" a="é">Hello &amp; 世界</x>').encode(encoding)
            tree = container.parse_xml(raw)['root']
            check(tree.tag == '{urn:fixture}x' and tree.text == 'Hello & 世界' and tree.get('a') == 'é', 'bounded XML encoding '+encoding)
        with limit(container, 'MAX_DEPTH', 4): refuse('XML depth budget', lambda: container.parse_xml(b'<x>'*5+b'</x>'*5))
        with limit(container, 'MAX_NODES', 4): refuse('XML node budget', lambda: container.parse_xml(b'<x><a/><b/><c/><d/></x>'))
        with limit(container, 'MAX_ATTRIBUTES', 1): refuse('XML attribute budget', lambda: container.parse_xml(b'<x a="1" b="2"/>'))
        with limit(container, 'MAX_NODES', max(item['nodes'] for item in first['xml'].values())+1): refuse('aggregate XML nodes', lambda: inspect(source))
        with limit(container, 'MAX_XML', max(len(members[name]) for name in first['xml'])+1): refuse('aggregate XML bytes', lambda: inspect(source))
        with limit(opc, 'MAX_RELATIONSHIPS', 11): refuse('aggregate relationships', lambda: inspect(source))
        with limit(container, 'MAX_EXPANDED', 100): refuse('expanded archive budget', lambda: inspect(source))
        with limit(container, 'MAX_MEMBER', 100): refuse('individual archive member budget', lambda: inspect(source))

        for name in ('../escape.xml', '/absolute.xml', 'word\\escape.xml', 'word/../escape.xml', 'word//bad.xml', 'word/evil\x00.xml'):
            # ZipInfo itself truncates NUL names; mutate both original headers below instead.
            if '\x00' in name: continue
            refuse('unsafe archive name '+name, lambda key=name: inspect(archive([*members.items(), (key, b'<x/>')])) )
        refuse('duplicate archive member', lambda: inspect(archive([*members.items(), ('word/document.xml', members['word/document.xml'])])))
        refuse('case collision', lambda: inspect(mutated('WORD/document.xml', members['word/document.xml'])))
        refuse('Unicode normalization collision', lambda: inspect(archive([*members.items(), ('é.xml', b'<x/>'), ('e\u0301.xml', b'<x/>')])) )
        refuse('file and descendant conflict', lambda: inspect(mutated('word', b'not-a-directory')))
        link = zipfile.ZipInfo('word/link.xml'); link.external_attr = (stat.S_IFLNK | 0o777) << 16
        refuse('archive symlink', lambda: inspect(archive([*members.items(), (link, b'/tmp/private')])) )
        for label, data in [('truncated archive', source[:-1]), ('trailing archive bytes', source+b'junk'), ('prepended archive bytes', b'junk'+source)]:
            refuse(label, lambda value=data: inspect(value))
        crc = bytearray(source); crc[14] ^= 1
        refuse('local checksum differs', lambda: inspect(bytes(crc)))
        flags = bytearray(source); struct.pack_into('<H', flags, 6, struct.unpack_from('<H', flags, 6)[0] | 1)
        refuse('local encryption flag', lambda: inspect(bytes(flags)))

        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'{"x":1e39}',
                    b'{"x":18446744073709551616}', b'{"x":"\\ud800"}', b'[]', b'{"x":1}junk'):
            refuse('invalid native JSON '+raw.decode(), lambda data=raw: container.inspect_bytes(data, 'json'))
        raw = b'{"unknown":{"original":" retained ","id":18446744073709551615},"value":-0.0}'
        observed = container.inspect_bytes(raw, 'json')
        check(observed['source_bytes'] == raw and observed['document']['unknown']['id'] == 18446744073709551615
              and not observed['engine_admission_complete'], 'unknown JSON content and large integer retained without semantic admission')
        check(container.check_preservation(observed, container.inspect_bytes(raw, 'json'))['source_bytes_equal'], 'exact native JSON preserved')
        refuse('reserialized native JSON import', lambda: container.check_preservation(observed, container.inspect_bytes(json.dumps(observed['document']).encode(), 'json')))
        with limit(container, 'MAX_JSON', 4): refuse('JSON byte budget', lambda: container.strict_json(b'{"x":1}'))
        refuse('JSON depth budget', lambda: container.strict_json(b'['*100+b'0'+b']'*100))
        refuse('undeclared format sniffing', lambda: container.inspect_bytes(native, 'docx'))
        refuse('unsupported format', lambda: container.inspect_bytes(source, 'odt'))
        check(container.read_bytes(out/'source.docx') == source, 'regular-file snapshot preserves exact source')
        symlink = out/'link.docx'; symlink.symlink_to(out/'source.docx')
        refuse('final input symlink', lambda: container.read_bytes(symlink))
        fifo = out/'pipe.docx'; os.mkfifo(fifo)
        refuse('nonblocking FIFO input', lambda: container.read_bytes(fifo))
        refuse('directory input', lambda: container.read_bytes(out))
        check((out/'source.docx').read_bytes() == source and (out/'source.json').read_bytes() == native,
              'all inspections leave original evidence byte-identical')
        report = {'passed': True, 'checks': checks, 'refusals': refusals, 'seconds': time.monotonic()-started,
                  'source_sha256': first['source_sha256'], 'members': len(members), 'xml_nodes': first['xml_nodes'],
                  'scope': 'structural source inventory and OPC ownership only; no semantic/native/runtime/installed qualification',
                  'native_processes': 0, 'remote_actions': False}
        (out/'evidence.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n')
        raise


if __name__ == '__main__': main()
