#!/usr/bin/env python3
"""Ordered function flow, actual CPU results/errors and owned call isolation."""
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
from studio_runtime import material_references as refs, material_function_flow as flow, material_procedural as proc
from material_procedural_check import body,child,value


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--fixture',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[]
    original=args.fixture.read_bytes();snapshot=container.inspect_bytes(original);base=ET.fromstring(snapshot['members'][snapshot['root']])
    f=lambda i,v:(i,'const_float1',[],('float',v),256)
    b=lambda i,v:(i,'const_bool',[],('bool',v),4)
    get=lambda i,name:(i,'get_float1',[],('text',name),256)
    put=lambda i,source,name='x':(i,'set',[source],('text',name),256)
    seq=lambda i,left,right:(i,'sequence',[left,right],None,256)
    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)
    def resolved(element):
        p=ET.Element('package');p.append(copy.deepcopy(element));snap=container.inspect_bytes(ET.tostring(p,encoding='utf-8'))
        report=proc.function(snap['xml'][snap['root']]['elements'][1]);model=report['model']
        return {'model':model,'calls':{},'types':refs.node_types(model,{})}
    def inspect(spec,result,variables=None,scope='node'):
        return flow.inspect({'entry':resolved(body(spec,result))},'entry',scope,variables)
    def exposed(holder,name,kind,data,identity):
        codes={'bool':4,'float':256};port=child(holder,'paraminput');child(port,'identifier',name);child(port,'uid',identity);child(port,'type',codes[kind])
        attrs=child(port,'attributes');child(attrs,'label',name);child(attrs,'description','Owned flow input')
        value(child(port,'defaultValue'),kind,data);widget=child(port,'defaultWidget');child(widget,'name','buttons' if kind=='bool' else 'slider');opts=child(widget,'options')
        for name,text in [('min','0'),('max','1'),('clamp','0')]:
            option=child(opts,'option');child(option,'name',name);child(option,'value',text)
    def fixture(element,arg=False):
        root=copy.deepcopy(base);old=next(root.iter('dynamicValue'));parent=next(p for p in root.iter() if old in list(p));parent.remove(old);parent.append(copy.deepcopy(element))
        exposed(root.find('content/graph/paraminputs'),'arg','bool',arg,2100000000);return root
    def run(label,root):
        path=out/(label+'.sbs');path.write_bytes(ET.tostring(root,encoding='utf-8'));data=path.read_bytes()
        result=subprocess.run([str(args.engine.resolve()),'info',str(path)],capture_output=True,timeout=60)
        i=len(calls);(out/f'{i:03}.stdout').write_bytes(result.stdout);(out/f'{i:03}.stderr').write_bytes(result.stderr)
        calls.append({'file':path.name,'exit_code':result.returncode});check(label+' native process',result.returncode==0)
        check(label+' source unchanged',path.read_bytes()==data)
        return next(n for n in json.loads(result.stdout)['graph']['nodes'] if n['def']=='value_processor')['cooked']
    def case(label,spec,result,proven,expected=None,error=None,arg=False,variables=None):
        report=inspect(spec,result,variables);check(label+' flow result',report['variable_flow_proven']==proven and not report['engine_admission_complete'])
        cooked=run(label,fixture(body(spec,result),arg))
        if error is not None:check(label+' native error',error in (cooked['error'] or ''))
        else:check(label+' native value',cooked['error'] is None and cooked['value']==expected)
        return report
    scalar=lambda v:{'t':'float','v':v}
    try:
        case('sequence',[f(1,.25),put(2,1),get(3,'x'),seq(4,2,3)],4,True,scalar(.25))
        case('read-before-write',[f(1,.25),put(2,1),get(3,'x'),seq(4,3,2)],4,False,error='undefined variable')
        case('argument-order',[f(1,.25),put(2,1),get(3,'x'),(4,'add',[2,3],None,256)],4,True,scalar(.5))
        case('reversed-argument-order',[f(1,.25),put(2,1),get(3,'x'),(4,'add',[3,2],None,256)],4,False,error='undefined variable')
        common=[(1,'get_bool',[],('text','arg'),4),f(2,.25),put(3,2),f(4,.5),put(5,4),(6,'ifelse',[1,3,5],None,256),get(7,'x'),seq(8,6,7)]
        for arg in (False,True):case('both-branches-'+str(arg),common,8,True,scalar(.25 if arg else .5),arg=arg,variables={'arg':4})
        optional=copy.deepcopy(common);optional[5]=(6,'ifelse',[1,3,4],None,256)
        case('optional-assignment-false',optional,8,False,error='undefined variable',variables={'arg':4})
        case('optional-assignment-true',optional,8,False,scalar(.25),arg=True,variables={'arg':4})
        guarded=optional[:6]+[(7,'isdefined',[],('text','x'),4),get(8,'x'),f(9,.75),(10,'ifelse',[7,8,9],None,256),seq(11,6,10)]
        for arg in (False,True):case('defined-guard-'+str(arg),guarded,11,True,scalar(.25 if arg else .75),arg=arg,variables={'arg':4})
        negated=guarded[:9]+[(10,'not',[7],None,4),(11,'ifelse',[10,9,8],None,256),seq(12,6,11)]
        for arg in (False,True):case('negated-guard-'+str(arg),negated,12,True,scalar(.25 if arg else .75),arg=arg,variables={'arg':4})
        # Type changes can hide inside a branch whose result still has the
        # correct declared type. Both environments must survive the merge.
        mismatch=common[:4]+[(4,'const_int1',[],('int',2),16),(5,'set',[4],('text','x'),16),seq(9,5,2),(6,'ifelse',[1,3,9],None,256),get(7,'x'),seq(8,6,7)]
        mismatch=[n for i,n in enumerate(mismatch) if not any(later[0]==n[0] for later in mismatch[i+1:])]
        case('branch-type-change',mismatch,8,False,error='wrong type',variables={'arg':4})
        case('logical-inputs-eager',[b(1,False),(2,'get_bool',[],('text','missing'),4),(3,'and',[1,2],None,4)],3,False,error='undefined variable')
        case('caller-variable-type',[get(1,'arg')],1,False,error='wrong type',variables={'arg':4})
        case('constant-branch',[b(1,False),get(2,'missing'),f(3,.5),(4,'ifelse',[1,2,3],None,256)],4,True,scalar(.5))
        position=[(1,'isdefined',[],('text','$pos'),4),(2,'get_float2',[],('text','$pos'),512),(3,'const_float2',[],('float2',[.25,.5]),512),(4,'ifelse',[1,2,3],None,512)]
        case('guarded-system-scope',position,4,True,{'t':'float2','v':[.25,.5]})
        check('same guarded body in pixel scope',inspect(position,4,scope='pixel')['variable_flow_proven'])
        case('unguarded-system-scope',position,2,False,error='undefined variable')
        case('zero-loop',[f(1,.25),b(2,False),get(3,'missing'),(4,'while',[1,2,3],('int',0),256)],4,True,scalar(.25))
        case('zero-loop-still-reads-condition',[f(1,.25),(2,'get_bool',[],('text','missing'),4),f(3,.5),(4,'while',[1,2,3],('int',0),256)],4,False,error='undefined variable')
        repeated=[f(1,.25),put(2,1),b(3,False),f(4,.5),put(5,4),(6,'while',[2,3,5],('int',3),256),get(7,'x'),seq(8,6,7)]
        case('loop-assignment',repeated,8,True,scalar(.5))
        unbounded=[f(1,.25),(2,'isdefined',[],('text','x'),4),f(3,.5),put(4,3),(5,'while',[1,2,4],('int',-1),256),get(6,'x'),seq(7,5,6)]
        report=case('loop-exit-guard',unbounded,7,True,scalar(.5));check('flow does not certify unbounded termination',report['has_unbounded_loop'] and not report['numeric_values_qualified'])
        # Full owned call resolution supplies defaults and exact source bodies.
        def call_fixture(source_spec,source_result,default=False):
            caller=body([f(1,.25),put(2,1),f(3,0.),get(4,'x'),seq(5,3,4),seq(6,2,5)],6)
            node=caller.findall('paramNodes/paramNode')[2];node.find('function').set('v','instance');node.find('funcDatas/funcData/name').set('v','instance')
            holder=node.find('funcDatas/funcData/constantValue');holder.clear();value(holder,'text','pkg:///Owned');interface=child(node,'materialcraftInterface')
            root=fixture(caller);function=child(root.find('content'),'function');child(function,'identifier','Owned');child(function,'uid',2100000001);child(function,'attributes');ports=child(function,'paraminputs')
            interface=next(root.iter('materialcraftInterface'))
            if default:
                exposed(ports,'x','float',.75,2100000002);port=child(interface,'input');child(port,'identifier','x');child(port,'type',256)
            child(function,'type',256);child(function,'paramValue').append(body(source_spec,source_result))
            return root
        shadow=call_fixture([get(1,'x')],1,True)
        caller=next(shadow.iter('dynamicValue'));nodes=caller.findall('paramNodes/paramNode')
        nodes[0].find('function').set('v','const_int1');nodes[0].find('funcDatas/funcData/name').set('v','const_int1')
        holder=nodes[0].find('funcDatas/funcData/constantValue');holder.clear();value(holder,'int',3)
        nodes[3].find('function').set('v','get_integer1');nodes[3].find('funcDatas/funcData/name').set('v','get_integer1')
        for index in (0,1,3,4,5):nodes[index].find('type').set('v','16')
        argument=call_fixture([get(1,'y')],1,True);caller=next(argument.iter('dynamicValue'))
        for node in body([f(8,.5),put(7,8,'y')],7).find('paramNodes'):caller.find('paramNodes').append(node)
        call=caller.findall('paramNodes/paramNode')[2];wire=child(call.find('connections'),'connection');child(wire,'identifier','x');child(wire,'connRef',7)
        caller.findall('paramNodes/paramNode')[3].find('funcDatas/funcData/constantValue/constantValueString').set('v','y')
        isolation=[get(1,'x'),(2,'const_int1',[],('int',2),16),(3,'set',[2],('text','x'),16),f(4,.75),seq(5,3,4),seq(6,1,5)]
        scoped=call_fixture([(1,'get_float1',[],('text','$depth'),256)],1)
        for label,root,expected,expected_value in [
            ('call-inherits-and-isolates',call_fixture(isolation,6),True,scalar(.25)),
            ('call-default-shadow',shadow,True,{'t':'int','v':3}),
            ('call-argument-effects',argument,True,scalar(.5)),
            ('call-undefined-read',call_fixture([get(1,'missing')],1),False,None),
            ('call-propagates-scope',scoped,False,None),
        ]:
            snap=container.inspect_bytes(ET.tostring(root,encoding='utf-8'));pkg=resources.inspect(snap);g=graphs.inspect(snap,pkg);resolved_calls=refs.inspect(snap,pkg,g)
            functions=resolved_calls['functions'];entry=next(key for key,r in functions.items() if r['calls'])
            report=flow.inspect(functions,entry,'node',{'arg':4});check(label+' full resolved flow',report['variable_flow_proven']==expected and report['body_count']==2 and report['call_visits']==1)
            cooked=run(label,root)
            if expected:check(label+' native caller state preserved',cooked['error'] is None and cooked['value']==expected_value)
            else:check(label+' native callee error','undefined variable' in cooked['error'])
            if label=='call-propagates-scope':check('same call valid in FX-Map scope',flow.inspect(functions,entry,'fx_map',{'arg':4})['variable_flow_proven'])
        # The compiler visits both branches, but variable reads occur only in
        # the selected branch. A disconnected callee input still fails compile.
        for missing_input in (False,True):
            root=call_fixture([f(1,.5),(2,'add',[1,None],None,256)] if missing_input else [get(1,'missing')],2 if missing_input else 1)
            old=next(root.iter('dynamicValue'));call=copy.deepcopy(old.findall('paramNodes/paramNode')[2])
            guarded=body([b(7,False),f(1,.25),(6,'ifelse',[7,3,1],None,256)],6);guarded.find('paramNodes').append(call)
            parent=next(p for p in root.iter() if old in list(p));parent.remove(old);parent.append(guarded)
            snap=container.inspect_bytes(ET.tostring(root,encoding='utf-8'));pkg=resources.inspect(snap);g=graphs.inspect(snap,pkg)
            functions=refs.inspect(snap,pkg,g)['functions'];entry=next(key for key,r in functions.items() if r['calls'])
            if missing_input:
                try:flow.inspect(functions,entry,'node')
                except ValueError:checks.append('unselected callee still requires compilable inputs')
                else:raise AssertionError('uncompilable unselected callee accepted')
            else:
                report=flow.inspect(functions,entry,'node');check('unselected callee read is not evaluated',report['variable_flow_proven'] and report['body_count']==2 and report['call_visits']==0)
            cooked=run('unselected-call-'+str(missing_input),root)
            check('native compiler versus evaluation '+str(missing_input),'requires connected inputs' in (cooked['error'] or '') if missing_input else cooked['error'] is None and cooked['value']==scalar(.25))
        check('local names cannot enable out-of-scope system variables',not inspect(position,2,variables={'$pos':512})['variable_flow_proven'])
        try:inspect([(1,'get_integer1',[],('text','$tiling'),16)],1,variables={'$tiling':256})
        except ValueError:checks.append('incorrect system context type refused')
        else:raise AssertionError('incorrect system context type accepted')
        chain=[f(1,.5)]+[(i,'neg',[i-1],None,256) for i in range(2,4097)]
        report=inspect(chain,4096);check('4096-node chain avoids Python recursion',report['node_visits']==4096 and report['variable_flow_proven'])
        oversized={str(i):resolved(body([f(1,.5)],1)) for i in range(257)}
        try:flow.inspect(oversized,'0','node')
        except ValueError:checks.append('aggregate flow body budget')
        else:raise AssertionError('aggregate flow body budget ignored')
        for name,limit,spec,result in [('MAX_VISITS',2,chain,4096),('MAX_ENVIRONMENT_CELLS',0,[f(1,.25),put(2,1),put(3,2,'y')],3),('MAX_VARIABLES',0,[f(1,.25),put(2,1)],2)]:
            old=getattr(flow,name);setattr(flow,name,limit)
            try:
                try:inspect(spec,result)
                except ValueError:checks.append('bounded analysis '+name)
                else:raise AssertionError('unbounded analysis '+name)
            finally:setattr(flow,name,old)
        check('original fixture unchanged',args.fixture.read_bytes()==original)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'engine_admission_complete':False,'remote_actions':False,
                  'scope':'ordered variable types, control guards, caller scopes and owned call isolation; concrete numeric values, dynamic base contexts and whole-job execution remain separate'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
