#!/usr/bin/env python3
"""Check CAD source ownership, typed replay, portable archives and native cold reads.

This is local evidence for controlled private models. DXF baseline binding,
public admission, installed runtime and complete CAD fidelity remain separate.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'fixture', 'output'): parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import cad_source as source, cad_revision as revision, cad_project as project, cad_parametric
    checks = []; refusals = []; calls = 0; exe = args.engine.resolve(); fixture = args.fixture.resolve()
    lock_bytes = (Path(__file__).resolve().parents[1]/'engines/cad.lock.json').read_bytes(); lock = json.loads(lock_bytes)
    pin = {'product': 'dobe-cad', 'version': lock['engine_version'], 'source_revision': lock['source']['revision'], 'source_lock_sha256': source.sha(lock_bytes)}
    def check(label, value):
        if not value: raise AssertionError(label)
        checks.append(label)
    def refused(label, function):
        try: function()
        except ValueError as error: refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)
    def native(*arguments):
        nonlocal calls
        calls += 1
        result = subprocess.run([str(exe), *map(str, arguments)], capture_output=True, timeout=120,
                                env={'PATH': '/usr/bin:/bin', 'HOME': str(out)})
        (out/f'native-{calls}.stdout').write_bytes(result.stdout); (out/f'native-{calls}.stderr').write_bytes(result.stderr)
        if result.returncode: raise AssertionError(('native command failed', arguments, result.returncode, result.stderr.decode()))
    def cold(label, data):
        path = out/(label+'.json'); path.write_bytes(data); target = out/(label+'-cold.json')
        native('encode', path, target)
        check(label+' full native cold model equals exact prediction', revision.canonical(source.strict_json(target.read_bytes())) == revision.canonical(source.strict_json(data)))
    def rewrite(profile, mutate):
        manifest = copy.deepcopy(profile['manifest']); members = {name: data for name, data in profile['members'].items() if name != 'project.json'}
        mutate(manifest, members); return project.pack(manifest, members)
    try:
        original = (fixture/'original.dxf').read_bytes(); model_bytes = (fixture/'source-model.json').read_bytes(); model = source.strict_json(model_bytes)
        inspected = source.inspect_bytes(original, 'dxf')
        check('exact text original bytes and typed tag spans retained', inspected['source_bytes'] == original
              and inspected['source_sha256'] == source.sha(original) and inspected['dxf']['sections'] == ['HEADER', 'ENTITIES']
              and inspected['dxf']['records'] == {'ENTITIES/LINE': 1, 'ENTITIES/CIRCLE': 1, 'ENTITIES/TEXT': 1}
              and all(0 <= row['span'][0] < row['span'][1] <= len(original) for row in inspected['dxf']['tags']))
        for label, data in [('crlf', original.replace(b'\n', b'\r\n')), ('cr', original.replace(b'\n', b'\r')),
                            ('bom', b'\xef\xbb\xbf'+original), ('blank', b'\n\n'+original+b' \r\n')]:
            checked = source.inspect_bytes(data, 'dxf')
            check(label+' keeps original spelling and same typed values', checked['source_bytes'] == data
                  and [(t['code'], t['kind'], t['value']) for t in checked['dxf']['tags']] == [(t['code'], t['kind'], t['value']) for t in inspected['dxf']['tags']])
        # This fixture builder uses explicit wire types, independently of the reader.
        binary = bytearray(b'AutoCAD Binary DXF\r\n\x1a\x00'); rows = original.splitlines()
        for index in range(0, len(rows), 2):
            code = int(rows[index]); value = rows[index+1]; binary.extend(struct.pack('<h', code))
            if code in (10, 20, 30, 11, 21, 31, 40): binary.extend(struct.pack('<d', float(value)))
            elif code == 70: binary.extend(struct.pack('<h', int(value)))
            else: binary.extend(value+b'\x00')
        binary = bytes(binary); binary_path = out/'original-binary.dxf'; binary_path.write_bytes(binary)
        binary_profile = source.inspect_bytes(binary, 'dxf')
        check('binary DXF reconstructs the same independently specified wire values', binary_profile['dxf']['encoding'] == 'binary-r13'
              and [(t['code'], t['value']) for t in binary_profile['dxf']['tags']] == [(t['code'], t['value']) for t in inspected['dxf']['tags']])
        native('snapshot', 'dxf', binary_path, out/'binary-model.json')
        check('actual binary DXF parser yields the complete text-source model', revision.canonical(source.strict_json((out/'binary-model.json').read_bytes())) == revision.canonical(model))
        unknown = b'0\nSECTION\n2\nSOURCE_DATA\n0\nORIGINAL_RECORD\n999\nlegacy caf\xe9 / \\U+00E9\n160\n-9007199254740993\n310\n00abFF\n290\n1\n90\n2147483647\n70\n-32768\n40\n.125e2\n0\nENDSEC\n0\nEOF\n'
        owned = source.inspect_bytes(unknown, 'dxf'); values = {t['code']: t['value'] for t in owned['dxf']['tags'] if t['code'] not in (0, 2)}
        check('unknown sections retain exact legacy bytes, escaped text, 64-bit integers and chunks', owned['source_bytes'] == unknown
              and values == {999: b'legacy caf\xe9 / \\U+00E9', 160: -9007199254740993, 310: b'\x00\xab\xff', 290: 1, 90: 2147483647, 70: -32768, 40: 12.5})
        wire = b'AutoCAD Binary DXF\r\n\x1a\x00'+struct.pack('<h',0)+b'SECTION\x00'+struct.pack('<h',2)+b'SOURCE_DATA\x00'
        for code, fmt, value in [(160, '<q', -9007199254740993), (290, '<B', 1), (90, '<i', 2147483647), (70, '<h', -32768), (40, '<d', 12.5)]:
            wire += struct.pack('<h', code)+struct.pack(fmt, value)
        wire += struct.pack('<hh', 255, 310)+b'\x03\x00\xab\xff'+struct.pack('<h',999)+b'legacy caf\xe9 / \\U+00E9\x00'
        wire += struct.pack('<h',0)+b'ENDSEC\x00'+struct.pack('<h',0)+b'EOF\x00'
        wire_values = {t['code']: t['value'] for t in source.inspect_bytes(wire,'dxf')['dxf']['tags'] if t['code'] not in (0,2)}
        check('all binary wire types and escaped group codes preserve exact values', wire_values == values)
        checked = source.inspect_bytes(model_bytes, 'json')
        check('full native JSON inventories all entities and fields without execution permission', checked['inventory']['entity_count'] == 3
              and checked['inventory']['entity_kinds'] == ['circle', 'line', 'text'] and checked['document'] == model and not checked['engine_admission_complete'])
        full = source.strict_json((fixture/'complete.json').read_bytes()); full['handseed'] = 2049
        full['blocks']['OwnedBlock']['xrefPath'] = '/never/open/reference.dwg'
        full['unrecognized_extension'] = {'owned': ['must remain exact', 1, 1.0]}
        rich_bytes = revision.encoded(full)
        with patch('builtins.open', side_effect=AssertionError('unexpected file read')), patch('os.open', side_effect=AssertionError('unexpected file descriptor')):
            rich = source.inspect_bytes(rich_bytes, 'json')
        check('pure source inspection never follows xrefs and retains unknown fields and resource pixels', rich['inventory']['entity_count'] == 5
              and rich['inventory']['external_references'] == [{'kind':'xref','owner':'OwnedBlock','reference':'/never/open/reference.dwg'}]
              and rich['inventory']['binary_bytes'] == 8 and rich['inventory']['unknown_fields'] == ['unrecognized_extension']
              and {'unknown-model-fields','external-reference-policy'} <= set(rich['pending_qualification']))
        source_path = out/'owned.json'; source_path.write_bytes(model_bytes)
        check('regular file snapshot retains original bytes', source.read_source(source_path,'json')['source_bytes'] == model_bytes)
        link = out/'linked.json'; link.symlink_to(source_path); refused('source symlink', lambda:source.read_source(link,'json'))
        fifo = out/'pipe'; os.mkfifo(fifo); refused('source FIFO', lambda:source.read_source(fifo,'json'))
        refused('source directory', lambda:source.read_source(out,'json'))
        for label, text in [('duplicate key',b'{"x":1,"x":2}'),('invalid Unicode',b'"\\ud800"'),('nonfinite',b'NaN'),('overflow',b'1e309'),('integer overflow',b'18446744073709551616')]:
            refused(label, lambda text=text:source.strict_json(text))
        malformed = [
            ('numeric repair',original.replace(b'11\n100\n',b'11\ninvalid\n')),
            ('integer truncation',original.replace(b'70\n4\n',b'70\n4.5\n')),
            ('integer width overflow',original.replace(b'70\n4\n',b'70\n65536\n')),
            ('nonfinite real',original.replace(b'11\n100\n',b'11\n1e309\n')),
            ('boolean coercion',unknown.replace(b'290\n1\n',b'290\n2\n')),
            ('hex repair',unknown.replace(b'00abFF',b'00abFZ')),
            ('data outside section',b'9\n$OUTSIDE\n'+original),('missing EOF',original[:-6]),
            ('trailing payload',original+b'arbitrary payload'),('nested section',original.replace(b'0\nENDSEC',b'0\nSECTION',1)),
            ('duplicate section',original.replace(b'2\nENTITIES',b'2\nHEADER')),
            ('truncated binary',binary[:-1]),('binary float nonfinite',binary.replace(struct.pack('<d',100.0),struct.pack('<d',float('nan')))),
            ('binary boolean coercion',wire.replace(struct.pack('<hB',290,1),struct.pack('<hB',290,2)))]
        for label, data in malformed: refused(label, lambda data=data:source.inspect_bytes(data,'dxf'))
        for label, mutate in [
            ('missing field',lambda d:d.pop('model')),
            ('duplicate handle',lambda d:d['model'].append(copy.deepcopy(d['model'][0]))),
            ('cross-store duplicate',lambda d:d['layouts'][0]['entities'].append(copy.deepcopy(d['model'][0]))),
            ('stale handseed',lambda d:d.update(handseed=256)),('boolean handle',lambda d:d['model'][0].update(handle=True)),
            ('raster length',lambda d:d['rasters']['owned-pixels'].update(width=3)),
            ('raster opacity',lambda d:d['rasters']['owned-pixels'].update(opaque=True)),
            ('raster non-byte',lambda d:d['rasters']['owned-pixels']['rgba'].__setitem__(0,True)),
            ('foreign duplicate',lambda d:d['foreign']['records'].append(copy.deepcopy(d['foreign']['records'][0])))]:
            bad = copy.deepcopy(full); mutate(bad); refused(label, lambda bad=bad:source.inspect_bytes(revision.encoded(bad),'json'))
        portable = project.create(model_bytes,'json',engine=pin)
        check('JSON project preserves exact original baseline and deterministic package', project.create(model_bytes,'json',engine=pin) == portable
              and project.inspect_bytes(portable)['members']['baseline.json'] == model_bytes)
        dxf_project = project.create(original,'dxf',engine=pin,baseline=model_bytes)
        check('DXF candidate baseline stays explicitly unbound', project.inspect_bytes(dxf_project)['native_baseline_binding_required']
              and not project.inspect_bytes(dxf_project)['engine_admission_complete'])
        for label, input_project in [('json',portable),('dxf',dxf_project)]:
            edits = [{'kind':'geometry.set','handle':256,'expected':model['model'][0]['kind'],'set':{'b':{'x':120,'y':0,'z':0}}},
                     {'kind':'geometry.set','handle':257,'expected':model['model'][1]['kind'],'set':{'radius':18}},
                     {'kind':'text.replace','handle':258,'expected':'Workshop / 100 mm','value':'Ångström / 120 mm'},
                     {'kind':'entity.properties','handle':256,'expected':{'visible':True,'ltscale':1.0},'set':{'visible':True,'ltscale':2}}]
            changed = project.revise(input_project,source.sha(input_project),edits); after = project.inspect_bytes(changed)
            predicted = copy.deepcopy(model); predicted['model'][0]['kind']['b']['x'] = 120.0; predicted['model'][1]['kind']['radius'] = 18.0
            predicted['model'][2]['kind']['value'] = 'Ångström / 120 mm'; predicted['model'][0]['common']['ltscale'] = 2.0
            check(label+' typed replay changes only named geometry, text and properties', revision.canonical(after['current']['document']) == revision.canonical(predicted))
            check(label+' original and baseline stay byte exact after revision', after['members']['original.'+label] == (model_bytes if label == 'json' else original)
                  and after['members']['baseline.json'] == model_bytes and after['replayed_edits'] == 4 and after['revision_count'] == 1)
            cold(label+'-revised',after['members']['document.json']); (out/(label+'-revised.dobecad')).write_bytes(changed)
        rich_portable = project.create(rich_bytes,'json',engine=pin)
        paper_edit = {'kind':'geometry.set','handle':1024,'expected':full['layouts'][0]['entities'][0]['kind'],'set':{'b':{'x':125,'y':0,'z':0}}}
        block_edit = {'kind':'geometry.set','handle':1025,'expected':full['blocks']['OwnedBlock']['entities'][0]['kind'],'set':{'a':{'x':5,'y':0,'z':0}}}
        rich_final = project.inspect_bytes(project.revise(rich_portable,source.sha(rich_portable),[paper_edit,block_edit]))
        rich_prediction = copy.deepcopy(full); rich_prediction['layouts'][0]['entities'][0]['kind']['b']['x'] = 125.0; rich_prediction['blocks']['OwnedBlock']['entities'][0]['kind']['a']['x'] = 5.0
        check('paper/block edits retain exact unknown fields, original xrefs, raster pixels and foreign data', revision.canonical(rich_final['current']['document']) == revision.canonical(rich_prediction)
              and rich_final['members']['original.json'] == rich_bytes and rich_final['current']['inventory']['resources'] == rich['inventory']['resources'])
        native('new','metric',out/'metric.json'); recipe = cad_parametric.create(source.strict_json((out/'metric.json').read_bytes()),120,80)
        panel = revision.encoded(recipe['document']); panel_project = project.create(panel,'json',engine=pin)
        parameter = {'kind':'parameter.expression','name':'width','expected':'120','value':'150'}
        parameter_project = project.revise(panel_project,source.sha(panel_project),[parameter]); parameter_profile = project.inspect_bytes(parameter_project)
        check('parameter edit preserves geometry and explicitly requires native solve', parameter_profile['current']['document']['model'] == recipe['document']['model']
              and 'native-constraint-solve' in parameter_profile['pending_qualification'])
        cold('parameter-revised',parameter_profile['members']['document.json'])
        (out/'parameter.dobecad').write_bytes(parameter_project)
        for label, edit in [('stale entity',{**edits[0],'expected':{}}),('unknown entity',{**edits[0],'handle':999}),
                            ('bool handle',{**edits[0],'handle':True}),('negative radius',{**edits[1],'set':{'radius':-1}}),
                            ('bool coordinate',{**edits[0],'set':{'b':{'x':True,'y':0,'z':0}}}),
                            ('unsupported geometry',{**edits[0],'set':{'extrusion':{}}}),
                            ('text control',{**edits[2],'value':'bad\nline'}),('missing layer',{'kind':'entity.properties','handle':256,'expected':{'layer':'0'},'set':{'layer':'missing'}}),
                            ('competing edits',[edits[0],edits[0]]),('empty edits',[]),('no change',{**edits[2],'value':'Workshop / 100 mm'})]:
            refused(label,lambda edit=edit:revision.revise_bytes(model_bytes,source.sha(model_bytes),edit if type(edit) is list else [edit]))
        refused('stale parameter',lambda:revision.revise_bytes(panel,source.sha(panel),[{**parameter,'expected':'121'}]))
        refused('stale original hash',lambda:revision.revise_bytes(model_bytes,'0'*64,edits))
        refused('stale portable hash',lambda:project.revise(portable,'0'*64,edits))
        refused('DXF without baseline',lambda:project.create(original,'dxf',engine=pin))
        current = project.inspect_bytes(changed)
        for label, mutate in [
            ('self-asserted native binding',lambda m,p:m.update(baseline_binding='verified')),
            ('changed current bytes',lambda m,p:p.update({'document.json':model_bytes})),
            ('broken history predecessor',lambda m,p:m['history'][0].update(before='0'*64)),
            ('broken history result',lambda m,p:m['history'][0].update(after='0'*64)),
            ('extra archive member',lambda m,p:p.update({'unowned.txt':b'x'})),
            ('unknown project field',lambda m,p:m.update(execute=True)),
            ('wrong engine product',lambda m,p:m['engine'].update(product='cadcraft'))]:
            bad = rewrite(current,mutate); refused(label,lambda bad=bad:project.inspect_bytes(bad))
        # Rehashing current bytes cannot bypass replay validation.
        def rehash_current(manifest,members):
            members['document.json'] = model_bytes; manifest['members']['document.json'] = project.record(model_bytes)
        refused('rehashed current model outside history',lambda:project.inspect_bytes(rewrite(current,rehash_current)))
        # A foreign DXF candidate can be stored, but never becomes an attested baseline.
        foreign = project.create(original,'dxf',engine=pin,baseline=(out/'metric.json').read_bytes())
        check('unrelated candidate baseline never grants native permission', project.inspect_bytes(foreign)['native_baseline_binding_required']
              and 'native-baseline-binding' in project.inspect_bytes(foreign)['pending_qualification'] and not project.inspect_bytes(foreign)['engine_admission_complete'])
        with patch.object(source,'MAX_TAGS',3):
            refused('aggregate DXF tag budget',lambda:source.inspect_bytes(original,'dxf'))
        with patch.object(source,'MAX_ENTITIES',4):
            refused('aggregate entities across stores',lambda:source.inspect_bytes(rich_bytes,'json'))
        with patch.object(project,'MAX_EDITS',3):
            refused('aggregate replay edit budget',lambda:project.inspect_bytes(changed))
        with patch.object(project,'MAX_HISTORY',0):
            refused('portable history budget',lambda:project.inspect_bytes(changed))
        with patch.object(project,'MAX_REPLAY',len(model_bytes)):
            refused('portable replay byte budget',lambda:project.inspect_bytes(changed))
        refused('deep JSON before parsing',lambda:source.strict_json(b'['*1000+b'0'+b']'*1000))
        refused('trailing archive bytes',lambda:project.inspect_bytes(changed+b'unowned'))
        # A hash update cannot replace an original JSON baseline with a new model.
        def replace_json_baseline(manifest,members):
            members['baseline.json'] = (out/'metric.json').read_bytes()
            manifest['members']['baseline.json'] = project.record(members['baseline.json'])
        refused('replacement JSON baseline',lambda:project.inspect_bytes(rewrite(project.inspect_bytes(portable),replace_json_baseline)))
        # Two separate revisions must replay in sequence with exact predecessor hashes.
        second_edit = {'kind':'text.replace','handle':258,'expected':'Ångström / 120 mm','value':'Ångström / final'}
        second = project.revise(changed,source.sha(changed),[second_edit]); second_profile = project.inspect_bytes(second)
        check('multi-revision history replays exact predecessors and retains original', second_profile['revision_count']==2
              and second_profile['replayed_edits']==5 and second_profile['members']['original.dxf']==original
              and second_profile['current']['document']['model'][2]['kind']['value']=='Ångström / final')
        cold('second-revision',second_profile['members']['document.json'])
        # JSON pointer escaping is derived from an owned block name, never caller paths.
        renamed = copy.deepcopy(full); block = renamed['blocks'].pop('OwnedBlock'); block['name']='A/B~C'; renamed['blocks']['A/B~C']=block
        renamed_bytes=revision.encoded(renamed); renamed_change=revision.revise_bytes(renamed_bytes,source.sha(renamed_bytes),[block_edit])
        check('stable handles resolve escaped block owners without accepting arbitrary paths', renamed_change['document']['blocks']['A/B~C']['entities'][0]['kind']['a']['x']==5.0
              and renamed_change['changed_paths']==['/blocks/A~1B~0C/entities/0/kind'])
        check('input fixtures remain unchanged', (fixture/'original.dxf').read_bytes() == original and (fixture/'source-model.json').read_bytes() == model_bytes)
        evidence = {'passed':True,'checks':checks,'refusals':refusals,'native_calls':calls,'binary_sha256':source.sha(exe.read_bytes()),
                    'engine':pin,'exact_originals':True,'complete_typed_replay':True,'binary_text_complete_native_equal':True,
                    'dxf_native_baseline_binding_implemented':False,'public_runtime_qualified':False,'installed_qualified':False,
                    'general_cad_fidelity_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':calls}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':calls},indent=2)+'\n'); raise


if __name__ == '__main__': main()
