#!/usr/bin/env python3
"""Real native CAD constraint solving and independent rectangle measurements."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import cad_parametric as panel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    engine = args.engine.resolve(); calls = 0; checks = []; refusals = []; cases = []
    def check(label, condition):
        assert condition, label
        checks.append(label)
    def call(*arguments, fail=False):
        nonlocal calls
        calls += 1
        result = subprocess.run([str(engine), *map(str, arguments)], capture_output=True, timeout=120,
                                env={'PATH':'/usr/bin:/bin','HOME':str(out)})
        (out/f'call-{calls:02d}.stderr').write_bytes(result.stderr)
        assert result.returncode == (2 if fail else 0), (arguments, result.returncode, result.stderr.decode())
        if fail: refusals.append(result.stderr.decode().strip())
        return result
    def save(name, value):
        path = out/name; path.write_text(json.dumps(value)+'\n'); return path
    def refuse(label, action):
        try: action()
        except ValueError: refusals.append(label)
        else: raise AssertionError('accepted '+label)
    def solve(label, document, recipe, width, height):
        source = save(label+'-input.json', document); before = source.read_bytes(); target = out/(label+'-solved.json')
        call('solve', source, target); report = json.loads(target.read_bytes())
        verified = panel.verify(document, report, recipe, width=width, height=height)
        save(label+'-verification.json', verified); cases.append({'case':label, **verified})
        result = save(label+'-model.json', report['document']); cold = out/(label+'-cold.json')
        call('encode', result, cold)
        check(label+' full native cold reopen', json.loads(cold.read_bytes())==report['document'])
        check(label+' source preserved', source.read_bytes()==before)
        return report, result
    try:
        call('new','metric',out/'base.json');base=json.loads((out/'base.json').read_bytes())
        created=panel.create(base,120,80);recipe=created['recipe'];document=created['document']
        save('recipe.json',recipe)
        initial, initial_file=solve('initial',document,recipe,120,80)
        revised=panel.parameter_edit(initial['document'],'width',150,expected_expression='120')
        expected=copy.deepcopy(initial['document']);expected['parametric']['parameters'][0]['expr']='150'
        check('parameter revision changes exactly one expression before native solve',revised==expected)
        changed, changed_file=solve('revised',revised,recipe,150,80)
        check('real native solver moves constrained geometry',changed['moved']!=[] and changed['document']['model']!=initial['document']['model'])
        repeat, _=solve('repeat',revised,recipe,150,80)
        check('two cold solves produce identical complete reports',repeat==changed)
        for label,path in [('initial',initial_file),('revised',changed_file)]:
            call('render',path,out/(label+'.png'),1200,800)
            with Image.open(out/(label+'.png')) as image:
                image.load();check(label+' real PNG independently decoded',image.size==(1200,800) and len(image.getcolors(960000) or [])>1)
        check('revised dimensions change rendered shape',(out/'initial.png').read_bytes()!=(out/'revised.png').read_bytes())
        small=panel.create(base,.1,.2);solve('small',small['document'],small['recipe'],.1,.2)
        large=panel.parameter_edit(document,'width',10000,expected_expression='120');solve('large',large,recipe,10000,80)
        # The wrapper must refuse every bad request before creating the report.
        bad=[]
        d=copy.deepcopy(document);d['constraints'].append(copy.deepcopy(d['constraints'][0]));bad.append(('duplicate-id',d))
        d=copy.deepcopy(document);d['parametric']['parameters'].append(copy.deepcopy(d['parametric']['parameters'][0]));bad.append(('duplicate-name',d))
        d=copy.deepcopy(document);d['constraints'][-1]['name']='width';bad.append(('shadowed-name',d))
        d=copy.deepcopy(document);d['constraints'][0]['refs'][0]['handle']=999999;bad.append(('missing-reference',d))
        d=copy.deepcopy(document);d['parametric']['parameters'][0]['expr']='width+1';bad.append(('cycle',d))
        d=copy.deepcopy(document);d['parametric']['parameters'][0]['expr']='1/0';bad.append(('division-zero',d))
        d=copy.deepcopy(document);d['parametric']['parameters'].append({'name':'unused','expr':'1/0','description':''});bad.append(('unused-bad-expression',d))
        d=copy.deepcopy(document);d['constraints'][0]['expr']='unused';bad.append(('unused-geometric-expression',d))
        d=copy.deepcopy(document);d['constraints'].append({'id':12,'kind':{'distance':'horizontal'},'refs':copy.deepcopy(d['constraints'][9]['refs']),'name':'conflicting_width','expr':'200'});bad.append(('conflict',d))
        for label,drawing in bad:
            source=save(label+'.json',drawing);before=source.read_bytes();target=out/(label+'-report.json')
            call('solve',source,target,fail=True);check(label+' leaves source and output unchanged',source.read_bytes()==before and not target.exists())
        for label,mutate in [
            ('boolean-report-version',lambda r:r.update(schema_version=True)),
            ('changed-header-number-type',lambda r:r['document']['header']['vars'].update(INSUNITS=4.0)),
            ('changed-property-type',lambda r:r['document']['model'][0]['common'].update(visible=1)),
            ('moved-fixed-origin',lambda r:r['document']['model'][0]['kind']['a'].update(x=.01)),
            ('wrong-height',lambda r:r['document']['model'][1]['kind']['b'].update(y=81)),
            ('lost-source-field',lambda r:r['document'].pop('foreign')),
            ('changed-layer',lambda r:r['document']['model'][0]['common'].update(layer='Other')),
            ('skipped-constraint',lambda r:r.update(skipped=[[1,'ignored']])),
            ('forged-dimension',lambda r:r['dimensions'][0].update(measured=100)),
            ('missing-residual',lambda r:r['residuals'].pop()),
            ('false-change-report',lambda r:r.update(moved=[]))]:
            broken=copy.deepcopy(changed);mutate(broken)
            refuse(label,lambda:panel.verify(revised,broken,recipe,width=150,height=80))
        refuse('stale parameter expression',lambda:panel.parameter_edit(document,'width',150,expected_expression='119'))
        for value in (True,float('nan'),float('inf'),0,10001):
            refuse('invalid dimension '+str(value),lambda:panel.create(base,value,80))
        check('pristine baseline remains unchanged',json.loads((out/'base.json').read_bytes())==base)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'cases':cases,'native_calls':calls,
                  'binary_sha256':hashlib.sha256(engine.read_bytes()).hexdigest(),'native_solver_used':True,
                  'independent_endpoint_measurements':True,'parameter_change_drives_geometry':True,'originals_preserved':True,
                  'public_runtime_qualified':False,'solid_mesh_qualified':False,'general_manufacturing_qualified':False,'remote_actions':False}
        save('evidence.json',evidence);print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':calls,'cases':len(cases)}))
    except Exception as error:
        save('failure.json',{'error':str(error),'checks':checks,'refusals':refusals,'cases':cases,'native_calls':calls});raise


if __name__=='__main__':main()
