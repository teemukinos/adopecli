#!/usr/bin/env python3
"""Typed Material changes preserve unrequested source bytes and native state."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_container as container,material_document as document,material_revision as revision
from studio_runtime import material_procedural as proc
from studio_runtime.material_model import members
from studio_runtime.material_resources import children,scalar


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','fixtures','graph-fixtures','model-fixtures','base-fixtures','document-fixtures','resource-fixture','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];originals={};invocations=[];run=document.run
    def tracked(command,*a,**kw):invocations.append(command[1]);return run(command,*a,**kw)
    document.run=tracked
    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def read(path):
        data=path.read_bytes();originals[path]=data;return document.inspect_bytes(data)
    def first(profile):return next(iter(profile['graphs']['graphs'].items()))
    def edit(profile,kind,**selectors):
        key,_=first(profile);e={'kind':kind,'package':key[0],'graph':key[1],**selectors}
        e['expected']=revision.semantic(revision.target(profile,e),kind);return e
    def agree(label,profile,edits):
        source=out/(label+'.input');source.write_bytes(profile['container']['source_bytes']);original=source.read_bytes();dest=out/label
        report=revision.prepare(out,source,dest,args.engine,profile['container']['source_sha256'],edits)
        after=document.read_native(dest/'native/document.mcraft')
        check(label+' verified native cold revision',report['native_verified'] and report['native_cold_reopen'])
        check(label+' source unchanged',source.read_bytes()==original)
        check(label+' requested source values',all(revision.equal(revision.semantic(revision.target(after,e),e['kind']),revision.literal(e['value'])[1]) for e in edits))
        check(label+' original binary resources unchanged',all(after['container']['members'][name]==data for name,data in profile['container']['members'].items() if not name.endswith('.sbs')))
        check(label+' no staging file remains',not dest.with_name(dest.name+'.revision-input').exists())
        check(label+' no rendering claim',not report['engine_admission_complete'])
        return after,report
    def refused(label,profile,edits,digest=None):
        start=len(invocations)
        try:revision.revise_bytes(profile['container']['source_bytes'],digest or profile['container']['source_sha256'],edits)
        except ValueError:check(label+' refuses before native',len(invocations)==start)
        else:raise AssertionError('accepted '+label)
    try:
        paint=read(args.fixtures/'paint.mcraft');key,graph=first(paint);node_id=next(iter(graph['nodes']))
        color=edit(paint,'node.parameter',node=str(node_id),name='outputcolor');color['value']={'t':'float4','v':[.2,.4,.8,1.]}
        after,_=agree('color',paint,[color])
        # The complete member must be exactly the old bytes with one chosen
        # scalar span replaced. This catches edits to an equal-valued sibling.
        element=revision.target(paint,color);parsed=paint['container']['xml'][key[0]];index=next(i for i,e in enumerate(parsed['elements']) if e is element);start,end=parsed['spans'][index]
        replacement,_=revision.encode(element,color['value'],color['kind']);old=paint['container']['members'][key[0]]
        check('single edit has no unrelated lexical changes',after['container']['members'][key[0]]==old[:start]+replacement+old[end:])
        pos=edit(paint,'node.position',node=str(node_id));pos['value']={'t':'float2','v':[137.,-42.]}
        size=edit(paint,'graph.size');size['value']={'t':'int2','v':[7,5]}
        out_name=next(iter(graph['outputs'].values()))['name'];label=edit(paint,'output.label',name=out_name);label['value']={'t':'text','v':'Paint — base'}
        agree('layout-and-output',paint,[pos,size,label])
        base=read(args.base_fixtures/'negative-seed.sbs');seed=edit(base,'graph.base',name='randomseed');seed['value']={'t':'int','v':17};agree('graph-base',base,[seed])
        controls=read(args.graph_fixtures/'rich-controls.mcraft');_,g=first(controls)
        defaults={'bool':False,'int':1,'int2':[1,2],'int3':[1,2,3],'int4':[1,2,3,4],'float':.375,'float2':[.125,.875],
                  'float3':[.125,.375,.875],'float4':[.125,.375,.875,1.],'text':'Ä <Desk> & "finish"\nNext\trow'}
        edits=[]
        for port in g['inputs'].values():
            if port['connectable']:continue
            e=edit(controls,'input.default',name=port['name']);kind=e['expected']['t'];e['value']={'t':kind,'v':defaults[kind]};edits.append(e)
        revised,report=agree('all-exposed-types',controls,edits)
        check('dropdown redundant source value follows requested default',any(e['derived_source_updates'] for e in report['edits']))
        check('unrequested dropdown labels remain identical',next(p for p in revised['model']['packages'][key[0]]['graphs'][0]['exposed'] if p['id']=='dropdown')['options']==['Low','High'])
        rich=read(args.model_fixtures/'rich-metadata.sbs');meta=edit(rich,'graph.attribute',name='description');meta['value']={'t':'text','v':'Ü & > "finish"\nPrecision'};agree('metadata',rich,[meta])
        # Same parser handles explicit close tags, BOMs, quote styles and UTF-8
        # before the edited field; source spans are byte offsets, not characters.
        root=rich['container']['source_bytes'];root=root.replace(b'<description v="Layered finish" />',b"<description v='Layered finish'></description>")
        root=b'\xef\xbb\xbf'+root.replace(b'Studio finish','Ä > finish'.encode())
        check('lexical fixture has explicit quotes and Unicode before edit',b"<description v='Layered finish'></description>" in root and 'Ä > finish'.encode() in root)
        lexical=document.inspect_bytes(root);agree('lexical-xml',lexical,[meta])
        atomic=read(args.fixtures/'atomic.mcraft');a_key,a_graph=first(atomic)
        for (package,body_index),body in atomic['graphs']['procedural']['functions'].items():
            node=next((n for n in body['model']['nodes'] if n['op']=='const_float1'),None)
            if node:break
        constant=edit(atomic,'function.constant',body=body_index,node=str(node['id']));constant['value']={'t':'float','v':.375};agree('function-constant',atomic,[constant])
        outer_id,outer=next((i,n) for i,n in a_graph['nodes'].items() if n['definition']=='fx_map')
        pattern=next(n for n in outer['pattern']['model']['nodes'] if 'opacity' in n['parameters'])
        pattern_edit=edit(atomic,'pattern.parameter',node=str(outer_id),pattern_node=str(pattern['id']),name='opacity')
        pattern_edit['value']={'t':pattern_edit['expected']['t'],'v':.375 if pattern_edit['expected']['t']=='float' else [.125,.375,.875,1.]}
        agree('pattern-parameter',atomic,[pattern_edit])
        catalog=read(args.graph_fixtures/'all-nodes.mcraft');c_key,c_graph=first(catalog)
        gradient_id=next(i for i,n in c_graph['nodes'].items() if n['definition']=='gradient_map')
        root=catalog['resources']['packages'][c_key[0]]['graphs'][c_key[1]]['element'];node=members(revision.by_id(members(root)['compNodes'],str(gradient_id)))
        impl=members(proc.single(node['compImplementation']));array=members(revision.entry(impl['paramsArrays'],'gradientrgba'));cell=children(array['paramsArrayCells'])[0];cell_id=scalar(members(cell)['uid'])
        gradient=edit(catalog,'array.cell',node=str(gradient_id),array='gradientrgba',cell=cell_id,name='value');gradient['value']={'t':'float4','v':[.5,.5,.5,1.]};after,_=agree('gradient-cell',catalog,[gradient])
        actual=next(n for n in after['model']['packages'][c_key[0]]['graphs'][0]['nodes'] if n['def']=='gradient_map')['params']['gradient']['v']['keys'][0]['color']
        check('gradient revision stays linear',actual==[.5,.5,.5,1.])
        resource=read(args.resource_fixture);_,r_graph=first(resource);move=edit(resource,'node.position',node=str(next(iter(r_graph['nodes']))));move['value']={'t':'float2','v':[150.,75.]};agree('resource-preservation',resource,[move])
        drift=read(args.document_fixtures/'color-3/native/document.mcraft');_,d_graph=first(drift);move=edit(drift,'node.position',node=str(next(iter(d_graph['nodes']))));move['value']={'t':'float2','v':[200.,100.]};changed,_=agree('unrequested-color-preservation',drift,[move])
        d_root=drift['container']['root'];check('unedited problematic color retains exact native bits',drift['model']['packages'][d_root]['graphs'][0]['nodes'][0]['params']['color']==changed['model']['packages'][d_root]['graphs'][0]['nodes'][0]['params']['color'])
        refused('stale source digest',paint,[color],digest='0'*64)
        bad=copy.deepcopy(color);bad['expected']['v'][0]=.99;refused('wrong expected value',paint,[bad])
        refused('duplicate target',paint,[color,color])
        bad=copy.deepcopy(color);bad['value']={'t':'float4','v':[True,0,0,1]};refused('Boolean numeric coercion',paint,[bad])
        bad=copy.deepcopy(color);bad['value']={'t':'int4','v':[1,1,1,1]};refused('implicit native type change',paint,[bad])
        bad=copy.deepcopy(color);bad['value']['v'][0]=2e16;refused('nonlinear color overflow',paint,[bad])
        bad=copy.deepcopy(size);bad['value']['v']=[14,4];refused('oversized graph',paint,[bad])
        bad=copy.deepcopy(color);bad['node']='999999';refused('missing node',paint,[bad])
        bad=copy.deepcopy(meta);bad['value']['v']='bad\0text';refused('forbidden XML character',rich,[bad])
        bad=copy.deepcopy(constant);bad['body']=-1;refused('unknown function body',atomic,[bad])
        source=out/'color.input';existing=out/'occupied';existing.mkdir();(existing/'sentinel').write_text('keep')
        try:revision.prepare(out,source,existing,args.engine,paint['container']['source_sha256'],[color])
        except ValueError:check('existing destination preserved',(existing/'sentinel').read_text()=='keep')
        else:raise AssertionError('replaced existing destination')
        staged=out/'blocked.revision-input';staged.write_text('keep staged input')
        try:revision.prepare(out,source,out/'blocked',args.engine,paint['container']['source_sha256'],[color])
        except FileExistsError:check('existing staging input preserved',staged.read_text()=='keep staged input' and not (out/'blocked').exists())
        else:raise AssertionError('replaced existing staging input')
        try:revision.prepare(out,source,out/'cancelled',args.engine,paint['container']['source_sha256'],[color],cancelled=lambda:True)
        except ValueError:check('cancelled revision has no artifacts',not (out/'cancelled').exists() and not (out/'cancelled.revision-input').exists())
        else:raise AssertionError('cancelled revision succeeded')
        check('all original fixtures unchanged',all(p.read_bytes()==data for p,data in originals.items()))
        evidence={'passed':True,'checks':checks,'native_calls':len(invocations),'edit_kinds':sorted(revision.KINDS),'engine_admission_complete':False,'remote_actions':False,
                  'scope':'targeted existing scalar values and exact unrequested bytes; structural authoring, absent field creation, cooking and durable public runtime remain pending'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(invocations)}))
    except Exception as error:(out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:document.run=run;(out/'calls.json').write_text(json.dumps(invocations,indent=2)+'\n')


if __name__=='__main__':main()
