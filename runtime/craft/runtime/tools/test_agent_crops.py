"""Crop inspection uses original pixels, immutable sources and durable selection."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from studio_runtime import agent_crops, agent_evidence
from studio_runtime.agent import Coordinator, specification
from studio_runtime.agent_store import Journal
from studio_runtime.store import Conflict, Store


class CropTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.store=Store(self.root/'state')
        self.project=self.store.create_project('local','Crop fixture')['id']
        self.source=Image.new('RGBA',(80,60))
        self.source.putdata([(x*3,y*4,(x+y)%256,(x*2+y)%256) for y in range(60) for x in range(80)])
        path=self.root/'source.png';self.source.save(path)
        self.raw=path.read_bytes();asset=self.store.import_asset('local',self.project,path)
        self.entry={'path':'exports/source.png','role':'export','sha256':asset['sha256']}
        self.manifest={'files':[self.entry],'validation':{'passed':True}}
        mocked=patch.object(self.store,'get_revision',return_value=self.manifest)
        mocked.start();self.addCleanup(mocked.stop)
        self.context={'revision':'revision-one','approved_constraints':['Keep exact text.']}
        self.decision={'action':'inspect','revision':'revision-one',
                       'crops':[{'path':self.entry['path'],'box':[12,8,25,20]}]}

    def collect(self,decision=None):
        selected=agent_evidence.inspection_selection(self.store,'local',self.context,decision or self.decision)
        return selected,agent_evidence.collect(self.store,'local','revision-one',selected['selection'],crops=selected['crops'])

    def test_original_pixels_alpha_and_source_are_preserved(self):
        _,observed=self.collect();image=observed['images'][0]
        raw=base64.b64decode(image['content']['image_url'].split(',',1)[1])
        with Image.open(io.BytesIO(raw)) as crop:
            self.assertEqual(crop.size,(25,20));self.assertEqual(crop.mode,'RGBA')
            self.assertEqual(crop.tobytes(),self.source.crop((12,8,37,28)).tobytes())
        self.assertEqual(agent_evidence.blob(self.store,self.entry),self.raw)
        proof=observed['technical_evidence']['detail_crops'][0]
        self.assertEqual(proof['source_sha256'],self.entry['sha256'])
        self.assertFalse(proof['resampled']);self.assertEqual(proof['sha256'],hashlib.sha256(raw).hexdigest())

    def test_paths_bounds_counts_and_types_fail_closed(self):
        for box in ([-1,0,2,2],[0,0,0,2],[0,0,81,2],[79,59,2,2],[0,0,2.0,2],[False,0,2,2],[0,0,2]):
            with self.subTest(box=box),self.assertRaises(ValueError):
                decision=copy.deepcopy(self.decision);decision['crops'][0]['box']=box;self.collect(decision)
        for path in ('/exports/source.png','exports/../exports/source.png','exports//source.png','Exports/source.png','source.png'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                decision=copy.deepcopy(self.decision);decision['crops'][0]['path']=path;self.collect(decision)
        for regions in ([],self.decision['crops']*2,self.decision['crops']*9):
            with self.assertRaises(ValueError):self.collect({**self.decision,'crops':regions})
        regions=[{'path':self.entry['path'],'box':[i,0,1,1]} for i in range(8)]
        with self.assertRaises(ValueError):self.collect({**self.decision,'artifacts':[self.entry['path']],'crops':regions})

    def test_revision_hash_corruption_and_partial_bytes_are_rejected(self):
        with self.assertRaises(Conflict):self.collect({**self.decision,'revision':'old-revision'})
        selected,_=self.collect();selected['crops']['regions'][0]['sha256']='a'*64
        with self.assertRaises(Conflict):agent_evidence.collect(self.store,'local','revision-one',crops=selected['crops'])
        with patch('studio_runtime.agent_crops.MAX_PIXELS',100):
            with self.assertRaises(ValueError):self.collect()
        with self.assertRaises((OSError,ValueError)):
            raw=self.raw[:50];agent_crops.render(raw,{'sha256':hashlib.sha256(raw).hexdigest(),'box':[0,0,1,1]},'revision-one')
        blob=self.store.blobs/self.entry['sha256'];blob.chmod(0o600);blob.write_bytes(b'corrupt')
        with self.assertRaises(Conflict):self.collect()

    def test_jpeg_crop_matches_decoded_source_without_resampling(self):
        output=io.BytesIO();self.source.convert('RGB').save(output,format='JPEG')
        raw=output.getvalue();region={'path':'exports/source.jpg','sha256':hashlib.sha256(raw).hexdigest(),'box':[2,3,20,15]}
        result,_=agent_crops.render(raw,region,'revision-one')
        with Image.open(io.BytesIO(raw)) as original,Image.open(io.BytesIO(result)) as crop:
            self.assertEqual(crop.tobytes(),original.crop((2,3,22,18)).tobytes())

    def test_behavioral_previews_use_same_crop_interface(self):
        asset=self.store.import_asset('local',self.project,self.root/'source.png')
        self.context['inspection']={'revision':'revision-one','passed':True,'previews':[
            {'project':self.project,'asset':asset['id'],'sha256':asset['sha256'],'path':'button/pressed.png'}]}
        decision={**self.decision,'crops':[{'path':'inspection/button/pressed.png','box':[0,0,20,20]}]}
        selected=agent_evidence.inspection_selection(self.store,'local',self.context,decision)
        observed=agent_evidence.collect(self.store,'local','revision-one',inspection=self.context['inspection'],crops=selected['crops'])
        self.assertEqual(observed['images'][0]['dimensions'],[20,20])

    def test_restart_reuses_selection_without_model_or_render_calls(self):
        journal=Journal(self.store)
        run=journal.create(self.project,specification('Keep exact text.','image'),1)['id']
        owner=journal.claim(run);selected,observed=self.collect()
        journal.set_state(run,owner,'inspecting',{**self.context,**selected});journal.release(run,owner)
        # Reopening the existing Store reproduces bytes from persisted hashes.
        reopened=Store(self.store.root)
        with patch.object(reopened,'get_revision',return_value=self.manifest):
            coordinator=Coordinator(reopened)
            with patch('studio_runtime.agent_provider.Provider',side_effect=AssertionError('Unexpected API call')),patch.object(reopened,'submit',side_effect=AssertionError('Unexpected render')):
                request,after=coordinator.request(coordinator.journal.status(run))
            self.assertEqual(after['images'],observed['images'])
            text=json.loads(request['input'][0]['content'][0]['text'])
            self.assertEqual(text['brief'],'Keep exact text.')
            self.assertEqual(text['evidence']['preview_dimensions'][after['images'][0]['path']],[25,20])
            self.assertIn('detail_crops',text['evidence']['technical_evidence'])
            self.assertEqual(coordinator.journal.status(run)['calls'],[])

    def test_received_inspect_decision_replays_in_both_arms_without_payment(self):
        from agent_benchmark import baseline_class
        for coordinator_type in (Coordinator,baseline_class()):
            with self.subTest(arm=coordinator_type.__name__):
                journal=Journal(self.store)
                run=journal.create(self.project,specification('Keep exact text.','image'),1)['id']
                owner=journal.claim(run);journal.set_state(run,owner,'ready',self.context)
                number=journal.reserve(run,owner,{},1)
                response={'status':'completed','output':[{'type':'message','content':[
                    {'type':'output_text','text':json.dumps(self.decision)}]}]}
                journal.settle(run,owner,number,response=response,usage={},charge=0)
                journal.release(run,owner)
                coordinator=coordinator_type(self.store)
                with patch.object(coordinator,'_call',return_value=None),patch.object(self.store,'submit',side_effect=AssertionError('Unexpected render')):
                    status=coordinator.run(run)
                self.assertEqual(status['state'],'inspecting')
                self.assertEqual(status['context']['consumed_call'],1)
                self.assertEqual(status['context']['crops']['regions'][0]['sha256'],self.entry['sha256'])
                self.assertEqual(len(status['calls']),1)
                self.assertEqual(status['calls'][0]['charged_microusd'],0)

    def test_alternating_inspection_keeps_assessments_after_restart(self):
        first={**self.decision,'notes':'Full composition passes; inspect glass detail.'}
        selected=agent_evidence.inspection_selection(self.store,'local',self.context,first)
        context={**self.context,**selected}
        second={'action':'inspect','revision':'revision-one','artifacts':[self.entry['path']],
                'notes':'Label is readable; glass faceting remains unresolved.'}
        selected=agent_evidence.inspection_selection(self.store,'local',context,second)
        journal=Journal(self.store)
        run=journal.create(self.project,specification('Keep exact text.','image'),1)['id']
        owner=journal.claim(run)
        journal.set_state(run,owner,'inspecting',{**context,**selected});journal.release(run,owner)
        reopened=Store(self.store.root)
        with patch.object(reopened,'get_revision',return_value=self.manifest),patch('studio_runtime.agent_provider.Provider',side_effect=AssertionError('Unexpected API call')):
            coordinator=Coordinator(reopened)
            request,_=coordinator.request(coordinator.journal.status(run))
        state=json.loads(request['input'][0]['content'][0]['text'])['state']
        memory=state['inspection_memory']
        self.assertEqual(memory['revision'],'revision-one')
        self.assertEqual([entry['notes'] for entry in memory['assessments']],[first['notes'],second['notes']])
        self.assertEqual(memory['assessments'][1]['reviewed']['crops'],context['crops']['regions'])
        self.assertEqual(state['approved_constraints'],['Keep exact text.'])
        self.assertNotIn('image_url',json.dumps(memory))
        self.assertEqual(coordinator.journal.status(run)['calls'],[])

    def test_inspection_memory_is_bounded_and_stale_findings_are_not_reused(self):
        context=copy.deepcopy(self.context)
        for number in range(6):
            decision={**self.decision,'notes':str(number)+'x'*2500}
            context.update(agent_evidence.inspection_selection(self.store,'local',context,decision))
        memory=context['inspection_memory']
        self.assertEqual(len(memory['assessments']),4)
        self.assertEqual(memory['omitted_assessments'],2)
        self.assertTrue(all(len(a['notes'])==2000 and a['notes_truncated'] for a in memory['assessments']))
        self.assertNotIn('inspection_memory',agent_evidence.selected_state({**context,'revision':'new-revision'}))
        memory['version']=999
        with self.assertRaisesRegex(Conflict,'inspection memory version'):
            agent_evidence.selected_state(context)
        with self.assertRaises(ValueError):
            agent_evidence.inspection_selection(self.store,'local',self.context,{**self.decision,'notes':{}})

    def test_new_native_revision_clears_prior_inspection_assessments(self):
        journal=Journal(self.store)
        run=journal.create(self.project,specification('Keep exact text.','image'),1)['id']
        owner=journal.claim(run)
        context={**self.context,**agent_evidence.inspection_selection(self.store,'local',self.context,self.decision)}
        journal.set_state(run,owner,'ready',context)
        decision={'operation':'image.edit','parameters':{'edits':[{'name':'label','text':'Updated'}]},'source_revision':'revision-one'}
        journal.step(run,owner,1,decision)
        coordinator=Coordinator(self.store)
        self.manifest.update(project=self.project,engine={'name':'image'})
        with patch('studio_runtime.capabilities.engine_identity',return_value={'name':'image'}),patch.object(self.store,'submit',return_value={'id':'synthetic-job','state':'succeeded','result_revision':'revision-two'}):
            status=journal.status(run)
            self.assertTrue(coordinator._execute(run,owner,status,status['steps'][0]))
        context=journal.status(run)['context']
        self.assertEqual(context['revision'],'revision-two')
        self.assertNotIn('inspection_memory',context)
        self.assertIsNone(context['crops'])


if __name__=='__main__':unittest.main()
