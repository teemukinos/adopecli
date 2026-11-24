#!/usr/bin/env python3
"""Cold preservation and actual native-loss counterexamples on owned fixtures."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_container as container


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[]
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def run(source,target):
        result=subprocess.run([str(args.engine.resolve()),'run',str(source),'file.save',json.dumps({'path':str(target)})],capture_output=True,timeout=60)
        index=len(calls);(out/f'{index:02}.stdout').write_bytes(result.stdout);(out/f'{index:02}.stderr').write_bytes(result.stderr)
        calls.append({'source':str(source),'target':str(target),'exit_code':result.returncode})
        check('native save succeeds: '+source.name,result.returncode==0)
    def pack(members,directories):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name in directories:archive.writestr(name,b'')
            for name,data in members.items():archive.writestr(name,data)
        return stream.getvalue()
    try:
        for name in ('paint.mcraft','red.mcraft','atomic.mcraft','embedded.mcraft','portable-source.sbs'):
            original=(args.fixtures/name).read_bytes();source=out/name;source.write_bytes(original)
            before=container.read_native(source);target=out/('cold-'+name);run(source,target)
            after=container.read_native(target);container.check_preservation(before,after)
            check('complete member preservation: '+name,source.read_bytes()==original)
        baseline=container.read_native(out/'paint.mcraft')
        for name,mutate in (
            ('unknown-member',lambda members:members.update({'future-retained.bin':b'original opaque payload'})),
            ('unknown-XML',lambda members:members.update({'package.sbs':members['package.sbs'].replace(b'<package>',b'<package future="retain-me">',1)})),
        ):
            members=dict(baseline['members']);mutate(members);original=pack(members,baseline['directories'])
            source=out/(name+'.mcraft');source.write_bytes(original);target=out/(name+'-saved.mcraft')
            before=container.read_native(source);run(source,target);after=container.read_native(target)
            try:container.check_preservation(before,after)
            except ValueError as error:
                check('native loss detected: '+name,source.read_bytes()==original)
                (out/(name+'-loss.json')).write_text(json.dumps({'refused':True,'reason':str(error),'original_retained':True},indent=2)+'\n')
            else:raise AssertionError('expected native loss was not detected: '+name)
        # Portable sources really contain compressed embedded resources. Native
        # standalone SBS saving changes those into sidecars, so conversion needs
        # a separate explicit contract rather than a false byte-preservation claim.
        material=out/'embedded-portable.mcmat'
        result=subprocess.run([str(args.engine.resolve()),'run',str(out/'embedded.mcraft'),'file.exportMaterial',
            json.dumps({'path':str(material),'size':64})],capture_output=True,timeout=60)
        index=len(calls);(out/f'{index:02}.stdout').write_bytes(result.stdout);(out/f'{index:02}.stderr').write_bytes(result.stderr)
        calls.append({'operation':'file.exportMaterial','exit_code':result.returncode})
        check('native portable material with resources exports',result.returncode==0)
        with zipfile.ZipFile(material) as archive:payload=archive.read('source.sbs')
        source=out/'portable-resource.sbs';source.write_bytes(payload);before=container.read_native(source)
        check('actual embedded native resource decodes exactly',list(before['embedded'].values())==[(args.fixtures/'external.png').read_bytes()])
        target=out/'sidecar-resource.sbs';run(source,target);after=container.read_native(target)
        try:container.check_preservation(before,after)
        except ValueError as error:
            check('native embedded-to-sidecar conversion requires an explicit conversion contract',source.read_bytes()==payload)
            (out/'sidecar-conversion.json').write_text(json.dumps({'conversion_required':True,'reason':str(error),'source_retained':True},indent=2)+'\n')
        else:raise AssertionError('native sidecar conversion unexpectedly retained exact XML bytes')
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'scope':'known local native fixtures and loss detection only; graph/schema/execution admission still required','engine_admission_complete':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls),'evidence':str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
