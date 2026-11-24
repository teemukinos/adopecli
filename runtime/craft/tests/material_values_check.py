#!/usr/bin/env python3
"""Native literal/default conversion, finite color bounds and array ordering."""
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
from studio_runtime import material_container as container,material_resources as resources,material_graphs as graphs
from studio_runtime import material_references as references,material_values as values


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--fixtures',type=Path,required=True)
    ap.add_argument('--graph-fixtures',type=Path,required=True);ap.add_argument('--reference-fixtures',type=Path,required=True)
    ap.add_argument('--resource-fixture',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[];originals={}
    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def read(path):
        data=path.read_bytes();originals[path]=data;p=container.inspect_bytes(data);return ET.fromstring(p['members'][p['root']])
    def inspect(data):
        snapshot=container.inspect_bytes(data);pkg=resources.inspect(snapshot);g=graphs.inspect(snapshot,pkg)
        refs=references.inspect(snapshot,pkg,g);return snapshot,values.inspect(g,refs)
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        i=len(calls);(out/f'{i:03}.stdout').write_bytes(result.stdout);(out/f'{i:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode});check('native process '+str(i),result.returncode==0)
        return json.loads(result.stdout)
    def agree(label,root=None,path=None):
        if path is None:
            path=out/(label+'.sbs');path.write_bytes(ET.tostring(root,encoding='utf-8'))
        data=path.read_bytes();snapshot,predicted=inspect(data);info=run('info',path)
        values.check_native(predicted,snapshot['root'],info['nativePackage']);check(label+' complete literal fields and defaults',True)
        check(label+' does not claim procedural comparison',not values.check_native(predicted,snapshot['root'],info['nativePackage'])['procedural_bodies_compared'])
        check(label+' unchanged source',path.read_bytes()==data)
        return snapshot,predicted,info
    def refused(label,root):
        try:inspect(ET.tostring(root,encoding='utf-8'))
        except ValueError:checks.append(label+' refused before native access')
        else:raise AssertionError('accepted '+label)
    try:
        for name,path in [('paint',args.fixtures/'paint.mcraft'),('atomic',args.fixtures/'atomic.mcraft'),
                          ('catalog',args.graph_fixtures/'all-nodes.mcraft'),('controls',args.graph_fixtures/'rich-controls.mcraft'),
                          ('resource',args.resource_fixture),('calls',args.reference_fixtures/'source-default.mcraft'),
                          ('image-instance',args.reference_fixtures/'image-instance.mcraft'),
                          ('nested-instance',args.reference_fixtures/'image-depth-eight.sbs')]:
            read(path);agree(name,path=path)
        root=read(args.fixtures/'paint.mcraft');rng=random.Random(601)
        samples=[[0.,.04045,1.,1.],[-0.,-.5,1e-40,.75],[.1,.3,.7,1.],[1e16,-1e16,.5,1e38]]
        samples.extend([[rng.uniform(-2,10) for _ in range(3)]+[rng.random()] for _ in range(24)])
        for index,color in enumerate(samples):
            altered=copy.deepcopy(root);target=altered.find('content/graph/compNodes/compNode/compImplementation/compFilter/parameters/parameter/paramValue/constantValueFloat4')
            if target is None:target=next(altered.iter('constantValueFloat4'))
            target.set('v',' '.join(map(str,color)));agree('color-'+str(index),altered)
        check('known transfer endpoints',values.linear(0)==0 and values.linear(1)==1)
        check('linear branch preserves signed zero',math.copysign(1,values.linear(-0.))==-1)
        check('alpha never undergoes RGB transfer',values.color({'t':'float4','v':[0.,0.,0.,.5]})['v'][3]==.5)
        # Finite SBS Float4 input can overflow during the nonlinear RGB transfer.
        # The old private engine serializes the nonfinite raw color as null.
        overflow=copy.deepcopy(root);next(overflow.iter('constantValueFloat4')).set('v','2e16 0 0 1')
        refused('nonlinear RGB overflow',overflow)
        path=out/'overflow-native-counterexample.sbs';path.write_bytes(ET.tostring(overflow,encoding='utf-8'))
        observed=run('info',path)['nativePackage']['graphs'][0]['nodes'][0]['params']['color']['v']
        check('actual native nonlinear overflow becomes null',observed[0] is None)
        controls=read(args.graph_fixtures/'rich-controls.sbs')
        color_port=next(p for p in controls.findall('.//paraminput') if p.find('defaultWidget/name').get('v')=='color')
        color_port.find('defaultValue/constantValueFloat4').set('v','2e16 0 0 1');refused('exposed color overflow',controls)
        catalog=read(args.graph_fixtures/'all-nodes.mcraft')
        image_port=next(p for p in catalog.findall('.//paraminput') if p.find('type').get('v') in ('1','2'))
        image_port.find('defaultValue/constantValueFloat4').set('v','2e16 0 0 1');refused('input image default color overflow',catalog)
        # Gradient cells are linear values, unlike node/exposed displayed colors.
        catalog=read(args.graph_fixtures/'all-nodes.mcraft')
        gradient=next(a for a in catalog.findall('.//paramsArray') if a.find('name').get('v')=='gradientrgba')
        cells=gradient.findall('paramsArrayCells/paramsArrayCell');first=next(p for p in cells[0].find('parameters') if p.find('name').get('v')=='value')
        first.find('paramValue/constantValueFloat4').set('v','.5 .5 .5 1')
        _,_,info=agree('linear-gradient',catalog)
        actual=next(n for n in info['nativePackage']['graphs'][0]['nodes'] if n['def']=='gradient_map')['params']['gradient']['v']['keys']
        check('gradient cell stays linear one-half',actual[0]['color']==[.5,.5,.5,1.])
        # Ordinary numeric ordering treats +0 and -0 as equal. Native total_cmp
        # orders -0 first, changing which distinct gradient stop starts the ramp.
        second_position=next(p for p in cells[1].find('parameters') if p.find('name').get('v')=='position')
        second_position.find('paramValue/constantValueFloat1').set('v','-0.0')
        refused('signed-zero gradient reorder',catalog)
        path=out/'signed-zero-native-counterexample.sbs';path.write_bytes(ET.tostring(catalog,encoding='utf-8'))
        info=run('info',path);actual=next(n for n in info['nativePackage']['graphs'][0]['nodes'] if n['def']=='gradient_map')['params']['gradient']['v']['keys']
        check('actual native signed-zero reorder changes first stop',math.copysign(1,actual[0]['pos'])==-1 and actual[0]['color']!=[.5,.5,.5,1.])
        # Already correctly ordered signed zero remains representable.
        first_position=next(p for p in cells[0].find('parameters') if p.find('name').get('v')=='position')
        first_position.find('paramValue/constantValueFloat1').set('v','-0.0');second_position.find('paramValue/constantValueFloat1').set('v','0.0')
        snapshot,predicted,info=agree('ordered-signed-zero',catalog)
        bad=copy.deepcopy(info['nativePackage']);node=next(n for n in bad['graphs'][0]['nodes'] if n['def']=='uniform');node['params']['color']['v'][3]=True
        try:values.check_native(predicted,snapshot['root'],bad)
        except ValueError:checks.append('Boolean substitution in numeric literal refused')
        else:raise AssertionError('Boolean numeric substitution accepted')
        mutations=[('missing graph',lambda p:p['graphs'].clear()),
                   ('duplicate graph',lambda p:p['graphs'].append(copy.deepcopy(p['graphs'][0]))),
                   ('missing node',lambda p:p['graphs'][0]['nodes'].pop()),
                   ('duplicate node',lambda p:p['graphs'][0]['nodes'].__setitem__(0,copy.deepcopy(p['graphs'][0]['nodes'][1]))),
                   ('malformed node',lambda p:p['graphs'][0]['nodes'].__setitem__(0,None)),
                   ('malformed parameter map',lambda p:p['graphs'][0]['nodes'][0].__setitem__('params',None)),
                   ('malformed function map',lambda p:p['graphs'][0]['nodes'][0].__setitem__('functions',[])),
                   ('extra literal',lambda p:p['graphs'][0]['nodes'][0]['params'].__setitem__('unexpected',{'t':'float','v':1.})),
                   ('missing literal',lambda p:p['graphs'][0]['nodes'][0]['params'].clear()),
                   ('malformed exposed input',lambda p:p['graphs'][0]['exposed'].append(None)),
                   ('extra exposed default',lambda p:p['graphs'][0]['exposed'].append({'id':'unexpected','default':{'t':'bool','v':True}}))]
        for label,mutate in mutations:
            bad=copy.deepcopy(info['nativePackage']);mutate(bad)
            try:values.check_native(predicted,snapshot['root'],bad)
            except ValueError:checks.append(label+' refused')
            else:raise AssertionError('accepted '+label)
        check('all original fixtures unchanged',all(path.read_bytes()==data for path,data in originals.items()))
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'color_samples':len(samples),'engine_admission_complete':False,'remote_actions':False,
                  'scope':'literal/default/array prediction and finite nonlinear color conversion; procedural bodies, effective cook clamps and complete native fields remain separate; current host powf ABI qualified on macOS ARM64 only'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
