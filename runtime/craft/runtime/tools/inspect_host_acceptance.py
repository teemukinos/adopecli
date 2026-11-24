#!/usr/bin/env python3
"""Use real macOS replay against explicitly synthetic foreign-host reports.

No Linux binary or inspected target is executed. Original retained fixture bytes
stay unchanged. Run with a read-only package and OS network denial.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4
import zipfile


def sha(data): return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','inputs','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();package=args.package.resolve(strict=True)
    inputs=json.loads(args.inputs.read_text());assert len(inputs)==18
    args.output.mkdir(mode=0o700);out=args.output.resolve();source=Path(__file__).resolve().parents[1]/'studio_runtime'
    sys.path.insert(0,str(package/'lib/dobe/runtime'));import studio_runtime
    modules=('inspect_source','inspect_host','inspect_project','inspect_engine','inspection','inspect_bundle','bundle_replay','bundle')
    for name in modules:
        spec=importlib.util.spec_from_file_location('studio_runtime.'+name,source/(name+'.py'))
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);setattr(studio_runtime,name,module)
    from studio_runtime import inspect_source as data, inspect_host as host, inspect_project as project, inspection, inspect_binding, bundle
    assert host.current()=='macos-aarch64','this fixture qualifies actual macOS execution only'
    binding=inspect_binding.resolve();empty=out/'empty-path';empty.mkdir();os.environ['PATH']=str(empty)
    report={'started':time.time(),'cases':[],'refusals':[],'productionOperations':[],
            'sourceModules':{name:sha((source/(name+'.py')).read_bytes()) for name in modules},
            'nativeExecutableSha256':binding['expected_binary_sha256'],'inputs':inputs,
            'syntheticForeignReports':True,'linuxExecuted':False,'inspectedTargetsExecuted':False,
            'sealedSourceQualified':False,'durableJobs':0}
    def save():(out/'evidence.json').write_text(json.dumps(report,indent=2)+'\n')
    results={}
    for label,info in sorted(inputs.items()):
        raw=Path(info['path']).read_bytes();assert len(raw)==info['bytes'] and sha(raw)==info['sha256']
        with zipfile.ZipFile(Path(info['path'])) as archive:original=archive.read('native/project.dobeinspect')
        checked=project.inspect_bytes(original);native_report=checked['members']['report.json']
        # The original ID came from the real pinned Rust engine. Reconstructing
        # it exactly checks numeric tokens and canonical key/string handling.
        assert host.rehost(native_report,'macos-aarch64')==native_report
        foreign_report=host.rehost(native_report,'linux-x86_64')
        assert host.rehost(foreign_report,'macos-aarch64')==native_report
        foreign=project.create(checked['members']['source.bin'],checked['manifest']['input_format'],foreign_report,engine=checked['manifest']['engine'])
        for step in checked['manifest']['history']:foreign=project.revise(foreign,sha(foreign),step['edits'])
        changed=project.inspect_bytes(foreign)
        for before,after in zip(checked['annotations'],changed['annotations'],strict=True):
            assert {k:v for k,v in before.items() if k not in ('report_sha256','evidence_id')}=={
                k:v for k,v in after.items() if k not in ('report_sha256','evidence_id')}
        root=out/'imports'/label;root.mkdir(parents=True);asset=str(uuid4())
        params={'asset':asset,'permission':'owned-or-authorized','input_sha256':checked['source_sha256'],'expected_sha256':sha(foreign)}
        path=root/inspection.assets('inspect.import',params)[asset];path.parent.mkdir(parents=True);path.write_bytes(foreign)
        result=inspection.execute(root,'inspect.import',params)
        observed=data.strict_json((root/'exports/inspection.json').read_bytes())
        assert observed['complete_report_equal'] is False and observed['host_migration']==host.compare(foreign_report,native_report)
        assert result['validation']['native_report_host_migration']==observed['host_migration']
        assert (root/'native/project.dobeinspect').read_bytes()==foreign
        assert (root/'native/source.bin').read_bytes()==checked['members']['source.bin']
        assert (root/'native/report.json').read_bytes()==foreign_report
        report['cases'].append({'label':label,'originalNativeIdReconstructed':True,'nativeProjectPreserved':True,
                                'annotationSteps':len(checked['manifest']['history']),'result':result,
                                'hostMigration':observed['host_migration']});save()
        results[label]=(root,result,params)

    def package_bundle(root,result,path,transform=None):
        members={row['path']:(root/row['path']).read_bytes() for row in result['artifacts']}
        if transform:transform(members)
        manifest={'schema_version':1,'engine':result['engine'],'files':[
            {'path':row['path'],'role':row['role'],'bytes':len(members[row['path']]),'sha256':sha(members[row['path']])}
            for row in result['artifacts']]}
        with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,value in members.items():archive.writestr(name,value)
            archive.writestr('project.json',data.encoded(manifest))

    root,result,params=results['annotated']
    authorization={'inspect':{k:params[k] for k in ('permission','input_sha256','expected_sha256')}}
    def replay(label,transform=None,expected=None):
        archive=out/(label+'.zip');package_bundle(root,result,archive,transform)
        try:
            observed=bundle.execute(archive,out/label,64<<20,replay_families=('inspect',),replay_authorizations=authorization)
        except ValueError as error:
            assert expected is not None and expected in str(error),(label,str(error))
            report['refusals'].append({'label':label,'message':str(error)[:400]});save();return
        assert expected is None,label
        assert observed['validation']['imported_native_bytes_preserved'] and observed['validation']['current_content_deliveries_replayed']
        report['cases'].append({'label':label,'result':observed});save()

    def receipt(members,change):
        value=data.strict_json(members['exports/inspection.json']);change(value)
        members['exports/inspection.json']=data.encoded(value)

    def foreign_execution(value):
        value.pop('host_migration');value['complete_report_equal']=True
        value['binary_sha256']='c'*64  # Explicitly synthetic historical claim.

    replay('actual-macos-migration-receipt')
    replay('synthetic-linux-execution-receipt',lambda m:receipt(m,foreign_execution))
    replay('forged-migration-digest',lambda m:receipt(m,lambda v:v['host_migration'].update(replayed_report_sha256='0'*64)),
           'retained host migration differs')
    replay('forged-same-host-binary',lambda m:receipt(m,lambda v:v.update(binary_sha256='d'*64)),
           'delivery differs from current native findings')
    def bad_foreign(members):
        def change(value):foreign_execution(value);value['binary_sha256']='not-a-digest'
        receipt(members,change)
    replay('invalid-foreign-binary-claim',bad_foreign,'SHA-256 is invalid')

    checked=project.inspect_bytes((results['original'][0]/'native/project.dobeinspect').read_bytes())
    for label in ('changed-foreign-findings','host-without-recomputed-identity'):
        value=data.strict_json(checked['members']['report.json'])
        if label=='changed-foreign-findings':
            value['evidence']['result']['forged']=True
            changed_report=host.rehost(data.encoded(value),'linux-x86_64')
        else:
            value['evidence']['id']=data.strict_json(host.rehost(checked['members']['report.json'],'macos-aarch64'))['evidence']['id']
            changed_report=data.encoded(value)
        changed=project.create(checked['members']['source.bin'],checked['manifest']['input_format'],changed_report,engine=checked['manifest']['engine'])
        attempt=out/label;attempt.mkdir();asset=str(uuid4())
        value={'asset':asset,'permission':'owned-or-authorized','input_sha256':checked['source_sha256'],'expected_sha256':sha(changed)}
        path=attempt/inspection.assets('inspect.import',value)[asset];path.parent.mkdir();path.write_bytes(changed)
        try:inspection.execute(attempt,'inspect.import',value)
        except ValueError as error:
            assert 'host reconstruction differs' in str(error),str(error)
            assert not (attempt/'native').exists()
            report['refusals'].append({'label':label,'message':str(error),'nativePublicationCreated':False});save()
        else:raise AssertionError(label+' unexpectedly succeeded')

    # Revise and export a real imported foreign-report project while preserving
    # its original source/report bytes and complete prior annotation history.
    original_native=(root/'native/project.dobeinspect').read_bytes();before=project.inspect_bytes(original_native)
    common={'permission':'owned-or-authorized','input_sha256':before['source_sha256']}
    sequence=[('inspect.annotate',{'edits':[{'kind':'upsert','id':'HostTransfer','pointer':'/evidence/result',
        'title':'Transfer check','text':'Editable after host reconstruction.','status':'open','severity':'note'}]}),
        ('inspect.export',{'format':'json'}),('inspect.export',{'format':'html'}),
        ('inspect.bundle',{}),('inspect.inspect',{}),('inspect.annotate',{'edits':[{'kind':'remove','id':'HostTransfer'}]})]
    for operation,extra in sequence:
        value={**common,'expected_sha256':sha((root/'native/project.dobeinspect').read_bytes()),**extra}
        observed=inspection.execute(root,operation,value)
        checked=project.inspect_bytes((root/'native/project.dobeinspect').read_bytes())
        assert checked['members']['source.bin']==before['members']['source.bin'] and checked['members']['report.json']==before['members']['report.json']
        report['productionOperations'].append({'operation':operation,'result':observed});save()
    after=project.inspect_bytes((root/'native/project.dobeinspect').read_bytes())
    assert after['annotations']==before['annotations'] and after['revision_count']==before['revision_count']+2
    for info in inputs.values():assert sha(Path(info['path']).read_bytes())==info['sha256']
    report.update(passed=True,completed=time.time(),nativeCases=len(report['cases']),refusalCases=len(report['refusals']),
                  productionCases=len(report['productionOperations']),originalInputsUnchanged=True)
    save();print('PASS',report['nativeCases'],'host reconstruction cases,',report['refusalCases'],'refusals,',report['productionCases'],'revisions/exports')


if __name__=='__main__':main()
