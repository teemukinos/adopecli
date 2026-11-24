"""Local orchestration contracts; no provider requests or paid services."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from studio_runtime.store import Store, Conflict, LeaseLost
from studio_runtime.agent_store import Journal, dollars
from studio_runtime.agent import Coordinator, specification, public_status
from studio_runtime import agent_catalog, agent_provider, agent_evidence, production_schema

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'state');self.journal=Journal(self.store)
        self.project=self.store.create_project('local','test')['id']
        self.spec=specification('Shared constraint: retain exact text.','image')
        self.run=self.journal.create(self.project,self.spec,1)['id']
        self.owner=self.journal.claim(self.run)
    def reserve(self,maximum=900000):
        return self.journal.reserve(self.run,self.owner,{'request':{'input':'private evidence'}},maximum)
    def test_duplicate_resume_is_fenced(self):
        with self.assertRaises(Conflict):self.journal.claim(self.run)
    def test_expired_owner_cannot_write(self):
        with self.store.transaction() as db:db.execute('UPDATE agent_runs SET lease_until=0 WHERE id=?',(self.run,))
        successor=self.journal.claim(self.run)
        with self.assertRaises(LeaseLost):self.journal.set_state(self.run,self.owner,'completed')
        self.journal.release(self.run,self.owner)
        self.journal.heartbeat(self.run,successor)
    def test_sleep_recovery_renews_only_unsuperseded_owner(self):
        with self.store.transaction() as db:db.execute('UPDATE agent_runs SET lease_until=0 WHERE id=?',(self.run,))
        self.journal.heartbeat(self.run,self.owner)
        self.journal.set_state(self.run,self.owner,'ready')
        with self.store.transaction() as db:db.execute('UPDATE agent_runs SET lease_until=0 WHERE id=?',(self.run,))
        successor=self.journal.claim(self.run)
        with self.assertRaises(LeaseLost):self.journal.heartbeat(self.run,self.owner)
        self.journal.heartbeat(self.run,successor)
    def test_concurrent_reservations_share_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        budget=self.journal.status(self.run)['budget']
        other=self.journal.create(self.project,self.spec,budget=budget)['id'];owner=self.journal.claim(other)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.journal.reserve,r,o,{},600000) for r,o in ((self.run,self.owner),(other,owner))]
            self.assertEqual(sum(f.result() is not None for f in futures),1)
    def test_shared_budget_counts_both_runs(self):
        self.reserve()
        budget=self.journal.status(self.run)['budget']
        other=self.journal.create(self.project,self.spec,budget=budget)['id'];owner=self.journal.claim(other)
        self.assertIsNone(self.journal.reserve(other,owner,{},100001))
        self.assertEqual(self.journal.status(other)['state'],'budget_exhausted')
    def test_storage_admission_blocks_new_calls_but_allows_settlement(self):
        from studio_runtime.capacity import CapacityError
        call=self.reserve()
        with patch('studio_runtime.agent_store.capacity.admit',side_effect=CapacityError('synthetic storage pressure')):
            with self.assertRaises(CapacityError):self.journal.budget(1)
            with self.assertRaises(CapacityError):self.reserve(1)
            self.journal.settle(self.run,self.owner,call,response={},usage={},charge=10)
        status=self.journal.status(self.run)
        self.assertEqual(len(status['calls']),1)
        self.assertEqual(status['budget_committed_microusd'],10)
    def test_charge_releases_only_known_unused_reservation(self):
        call=self.reserve();self.journal.settle(self.run,self.owner,call,response={},usage={},charge=123)
        self.assertEqual(self.journal.status(self.run)['budget_committed_microusd'],123)
        with self.assertRaises(Conflict):self.journal.settle(self.run,self.owner,call,charge=0)
    def test_timeout_retains_reservation(self):
        call=self.reserve();self.journal.settle(self.run,self.owner,call,error='TimeoutError')
        status=self.journal.status(self.run)
        self.assertEqual(status['state'],'uncertain');self.assertEqual(status['budget_committed_microusd'],900000)
        with self.assertRaises(Conflict):self.reserve(1)
    def test_crash_after_reservation_never_reissues(self):
        self.reserve();self.journal.release(self.run,self.owner)
        self.assertIsNone(self.journal.claim(self.run))
        self.assertEqual(self.journal.status(self.run)['state'],'uncertain')
    def test_overcharge_is_never_zero_cost(self):
        call=self.reserve()
        with self.assertRaises(ValueError):self.journal.settle(self.run,self.owner,call,response={},charge=900001)
        self.assertEqual(self.journal.status(self.run)['budget_committed_microusd'],900000)
    def test_completed_resume_is_idempotent(self):
        self.journal.set_state(self.run,self.owner,'completed');self.journal.release(self.run,self.owner)
        self.assertIsNone(self.journal.claim(self.run))
    def test_changed_contract_is_refused_without_mutating_the_run(self):
        self.journal.release(self.run,self.owner)
        before=self.journal.status(self.run)
        with patch.object(agent_catalog,'execution_binding',return_value={'version':999}):
            with self.assertRaisesRegex(Conflict,'contract or package changed'):
                Coordinator(self.store).run(self.run)
        self.assertEqual(self.journal.status(self.run),before)
    def test_unknown_run_version_is_refused_before_any_request(self):
        spec={**self.spec,'version':999}
        run=self.journal.create(self.project,spec,1)['id']
        with self.assertRaisesRegex(Conflict,'run-state version'):
            Coordinator(self.store).run(run)
        status=self.journal.status(run)
        self.assertEqual(status['state'],'ready');self.assertEqual(status['calls'],[])
    def test_legacy_completed_result_stays_readable_without_contract_replay(self):
        spec={k:v for k,v in self.spec.items() if k!='execution_binding'}
        run=self.journal.create(self.project,spec,1)['id']
        with self.assertRaisesRegex(Conflict,'originating development package'):
            Coordinator(self.store).run(run)
        owner=self.journal.claim(run);self.journal.set_state(run,owner,'completed');self.journal.release(run,owner)
        self.assertEqual(Coordinator(self.store).run(run)['state'],'completed')
        self.assertEqual(self.journal.status(run)['calls'],[])
    def test_baseline_allows_native_inspection_without_spending_correction(self):
        from agent_benchmark import baseline_class
        run=self.journal.create(self.project,specification('Inspect native animation.','animation'),1)['id']
        owner=self.journal.claim(run)
        self.journal.set_state(run,owner,'inspecting',{'revision':'native-revision'})
        self.journal.release(run,owner)
        class Transport:
            count_calls=0
            def count(self,request):return 1,'synthetic-count'
            def generate(self,request):
                self.count_calls+=1
                answer=({'action':'submit','operation':'construct.inspect','parameters':{}} if self.count_calls==1 else
                        {'action':'accept','checks':{'brief':True},'findings':[],'limitations':[]})
                return {'status':'completed','usage':{'input_tokens':1,'output_tokens':1},
                        'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]},'synthetic-response'
        observed={'revision':'native-revision','validation':{'passed':True},'artifacts':[], 'sources':{},'technical_evidence':{},
                  'images':[{'path':'preview.png','sha256':'a'*64,'content':{'type':'input_image','image_url':'synthetic'}}]}
        baseline=baseline_class()
        def execute(coordinator,run,owner,status,step):
            context={**status['context'],'consumed_call':step['decision']['model_call']}
            coordinator.journal.complete_step(run,owner,step['number'],'native-revision',context,{'synthetic':True})
            return True
        with patch.object(baseline,'_execute',execute),patch('studio_runtime.agent_evidence.collect',return_value=observed):
            result=baseline(self.store,transport=Transport()).run(run)
        self.assertEqual(result['state'],'completed',result['context'])
        self.assertEqual(result['steps'][0]['decision']['source_revision'],'native-revision')
        self.assertEqual(result['context'].get('corrections',0),0)
    def test_cancel_idle_run(self):
        self.journal.release(self.run,self.owner)
        self.assertEqual(self.journal.cancel(self.run)['state'],'cancelled')
    def test_cancel_uncertain_preserves_hold(self):
        self.reserve();self.journal.release(self.run,self.owner)
        self.assertEqual(self.journal.cancel(self.run)['state'],'uncertain')
    def test_cancel_finds_job_before_step_link_was_saved(self):
        params={'width':64,'height':64,'background':'#FFFFFF','layers':[{'name':'fill','type':'solid','color':'#FFFFFF'}]}
        self.journal.step(self.run,self.owner,1,{'operation':'image.create','parameters':params,'source_revision':None})
        job=self.store.submit('local',self.project,'image.create',params,'agent-'+self.run+'-1',None,7200)
        self.journal.cancel(self.run)
        self.assertEqual(self.store.get_job('local',job['id'])['state'],'cancelled')
        self.assertIsNone(self.journal.status(self.run)['steps'][0]['job'])
    def test_stale_coordinator_snapshot_cannot_submit_after_cancel(self):
        params={'width':64,'height':64,'background':'#FFFFFF','layers':[{'name':'fill','type':'solid','color':'#FFFFFF'}]}
        self.journal.step(self.run,self.owner,1,{'operation':'image.create','parameters':params,'source_revision':None})
        stale=self.journal.status(self.run)
        self.journal.cancel(self.run)
        with self.assertRaises(Conflict):
            Coordinator(self.store)._execute(self.run,self.owner,stale,stale['steps'][0])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
    def test_cancel_finds_unlinked_job_in_active_reconstruction_project(self):
        child=self.store.create_project('local','Reconstruction')['id']
        params={'width':64,'height':64,'background':'#FFFFFF','layers':[{'name':'fill','type':'solid','color':'#FFFFFF'}]}
        self.journal.set_state(self.run,self.owner,'ready',{'active_project':child,'reconstruction_projects':{'1':child}})
        self.journal.step(self.run,self.owner,2,{'operation':'image.create','parameters':params,'source_revision':None})
        job=self.store.submit('local',child,'image.create',params,'agent-'+self.run+'-2',None,7200)
        self.journal.cancel(self.run)
        self.assertEqual(self.store.get_job('local',job['id'])['state'],'cancelled')
    def test_atomic_step_commit(self):
        decision={'operation':'image.create','parameters':{}}
        self.journal.step(self.run,self.owner,1,decision)
        self.journal.complete_step(self.run,self.owner,1,'revision',{'revision':'revision','corrections':1},{})
        status=self.journal.status(self.run)
        self.assertEqual(status['steps'][0]['state'],'completed');self.assertEqual(status['context']['corrections'],1)
        with self.assertRaises(Conflict):self.journal.step(self.run,self.owner,1,{'different':True})
    def test_status_does_not_dump_context_or_previews(self):
        self.reserve();status=public_status(self.journal.status(self.run))
        self.assertNotIn('private evidence',json.dumps(status));self.assertNotIn('specification',status)
    def test_constraints_survive_compact_request(self):
        request,_=Coordinator(self.store).request(self.journal.status(self.run))
        text=request['input'][0]['content'][0]['text']
        self.assertIn(self.spec['brief'],text);self.assertNotIn('production.create',text)
    def test_provider_failure_reserves_once(self):
        class Failure:
            calls=0
            def count(self,r):return 10,'count'
            def generate(self,r):self.calls+=1;raise TimeoutError('lost response')
        transport=Failure();coordinator=Coordinator(self.store,transport=transport)
        self.journal.release(self.run,self.owner);status=coordinator.run(self.run)
        self.assertEqual(status['state'],'uncertain');self.assertEqual(transport.calls,1)
        self.assertEqual(len(status['calls']),1);self.assertGreater(status['budget_committed_microusd'],0)
    def test_unknown_response_cannot_be_reconciled(self):
        call=self.reserve();self.journal.settle(self.run,self.owner,call,error='timeout')
        self.journal.release(self.run,self.owner)
        with self.assertRaises(Conflict):self.journal.reconcile_received_usage(self.run)
    def test_received_cache_usage_can_be_reconciled_without_network(self):
        usage={'input_tokens':100,'output_tokens':2,'input_tokens_details':{'cache_write_tokens':80,'cache_write_tokens_details':{'ttl_30m_tokens':80}}}
        response={'status':'completed','usage':usage};call=self.reserve()
        self.journal.settle(self.run,self.owner,call,response=response,usage=usage,error='old accounting format')
        self.journal.release(self.run,self.owner)
        status=self.journal.reconcile_received_usage(self.run)
        self.assertEqual(status['state'],'ready');self.assertEqual(status['calls'][0]['charged_microusd'],1300)
        self.assertEqual(len(status['context']['usage_reconciliations']),1)
    def test_waiting_does_not_generate_model_calls(self):
        params={'width':64,'height':64,'background':'#FFFFFF','layers':[{'name':'fill','type':'solid','color':'#FFFFFF'}]}
        decision={'operation':'image.create','parameters':params,'source_revision':None}
        self.journal.step(self.run,self.owner,1,decision);status=self.journal.status(self.run)
        coordinator=Coordinator(self.store,poll_seconds=0)
        with patch('studio_runtime.agent.time.monotonic',side_effect=[0,121]):
            self.assertFalse(coordinator._execute(self.run,self.owner,status,status['steps'][0]))
        first=self.journal.status(self.run)
        self.assertEqual(first['calls'],[]);self.assertEqual(first['steps'][0]['state'],'waiting')
        with patch('studio_runtime.agent.time.monotonic',side_effect=[0,121]):
            coordinator._execute(self.run,self.owner,first,first['steps'][0])
        self.assertEqual(self.journal.status(self.run)['steps'][0]['job'],first['steps'][0]['job'])
    def test_new_engine_runs_without_coordinator_control_flow_changes(self):
        import hashlib
        import io
        from PIL import Image
        class Adapter:
            @staticmethod
            def validate(operation,parameters,source):
                if operation!='mock.create' or parameters!={'value':1} or source is not None:
                    raise ValueError('Invalid extension request')
        responses=[{'action':'submit','operation':'mock.create','parameters':{'value':1}},
                   {'action':'accept','checks':{'brief':True},'findings':['fixture pixels inspected'],'limitations':[]}]
        class Transport:
            def count(self,request):return 100,'count-fixture'
            def generate(self,request):
                decision=responses.pop(0)
                return {'status':'completed','usage':{'input_tokens':100,'output_tokens':20},
                        'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(decision)}]}]},'fixture-request'
        buffer=io.BytesIO();Image.new('RGB',(8,8),'white').save(buffer,format='PNG');raw=buffer.getvalue()
        digest=hashlib.sha256(raw).hexdigest();(self.store.blobs/digest).write_bytes(raw)
        manifest={'files':[{'path':'exports/preview.png','role':'export','sha256':digest}],'validation':{'passed':True}}
        contract={'operations':['mock.create'],'family':'extension','inspection':['fixture pixels']}
        with patch.dict(agent_catalog.WORKFLOWS,{'extension':contract}),patch.object(agent_catalog,'contracts',return_value={'extension':'mock.create takes value=1'}),patch.object(agent_catalog.capabilities,'adapter',return_value=Adapter),patch.object(agent_catalog.capabilities,'OPERATIONS',('mock.create',)),patch.object(agent_catalog.capabilities,'validate_for_project'),patch.object(self.store,'submit',return_value={'id':'mock-job','state':'succeeded','result_revision':'mock-revision'}),patch.object(self.store,'get_revision',return_value=manifest):
            spec=specification('Render fixture pixels.','extension');run=self.journal.create(self.project,spec,1)['id']
            status=Coordinator(self.store,transport=Transport()).run(run)
        self.assertEqual(status['state'],'completed',status['context'])
        self.assertEqual(len(status['calls']),2);self.assertEqual(status['steps'][0]['job'],'mock-job')

    def test_schema_fences_old_writers(self):
        db=sqlite3.connect(self.store.db);self.addCleanup(db.close)
        db.create_function('studio_writer_version',0,lambda:5)
        with self.assertRaises(sqlite3.DatabaseError):db.execute("UPDATE agent_runs SET state='ready'")
    def test_newer_schema_refused(self):
        with self.store.connect() as db:db.execute('PRAGMA user_version=999')
        with self.assertRaises(ValueError):Store(self.store.root)
    def test_alias_state_root_refused(self):
        alias=Path(self.temp.name)/'alias';alias.symlink_to(self.store.root)
        with self.assertRaises(ValueError):Store(alias)
    def test_migration_preserves_existing_project(self):
        with self.store.connect() as db:db.execute('PRAGMA user_version=5')
        upgraded=Store(self.store.root)
        self.assertEqual(upgraded.get_project('local',self.project)['id'],self.project)

class ContractTests(unittest.TestCase):
    def test_invalid_credentials_cannot_enter_http_error_messages(self):
        for value in ('private-secret\nheader', 'private-secret\x00', 'private-secret\u2028header'):
            with self.assertRaises(ValueError) as raised:agent_provider.Provider(credential=value)
            self.assertNotIn('private-secret',str(raised.exception))
        self.assertEqual(agent_provider.Provider(credential='  synthetic-token  ').credential,'synthetic-token')
    def test_rates_include_reasoning_once(self):
        usage={'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':40},'output_tokens_details':{'reasoning_tokens':15}}
        self.assertEqual(agent_provider.cost(usage),1640)
    def test_invalid_usage_rejected(self):
        for value in (-1,True,1.5):
            with self.assertRaises(ValueError):agent_provider.cost({'input_tokens':value,'output_tokens':1})
    def test_both_cache_write_prices(self):
        usage={'input_tokens':100,'output_tokens':0,'input_tokens_details':{'cached_tokens':20,'cache_write_tokens':70,'cache_write_tokens_details':{'ttl_30m_tokens':40,'ttl_12h_tokens':30}}}
        self.assertEqual(agent_provider.cost(usage),1370)
    def test_invalid_budgets_rejected(self):
        for value in (0,-1,float('inf'),float('nan'),True,0.0000001):
            with self.assertRaises(ValueError):dollars(value)
    def test_all_descriptors_match_registration(self):
        for name in agent_catalog.WORKFLOWS:
            desc=agent_catalog.describe(name)
            self.assertEqual(len(desc['validator_sha256']),64)
            for op in desc['operations']:self.assertIn(op,agent_catalog.capabilities.OPERATIONS)
    def test_missing_engine_is_not_qualified(self):
        with patch('studio_runtime.construction_support.binary',side_effect=ValueError('missing')):
            result=agent_catalog.availability('3d')
        self.assertFalse(result['available']);self.assertFalse(result['qualified_for_agent_workflow'])
    def test_unrelated_operation_rejected(self):
        with self.assertRaises(ValueError):agent_catalog.validate('image','production.create',{},None)
    def test_simulated_engine_extension_needs_no_coordinator_branch(self):
        fake={'operations':['image.create'],'family':'image','inspection':['native']}
        with patch.dict(agent_catalog.WORKFLOWS,{'extension':fake}),patch.object(agent_catalog,'contracts',return_value={'extension':'fixture contract'}):
            spec=specification('Keep shared constraints.','extension')
            self.assertEqual(spec['workflow'],'extension')
            self.assertIn('fixture contract',agent_catalog.documentation('extension'))
    def test_focus_keeps_policy(self):
        context={'shared':['one'],'document':{'policy':{'network':'offline'},'components':[{'id':'a','engine':'rive'},{'id':'b','engine':'rive'}]}}
        reduced=agent_evidence.selected_state(context,['a'])
        self.assertEqual(reduced['shared'],['one']);self.assertEqual(reduced['document']['policy'],context['document']['policy'])
        self.assertEqual(len(reduced['document']['components']),1);self.assertEqual(len(context['document']['components']),2)
    def test_partial_or_corrupt_blob_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            class Fake:blobs=Path(temp)
            (Path(temp)/('0'*64)).write_bytes(b'partial')
            with self.assertRaises(Conflict):agent_evidence.blob(Fake(),{'sha256':'0'*64})
    def test_new_production_edit_fields(self):
        for group,field,value in [('camera','lens',70),('objects','location',[1,2,3]),('objects','text','NEW'),('world','strength',.4)]:
            production_schema.validate_edit({'collection':group,'id':group if group in ('camera','world') else 'bottle','field':field,'before':value,'value':value})
        with self.assertRaises(ValueError):production_schema.validate_edit({'collection':'objects','id':'bottle','field':'bevel','before':.1,'value':.2})

if __name__=='__main__':unittest.main()
