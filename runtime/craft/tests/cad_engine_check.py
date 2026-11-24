#!/usr/bin/env python3
"""Check receipt-bound CAD originals, history, native solving and cancellation.

The disposable distribution layout is not an installed release, public model
admission, complete interchange fidelity or durable runtime qualification.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine','fixture','output'): parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--staged',action='store_true'); args=parser.parse_args()
    out=args.output.resolve(); resources=out/'fixture/DobeCLI/lib/dobe'; runtime=resources/'runtime'
    if not args.staged:
        out.mkdir(parents=True)
        shutil.copytree(Path(__file__).resolve().parents[1]/'runtime/studio_runtime',runtime/'studio_runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(args.engine.resolve().parent.parent,resources/'engines/cad')
        metadata_bytes=(resources/'engines/cad/engine.json').read_bytes(); metadata=json.loads(metadata_bytes)
        receipt={'schema_version':1,'product':'dobe','distribution':'dobe-cli','platform':'macos-arm64',
                 'qualification':'disposable-layout-not-installed','release_signed':False,
                 'components':[{'name':'dobe-cad','version':metadata['version'],'source_lock_sha256':metadata['source_lock_sha256'],
                                'engine_manifest_sha256':hashlib.sha256(metadata_bytes).hexdigest()}],'files':{}}
        for path in resources.rglob('*'):
            if path.is_file(): receipt['files'][path.relative_to(resources.parent.parent).as_posix()]={'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        (resources/'bundle.json').write_text(json.dumps(receipt,sort_keys=True)+'\n')
        command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--staged']
        for key in ('engine','fixture','output'): command.extend(['--'+key,str(getattr(args,key).resolve())])
        raise SystemExit(subprocess.run(command,timeout=300).returncode)
    sys.path.insert(0,str(runtime))
    from studio_runtime import cad_binding as binding,cad_engine,cad_project as project,cad_source as source,cad_revision as revision,cad_parametric,animate_process
    work=out/'attempt'; work.mkdir(); checks=[];refusals=[];children=[];started=time.monotonic()
    receipt=resources/'bundle.json'; receipt_bytes=receipt.read_bytes(); engine_bytes=args.engine.read_bytes()
    original=(args.fixture/'original.dxf').read_bytes(); baseline=(args.fixture/'source-model.json').read_bytes(); model=source.strict_json(baseline)
    real_popen=animate_process.subprocess.Popen; state={'cancel':False,'native_live':False}
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def popen(command,*values,**keywords):
        child=real_popen(command,*values,**keywords); children.append({'pid':child.pid,'command':list(command),'process':child})
        if state['cancel'] and 'encode' in command:
            end=time.monotonic()+10
            while child.poll() is None and time.monotonic()<end:
                with real_popen(['/bin/ps','-p',str(child.pid),'-o','comm='],stdout=subprocess.PIPE) as probe:
                    name=probe.communicate(timeout=5)[0].decode().strip()
                if name==str(resources/'engines/cad/bin/dobe-cad') and child.poll() is None:
                    state['native_live']=True;break
                time.sleep(.005)
            if not state['native_live']:
                child.kill();child.wait();raise AssertionError('did not observe live CAD executable')
        return child
    def engine(**overrides):return cad_engine.Engine(root=work,**(binding.resolve()|overrides))
    def refused(label,action,contains,launches=0):
        count=len(children)
        try:action()
        except ValueError as error:
            check(label+' refused at intended boundary',contains in str(error));check(label+' exact launch count',len(children)-count==launches)
            refusals.append({'case':label,'error':str(error),'children':launches})
        else:raise AssertionError('accepted '+label)
    def rewrite(data,mutate):
        checked=project.inspect_bytes(data);metadata=copy.deepcopy(checked['manifest']);members={k:v for k,v in checked['members'].items() if k!='project.json'}
        mutate(metadata,members);return project.pack(metadata,members)
    try:
        with patch.object(animate_process.subprocess,'Popen',popen):
            os.environ['PATH']=str(out/'untrusted-bin');os.environ['STUDIO_BUNDLE_RESOURCES']=str(out/'untrusted-resources')
            bound=binding.resolve();pin=bound['expected_pin'];executable=bound['executable']
            check('fixed runtime path and compiled source lock ignore environment',executable==resources/'engines/cad/bin/dobe-cad' and pin==binding.PIN and binding.available())
            base=project.create(original,'dxf',engine=pin,baseline=baseline)
            edit={'kind':'geometry.set','handle':256,'expected':model['model'][0]['kind'],'set':{'b':{'x':120,'y':0,'z':0}}}
            first=project.revise(base,source.sha(base),[edit]);second=project.revise(first,source.sha(first),[{'kind':'text.replace','handle':258,'expected':'Workshop / 100 mm','value':'Workshop / 120 mm'}])
            (out/'two-revisions.dobecad').write_bytes(second);checked=project.inspect_bytes(second)
            native=engine();report=native.verify_project(second,work/'verified')
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            check('actual original parser binds full baseline and every typed intermediate',report['native_calls']==8 and report['native_baseline_bound']
                  and report['baseline_model_equal'] and report['current_model_equal'] and report['original_native_model_equal']
                  and report['observed_revision_sha256']==[row['after'] for row in checked['manifest']['history']] and report['native_cold_reopens']==6)
            check('originals, baseline, current and history stay byte exact',all((work/'verified'/name).read_bytes()==value for name,value in checked['members'].items())
                  and report['original_bytes_unchanged'] and report['resource_bytes_equal'])
            check('observation does not grant public admission or format/render/publication fidelity',not any(report[k] for k in ('engine_admission_complete','source_format_fidelity_qualified','rendered_fidelity_qualified','durable_publication_qualified'))
                  and not {'native-full-model-comparison','native-baseline-binding'} & set(report['pending_qualification'])
                  and 'complete-dxf-semantics' in report['pending_qualification'])
            json_project=project.create(baseline,'json',engine=pin); json_report=engine().verify_project(json_project,work/'json-original')
            check('exact JSON source is observed without DXF export normalization',json_report['native_calls']==4 and json_report['native_baseline_bound'] and json_report['original_native_model_equal'] is None)
            binary=(args.fixture.parent/'cad-project-check-2/original-binary.dxf').read_bytes()
            binary_project=project.create(binary,'dxf',engine=pin,baseline=baseline)
            binary_report=engine().verify_project(binary_project,work/'binary-original')
            check('binary DXF full baseline is also bound to actual native reader',binary_report['native_calls']==6 and binary_report['original_native_model_equal'])
            rich=source.strict_json((args.fixture/'complete.json').read_bytes());rich['handseed']=2049
            rich['blocks']['OwnedBlock']['xrefPath']='/never/open/reference.dwg'
            rich_bytes=revision.encoded(rich);rich_project=project.create(rich_bytes,'json',engine=pin)
            rich_report=engine().verify_project(rich_project,work/'rich-source')
            check('native cold observation preserves paper, blocks, foreign data, raster bytes and passive xref',rich_report['baseline_model_equal']
                  and rich_report['current_model_equal'] and rich_report['resource_bytes_equal']
                  and (work/'rich-source/document.json').read_bytes()==rich_bytes)
            ticks=[0]
            def checkout_cancelled():
                ticks[0]+=1;return ticks[0]>=3
            refused('cancel partial portable checkout',lambda:project.checkout(work,work/'partial',second,cancelled=checkout_cancelled),'checkout cancelled')
            check('partial checkout cleanup retains existing owner files',not (work/'partial').exists() and (work/'verified/original.dxf').read_bytes()==original)
            check('temporary history and native outputs do not enter portable checkout',not list(work.glob('.cad-*')) and len(list((work/'verified').iterdir()))==4)
            # A project can store an unrelated DXF candidate but cannot verify it.
            unrelated=copy.deepcopy(model);unrelated['model'][0]['kind']['b']['x']=999.0
            forged=project.create(original,'dxf',engine=pin,baseline=revision.encoded(unrelated))
            refused('unrelated DXF candidate',lambda:native.verify_project(forged,work/'forged'),'complete predicted model',1)
            check('failed source binding removes only fresh checkout',not (work/'forged').exists() and (work/'verified/original.dxf').read_bytes()==original)
            # Compare all history states, not only a final model that later edits fix.
            bad_text={'kind':'text.replace','handle':258,'expected':'Workshop / 100 mm','value':'Temporary'}
            interim=project.revise(json_project,source.sha(json_project),[bad_text])
            final=project.revise(interim,source.sha(interim),[{**bad_text,'expected':'Temporary','value':'Workshop / 100 mm'}])
            historical=engine().verify_project(final,work/'round-trip-history')
            check('intermediate changes remain observed even when final model equals baseline',historical['native_calls']==6 and len(historical['observed_revision_sha256'])==2)
            # Build a native metric base through the fixed known command for the recipe.
            native._command('new','metric',work/'metric.json');metric=source.strict_json((work/'metric.json').read_bytes())
            panel=cad_parametric.create(metric,120,80);panel_bytes=revision.encoded(panel['document'])
            panel_project=project.create(panel_bytes,'json',engine=pin)
            parameter=project.revise(panel_project,source.sha(panel_project),[{'kind':'parameter.expression','name':'width','expected':'120','value':'150'}])
            parameter_profile=project.inspect_bytes(parameter);parameter_report=engine().verify_project(parameter,work/'parameter')
            check('model observation alone does not claim parameters are solved','native-constraint-solve' in parameter_report['pending_qualification'])
            solve=engine().solve_panel(work/'parameter/document.json',parameter_profile['members']['document.json'],panel['recipe'],width=150,height=80)
            (out/'solve-report.json').write_text(json.dumps({k:v for k,v in solve.items() if k!='data'},indent=2)+'\n')
            check('receipt-bound actual solve independently checks geometry and two cold reopens',solve['measurements']['closed_rectangle_verified']
                  and solve['measurements']['maximum_endpoint_error_mm']<=1e-6 and solve['native_cold_reopens']==2
                  and solve['document']['model']!=panel['document']['model'] and not solve['durable_publication_qualified'])
            refused('wrong requested solved dimension',lambda:native.solve_panel(work/'parameter/document.json',parameter_profile['members']['document.json'],panel['recipe'],width=151,height=80),'source parameter differs',1)
            refused('wrong binary receipt',lambda:engine(expected_binary_sha256='0'*64),'differs from verified receipt')
            refused('wrong revision receipt',lambda:engine(expected_pin={**pin,'source_revision':'0'*40}),'differs from verified source pin')
            refused('wrong lock receipt',lambda:engine(expected_pin={**pin,'source_lock_sha256':'0'*64}),'differs from verified source pin')
            refused('unbounded deadline',lambda:engine(seconds=float('inf')),'time budget')
            refused('pre-cancelled constructor',lambda:engine(cancelled=lambda:True),'cancelled')
            refused('existing checkout',lambda:native.verify_project(second,work/'verified'),'fresh destination')
            refused('external checkout',lambda:native.verify_project(second,out/'external'),'inside its attempt')
            alias=work/'alias';alias.symlink_to(work/'verified',target_is_directory=True)
            refused('symlink checkout ancestor',lambda:native.verify_project(second,alias/'child'),'symbolic links')
            refused('changed model input',lambda:native.observe(work/'verified/document.json',baseline),'changed before observation')
            refused('external model input',lambda:native.observe(args.fixture/'source-model.json',baseline),'inside its attempt')
            refused('boolean reopen count',lambda:native.observe(work/'verified/document.json',checked['members']['document.json'],cold_reopens=True),'reopen count')
            wrong_pin=rewrite(second,lambda m,p:m['engine'].update(source_revision='0'*40))
            refused('project cannot select another engine',lambda:native.verify_project(wrong_pin,work/'wrong-pin'),'pinned engine')
            check('foreign engine pin refused before checkout',not (work/'wrong-pin').exists())
            unknown=copy.deepcopy(model);unknown['futureProperty']='must remain owned'
            unknown_project=project.create(revision.encoded(unknown),'json',engine=pin)
            refused('unknown field cannot disappear in native model',lambda:native.verify_project(unknown_project,work/'unknown'),'native operation failed',1)
            check('native rejection cleans disposable checkout and scratch',not (work/'unknown').exists() and not list(work.glob('.cad-*')))
            native.deadline=time.monotonic()-1
            refused('expired shared deadline',lambda:native.verify_project(second,work/'expired'),'timed out')
            check('expired attempt creates no checkout',not (work/'expired').exists())
            for label,mutate in [
                ('binary receipt mismatch',lambda m:m['files']['lib/dobe/engines/cad/bin/dobe-cad'].update(sha256='0'*64)),
                ('component source lock mismatch',lambda m:m['components'][0].update(source_lock_sha256='0'*64)),
                ('duplicate engine component',lambda m:m['components'].append(copy.deepcopy(m['components'][0]))),
                ('unqualified Linux platform',lambda m:m.update(platform='linux-x86_64'))]:
                damaged=json.loads(receipt_bytes);mutate(damaged);receipt.write_text(json.dumps(damaged));count=len(children)
                try:check(label+' unavailable with no process launch',not binding.available() and len(children)==count)
                finally:receipt.write_bytes(receipt_bytes)
            copied=work/'copied-engine';(copied/'bin').mkdir(parents=True);shutil.copy2(executable,copied/'bin/dobe-cad')
            shutil.copy2(executable.parent.parent/'engine.json',copied/'engine.json');mutated=engine(executable=copied/'bin/dobe-cad')
            with (copied/'bin/dobe-cad').open('r+b') as stream:
                stream.seek(-1,os.SEEK_END);byte=stream.read(1);stream.seek(-1,os.SEEK_END);stream.write(bytes([byte[0]^1]))
            refused('post-receipt binary mutation',lambda:mutated.observe(work/'verified/document.json',checked['members']['document.json']),'changed after receipt verification')
            linked=work/'engine-alias';linked.symlink_to(executable.parent.parent,target_is_directory=True)
            refused('symlink executable ancestor',lambda:engine(executable=linked/'bin/dobe-cad'),'symbolic links')
            # A redirected executable ancestor must fail even if its target inode is unchanged.
            redirect=work/'redirect-engine';(redirect/'bin').mkdir(parents=True)
            shutil.copy2(executable,redirect/'bin/dobe-cad');shutil.copy2(executable.parent.parent/'engine.json',redirect/'engine.json')
            redirected=engine(executable=redirect/'bin/dobe-cad');saved=work/'retained-engine';redirect.rename(saved);redirect.symlink_to(saved,target_is_directory=True)
            refused('redirected executable ancestor after receipt',lambda:redirected.observe(work/'verified/document.json',checked['members']['document.json']),'symbolic links')
            large=copy.deepcopy(model);large['model']=[]
            for index in range(30000):
                entity=copy.deepcopy(model['model'][0]);entity['handle']=256+index;large['model'].append(entity)
            large['handseed']=30256;large_bytes=revision.encoded(large);large_path=work/'large.json';large_path.write_bytes(large_bytes)
            cancellable=engine();cancellable.cancelled=lambda:state['native_live'];state['cancel']=True
            refused('cancel confirmed live native encoder',lambda:cancellable.observe(large_path,large_bytes),'cancelled',1)
            state['cancel']=False
            check('live cancellation preserves input and removes scratch',state['native_live'] and large_path.read_bytes()==large_bytes and not list(work.glob('.cad-*')))
            for child in children:
                check('native child '+str(child['pid'])+' reaped',child['process'].poll() is not None)
                try:os.killpg(child['pid'],0)
                except ProcessLookupError:pass
                else:raise AssertionError('process group survived '+str(child['pid']))
            check('external fixtures and original binary remain unchanged',args.engine.read_bytes()==engine_bytes and (args.fixture/'original.dxf').read_bytes()==original and (args.fixture/'source-model.json').read_bytes()==baseline)
            evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':len(children),'engine':pin,
                      'original_dxf_bound':True,'all_intermediate_revisions_observed':True,'receipt_bound_panel_solve':True,
                      'maximum_endpoint_error_mm':solve['measurements']['maximum_endpoint_error_mm'],'live_native_cancellation':state['native_live'],
                      'process_groups_gone':True,'distribution_layout_fixture':True,'installed_qualification':False,'public_admission_qualified':False,
                      'remote_actions':False,'seconds':time.monotonic()-started}
            (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
            print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':len(children)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals},indent=2)+'\n');raise
    finally:
        receipt.write_bytes(receipt_bytes)
        (out/'children.json').write_text(json.dumps([{k:v for k,v in child.items() if k!='process'}|{'exit_code':child['process'].poll()} for child in children],indent=2)+'\n')


if __name__=='__main__':main()
