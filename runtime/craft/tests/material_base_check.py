#!/usr/bin/env python3
"""Independent base inheritance predictions against offline native CPU cooks."""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_container as container, material_resources as resources, material_graphs as graphs
from studio_runtime import material_references as references, material_base as base
from material_procedural_check import child, value, body


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--fixtures',type=Path,required=True)
    ap.add_argument('--catalog-fixture',type=Path,required=True);ap.add_argument('--upstream',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[]
    def check(label, condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def xml(path):
        p=container.read_native(path);return ET.fromstring(p['members'][p['root']])
    original=xml(args.fixtures/'paint.mcraft');original_bytes=(args.fixtures/'paint.mcraft').read_bytes()
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        i=len(calls);(out/f'{i:03}.stdout').write_bytes(result.stdout);(out/f'{i:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        check('native process '+str(i),result.returncode==0);return json.loads(result.stdout)
    def parameter(holder,name,kind,data,mode='0',dynamic=False):
        for old in list(holder):
            if old.find('name').get('v')==name:holder.remove(old)
        entry=child(holder,'parameter');child(entry,'name',name);child(entry,'relativeTo',mode);v=child(entry,'paramValue')
        if dynamic:
            op='const_'+{'int':'int1','float':'float1'}.get(kind,kind)
            from studio_runtime.material_references import VALUE_CODES
            v.append(body([(1,op,[],(kind,data),VALUE_CODES[kind])],1))
        else:value(v,kind,data)
    def inspect(path,evaluated=None):
        snapshot=container.read_native(path);package=resources.inspect(snapshot);report=graphs.inspect(snapshot,package)
        refs=references.inspect(snapshot,package,report)
        key=next(k for k in report['graphs'] if k[0]==snapshot['root']);graph=report['graphs'][key]
        prediction=base.inspect_graph(graph,refs['image_calls'][key],maximum=512,evaluated=evaluated)
        return graph,prediction
    def agree(label,root=None,path=None,evaluated=None):
        if path is None:
            path=out/(label+'.sbs');path.write_bytes(ET.tostring(root,encoding='utf-8'))
        graph,prediction=inspect(path,evaluated);info=run('info',path)
        base.check_native(prediction,info['graph']['nodes']);check(label+' all resolved bases',True)
        for source,actual in zip(graph['nodes'].values(),info['nativePackage']['graphs'][0]['nodes']):
            expected=base.model(source['parameters']);record=expected['literal']
            if expected['functions']:record['functions']={name:report['model'] for name,report in expected['functions'].items()}
            check(label+' serialized base '+str(actual['id']),actual['base']==record)
        check(label+' never grants execution',not prediction['engine_admission_complete'])
        return graph,prediction,info
    try:
        # Read every definition, rather than assuming unlisted nodes are generators.
        generators=set();primary={};definitions=set()
        for path in (args.upstream/'crates/nodes/src/atomic').glob('*.rs'):
            text=path.read_text();match=re.search(r'node\("([^"]+)"',text)
            if not match:continue
            name=match[1];definitions.add(name)
            if '.generator()' in text:generators.add(name)
            match=re.search(r'\.primary_input\("([^"]+)"\)',text)
            if match:primary[name]=match[1]
        check('all native sizing traits pinned',generators==base.GENERATORS and primary==base.PRIMARY_INPUTS and definitions==set(base.DEFINITIONS))
        agree('paint',path=args.fixtures/'paint.mcraft')
        agree('atomic',path=args.fixtures/'atomic.mcraft')
        agree('all-29-definitions',path=args.catalog_fixture)
        cases=[
            ('absolute-size','outputsize','int2',[7,5],'0',[128,32]),
            ('relative-size','outputsize','int2',[1,-1],'1',[128,32]),
            ('parent-size','outputsize','int2',[1,-1],'2',[128,32]),
            ('lower-clamp','outputsize','int2',[-12,-12],'0',[16,16]),
            ('upper-clamp','outputsize','int2',[13,13],'2',[8192,8192]),
            ('negative-seed','randomseed','int',-1,'0',None),
            ('relative-seed','randomseed','int',-1,'1',None),
            ('absolute-format','format','int',3,'0',None),
            ('inherited-format','format','int',0,'1',None),
            ('parent-format','format','int',2,'2',None),
            ('absolute-pixels','pixelsize','float2',[.25,2.],'0',None),
            ('relative-pixels','pixelsize','float2',[.25,2.],'1',None),
            ('fractional-pixels','pixelsize','float2',[.1,.3],'0',None),
            ('tiling','tiling','int',1,'0',None),
            ('ratio','pixelratio','int',1,'0',None),
        ]
        for label,name,kind,data,mode,size in cases:
            root=copy.deepcopy(original);g=root.find('content/graph')
            parameter(g.find('baseParameters'),'randomseed','int',2147483647,'0')
            parameter(g.find('compNodes/compNode/compImplementation/compFilter/parameters'),name,kind,data,mode)
            graph,prediction,info=agree(label,root)
            if size is not None:
                check(label+' independent size oracle',prediction['nodes'][1]['base']['size']==size)
                check(label+' actual capped uniform image size',info['graph']['nodes'][0]['cooked']['size']==base.limited_size(size,512))
            if name=='randomseed':
                expected=4294967295 if mode=='0' else (2147483647*0x9e3779b9-1)%2**32
                check(label+' independent seed oracle',prediction['nodes'][1]['base']['seed']==expected)
        # Blend inherits only its background, regardless of connection order.
        root=copy.deepcopy(original);g=root.find('content/graph');nodes=g.find('compNodes');first,second=nodes[0],nodes[2]
        parameter(first.find('compImplementation/compFilter/parameters'),'outputsize','int2',[7,5])
        parameter(second.find('compImplementation/compFilter/parameters'),'outputsize','int2',[5,7])
        parameter(second.find('compImplementation/compFilter/parameters'),'randomseed','int',17)
        def filter_node(filter_name,identity):
            n=child(nodes,'compNode');child(n,'uid',identity);child(child(n,'GUILayout'),'gpos','50 40 0')
            o=child(child(n,'compOutputs'),'compOutput');child(o,'uid',identity+1);child(o,'comptype',1)
            impl=child(child(n,'compImplementation'),'compFilter');child(impl,'filter',filter_name);child(impl,'parameters');child(n,'connections');return n
        def wire(target,label,source):
            c=child(target.find('connections'),'connection');child(c,'identifier',label);child(c,'connRef',source.find('uid').get('v'));child(c,'connRefOutput',source.find('compOutputs/compOutput/uid').get('v'))
        blend=filter_node('blend',2000000000);wire(blend,'source',first);wire(blend,'destination',second)
        fx=filter_node('fxmaps',2000000010);wire(fx,'background',blend)
        pixel=filter_node('pixelprocessor',2000000020);wire(pixel,'input',blend)
        graph,prediction,info=agree('port-inheritance',root)
        check('blend selects background source',prediction['nodes'][13]['input_base_source']==3 and prediction['nodes'][13]['base']['size']==[32,128])
        check('generator replaces only inherited size',prediction['nodes'][14]['base']['size']==[64,64] and prediction['nodes'][14]['base']['seed']==17)
        check('pixel processor inherits image dimensions',prediction['nodes'][15]['base']['size']==[32,128])
        pixel.find('connections').clear();wire(pixel,'input:7',second);wire(pixel,'input:1',first)
        _,indexed,_=agree('indexed-port-order',root)
        check('indexed image ports use numeric order not wire order',indexed['nodes'][15]['input_base_source']==1 and indexed['nodes'][15]['base']['size']==[128,32])
        blend.find('connections').remove(blend.findall('connections/connection')[1])
        _,prediction,_=agree('missing-primary',root)
        check('missing background falls back to parent not foreground',prediction['nodes'][13]['input_base_source'] is None and prediction['nodes'][13]['base']['size']==[64,64])
        # A dynamic dimension is not guessed from its serialized literal default.
        root=copy.deepcopy(original);holder=root.find('content/graph/compNodes/compNode/compImplementation/compFilter/parameters')
        parameter(holder,'outputsize','int2',[7,5],'0',True)
        path=out/'dynamic.sbs';path.write_bytes(ET.tostring(root,encoding='utf-8'))
        try:inspect(path)
        except ValueError as error:check('dynamic base requires separate evaluation','qualified evaluation' in str(error))
        else:raise AssertionError('unresolved dynamic dimensions accepted')
        _,prediction,info=agree('dynamic-qualified',path=path,evaluated={1:{'outputsize':{'t':'int2','v':[7,5]}}})
        check('dynamic literal result matches actual CPU size',info['graph']['nodes'][0]['cooked']['size']==[128,32])
        for name,kind,data in [('randomseed','int',-7),('format','int',3),('pixelsize','float2',[.1,.3]),('pixelratio','int',1),('tiling','int',2)]:
            changed=copy.deepcopy(original);holder=changed.find('content/graph/compNodes/compNode/compImplementation/compFilter/parameters')
            parameter(holder,name,kind,data,'0',True)
            agree('dynamic-'+name,changed,evaluated={1:{name:{'t':kind,'v':data}}})
        # Upper and lower bounds use the exact native clamps even for dynamic i32 extremes.
        dynamic={'outputsize':{'mode':'0','value':{'t':'function','v':{}}}}
        parent={'size':[64,64],'seed':0,'format':'u16','pixelSize':[1.,1.],'tiling':[True,True],'pixelRatio':0}
        result=base.resolve(dynamic,None,parent,{'outputsize':{'t':'int2','v':[-2**31,2**31-1]}})
        check('dynamic native integer extremes bounded',result['size']==[16,8192])
        pixels={'pixelsize':{'mode':'1','value':{'t':'float2','v':[8192.,1e-40]}}}
        result=base.resolve(pixels,{**parent,'pixelSize':[8192.,1e-40]},parent)
        check('pixel products follow binary32 and clamp',result['pixelSize']==[8192.,base.MIN_POSITIVE])
        check('preview rounding is positive half-away not bankers',base.limited_size([16,32],5)==[3,5])
        check('zero native preview maximum still produces a pixel',base.limited_size([16,8192],0)==[1,1])
        # Child graph context inherits instance size/seed/format, while explicit
        # graph tiling and pixel ratio can override their parent independently.
        graph={'size':[4,5],'base':{'tiling':{'mode':'0','value':{'t':'int','v':2}},'pixelratio':{'mode':'0','value':{'t':'int','v':1}}}}
        result=base.graph_parent(graph,{**parent,'size':[128,256],'seed':27,'format':'f32'})
        check('image call parent base contract',result=={**parent,'size':[128,256],'seed':27,'format':'f32','tiling':[False,True],'pixelRatio':1})
        # A real owned graph instance passes its uncapped base into a child.
        # The child's Value Processor sees the separately capped raster size.
        nested=copy.deepcopy(original);child_graph=nested.find('content/graph');child_graph.find('identifier').set('v','Child')
        for holder_path in ('graphOutputs','root/rootOutputs'):
            holder=child_graph.find(holder_path)
            for extra in list(holder)[1:]:holder.remove(extra)
        holder=child_graph.find('compNodes')
        for extra in list(holder)[2:]:holder.remove(extra)
        processor=holder[0];impl=processor.find('compImplementation/compFilter');impl.find('filter').set('v','valueprocessor')
        params=impl.find('parameters');params.clear();entry=child(params,'parameter');child(entry,'name','function');child(entry,'relativeTo','0')
        child(entry,'paramValue').append(body([(1,'get_float2',[],('text','$size'),512)],1))
        processor.find('compOutputs/compOutput/comptype').set('v','512');child_graph.find('graphOutputs/graphoutput/channels').set('v','512')
        for option in child_graph.find('options'):
            if option.find('name').get('v')=='defaultParentSize':option.find('value').set('v','4x4')
        caller=copy.deepcopy(child_graph);caller.find('identifier').set('v','Parent');caller.find('uid').set('v','2000000300')
        call_node=caller.find('compNodes/compNode');holder=call_node.find('compImplementation');holder.clear()
        instance=child(holder,'compInstance');child(instance,'path','pkg:///Child');params=child(instance,'parameters')
        parameter(params,'outputsize','int2',[10,8])
        bridging=child(child(instance,'outputBridgings'),'outputBridging')
        child(bridging,'uid',call_node.find('compOutputs/compOutput/uid').get('v'))
        child(bridging,'identifier',caller.find('graphOutputs/graphoutput/identifier').get('v'))
        nested.find('content').insert(0,caller)
        _,nested_prediction,nested_info=agree('owned-call-context',nested)
        path=out/'owned-call-context.sbs';snap=container.read_native(path);pkg=resources.inspect(snap);all_graphs=graphs.inspect(snap,pkg)
        child_profile=all_graphs['graphs'][(snap['root'],'Child')]
        child_prediction=base.inspect_graph(child_profile,parent=nested_prediction['nodes'][1]['base'],maximum=512)
        check('actual call inherits parent rather than saved child dimensions',child_prediction['nodes'][1]['base']['size']==[1024,256])
        check('actual child processor uses capped raster context',nested_info['graph']['nodes'][0]['cooked']['value']=={'t':'float2','v':[512.,128.]} and child_prediction['nodes'][1]['raster_size']==[512,128])
        for label,params,evaluated in [
            ('incomplete',dynamic,{}),
            ('extra',{}, {'outputsize':{'t':'int2','v':[6,6]}}),
            ('wrong-type',dynamic,{'outputsize':{'t':'float2','v':[6.,6.]}}),
            ('Boolean-as-integer',dynamic,{'outputsize':{'t':'int2','v':[True,6]}}),
            ('integer-overflow',dynamic,{'outputsize':{'t':'int2','v':[2**31,6]}}),
            ('pixel-underflow',{'pixelsize':{'mode':'0','value':{'t':'function','v':{}}}},{'pixelsize':{'t':'float2','v':[1e-100,1.]}}),
        ]:
            try:base.resolve(params,None,parent,evaluated)
            except ValueError:checks.append('invalid evaluated base '+label)
            else:raise AssertionError('accepted evaluated base '+label)
        bad=copy.deepcopy(info['graph']['nodes']);bad[0]['cooked']['base']['size']=[16,16]
        try:base.check_native(prediction,bad)
        except ValueError:checks.append('tampered native base refused')
        else:raise AssertionError('tampered native base accepted')
        for label,change in [
            ('Boolean seed',lambda nodes:nodes[0]['cooked']['base'].__setitem__('seed',False)),
            ('missing cooked',lambda nodes:nodes[0].__setitem__('cooked',None)),
            ('duplicate identity',lambda nodes:nodes[1].__setitem__('id',nodes[0]['id'])),
            ('nonfinite pixel size',lambda nodes:nodes[0]['cooked']['base'].__setitem__('pixelSize',[float('nan'),1.])),
        ]:
            bad=copy.deepcopy(info['graph']['nodes']);change(bad)
            try:base.check_native(prediction,bad)
            except ValueError:checks.append('malformed native base '+label)
            else:raise AssertionError('accepted malformed native base '+label)
        check('original source unchanged',(args.fixtures/'paint.mcraft').read_bytes()==original_bytes)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'engine_admission_complete':False,'remote_actions':False,
                  'scope':'serialized and resolved base parameters, port inheritance and capped dimensions; dynamic evaluator, recursive call layout and complete raster budgets remain separate'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
