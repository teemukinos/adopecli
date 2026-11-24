#!/usr/bin/env python3
"""Verify portable solid/solver history with real native replay and cold transfer."""
import argparse
import copy
import json
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import cad_binding as binding,cad_engine,cad_source as source,cad_revision as revision,cad_project as project,cad_parametric as panel,cad_history as history
    exe=args.engine.resolve();checks=[];refusals=[]
    native=cad_engine.Engine(exe,out,expected_pin=binding.PIN,expected_binary_sha256=source.sha(exe.read_bytes()),seconds=300)
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,action,contains=None):
        try:action()
        except ValueError as error:
            if contains is not None:check(label+' intended boundary',contains in str(error))
            refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def current(data):return project.inspect_bytes(data)['members']['document.json']
    def save(name,data):
        path=out/name;path.write_bytes(data);return path
    try:
        native._command('new','metric',out/'metric.json');base=source.strict_json((out/'metric.json').read_bytes())
        authored=panel.create(base,120,80);recipe=authored['recipe']
        authored['document']['read_notes']=['Keep original source note']
        original=(json.dumps(authored['document'],indent=2)+'\n').encode();portable=project.create(original,'json',engine=binding.PIN)
        creation={'kind':'panel.solid','recipe':recipe,'width':120,'height':80,'depth':12,'mesh_handle':None}
        created=project.revise(portable,source.sha(portable),[creation]);created_profile=project.inspect_bytes(created)
        handle=created_profile['current']['document']['model'][-1]['handle']
        check('pure solid history predicts stable geometry but grants no native claim',created_profile['revision_count']==1
              and 'native-recipe-replay' in created_profile['pending_qualification'] and not created_profile['engine_admission_complete'])
        created_report=native.verify_project(created,out/'created')
        check('creation history is reproduced by actual native extrusion',created_report['native_solid_regeneration_verified']
              and [r['kind'] for r in created_report['recipe_observations']]==['panel.solid'] and 'native-recipe-replay' not in created_report['pending_qualification'])
        parameter_edits=[{'kind':'parameter.expression','name':name,'expected':old,'value':value} for name,old,value in (('width','120','150'),('height','80','90'))]
        parameters=project.revise(created,source.sha(created),parameter_edits);parameter_profile=project.inspect_bytes(parameters)
        check('parameter history preserves old geometry and requires solve plus regeneration',parameter_profile['current']['document']['model']==created_profile['current']['document']['model']
              and {'native-constraint-solve','native-solid-regeneration'} <= set(parameter_profile['pending_qualification']))
        parameter_report=native.verify_project(parameters,out/'parameters')
        check('native serialization alone cannot mark revised parameters or mesh solved',not parameter_report['native_constraint_solve_verified']
              and not parameter_report['native_solid_regeneration_verified'] and 'native-constraint-solve' in parameter_report['pending_qualification'])
        parameter_bytes=current(parameters);path=save('parameter-input.json',parameter_bytes)
        solved=native.solve_panel(path,parameter_bytes,recipe,width=150,height=90,mesh_handle=handle)
        captured=history.capture_solve(parameter_bytes,solved['data'],recipe,width=150,height=90,mesh_handle=handle)
        solved_project=project.revise(parameters,source.sha(parameters),[captured]);solved_profile=project.inspect_bytes(solved_project)
        check('solve capture stores exact actual endpoint deltas and preserves every other field',current(solved_project)==solved['data']
              and 1<=len(captured['geometry'])<=4 and 'native-recipe-replay' in solved_profile['pending_qualification'])
        solved_report=native.verify_project(solved_project,out/'solved')
        check('fresh native replay verifies solve but keeps stale mesh pending',solved_report['native_constraint_solve_verified']
              and not solved_report['native_solid_regeneration_verified'] and 'native-solid-regeneration' in solved_report['pending_qualification']
              and 'native-constraint-solve' not in solved_report['pending_qualification'])
        regeneration={**creation,'width':150,'height':90,'depth':20,'mesh_handle':handle}
        final=project.revise(solved_project,source.sha(solved_project),[regeneration]);final_profile=project.inspect_bytes(final)
        final_report=native.verify_project(final,out/'final')
        check('full history preserves exact originals and four typed revisions',final_profile['revision_count']==4 and final_profile['replayed_edits']==5
              and final_profile['members']['original.json']==original and final_profile['members']['baseline.json']==original
              and final_profile['current']['document']['handseed']==created_profile['current']['document']['handseed'])
        check('native replay independently executes both solid operations and the solve',final_report['native_constraint_solve_verified']
              and final_report['native_solid_regeneration_verified'] and [r['kind'] for r in final_report['recipe_observations']]==['panel.solid','panel.solve','panel.solid']
              and not {'native-constraint-solve','native-solid-regeneration','native-recipe-replay'} & set(final_report['pending_qualification']))
        check('native recipe evidence does not imply public admission or publication',not final_report['engine_admission_complete'] and not final_report['durable_publication_qualified'])
        saved=save('parametric-panel.dobecad',final)
        delivery=native.export_panel_obj(out/'final/document.json',current(final),handle,width=150,height=90,depth=20);save('panel.obj',delivery['data'])
        destination=out/'transferred';destination.mkdir()
        other=cad_engine.Engine(exe,destination,expected_pin=binding.PIN,expected_binary_sha256=source.sha(exe.read_bytes()),seconds=300)
        transferred=other.verify_project(saved.read_bytes(),destination/'observed')
        repeated=other.export_panel_obj(destination/'observed/document.json',current(final),handle,width=150,height=90,depth=20)
        check('cold transfer replays actual source operations and yields identical mesh bytes',transferred['current_sha256']==final_report['current_sha256']
              and transferred['observed_revision_sha256']==final_report['observed_revision_sha256'] and repeated['data']==delivery['data'])
        # A geometrically plausible saved candidate is still not native evidence.
        forged=copy.deepcopy(captured)
        target=next(change for change in forged['geometry'] if change['handle']==recipe['entities']['right'])
        target['value']['b']['x']+=5e-7
        plausible=project.revise(parameters,source.sha(parameters),[forged])
        check('pure tolerance check leaves fabricated candidate unverified','native-recipe-replay' in project.inspect_bytes(plausible)['pending_qualification'])
        refused('fabricated solve coordinates despite acceptable dimensions',lambda:native.verify_project(plausible,out/'forged'),'native recipe replay differs')
        check('failed actual replay removes only disposable checkout',not (out/'forged').exists() and (out/'final/original.json').read_bytes()==original)
        lost=copy.deepcopy(solved['document']);lost['read_notes']=[]
        refused('solver capture cannot discard unrelated state',lambda:history.capture_solve(parameter_bytes,revision.encoded(lost),recipe,width=150,height=90,mesh_handle=handle),'unrelated source state')
        for label,edit in [('wrong solid dimensions',{**regeneration,'width':151}),('invalid mesh handle',{**regeneration,'mesh_handle':True}),
                           ('negative depth',{**regeneration,'depth':-1}),('unknown recipe',{**regeneration,'recipe':{**recipe,'version':True}}),
                           ('extra native proof flag',{**regeneration,'native_verified':True})]:
            refused(label,lambda edit=edit:project.revise(solved_project,source.sha(solved_project),[edit]))
        for label,mutate in [('duplicate solve owner',lambda e:e['geometry'].append(copy.deepcopy(e['geometry'][0]))),
                             ('wrong expected geometry',lambda e:e['geometry'][0].update(expected={})),
                             ('non-sketch owner',lambda e:e['geometry'][0].update(handle=handle)),
                             ('changed fixed anchor',lambda e:e['geometry'][0]['value']['a'].update(x=5e-7)),
                             ('unbounded coordinate',lambda e:e['geometry'][0]['value']['b'].update(x=float('inf'))),
                             ('wrong source parameter',lambda e:e.update(width=151)),('missing geometry',lambda e:e.update(geometry=[]))]:
            edit=copy.deepcopy(captured);mutate(edit);refused(label,lambda edit=edit:project.revise(parameters,source.sha(parameters),[edit]))
        refused('compound history cannot compete with primitive edits',lambda:project.revise(portable,source.sha(portable),[creation,parameter_edits[0]]),'separate atomic revision')
        refused('stale portable source hash',lambda:project.revise(final,source.sha(parameters),[regeneration]),'hash is stale')
        refused('unchanged solid cannot create a fake revision',lambda:project.revise(final,source.sha(final),[regeneration]),'changes nothing')
        # A later parameter edit must invalidate the previous solve/mesh evidence.
        later=project.revise(final,source.sha(final),[{'kind':'parameter.expression','name':'width','expected':'150','value':'160'}])
        later_report=native.verify_project(later,out/'later')
        check('later parameter edit cannot inherit earlier solved-state claims',not later_report['native_constraint_solve_verified']
              and not later_report['native_solid_regeneration_verified'] and {'native-constraint-solve','native-solid-regeneration'}<=set(later_report['pending_qualification']))
        check('portable originals and delivered OBJ remain unchanged',saved.read_bytes()==final and (out/'panel.obj').read_bytes()==delivery['data'] and current(solved_project)==solved['data'])
        check('temporary native and history directories are absent',not list(out.glob('.cad-*')) and not list(destination.glob('.cad-*')))
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':native.calls+other.calls,'engine':binding.PIN,
                  'exact_originals':True,'exact_native_recipe_replay':True,'cold_portable_transfer':True,'solid_handle':handle,'revision_count':4,
                  'final_model_sha256':final_profile['current_sha256'],'obj_sha256':source.sha(delivery['data']),
                  'saved_candidates_not_execution_authority':True,'public_runtime_qualified':False,'installed_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');(out/'native-report.json').write_text(json.dumps(final_report,indent=2)+'\n')
        print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':native.calls+other.calls}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':native.calls},indent=2)+'\n');raise


if __name__=='__main__':main()
