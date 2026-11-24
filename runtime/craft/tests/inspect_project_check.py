#!/usr/bin/env python3
"""Native report replay, precise annotations and hostile portable-container controls."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import inspect_source as source, inspect_project as project, inspect_engine, inspection


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir();binary=args.engine.resolve();checks=[];refusals=[]
    def check(label,condition):assert condition,label;checks.append(label)
    def refuse(label,fn):
        try:fn()
        except (ValueError,OSError) as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    options={'expected_pin':source.PIN,'expected_binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
    native=inspect_engine.Engine(binary,out,**options)
    original=b"export const answer=42; console.log('</pre><script>forged()</script>');\n"
    report=native.analyze(original,'javascript',source.sha(original));portable=project.create(original,'javascript',report,engine=source.PIN)
    (out/'original.dobeinspect').write_bytes(portable);first=project.inspect_bytes(portable)
    check('native report replays before annotations',native.verify_project(portable)['complete_report_equal'])
    edits=[{'kind':'upsert','id':'ExportAnswer','pointer':'/evidence/result/facts/exports/esm/0','title':'Public export',
            'text':'Keep this export. <img src=x onerror=forged()>','status':'open','severity':'note'}]
    revised=project.revise(portable,source.sha(portable),edits);current=project.inspect_bytes(revised);proof=native.verify_project(revised)
    check('precise annotation preserves source and findings',current['members']['source.bin']==original and current['members']['report.json']==report)
    check('annotation references exact source report and evidence',current['annotations'][0]['input_sha256']==source.sha(original)
          and current['annotations'][0]['report_sha256']==source.sha(report) and current['annotations'][0]['evidence_id']==first['report']['evidence']['id'])
    check('annotation history replayed',proof['annotation_history_replayed']==1)
    update=copy.deepcopy(edits);update[0].update(text='Reviewed the export.',status='resolved')
    second=project.revise(revised,source.sha(revised),update);again=project.inspect_bytes(second);native.verify_project(second)
    check('revision changes only requested annotation state',again['annotations'][0]['status']=='resolved' and again['members']['notes-0001.json']==current['members']['notes-0001.json'])
    removed=project.revise(second,source.sha(second),[{'kind':'remove','id':'ExportAnswer'}]);empty=project.inspect_bytes(removed);native.verify_project(removed)
    check('removal preserves audit history',empty['annotations']==[] and empty['revision_count']==3 and empty['members']['report.json']==report)
    (out/'revised.dobeinspect').write_bytes(revised);(out/'removed.dobeinspect').write_bytes(removed)
    delivered=inspection.delivery(current,'json');view=inspection.delivery(current,'html');(out/'findings.html').write_bytes(view)
    check('JSON delivery separates native and analyst records',json.loads(delivered)['native_report']==current['report'] and json.loads(delivered)['analyst_annotations']==current['annotations'])
    check('HTML renders target strings only as escaped text',b'<script>' not in view and b'<img ' not in view and b'&lt;img' in view
          and b"default-src 'none'" in view and b'&lt;/pre&gt;&lt;script&gt;' in view)
    calls=native.calls
    for label,data in [('duplicate',b'{"a":1,"a":2}'),('nan',b'{"a":NaN}'),('huge-integer',b'{"a":18446744073709551616}'),
                       ('unicode',b'{"a":"\\ud800"}'),('nested',b'['*100+b'0'+b']'*100)]:
        refuse(label,lambda data=data:source.strict_json(data))
    for label,change in [('missing-pointer',dict(edits[0],pointer='/evidence/result/missing')),('escape',dict(edits[0],pointer='/evidence/result/~2')),
                         ('outside-findings',dict(edits[0],pointer='/evidence/environment')),('large-text',dict(edits[0],text='x'*4097)),
                         ('unknown-fields',dict(edits[0],script='execute()')),('status',dict(edits[0],status='approved-safe'))]:
        refuse(label,lambda change=change:project.revise(revised,source.sha(revised),[change]))
    refuse('stale project hash',lambda:project.revise(revised,'0'*64,edits))
    refuse('duplicate edit identifiers',lambda:project.revise(revised,source.sha(revised),edits+edits))
    refuse('missing removal target',lambda:project.revise(revised,source.sha(revised),[{'kind':'remove','id':'Missing'}]))
    check('static refusals execute no native commands',native.calls==calls)
    def rewrite(data,mutate):
        checked=project.inspect_bytes(data);manifest=copy.deepcopy(checked['manifest']);members={k:v for k,v in checked['members'].items() if k!='project.json'}
        mutate(manifest,members);return project.pack(manifest,members)
    def change_report(manifest,members):
        value=source.strict_json(members['report.json']);value['evidence']['summary']='A forged summary not covered by the upstream evidence ID.'
        members['report.json']=source.encoded(value);manifest['report']=source.sha(members['report.json']);manifest['members']['report.json']=project.record(members['report.json'])
    forged=rewrite(portable,change_report);check('self-consistent forged report is only a candidate',project.inspect_bytes(forged)['native_replay_required'])
    refuse('forged display text with valid canonical evidence ID',lambda:native.verify_project(forged))
    def change_notes(manifest,members):
        notes=source.strict_json(members['annotations.json']);notes[0]['text']='Not produced by recorded edit.'
        data=source.encoded(notes)
        for name in ('annotations.json','notes-0001.json'):members[name]=data;manifest['members'][name]=project.record(data)
        manifest['current']=source.sha(data);manifest['history'][0]['after']=source.sha(data)
    refuse('forged annotation result with rewritten hashes',lambda:project.inspect_bytes(rewrite(revised,change_notes)))
    refuse('unknown archive member',lambda:project.inspect_bytes(rewrite(portable,lambda m,b:b.update({'evil.py':b'exec'}))))
    refuse('wrong source pin',lambda:project.inspect_bytes(rewrite(portable,lambda m,b:m['engine'].update(source_lock_sha256='0'*64))))
    refuse('wrong member checksum',lambda:project.inspect_bytes(rewrite(portable,lambda m,b:m['members']['source.bin'].update(sha256='0'*64))))
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        for name,data in first['members'].items():archive.writestr('../'+name if name=='source.bin' else name,data)
    refuse('archive path escape',lambda:project.inspect_bytes(stream.getvalue()))
    for operation,params in [('inspect.analyze',{'asset':'0'*32,'format':'javascript','input_sha256':source.sha(original)}),
                             ('inspect.analyze',{'asset':'/etc/passwd','format':'native','input_sha256':source.sha(original),'permission':'owned-or-authorized'}),
                             ('inspect.import',{'asset':'0'*32,'expected_sha256':source.sha(portable),'input_sha256':source.sha(original),'permission':True})]:
        refuse('public admission '+operation,lambda operation=operation,params=params:inspection.validate(operation,params,None))
    cancel=[False];other=inspect_engine.Engine(binary,out,**options,cancelled=lambda:cancel[0]);cancel[0]=True;before=other.calls
    refuse('cancel before native launch',lambda:other.verify_project(portable));check('cancel starts no extra native command',other.calls==before)
    refuse('incorrect binary receipt',lambda:inspect_engine.Engine(binary,out,expected_pin=source.PIN,expected_binary_sha256='0'*64))
    check('all original artifacts remain exact',(out/'original.dobeinspect').read_bytes()==portable and project.inspect_bytes(revised)['members']['source.bin']==original)
    evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':native.calls+other.calls,'engine':source.PIN,
              'binary_sha256':options['expected_binary_sha256'],'public_runtime_qualified':False,'installed_qualified':False,'linux_qualified':False,'remote_actions':False}
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':evidence['native_calls']}))


if __name__=='__main__':main()
