"""Measure preparation usage from an authorized local Codex history snapshot.

Reads only local history. Reports token counters and model metadata, not prompts
or transcripts. API-equivalent costs are a declared pricing scenario, not a bill.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from agent_report import atomic_text

FIELDS=('input_tokens','cached_input_tokens','cache_write_input_tokens',
        'output_tokens','reasoning_output_tokens','total_tokens')


def measure(path, since):
    previous=None;selected=[];model=None;models=set();digest=hashlib.sha256()
    with path.open() as stream:
        for line in stream:
            try:record=json.loads(line)
            except ValueError:continue  # A concurrently appended final line may be partial.
            timestamp=record.get('timestamp')
            if not timestamp:continue
            when=datetime.fromisoformat(timestamp.replace('Z','+00:00'))
            if record.get('type')=='turn_context':
                payload=record['payload'];model=(payload.get('model'),payload.get('effort'),payload.get('service_tier'))
            payload=record.get('payload',{})
            if record.get('type')!='event_msg' or payload.get('type')!='token_count' or not payload.get('info'):continue
            value={'timestamp':timestamp,'counters':payload['info']['total_token_usage'],
                   'reasoning_in_output':payload['info'].get('last_usage_includes_reasoning'),
                   'model':model}
            if when<since:previous=value
            else:selected.append(value);models.add(model)
    if previous is None or not selected:raise ValueError('History must contain counters before and after the requested start')
    increments={name:0 for name in FIELDS};prior=previous['counters']
    for record in selected:
        counters=record['counters']
        for name in FIELDS:
            difference=counters.get(name,0)-prior.get(name,0)
            if difference<0:raise ValueError('Cumulative token counters reset; split the measurement interval')
            increments[name]+=difference
        digest.update(json.dumps(record,sort_keys=True,separators=(',',':')).encode())
        prior=counters
    if increments['total_tokens']!=increments['input_tokens']+increments['output_tokens']:
        raise ValueError('Input/output counters do not reconcile with total tokens')
    if increments['cached_input_tokens']>increments['input_tokens']:
        raise ValueError('Cached input exceeds total input')
    priced=models=={('gpt-6-astra','high',None)} and increments['cache_write_input_tokens']==0 and all(x['reasoning_in_output'] is True for x in selected)
    observed=(10*(increments['input_tokens']-increments['cached_input_tokens'])+
              increments['cached_input_tokens']+50*increments['output_tokens'])/1e6 if priced else None
    normalized=(10*increments['input_tokens']+50*increments['output_tokens'])/1e6 if priced else None
    return {'version':1,'source_history':str(path),'requested_start':since.isoformat(),
            'preceding_counter_timestamp':previous['timestamp'],'through':selected[-1]['timestamp'],
            'selected_counter_records':len(selected),'counter_records_sha256':digest.hexdigest(),
            'models':[list(value) if value else None for value in sorted(models,key=str)],
            'measured_tokens':increments,
            'uncached_input_plus_output_tokens':increments['input_tokens']-increments['cached_input_tokens']+increments['output_tokens'],
            'api_equivalent_observed_cache_usd':observed,'api_equivalent_uncached_normalized_usd':normalized,
            'pricing_basis':'2026-11-19 GPT-6 Astra standard API scenario: uncached input $10/M, cached input $1/M, output $50/M. Reasoning is included in output. This is not Codex billing or an invoice.',
            'scope':'Preparation and implementation in the current thread from the first completion recorded after goal creation. Includes cached context on every recorded request. Separate from benchmark API requests and recurring product costs. The first included request may have begun before goal registration. Later work is excluded until this snapshot is refreshed.',
            'not_included':'Usage not present in this local history, including other conversations and any unrecorded failed requests. The benchmark dispatcher ledger is accounted separately.',
            'provider_requests':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',type=Path,required=True);parser.add_argument('--since',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    since=datetime.fromisoformat(args.since.replace('Z','+00:00'))
    if since.tzinfo is None:raise ValueError('Start timestamp must include a timezone')
    result=measure(args.history.resolve(strict=True),since)
    atomic_text(args.output,json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('through','measured_tokens','api_equivalent_observed_cache_usd','api_equivalent_uncached_normalized_usd')}))


if __name__=='__main__':main()
