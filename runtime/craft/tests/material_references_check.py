#!/usr/bin/env python3
"""Reference resolution against real native calls, defaults and portable archives."""
import argparse
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_container as container,material_resources as resources,material_graphs as graphs,material_references as references
from material_procedural_check import body,child,value


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--fixtures',type=Path,required=True)
    ap.add_argument('--resource-fixture',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[];serial=2000000000
    def xml(path):
        profile=container.read_native(path);return ET.fromstring(profile['members'][profile['root']])
    atomic=xml(args.fixtures/'atomic.mcraft');paint=xml(args.fixtures/'paint.mcraft')
    originals={path:path.read_bytes() for path in (args.fixtures/'atomic.mcraft',args.fixtures/'paint.mcraft',args.resource_fixture)}
    def identity():
        nonlocal serial
        serial+=1;return serial
    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        i=len(calls);(out/f'{i:03}.stdout').write_bytes(result.stdout);(out/f'{i:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        if result.returncode:raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout)
    def inspect(data):
        source=container.inspect_bytes(data);package=resources.inspect(source);graph=graphs.inspect(source,package)
        return source,graph,references.inspect(source,package,graph)
    def inspect_xml(root):return inspect(ET.tostring(root,encoding='utf-8'))
    def refused(label,root):
        try:inspect_xml(root)
        except ValueError:checks.append(label)
        else:raise AssertionError('accepted '+label)
    def call_body(target,connected=True,argument='constant'):
        first=(1,'const_float1',[],('float',.75),256) if argument=='constant' else (1,'get_float1',[],('text','amount'),256)
        result=body([first,(2,'const_float1',[],('float',0),256)],2);node=result.findall('paramNodes/paramNode')[1]
        node.find('function').set('v','instance');node.find('funcDatas/funcData/name').set('v','instance')
        data=node.find('funcDatas/funcData/constantValue');data.clear();value(data,'text','pkg:///'+target)
        port=child(child(node,'materialcraftInterface'),'input');child(port,'identifier','amount');child(port,'type',256)
        if connected:
            wire=child(node.find('connections'),'connection');child(wire,'identifier','amount');child(wire,'connRef',1)
        return result
    def function(name,target=None):
        graph=ET.Element('function');child(graph,'identifier',name);child(graph,'uid',identity());child(graph,'attributes')
        input_=child(child(graph,'paraminputs'),'paraminput');child(input_,'identifier','amount');child(input_,'uid',identity())
        attrs=child(input_,'attributes');child(attrs,'label','Amount');child(attrs,'description','Reusable scalar input')
        child(input_,'type',256);value(child(input_,'defaultValue'),'float',.25)
        widget=child(input_,'defaultWidget');child(widget,'name','slider');opts=child(widget,'options')
        for key,val in [('min','0'),('max','1'),('clamp','0')]:
            option=child(opts,'option');child(option,'name',key);child(option,'value',val)
        child(graph,'type',256)
        nodes=[(1,'get_float1',[],('text','amount'),256),(2,'const_float1',[],('float',.5),256),(3,'mul',[1,2],None,256)]
        child(graph,'paramValue').append(body(nodes,3) if target is None else call_body(target,True,'variable'))
        return graph
    def function_fixture(connected=True,depth=1):
        root=copy.deepcopy(atomic);target=next(root.iter('dynamicValue'));parent=next(p for p in root.iter() if target in list(p));parent.remove(target);parent.append(call_body('F1',connected))
        for i in range(1,depth+1):root.find('content').append(function('F'+str(i),'F'+str(i+1) if i<depth else None))
        return root
    def caller_body_key(report):
        return next(key for key,r in report['functions'].items() if r['calls'] and next(iter(r['calls'].values()))['target'][1].split('/')[-1]=='F1')
    def verify_function(label,root,expected):
        source,_,report=inspect_xml(root);path=out/(label+'.sbs');path.write_bytes(ET.tostring(root,encoding='utf-8'));original=path.read_bytes()
        info=run('info',path);node=next(n for n in info['graph']['nodes'] if n['def']=='value_processor')
        check(label+' native value',node['cooked']['error'] is None and node['cooked']['value']=={'t':'float','v':expected})
        expected_model=report['functions'][caller_body_key(report)]['model']
        native=next(n for n in info['nativePackage']['graphs'][0]['nodes'] if n['def']=='value_processor')['params']['function']['v']
        check(label+' independent resolved model',native==expected_model)
        canonical=out/(label+'.mcraft');run('run',path,'file.save',json.dumps({'path':str(canonical)}))
        admitted,_,cold_report=inspect(canonical.read_bytes());cold=out/(label+'-cold.mcraft');run('run',canonical,'file.save',json.dumps({'path':str(cold)}))
        container.check_preservation(admitted,container.read_native(cold));check(label+' cold preservation and original unchanged',path.read_bytes()==original)
        return report
    def image_fixture():
        root=copy.deepcopy(paint);source=root.find('content/graph');source.find('identifier').set('v','Child')
        parent=copy.deepcopy(source);parent.find('identifier').set('v','Parent');parent.find('uid').set('v',str(identity()))
        output_nodes=[n for n in parent.findall('compNodes/compNode') if n.find('compImplementation/compOutputBridge') is not None]
        holder=parent.find('compNodes');holder.clear();node=child(holder,'compNode');nid=identity();child(node,'uid',nid);child(child(node,'GUILayout'),'gpos','50 40 0')
        output_holder=child(node,'compOutputs');impl=child(child(node,'compImplementation'),'compInstance');child(impl,'path','pkg:///Child');child(impl,'parameters');bridges=child(impl,'outputBridgings')
        for output,bridge in zip(parent.findall('graphOutputs/graphoutput'),output_nodes):
            pid=identity();record=child(output_holder,'compOutput');child(record,'uid',pid);child(record,'comptype',output.find('channels').get('v'))
            record=child(bridges,'outputBridging');child(record,'uid',pid);child(record,'identifier',output.find('identifier').get('v'))
            bridge.find('connections/connection/connRef').set('v',str(nid));bridge.find('connections/connection/connRefOutput').set('v',str(pid));holder.append(bridge)
        root.find('content').insert(0,parent);return root
    try:
        for name in ('paint.mcraft','atomic.mcraft','embedded.mcraft','linked-package.mcraft','portable-source.sbs'):
            _,_,report=inspect((args.fixtures/name).read_bytes());check('retained references '+name,not report['engine_admission_complete'])
        default=verify_function('source-default',function_fixture(False),.125)
        check('default specification comes from admitted source',default['functions'][caller_body_key(default)]['calls'][2]['default_specs']['amount']['value']=={'t':'float','v':.25})
        override=verify_function('connected-argument',function_fixture(True),.375)
        nested=verify_function('depth-eight',function_fixture(True,8),.375)
        check('eight levels and repeated body sizes computed before expansion',nested['functions'][caller_body_key(nested)]['call_depth']==8 and nested['functions'][caller_body_key(nested)]['expanded_nodes']==19)
        repeated=function_fixture();dynamic=next(repeated.iter('dynamicValue'));node=copy.deepcopy(dynamic.findall('paramNodes/paramNode')[1]);node.find('uid').set('v','3');dynamic.find('paramNodes').append(node);dynamic.find('rootnode').set('v','3')
        repeated_report=verify_function('shared-call-expansion',repeated,.375)
        check('shared function source counted for each call occurrence',repeated_report['functions'][caller_body_key(repeated_report)]['expanded_nodes']==9)
        refused('ninth function call level',function_fixture(True,9))
        for label,change in [
            ('missing function',lambda r:r.find('.//materialcraftInterface/../funcDatas/funcData/constantValue/constantValueString').set('v','pkg:///Missing')),
            ('wrong function kind',lambda r:r.find('.//materialcraftInterface/../funcDatas/funcData/constantValue/constantValueString').set('v','pkg:///Atomic')),
            ('unknown dependency',lambda r:r.find('.//materialcraftInterface/../funcDatas/funcData/constantValue/constantValueString').set('v','pkg:///F1?dependency=999')),
            ('noncanonical dependency identity',lambda r:r.find('dependencies/dependency/uid').set('v','0'+r.find('dependencies/dependency/uid').get('v'))),
            ('cached result type differs',lambda r:r.find('.//materialcraftInterface/../type').set('v','16')),
            ('cached input name differs',lambda r:r.find('.//materialcraftInterface/input/identifier').set('v','renamed')),
            ('cached input type differs',lambda r:r.find('.//materialcraftInterface/input/type').set('v','16')),
            ('source result type differs',lambda r:r.find('content/function/type').set('v','16')),
        ]:
            root=function_fixture();change(root);refused(label,root)
        unused=copy.deepcopy(atomic);empty=function('Empty');holder=empty.find('paramValue');holder.clear();holder.append(body([],None));unused.find('content').append(empty)
        _,_,empty_report=inspect_xml(unused);check('unused empty function stays editable without a result claim',None in empty_report['function_graph_types'].values())
        root=function_fixture();holder=root.find('content/function/paramValue');holder.clear();holder.append(body([],None));refused('called empty function has no result',root)
        root=function_fixture();fn=root.find('content/function');holder=fn.find('paramValue');holder.clear();holder.append(call_body('F1',True,'variable'));refused('recursive function graph',root)
        root=function_fixture(True,2);holder=root.findall('content/function')[1].find('paramValue');holder.clear();holder.append(call_body('F1',True,'variable'));refused('mutual function recursion',root)
        root=function_fixture();node=next(root.iter('dynamicValue')).find('paramNodes/paramNode');node.find('function').set('v','const_int1');node.find('type').set('v','16');node.find('funcDatas/funcData/name').set('v','const_int1')
        data=node.find('funcDatas/funcData/constantValue');data.clear();value(data,'int',1);refused('connected argument type mismatch',root)
        # A unique leaf alias is a native function feature; ambiguous aliases
        # refuse, and an exact root path wins over same-named nested graphs.
        root=function_fixture();fn=root.find('content/function');root.find('content').remove(fn)
        group=child(root.find('content'),'group');child(group,'identifier','Library');child(group,'uid',identity());child(group,'content').append(fn)
        verify_function('unique-leaf-alias',root,.375)
        extra=copy.deepcopy(group);extra.find('identifier').set('v','Other');extra.find('uid').set('v',str(identity()));extra.find('content/function/uid').set('v',str(identity()));root.find('content').append(extra);refused('ambiguous leaf alias',root)
        root.find('content').append(function('F1'));verify_function('exact-path-wins',root,.375)
        image_root=image_fixture();source,graph,report=inspect_xml(image_root)
        parent_key=next(key for key in report['expanded_image_nodes'] if key[1]=='Parent')
        check('image graph expansion counts callee nodes',report['expanded_image_nodes'][parent_key]==19 and report['image_call_depth'][parent_key]==1)
        path=out/'image-instance.sbs';path.write_bytes(ET.tostring(image_root,encoding='utf-8'));info=run('info',path);graphs.check_native(graph,source['root'],info['nativePackage'])
        check('native image instance cooks with exact topology',all(not n['cooked'] or n['cooked']['error'] is None for n in info['graph']['nodes']))
        exports=out/'instance-maps';run('export',path,exports,'--depth','8')
        pixels={'basecolor':(188,188,188,255),'normal':(128,128,255,255),'roughness':(128,128,128,255),'metallic':(0,0,0,255),'height':(0,0,0,255),'ambientocclusion':(255,255,255,255)}
        for channel,pixel in pixels.items():
            im=Image.open(exports/('Parent_'+channel+'.png')).convert('RGBA');check('instance analytic pixels '+channel,im.size==(64,64) and im.tobytes()==bytes(pixel)*4096)
        target=out/'image-instance.mcraft';run('run',path,'file.save',json.dumps({'path':str(target)}));admitted,_,_=inspect(target.read_bytes())
        cold=out/'image-instance-cold.mcraft';run('run',target,'file.save',json.dumps({'path':str(cold)}));container.check_preservation(admitted,container.read_native(cold));check('image instance exact cold preservation',True)
        for label,change in [
            ('missing image target',lambda r:r.find('.//compInstance/path').set('v','pkg:///Missing')),
            ('image self recursion',lambda r:r.find('.//compInstance/path').set('v','pkg:///Parent')),
            ('wrong image output type',lambda r:r.find('.//compNodes/compNode/compOutputs/compOutput/comptype').set('v','16')),
            ('wrong image output name',lambda r:r.find('.//outputBridging/identifier').set('v','missing')),
        ]:
            root=copy.deepcopy(image_root);change(root);refused(label,root)
        root=copy.deepcopy(image_root);root.find('content').append(function('F1'));root.find('.//compInstance/path').set('v','pkg:///F1');refused('image instance cannot target function',root)
        recursive=copy.deepcopy(image_root);content=recursive.find('content');child_graph=content.findall('graph')[1];content.remove(child_graph)
        other=copy.deepcopy(content.find('graph'));other.find('identifier').set('v','Child');other.find('uid').set('v',str(identity()));other.find('.//compInstance/path').set('v','pkg:///Parent');content.append(other);refused('mutual image graph recursion',recursive)
        def image_chain(depth):
            root=copy.deepcopy(image_root);content=root.find('content');template=copy.deepcopy(content.findall('graph')[0]);leaf=copy.deepcopy(content.findall('graph')[1]);content.clear();leaf.find('identifier').set('v','Leaf')
            for i in range(1,depth+1):
                graph=copy.deepcopy(template);graph.find('uid').set('v',str(identity()));graph.find('identifier').set('v','G'+str(i));graph.find('.//compInstance/path').set('v','pkg:///'+('G'+str(i+1) if i<depth else 'Leaf'));content.append(graph)
            content.append(leaf);return root
        deep=image_chain(8);_,_,deep_report=inspect_xml(deep);key=next(k for k in deep_report['image_call_depth'] if k[1]=='G1')
        check('eight image call levels have exact expansion count',deep_report['image_call_depth'][key]==8 and deep_report['expanded_image_nodes'][key]==68)
        path=out/'image-depth-eight.sbs';path.write_bytes(ET.tostring(deep,encoding='utf-8'));info=run('info',path)
        check('eight image levels cook in real engine',all(not n['cooked'] or n['cooked']['error'] is None for n in info['graph']['nodes']))
        exports=out/'depth-eight-maps';run('export',path,exports,'--depth','8');im=Image.open(exports/'G1_basecolor.png').convert('RGBA');check('eight image levels retain analytic pixels',im.tobytes()==bytes((188,188,188,255))*4096)
        refused('ninth image call level',image_chain(9))
        # Package dependency declarations resolve only snapshot XML members.
        # This validates ownership without enabling the native external loader.
        archive_root=copy.deepcopy(image_root);child_graph=archive_root.findall('content/graph')[1];archive_root.find('content').remove(child_graph)
        external=copy.deepcopy(paint);external.find('content').clear();external.find('content').append(child_graph)
        dep=copy.deepcopy(archive_root.find('dependencies/dependency'));dep.find('uid').set('v',str(identity()));dep.find('filename').set('v','dependencies/child.sbs');archive_root.find('dependencies').append(dep)
        archive_root.find('.//compInstance/path').set('v','pkg:///Child?dependency='+dep.find('uid').get('v'))
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('package.sbs',ET.tostring(archive_root,encoding='utf-8'));z.writestr('dependencies/child.sbs',ET.tostring(external,encoding='utf-8'))
        archive=stream.getvalue();(out/'admitted-dependency.mcraft').write_bytes(archive);_,_,report=inspect(archive)
        check('owned archived image dependency resolves with explicit handoff gate',report['requires_external_handoff'] and not report['engine_admission_complete'])
        source,graph,report=inspect(args.resource_fixture.read_bytes());check('bitmap resource resolves to exact owned bytes',len(report['resources'])==1)
        # Reference mutation keeps the same owned image file and only changes
        # the lookup, so rejection cannot be mistaken for missing image decode.
        with zipfile.ZipFile(args.resource_fixture) as z:members={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
        root=ET.fromstring(members[source['root']]);node=next(p for p in root.findall('.//parameter') if p.find('name').get('v')=='bitmapresourcepath')
        node.find('paramValue/constantValueString').set('v','pkg:///Resources/Missing')
        members[source['root']]=ET.tostring(root,encoding='utf-8');stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for name,data in members.items():z.writestr(name,data)
        try:inspect(stream.getvalue())
        except ValueError:checks.append('missing bitmap target refuses after complete resource decode')
        else:raise AssertionError('accepted missing bitmap target')
        def archive(members):
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:
                for name,data in members.items():z.writestr(name,data)
            return stream.getvalue()
        # Preview bindings use the same owned bitmap bytes as explicit nodes.
        with zipfile.ZipFile(args.resource_fixture) as z:members={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
        source=container.inspect_bytes(archive(members));resource_profile=resources.inspect(source);resource_name=next(iter(resource_profile['packages'][source['root']]['resources']))
        root=ET.fromstring(members[source['root']]);graph=root.find('content/graph');input_uid=identity();node_uid=identity();output_uid=identity()
        port=child(graph.find('paraminputs'),'paraminput');child(port,'identifier','Preview');child(port,'uid',input_uid);child(port,'isConnectable','1');child(port,'type','1');value(child(port,'defaultValue'),'float4',[0,0,0,1])
        widget=child(port,'defaultWidget');child(widget,'name','');child(widget,'options');usage=child(child(port,'usages'),'usage');child(usage,'components','RGBA');child(usage,'name','any')
        node=child(graph.find('compNodes'),'compNode');child(node,'uid',node_uid);child(child(node,'GUILayout'),'gpos','50 40 0');output=child(child(node,'compOutputs'),'compOutput');child(output,'uid',output_uid);child(output,'comptype','1')
        impl=child(child(node,'compImplementation'),'compInputBridge');child(impl,'entry',input_uid);child(impl,'parameters')
        option=child(graph.find('options'),'option');child(option,'name','materialcraft.previewImage.Preview');child(option,'value',resource_name)
        target=next(n for n in graph.findall('compNodes/compNode') if n.find('compImplementation/compOutputBridge') is not None)
        target.find('connections/connection/connRef').set('v',str(node_uid));target.find('connections/connection/connRefOutput').set('v',str(output_uid))
        members[source['root']]=ET.tostring(root,encoding='utf-8');payload=archive(members);_,_,preview_report=inspect(payload)
        check('preview resolves exact owned resource identity',preview_report['previews'][0]['resource']==(source['root'],resource_name))
        path=out/'preview.mcraft';path.write_bytes(payload);info=run('info',path);preview_node=next(n for n in info['graph']['nodes'] if n['def']=='input_color')
        check('native bound preview image cooks',preview_node['cooked']['error'] is None and preview_node['cooked']['size']==[64,64])
        exports=out/'preview-maps';run('export',path,exports,'--depth','8');im=Image.open(exports/'Paint_basecolor.png').convert('RGBA')
        check('bound preview pixels match independent image oracle',im.tobytes()==bytes((137,188,225,255))*4096)
        option.find('value').set('v','Missing');members[source['root']]=ET.tostring(root,encoding='utf-8')
        try:inspect(archive(members))
        except ValueError:checks.append('missing preview resource refused')
        else:raise AssertionError('accepted missing preview')
        option.find('value').set('v',resource_name)
        dep=copy.deepcopy(root.find('dependencies/dependency'));dep.find('uid').set('v',str(identity()));dep.find('filename').set('v','dependencies/other.sbs');root.find('dependencies').append(dep)
        parameter=next(p for p in root.findall('.//parameter') if p.find('name').get('v')=='bitmapresourcepath')
        reference=parameter.find('paramValue/constantValueString');reference.set('v',reference.get('v').split('?')[0]+'?dependency='+dep.find('uid').get('v'))
        members[source['root']]=ET.tostring(root,encoding='utf-8');members['dependencies/other.sbs']=ET.tostring(paint,encoding='utf-8')
        try:inspect(archive(members))
        except ValueError:checks.append('cross-package bitmap dependency cannot silently bind local bytes')
        else:raise AssertionError('accepted cross-package bitmap confusion')
        # Functions resolve across admitted archive members but keep the native
        # external-loader gate. No filesystem callback or editor is involved.
        root=function_fixture();fn=root.find('content/function');root.find('content').remove(fn)
        nested=copy.deepcopy(paint);nested.find('content').clear();nested.find('content').append(fn)
        dep=copy.deepcopy(root.find('dependencies/dependency'));dep.find('uid').set('v',str(identity()));dep.find('filename').set('v','dependencies/called.sbs');root.find('dependencies').append(dep)
        root.find('.//materialcraftInterface/../funcDatas/funcData/constantValue/constantValueString').set('v','pkg:///F1?dependency='+dep.find('uid').get('v'))
        _,_,external_report=inspect(archive({'package.sbs':ET.tostring(root,encoding='utf-8'),'dependencies/called.sbs':ET.tostring(nested,encoding='utf-8')}))
        check('owned archived function resolves with explicit handoff gate',external_report['requires_external_handoff'] and not external_report['engine_admission_complete'])
        for key,limit in [('MAX_EXPANDED_FUNCTION_NODES',4),('MAX_EXPANDED_IMAGE_NODES',18)]:
            old=getattr(references,key);setattr(references,key,limit)
            try:refused('expanded budget '+key,function_fixture() if key=='MAX_EXPANDED_FUNCTION_NODES' else image_root)
            finally:setattr(references,key,old)
        check('original fixtures unchanged',all(path.read_bytes()==data for path,data in originals.items()))
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'engine_admission_complete':False,'remote_actions':False,
            'scope':'owned package references, function interfaces/default metadata, call topology and expansion; full operand/scope semantics, external native handoff and job work remain required'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls),'evidence':str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
