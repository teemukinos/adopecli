#!/usr/bin/env python3
"""Lossless managed Material preparation, cold snapshots and failure cleanup."""
import argparse
import copy
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_document as document, material_model as model


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','fixtures','graph-fixtures','reference-fixtures','model-fixtures','resource-fixture','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);inputs=out/'inputs';inputs.mkdir();checks=[];calls=[];originals={}
    original_run=document.run
    def tracked(command,*positional,**kwargs):
        record={'command':command,'result':'running'};calls.append(record)
        try:
            result=original_run(command,*positional,**kwargs);record['result']='success';record['stdout_bytes']=len(result);return result
        except BaseException as error:record['result']='failed';record['error']=str(error);raise
    document.run=tracked
    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def retain(path):
        data=path.read_bytes();originals[path]=data;return data
    def xml(path):
        p=document.inspect_bytes(retain(path))['container'];return ET.fromstring(p['members'][p['root']])
    def prepare(label,data):
        source=inputs/(label+'.input');source.write_bytes(data);destination=out/label
        first=document.inspect_bytes(data);report=document.prepare(out,source,destination,args.engine)
        current=document.read_native(destination/'native/document.mcraft');proof=document.preservation(first,current)
        check(label+' exact source members',proof['source_members_equal'] and source.read_bytes()==data)
        check(label+' retained original', (destination/report['source_file']).read_bytes()==data)
        check(label+' independent cold snapshots',report['native_cold_reopen'] and report['native_model_equal'] and report['native_calls']==3
              and report['native_packages_compared']==sorted(current['model']['packages']))
        check(label+' no cook or render admission',not report['cook_performed'] and not report['engine_admission_complete'] and not report['render_qualified'])
        model.check_native(current['model'],current['container']['root'],json.loads((destination/'native/model.json').read_bytes()))
        check(label+' retained complete model',True)
        actual=json.loads((destination/'native/objects.json').read_bytes());check(label+' stable source selectors',actual==document.object_map(current))
        check(label+' fixed output inventory',{p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()}=={
            'native/document.mcraft',report['source_file'],'native/model.json','native/objects.json','native/source-index.json','exports/inspection.json'})
        return destination,report
    def refuse(label,source,destination,**options):
        try:document.prepare(out,source,destination,args.engine,**options)
        except ValueError:checks.append(label+' refused')
        else:raise AssertionError('accepted '+label)
    try:
        fixtures=[('paint',args.fixtures/'paint.mcraft'),('atomic',args.fixtures/'atomic.mcraft'),('embedded',args.fixtures/'embedded.mcraft'),
                  ('bare',args.fixtures/'portable-source.sbs'),('controls',args.graph_fixtures/'rich-controls.mcraft'),
                  ('functions',args.reference_fixtures/'source-default.mcraft'),('instances',args.reference_fixtures/'image-instance.mcraft'),
                  ('resource',args.resource_fixture),('metadata',args.model_fixtures/'rich-metadata.sbs'),
                  ('canvases',args.model_fixtures/'pattern-function-canvases.sbs')]
        for name,path in fixtures:prepare(name,retain(path))
        root=xml(args.fixtures/'paint.mcraft');rng=random.Random(972)
        colors=[[0.,.04045,1.,1.],[-0.,-.5,1e-40,.75],[1e16,-1e16,.5,1e38],
                [0.4539059751422342,0.41043622085578124,0.7616346790648817,1.]]
        colors += [[rng.random() for _ in range(3)]+[1.] for _ in range(24)]
        for index,color in enumerate(colors):
            altered=copy.deepcopy(root);next(altered.iter('constantValueFloat4')).set('v',' '.join(map(str,color)))
            prepare('color-'+str(index),ET.tostring(altered,encoding='utf-8'))
        # The pinned native writer changes an unedited binary32 green channel.
        # Keep the counterexample, then prove managed import does not use it.
        source=inputs/'color-3.input';saved=out/'native-writer-counterexample.mcraft'
        result=subprocess.run([str(args.engine.resolve()),'run',str(source),'file.save',json.dumps({'path':str(saved)})],capture_output=True,timeout=60)
        (out/'native-save.stdout').write_bytes(result.stdout);(out/'native-save.stderr').write_bytes(result.stderr)
        check('counterexample native save succeeds',result.returncode==0)
        before=document.read_native(source);after=document.read_native(saved)
        old=before['model']['packages'][before['container']['root']]['graphs'][0]['nodes'][0]['params']['color']
        new=after['model']['packages'][after['container']['root']]['graphs'][0]['nodes'][0]['params']['color']
        check('native save changes unedited green channel',old['v'][1]!=new['v'][1])
        (out/'color-drift.json').write_text(json.dumps({'source_color':colors[3],'before':old,'native_saved':new,'managed_source_unchanged':True},indent=2)+'\n')
        native=out/'color-3/native/document.mcraft';original=native.read_bytes()
        first=document.prepare(out,native,out/'reimport-one',args.engine)
        second=document.prepare(out,out/'reimport-one/native/document.mcraft',out/'reimport-two',args.engine)
        check('repeated managed reopen stays byte-identical',(out/'reimport-two/native/document.mcraft').read_bytes()==original and first['archive_bytes_equal'] and second['archive_bytes_equal'])
        # A source ID beyond JavaScript's exact integer range stays a string in
        # the public selector map; native reindexing remains explicit.
        altered=copy.deepcopy(root);node=altered.find('content/graph/compNodes/compNode');old_id=node.find('uid').get('v');identity='9007199254740993';node.find('uid').set('v',identity)
        for ref in altered.findall('.//connRef'):
            if ref.get('v')==old_id:ref.set('v',identity)
        dest,_=prepare('large-source-id',ET.tostring(altered,encoding='utf-8'))
        mapping=json.loads((dest/'native/objects.json').read_text());check('large source ID remains exact string',mapping['graphs'][0]['nodes'][0]['id']==identity)
        source=inputs/'paint.input';preserved=source.read_bytes()
        existing=out/'existing';existing.mkdir();(existing/'sentinel').write_text('keep')
        refuse('existing destination',source,existing);check('existing destination preserved',(existing/'sentinel').read_text()=='keep')
        link=inputs/'linked.input';link.symlink_to(source);refuse('source symlink',link,out/'failed-link')
        linkdir=out/'linked-directory';linkdir.symlink_to(inputs,target_is_directory=True);refuse('ancestor symlink',linkdir/'paint.input',out/'failed-ancestor')
        archived=retain(args.fixtures/'linked-package.mcraft')
        prepare('archived-dependency',archived)
        archived_profile=document.inspect_bytes(archived)['container']
        external=inputs/'external.input';external.write_bytes(archived_profile['members'][archived_profile['root']])
        start=len(calls);refuse('external package',external,out/'failed-external');check('external package never reaches native',len(calls)==start)
        malformed=inputs/'bad.input';malformed.write_bytes(b'<package/>');start=len(calls);refuse('malformed input',malformed,out/'failed-schema');check('malformed input never reaches native',len(calls)==start)
        refuse('pre-cancelled',source,out/'failed-cancel',cancelled=lambda:True)
        refuse('expired native deadline',source,out/'failed-timeout',seconds=1e-12)
        snapshots=0
        def after_snapshot(command,*positional,**kwargs):
            nonlocal snapshots
            result=tracked(command,*positional,**kwargs)
            if command[1]=='snapshot':snapshots+=1
            return result
        document.run=after_snapshot
        refuse('cancel after first native snapshot',source,out/'failed-mid-cancel',cancelled=lambda:snapshots>=1)
        check('cancellation follows a completed native snapshot',snapshots==1)
        def mutate_native_input(command,*positional,**kwargs):
            result=tracked(command,*positional,**kwargs)
            if command[1]=='snapshot':Path(command[2]).write_bytes(b'changed')
            return result
        document.run=mutate_native_input;refuse('native input mutation',source,out/'failed-mutation');document.run=tracked
        check('failed preparations leave no completed directories',not any((out/name).exists() for name in ['failed-link','failed-ancestor','failed-external','failed-schema','failed-cancel','failed-timeout','failed-mid-cancel','failed-mutation']))
        check('failure paths preserve original source',source.read_bytes()==preserved)
        for label,data in [('duplicate key',b'{"a":1,"a":2}'),('nonfinite',b'NaN'),('overflow',b'1e39'),('wide integer',b'18446744073709551616'),
                           ('deep JSON',b'['*65+b'0'+b']'*65),('invalid Unicode',b'"\\ud800"')]:
            try:document.snapshot_json(data)
            except ValueError:checks.append(label+' refused')
            else:raise AssertionError('accepted '+label)
        check('full native numeric domain admitted',document.snapshot_json(b'[1e38,-1e38,-0.0,18446744073709551615]')[:2]==[1e38,-1e38])
        check('signed zero retained by snapshot decoder',math.copysign(1,document.snapshot_json(b'-0.0'))==-1)
        check('all upstream fixtures unchanged',all(path.read_bytes()==data for path,data in originals.items()))
        evidence={'passed':True,'checks':checks,'native_calls':sum(c['result']=='success' for c in calls)+1,'native_attempts':len(calls)+1,'managed_calls':len(calls),'color_samples':len(colors),
                  'source_preservation_qualified':True,'engine_admission_complete':False,'runtime_registered':False,'remote_actions':False,
                  'scope':'managed editable preparation and fresh-process cold inspection; native writer color round-trip remains lossy; cooking, typed revisions, external handoff and durable runtime integration pending'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':evidence['native_calls'],'native_attempts':evidence['native_attempts']}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:
        document.run=original_run;(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
