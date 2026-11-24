#!/usr/bin/env python3
"""Outer graph schemas against maintained native authoring and cold files."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_container as container,material_resources as resources,material_graphs as graphs
from studio_runtime import material_node_catalog as catalog


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--fixtures',type=Path,required=True)
    ap.add_argument('--upstream',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[]
    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def run(*arguments):
        result=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=60)
        index=len(calls);(out/f'{index:03}.stdout').write_bytes(result.stdout);(out/f'{index:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments':list(map(str,arguments)),'exit_code':result.returncode})
        if result.returncode:raise AssertionError(result.stderr.decode()[:1000])
        return json.loads(result.stdout)
    def inspect(path):
        profile=container.read_native(path);return profile,graphs.inspect(profile,resources.inspect(profile))
    def parsed(root):
        source=container.inspect_bytes(ET.tostring(root,encoding='utf-8'));return source['xml'][source['root']]['root']
    def refused(label,root):
        try:graphs.graph(parsed(root))
        except ValueError:checks.append(label)
        else:raise AssertionError('accepted '+label)
    def agree(label,path):
        profile,report=inspect(path);info=run('info',path)
        graphs.check_native(report,profile['root'],info['nativePackage']);check(label+' actual native graph topology',True)
        return profile,report,info
    try:
        mapping=(args.upstream/'crates/formats/src/sbs/filter_map.rs').read_bytes()
        check('mapping source checksum',hashlib.sha256(mapping).hexdigest()==catalog.MAPPING_SHA256)
        observed=run('nodes');contract={d['id']:{'inputs':[p['id'] for p in d['inputs']], 'outputs':[p['id'] for p in d['outputs']],
            'parameters':{p['id']:{'default':p['default'],'options':len(p['options'])} for p in d['params']}} for d in observed}
        check('all 29 native node contracts match',contract==catalog.DEFINITIONS and len(contract)==29 and len(catalog.FILTERS)==25)
        for name in ('paint.mcraft','atomic.mcraft','embedded.mcraft','portable-source.sbs'):
            agree(name,args.fixtures/name)
        _,linked=inspect(args.fixtures/'linked-package.mcraft');check('archived graph inventory without native dependency access',len(linked['graphs'])==2)
        empty=out/'empty.mcraft';run('new','empty',empty,'--size','64','--name','Catalog')
        script={'open':str(empty),'steps':[],'save':str(out/'all-nodes.mcraft')}
        for definition in contract:
            params={'def':definition,'at':[len(script['steps'])*180,0]}
            if definition in ('input_color','input_grayscale','input_value','output'):params['params']={'identifier':definition}
            script['steps'].append({'id':'graph.node.add','params':params})
        recipe=out/'all-nodes.json';recipe.write_text(json.dumps(script));run('batch',recipe)
        canonical=out/'all-nodes.mcraft';profile,report,info=agree('all native node kinds',canonical)
        expected=next(iter(report['graphs'].values()))
        check('29 definitions represented in actual editable graph',{n['definition'] for n in expected['nodes'].values()}==set(contract))
        cold=out/'all-nodes-cold.mcraft';run('run',canonical,'file.save',json.dumps({'path':str(cold)}))
        container.check_preservation(profile,container.read_native(cold));agree('all node kinds cold',cold);check('all node kinds exact cold member preservation',True)
        with zipfile.ZipFile(canonical) as z:all_root=ET.fromstring(z.read('package.sbs')).find('content/graph')
        with zipfile.ZipFile(args.fixtures/'paint.mcraft') as z:root=ET.fromstring(z.read('package.sbs')).find('content/graph')
        cases=[
            ('unknown graph field',lambda e:ET.SubElement(e,'future')),
            ('unknown graph type',lambda e:e.find('graphtype').set('v','future')),
            ('duplicate graph identity',lambda e:e.append(copy.deepcopy(e.find('identifier')))),
            ('unknown metadata',lambda e:ET.SubElement(e.find('attributes'),'future',{'v':'x'})),
            ('size would clamp',lambda e:e.find('options/option/value').set('v','14x6')),
            ('malformed size',lambda e:e.find('options/option/value').set('v','6 x 6')),
            ('duplicate option',lambda e:e.find('options').append(copy.deepcopy(e.find('options/option')))),
            ('ignored option',lambda e:e.find('options/option/name').set('v','future')),
            ('ignored root format',lambda e:e.find('root/rootOutputs/rootOutput/format').set('v','1')),
            ('missing root output',lambda e:e.find('root/rootOutputs').remove(e.find('root/rootOutputs/rootOutput'))),
            ('empty output label',lambda e:e.find('graphOutputs/graphoutput/attributes/label').set('v','')),
            ('lost output group',lambda e:e.find('graphOutputs/graphoutput/group').set('v','Other')),
            ('invalid output usage',lambda e:e.find('.//usage/name').set('v','future')),
            ('duplicate node ID',lambda e:e.findall('compNodes/compNode/uid')[1].set('v',e.find('compNodes/compNode/uid').get('v'))),
            ('unknown node field',lambda e:ET.SubElement(e.find('compNodes/compNode'),'future')),
            ('multiple implementation',lambda e:e.find('.//compImplementation').append(copy.deepcopy(e.find('.//compFilter')))),
            ('unknown filter',lambda e:e.find('.//filter').set('v','future')),
            ('ignored filter parameter',lambda e:e.find('.//compFilter/parameters/parameter/name').set('v','future')),
            ('ignored relative mode',lambda e:e.find('.//compFilter/parameters/parameter/relativeTo').set('v','2')),
            ('duplicate parameter',lambda e:e.find('.//compFilter/parameters').append(copy.deepcopy(e.find('.//compFilter/parameters/parameter')))),
            ('wrong output source',lambda e:e.find('.//connRefOutput').set('v','1')),
            ('missing source',lambda e:e.find('.//connRef').set('v','1')),
            ('unknown destination port',lambda e:e.find('.//connection/identifier').set('v','future')),
            ('duplicate wire destination',lambda e:e.find('.//connections').append(copy.deepcopy(e.find('.//connection')))),
        ]
        for label,change in cases:
            altered=copy.deepcopy(root);change(altered);refused(label,altered)
        # Prior engine qualification reproduced silent label loss. The maintained
        # Dobe reader now restores the custom title without changing other fields.
        altered=copy.deepcopy(root);altered.find('graphOutputs/graphoutput/attributes/label').set('v','Custom label')
        full=ET.fromstring(profile['members']['package.sbs']);content=full.find('content');content.clear();content.append(altered)
        source=out/'custom-label.sbs';source.write_bytes(ET.tostring(full,encoding='utf-8'));original=source.read_bytes()
        native=run('info',source);label_node=native['nativePackage']['graphs'][0]['nodes'][1]
        check('maintained reader restores custom output label',label_node['label']=='Custom label' and not native['package']['warnings'])
        before=copy.deepcopy(full);before.find('content/graph/graphOutputs/graphoutput/attributes/label').set('v',before.find('content/graph/graphOutputs/graphoutput/identifier').get('v'))
        baseline=out/'original-label.sbs';baseline.write_bytes(ET.tostring(before,encoding='utf-8'));previous=run('info',baseline)['nativePackage']
        previous['graphs'][0]['nodes'][1]['label']='Custom label'
        check('precise label change preserves all other native fields',previous==native['nativePackage'])
        target=out/'custom-label.mcraft';run('run',source,'file.save',json.dumps({'path':str(target)}));admitted,_,_=agree('custom output label',target)
        cold_label=out/'custom-label-cold.mcraft';run('run',target,'file.save',json.dumps({'path':str(cold_label)}))
        container.check_preservation(admitted,container.read_native(cold_label));check('custom output label exact cold preservation and original unchanged',source.read_bytes()==original)
        # Invalid curves, defaults and bridge ports are checked against a native
        # authored full catalog document rather than guessed XML structures.
        for label,change in [
            ('duplicate input bridge target',lambda e:e.findall('.//compInputBridge/entry')[1].set('v',e.find('.//compInputBridge/entry').get('v'))),
            ('invalid enum would clamp',lambda e:next(p for p in e.findall('.//compFilter/parameters/parameter') if p.find('name').get('v')=='blendingmode').find('.//constantValueInt32').set('v','999')),
            ('unknown array',lambda e:e.find('.//paramsArray/name').set('v','future')),
            ('curve flags would change',lambda e:next(p for p in e.findall('.//paramsArray/paramsArrayCells/paramsArrayCell/parameters/parameter') if p.find('name').get('v')=='isLocked').find('.//constantValueBool').set('v','1')),
            ('ignored input widget',lambda e:e.find('paraminputs/paraminput/defaultWidget/name').set('v','slider')),
            ('wrong input default type',lambda e:setattr(e.find('paraminputs/paraminput/defaultValue/constantValueFloat4'),'tag','constantValueFloat3')),
        ]:
            altered=copy.deepcopy(all_root);change(altered);refused(label,altered)
        def filter_node(root,name):return next(n for n in root.findall('compNodes/compNode') if n.find('compImplementation/compFilter/filter') is not None and n.find('compImplementation/compFilter/filter').get('v')==name)
        def wire(node,source,label):
            holder=node.find('connections')
            if holder is None:holder=ET.SubElement(node,'connections')
            entry=ET.SubElement(holder,'connection')
            for tag,val in [('identifier',label),('connRef',source.find('uid').get('v')),('connRefOutput',source.find('compOutputs/compOutput/uid').get('v'))]:ET.SubElement(entry,tag,{'v':val})
        altered=copy.deepcopy(all_root);node=filter_node(altered,'blend');wire(node,node,'source');refused('disconnected image cycle',altered)
        altered=copy.deepcopy(all_root);node=filter_node(altered,'dyngradient');source=filter_node(altered,'uniform')
        wire(node,source,'input2');wire(node,source,'inputgradient');refused('aliased ports cannot duplicate one native input',altered)
        altered=copy.deepcopy(all_root);wire(filter_node(altered,'pixelprocessor'),filter_node(altered,'uniform'),'input:256');refused('image input exceeds native 256-slot limit',altered)
        advanced=copy.deepcopy(all_root);wire(filter_node(advanced,'pixelprocessor'),filter_node(advanced,'uniform'),'input:255')
        full=ET.fromstring(profile['members']['package.sbs']);content=full.find('content');content.clear();content.append(advanced)
        path=out/'last-image-port.sbs';path.write_bytes(ET.tostring(full,encoding='utf-8'));_,boundary,_=agree('last image input slot',path)
        check('indexed image port preserves native identity',next(iter(boundary['graphs'].values()))['connections'][0]['toPort']=='input255')
        # Native editable exposed controls cover every scalar/vector type,
        # dropdown metadata and displayed colors, plus all six base parameters.
        rich=copy.deepcopy(all_root)
        def add(parent,tag,value=None):return ET.SubElement(parent,tag,{} if value is None else {'v':str(value)})
        for index,(code,kind) in enumerate(graphs.VALUE_TYPES.items()):
            entry=add(rich.find('paraminputs'),'paraminput');add(entry,'identifier','exposed_'+kind);add(entry,'uid',1800000000+index)
            attrs=add(entry,'attributes');add(attrs,'label',kind+' label');add(attrs,'description','Editable '+kind);add(entry,'type',code)
            default=add(entry,'defaultValue');tag='String' if kind=='text' else 'Bool' if kind=='bool' else 'Int32' if kind=='int' else 'Float1' if kind=='float' else kind.title()
            value='value' if kind=='text' else '1' if kind=='bool' else ' '.join(['0']*int(kind[-1])) if kind[-1].isdigit() else '0'
            add(default,'constantValue'+tag,value);widget=add(entry,'defaultWidget');add(widget,'name','text' if kind=='text' else 'buttons' if kind=='bool' else 'slider')
            opts=add(widget,'options')
            for key,val in [('min','0'),('max','1'),('clamp','0')]:
                option=add(opts,'option');add(option,'name',key);add(option,'value',val)
            add(entry,'group','Controls')
        # Additional controls reuse the exact native input grammar above.
        for index,kind in enumerate(('dropdown','color'),20):
            original=next(p for p in rich.findall('paraminputs/paraminput') if p.find('identifier').get('v')==('exposed_int' if kind=='dropdown' else 'exposed_float4'))
            entry=copy.deepcopy(original);entry.find('identifier').set('v',kind);entry.find('uid').set('v',str(1800000000+index))
            entry.find('defaultWidget/name').set('v','dropdownlist' if kind=='dropdown' else 'color')
            opts=entry.find('defaultWidget/options');option=add(opts,'option');add(option,'name','parameters' if kind=='dropdown' else 'valueInterpretation');add(option,'value','0;0;Low;1;High' if kind=='dropdown' else 'color')
            rich.find('paraminputs').append(entry)
        uniform=next(n for n in rich.findall('compNodes/compNode') if n.find('compImplementation/compFilter/filter') is not None and n.find('compImplementation/compFilter/filter').get('v')=='uniform')
        holder=uniform.find('compImplementation/compFilter/parameters')
        for name,tag,value in [('outputsize','Int2','6 6'),('format','Int32','3'),('pixelsize','Float2','1 1'),('pixelratio','Int32','1'),('tiling','Int32','1'),('randomseed','Int32','42')]:
            parameter=add(holder,'parameter');add(parameter,'name',name);add(parameter,'relativeTo','0');add(add(parameter,'paramValue'),'constantValue'+tag,value)
        full=ET.fromstring(profile['members']['package.sbs']);content=full.find('content');content.clear();content.append(rich)
        source=out/'rich-controls.sbs';source.write_bytes(ET.tostring(full,encoding='utf-8'))
        _,_,rich_info=agree('rich controls and base parameters',source)
        check('all exposed value/control types retained',len(rich_info['nativePackage']['graphs'][0]['exposed'])==12)
        target=out/'rich-controls.mcraft';run('run',source,'file.save',json.dumps({'path':str(target)}));admitted,_,before=agree('canonical rich controls',target)
        cold_rich=out/'rich-controls-cold.mcraft';run('run',target,'file.save',json.dumps({'path':str(cold_rich)}));_,_,after=agree('cold rich controls',cold_rich)
        container.check_preservation(admitted,container.read_native(cold_rich));check('rich controls preserve full native model and member bytes',before['nativePackage']==after['nativePackage'])
        for label,change in [
            ('ignored widget option',lambda e:e.find('paraminputs/paraminput/defaultWidget/options/option/name').set('v','future')),
            ('oversized base size',lambda e:next(p for p in e.findall('.//compFilter/parameters/parameter') if p.find('name').get('v')=='outputsize').find('.//constantValueInt2').set('v','14 14')),
            ('invalid base format',lambda e:next(p for p in e.findall('.//compFilter/parameters/parameter') if p.find('name').get('v')=='format').find('.//constantValueInt32').set('v','4')),
            ('nonpositive pixel size',lambda e:next(p for p in e.findall('.//compFilter/parameters/parameter') if p.find('name').get('v')=='pixelsize').find('.//constantValueFloat2').set('v','0 1')),
        ]:
            altered=copy.deepcopy(rich);change(altered);refused(label,altered)
        full=ET.fromstring(profile['members']['package.sbs']);standalone=add(full.find('content'),'function')
        add(standalone,'identifier','Reusable');add(standalone,'uid',1900000000);add(standalone,'attributes');add(standalone,'paraminputs');add(standalone,'type',256)
        dynamic=add(add(standalone,'paramValue'),'dynamicValue');add(dynamic,'rootnode',1900000001)
        n=add(add(dynamic,'paramNodes'),'paramNode');add(n,'uid',1900000001);add(n,'function','const_float1');add(n,'type',256)
        add(add(n,'GUILayout'),'gpos','0 0 0');add(n,'connections');d=add(add(n,'funcDatas'),'funcData');add(d,'name','const_float1');add(add(d,'constantValue'),'constantValueFloat1','0.25')
        source=out/'standalone.sbs';source.write_bytes(ET.tostring(full,encoding='utf-8'));_,standalone_report,_=agree('standalone function graph',source)
        check('standalone and image graph kinds retained',len(standalone_report['graphs'])==2 and sum('function' in g for g in standalone_report['graphs'].values())==1)
        target=out/'standalone.mcraft';run('run',source,'file.save',json.dumps({'path':str(target)}));admitted,standalone_report,standalone_info=agree('canonical standalone graph',target)
        cold_standalone=out/'standalone-cold.mcraft';run('run',target,'file.save',json.dumps({'path':str(cold_standalone)}))
        container.check_preservation(admitted,container.read_native(cold_standalone));check('standalone function cold member preservation',True)
        altered=copy.deepcopy(standalone_info['nativePackage']);altered['graphs'][1]['function']['nodes'][0]['value']['v']=.75
        try:graphs.check_native(standalone_report,admitted['root'],altered)
        except ValueError:checks.append('standalone function native model mismatch')
        else:raise AssertionError('accepted altered standalone body')
        for key,new in [('MAX_PORTS',0),('MAX_ARRAY_CELLS',1)]:
            old=getattr(graphs,key);setattr(graphs,key,new)
            try:refused('local budget '+key,all_root)
            finally:setattr(graphs,key,old)
        for key in ('MAX_GRAPHS','MAX_NODES'):
            old=getattr(graphs,key);setattr(graphs,key,0)
            try:
                try:inspect(canonical)
                except ValueError:checks.append('aggregate '+key)
                else:raise AssertionError('accepted '+key)
            finally:setattr(graphs,key,old)
        for key in ('size','nodes','connections'):
            altered=copy.deepcopy(info['nativePackage']);altered['graphs'][0][key]=[{'from':1,'fromPort':'output','to':2,'toPort':'input'}] if key=='connections' else []
            try:graphs.check_native(report,profile['root'],altered)
            except ValueError:checks.append('native mismatch '+key)
            else:raise AssertionError('accepted native mismatch '+key)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'native_definitions':29,'filter_mappings':25,'engine_admission_complete':False,'remote_actions':False,
            'scope':'outer graph schema, native parameter contracts and exact native topology; full parameter semantics, type/reference resolution and whole-job work remain required'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls),'evidence':str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
