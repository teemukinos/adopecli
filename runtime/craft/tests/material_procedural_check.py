#!/usr/bin/env python3
"""Offline procedural structure, native model and real cook qualification."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_container as container, material_procedural as procedural
from studio_runtime import material_function_catalog as catalog


def child(parent, tag, value=None):
    return ET.SubElement(parent,tag,{} if value is None else {'v':str(value)})


def value(parent, kind, data):
    tag={'float':'Float1','float2':'Float2','float3':'Float3','float4':'Float4',
         'int':'Int32','int2':'Int2','int3':'Int3','int4':'Int4','bool':'Bool','text':'String'}[kind]
    if isinstance(data,list):data=' '.join(map(str,data))
    if isinstance(data,bool):data=int(data)
    child(parent,'constantValue'+tag,data)


def body(spec, result):
    root=ET.Element('dynamicValue')
    if result is not None:child(root,'rootnode',result)
    holder=child(root,'paramNodes')
    for identity,op,inputs,setting,code in spec:
        n=child(holder,'paramNode');child(n,'uid',identity);child(n,'function',op);child(n,'type',code)
        child(child(n,'GUILayout'),'gpos',f'{identity*140} 0 0');wires=child(n,'connections')
        for port,source in zip(catalog.INPUTS[op],inputs):
            if source is not None:
                wire=child(wires,'connection');child(wire,'identifier',port);child(wire,'connRef',source)
        if setting is not None:
            d=child(child(n,'funcDatas'),'funcData');child(d,'name',op);value(child(d,'constantValue'),*setting)
    return root


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--fixture',type=Path,required=True)
    ap.add_argument('--upstream',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[]
    original=args.fixture.read_bytes()
    with zipfile.ZipFile(args.fixture) as z:base=ET.fromstring(z.read('package.sbs'))
    def check(label,ok):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def parsed(element):
        root=ET.Element('package');root.append(copy.deepcopy(element))
        profile=container.inspect_bytes(ET.tostring(root,encoding='utf-8'))
        return profile['xml'][profile['root']]['elements'][1]
    def inspect(element):return procedural.function(parsed(element))
    def refused(label,element,pattern=False):
        try:(procedural.pattern if pattern else procedural.function)(parsed(element))
        except ValueError:checks.append(label)
        else:raise AssertionError('accepted '+label)
    def source(label,element,pattern=False):
        root=copy.deepcopy(base);tag='paramsGraph' if pattern else 'dynamicValue'
        target=next(root.iter(tag))
        parent=next(p for p in root.iter() if target in list(p));index=list(parent).index(target)
        parent.remove(target);parent.insert(index,copy.deepcopy(element))
        path=out/(label+'.sbs');path.write_bytes(ET.tostring(root,encoding='utf-8'));return path
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        index=len(calls);(out/f'{index:03}.stdout').write_bytes(result.stdout);(out/f'{index:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        if result.returncode:raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout)
    def native_bodies(data,tag):
        result=[]
        if isinstance(data,dict):
            if data.get('t')==tag:result.append(data['v'])
            for v in data.values():result.extend(native_bodies(v,tag))
        elif isinstance(data,list):
            for v in data:result.extend(native_bodies(v,tag))
        return result
    def agree(label,path):
        profile=procedural.inspect(container.read_native(path));info=run('info',path)
        for key,tag in [('functions','function'),('patterns','patternGraph')]:
            expected=[r['model'] for r in profile[key].values()]
            observed=native_bodies(info['nativePackage'],tag)
            check(label+' '+tag+' exact independent model',sorted(map(lambda x:json.dumps(x,sort_keys=True),expected))==sorted(map(lambda x:json.dumps(x,sort_keys=True),observed)))
        return profile,info
    try:
        text=(args.upstream/'crates/nodes/src/function/catalog.rs').read_bytes()
        check('pinned intrinsic source checksum',hashlib.sha256(text).hexdigest()==catalog.SOURCE_SHA256)
        entries=re.findall(r'FunctionDefinition \{ id: "([^"]+)", label: "[^"]+", inputs: &\[([^\]]*)\]',text.decode())
        expected={name:tuple(re.findall(r'"([^"]+)"',ports)) for name,ports in entries}
        check('all 85 intrinsic connector contracts match pinned source',expected==catalog.INPUTS and len(expected)==85)
        report,info=agree('retained atomic sample',args.fixture)
        check('all retained embedded bodies inventoried',len(report['functions'])==3 and len(report['patterns'])==1 and report['nodes']==15)
        pattern_report=next(iter(report['patterns'].values()))
        check('shared pattern child counted once per actual visit',pattern_report['visits_bound']==10 and pattern_report['stamps_bound']==8)
        # Every catalog operation is preserved through the real parser and
        # writer, including disconnected nodes. This is schema coverage, not
        # a claim that each operation's numeric semantics is qualified.
        spec=[(1,'const_float1',[],('float',0.25),256)]
        for index,(op,ports) in enumerate(catalog.INPUTS.items(),2):
            setting=None
            if op.startswith('const_'):
                kind=op[6:].replace('float1','float').replace('int1','int').replace('string','text')
                data='example' if kind=='text' else True if kind=='bool' else [0]*int(kind[-1]) if kind[-1:].isdigit() else 0
                setting=(kind,data)
            elif op.startswith('get_') or op in ('set','isdefined'):setting=('text','brightness')
            elif 'swizzle' in op:setting=('int',0) if op[-1]=='1' else ('int'+op[-1],[0]*int(op[-1]))
            elif op in ('samplecol','samplelum'):setting=('int2',[0,1])
            elif op=='while':setting=('int',3)
            spec.append((index,op,[1]*len(ports),setting,256))
        all_ops=body(spec,1);initial=source('all-intrinsics',all_ops)
        agree('all intrinsic schema',initial)
        canonical=out/'all-intrinsics.mcraft';run('run',initial,'file.save',json.dumps({'path':str(canonical)}))
        agree('native-authored intrinsic schema',canonical)
        cold=out/'all-intrinsics-cold.mcraft';run('run',canonical,'file.save',json.dumps({'path':str(cold)}))
        container.check_preservation(container.read_native(canonical),container.read_native(cold));check('all intrinsic cold member preservation',True)
        f=lambda i,x:(i,'const_float1',[],('float',x),256)
        b=lambda i,x:(i,'const_bool',[],('bool',x),4)
        cases=[
            ('arithmetic',[f(1,.25),f(2,.5),(3,'add',[1,2],None,256)],3,{'t':'float','v':.75}),
            ('branch',[b(1,False),f(2,.25),f(3,.5),(4,'ifelse',[1,2,3],None,256)],4,{'t':'float','v':.5}),
            ('state-sequence',[f(1,.25),(2,'set',[1],('text','saved'),256),(3,'get_float1',[],('text','saved'),256),(4,'sequence',[2,3],None,256)],4,{'t':'float','v':.25}),
            ('bounded-loop',[f(1,.25),b(2,False),f(3,.5),(4,'while',[1,2,3],('int',3),256)],4,{'t':'float','v':.5}),
            ('unbounded-loop-immediate-exit',[f(1,.25),b(2,True),f(3,.5),(4,'while',[1,2,3],('int',-1),256)],4,{'t':'float','v':.25}),
            ('vector',[(1,'const_float2',[],('float2',[.25,.5]),512),(2,'const_float2',[],('float2',[.75,1]),512),(3,'vector4',[1,2],None,2048)],3,{'t':'float4','v':[.25,.5,.75,1.]}),
            ('swizzle',[(1,'const_float4',[],('float4',[.25,.5,.75,1]),2048),(2,'swizzle1',[1],('int',2),256)],2,{'t':'float','v':.75}),
            ('cast',[(1,'const_int1',[],('int',3),16),(2,'tofloat',[1],None,256)],2,{'t':'float','v':3.}),
            ('sample-missing',[(1,'const_float2',[],('float2',[.25,.5]),512),(2,'samplelum',[1],('int2',[0,1]),256)],2,{'t':'float','v':0.}),
        ]
        for label,nodes,output,expected_value in cases:
            element=body(nodes,output);profile=inspect(element);path=source(label,element);_,info=agree(label,path)
            cooked=next(n for n in info['graph']['nodes'] if n['def']=='value_processor')['cooked']
            check(label+' actual native value oracle',cooked['error'] is None and cooked['value']==expected_value)
            if label=='bounded-loop':check('bounded loop conservative steps',profile['steps_bound']==25 and not profile['may_exhaust_native_budget'])
            if label=='unbounded-loop-immediate-exit':check('unbounded loop retains finite native guard without termination claim',profile['steps_bound']==100000 and profile['may_exhaust_native_budget'])
        # All four pattern node kinds, including an added Dot, are interpreted
        # by the real CPU engine and preserved after native canonicalization.
        pattern=copy.deepcopy(next(base.iter('paramsGraph')))
        d=child(pattern.find('paramsGraphDatas'),'paramsGraphData');child(d,'uid',1500000001);child(d,'type','passthrough');child(d,'parameters')
        n=child(pattern.find('paramsGraphNodes'),'paramsGraphNode');child(n,'uid',1500000000);child(n,'type','passthrough');child(n,'data',1500000001)
        child(child(n,'GUILayout'),'gpos','-140 0 0');wire=child(child(n,'connections'),'connection');child(wire,'identifier','output');child(wire,'connRef',pattern.find('rootnode').get('v'))
        pattern.find('rootnode').set('v','1500000000');path=source('all-pattern-kinds',pattern,True)
        profile,info=agree('all pattern kinds',path)
        check('all four pattern kinds inventoried',set(n['kind'] for n in next(iter(profile['patterns'].values()))['model']['nodes'])==set(procedural.PATTERN_PORTS))
        check('all pattern kinds native cook',next(n for n in info['graph']['nodes'] if n['def']=='fx_map')['cooked']['error'] is None)
        canonical=out/'all-pattern-kinds.mcraft';run('run',path,'file.save',json.dumps({'path':str(canonical)}));agree('canonical pattern',canonical)
        cold=out/'all-pattern-kinds-cold.mcraft';run('run',canonical,'file.save',json.dumps({'path':str(cold)}))
        container.check_preservation(container.read_native(canonical),container.read_native(cold));check('all pattern kinds cold member preservation',True)
        simple=body([f(1,.25),f(2,.5),(3,'add',[1,2],None,256)],3)
        mutations=[
            ('unknown root',lambda e:child(e,'future')),
            ('unknown node field',lambda e:child(e.find('paramNodes/paramNode'),'future')),
            ('duplicate ID',lambda e:e.find('paramNodes').append(copy.deepcopy(e.find('paramNodes/paramNode')))),
            ('u32 overflow',lambda e:e.find('paramNodes/paramNode/uid').set('v',str(2**32))),
            ('invalid type',lambda e:e.find('paramNodes/paramNode/type').set('v','999')),
            ('wrong constant arity',lambda e:e.find('.//constantValueFloat1').set('v','1 2')),
            ('nonfinite constant',lambda e:e.find('.//constantValueFloat1').set('v','NaN')),
            ('overflow float',lambda e:e.find('.//constantValueFloat1').set('v','1e80')),
            ('constant under wrong name',lambda e:e.find('.//funcData/name').set('v','other')),
            ('missing constant data',lambda e:e.find('paramNodes/paramNode').remove(e.find('paramNodes/paramNode/funcDatas'))),
            ('duplicate data',lambda e:e.find('.//funcDatas').append(copy.deepcopy(e.find('.//funcData')))),
            ('missing result',lambda e:e.find('rootnode').set('v','999')),
            ('missing source',lambda e:e.find('.//connRef').set('v','999')),
            ('cycle',lambda e:e.find('.//connRef').set('v','3')),
            ('unknown connector',lambda e:e.find('.//connection/identifier').set('v','future')),
            ('duplicate connector',lambda e:e.find('.//connection/..').append(copy.deepcopy(e.find('.//connection')))),
            ('ignored Z coordinate',lambda e:e.find('.//gpos').set('v','0 0 1')),
            ('unknown operation',lambda e:e.find('.//function').set('v','future')),
        ]
        for label,change in mutations:
            element=copy.deepcopy(simple);change(element);refused(label,element)
        element=copy.deepcopy(simple);element.find('rootnode').set('v','1');element.find('.//connRef').set('v','3');refused('unreachable cycle still refuses',element)
        element=body([(1,'passthrough',[None],None,256)],1);refused('Dot result would disappear',element)
        empty=inspect(body([],None));check('empty editable function has zero work',empty['steps_bound']==0 and empty['model']['output'] is None)
        incomplete=inspect(body([f(1,.25),(2,'add',[1,None],None,256)],2));check('incomplete editable graph never claims executable connectivity',not incomplete['complete_connections'])
        for label,change in [
            ('unknown pattern field',lambda e:child(e,'future')),
            ('duplicate pattern ID',lambda e:e.find('paramsGraphNodes').append(copy.deepcopy(e.find('paramsGraphNodes/paramsGraphNode')))),
            ('missing pattern child',lambda e:e.find('.//connection/connRef').set('v','999')),
            ('pattern cycle',lambda e:e.find('.//connection/connRef').set('v',e.find('paramsGraphNodes/paramsGraphNode/uid').get('v'))),
            ('unknown pattern port',lambda e:e.find('.//connection/identifier').set('v','future')),
            ('mismatched data type',lambda e:e.find('paramsGraphDatas/paramsGraphData/type').set('v','markov2')),
            ('unused data',lambda e:e.find('paramsGraphNodes').remove(e.find('paramsGraphNodes/paramsGraphNode'))),
            ('duplicate parameter',lambda e:e.find('.//parameters').append(copy.deepcopy(e.find('.//parameter')))),
            ('negative iteration',lambda e:e.find('.//constantValueInt32').set('v','-1')),
            ('excessive iteration',lambda e:e.find('.//constantValueInt32').set('v','10001')),
        ]:
            element=copy.deepcopy(pattern);change(element);refused(label,element,True)
        expanded=copy.deepcopy(next(base.iter('paramsGraph')))
        first_data=expanded.find('paramsGraphDatas/paramsGraphData');first_data.find('.//constantValueInt32').set('v','10000')
        nested_data=copy.deepcopy(first_data);nested_data.find('uid').set('v','1600000000');expanded.find('paramsGraphDatas').append(nested_data)
        first_node=expanded.find('paramsGraphNodes/paramsGraphNode');nested_node=copy.deepcopy(first_node)
        nested_node.find('uid').set('v','1600000001');nested_node.find('data').set('v','1600000000')
        expanded.find('paramsGraphNodes').append(nested_node);first_node.findall('.//connRef')[1].set('v','1600000001')
        report=procedural.pattern(parsed(expanded));check('nested pattern expansion saturates before native work',report['visits_bound']==65536 and report['stamps_bound']==65536 and report['may_exhaust_native_budget'])
        dynamic=copy.deepcopy(next(base.iter('paramsGraph')));parameter=dynamic.find('.//parameter')
        parameter.remove(parameter.find('relativeTo'));holder=parameter.find('paramValue');holder.clear()
        holder.append(body([(1,'const_int1',[],('int',3),16)],1))
        report=procedural.pattern(parsed(dynamic));check('dynamic iteration retains explicit uncertainty',report['dynamic_iterations'] and report['visits_bound']==10002 and not report['engine_admission_complete'])
        # Editable canvas fields are independently checked, then retained exactly
        # by two actual native saves. They are not erased to simplify comparison.
        annotated=copy.deepcopy(simple);objects=child(annotated,'GUIObjects')
        for index,kind in enumerate(('frame','comment','pin'),1):
            item=child(objects,'GUIObject');child(item,'type','PIN' if kind=='pin' else 'COMMENT')
            layout=child(item,'GUILayout');child(layout,'gpos','10 20 '+('-100' if kind=='frame' else '0'))
            if kind!='pin':child(layout,'size','180 70')
            child(item,'GUIName',kind+' text');child(item,'uid',2000000000+index)
            if kind!='pin':child(item,'isFrameVisible','1' if kind=='frame' else '0')
            if kind=='frame':
                child(item,'title','Procedure');child(item,'frameColor','1 0 0 0.5');child(item,'isTitleVisible','1')
        check('all three embedded canvas forms inventoried',len(inspect(annotated)['annotations_xml'])==3)
        path=source('canvas',annotated);info=run('info',path)
        observed=next(n for n in info['nativePackage']['graphs'][0]['nodes'] if n['def']=='value_processor')['params']['function']['v']['annotations']
        check('native canvas semantic fields agree',observed=={
            'frames':[{'id':1,'title':'Procedure','description':'frame text','title_visible':True,'rect':[10.,20.,180.,70.],'color':[1.,0.,0.,.5]}],
            'comments':[{'id':2,'text':'comment text','pos':[10.,20.],'size':[180.,70.]}],
            'pins':[{'id':3,'name':'pin text','pos':[10.,20.]}]})
        canonical=out/'canvas.mcraft';cold=out/'canvas-cold.mcraft'
        run('run',path,'file.save',json.dumps({'path':str(canonical)}));run('run',canonical,'file.save',json.dumps({'path':str(cold)}))
        container.check_preservation(container.read_native(canonical),container.read_native(cold));check('canvas cold byte preservation',True)
        for label,change in [
            ('unknown canvas kind',lambda e:e.find('.//GUIObject/type').set('v','future')),
            ('canvas size would clamp',lambda e:e.find('.//GUIObject/GUILayout/size').set('v','1 1')),
            ('unknown canvas attribute',lambda e:e.find('.//GUIObject').set('future','yes')),
            ('duplicate canvas UID',lambda e:e.findall('.//GUIObject/uid')[1].set('v',e.find('.//GUIObject/uid').get('v'))),
        ]:
            element=copy.deepcopy(annotated);change(element);refused(label,element)
        # Function instances retain their interface/reference without granting
        # access to an external package. Full resolution remains a prerequisite.
        instance=body([f(1,.25)],1);node=instance.find('paramNodes/paramNode')
        node.find('function').set('v','instance');node.find('funcDatas/funcData/name').set('v','instance')
        holder=node.find('funcDatas/funcData/constantValue');holder.clear();value(holder,'text','pkg:///Called')
        child(node,'materialcraftInterface')
        report=inspect(instance);check('instance requires explicit call resolution',report['requires_call_resolution'] and report['references'][0]['graph']=='Called' and not report['engine_admission_complete'])
        path=source('instance',instance);root=ET.fromstring(path.read_bytes());standalone=child(root.find('content'),'function')
        child(standalone,'identifier','Called');child(standalone,'uid',2000000000);child(standalone,'paraminputs');child(standalone,'type',256)
        child(standalone,'paramValue').append(body([f(1500000000,.25)],1500000000));path.write_bytes(ET.tostring(root,encoding='utf-8'))
        info=run('info',path);cooked=next(n for n in info['graph']['nodes'] if n['def']=='value_processor')['cooked']
        check('real same-package function call oracle',cooked['error'] is None and cooked['value']=={'t':'float','v':.25})
        for label,reference in [('ambient library reference','sbs://functions.sbs/Called'),('traversing graph reference','pkg:///../Called'),('extra dependency query','pkg:///Called?dependency=1&ignored=2')]:
            element=copy.deepcopy(instance);element.find('.//constantValueString').set('v',reference);refused(label,element)
        element=copy.deepcopy(instance);port=child(element.find('.//materialcraftInterface'),'input');child(port,'identifier','value');child(port,'type',256)
        element.find('.//materialcraftInterface').append(copy.deepcopy(port));refused('duplicate instance interface',element)
        # A full 4,096-node chain validates without Python recursion or quadratic
        # path expansion; every source is present and the topology stays intact.
        chain=[f(1,.5)]+[(i,'neg',[i-1],None,256) for i in range(2,4097)]
        report=inspect(body(chain,4096));check('maximum-depth flat DAG uses iterative topology',report['nodes']==4096 and report['steps_bound']==8192)
        # Work recurrence counts shared DAG paths, not just unique nodes, and
        # saturates before exponentiation can consume arbitrary Python memory.
        chain=[f(1,.5)]+[(i,'add',[i-1,i-1],None,256) for i in range(2,40)]
        report=inspect(body(chain,39));check('shared function expansion saturates',report['steps_bound']==100000 and report['may_exhaust_native_budget'])
        for key,value_ in [('MAX_NODES',2),('MAX_STRING_BYTES',0)]:
            old=getattr(procedural,key);setattr(procedural,key,value_)
            try:refused('budget '+key,simple)
            finally:setattr(procedural,key,old)
        for key in ('MAX_TOTAL_NODES','MAX_BODIES'):
            old=getattr(procedural,key);setattr(procedural,key,0)
            try:
                try:procedural.inspect(container.read_native(args.fixture))
                except ValueError:checks.append('aggregate '+key)
                else:raise AssertionError('accepted '+key)
            finally:setattr(procedural,key,old)
        check('original input unchanged',args.fixture.read_bytes()==original)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'intrinsic_schema_operations':85,'pattern_kinds':4,
                  'real_function_oracles':len(cases)+1,'engine_admission_complete':False,'remote_actions':False,
                  'scope':'procedural schema/topology and local work bounds; full type/scope/call resolution, outer graph admission, raster and whole-job budgets remain required'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls),'evidence':str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
