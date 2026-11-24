"""Local, append-only workflow accounting over the existing durable journal.

Agent calls and native attempts remain authoritative; receipts project them rather
than copying them. Imported usage must be incremental, never cumulative snapshots.
"""
import hashlib
import json
import math
import time
from .store import canonical, identifier, Conflict, NotFound


DOMAINS = ('assistant', 'generation', 'compute')


def events(db, project, kind, *, reverse=False):
    order = 'DESC' if reverse else 'ASC'
    for row in db.execute('SELECT detail FROM project_events WHERE project=? AND kind=? ORDER BY seq ' + order,
                          (project, 'usage.' + kind)):
        yield json.loads(row['detail'])


def append(db, project, kind, value):
    encoded = canonical(value)
    if len(encoded.encode()) > 262144:
        raise ValueError('Usage event exceeds 256 KiB')
    db.execute('INSERT INTO project_events(project,kind,detail,created) VALUES(?,?,?,?)',
               (project, 'usage.' + kind, encoded, time.time()))


def workflow(db, project, key):
    identifier(key)
    result = next((v for v in events(db, project, 'workflow') if v['id'] == key), None)
    if result is None:
        raise NotFound('Usage workflow not found in project')
    return result


def start(store, workspace, project, key, scope, workload, quality_contract, compute_microusd_per_hour=None):
    for value in (key, workload, quality_contract): identifier(value)
    if scope not in ('production', 'development'):
        raise ValueError('Scope must be production or development')
    if compute_microusd_per_hour is not None: integer(compute_microusd_per_hour, 'compute_microusd_per_hour')
    value = dict(id=key, scope=scope, workload=workload, quality_contract=quality_contract,
                 compute_microusd_per_hour=compute_microusd_per_hour)
    with store.transaction() as db:
        store._project(db, workspace, project, write=True)
        old = next((v for v in events(db, project, 'workflow') if v['id'] == key), None)
        if old is not None and old != value: raise Conflict('Workflow key already identifies different metadata')
        if old is None: append(db, project, 'workflow', value)
    return value


def integer(value, name):
    if type(value) is not int or not 0 <= value <= 10**15:
        raise ValueError(name + ' must be a nonnegative integer no greater than 10^15')
    return value


def tokens(value):
    """Cache and reasoning counts are subsets, not additional tokens."""
    if value is None: return None
    if not isinstance(value, dict) or set(value) - {'input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens'}:
        raise ValueError('Unsupported token fields; import incremental input/output usage')
    result = {k: integer(value[k], k) for k in ('input_tokens', 'output_tokens')}
    for key, parent in (('cached_input_tokens', 'input_tokens'), ('reasoning_tokens', 'output_tokens')):
        result[key] = integer(value.get(key, 0), key)
        if result[key] > result[parent]: raise ValueError(key + ' exceeds its parent total')
    return result


def record(store, workspace, project, key, entry):
    allowed = {'id', 'source', 'domain', 'model', 'tokens', 'cost_microusd', 'cost_basis', 'evidence', 'seconds'}
    if not isinstance(entry, dict) or set(entry) - allowed:
        raise ValueError('Unsupported usage fields')
    value = dict(entry)
    for field in ('id', 'source', 'evidence'): identifier(value.get(field))
    if value['source'].startswith('runtime:'): raise ValueError('runtime: is reserved for automatic accounting')
    if value.get('domain') not in DOMAINS: raise ValueError('Invalid usage domain')
    if 'model' in value: identifier(value['model'])
    value['tokens'] = tokens(value.get('tokens'))
    amount = value.get('cost_microusd')
    if amount is not None: integer(amount, 'cost_microusd')
    basis = value.get('cost_basis', 'unknown')
    if basis not in ('billed', 'usage_priced', 'estimated', 'quoted', 'unknown'):
        raise ValueError('Invalid cost basis')
    if (amount is None) != (basis == 'unknown'): raise ValueError('Unknown cost requires null amount and unknown basis')
    if 'seconds' in value and (type(value['seconds']) not in (int, float) or not math.isfinite(value['seconds']) or value['seconds'] < 0):
        raise ValueError('seconds must be finite and nonnegative')
    value.update(workflow=key, cost_microusd=amount, cost_basis=basis, reporting='imported_incremental')
    with store.transaction() as db:
        store._project(db, workspace, project, write=True); workflow(db, project, key)
        # Source IDs are unique across the project, including across workflows.
        old = next((v for v in events(db, project, 'record') if (v['source'], v['id']) == (value['source'], value['id'])), None)
        if old is not None and old != value: raise Conflict('Usage source ID already identifies another entry')
        if old is None: append(db, project, 'record', value)
    return value


def provider_tokens(usage):
    if not usage: return None
    try:
        return tokens({'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'],
                       'cached_input_tokens': usage.get('input_tokens_details', {}).get('cached_tokens', 0),
                       'reasoning_tokens': usage.get('output_tokens_details', {}).get('reasoning_tokens', 0)})
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def receipt(store, workspace, project, key=None, *, details=False):
    if key is not None: identifier(key)
    with store.connect() as db:
        db.execute('BEGIN')  # One consistent view while the worker is writing.
        store._project(db, workspace, project)
        metadata = workflow(db, project, key) if key else None
        rows = []; pending = []; selected_runs = set(); run_workflows = {}; run_evidence = []; preflights = 0
        workflows = {v['id']: v for v in events(db, project, 'workflow')}
        runs = db.execute('SELECT id,specification,state,context FROM agent_runs WHERE project=? ORDER BY id', (project,)).fetchall()
        for run in runs:
            spec = json.loads(run['specification'])
            if key and spec.get('usage_workflow') != key: continue
            selected_runs.add(run['id'])
            run_workflows[run['id']] = spec.get('usage_workflow')
            context = json.loads(run['context'])
            run_evidence.append({'id': run['id'], 'state': run['state'], 'revision': context.get('revision'), 'review': context.get('review')})
            preflights += len(context.get('preflight_attempts', []))
            if run['state'] not in ('completed', 'failed', 'cancelled', 'quality_unmet', 'budget_exhausted'):
                pending.append('agent:' + run['id'])
            for call in db.execute('SELECT id,state,usage,charged_microusd,reserved_microusd,started,finished,provider_request_id FROM agent_calls WHERE run=? ORDER BY number', (run['id'],)):
                if call['state'] in ('sent', 'uncertain'): pending.append('call:' + call['id'])
                rows.append(dict(id='agent:' + call['id'], source='runtime:agent', domain='assistant', model=spec.get('model'), workflow=spec.get('usage_workflow'),
                    state=call['state'], tokens=provider_tokens(json.loads(call['usage']) if call['usage'] else None),
                    provider_usage=json.loads(call['usage']) if call['usage'] else None,
                    cost_microusd=call['charged_microusd'], cost_basis='usage_priced' if call['charged_microusd'] is not None else 'unknown',
                    reserved_microusd=call['reserved_microusd'], provider_request_id=call['provider_request_id'],
                    seconds=call['finished'] - call['started'] if call['finished'] else None))
        linked_jobs = {r['job']: run_workflows[run] for run in selected_runs for r in db.execute('SELECT job FROM agent_steps WHERE run=? AND job IS NOT NULL', (run,))}
        for job in db.execute('SELECT id,request,state FROM jobs WHERE project=? ORDER BY created', (project,)):
            if key and json.loads(job['request']).get('usage_workflow') != key and job['id'] not in linked_jobs: continue
            job_workflow = json.loads(job['request']).get('usage_workflow') or linked_jobs.get(job['id'])
            if job['state'] in ('queued', 'running', 'validating', 'interrupted'): pending.append('job:' + job['id'])
            measurements = {v.get('token'): v for v in (json.loads(r['detail']) for r in db.execute(
                "SELECT detail FROM events WHERE job=? AND kind='execution_measurement' ORDER BY seq", (job['id'],)))}
            for attempt in db.execute('SELECT * FROM attempts WHERE job=? ORDER BY number', (job['id'],)):
                measurement = measurements.get(attempt['token'], {})
                if attempt['finished'] is None or attempt['state'] in ('running', 'validating', 'interrupted'):
                    pending.append('attempt:' + attempt['token'])
                rows.append(dict(id='attempt:' + attempt['token'], source='runtime:native', domain='compute', state=attempt['state'],
                    workflow=job_workflow, tokens=None, cost_microusd=None, cost_basis='unknown', seconds=measurement.get('wall_seconds'), measurement=measurement))
        rows.extend(v for v in events(db, project, 'record') if not key or v['workflow'] == key)
        finished_inspections = set()
        for item in events(db, project, 'inspection'):
            if key and item.get('workflow') != key: continue
            finished_inspections.add(item['id'])
            rows.append(dict(id='ocr:' + item['id'], source='runtime:ocr', domain='compute', tokens=None,
                workflow=item.get('workflow'),
                cost_microusd=None, cost_basis='unknown', seconds=item['elapsed_seconds'], cache_hit=item['cache_hit'],
                status=item['result']['status'], peak_rss_bytes=item['result'].get('peak_rss_bytes') if not item['cache_hit'] else None))
        for item in events(db, project, 'inspection_started'):
            if key and item.get('workflow') != key: continue
            if item['id'] in finished_inspections: continue
            pending.append('ocr:' + item['id'])
            rows.append(dict(id='ocr:' + item['id'], source='runtime:ocr', domain='compute', workflow=item.get('workflow'),
                tokens=None, cost_microusd=None, cost_basis='unknown', seconds=None, status='unsettled'))
        attestations = [v for v in events(db, project, 'assessment') if v['workflow'] == key]
    for row in rows:
        rate = workflows.get(row.get('workflow'), {}).get('compute_microusd_per_hour')
        row['scope'] = workflows.get(row.get('workflow'), {}).get('scope', 'unassigned')
        if rate is not None and row['source'] in ('runtime:native', 'runtime:ocr') and row.get('seconds') is not None:
            row.update(cost_microusd=math.ceil(row['seconds'] * rate / 3600), cost_basis='estimated')
    fingerprint = hashlib.sha256(canonical({'entries': rows, 'pending': pending, 'runs': run_evidence, 'preflights': preflights}).encode()).hexdigest()
    assessment = attestations[-1] if attestations else None
    current = bool(assessment and assessment['fingerprint'] == fingerprint)
    coverage = assessment['coverage'] if current else {d: 'unknown' for d in DOMAINS}
    total_tokens = {k: sum((v.get('tokens') or {}).get(k, 0) for v in rows if v['domain'] == 'assistant')
                    for k in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens')}
    total_tokens['total_tokens'] = total_tokens['input_tokens'] + total_tokens['output_tokens']
    unknown_tokens = sum(v['domain'] == 'assistant' and v.get('tokens') is None for v in rows)
    costs = {basis: sum(v['cost_microusd'] for v in rows if v['cost_basis'] == basis)
             for basis in ('billed', 'usage_priced', 'estimated', 'quoted')}
    unknown_costs = sum(v['cost_microusd'] is None for v in rows)
    complete = not pending and all(coverage[d] in ('complete', 'not_used') for d in DOMAINS)
    result = dict(version=1, project=project, workflow=metadata, currency='USD', fingerprint=fingerprint,
        agent_runs=run_evidence, preflight_attempts=preflights,
        entries=len(rows), pending=pending, assistant_tokens=total_tokens, unknown_assistant_entries=unknown_tokens,
        cost_by_basis_microusd=costs, known_cost_microusd=sum(costs[b] for b in ('billed', 'usage_priced', 'estimated')),
        unknown_cost_entries=unknown_costs, total_cost_microusd=None,
        coverage=coverage, assessment=assessment, assessment_current=current,
        measured_seconds_sum=sum(v['seconds'] for v in rows if v.get('seconds') is not None),
        time_basis='Sum of measured work, not end-to-end latency; overlapping work may overlap.',
        ocr_cache_hits=sum(v.get('cache_hit', False) for v in rows),
        limitations=['External coding-assistant and provider usage requires incremental import.',
                     'Coverage and quality are operator attestations, not independent verification.',
                     'Native compute and OCR costs use an optional explicit hourly estimate; otherwise cost is unknown.',
                     'Input-count preflights are not generated tokens. Uninstrumented preparation, hosted work and UI review need separate incremental entries.'])
    result['tokens_by_domain'] = {d: {k: sum((v.get('tokens') or {}).get(k, 0) for v in rows if v['domain'] == d)
                                      for k in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens')} for d in DOMAINS}
    result['by_scope'] = {scope: {'entries': sum(v['scope'] == scope for v in rows),
        'known_cost_microusd': sum(v['cost_microusd'] for v in rows if v['scope'] == scope and v['cost_basis'] in ('billed', 'usage_priced', 'estimated')),
        'assistant_tokens': sum(v['tokens']['input_tokens'] + v['tokens']['output_tokens'] for v in rows if v['scope'] == scope and v['domain'] == 'assistant' and v['tokens'])}
        for scope in ('production', 'development', 'unassigned')}
    if complete and not unknown_costs and not any(v['cost_basis'] == 'quoted' for v in rows):
        result['total_cost_microusd'] = result['known_cost_microusd']
    if details: result['ledger'] = rows
    return result


def assess(store, workspace, project, key, quality, evidence, coverage):
    if quality not in ('pass', 'fail', 'unreviewed'): raise ValueError('Invalid quality assessment')
    identifier(evidence)
    if not isinstance(coverage, dict) or set(coverage) != set(DOMAINS) or any(v not in ('complete', 'not_used', 'unknown') for v in coverage.values()):
        raise ValueError('Declare assistant, generation and compute coverage as complete, not_used or unknown')
    current = receipt(store, workspace, project, key, details=True)
    if current['pending']: raise Conflict('Workflow still has pending or uncertain work')
    for domain in DOMAINS:
        if coverage[domain] == 'not_used' and any(v['domain'] == domain for v in current['ledger']):
            raise Conflict('Observed usage contradicts not_used coverage')
    value = dict(workflow=key, quality=quality, evidence=evidence, coverage=coverage, fingerprint=current['fingerprint'])
    with store.transaction() as db:
        store._project(db, workspace, project, write=True)
        append(db, project, 'assessment', value)
    return value


def compare(store, workspace, project, baseline, candidate):
    if baseline == candidate: raise ValueError('Baseline and candidate must differ')
    before = receipt(store, workspace, project, baseline); after = receipt(store, workspace, project, candidate)
    reasons = []
    for field in ('scope', 'workload', 'quality_contract'):
        if before['workflow'][field] != after['workflow'][field]: reasons.append('Different ' + field)
    for item in (before, after):
        if item['pending'] or not item['assessment_current'] or item['assessment']['quality'] != 'pass':
            reasons.append('Both workflows need a current passing quality assessment and settled work')
    token_ready = not reasons and all(v['coverage']['assistant'] in ('complete', 'not_used') and not v['unknown_assistant_entries'] for v in (before, after))
    cost_ready = not reasons and all(v['total_cost_microusd'] is not None for v in (before, after))
    def delta(a, b): return {'baseline': a, 'candidate': b, 'saved': a - b, 'saved_percent': (a-b)*100/a if a else None}
    return dict(baseline=baseline, candidate=candidate, quality_basis='Operator-attested equivalent workload and acceptance contract',
        cost_basis_microusd={'baseline': before['cost_by_basis_microusd'], 'candidate': after['cost_by_basis_microusd']},
        assistant_tokens=delta(before['assistant_tokens']['total_tokens'], after['assistant_tokens']['total_tokens']) if token_ready else None,
        cost_microusd=delta(before['total_cost_microusd'], after['total_cost_microusd']) if cost_ready else None,
        unmeasured_reasons=reasons + ([] if token_ready else ['Assistant coverage or quality is incomplete']) + ([] if cost_ready else ['Total cost coverage or quality is incomplete']))
