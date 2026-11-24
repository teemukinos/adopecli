"""Explain measured API usage without another provider request.

Section character counts and image occurrences are structural diagnostics, not
token estimates. Only provider usage fields are reported as measured tokens.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
from agent_report import atomic_text


def breakdown(root, cohort):
    output=root/'benchmark'
    registry=json.loads((output/'registry.json').read_text())
    rows=[];totals={}
    with sqlite3.connect('file:'+str(output/'state/studio.sqlite3')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for record in registry['runs']:
            if record.get('cohort','development')!=cohort:continue
            state=db.execute('SELECT state FROM agent_runs WHERE id=?',(record['run'],)).fetchone()['state']
            key=record['workflow']+'/'+record['arm'];aggregate=totals.setdefault(key,Counter())
            aggregate['runs']+=1;aggregate['completed_runs']+=state=='completed'
            for call in db.execute('SELECT * FROM agent_calls WHERE run=? ORDER BY number',(record['run'],)):
                usage=json.loads(call['usage']) if call['usage'] else None
                request=json.loads(call['request']).get('request',{})
                stats=Counter(instructions_characters=len(request.get('instructions','')))
                images=set();sections=Counter()
                for message in request.get('input',[]):
                    content=message.get('content',[])
                    if isinstance(content,str):
                        stats['history_answer_characters']+=len(content);continue
                    for part in content:
                        if part.get('type')=='input_image':
                            stats['image_occurrences']+=1
                            images.add(hashlib.sha256(part.get('image_url','').encode()).hexdigest())
                        elif part.get('type')=='input_text':
                            text=part['text'];stats['input_text_characters']+=len(text)
                            try:value=json.loads(text)
                            except (ValueError,TypeError):continue
                            if isinstance(value,dict):
                                for name,item in value.items():
                                    sections[name]+=len(json.dumps(item,separators=(',',':'),ensure_ascii=False))
                stats['distinct_images']=len(images)
                if usage:
                    stats['input_tokens']=usage['input_tokens']
                    stats['output_tokens']=usage['output_tokens']
                    stats['reasoning_tokens']=usage.get('output_tokens_details',{}).get('reasoning_tokens',0)
                    stats['non_reasoning_output_tokens']=stats['output_tokens']-stats['reasoning_tokens']
                    stats['coding_tokens']=stats['input_tokens']+stats['output_tokens']
                stats['calls']=1;stats['usage_unknown_calls']=usage is None
                aggregate.update(stats)
                rows.append({'run':record['run'],'run_state':state,'workflow':record['workflow'],
                             'arm':record['arm'],'pair':record['pair'],'call':call['id'],
                             'call_number':call['number'],'call_state':call['state'],
                             'provider_request_id':call['provider_request_id'],'usage':usage,
                             'measurements':dict(stats),'section_value_characters':dict(sections)})
    result={'version':1,'cohort':cohort,'provider_requests':0,
            'measurement_boundary':'Provider input tokens include text and visual input. Reasoning is part of output tokens. Character counts and image counts are structural diagnostics, not additive token attribution. Active runs are partial; unknown usage is not zero.',
            'totals':{key:dict(value) for key,value in totals.items()},'calls':rows}
    path=output/(cohort+'-token-breakdown.json')
    atomic_text(path,json.dumps(result,indent=2)+'\n')
    return path,result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--cohort',required=True)
    args=parser.parse_args()
    # The cohort is also used in the report filename; disallow path traversal.
    if not args.cohort or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.cohort):
        raise ValueError('Cohort must be a simple name')
    path,result=breakdown(args.root.resolve(strict=True),args.cohort)
    print(json.dumps({'report':str(path),'totals':result['totals']}))


if __name__=='__main__':main()
