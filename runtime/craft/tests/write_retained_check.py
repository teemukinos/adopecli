#!/usr/bin/env python3
"""Verify retained font ownership against a pinned font and actual cold native use."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import write_container as container, write_resources as resources, write_retained as retained


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True); p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--font', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; calls = []; started = time.monotonic()
    source = args.fixtures/'brief.json'; original = source.read_bytes(); base = container.strict_json(original)
    font_bytes = args.font.read_bytes(); font_sha = hashlib.sha256(font_bytes).hexdigest()
    table_name = 'WORD/FONTTABLE.XML'; font_name = 'word/fonts/original.odttf'; alias = 'Dobe Original Embedded Fixture'
    guid = '{00112233-4455-6677-8899-AABBCCDDEEFF}'; key = bytes.fromhex('FFEEDDCCBBAA99887766554433221100')
    obfuscated = bytes(v ^ key[i % 16] for i, v in enumerate(font_bytes[:32]))+font_bytes[32:]
    office = retained.OFFICE[0]; word = retained.WORD[0]
    table = f'<x:fonts xmlns:x="{word}" xmlns:q="{office}"><x:font x:name="{alias}"><x:embedRegular q:id="rFont" x:fontKey="{guid}"/><x:embedBold q:id="rFont" x:fontKey="{guid}"/></x:font></x:fonts>'.encode()
    manifest = f'P\t{table_name}\tapplication/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml\nP\t{font_name}\tapplication/vnd.openxmlformats-officedocument.obfuscatedFont\nR\t{table_name}\trFont\t{office}/font\t{font_name}\tI\n'.encode()
    encode = lambda data: base64.b64encode(data).decode('ascii')
    document = copy.deepcopy(base); document['passthrough'] = {retained.MANIFEST: encode(manifest), table_name: encode(table), font_name: encode(obfuscated)}
    document['body'][2]['runs'][1]['props'].update(font=alias, bold=False, boldCs=False)

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments):
        result = subprocess.run([str(args.engine.resolve()), *map(str, arguments)], capture_output=True, timeout=90)
        index = len(calls); calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode})
        (out/f'{index:03}.stdout').write_bytes(result.stdout); (out/f'{index:03}.stderr').write_bytes(result.stderr)
        if result.returncode: raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def refused(label, change):
        doc = copy.deepcopy(document); change(doc); before = copy.deepcopy(doc)
        try: retained.inspect(doc)
        except ValueError as error: refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)
        check(doc == before, label+' refused without repairing source')

    def set_manifest(doc, data): doc['passthrough'][retained.MANIFEST] = encode(data)
    def set_table(doc, data): doc['passthrough'][table_name] = encode(data)
    def missing(path):
        output = call('run', '--file', path, '--cmd', 'font.missing={}', '--print').decode()
        return json.loads(output.removeprefix('font.missing: ').strip())['missing']

    try:
        check(retained.font_key(guid) == key, 'GUID byte order matches independently written reversed key')
        before = copy.deepcopy(document); report = retained.inspect(document)
        check(len(report['embedded_fonts']) == 1 and len(report['font_slots']) == 2, 'repeated native target/key/family loads one font but retains both slots')
        check(report['embedded_fonts'][0]['data'] == font_bytes and report['font_bytes'] == len(font_bytes), 'de-obfuscation restores every original pinned font byte')
        check(report['embedded_fonts'][0]['decoded_sha256'] == font_sha and document == before, 'extraction preserves source and records exact decoded hash')
        check('retained-package-and-embedded-fonts' in resources.inspect(document)['pending_qualification'], 'native control keys are recognized without granting font-loading permission')
        for key_name in ('wordcraft:unknown', 'wordcraft:vbaProject.related', 'word/vbaProject.bin'):
            refused('unqualified active or unknown retained key '+key_name, lambda d, k=key_name: d['passthrough'].update({k: encode(b'opaque')}))
        refused('missing retained font bytes', lambda d: d['passthrough'].pop(font_name))
        refused('font table without its manifest', lambda d: d['passthrough'].pop(retained.MANIFEST))
        refused('manifest duplicate part', lambda d: set_manifest(d, manifest+f'P\t{font_name}\tapplication/octet-stream\n'.encode()))
        refused('manifest unknown row', lambda d: set_manifest(d, manifest+b'Q\tunknown\n'))
        refused('manifest malformed row', lambda d: set_manifest(d, manifest+b'R\towner\n'))
        refused('manifest invalid UTF-8', lambda d: set_manifest(d, manifest+b'\xff'))
        refused('manifest ignored blank line', lambda d: set_manifest(d, manifest+b'\n'))
        refused('relationship before owner declaration', lambda d: set_manifest(d, manifest.splitlines(keepends=True)[-1]+b''.join(manifest.splitlines(keepends=True)[:-1])))
        refused('duplicate relationship ID', lambda d: set_manifest(d, manifest+manifest.splitlines(keepends=True)[-1]))
        refused('unknown relationship mode', lambda d: set_manifest(d, manifest.replace(b'\tI\n', b'\tX\n')))
        refused('external font relationship', lambda d: set_manifest(d, manifest.replace((font_name+'\tI').encode(), b'https://example.test/font.ttf\tE')))
        refused('font target traverses paths', lambda d: set_manifest(d, manifest.replace((font_name+'\tI').encode(), b'../outside.ttf\tI')))
        refused('relationship namespace prefix spoof', lambda d: set_manifest(d, manifest.replace((office+'/font').encode(), (office+'evil/font').encode())))
        refused('wrong font relationship kind', lambda d: set_manifest(d, manifest.replace(b'/font\t', b'/image\t')))
        refused('active retained content type', lambda d: set_manifest(d, manifest.replace(b'application/vnd.openxmlformats-officedocument.obfuscatedFont', b'application/vnd.ms-office.vbaProject')))
        refused('font reference missing ID', lambda d: set_table(d, table.replace(b'q:id="rFont"', b'q:id="missing"')))
        refused('font key malformed', lambda d: set_table(d, table.replace(guid.encode(), b'{not-a-guid}')))
        refused('font family would trim', lambda d: set_table(d, table.replace(alias.encode(), (' '+alias).encode())))
        refused('font family would truncate', lambda d: set_table(d, table.replace(alias.encode(), b'F'*129)))
        refused('font table wrong namespace', lambda d: set_table(d, table.replace(word.encode(), b'https://example.test/w')))
        refused('font table DTD', lambda d: set_table(d, b'<!DOCTYPE fonts [<!ENTITY external SYSTEM "file:///private">]>'+table))
        refused('conflicting family slot', lambda d: set_table(d, table.replace(b'embedBold', b'embedRegular').replace(b'<x:embedRegular q:id="rFont" x:fontKey="'+guid.encode()+b'"/></x:font>', b'<x:embedRegular q:id="rFont"/></x:font>')))
        plain = copy.deepcopy(document); plain['passthrough'][font_name] = encode(font_bytes)
        plain['passthrough'][table_name] = encode(table.replace(b' x:fontKey="'+guid.encode()+b'"', b''))
        check(retained.inspect(plain)['embedded_fonts'][0]['data'] == font_bytes, 'missing font key means exact unobfuscated source bytes')
        strict = copy.deepcopy(document); set_table(strict, table.replace(word.encode(), retained.WORD[1].encode()).replace(office.encode(), retained.OFFICE[1].encode()))
        check(retained.inspect(strict)['embedded_fonts'][0]['decoded_sha256'] == font_sha, 'strict OOXML namespaces retain the same owned font')
        controls = copy.deepcopy(document); controls['passthrough']['wordcraft:settings.orig'] = encode(b'<retained/>')
        check('retained-control-semantics' in retained.inspect(controls)['pending_qualification'], 'other recognized control records stay explicitly unqualified')

        embedded_path = out/'embedded.json'; embedded_path.write_text(json.dumps(document)+'\n')
        absent = copy.deepcopy(document); absent.pop('passthrough'); absent_path = out/'absent.json'; absent_path.write_text(json.dumps(absent)+'\n')
        check(any(f['font'] == alias for f in missing(absent_path)), 'fresh native process reports original alias missing without embedded bytes')
        check(not any(f['font'] == alias for f in missing(embedded_path)), 'fresh native process loads actual obfuscated font under document alias')
        check(json.loads(call('snapshot', embedded_path))['document'] == document, 'complete cold snapshot preserves font table manifest and obfuscated bytes exactly')
        call('render', embedded_path, out/'embedded.png', '--strict', '--scale', '1')
        docx = out/'embedded.docx'; call('convert', embedded_path, docx)
        reopened = json.loads(call('snapshot', docx))['document']; reopened_report = retained.inspect(reopened)
        check(any(f['family'] == alias and f['decoded_sha256'] == font_sha for f in reopened_report['embedded_fonts']),
              'native DOCX export and reopen retain exact de-obfuscated font identity')
        check(not any(f['font'] == alias for f in missing(docx)), 'fresh DOCX process uses the retained document font alias')
        check(args.font.read_bytes() == font_bytes and source.read_bytes() == original, 'pinned font and original document remain byte-identical')
        public = {**report, 'embedded_fonts': [{k: v for k, v in font.items() if k != 'data'} for font in report['embedded_fonts']]}
        (out/'retained.json').write_text(json.dumps(public, indent=2)+'\n')
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'native_calls': len(calls), 'seconds': time.monotonic()-started,
                    'font_source': str(args.font.resolve()), 'font_sha256': font_sha, 'engine_admission_complete': False, 'remote_actions': False,
                    'scope': 'retained relationships, exact de-obfuscation and controlled native alias use; arbitrary font files, rights and per-glyph identities remain unqualified'}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'passed': len(checks), 'refusals': len(refusals), 'native_calls': len(calls), 'evidence': str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise
    finally: (out/'calls.json').write_text(json.dumps(calls, indent=2)+'\n')


if __name__ == '__main__': main()
