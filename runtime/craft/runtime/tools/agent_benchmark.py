#!/usr/bin/env python3
"""Bounded local pilot. One shared $25 ledger, fresh runs, no hidden retries.

The baseline retains full authoring documents and review conversation. Its
creative correction reconstructs from a complete new document, as the frozen
production helper did. Generic deterministic job execution is shared. This is an
API-level orchestration pilot, not a replay of the desktop coding-agent harness.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import wave
from agent_report import atomic_text

HARNESS_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def initialize(package):
    resources=package/'lib/dobe';sys.path.insert(0,str(resources/'runtime'))
    os.environ['STUDIO_BUNDLE_RESOURCES']=str(resources)
    os.environ['PATH']=os.pathsep.join(str(p) for p in (resources/'engines').glob('*/bin'))+os.pathsep+os.environ['PATH']


def baseline_class():
    from studio_runtime.agent import Coordinator, INSTRUCTIONS
    from studio_runtime.store import LeaseLost
    from studio_runtime import agent_provider as provider
    class Baseline(Coordinator):
        # Preserve the original API-level authoring/review context. Context
        # projections are the optimized arm's treatment, not baseline behavior.
        compact_context = False

        def _execute(self,run,owner,status,step):
            if step['decision']['operation'].endswith('.create') and status['context'].get('revision'):
                # The existing full-authoring helper used a fresh project per
                # reconstruction. The Store correctly rejects a second creation
                # against an existing head without a source revision.
                context=copy.deepcopy(status['context']);projects=context.setdefault('reconstruction_projects',{})
                key=str(step['number'])
                if key not in projects:
                    projects[key]=self.store.create_project(self.workspace,'Baseline reconstruction '+run+' '+key)['id']
                context['active_project']=projects[key]
                self.journal.set_state(run,owner,'ready',context)
                status={**status,'context':context,'project':projects[key]}
                # Asset IDs are project scoped. Reuse the approved bytes in
                # the reconstruction project, never an earlier creative answer.
                from studio_runtime.capabilities import asset_inputs
                replacements={}
                for asset in asset_inputs(step['decision']['operation'],step['decision']['parameters']):
                    original=self.store.get_asset(self.workspace,self.journal.status(run)['project'],asset)
                    with self.store.connect() as db:
                        existing=db.execute('SELECT id FROM assets WHERE workspace=? AND project=? AND sha256=? AND name=?',
                            (self.workspace,projects[key],original['sha256'],original['name'])).fetchone()
                    replacements[asset]=existing['id'] if existing else self.store.import_asset(
                        self.workspace,projects[key],self.store.blobs/original['sha256'],original['name'])['id']
                def remap(value):
                    if isinstance(value,list):return [remap(item) for item in value]
                    if isinstance(value,dict):return {k:replacements.get(v,v) if k=='asset' and isinstance(v,str) else remap(v) for k,v in value.items()}
                    return value
                step={**step,'decision':{**step['decision'],'parameters':remap(step['decision']['parameters'])}}
            elif status['context'].get('active_project'):
                # Follow-up inspection/export belongs to the latest rebuilt
                # project, including after a coordinator restart.
                status={**status,'project':status['context']['active_project']}
            return super()._execute(run,owner,status,step)

        def request(self,status):
            request,observed=super().request(status)
            request['instructions']=INSTRUCTIONS.replace('Use guarded minimal edits for corrections. Do not restate unchanged documents.',
                'For your one creative correction, submit a complete newly authored creation document, retaining all unchanged choices. Use the same create operation, not a patch.')
            history=[]
            for call in status['calls']:
                if call['state']=='received':
                    previous=call['request']['request']['input']
                    # The last user message is the new evidence for that turn.
                    history.append(previous[-1])
                    for item in call['response'].get('output',[]):
                        if item.get('type')=='message':
                            text='\n'.join(p['text'] for p in item['content'] if p['type']=='output_text')
                            history.append({'role':'assistant','content':text})
            if history:
                # Do not repeat the brief/contract on every historical turn.
                view=json.loads(request['input'][0]['content'][0]['text'])
                view={k:v for k,v in view.items() if k in ('response_format','evidence','remaining_corrections')}
                request['input'][0]['content'][0]['text']=json.dumps(view,separators=(',',':'))
                request['input']=history+request['input']
            return request,observed

        def run(self,run):
            # Older isolated packages remain valid benchmark artifacts. Newer
            # packages additionally fence contract/package changes on resume.
            if hasattr(self,'require_compatible'):self.require_compatible(run)
            owner=self.journal.claim(run)
            if owner is None:return self.journal.status(run)
            try:
                while True:
                    self.journal.heartbeat(run,owner)
                    status=self.journal.status(run);context=status['context'];spec=status['specification']
                    if status['cancel_requested']:
                        self.journal.set_state(run,owner,'cancelled');break
                    pending=next((s for s in status['steps'] if s['state'] in ('prepared','waiting')),None)
                    if pending:
                        if not self._execute(run,owner,status,pending):break
                        continue
                    if context.get('pending_actions'):
                        decision={**context['pending_actions'][0],'source_revision':context.get('revision'),'deterministic':True}
                        self.journal.step(run,owner,len(status['steps'])+1,decision);continue
                    calls=status['calls']
                    if calls and calls[-1]['number']>context.get('consumed_call',0):
                        decision=provider.decision(calls[-1]['response'])
                    else:
                        if len(calls)>=spec['max_calls']:
                            self.journal.set_state(run,owner,'quality_unmet');break
                        decision=self._call(run,owner,status)
                        if decision is None:break
                        status=self.journal.status(run);calls=status['calls'];context=status['context']
                    new=copy.deepcopy(context);new['consumed_call']=calls[-1]['number']
                    action=decision['action']
                    if action=='submit':
                        operation=decision.get('operation','')
                        source=context.get('revision')
                        if operation.endswith('.create'):
                            creates=sum(s['decision']['operation'].endswith('.create') for s in status['steps'])
                            if creates>spec['max_corrections']:
                                self.journal.set_state(run,owner,'quality_unmet');break
                            new['corrections']=creates
                            source=None
                        elif operation.endswith('.edit'):
                            raise ValueError('Baseline correction must author the full creation document')
                        # Native inspection/export is not a creative correction.
                        # The selected contract and ordinary validators remain authoritative.
                        saved={**decision,'source_revision':source,'model_call':calls[-1]['number']}
                        self.journal.step(run,owner,len(status['steps'])+1,saved);self.journal.set_state(run,owner,'ready',new)
                    elif action=='inspect':
                        from studio_runtime.agent_evidence import inspection_selection
                        new.update(inspection_selection(self.store,self.workspace,context,decision))
                        self.journal.set_state(run,owner,'inspecting',new)
                    elif action=='accept':
                        from studio_runtime.agent_evidence import collect
                        observed=collect(self.store,self.workspace,context['revision'],context.get('selection'),context.get('inspection'),context.get('crops'))
                        if context.get('inspection') and not context['inspection']['passed']:
                            new['review']=decision;self.journal.set_state(run,owner,'quality_unmet',new);break
                        if not observed['images'] or set(decision.get('checks',{}))!=set(spec['acceptance']) or any(v is not True for v in decision['checks'].values()):
                            raise ValueError('Acceptance requires current previews and every criterion')
                        if not isinstance(decision.get('findings'),list) or not isinstance(decision.get('limitations'),list):
                            raise ValueError('Acceptance requires findings and limitations')
                        new['review']=decision;self.journal.set_state(run,owner,'completed',new);break
                    else:
                        new['review']=decision;self.journal.set_state(run,owner,'quality_unmet',new);break
            except LeaseLost:
                raise
            except Exception as exc:
                status=self.journal.status(run)
                if status['state'] not in ('uncertain','budget_exhausted'):
                    context=status['context'];context['failure']={'class':type(exc).__name__,'message':str(exc)[:1000]}
                    self.journal.set_state(run,owner,'failed',context)
            finally:self.journal.release(run,owner)
            return self.journal.status(run)
    return Baseline


def freeze_audio(root):
    path=root/'frozen/timing-audio.wav'
    if path.exists():return path
    rate=48000
    with wave.open(str(path),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate)
        # Deterministic timing fixture, not a reused creative output.
        data=[]
        for n in range(rate*6):
            t=n/rate;envelope=min(1,t/.02,(6-t)/.02)
            data.append(struct.pack('<h',round(3200*envelope*math.sin(2*math.pi*220*t))))
        stream.writeframes(b''.join(data))
    (root/'frozen/inputs-manifest.json').write_text(json.dumps({path.name:hashlib.sha256(path.read_bytes()).hexdigest()},indent=2)+'\n')
    return path


def report(store,journal,registry,out):
    rows=[]
    for record in registry['runs']:
        status=journal.status(record['run']);tokens=0;paid=0;normalized=0;reserved=0
        calls=[]
        for call in status['calls']:
            usage=call['usage'] or {};tokens+=usage.get('input_tokens',0)+usage.get('output_tokens',0)
            paid+=call['charged_microusd'] or 0
            if call['charged_microusd'] is None:reserved+=call['reserved_microusd']
            normalized+=usage.get('input_tokens',0)*10+usage.get('output_tokens',0)*50
            calls.append({k:call[k] for k in ('id','number','state','usage','charged_microusd','reserved_microusd','provider_request_id','started','finished','error')})
        jobs=[]
        linked={step['job']:step['number'] for step in status['steps'] if step['job']}
        # A process may die after durable submission but before saving the step
        # link. Such native attempts still belong in the accounting report.
        projects={status['project'],*status['context'].get('reconstruction_projects',{}).values()}
        with store.connect() as db:
            submitted=[dict(row) for row in db.execute('SELECT id,project FROM jobs WHERE workspace=? AND idempotency_key LIKE ? ORDER BY created',
                ('local','agent-'+record['run']+'-%')) if row['project'] in projects]
        for job_id in dict.fromkeys([*linked,*(job['id'] for job in submitted)]):
            job=store.get_job('local',job_id);events=[];cursor=0
            while True:
                page=store.events('local',job_id,cursor)
                if not page:break
                events.extend(page);cursor=page[-1]['seq']
            job['agent_step']=linked.get(job_id)
            job['recovered_from_idempotency_key']=job_id not in linked
            job['execution_measurements']=[event['detail'] for event in events if event['kind']=='execution_measurement']
            jobs.append(job)
        elapsed=record.get('elapsed_seconds')
        rows.append({**record,'state':status['state'],'coding_tokens':tokens,'observed_cache_usd':paid/1e6,
                     'uncached_normalized_usd':normalized/1e6,'uncertain_reserved_usd':reserved/1e6,
                     'local_cost_assumption_usd':elapsed*.1/3600 if elapsed is not None else None,
                     'compute_cost_basis':'$0.10/hour allocated machine time, assumed; includes model waiting; no electricity measurement',
                     'model_attempts':calls,'preflight_attempts':status['context'].get('preflight_attempts',[]),'jobs':jobs,'inspection':status['context'].get('inspection'),'review':status['context'].get('review'),'failure':status['context'].get('failure')})
    totals={arm:sum(x['coding_tokens'] for x in rows if x['arm']==arm) for arm in ('baseline','optimized')}
    result={'version':1,'runs':rows,'total_known_model_usd':sum(x['observed_cache_usd'] for x in rows),
            'total_uncertain_reserved_usd':sum(x['uncertain_reserved_usd'] for x in rows),'tokens':totals,
            'aggregate_reduction':1-totals['optimized']/totals['baseline'] if totals['baseline'] else None,
            'qualification':'API-level pilot only; creative acceptance and temporal inspection require separate evidence',
            'all_attempts_included':True}
    atomic_text(out/'report.json',json.dumps(result,indent=2)+'\n')
    from agent_report import write_audit
    write_audit(store,journal,registry,result,out)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--package',type=Path,required=True)
    p.add_argument('--execute',action='store_true',help='Dispatch explicitly approved paid benchmark requests')
    p.add_argument('--limit-runs',type=int,default=20);p.add_argument('--cohort',default='development');a=p.parse_args()
    output=a.root.resolve()/'benchmark';output.mkdir(exist_ok=True)
    if not a.execute:return execute(a)
    fd=os.open(output/'dispatcher.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return execute(a)
    finally:os.close(fd)


def execute(a):
    initialize(a.package.resolve())
    from studio_runtime.store import Store
    from studio_runtime.agent_store import Journal
    from studio_runtime.agent import Coordinator,specification
    from studio_runtime import agent_catalog
    root=a.root.resolve();out=root/'benchmark';out.mkdir(exist_ok=True)
    store=Store(out/'state');journal=Journal(store);path=out/'registry.json';audio=freeze_audio(root)
    if path.exists():registry=json.loads(path.read_text())
    else:
        registry={'budget':journal.budget(25),'runs':[]};atomic_text(path,json.dumps(registry,indent=2)+'\n')
    if not a.execute:
        result=report(store,journal,registry,out)
        print(json.dumps({'report':str(out/'REPORT.md'),'runs':len(result['runs']),
                          'known_model_usd':result['total_known_model_usd'],
                          'uncertain_reserved_usd':result['total_uncertain_reserved_usd']}));return
    manifest=json.loads((root/'frozen/manifest.json').read_text())
    for name,digest in manifest.items():
        if hashlib.sha256((root/'frozen'/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen benchmark input changed')
    worker=subprocess.Popen([str(a.package/'bin/a-dope-cli'),'--state',str(store.root),'worker'],stdout=(out/'worker.log').open('a'),stderr=subprocess.STDOUT)
    try:
        for workflow in ('image','video','animation','3d','document'):
            available=agent_catalog.availability(workflow)
            if not available['available']:raise ValueError(workflow+' unavailable: '+available.get('reason',''))
            frozen=json.loads((root/'frozen'/(workflow+'.json')).read_text())
            for pair,order in enumerate((('baseline','optimized'),('optimized','baseline')),1):
                for arm in order:
                    if sum(r.get('benchmark_eligible',True) and r.get('cohort','development')==a.cohort for r in registry['runs'])>=a.limit_runs:return
                    if any(r['workflow']==workflow and r['pair']==pair and r['arm']==arm and r.get('benchmark_eligible',True) and r.get('cohort','development')==a.cohort for r in registry['runs']):continue
                    project=store.create_project('local',f'{workflow} {pair} {arm}')['id'];assets=[]
                    if workflow=='video':
                        asset=store.import_asset('local',project,audio);assets=[{'id':asset['id'],'description':'6-second 48kHz mono timing audio; use at -12dB'}]
                    spec=specification(frozen['brief'],workflow,frozen['acceptance'],assets)
                    run=journal.create(project,spec,budget=registry['budget'])['id']
                    record={'run':run,'project':project,'workflow':workflow,'pair':pair,'arm':arm,'started':time.time(),'benchmark_eligible':True,'cohort':a.cohort}
                    record['package']=str(a.package.resolve())
                    record['package_manifest_sha256']=hashlib.sha256((a.package/'lib/dobe/bundle.json').read_bytes()).hexdigest()
                    record['harness_sha256']=HARNESS_SHA256
                    registry['runs'].append(record);atomic_text(path,json.dumps(registry,indent=2)+'\n')
                    start=time.monotonic();coordinator=(Coordinator if arm=='optimized' else baseline_class())(store)
                    coordinator.run(run);record['elapsed_seconds']=time.monotonic()-start
                    atomic_text(path,json.dumps(registry,indent=2)+'\n');result=report(store,journal,registry,out)
                    print(json.dumps({k:result['runs'][-1][k] for k in ('workflow','pair','arm','state','coding_tokens','observed_cache_usd','failure')}),flush=True)
                    if result['runs'][-1]['state'] in ('uncertain','budget_exhausted','failed'):return
    finally:
        worker.terminate();worker.wait(timeout=20);report(store,journal,registry,out)

if __name__=='__main__':main()
