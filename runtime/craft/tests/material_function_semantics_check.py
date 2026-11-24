#!/usr/bin/env python3
"""Qualify operand contracts against actual offline Material CPU evaluation."""
import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio_runtime import material_container as container, material_procedural as proc
from studio_runtime import material_references as refs, material_function_semantics as semantics
from material_procedural_check import body


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine', type=Path, required=True)
    ap.add_argument('--fixture', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; calls = []; covered = set(); originals = args.fixture.read_bytes()
    with zipfile.ZipFile(args.fixture) as archive: base = ET.fromstring(archive.read('package.sbs'))
    def check(label, condition):
        if not condition: raise AssertionError(label)
        checks.append(label)
    def constant(identity, kind, value):
        op = 'const_' + {'float':'float1', 'int':'int1', 'text':'string'}.get(kind, kind)
        return (identity, op, [], (kind, value), refs.VALUE_CODES[kind])
    def resolved(spec, result):
        element = body(spec, result)
        root = ET.Element('package'); root.append(element)
        profile = container.inspect_bytes(ET.tostring(root, encoding='utf-8'))
        parsed = profile['xml'][profile['root']]['elements'][1]
        model = proc.function(parsed)['model']
        return {'model': model, 'calls': {}, 'types': refs.node_types(model, {})}
    def inspect(spec, result, scope='node'):
        return semantics.inspect_function(resolved(spec, result), scope)
    def native(label, spec, result):
        root = copy.deepcopy(base); previous = next(root.iter('dynamicValue'))
        parent = next(p for p in root.iter() if previous in list(p))
        parent.remove(previous); parent.append(body(spec, result))
        path = out / (label + '.sbs'); path.write_bytes(ET.tostring(root, encoding='utf-8'))
        run = subprocess.run([str(args.engine.resolve()), 'info', str(path)], capture_output=True, timeout=60)
        index = len(calls); (out / f'{index:03}.stdout').write_bytes(run.stdout); (out / f'{index:03}.stderr').write_bytes(run.stderr)
        calls.append({'file': path.name, 'exit_code': run.returncode})
        check(label + ' native process', run.returncode == 0)
        info = json.loads(run.stdout)
        return next(node for node in info['graph']['nodes'] if node['def'] == 'value_processor')['cooked']
    def same(actual, expected):
        if isinstance(expected, list): return isinstance(actual, list) and len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
        if type(expected) is float: return type(actual) in (int, float) and math.isclose(actual, expected, rel_tol=2e-6, abs_tol=2e-7)
        return type(actual) is type(expected) and actual == expected
    def positive(label, spec, result, kind, value):
        report = inspect(spec, result)
        check(label + ' static result type', report['result_type'] == refs.VALUE_CODES[kind] and not report['engine_admission_complete'])
        cooked = native(label, spec, result)
        check(label + ' independent native numeric oracle', cooked['error'] is None and cooked['value']['t'] == kind and same(cooked['value']['v'], value))
        covered.update(node[1] for node in spec)
        return report
    def refused(label, spec, result, native_error=None, scope='node'):
        try: inspect(spec, result, scope)
        except ValueError: checks.append(label + ' static refusal')
        else: raise AssertionError('accepted ' + label)
        if native_error is not None:
            cooked = native(label, spec, result)
            check(label + ' native error oracle', cooked['error'] is not None and native_error in cooked['error'])
    f = lambda i, v: constant(i, 'float', v)
    b = lambda i, v: constant(i, 'bool', v)
    try:
        values = {'float': .25, 'float2':[.25,.5], 'float3':[.25,.5,.75], 'float4':[.25,.5,.75,1.],
                  'int': 3, 'int2':[3,4], 'int3':[3,4,5], 'int4':[3,4,5,6], 'bool':True, 'text':'owned'}
        for kind, value in values.items():
            code = refs.VALUE_CODES[kind]
            positive('constant-' + kind, [constant(1, kind, value)], 1, kind, value)
            getter = 'get_' + {'float':'float1', 'int':'integer1', 'int2':'integer2', 'int3':'integer3', 'int4':'integer4', 'text':'string'}.get(kind, kind)
            report = positive('getter-' + kind, [constant(1, kind, value), (2,'set',[1],('text','saved'),code),
                              (3,getter,[],('text','saved'),code), (4,'sequence',[2,3],None,code)], 4, kind, value)
            check('ordered variable flow stays explicit ' + kind, report['requires_variable_flow_validation'])
        for integer in (False, True):
            prefix = 'i' if integer else ''; family = 'int' if integer else 'float'
            for count in (2,3,4):
                left_kind = family if count == 2 else family + str(count-1)
                left = 2 if count == 2 else list(range(2, count+1))
                if not integer: left = float(left) if count == 2 else list(map(float,left))
                right = 7 if integer else 7.
                kind = family + str(count); code = refs.VALUE_CODES[kind]
                expected = ([left] if count == 2 else left) + [right]
                positive(prefix + 'vector' + str(count), [constant(1,left_kind,left),constant(2,family,right),
                         (3,prefix+'vector'+str(count),[1,2],None,code)], 3, kind, expected)
            for count in (1,2,3,4):
                kind = family + (str(count) if count > 1 else ''); code = refs.VALUE_CODES[kind]
                setting = 3 if count == 1 else list(range(4-count,4))
                expected = 4 if count == 1 else list(range(5-count,5))
                if not integer: expected = float(expected) if count == 1 else list(map(float,expected))
                positive(prefix+'swizzle'+str(count), [constant(1,family+'4',[1,2,3,4]),
                         (2,prefix+'swizzle'+str(count),[1],('int'+(str(count) if count>1 else ''),setting),code)], 2, kind, expected)
                source_kind = ('float' if integer else 'int') + (str(count) if count>1 else '')
                source = 3.75 if integer else 3
                data = source if count == 1 else [source]*count
                op = 'toint'+str(count) if integer else 'tofloat'+(str(count) if count>1 else '')
                expected = 3 if integer else 3.
                positive(op, [constant(1,source_kind,data),(2,op,[1],None,code)], 2, kind, expected if count==1 else [expected]*count)
        arithmetic = {
            'add':([.25,.5],.75), 'sub':([.25,.5],-.25), 'mul':([.25,.5],.125),
            'mulscalar':([.25,.5],.125), 'div':([.25,.5],.5), 'mod':([.75,.5],.25),
            'neg':([.25],-.25), 'abs':([-.25],.25), 'min':([.25,.5],.25), 'max':([.25,.5],.5),
            'floor':([.75],0.), 'ceil':([.25],1.), 'sqrt':([.25],.5), 'exp':([0.],1.),
            'log':([1.],0.), 'log2':([8.],3.), 'pow':([2.,3.],8.), 'pow2':([3.],8.),
            'sin':([0.],0.), 'cos':([0.],1.), 'tan':([0.],0.), 'lerp':([.25,.75,.5],.5),
            'rand':([0.],0.), 'dot':([.25,.5],.125),
        }
        for op,(operands,expected) in arithmetic.items():
            spec = [f(i+1,v) for i,v in enumerate(operands)]
            spec.append((10,op,list(range(1,len(operands)+1)),None,256))
            positive(op,spec,10,'float',expected)
        positive('atan2',[constant(1,'float2',[0.,1.]),(2,'atan2',[1],None,256)],2,'float',math.pi/2)
        positive('cartesian',[f(1,2.),f(2,0.),(3,'cartesian',[1,2],None,512)],3,'float2',[2.,0.])
        for op,expected in [('and',False),('or',True)]:
            positive(op,[b(1,True),b(2,False),(3,op,[1,2],None,4)],3,'bool',expected)
        positive('not',[b(1,False),(2,'not',[1],None,4)],2,'bool',True)
        for op,expected in [('eq',False),('noteq',True),('gt',False),('gteq',False),('lr',True),('lreq',True)]:
            positive(op,[f(1,.25),f(2,.5),(3,op,[1,2],None,4)],3,'bool',expected)
        positive('isdefined',[(1,'isdefined',[],('text','$pos'),4)],1,'bool',False)
        positive('ifelse',[b(1,False),f(2,.25),f(3,.5),(4,'ifelse',[1,2,3],None,256)],4,'float',.5)
        positive('while',[f(1,.25),b(2,False),f(3,.5),(4,'while',[1,2,3],('int',3),256)],4,'float',.5)
        positive('passthrough',[f(1,.25),(2,'passthrough',[1],None,256),(3,'sequence',[1,2],None,256)],3,'float',.25)
        for op,kind,result in [('samplelum','float',0.),('samplecol','float4',[0.,0.,0.,0.])]:
            positive(op,[constant(1,'float2',[.25,.5]),(2,op,[1],('int2',[0,1]),refs.VALUE_CODES[kind])],2,kind,result)
        check('all 85 intrinsics actually evaluated with independent result oracles',covered==set(semantics.INPUTS))
        # Wider arithmetic and integer families are not covered by scalar float success.
        for op,left,right,result in [('add',3,2,5),('sub',3,2,1),('mul',3,2,6),('div',7,2,3),('mod',7,2,1),('neg',3,None,-3),('abs',-3,None,3),('min',3,2,2),('max',3,2,3)]:
            spec=[constant(1,'int4',[left]*4)]
            if right is not None: spec.append(constant(2,'int4',[right]*4))
            spec.append((3,op,[1] if right is None else [1,2],None,128))
            positive('integer4-'+op,spec,3,'int4',[result]*4)
        positive('vector-scalar-multiply',[constant(1,'float3',[1.,2.,3.]),f(2,.5),(3,'mulscalar',[1,2],None,1024)],3,'float3',[.5,1.,1.5])
        positive('vector-scalar-interpolate',[constant(1,'float3',[1.,2.,3.]),constant(2,'float3',[3.,4.,5.]),f(3,.5),(4,'lerp',[1,2,3],None,1024)],4,'float3',[2.,3.,4.])
        negative = [
            ('mixed-families',[f(1,.25),constant(2,'int',2),(3,'add',[1,2],None,256)],3,'expected float'),
            ('mixed-dimensions',[constant(1,'float2',[1,2]),f(2,1),(3,'add',[1,2],None,512)],3,'same dimensions'),
            ('integer-sqrt',[constant(1,'int',4),(2,'sqrt',[1],None,16)],2,'requires floating-point'),
            ('logical-number',[f(1,1),(2,'not',[1],None,4)],2,'expected boolean'),
            ('equality-mixed',[f(1,1),constant(2,'int',1),(3,'eq',[1,2],None,4)],3,'same type'),
            ('vector-comparison',[constant(1,'float2',[1,2]),(2,'gt',[1,1],None,4)],2,'matching scalars'),
            ('swizzle-index',[constant(1,'float2',[1,2]),(2,'swizzle1',[1],('int',2),256)],2,'outside its input'),
            ('swizzle-family',[constant(1,'int2',[1,2]),(2,'swizzle1',[1],('int',0),256)],2,'expected float'),
            ('vector-arity',[f(1,1),f(2,2),(3,'vector3',[1,2],None,1024)],3,'totaling 3'),
            ('cast-dimensions',[constant(1,'float2',[1,2]),(2,'toint1',[1],None,16)],2,'preserve the number'),
            ('cast-family',[constant(1,'int',1),(2,'toint1',[1],None,16)],2,'expected float'),
            ('sample-position',[f(1,.5),(2,'samplelum',[1],('int2',[0,1]),256)],2,'must be float2'),
            ('sample-negative-index',[constant(1,'float2',[0,0]),(2,'samplelum',[1],('int2',[-1,1]),256)],2,'negative image index'),
            ('atan2-scalar',[f(1,1),(2,'atan2',[1],None,256)],2,'requires a float2'),
            ('cartesian-vector',[constant(1,'float2',[1,2]),(2,'cartesian',[1,1],None,512)],2,'requires scalar'),
            ('bad-condition',[f(1,1),f(2,2),(3,'ifelse',[1,2,2],None,256)],3,'expected boolean'),
            ('branch-result',[b(1,False),f(2,2),constant(3,'int',3),(4,'ifelse',[1,2,3],None,256)],4,'expected native type'),
            ('loop-init-result',[constant(1,'int',1),b(2,True),f(3,2),(4,'while',[1,2,3],('int',0),256)],4,'expected native type'),
            ('set-system',[f(1,1),(2,'set',[1],('text','$size'),256)],2,'nonempty user variable name'),
            ('missing-input',[f(1,1),(2,'add',[1,None],None,256)],2,'requires connected inputs'),
            ('wrong-result-code',[f(1,1),(2,'neg',[1],None,16)],2,'expected native type'),
            ('unavailable-position',[(1,'get_float2',[],('text','$pos'),512)],1,'undefined variable'),
            ('wrong-system-type',[(1,'get_float1',[],('text','$size'),256)],1,'wrong type'),
        ]
        for label,spec,result,error in negative: refused(label,spec,result,error)
        # Scope is a caller property, not a declaration that a getter can override.
        for scope in ('node','pixel','fx_map'):
            for name,code in semantics.SYSTEM.items():
                getter={16:'get_integer1',32:'get_integer2',256:'get_float1',512:'get_float2',1024:'get_float3'}[code]
                spec=[(1,getter,[],('text',name),code)]
                expected = (scope != 'node') if name=='$pos' else (scope=='fx_map') if name in ('$depth','$depthpow2','$number') else True
                if expected: check('scope '+scope+' '+name,inspect(spec,1,scope)['result_type']==code)
                else: refused('scope '+scope+' '+name,spec,1,scope=scope)
                report=inspect([(1,'isdefined',[],('text',name),4)],1,scope)
                check('scope predicate '+scope+' '+name,report['predicates'][0]['system_available']==expected)
        # Static types must not be mistaken for proof of successful numeric execution.
        for label,spec,error in [
            ('division-zero',[f(1,1),f(2,0),(3,'div',[1,2],None,256)],'non-finite'),
            ('integer-overflow',[constant(1,'int',2147483647),constant(2,'int',1),(3,'add',[1,2],None,16)],'overflow'),
            ('cast-overflow',[f(1,2147483648.),(3,'toint1',[1],None,16)],'outside the integer range'),
        ]:
            report=inspect(spec,3);check(label+' remains numeric obligation',bool(report['numeric_obligations']) and not report['concrete_values_qualified'])
            cooked=native(label,spec,3);check(label+' native domain error',error in (cooked['error'] or ''))
        # An unrelated incomplete draft is retained and never promoted into execution.
        spec=[f(1,.25),(2,'add',[None,None],None,256)]
        report=positive('unused-draft',spec,1,'float',.25)
        check('unused draft excluded from operand checks',report['draft_nodes']==1 and report['reachable_nodes']==1)
        spec=[f(1,.25)]+[(i,'neg',[i-1],None,256) for i in range(2,4097)]
        check('4096-node semantic walk stays iterative',inspect(spec,4096)['reachable_nodes']==4096)
        check('original fixture unchanged',args.fixture.read_bytes()==originals)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'intrinsics_evaluated':len(covered),
                  'engine_admission_complete':False,'remote_actions':False,
                  'scope':'operand/result contracts, caller system-variable scopes and real numeric examples; user-variable flow, concrete Value variants, numeric domains, call-context propagation and whole-job budgets remain separate'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps({'passed':len(checks),'native_calls':len(calls),'intrinsics_evaluated':len(covered)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally: (out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__': main()
