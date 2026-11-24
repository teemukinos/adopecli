#!/usr/bin/env python3
"""Qualify PPTX ownership with real native output and package graph mutations."""
import argparse
import copy
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import slides_pptx as pptx, write_opc as opc, write_container as container


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'model', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; refusals = []; original = args.source.read_bytes(); model = json.loads(args.model.read_bytes())
    def check(label, value):
        if not value: raise AssertionError(label)
        checks.append(label)
    def refused(label, callback):
        try: callback()
        except ValueError as error: refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)
    def archive(members):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in members.items(): z.writestr(name, data)
        return stream.getvalue()
    def mutate(name, action):
        changed = dict(members); tree = container.parse_xml(changed[name])['root']; action(tree)
        changed[name] = ET.tostring(tree, encoding='utf-8', xml_declaration=True); return changed
    try:
        result = pptx.inspect_bytes(original); members = result['members']; main = result['root']; p = '{'+pptx.PRESENTATION[0]+'}'
        rid = '{'+opc.OFFICE[0]+'}id'; rel = '{'+opc.RELS+'}Relationship'; types = '{'+opc.TYPES+'}'
        check('all original source bytes remain authoritative', result['source_bytes'] == original and result['source_sha256'] == pptx.sha(original))
        with zipfile.ZipFile(io.BytesIO(original)) as z:
            check('every payload matches independent ZIP reader', members == {name: z.read(name) for name in z.namelist()})
        check('five ordered slides match complete source inventory', len(result['slides']) == len(model['slides']) == 5)
        check('dimensions remain exact integer EMUs', result['slide_size_emu'] == {'cx': 12192000, 'cy': 6858000})
        check('inspection never grants native admission or source fidelity', not result['engine_admission_complete'] and not result['native_model_reconstructed'] and not result['source_format_fidelity_qualified'])
        for record, source in zip(result['slides'], model['slides']):
            expected = [run['text'] for shape in source['shapes'] if shape['text'] for para in shape['text']['paragraphs'] for run in para['runs']]
            check('slide '+str(record['index'])+' retains exact editable run order', record['text_runs'] == expected)
        check('all layouts retain declared masters and backlinks', len(result['masters']) == 1 and len(result['layouts']) == 11 and all(s['layout'] in result['layouts'] for s in result['slides']))
        check('notes belong to their actual slides', result['slides'][0]['notes_part'] is None and all(run['text'] in result['slides'][1]['notes_text_runs'] for para in model['slides'][1]['notes']['paragraphs'] for run in para['runs']))
        rebuilt = pptx.inspect_bytes(archive(members))
        check('repacking retains all members but not original container identity', rebuilt['members'] == members and rebuilt['source_sha256'] != result['source_sha256'])
        def reorder(root):
            node = root.find(p+'sldIdLst'); items = list(node); node[:] = [items[2], items[0], items[1], *items[3:]]
        reordered = pptx.inspect_bytes(archive(mutate(main, reorder)))
        check('slide order follows relationships rather than filenames', [s['part'] for s in reordered['slides']] == [result['slides'][i]['part'] for i in (2, 0, 1, 3, 4)])
        changed = dict(members)
        changed['ppt/custom.xml'] = changed.pop(main); changed['ppt/_rels/custom.xml.rels'] = changed.pop('ppt/_rels/presentation.xml.rels')
        changed['_rels/.rels'] = changed['_rels/.rels'].replace(b'ppt/presentation.xml', b'ppt/custom.xml')
        changed['[Content_Types].xml'] = changed['[Content_Types].xml'].replace(b'/ppt/presentation.xml', b'/ppt/custom.xml')
        check('main document is discovered from package graph', pptx.inspect_bytes(archive(changed))['root'] == 'ppt/custom.xml')
        changed = dict(members)
        changed['ppt/unreferenced.xml'] = b'<unknown xmlns="urn:dobe:qualification" future="retain">Opaque source information</unknown>'
        unknown = pptx.inspect_bytes(archive(changed))
        check('unreferenced XML is retained and explicitly inventoried', unknown['members']['ppt/unreferenced.xml'] == changed['ppt/unreferenced.xml'] and unknown['unreferenced_parts'] == ['ppt/unreferenced.xml'])
        strict = {}
        for name, data in members.items():
            for old, new in ((pptx.PRESENTATION[0], pptx.PRESENTATION[1]), (pptx.DRAWING[0], pptx.DRAWING[1]), (opc.OFFICE[0], opc.OFFICE[1])):
                data = data.replace(old.encode(), new.encode())
            strict[name] = data
        strict_result = pptx.inspect_bytes(archive(strict))
        check('strict namespace relationships retain ordered contents', strict_result['presentation_namespace'] == pptx.PRESENTATION[1] and [s['text_runs'] for s in strict_result['slides']] == [s['text_runs'] for s in result['slides']])
        # Passive links are inventoried; no fetch, application launch or native
        # model load occurs anywhere in this ownership-only module.
        main_rels = 'ppt/_rels/presentation.xml.rels'
        linked = mutate(main_rels, lambda root: ET.SubElement(root, rel, {'Id': 'passive', 'Type': opc.OFFICE[0]+'/hyperlink', 'Target': 'https://example.invalid/reference', 'TargetMode': 'External'}))
        passive = pptx.inspect_bytes(archive(linked))
        check('passive external hyperlink remains metadata', passive['external_hyperlinks'] == [{'source': main, 'id': 'passive', 'target': 'https://example.invalid/reference'}])
        notes = next(s['notes_part'] for s in result['slides'] if s['notes_part']); notes_rels = str(Path(notes).parent/'_rels'/(Path(notes).name+'.rels'))
        slide = result['slides'][0]['part']
        master = result['masters'][0]['part']; layout = result['slides'][0]['layout']
        layout_rels = str(Path(layout).parent/'_rels'/(Path(layout).name+'.rels'))
        cases = [
            ('layout backlink names a slide', layout_rels, lambda root: next(e for e in root if e.get('Type') == opc.OFFICE[0]+'/slideMaster').set('Target', '../slides/slide1.xml')),
            ('layout loses declared master ownership', master, lambda root: root.find(p+'sldLayoutIdLst').remove(list(root.find(p+'sldLayoutIdLst'))[6])),
            ('duplicate layout ID', master, lambda root: root.find(p+'sldLayoutIdLst')[1].set('id', root.find(p+'sldLayoutIdLst')[0].get('id'))),
            ('master ID below OOXML range', main, lambda root: root.find(p+'sldMasterIdLst')[0].set('id', '256')),
            ('notes lose declared master', main, lambda root: root.remove(root.find(p+'notesMasterIdLst'))),
            ('duplicated ordered slide ID', main, lambda root: root.find(p+'sldIdLst')[1].set('id', root.find(p+'sldIdLst')[0].get('id'))),
            ('duplicated ordered target', main, lambda root: root.find(p+'sldIdLst')[1].set(rid, root.find(p+'sldIdLst')[0].get(rid))),
            ('missing slide relationship', main, lambda root: root.find(p+'sldIdLst')[0].set(rid, 'missing')),
            ('slide ID below OOXML range', main, lambda root: root.find(p+'sldIdLst')[0].set('id', '255')),
            ('slide size exceeds bounded presentation', main, lambda root: root.find(p+'sldSz').set('cx', '51206401')),
            ('negative slide size', main, lambda root: root.find(p+'sldSz').set('cy', '-1')),
            ('ambiguous slide list', main, lambda root: root.append(copy.deepcopy(root.find(p+'sldIdLst')))),
            ('wrong slide relationship type', main_rels, lambda root: next(e for e in root if e.get('Type') == opc.OFFICE[0]+'/slide').set('Type', opc.OFFICE[0]+'/theme')),
            ('external slide relationship', main_rels, lambda root: next(e for e in root if e.get('Type') == opc.OFFICE[0]+'/slide').set('TargetMode', 'External')),
            ('relationship escapes archive', main_rels, lambda root: next(e for e in root if e.get('Type') == opc.OFFICE[0]+'/slide').set('Target', '../../../outside.xml')),
            ('notes backlink changes owning slide', notes_rels, lambda root: next(e for e in root if e.get('Type') == opc.OFFICE[0]+'/slide').set('Target', '../slides/slide1.xml')),
            ('duplicate shape identity', slide, lambda root: list(root.iter(p+'cNvPr'))[1].set('id', list(root.iter(p+'cNvPr'))[0].get('id'))),
            ('active OLE shape', slide, lambda root: ET.SubElement(root, p+'oleObj')),
            ('wrong slide XML root', slide, lambda root: setattr(root, 'tag', p+'notes')),
            ('wrong main content type', '[Content_Types].xml', lambda root: next(e for e in root if e.get('PartName') == '/'+main).set('ContentType', opc.DOC_MIME)),
            ('macro-enabled main content', '[Content_Types].xml', lambda root: next(e for e in root if e.get('PartName') == '/'+main).set('ContentType', 'application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml')),
        ]
        for label, name, action in cases: refused(label, lambda name=name, action=action: pptx.inspect_bytes(archive(mutate(name, action))))
        bad = dict(members); bad[slide] = b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///private/source">]><x>&a;</x>'
        refused('XML external entity', lambda: pptx.inspect_bytes(archive(bad)))
        bad = dict(members); bad['../escape.xml'] = b'<x/>'
        refused('archive path escape', lambda: pptx.inspect_bytes(archive(bad)))
        refused('whole-source truncation', lambda: pptx.inspect_bytes(original[:-1]))
        check('fixture is unchanged after all inspections', args.source.read_bytes() == original)
        evidence = {'passed': True, 'checks': checks, 'refusals': refusals, 'source_sha256': result['source_sha256'],
                    'members': len(members), 'slides': len(result['slides']), 'relationships': result['relationship_count'],
                    'xml_nodes': result['xml_nodes'], 'native_execution': False, 'remote_actions': False,
                    'engine_admission_complete': False, 'source_format_fidelity_qualified': False, 'goal_complete': False}
        (out/'evidence.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps({'checks': len(checks), 'refusals': len(refusals)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error': str(error), 'checks': checks, 'refusals': refusals}, indent=2)+'\n'); raise


if __name__ == '__main__': main()
