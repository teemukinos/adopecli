#!/usr/bin/env python3
"""Actual bounded Material evaluation, dynamic bases, nested budgets and failed jobs."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_compute as compute, material_document as document, material_source as source
from studio_runtime.store import Store
from studio_runtime.worker import Worker
from material_source_check import recipe, element, scalar, parameter
from material_procedural_check import body


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','fixtures','base-fixtures','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[];originals={};original_run=document.run
    os.environ['PATH']=str(args.engine.resolve().parent)+':/usr/bin:/bin'
    def tracked(command,*a,**kw):
        calls.append(list(map(str,command)));return original_run(command,*a,**kw)
    document.run=tracked
    def check(label,ok=True):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def graph(data):
        p=document.inspect_bytes(data);g=p['model']['packages'][p['container']['root']]['graphs'][0]
        return '/'.join(filter(None,(g.get('folder'),g['name'])))
    def cook(label,data):
        path=out/(label+'.input');path.write_bytes(data);result=compute.cook(out,path,graph(data),args.engine)
        check(label+' full finite cook without source changes',result['full_size'] and result['finite_outputs'] and path.read_bytes()==data and result['source_bytes_unchanged'])
        (out/(label+'.json')).write_text(json.dumps(result,indent=2)+'\n');return result,path
    def read(path):
        data=path.read_bytes();originals[path]=data;return data
    def refused(label,data,part):
        path=out/(label+'.input');path.write_bytes(data)
        try:compute.cook(out,path,graph(data),args.engine)
        except ValueError as error:check(label+' refuses explicit native failure',part in str(error));return path
        else:raise AssertionError('accepted '+label)
    def bare(data):
        p=document.inspect_bytes(data)['container'];return ET.fromstring(p['members'][p['root']])
    try:
        data,_=source.create({'package.sbs':recipe()});result,path=cook('original',data)
        check('root counters include all five image nodes and output bridges',result['usage']=={'node_visits':5,'output_texels':5*32*32})
        check('original output geometry matches authored size',all(o['width']==32 and o['height']==32 for n in result['nodes'] for o in n['outputs']))
        check('roughness pixels have exactly zero lower and upper range',result['nodes'][-1]['outputs'][0]['minimum']==0 and result['nodes'][-1]['outputs'][0]['maximum']==0)
        for name in ['dynamic.sbs','dynamic-randomseed.sbs','dynamic-format.sbs','dynamic-pixelsize.sbs','dynamic-pixelratio.sbs','dynamic-tiling.sbs','owned-call-context.sbs']:
            actual,_=cook(name[:-4],read(args.base_fixtures/name))
            if name=='owned-call-context.sbs':check('instances share aggregate visit counters',actual['usage']['node_visits']>len(actual['nodes']))
            else:check(name+' dynamic base values recorded',any(n['baseValues'] for n in actual['nodes']))
        ordered=bare(data);holder=ordered.find('.//compNode/compImplementation/compFilter/parameters')
        for name,program in [
            ('outputsize',body([(1,'const_int2',[],('int2',[7,5]),32)],1)),
            ('pixelsize',body([(1,'get_float2',[],('text','$size'),512)],1)),
            ('pixelratio',body([(1,'const_int1',[],('int',1),16)],1)),
            ('tiling',body([(1,'get_integer1',[],('text','$pixelratio'),16)],1))]:
            p=ET.SubElement(holder,'parameter');ET.SubElement(p,'name',v=name);ET.SubElement(p,'relativeTo',v='0');ET.SubElement(p,'paramValue').append(program)
        ordered_result,_=cook('dynamic-context-order',ET.tostring(ordered,encoding='utf-8'))
        resolved=ordered_result['nodes'][0]['base']
        check('dynamic pixel size observes newly resolved dimensions',resolved['size']==[128,32] and resolved['pixelSize']==[128.,32.])
        check('dynamic tiling observes newly resolved pixel ratio',resolved['pixelRatio']==1 and resolved['tiling']==[True,False])
        nested=bare(read(args.base_fixtures/'owned-call-context.sbs'));child=nested.findall('.//graph')[1]
        holder=child.find('compNodes/compNode/compImplementation/compFilter/parameters')
        for item in list(holder):
            if item.find('name').get('v')=='outputsize':holder.remove(item)
        p=ET.SubElement(holder,'parameter');ET.SubElement(p,'name',v='outputsize');ET.SubElement(p,'relativeTo',v='0');ET.SubElement(ET.SubElement(p,'paramValue'),'constantValueInt2',v='13 13')
        refused('nested-node-budget',ET.tostring(nested,encoding='utf-8'),'Child: Dobe node raster budget')
        atomic=read(args.fixtures/'atomic.mcraft');tree=bare(atomic)
        new=body([(1,'const_float1',[],('float',.25),256),(2,'const_float1',[],('float',.5),256),(3,'add',[1,2],None,256)],3)
        target=next(tree.iter('dynamicValue'));parent=next(p for p in tree.iter() if target in list(p));position=list(parent).index(target);parent.remove(target);parent.insert(position,new)
        actual,_=cook('sum',ET.tostring(tree,encoding='utf-8'))
        check('real procedural sum equals independent arithmetic oracle',any(o.get('value')=={'t':'float','v':.75} for n in actual['nodes'] for o in n['outputs']))
        overflow=body([(1,'const_float1',[],('float',1e38),256),(2,'const_float1',[],('float',1e38),256),(3,'mul',[1,2],None,256)],3)
        parent.remove(new);parent.insert(position,overflow)
        bad_numeric=refused('numeric-overflow',ET.tostring(tree,encoding='utf-8'),'non-finite')
        # Graph size is allowed authoring state. Execution refuses oversized
        # resolved rasters before allocating a native placeholder or output.
        large=bare(data);large.find('.//option/value').set('v','13x13')
        large_bytes=ET.tostring(large,encoding='utf-8');large_path=refused('node-budget',large_bytes,'node raster budget')
        large.find('.//option/value').set('v','12x12')
        refused('aggregate-budget',ET.tostring(large,encoding='utf-8'),'aggregate evaluation budget')
        dynamic=bare(data);first=dynamic.find('.//compNode/compImplementation/compFilter/parameters')
        p=ET.SubElement(first,'parameter');ET.SubElement(p,'name',v='outputsize');ET.SubElement(p,'relativeTo',v='0');pv=ET.SubElement(p,'paramValue')
        pv.append(body([(1,'const_int2',[],('int2',[13,13]),32)],1))
        refused('dynamic-size-budget',ET.tostring(dynamic,encoding='utf-8'),'node raster budget')
        for arguments in [('evaluate',path),('evaluate',path,'999'),('evaluate',path,'0','extra'),('evaluate',path,'0','--full')]:
            process=subprocess.run([str(args.engine.resolve()),*map(str,arguments)],capture_output=True,timeout=30);calls.append(list(map(str,arguments)))
            check('private route rejects missing extra invalid or flagged graph arguments',process.returncode!=0 and not process.stdout)
        try:compute.cook(out,path,'absent',args.engine)
        except ValueError:check('unknown graph refuses before native')
        else:raise AssertionError('accepted absent graph')
        before=len(calls)
        try:compute.cook(out,path,'Original',args.engine,cancelled=lambda:True)
        except ValueError:check('pre-cancelled cook refuses',len(calls)==before+1)
        else:raise AssertionError('accepted cancelled cook')
        # The public durable operation must fail the entire job on native
        # numeric errors. Exit status zero from an old info route is insufficient.
        state=out/'store';store=Store(state);records=[]
        for name,input_path,success in [('good',path,True),('overflow',bad_numeric,False),('budget',large_path,False)]:
            project=store.create_project('local','Cook '+name)['id'];identity=store.import_asset('local',project,input_path)['id']
            initial=store.submit('local',project,'material.import',{'asset':identity},'import');Worker(store).run_one();initial=store.get_job('local',initial['id']);check(name+' source remains editable',initial['state']=='succeeded')
            prior=initial['result_revision'];current=store.get_revision('local',prior);initial_file=next(f for f in current['files'] if f['path']=='native/original.input')
            queued=store.submit('local',project,'material.cook',{'graph':graph(input_path.read_bytes())},'cook',prior);Worker(store).run_one();job=store.get_job('local',queued['id']);records.append(job)
            check(name+' durable cook state',job['state']==('succeeded' if success else 'failed'))
            if success:
                result=store.get_revision('local',job['result_revision']);bundle=out/'cooked-bundle';store.checkout('local',result['id'],bundle)
                check('durable cook retains original and current source',hashlib.sha256((bundle/'native/original.input').read_bytes()).hexdigest()==initial_file['sha256'] and (bundle/'native/document.mcraft').read_bytes()==data)
                report=json.loads((bundle/'exports/cook.json').read_text());check('durable native cook evidence published',result['validation']['cook_performed'] and report['finite_outputs'] and report['usage']['node_visits']==5)
            else:check(name+' failed cook publishes nothing',job['result_revision'] is None and store.get_project('local',project)['head']==prior)
        check('all upstream inputs unchanged',all(p.read_bytes()==data for p,data in originals.items()))
        (out/'jobs.json').write_text(json.dumps(records,indent=2)+'\n')
        result={'passed':True,'checks':checks,'native_attempts':len(calls),'durable_jobs':6,'durable_cook_jobs':3,'native_calls_exclude_worker_children':True,
                'dynamic_bases_qualified':True,'instance_budget_shared':True,'finite_output_check':True,'temporary_allocations_proven_bounded':False,
                'outer_worker_limits_required':True,'map_export_qualified':False,'installed_qualification':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_attempts':len(calls),'durable_jobs':6}))
    except Exception as error:(out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:document.run=original_run;(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
