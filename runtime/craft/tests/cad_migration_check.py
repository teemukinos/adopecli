#!/usr/bin/env python3
"""Qualify an exact CAD pin transition against both real maintained binaries."""
import argparse
import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('old-engine','engine','fixture','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import cad_binding as binding,cad_engine,cad_project as project,cad_source as source,cad_revision as revision,cad_parametric as panel
    old_pin={**binding.PIN,'source_lock_sha256':'46620256f0d0de9e29a4275df32af29f2809885efa8631243ce4a7ff821d60d9'}
    old=cad_engine.Engine(args.old_engine.resolve(),out,expected_pin=old_pin,expected_binary_sha256=source.sha(args.old_engine.read_bytes()),seconds=300)
    new=cad_engine.Engine(args.engine.resolve(),out,expected_pin=binding.PIN,expected_binary_sha256=source.sha(args.engine.read_bytes()),seconds=300)
    checks=[];refusals=[];cases=[]
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,action,contains=None):
        try:action()
        except ValueError as error:
            if contains:check(label+' intended boundary',contains in str(error))
            refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def rewrite(data,mutate):
        checked=project.inspect_bytes(data);manifest=copy.deepcopy(checked['manifest']);members={k:v for k,v in checked['members'].items() if k!='project.json'}
        mutate(manifest,members);return project.pack(manifest,members)
    try:
        old._command('new','metric',out/'metric.json');authored=panel.create(source.strict_json((out/'metric.json').read_bytes()),120,80)
        inputs=[('json',(args.fixture/'cad-project-check-2/json-revised.dobecad').read_bytes()),
                ('dxf',(args.fixture/'cad-project-check-2/dxf-revised.dobecad').read_bytes()),
                ('binary',project.create((args.fixture/'cad-project-check-2/original-binary.dxf').read_bytes(),'dxf',engine=old_pin,
                                         baseline=(args.fixture/'cad-native-check-3/source-model.json').read_bytes())),
                ('parametric',project.create(revision.encoded(authored['document']),'json',engine=old_pin))]
        rich=source.strict_json((args.fixture/'cad-native-check-3/complete.json').read_bytes());rich['handseed']=2049
        inputs.append(('rich',project.create(revision.encoded(rich),'json',engine=old_pin)))
        migrated_cases={}
        for label,data in inputs:
            before=project.inspect_bytes(data);old_report=old.verify_project(data,out/(label+'-old'))
            migrated=project.migrate(data,source.sha(data),engine=binding.PIN);after=project.inspect_bytes(migrated)
            check(label+' migration deterministic with exact predecessor archive',project.migrate(data,source.sha(data),engine=binding.PIN)==migrated
                  and after['members']['predecessor.dobecad']==data and after['current_sha256']==before['current_sha256'])
            check(label+' original baseline and all historical edits remain exact',after['source_sha256']==before['source_sha256']
                  and after['members']['baseline.json']==before['members']['baseline.json'] and after['manifest']['history']==before['manifest']['history'])
            report=new.verify_project(migrated,out/(label+'-new'))
            check(label+' complete actual native model matches across both pins',report['native_migration_verified']
                  and report['current_sha256']==old_report['current_sha256'] and report['observed_revision_sha256']==old_report['observed_revision_sha256'])
            check(label+' migration does not claim full admission or interchange fidelity',not report['engine_admission_complete'] and not report['source_format_fidelity_qualified'])
            (out/(label+'-migrated.dobecad')).write_bytes(migrated);migrated_cases[label]=migrated
            cases.append({'case':label,'predecessor_sha256':source.sha(data),'migrated_sha256':source.sha(migrated),'current_sha256':after['current_sha256'],
                          'revision_count':after['revision_count'],'old_binary_model_equal':True,'new_binary_model_equal':True})
        parametric=migrated_cases['parametric'];creation={'kind':'panel.solid','recipe':authored['recipe'],'width':120,'height':80,'depth':12,'mesh_handle':None}
        extended=project.revise(parametric,source.sha(parametric),[creation]);extended_profile=project.inspect_bytes(extended)
        extended_report=new.verify_project(extended,out/'extended')
        check('new solid history appends after migration without rewriting predecessor',extended_profile['revision_count']==1
              and extended_profile['members']['predecessor.dobecad']==project.inspect_bytes(parametric)['members']['predecessor.dobecad']
              and extended_report['native_solid_regeneration_verified'] and extended_report['native_migration_verified'])
        (out/'migrated-solid.dobecad').write_bytes(extended)
        refused('old engine cannot execute migrated pin',lambda:old.verify_project(extended,out/'wrong-pin'),'pinned engine')
        refused('old pin cannot claim new solid history',lambda:project.revise(inputs[3][1],source.sha(inputs[3][1]),[creation]),'does not support typed panel')
        refused('stale migration hash',lambda:project.migrate(inputs[0][1],'0'*64,engine=binding.PIN),'hash is stale')
        refused('nested migration',lambda:project.migrate(parametric,source.sha(parametric),engine=binding.PIN),'nested migration')
        refused('invented transition',lambda:project.migrate(inputs[0][1],source.sha(inputs[0][1]),engine={**binding.PIN,'source_lock_sha256':'0'*64}),'qualified maintained transition')
        reverse=project.create((args.fixture/'cad-native-check-3/source-model.json').read_bytes(),'json',engine=binding.PIN)
        refused('unqualified reverse transition',lambda:project.migrate(reverse,source.sha(reverse),engine=old_pin),'qualified maintained transition')
        data=migrated_cases['json']
        for label,mutate in [
            ('changed predecessor hash',lambda m,p:m['migration'].update(predecessor_sha256='0'*64)),
            ('boolean prior count',lambda m,p:m['migration'].update(revision_count=True)),
            ('changed prior head',lambda m,p:m['migration'].update(current_sha256='0'*64)),
            ('missing predecessor',lambda m,p:p.pop('predecessor.dobecad')),
            ('wrong recorded source pin',lambda m,p:m['migration']['from_engine'].update(source_lock_sha256='0'*64))]:
            forged=rewrite(data,mutate);refused(label,lambda forged=forged:project.inspect_bytes(forged))
        # An appended no-op prefix cannot hide or replace the actual prior edits.
        def replace_history(manifest,members):
            manifest['history']=[];members['document.json']=members['baseline.json'];manifest['members']['document.json']=project.record(members['document.json'])
        refused('rewritten predecessor history with rehashed current',lambda:project.inspect_bytes(rewrite(data,replace_history)),'predecessor edit history')
        inspected=project.inspect_bytes(data);parent_bytes=inspected['replayed_bytes']-inspected['predecessor']['replayed_bytes']
        with patch.object(project,'MAX_REPLAY',parent_bytes):
            refused('aggregate predecessor replay budget',lambda:project.inspect_bytes(data),'replay exceeds')
        check('original historical archives remain byte exact',inputs[0][1]==(args.fixture/'cad-project-check-2/json-revised.dobecad').read_bytes()
              and inputs[1][1]==(args.fixture/'cad-project-check-2/dxf-revised.dobecad').read_bytes())
        evidence={'passed':True,'checks':checks,'refusals':refusals,'cases':cases,'native_calls':old.calls+new.calls,
                  'old_pin':old_pin,'new_pin':binding.PIN,'exact_predecessor_retained':True,'all_history_preserved':True,
                  'controlled_native_transition_equal':True,'public_runtime_qualified':False,'installed_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':old.calls+new.calls,'cases':len(cases)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':old.calls+new.calls},indent=2)+'\n');raise


if __name__=='__main__':main()
