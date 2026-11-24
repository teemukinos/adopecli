#!/usr/bin/env python3
"""Native function defaults keep editable enum/color metadata and numeric meaning."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_container as container, material_resources as resources, material_graphs as graphs
from studio_runtime import material_references as references, material_function_semantics as semantics
from material_procedural_check import body, child, value


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--fixture',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[]
    original=args.fixture.read_bytes();profile=container.inspect_bytes(original);base=ET.fromstring(profile['members'][profile['root']])
    def check(label, condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        i=len(calls);(out/f'{i:03}.stdout').write_bytes(result.stdout);(out/f'{i:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        check('native process '+str(i),result.returncode==0);return json.loads(result.stdout)
    def fixture(color, connected):
        code=2048 if color else 16;result_code=4 if color else 256;kind='float4' if color else 'int'
        default=[0.,0.,0.,1.] if color else 2
        root=copy.deepcopy(base);source=child(root.find('content'),'function')
        child(source,'identifier','Owned');child(source,'uid',2000000000);child(source,'attributes')
        port=child(child(source,'paraminputs'),'paraminput');child(port,'identifier','choice');child(port,'uid',2000000001)
        child(port,'type',code);value(child(port,'defaultValue'),kind,default)
        attrs=child(port,'attributes');child(attrs,'label','Choice');child(attrs,'description','Editable color or enum default')
        widget=child(port,'defaultWidget');child(widget,'name','color' if color else 'dropdownlist');opts=child(widget,'options')
        options=[('min','0'),('max','1' if color else '2'),('clamp','0')]
        options.append(('valueInterpretation','color') if color else ('parameters','2;0;Zero;1;One;2;Two'))
        for key,text in options:
            option=child(opts,'option');child(option,'name',key);child(option,'value',text)
        getter=(1,'get_float4' if color else 'get_integer1',[],('text','choice'),code)
        spec=[getter,(2,'const_float4',[],('float4',default),2048),(3,'eq',[1,2],None,4)] if color else [getter,(3,'tofloat',[1],None,256)]
        child(source,'type',result_code);child(source,'paramValue').append(body(spec,3))
        # A normal serialized constant is changed into an explicit owned call.
        caller=body([(1,'const_'+('float4' if color else 'int1'),[],(kind,default),code),
                     (2,'const_float1',[],('float',0),result_code)],2)
        node=caller.findall('paramNodes/paramNode')[1];node.find('function').set('v','instance')
        node.find('funcDatas/funcData/name').set('v','instance');holder=node.find('funcDatas/funcData/constantValue');holder.clear();value(holder,'text','pkg:///Owned')
        interface=child(child(node,'materialcraftInterface'),'input');child(interface,'identifier','choice');child(interface,'type',code)
        if connected:
            wire=child(node.find('connections'),'connection');child(wire,'identifier','choice');child(wire,'connRef',1)
        old=next(root.iter('dynamicValue'));parent=next(p for p in root.iter() if old in list(p));parent.remove(old);parent.append(caller)
        return root
    try:
        for color in (False,True):
            for connected in (False,True):
                label=('color' if color else 'enum')+('-connected' if connected else '-default')
                root=fixture(color,connected);path=out/(label+'.sbs');data=ET.tostring(root,encoding='utf-8');path.write_bytes(data)
                snapshot=container.inspect_bytes(data);package=resources.inspect(snapshot);graph=graphs.inspect(snapshot,package)
                refs=references.inspect(snapshot,package,graph)
                for report in refs['functions'].values():
                    # The retained fixture also has a pixel body. Only the two
                    # newly authored value/call bodies use Node scope here.
                    if report['model']['nodes'][0]['id']==1:semantics.inspect_function(report,'node')
                check(label+' admitted operand contracts',True)
                info=run('info',path);cooked=next(n for n in info['graph']['nodes'] if n['def']=='value_processor')['cooked']
                expected={'t':'bool','v':True} if color else {'t':'float','v':2.}
                check(label+' independent native value',cooked['error'] is None and cooked['value']==expected)
                source=next(g for g in info['nativePackage']['graphs'] if g['name']=='Owned')
                check(label+' editable concrete default retained',source['exposed'][0]['default']==({'t':'color','v':[0.,0.,0.,1.]} if color else {'t':'enum','v':2}))
                canonical=out/(label+'.mcraft');cold=out/(label+'-cold.mcraft')
                run('run',path,'file.save',json.dumps({'path':str(canonical)}));run('run',canonical,'file.save',json.dumps({'path':str(cold)}))
                container.check_preservation(container.read_native(canonical),container.read_native(cold));check(label+' complete cold member equality',True)
                reopened=run('info',cold);check(label+' cold numeric result',next(n for n in reopened['graph']['nodes'] if n['def']=='value_processor')['cooked']['value']==expected)
                check(label+' input unchanged',path.read_bytes()==data)
        check('original fixture unchanged',args.fixture.read_bytes()==original)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'engine_admission_complete':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
