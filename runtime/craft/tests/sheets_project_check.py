#!/usr/bin/env python3
"""Real pinned Sheets replay, immutable source and hostile archive qualification."""
import argparse
import copy
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import sheets_source as source, sheets_project as project, sheets_engine as native


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--pack',type=Path,required=True);parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(); pack=args.pack.resolve();fixture=args.fixture.resolve()
    checks=[];refusals=[]
    def check(name,condition):
        checks.append({'name':name,'passed':bool(condition)});(out/'checks.json').write_text(json.dumps(checks,indent=2));assert condition,name
    def refuse(name,call,contains=None):
        try:call()
        except (ValueError,OSError) as error:
            if contains:assert contains in str(error),(name,str(error))
            refusals.append({'name':name,'error':str(error)});(out/'refusals.json').write_text(json.dumps(refusals,indent=2));return
        raise AssertionError(name+' did not refuse')
    binary=pack/'bin/dobe-sheets'; options={'expected_pin':project.PIN,'expected_binary_sha256':source.sha(binary.read_bytes())}
    engine=native.Engine(binary,out,**options)
    original=(fixture/'edited.json').read_bytes();input_path=out/'original.json';input_path.write_bytes(original)
    profile=source.inspect_bytes(original)
    check('full source model and profile inventoried',profile['cell_count']==20 and profile['formula_count']==13 and profile['native_admission_required'] and not profile['calculation_verified'])
    check('native cold model admitted',engine.observe(input_path,original)['complete_model_equal'])
    portable=project.create(original,engine=project.PIN);(out/'original.dobesheets').write_bytes(portable)
    inspected=project.inspect_bytes(portable);check('exact source bytes retained without calculation claim',inspected['members']['original.json']==original and not inspected['calculation_verified'])
    observed=engine.verify_project(portable,out/'original-checkout');check('history-free verification does not invent calculation proof',not observed['calculation_verified'] and observed['native_admission_complete'])
    change={'kind':'cells.edit','edits':[{'sheet':0,'cell':'A2','value':12}]}
    produced=engine.produce(input_path,original,change);result=produced['data'];(out/'revised.json').write_bytes(result)
    check('actual calculation matches independently preserved earlier fixture',result==(fixture/'revision.json').read_bytes())
    check('source and unrelated state preserved',input_path.read_bytes()==original and produced['unrelated_state_preserved'])
    revised=project.append_candidate(portable,source.sha(portable),change,result);(out/'revised.dobesheets').write_bytes(revised)
    checked=project.inspect_bytes(revised);check('candidate history never asserts native proof',checked['history_native_replay_required'] and not checked['calculation_verified'])
    verified=engine.verify_project(revised,out/'revised-checkout');check('actual full history replay establishes calculation',verified['history_replayed']==1 and verified['calculation_verified'])
    calculation=engine.produce(out/'revised.json',result,{'kind':'calculate'})
    twice=project.append_candidate(revised,source.sha(revised),{'kind':'calculate'},calculation['data']);(out/'twice.dobesheets').write_bytes(twice)
    verify_twice=engine.verify_project(twice,out/'twice-checkout');check('two operations replay independently',verify_twice['history_replayed']==2 and project.inspect_bytes(twice)['members']['original.json']==original)
    delivered=engine.export(out/'revised.json',result,'csv');(out/'budget.csv').write_bytes(delivered['data'])
    rows=list(csv.reader(io.StringIO(delivered['data'].decode())));check('independent CSV decoder sees revised total',rows[4][2]=='285.2' and delivered['calculation_verified'])
    preview=engine.export(out/'revised.json',result,'html');(out/'budget.html').write_bytes(preview['data']);check('HTML preserves text safely without font claim',b'&lt;script&gt;' in preview['data'] and not preview['pinned_font_rendering_verified'])
    empty=(fixture/'new.json').read_bytes();(out/'empty.json').write_bytes(empty);empty_csv=engine.export(out/'empty.json',empty,'csv');check('empty CSV is valid bounded output',empty_csv['data']==b'')
    before_calls=engine.calls
    for name,data in [('duplicate',b'{"sheets":[],"sheets":[]}'),('nan',b'{"x":NaN}'),('large-integer',b'{"x":18446744073709551616}'),('invalid-unicode',b'{"x":"\\ud800"}'),('deep',b'['*100+b'0'+b']'*100)]:
        refuse(name,lambda data=data:source.inspect_bytes(data))
    check('static JSON refusals execute no native calls',engine.calls==before_calls)
    for name,mutator in [('unknown',lambda m:m.update(unknown=1)),('count',lambda m:m['sheets'][0]['cells'].update(len=9)),('font',lambda m:m['styles']['styles'][0]['font'].update(name='Other')),('duplicate-sheet',lambda m:m['sheets'][1].update(name='budget')),('style-index',lambda m:m['sheets'][0]['cells']['bands']['0']['rows']['1']['0'].update(style=400))]:
        model=copy.deepcopy(profile['document']);mutator(model);refuse(name,lambda model=model:source.inspect_bytes(source.encoded(model)))
    for name,edits in [('integer-rounding',[{'sheet':0,'cell':'A1','value':2**53+1}]),('oversized-integer',[{'sheet':0,'cell':'A1','value':10**1000}]),('boolean-sheet',[{'sheet':True,'cell':'A1','value':1}]),('conflicting-content',[{'sheet':0,'cell':'A1','value':1,'formula':'2'}]),('oversized-cell',[{'sheet':0,'cell':'BM1','value':1}]),('unknown-format',[{'sheet':0,'cell':'A1','format':{'font':'Other'}}])]:
        refuse(name,lambda edits=edits:source.edits(edits))
    def rewrite(data,mutator):
        state=project.inspect_bytes(data);manifest=copy.deepcopy(state['manifest']);members={k:v for k,v in state['members'].items() if k!='project.json'};mutator(manifest,members);return project.pack(manifest,members)
    def wrong_cache(manifest,members):
        model=source.strict_json(members['state-0001.json']);model['sheets'][0]['cells']['bands']['0']['rows']['4']['2']['value']={'t':'Number','v':12345.0}
        data=source.encoded(model);members['state-0001.json']=data;members['document.json']=data
        manifest['current']=source.sha(data);manifest['history'][0]['after']=source.sha(data)
        for name in ('state-0001.json','document.json'):manifest['members'][name]=project.record(data)
    forged=rewrite(revised,wrong_cache);(out/'forged-cache.dobesheets').write_bytes(forged)
    check('self-consistent forged candidate has no authority',not project.inspect_bytes(forged)['calculation_verified'])
    refuse('forged calculated cache',lambda:engine.verify_project(forged,out/'forged-checkout'),'native history replay differs')
    check('failed native replay removes only fresh checkout',not (out/'forged-checkout').exists() and (out/'revised-checkout').is_dir())
    forged_request=rewrite(revised,lambda m,b:m['history'][0]['operation']['edits'][0].update(value=99))
    refuse('forged request with original result',lambda:engine.verify_project(forged_request,out/'forged-request'),'native history replay differs')
    def hidden_intermediate(m,b):
        model=source.strict_json(b['state-0001.json']);model['sheets'][0]['default_col_width']=90.0;b['state-0001.json']=source.encoded(model)
        digest=source.sha(b['state-0001.json']);m['history'][0]['after']=digest;m['history'][1]['before']=digest;m['members']['state-0001.json']=project.record(b['state-0001.json'])
    hidden=rewrite(twice,hidden_intermediate);before_calls=engine.calls
    refuse('unsupported hidden intermediate',lambda:engine.verify_project(hidden,out/'hidden-intermediate'),'supported native profile')
    check('all history statically admitted before native execution',engine.calls==before_calls and not (out/'hidden-intermediate').exists())
    refuse('wrong member digest',lambda:project.inspect_bytes(rewrite(revised,lambda m,b:m['members']['original.json'].update(sha256='0'*64))))
    refuse('unknown archive member',lambda:project.inspect_bytes(rewrite(revised,lambda m,b:b.update({'unexpected.txt':b'x'}))))
    refuse('wrong engine pin',lambda:project.inspect_bytes(rewrite(revised,lambda m,b:m['engine'].update(source_lock_sha256='0'*64))))
    refuse('stale revision hash',lambda:project.append_candidate(revised,'0'*64,change,result))
    refuse('unknown operation',lambda:project.operation({'kind':'run','script':'x'}))
    (out/'symlink.json').symlink_to(input_path)
    refuse('symlink input',lambda:engine.observe(out/'symlink.json',original),'symbolic links')
    refuse('outside owned attempt',lambda:engine.observe(fixture/'edited.json',original),'inside its attempt')
    input_path.write_bytes(empty);refuse('changed source bytes',lambda:engine.observe(input_path,original),'changed before execution');input_path.write_bytes(original)
    refuse('wrong binary receipt',lambda:native.Engine(binary,out,expected_pin=project.PIN,expected_binary_sha256='0'*64),'binary receipt')
    cancel=[False];cancelled=native.Engine(binary,out,**options,cancelled=lambda:cancel[0]);cancel[0]=True;calls=cancelled.calls
    refuse('cancelled before process',lambda:cancelled.observe(input_path,original),'cancelled');check('cancelled observer starts no process',cancelled.calls==calls)
    stale=source.strict_json(original);stale['sheets'][0]['cells']['bands']['0']['rows']['1']['2']['value']={'t':'Number','v':999.0};stale_bytes=source.encoded(stale);stale_path=out/'stale.json';stale_path.write_bytes(stale_bytes)
    refuse('stale export cache',lambda:engine.export(stale_path,stale_bytes,'csv'),'caches are stale')
    repaired=engine.produce(stale_path,stale_bytes,{'kind':'calculate'});check('explicit calculation repairs stale cache without source changes',source.strict_json(repaired['data'])==source.strict_json(original))
    check('original archive unchanged',project.inspect_bytes(revised)['members']['original.json']==original and (out/'original.dobesheets').read_bytes()==portable)
    evidence={'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':engine.calls+cancelled.calls,'engine':project.PIN,'binary_sha256':options['expected_binary_sha256'],
              'history_native_replay':True,'caller_claims_trusted':False,'public_runtime_registered':False,'installed_qualified':False,'linux_qualified':False}
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))


if __name__=='__main__':main()
