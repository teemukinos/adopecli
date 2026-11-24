"""Coordinator journal in the existing runtime database, separate from engine jobs."""
import json
import math
import time
import uuid
from . import capacity

TABLES = ('agent_budgets', 'agent_runs', 'agent_calls', 'agent_steps')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS agent_budgets (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, limit_microusd INTEGER NOT NULL CHECK(limit_microusd>0),
 created REAL NOT NULL, retired_microusd INTEGER NOT NULL DEFAULT 0 CHECK(retired_microusd>=0)
);
CREATE TABLE IF NOT EXISTS agent_runs (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, project TEXT NOT NULL REFERENCES projects(id),
 budget TEXT NOT NULL REFERENCES agent_budgets(id), specification TEXT NOT NULL,
 state TEXT NOT NULL, context TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
 owner TEXT, lease_until REAL, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_calls (
 id TEXT PRIMARY KEY, run TEXT NOT NULL REFERENCES agent_runs(id), number INTEGER NOT NULL,
 state TEXT NOT NULL, reserved_microusd INTEGER NOT NULL CHECK(reserved_microusd>=0),
 charged_microusd INTEGER, request TEXT NOT NULL, response TEXT, usage TEXT,
 provider_request_id TEXT, error TEXT, started REAL NOT NULL, finished REAL,
 UNIQUE(run,number)
);
CREATE TABLE IF NOT EXISTS agent_steps (
 run TEXT NOT NULL REFERENCES agent_runs(id), number INTEGER NOT NULL,
 decision TEXT NOT NULL, job TEXT, revision TEXT, state TEXT NOT NULL,
 result TEXT, started REAL NOT NULL, finished REAL,
 PRIMARY KEY(run,number)
);
'''


def dollars(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('Budget must be a finite positive USD amount')
    amount = math.floor(value * 1_000_000)
    if amount < 1:
        raise ValueError('Budget must be at least one micro-USD')
    return amount


class Journal:
    def __init__(self, store, workspace='local'):
        self.store, self.workspace = store, workspace

    def _run(self, db, run):
        from .store import NotFound
        row = db.execute('SELECT * FROM agent_runs WHERE id=? AND workspace=?', (run, self.workspace)).fetchone()
        if row is None:
            raise NotFound('Agent run not found')
        return row

    def _owned(self, db, run, owner):
        from .store import LeaseLost
        row = self._run(db, run)
        if not owner or row['owner'] != owner or (row['lease_until'] or 0) <= time.time():
            raise LeaseLost('Coordinator lease expired or superseded')
        return row

    def budget(self, limit_usd):
        capacity.admit(self.store.root,self.store.storage_generation)
        budget = uuid.uuid4().hex
        with self.store.transaction() as db:
            db.execute('INSERT INTO agent_budgets(id,workspace,limit_microusd,created) VALUES(?,?,?,?)',
                       (budget, self.workspace, dollars(limit_usd), time.time()))
        return budget

    def create(self, project, specification, limit_usd=None, budget=None):
        from .store import canonical, NotFound
        capacity.admit(self.store.root,self.store.storage_generation)
        if budget is None:
            budget = self.budget(limit_usd)
        run = uuid.uuid4().hex
        with self.store.transaction() as db:
            self.store._project(db, self.workspace, project, write=True)
            if specification.get('usage_workflow') is not None:
                from .usage import workflow
                workflow(db, project, specification['usage_workflow'])
            if not db.execute('SELECT 1 FROM agent_budgets WHERE id=? AND workspace=?', (budget, self.workspace)).fetchone():
                raise NotFound('Agent budget not found')
            now = time.time()
            db.execute('INSERT INTO agent_runs(id,workspace,project,budget,specification,state,context,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (run, self.workspace, project, budget, canonical(specification), 'ready', '{}', now, now))
        return self.status(run)

    def claim(self, run, ttl=45):
        from .store import Conflict
        if not 1 <= ttl <= 300:
            raise ValueError('Invalid coordinator lease duration')
        owner = uuid.uuid4().hex
        with self.store.transaction() as db:
            row = self._run(db, run)
            if row['owner'] and (row['lease_until'] or 0) > time.time():
                raise Conflict('Another coordinator owns this run')
            if row['state'] == 'completed':
                return None
            if row['state'] in ('cancelled', 'failed', 'budget_exhausted', 'uncertain', 'quality_unmet'):
                raise Conflict('Run cannot resume without resolving its terminal or held state')
            if db.execute("SELECT 1 FROM agent_calls WHERE run=? AND state IN ('sent','uncertain')", (run,)).fetchone():
                db.execute("UPDATE agent_runs SET state='uncertain',owner=NULL,lease_until=NULL WHERE id=?", (run,))
                return None
            db.execute('UPDATE agent_runs SET owner=?,lease_until=?,updated=? WHERE id=?',
                       (owner, time.time()+ttl, time.time(), run))
        return owner

    def heartbeat(self, run, owner, ttl=45):
        from .store import LeaseLost
        with self.store.transaction() as db:
            row = self._run(db, run)
            # After machine sleep, renew atomically only if no successor took
            # ownership. All ordinary writes still require an unexpired lease.
            if not owner or row['owner']!=owner:raise LeaseLost('Coordinator lease superseded')
            db.execute('UPDATE agent_runs SET lease_until=?,updated=? WHERE id=?', (time.time()+ttl,time.time(),run))
            return bool(row['cancel_requested'])

    def release(self, run, owner):
        with self.store.transaction() as db:
            db.execute('UPDATE agent_runs SET owner=NULL,lease_until=NULL WHERE id=? AND workspace=? AND owner=?',
                       (run,self.workspace,owner))

    def set_state(self, run, owner, state, context=None):
        from .store import canonical
        if state not in ('ready','deciding','waiting','inspecting','completed','cancelled','failed','budget_exhausted','uncertain','quality_unmet'):
            raise ValueError('Invalid coordinator state')
        with self.store.transaction() as db:
            row = self._owned(db,run,owner)
            db.execute('UPDATE agent_runs SET state=?,context=?,updated=? WHERE id=?',
                       (state,canonical(context) if context is not None else row['context'],time.time(),run))

    def _spend(self, db, budget):
        return db.execute('SELECT retired_microusd FROM agent_budgets WHERE id=?', (budget,)).fetchone()[0] + db.execute('''SELECT COALESCE(SUM(COALESCE(c.charged_microusd,c.reserved_microusd)),0)
            FROM agent_calls c JOIN agent_runs r ON r.id=c.run WHERE r.budget=?''', (budget,)).fetchone()[0]

    def reserve(self, run, owner, request, maximum_microusd):
        from .store import canonical, Conflict
        if type(maximum_microusd) is not int or maximum_microusd <= 0:
            raise ValueError('A positive worst-case reservation is required')
        capacity.admit(self.store.root,self.store.storage_generation)
        with self.store.transaction() as db:
            row = self._owned(db,run,owner)
            if row['cancel_requested']:
                raise Conflict('Run cancellation requested')
            if db.execute("SELECT 1 FROM agent_calls WHERE run=? AND state IN ('sent','uncertain')",(run,)).fetchone():
                raise Conflict('An earlier paid call remains uncertain')
            limit = db.execute('SELECT limit_microusd FROM agent_budgets WHERE id=?',(row['budget'],)).fetchone()[0]
            if self._spend(db,row['budget'])+maximum_microusd > limit:
                context=json.loads(row['context']);context['budget_rejection']={'required_microusd':maximum_microusd,'remaining_microusd':limit-self._spend(db,row['budget']),'at':time.time()}
                db.execute("UPDATE agent_runs SET state='budget_exhausted',context=? WHERE id=?",(canonical(context),run))
                return None
            number = db.execute('SELECT COALESCE(MAX(number),0)+1 FROM agent_calls WHERE run=?',(run,)).fetchone()[0]
            call=uuid.uuid4().hex
            # Durable reservation precedes all network I/O. A crash here is conservatively uncertain.
            db.execute('INSERT INTO agent_calls(id,run,number,state,reserved_microusd,request,started) VALUES(?,?,?,?,?,?,?)',
                       (call,run,number,'sent',maximum_microusd,canonical(request),time.time()))
            db.execute("UPDATE agent_runs SET state='deciding' WHERE id=?",(run,))
        return call

    def preflight(self,run,owner,number=None,result=None):
        """Retain token-count failures separately from paid model attempts."""
        from .store import canonical
        with self.store.transaction() as db:
            row=self._owned(db,run,owner);context=json.loads(row['context'])
            checks=context.setdefault('preflight_attempts',[])
            if number is None:
                checks.append({'endpoint':'responses/input_tokens','state':'sent','started':time.time(),'generation_dispatched':False})
                number=len(checks)
            else:
                checks[number-1].update(result or {},finished=time.time())
            db.execute('UPDATE agent_runs SET context=?,updated=? WHERE id=?',(canonical(context),time.time(),run))
        return number

    def settle(self, run, owner, call, response=None, usage=None, charge=None, request_id=None, error=None):
        from .store import canonical, Conflict
        with self.store.transaction() as db:
            self._owned(db,run,owner)
            row=db.execute("SELECT * FROM agent_calls WHERE id=? AND run=? AND state='sent'",(call,run)).fetchone()
            if row is None:
                raise Conflict('Call already settled or missing')
            if charge is not None and (type(charge) is not int or charge<0 or charge>row['reserved_microusd']):
                raise ValueError('Provider cost exceeds the reserved maximum; retain reservation for reconciliation')
            state='received' if response is not None and charge is not None else 'uncertain'
            db.execute('UPDATE agent_calls SET state=?,response=?,usage=?,charged_microusd=?,provider_request_id=?,error=?,finished=? WHERE id=?',
                       (state,canonical(response) if response is not None else None,canonical(usage) if usage is not None else None,
                        charge,request_id,error,time.time(),call))
            if state=='uncertain':
                db.execute("UPDATE agent_runs SET state='uncertain' WHERE id=?",(run,))

    def step(self, run, owner, number, decision):
        from .store import canonical, Conflict
        with self.store.transaction() as db:
            self._owned(db,run,owner)
            old=db.execute('SELECT * FROM agent_steps WHERE run=? AND number=?',(run,number)).fetchone()
            if old:
                if old['decision']!=canonical(decision): raise Conflict('Decision differs from saved step')
            else:
                db.execute('INSERT INTO agent_steps(run,number,decision,state,started) VALUES(?,?,?,?,?)',
                           (run,number,canonical(decision),'prepared',time.time()))

    def reconcile_received_usage(self,run):
        """Resolve only a retained provider receipt; never infer a missing charge."""
        from .store import Conflict,canonical
        from .agent_provider import cost
        with self.store.transaction() as db:
            row=self._run(db,run)
            if row['owner'] and (row['lease_until'] or 0)>time.time():raise Conflict('Run has an active coordinator')
            calls=db.execute("SELECT * FROM agent_calls WHERE run=? AND state='uncertain'",(run,)).fetchall()
            if not calls:raise Conflict('No uncertain received usage to reconcile')
            context=json.loads(row['context']);evidence=context.setdefault('usage_reconciliations',[])
            checked=[]
            for call in calls:
                if not call['response'] or not call['usage']:raise Conflict('Provider outcome is unknown; keep reservation')
                response=json.loads(call['response']);usage=json.loads(call['usage'])
                if response.get('usage')!=usage:raise Conflict('Stored usage differs from response')
                charge=cost(usage)
                if charge>call['reserved_microusd']:raise Conflict('Actual usage exceeds reservation; explicit billing investigation required')
                checked.append((call,charge))
            for call,charge in checked:
                evidence.append({'call':call['id'],'previous_state':'uncertain','previous_error':call['error'],
                                 'charged_microusd':charge,'reconciled':time.time(),'basis':'retained provider response usage; no network request'})
                db.execute("UPDATE agent_calls SET state='received',charged_microusd=? WHERE id=?",(charge,call['id']))
            db.execute("UPDATE agent_runs SET state='ready',context=?,updated=? WHERE id=?",(canonical(context),time.time(),run))
        return self.status(run)

    def step_result(self, run, owner, number, *, job=None, revision=None, state='waiting', result=None):
        from .store import canonical
        with self.store.transaction() as db:
            self._owned(db,run,owner)
            db.execute('UPDATE agent_steps SET job=COALESCE(?,job),revision=COALESCE(?,revision),state=?,result=?,finished=? WHERE run=? AND number=?',
                       (job,revision,state,canonical(result) if result is not None else None,
                        time.time() if state in ('completed','failed') else None,run,number))

    def cancel(self, run):
        with self.store.transaction() as db:
            row=self._run(db,run)
            if row['state'] not in ('completed','cancelled','failed','quality_unmet','budget_exhausted'):
                db.execute('UPDATE agent_runs SET cancel_requested=1,updated=? WHERE id=?',(time.time(),run))
                if not row['owner'] or (row['lease_until'] or 0) <= time.time():
                    state = 'uncertain' if db.execute("SELECT 1 FROM agent_calls WHERE run=? AND state IN ('sent','uncertain')",(run,)).fetchone() else 'cancelled'
                    db.execute('UPDATE agent_runs SET state=? WHERE id=?',(state,run))
            jobs=[]
            context=json.loads(row['context'])
            for step in db.execute("SELECT number,job FROM agent_steps WHERE run=? AND state IN ('prepared','waiting')",(run,)):
                if step['job']:
                    jobs.append(step['job'])
                else:
                    # Publication may finish before the coordinator persists
                    # its step/job link. The idempotency key closes that crash window.
                    project=context.get('reconstruction_projects',{}).get(str(step['number']),context.get('active_project',row['project']))
                    job=db.execute('SELECT id FROM jobs WHERE workspace=? AND project=? AND idempotency_key=?',
                                   (self.workspace,project,'agent-'+run+'-'+str(step['number']))).fetchone()
                    if job:jobs.append(job['id'])
        for job in jobs: self.store.cancel(self.workspace,job)
        return self.status(run)

    def complete_step(self,run,owner,number,revision,context,result):
        from .store import canonical
        with self.store.transaction() as db:
            self._owned(db,run,owner)
            db.execute("UPDATE agent_steps SET revision=?,state='completed',result=?,finished=? WHERE run=? AND number=?",
                       (revision,canonical(result),time.time(),run,number))
            db.execute("UPDATE agent_runs SET state='inspecting',context=?,updated=? WHERE id=?",
                       (canonical(context),time.time(),run))

    def status(self, run):
        with self.store.connect() as db:
            row=dict(self._run(db,run));row.pop('owner',None);row.pop('lease_until',None)
            for k in ('specification','context'):row[k]=json.loads(row[k])
            row['calls']=[dict(x) for x in db.execute('SELECT * FROM agent_calls WHERE run=? ORDER BY number',(run,))]
            row['steps']=[dict(x) for x in db.execute('SELECT * FROM agent_steps WHERE run=? ORDER BY number',(run,))]
            for x in row['calls']:
                for k in ('request','response','usage'): x[k]=json.loads(x[k]) if x[k] else None
            for x in row['steps']:
                for k in ('decision','result'):x[k]=json.loads(x[k]) if x[k] else None
            row['budget_limit_microusd']=db.execute('SELECT limit_microusd FROM agent_budgets WHERE id=?',(row['budget'],)).fetchone()[0]
            row['budget_committed_microusd']=self._spend(db,row['budget'])
        return row
