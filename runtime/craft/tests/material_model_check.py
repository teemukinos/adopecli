#!/usr/bin/env python3
"""Full serialized editable state against the maintained native engine."""
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
from studio_runtime import material_references as references, material_model as model
from material_procedural_check import child, body


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','fixtures','graph-fixtures','reference-fixtures','procedural-fixtures','base-fixtures','resource-fixture','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[];originals={}
    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def inspect(data):
        snapshot=container.inspect_bytes(data);res=resources.inspect(snapshot);graph=graphs.inspect(snapshot,res);refs=references.inspect(snapshot,res,graph)
        return snapshot,model.inspect(snapshot,res,graph,refs)
    def xml(path):
        data=path.read_bytes();originals[path]=data;snapshot=container.inspect_bytes(data)
        return ET.fromstring(snapshot['members'][snapshot['root']])
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        i=len(calls);(out/f'{i:03}.stdout').write_bytes(result.stdout);(out/f'{i:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        check('native process '+str(i),result.returncode==0);return json.loads(result.stdout)
    def agree(label,path=None,root=None,cold=False):
        if path is None:path=out/(label+'.sbs');path.write_bytes(ET.tostring(root,encoding='utf-8'))
        original=path.read_bytes();snapshot,predicted=inspect(original)
        uncooked=run('snapshot',path);model.check_native(predicted,snapshot['root'],uncooked['nativePackage'])
        check(label+' snapshot performs no cook',uncooked['cookedNodeCount']==0 and uncooked['pendingCook'] is True and uncooked['loadWarnings']==[])
        info=run('info',path)
        check(label+' snapshot and cooked editable state agree',uncooked['nativePackage']==info['nativePackage'])
        model.check_native(predicted,snapshot['root'],info['nativePackage']);check(label+' complete serialized native package',True)
        check(label+' explicit non-admission',predicted['serialized_native_model_complete'] and not predicted['engine_admission_complete'])
        if cold:
            canonical=out/(label+'.mcraft');reopened=out/(label+'-cold.mcraft')
            run('run',path,'file.save',json.dumps({'path':str(canonical)}))
            first,report=inspect(canonical.read_bytes());model.check_native(report,first['root'],run('info',canonical)['nativePackage'])
            run('run',canonical,'file.save',json.dumps({'path':str(reopened)}))
            second,report=inspect(reopened.read_bytes());model.check_native(report,second['root'],run('info',reopened)['nativePackage'])
            container.check_preservation(first,second);check(label+' exact canonical cold member preservation',True)
        check(label+' source unchanged',path.read_bytes()==original)
        return snapshot,predicted,info
    try:
        cases=[('paint',args.fixtures/'paint.mcraft'),('atomic',args.fixtures/'atomic.mcraft'),
               ('catalog',args.graph_fixtures/'all-nodes.mcraft'),('controls',args.graph_fixtures/'rich-controls.mcraft'),
               ('resource',args.resource_fixture)]
        cases += [(name,args.reference_fixtures/(name+suffix)) for name,suffix in [('source-default','.mcraft'),('depth-eight','.mcraft'),
                  ('exact-path-wins','.mcraft'),('image-instance','.mcraft'),('image-depth-eight','.sbs'),('preview','.mcraft')]]
        cases += [(name,args.procedural_fixtures/(name+'.sbs')) for name in ['all-intrinsics','all-pattern-kinds','canvas']]
        cases += [(name,args.base_fixtures/(name+'.sbs')) for name in ['dynamic','dynamic-format','dynamic-pixelsize','dynamic-pixelratio','dynamic-randomseed','dynamic-tiling']]
        for label,path in cases:xml(path);agree(label,path=path)
        # Populate metadata and canvases at every native ownership level.
        rich=xml(args.graph_fixtures/'rich-controls.mcraft');graph=rich.find('content/graph');attrs=graph.find('attributes');attrs.clear()
        for name,value in [('label','Studio finish'),('category','Surfaces'),('description','Layered finish'),('author','Dobe'),('authorURL','https://example.invalid'),
                           ('tags','paint;ceramic'),('group','Library'),('userdata','editable'),('physicalSize','0.25 0.5 2')]:child(attrs,name,value)
        annotations=copy.deepcopy(next(xml(args.procedural_fixtures/'canvas.sbs').iter('dynamicValue')).find('GUIObjects'))
        graph.remove(graph.find('GUIObjects'));graph.append(copy.deepcopy(annotations))
        for port in graph.findall('paraminputs/paraminput'):
            if port.find('isConnectable') is not None:continue
            port.find('attributes/label').set('v','')
            options=port.find('defaultWidget/options')
            next(o for o in options if o.find('name').get('v')=='clamp').find('value').set('v','1')
            step=child(options,'option');child(step,'name','step');child(step,'value','.125')
            widget=port.find('defaultWidget/name')
            if widget.get('v')=='slider':widget.set('v','inputfield')
        rich_snapshot,rich_report,rich_info=agree('rich-metadata',root=rich,cold=True)
        # Standalone function annotations live on the document graph. Embedded
        # bodies keep their own annotation IDs independent of image node IDs.
        functions=xml(args.reference_fixtures/'source-default.mcraft')
        for dynamic in functions.iter('dynamicValue'):
            old=dynamic.find('GUIObjects')
            if old is not None:dynamic.remove(old)
            dynamic.append(copy.deepcopy(annotations))
        agree('all-function-canvases',root=functions,cold=True)
        patterns=xml(args.procedural_fixtures/'all-pattern-kinds.sbs');pattern=next(patterns.iter('paramsGraph'))
        old=pattern.find('GUIObjects')
        if old is not None:pattern.remove(old)
        pattern.append(copy.deepcopy(annotations))
        parameter=next(p for p in pattern.findall('paramsGraphDatas/paramsGraphData/parameters/parameter') if p.find('name').get('v')=='numberadded')
        parameter.remove(parameter.find('relativeTo'));holder=parameter.find('paramValue');holder.clear()
        dynamic=body([(1,'const_int1',[],('int',2),16)],1);dynamic.append(copy.deepcopy(annotations));holder.append(dynamic)
        agree('pattern-function-canvases',root=patterns,cold=True)
        # A regular color driven by a function belongs in node.functions, not
        # in literal parameters or processor-body values.
        parameter_root=xml(args.fixtures/'paint.mcraft')
        parameter=next(p for p in parameter_root.findall('.//compFilter/parameters/parameter') if p.find('name').get('v')=='outputcolor')
        holder=parameter.find('paramValue');holder.clear();holder.append(body([(1,'const_float4',[],('float4',[.25,.5,.75,1.]),2048)],1))
        agree('dynamic-color-parameter',root=parameter_root,cold=True)
        # A source interface that advertises a different image kind is caught
        # against actual native interface inference, even when caches agree.
        mismatched=xml(args.reference_fixtures/'image-instance.mcraft')
        for graph in mismatched.findall('content/graph'):
            graph.find('graphOutputs/graphoutput/channels').set('v','2')
        instance=next(n for n in mismatched.findall('.//compNode') if n.find('compImplementation/compInstance') is not None)
        instance.find('compOutputs/compOutput/comptype').set('v','2')
        path=out/'stale-image-kind.sbs';path.write_bytes(ET.tostring(mismatched,encoding='utf-8'));snapshot,predicted=inspect(path.read_bytes())
        observed=run('info',path)['nativePackage']
        try:model.check_native(predicted,snapshot['root'],observed)
        except ValueError:checks.append('actual inferred image kind mismatch refused')
        else:raise AssertionError('accepted stale image type')
        # Inspection must remain possible before evaluating an invalid body.
        invalid=xml(args.fixtures/'atomic.mcraft')
        processor=next(n for n in invalid.findall('.//compNode') if n.find('compImplementation/compFilter/filter') is not None and n.find('compImplementation/compFilter/filter').get('v')=='valueprocessor')
        parameter=next(p for p in processor.findall('.//parameter') if p.find('name').get('v')=='function')
        holder=parameter.find('paramValue');holder.clear();holder.append(body([(1,'get_float1',[],('text','undefined_snapshot_probe'),256)],1))
        _,_,info=agree('unevaluated-invalid-body',root=invalid)
        result=next(n for n in info['graph']['nodes'] if n['def']=='value_processor')['cooked']
        check('ordinary info evaluates the invalid body',result['error'] is not None and result['value'] is None)
        archived=container.read_native(args.fixtures/'linked-package.mcraft');external=out/'unowned.sbs';external.write_bytes(archived['members'][archived['root']])
        for label,arguments in [('extra snapshot input',['snapshot','missing.sbs','extra']),('snapshot flag',['snapshot','missing.sbs','--graph','0']),
                                ('snapshot external package',['snapshot',str(external)])]:
            result=subprocess.run([str(args.engine.resolve()),*arguments],capture_output=True,timeout=60)
            i=len(calls);(out/f'{i:03}.stdout').write_bytes(result.stdout);(out/f'{i:03}.stderr').write_bytes(result.stderr)
            calls.append({'arguments':arguments,'exit_code':result.returncode});check(label+' refused',result.returncode!=0 and not result.stdout)
        # Nonempty sibling and nested folders preserve breadth-first order.
        root=xml(args.fixtures/'paint.mcraft');content=root.find('content');template=copy.deepcopy(content.find('graph'));content.clear()
        serial=2100000000
        def group(holder,name,description):
            nonlocal serial
            serial+=1;g=child(holder,'group');child(g,'identifier',name);child(g,'uid',serial);child(g,'desc',description);return child(g,'content')
        left=group(content,'Left','Left folder');right=group(content,'Right','Right folder');nested=group(left,'Nested','Nested folder')
        for holder,name in [(left,'LeftGraph'),(right,'RightGraph'),(nested,'DeepGraph')]:
            serial+=1;g=copy.deepcopy(template);g.find('uid').set('v',str(serial));g.find('identifier').set('v',name);holder.append(g)
        agree('folder-order',root=root,cold=True)
        # Change every scalar and every field inventory in the independent full
        # model. No changed field is allowed to hide behind partial comparison.
        expected=rich_report['packages'][rich_snapshot['root']];pending=[(expected,())];mutations=0
        while pending:
            item,path=pending.pop()
            if type(item) in (dict,list):
                pending.extend((v,path+(k,)) for k,v in (item.items() if type(item) is dict else enumerate(item)))
                if type(item) is dict:
                    bad=copy.deepcopy(expected);target=bad
                    for part in path:target=target[part]
                    target['unexpectedNativeField']=None
                else:continue
            else:
                bad=copy.deepcopy(expected);target=bad
                for part in path[:-1]:target=target[part]
                target[path[-1]]=not item if type(item) is bool else item+1 if type(item) in (int,float) else item+' changed' if type(item) is str else 'unexpected'
            try:model.check_native(rich_report,rich_snapshot['root'],bad)
            except ValueError:mutations+=1
            else:raise AssertionError('accepted changed field '+str(path))
        check('every field mutation refused',mutations>500)
        check('all original fixtures unchanged',all(path.read_bytes()==data for path,data in originals.items()))
        (out/'evidence.json').write_text(json.dumps({'passed':True,'checks':checks,'native_calls':len(calls),'field_mutations_refused':mutations,
            'serialized_native_model_complete':True,'engine_admission_complete':False,'remote_actions':False,
            'scope':'full serialized editable state; resource payloads, native execution budgets, arbitrary-color cold fidelity and external package handoff remain separate'},indent=2)+'\n')
        print(json.dumps({'passed':len(checks),'native_calls':len(calls),'field_mutations_refused':mutations}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
