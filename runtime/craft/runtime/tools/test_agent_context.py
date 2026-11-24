"""Context projection retains constraints and evidence needed for creative review."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio_runtime import agent_catalog, agent_context, agent_evidence
from studio_runtime.store import Store, Conflict


class ContextTests(unittest.TestCase):
    def test_native_readback_is_available_for_editability_review(self):
        import json
        from unittest.mock import Mock
        readback={'objects':['Camera','label'],'geometry':{'label':{'type':'FONT','text':'ATELIER','size':.01}},
                  'camera':{'lens':50},'render':{'samples':384},'lights':{'key':{'power':100}}}
        store=Mock();store.get_revision.return_value={'files':[{'path':'production/native/readback.json',
            'role':'native','sha256':'a'*64}],'validation':{'native_cold_reopen':True,'passed':True}}
        with patch('studio_runtime.agent_evidence.blob',return_value=json.dumps(readback).encode()):
            observed=agent_evidence.collect(store,'local','revision')
        self.assertEqual(observed['technical_evidence']['production/native/readback.json'],readback)
        compact=agent_context.evidence(observed,'3d')
        self.assertEqual(compact['technical_evidence']['production/native/readback.json'],readback)

    def test_readback_projection_removes_only_mesh_digests(self):
        readback={'objects':['bottle'],'geometry':{'bottle':{'type':'MESH','materials':['glass'],
                   'matrix':[[1,0,0,2]],'mesh_sha256':'a'*64}},'camera':{'lens':50},'render':{'samples':384}}
        observed={'artifacts':[],'technical_evidence':{'production/native/readback.json':readback}}
        projected=agent_context.evidence(observed,'3d')['technical_evidence']['production/native/readback.json']
        self.assertNotIn('mesh_sha256',projected['geometry']['bottle'])
        self.assertEqual(projected['geometry']['bottle']['matrix'],[[1,0,0,2]])
        self.assertEqual(projected['objects'],['bottle']);self.assertEqual(projected['camera'],readback['camera'])
        self.assertIn('mesh_sha256',readback['geometry']['bottle'])

    def test_operation_interfaces_derive_only_selected_native_operations(self):
        for workflow in agent_catalog.WORKFLOWS:
            interface=agent_catalog.interface(workflow)
            descriptors=interface['operation_descriptors'];tools=interface['tool_definitions']
            self.assertEqual([d['operation'] for d in descriptors],interface['operations'])
            for descriptor,tool in zip(descriptors,tools):
                self.assertEqual(descriptor['version'],1)
                self.assertEqual(tool['parameters'],descriptor['parameters'])
                self.assertFalse(tool['strict'])
                self.assertIn('native validation',descriptor['parameter_scope'])
                self.assertTrue(descriptor['output_artifacts'])
        creation=agent_catalog.interface('video')['tool_definitions'][0]['parameters']
        self.assertEqual(creation['properties']['width']['multipleOf'],2)
        self.assertEqual(creation['properties']['fps']['enum'],[24,25,30,50,60])

    def test_identical_previews_preserve_all_sample_labels_without_resampling(self):
        images = [{'path': path, 'sha256': digest, 'content': {'image_url': raw, 'detail': 'high'}}
                  for path, digest, raw in (('frame-0.png', 'a', 'original-a'), ('frame-59.png', 'a', 'original-a'),
                                            ('frame-60.png', 'b', 'original-b'))]
        unique, aliases = agent_context.previews(images)
        self.assertEqual(unique, [images[0], images[2]])
        self.assertEqual(aliases, {'frame-59.png': 'frame-0.png'})
        images[1]['content']['image_url'] = 'different'
        with self.assertRaises(ValueError):agent_context.previews(images)

    def test_native_proof_retains_all_changes_and_identity_checks(self):
        before = {'objects': ['Camera', 'label'], 'render': {'samples': 384}, 'geometry': {'label': {'text': 'A', 'size': .01}}}
        after = copy.deepcopy(before); after['geometry']['label']['text'] = 'B'
        value = {'artifacts': [], 'technical_evidence': {'production/revision-proof.json': {'before': before, 'after': after, 'passed': True}}}
        result = agent_context.evidence(value, '3d')['technical_evidence']['production/revision-proof.json']
        self.assertTrue(result['object_identity_preserved'])
        self.assertTrue(result['render_settings_preserved'])
        self.assertEqual(result['native_changes'], [{'path': '/geometry/label/text', 'before': 'A', 'after': 'B'}])
        self.assertTrue(result['passed'])
        self.assertEqual(value['technical_evidence']['production/revision-proof.json']['before'], before)

    def test_identifiers_match_authoritative_validator_contracts(self):
        from studio_runtime import image_layers, video, construction_schema
        for workflow, adapter in (('image', image_layers), ('video', video), ('animation', construction_schema)):
            self.assertIn(adapter.NAME.pattern, agent_catalog.contracts()[workflow])
        valid = {'width': 320, 'height': 240, 'fps': 30,
                 'clips': [{'name': 'Warm_ivory_card', 'start': 0, 'frames': 30, 'color': '#FFFFFF'}]}
        agent_catalog.validate('video', 'video.create', valid, None)
        valid['clips'][0]['name'] = 'Warm ivory card'
        with self.assertRaises(ValueError):
            agent_catalog.validate('video', 'video.create', valid, None)

    def test_review_selects_explicit_edit_contracts(self):
        for workflow in ('image', 'video', 'document'):
            descriptor = agent_catalog.describe(workflow)
            create = agent_context.contract(descriptor)
            review = agent_context.contract(descriptor, True)
            self.assertEqual(create['contract'], descriptor['contract'])
            self.assertLess(len(review['contract']), len(create['contract']))
            self.assertIn('.edit ', review['contract'])
            self.assertTrue(review['native_validation_required'])
            self.assertEqual(review['operations'], descriptor['operations'])

    def test_scene_and_animation_keep_parameter_limits(self):
        for workflow in ('3d', 'animation'):
            descriptor = agent_catalog.describe(workflow)
            self.assertEqual(agent_context.contract(descriptor, True)['contract'], descriptor['contract'])

    def test_image_projection_retains_actual_bounds_text_and_warnings(self):
        original = {'revision': 'revision', 'artifacts': [{'path': 'native/structure.json', 'role': 'native', 'sha256': 'a' * 64}],
                    'validation': {'passed': True, 'native_cold_reopen': True}, 'preview_order': ['exports/document.png'],
                    'technical_evidence': {'native/structure.json': {'width': 1200, 'height': 800, 'warnings': ['font issue'],
                        'activeLayer': 9, 'historySource': {'label': 'Open'},
                        'layers': [{'id': 1, 'name': 'title', 'kind': 'Type', 'bounds': [10, -12, 500, 70],
                                    'text': {'font': 'Inter', 'text': 'FIELD NOTES'}, 'visible': True, 'opacity': .8,
                                    'clipped': False, 'selected': True}]}}}
        before = copy.deepcopy(original)
        result = agent_context.evidence(original, 'image')
        self.assertEqual(original, before)
        native = result['technical_evidence']['native/structure.json']
        self.assertEqual(native['warnings'], ['font issue'])
        for key in ('id', 'name', 'kind', 'bounds', 'text', 'visible', 'opacity', 'clipped'):
            self.assertEqual(native['layers'][0][key], original['technical_evidence']['native/structure.json']['layers'][0][key])
        self.assertEqual(result['validation'], original['validation'])
        self.assertEqual(result['preview_order'], original['preview_order'])
        self.assertNotIn('activeLayer', native)
        self.assertNotIn('sha256', result['artifacts'][0])

    def test_other_engine_evidence_is_not_projected_as_image(self):
        original = {'artifacts': [], 'technical_evidence': {'native/structure.json': {'layers': [], 'custom': 'required'}}}
        self.assertEqual(agent_context.evidence(original, 'document'), original)

    def test_duplicate_frames_cannot_crowd_out_distinct_transition(self):
        entries=[{'path':f'exports/frame-{i}.png','role':'export','sha256':str(value)*64}
                 for i,value in enumerate((1,1,1,2,3,2,4,5,2))]
        from unittest.mock import Mock
        store=Mock();store.get_revision.return_value={'files':entries,'validation':{'passed':True}}
        import io
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGB',(8,8),'orange').save(buffer,format='PNG')
        with patch('studio_runtime.agent_evidence.blob',return_value=buffer.getvalue()):
            evidence=agent_evidence.collect(store,'local','revision')
        self.assertEqual(len(evidence['images']),8)
        self.assertEqual({image['sha256'] for image in evidence['images']},{str(i)*64 for i in range(1,6)})

    def test_behavioral_preview_can_be_selected_with_revision_guard(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); store = Store(root / 'state')
            project = store.create_project('local', 'inspection fixture')['id']
            path = root / 'result.png'; Image.new('RGB', (8, 8), 'orange').save(path)
            asset = store.import_asset('local', project, path)
            inspection = {'revision': 'revision', 'passed': True, 'previews': [
                {'project': project, 'asset': asset['id'], 'sha256': asset['sha256'], 'path': 'button/result.png'}]}
            with patch.object(store, 'get_revision', return_value={'files': [], 'validation': {'passed': True}}):
                value = agent_evidence.collect(store, 'local', 'revision', ['inspection/button/result.png'], inspection)
                self.assertEqual([image['path'] for image in value['images']], ['inspection/button/result.png'])
                self.assertEqual(value['artifacts'][0]['sha256'], asset['sha256'])
                with self.assertRaises(Conflict):
                    agent_evidence.collect(store, 'local', 'another-revision', inspection=inspection)


if __name__ == '__main__':
    unittest.main()
