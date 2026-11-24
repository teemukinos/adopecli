"""Complete pilot accounting and cohort gates; no network or model requests."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile

WORKFLOWS = ('image', 'video', 'animation', '3d', 'document')
ARMS = ('baseline', 'optimized')


def atomic_text(path, text):
    """Publish a complete private report; preserve the prior file on write failure."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Report destination must not be a symlink')
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(pending, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        pending.unlink(missing_ok=True)


def compare(rows):
    """Failures remain in each arm. Missing pairs never imply a passing gate."""
    workflows = {}
    expected = {(workflow, pair, arm) for workflow in WORKFLOWS for pair in (1, 2) for arm in ARMS}
    actual = [(row['workflow'], row['pair'], row['arm']) for row in rows]
    complete = len(actual) == len(expected) and set(actual) == expected
    for workflow in WORKFLOWS:
        arms = {}
        for arm in ARMS:
            selected = [r for r in rows if r['workflow'] == workflow and r['arm'] == arm]
            known_cost = all(r.get('local_cost_assumption_usd') is not None and not r['uncertain_reserved_usd'] for r in selected)
            arms[arm] = {
                'runs': len(selected),
                'successful_runs': sum(r['state'] == 'completed' for r in selected),
                'coding_tokens': sum(r['coding_tokens'] for r in selected),
                'mean_coding_tokens': sum(r['coding_tokens'] for r in selected) / len(selected) if selected else None,
                'observed_cache_usd': sum(r['observed_cache_usd'] for r in selected),
                'uncached_normalized_usd': sum(r['uncached_normalized_usd'] for r in selected),
                'mean_production_usd': sum(r['observed_cache_usd'] + (r['local_cost_assumption_usd'] or 0) for r in selected) / len(selected) if selected and known_cost else None,
            }
        workflows[workflow] = arms
    tokens = {arm: sum(r['coding_tokens'] for r in rows if r['arm'] == arm) for arm in ARMS}
    reduction = 1 - tokens['optimized'] / tokens['baseline'] if tokens['baseline'] else None
    mean_tokens_pass = complete and all(w['optimized']['mean_coding_tokens'] <= w['baseline']['mean_coding_tokens'] for w in workflows.values())
    cost_known = complete and all(w[arm]['mean_production_usd'] is not None for w in workflows.values() for arm in ARMS)
    mean_cost = {arm: sum(w[arm]['mean_production_usd'] for w in workflows.values()) / len(WORKFLOWS) if cost_known else None for arm in ARMS}
    gates = {
        'two_pairs_each_workflow': complete,
        'all_runs_completed': complete and all(r['state'] == 'completed' for r in rows),
        'aggregate_tokens_reduced_at_least_50_percent': complete and reduction is not None and reduction >= .5,
        'no_workflow_mean_token_increase': mean_tokens_pass,
        'mean_production_cost_does_not_increase': cost_known and mean_cost['optimized'] <= mean_cost['baseline'],
        'all_provider_charges_known': all(not r['uncertain_reserved_usd'] for r in rows),
    }
    return {'workflows': workflows, 'tokens': tokens, 'aggregate_token_reduction': reduction,
            'mean_production_usd': mean_cost, 'gates': gates,
            'missing_pairs': [list(x) for x in sorted(expected - set(actual))],
            'duplicate_pair_entries': len(actual) != len(set(actual)),
            'qualification': 'Numerical gates only. Creative, technical, baseline-fidelity and experimental-control evidence remain separate requirements.'}


def write_audit(store, journal, registry, report, output):
    """Audit the entire shared allowance, including retired and unattributed usage."""
    output = Path(output)
    rows = report['runs']
    cohorts = sorted({row.get('cohort', 'development') for row in rows})
    with store.connect() as db:
        budget = dict(db.execute('SELECT * FROM agent_budgets WHERE id=?', (registry['budget'],)).fetchone())
        calls = [dict(row) for row in db.execute('''SELECT c.*,r.project FROM agent_calls c
            JOIN agent_runs r ON r.id=c.run WHERE r.budget=? ORDER BY c.started''', (registry['budget'],))]
        all_runs = {row[0] for row in db.execute('SELECT id FROM agent_runs WHERE budget=?', (registry['budget'],))}
        attempts = []
        for row in rows:
            for job in row['jobs']:
                for attempt in db.execute('SELECT * FROM attempts WHERE job=? ORDER BY number', (job['id'],)):
                    value = dict(attempt)
                    value.update(run=row['run'], cohort=row.get('cohort', 'development'), workflow=row['workflow'], arm=row['arm'],
                                 revision=job.get('result_revision'),
                                 measurements=[m for m in job['execution_measurements'] if m['attempt'] == value['number']])
                    attempts.append(value)
        committed = journal._spend(db, registry['budget'])
    registered = {row['run'] for row in rows}
    paid = sum(call['charged_microusd'] or 0 for call in calls)
    held = sum(call['reserved_microusd'] for call in calls if call['charged_microusd'] is None)
    totals_match = round(sum(row['observed_cache_usd'] for row in rows) * 1_000_000) == paid
    deliverables=[]
    for row in rows:
        status=journal.status(row['run']);revision=status['context'].get('revision')
        if revision:
            manifest=store.get_revision('local',revision)
            deliverables.append({'run':row['run'],'cohort':row.get('cohort','development'),'workflow':row['workflow'],
                                 'pair':row['pair'],'arm':row['arm'],'state':row['state'],'revision':revision,
                                 'native_artifacts':[entry for entry in manifest['files'] if entry['role']=='native'],
                                 'export_artifacts':[entry for entry in manifest['files'] if entry['role']=='export'],
                                 'native_validation':manifest.get('validation'),
                                 'creative_review':status['context'].get('review')})
    # Keep implementation-agent observations separate from model self-acceptance.
    # Only current revision-bound observations can describe a delivered result.
    current={item['run']:item['revision'] for item in deliverables}
    creative_audits=[]
    for path in sorted(output.glob('visual-audit*.json')):
        value=json.loads(path.read_text())
        for observation in value.get('observations',[]):
            if observation.get('run') in current and observation.get('revision')==current[observation['run']]:
                creative_audits.append({**observation,'audit_file':path.name})
    audit = {
        'version': 1,
        'budget_limit_microusd': budget['limit_microusd'],
        'known_model_microusd': paid,
        'uncertain_reserved_microusd': held,
        'retired_model_microusd': budget['retired_microusd'],
        'committed_microusd': committed,
        'remaining_microusd': budget['limit_microusd'] - committed,
        'accounting_matches_store': totals_match and committed == paid + held + budget['retired_microusd'],
        'unregistered_runs': sorted(all_runs - registered),
        'missing_registered_runs': sorted(registered - all_runs),
        'all_attempts_attributed': all_runs == registered and totals_match and budget['retired_microusd'] == 0,
        'cohorts': {cohort: compare([row for row in rows if row.get('cohort', 'development') == cohort]) for cohort in cohorts},
        'render_attempts': attempts,
        'deliverables': deliverables,
        'creative_audits': creative_audits,
        'failed_or_unfinished_runs': [{k: row.get(k) for k in ('run', 'cohort', 'workflow', 'pair', 'arm', 'state', 'coding_tokens', 'observed_cache_usd', 'uncached_normalized_usd', 'uncertain_reserved_usd', 'local_cost_assumption_usd', 'failure')} for row in rows if row['state'] != 'completed'],
        'preparation_accounting': 'Implementation, source reconciliation, package builds and local verification are preparation overhead. Their complete coding-agent usage is not exposed by this API ledger. Do not report it as zero or combine it with recurring model usage.',
        'preparation_usage_snapshot': json.loads((output.parent/'preparation-usage.json').read_text()) if (output.parent/'preparation-usage.json').is_file() else None,
        'local_cost_basis': '$0.10 per allocated machine-hour, including model waiting. This is an assumption, not measured electricity. CPU seconds and sampled process-group RSS remain separate measured evidence.',
        'baseline_boundary': 'API-level full-document authoring and review history; not an exact replay of the desktop coding-agent harness.',
        'freeze_boundary': 'Baseline source was frozen before implementation. Briefs and rubrics were frozen after initial infrastructure edits but before paid pilot requests or artwork. This differs from the accepted pre-implementation freeze requirement.',
        'pricing_basis': 'Measured provider token usage evaluated at the 2026-11-19 published standard API rate snapshot. This is not invoice reconciliation.',
    }
    atomic_text(output / 'accounting-audit.json', json.dumps(audit, indent=2) + '\n')
    fields = ['run', 'cohort', 'workflow', 'pair', 'arm', 'call', 'state', 'input_tokens', 'cached_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens', 'charged_microusd', 'reserved_microusd', 'provider_request_id', 'started', 'finished', 'error']
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
    by_run = {row['run']: row for row in rows}
    for call in calls:
        row = by_run.get(call['run'], {})
        usage = json.loads(call['usage']) if call['usage'] else {}
        details = usage.get('input_tokens_details', {})
        writer.writerow({**{k: row.get(k) for k in ('cohort', 'workflow', 'pair', 'arm')},
                         **{k: call.get(k) for k in ('run', 'state', 'charged_microusd', 'reserved_microusd', 'provider_request_id', 'started', 'finished', 'error')},
                         'call': call['id'], 'input_tokens': usage.get('input_tokens'), 'output_tokens': usage.get('output_tokens'),
                         'cached_tokens': details.get('cached_tokens'), 'cache_write_tokens': details.get('cache_write_tokens'),
                         'reasoning_tokens': usage.get('output_tokens_details', {}).get('reasoning_tokens')})
    atomic_text(output / 'model-attempts.csv', stream.getvalue())
    atomic_text(output / 'REPORT.md', markdown(audit,rows))
    return audit


def markdown(audit, rows):
    """Human-readable companion; raw attempt receipts remain authoritative."""
    money=lambda value:'unknown' if value is None else f'${value:.6f}'
    number=lambda value:'—' if value is None else f'{value:,.1f}'
    known_local=sum(row['local_cost_assumption_usd'] or 0 for row in rows)
    missing_local=sum(row['local_cost_assumption_usd'] is None for row in rows)
    lines=['# A dope CLI orchestration pilot', '',
           '**Qualification is incomplete.** Numerical cohort gates do not establish creative acceptance or exact baseline fidelity.', '',
           '## Complete allowance accounting', '',
           f"- Model cost from received usage: {money(audit['known_model_microusd']/1e6)}.",
           f"- Pending or uncertain model reservations: {money(audit['uncertain_reserved_microusd']/1e6)}.",
           f"- Retired model cost retained in the shared budget: {money(audit['retired_model_microusd']/1e6)}.",
           f"- Model request allowance: {money(audit['budget_limit_microusd']/1e6)}; remaining after reservations: {money(audit['remaining_microusd']/1e6)}.",
           f'- Known local-cost subtotal: {money(known_local)}; {missing_local} runs have missing elapsed measurements. Missing measurements are not treated as zero in comparison gates.',
           f"- Whole-ledger accounting matches: {audit['accounting_matches_store']}. Every model attempt is attributed: {audit['all_attempts_attributed']}.", '',
           audit['pricing_basis'], '', audit['local_cost_basis'], '',
           'Input plus output tokens are the complete measured API coding-agent tokens. Reasoning is already included in output; the CSV also exposes it separately. Uncached-normalized costs price every input token at the uncached input rate. Cache writes and reads use their observed prices in the observed-cache totals.', '',
           '## Controlled cohorts', '',
           'Every cohort includes all of its failed and unfinished attempts. Earlier cohorts remain in the whole-allowance totals; their costs are not silently removed from the experiment. Compare source/package boundaries before comparing different cohorts.', '']
    for cohort, result in audit['cohorts'].items():
        lines += [f'### {cohort}', '',
                  '| Workflow | Baseline runs | Optimized runs | Mean baseline tokens | Mean optimized tokens | Mean baseline cost | Mean optimized cost |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for workflow, arms in result['workflows'].items():
            base,optimized=arms['baseline'],arms['optimized']
            lines.append(f"| {workflow} | {base['runs']} | {optimized['runs']} | {number(base['mean_coding_tokens'])} | {number(optimized['mean_coding_tokens'])} | {money(base['mean_production_usd'])} | {money(optimized['mean_production_usd'])} |")
        reduction=result['aggregate_token_reduction']
        lines += ['', 'Mean cost includes observed-cache model cost and the same declared local-cost assumption.', '',
                  'Aggregate token reduction: '+('unknown' if reduction is None else f'{100*reduction:.2f}%')+'. This is provisional unless all twenty controlled runs are present.', '']
        lines += [f"- `{name}`: {'PASS' if passed else 'UNMET OR INCOMPLETE'}." for name,passed in result['gates'].items()]
        lines.append('')
    lines += ['## Failed or unfinished attempts', '',
              '| Cohort | Run | Workflow / arm | State | Tokens | Model cost | Reserved | Local cost |',
              '| --- | --- | --- | --- | ---: | ---: | ---: | ---: |']
    for row in audit['failed_or_unfinished_runs']:
        lines.append(f"| {row.get('cohort') or 'development'} | `{row['run']}` | {row['workflow']} / {row['arm']} | {row['state']} | {row['coding_tokens']} | {money(row['observed_cache_usd'])} | {money(row['uncertain_reserved_usd'])} | {money(row['local_cost_assumption_usd'])} |")
    lines += ['', 'Errors, preflight failures, timing, provider request IDs, native job attempts and measured resource records remain in [report.json](report.json) and [accounting-audit.json](accounting-audit.json). Every model call is listed in [model-attempts.csv](model-attempts.csv).', '',
              '## Native artifacts and creative findings', '',
              'The audit links each resulting revision to its native artifacts, exports, native validation receipt and model creative review. Retaining a native file is not by itself proof of every editing operation. Local native reopening/edit probes and the operation matrix define that boundary. The model reviews are not independent owner approval.', '',
              f"Additional revision-bound implementation-agent observations cover {len({x['run'] for x in audit['creative_audits']})} runs. Missing observations are not a creative pass. These observations are preparation overhead and are not fed back into fresh benchmark contexts.", '']
    for observation in audit['creative_audits']:
        unmet=[name for name,passed in observation.get('checks',{}).items() if passed is not True]
        if unmet:
            lines.append(f"- `{observation['run']}`: creative criteria remain unmet or unproven: {', '.join(unmet)}. See [{observation['audit_file']}]({observation['audit_file']}). {observation.get('notes','')}")
    lines += ['',
              '## Boundaries and preparation overhead', '', audit['baseline_boundary'], '', audit['freeze_boundary'], '', audit['preparation_accounting'], '',
              'No image-generation service is used in this optimization pilot. No lower render settings, previous creative answer, hidden provider retry, or omitted failed request is credited as an orchestration saving.', '']
    preparation=audit.get('preparation_usage_snapshot')
    if preparation:
        usage=preparation['measured_tokens']
        lines += ['### Separate implementation usage snapshot', '',
                  f"Authorized local history through {preparation['through']} records **{usage['total_tokens']:,} tokens**: {usage['input_tokens']:,} input (including {usage['cached_input_tokens']:,} cached) and {usage['output_tokens']:,} output. Reasoning is included in output.", '',
                  f"At the declared GPT-6 Astra API scenario, observed-cache cost is {money(preparation['api_equivalent_observed_cache_usd'])}; uncached-normalized cost is {money(preparation['api_equivalent_uncached_normalized_usd'])}. These are API-equivalent implementation costs, not actual Codex charges or recurring product costs. They are separate from the $25 benchmark API request allowance.", '',
                  preparation['scope'], '', preparation['not_included'], '',
                  'See [preparation-usage.json](../preparation-usage.json) for source counter boundaries and pricing assumptions. No private transcript is copied into this report.', '']
    return '\n'.join(lines)
