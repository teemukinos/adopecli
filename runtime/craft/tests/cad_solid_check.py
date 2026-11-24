#!/usr/bin/env python3
"""Exercise native parametric panel solids and independently measure OBJ delivery."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
    from studio_runtime import cad_binding as binding,cad_engine,cad_source as source,cad_revision as revision,cad_parametric as panel,cad_solid as solid
    exe=args.engine.resolve();checks=[];refusals=[];raw_calls=0;cases=[]
    native=cad_engine.Engine(exe,out,expected_pin=binding.PIN,expected_binary_sha256=source.sha(exe.read_bytes()),seconds=300)
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def save(name,value):
        data=revision.encoded(value);path=out/name;path.write_bytes(data);return path,data
    def refused(label,action,contains=None):
        try:action()
        except ValueError as error:
            if contains is not None:check(label+' intended boundary',contains in str(error))
            refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def native_refusal(label,command,document,request=None):
        nonlocal raw_calls
        path,data=save(label+'.json',document);target=out/(label+'-result.json')
        if command=='panel-solid':
            request_path,_=save(label+'-request.json',request);arguments=[command,path,request_path,target]
        else:arguments=[command,path,str(handle),target]
        raw_calls+=1;result=subprocess.run([str(exe),*map(str,arguments)],capture_output=True,timeout=30,env={'HOME':str(out),'PATH':'/usr/bin:/bin'})
        (out/(label+'.stderr')).write_bytes(result.stderr)
        check(label+' native refusal preserves input and creates no output',result.returncode==2 and not target.exists() and path.read_bytes()==data)
        refusals.append({'case':label,'error':result.stderr.decode().strip()})
    try:
        native._command('new','metric',out/'metric.json');base=source.strict_json((out/'metric.json').read_bytes())
        made=panel.create(base,120,80);recipe=made['recipe'];drawing=made['document']
        # Unrelated paper state and opaque records must not disappear in extrusion.
        paper=copy.deepcopy(drawing['model'][2]);paper['handle']=1000;drawing['layouts'][0]['entities']=[paper];drawing['handseed']=1001
        drawing['read_notes']=['Keep original source observation'];drawing['hidden_objects']=[1000]
        original_path,original=save('original-panel.json',drawing)
        created=native.extrude_panel(original_path,original,recipe,width=120,height=80,depth=12)
        handle=created['mesh_handle'];check('native allocates one stable mesh handle without changing sketch or paper',handle==1001 and created['document']['handseed']==1002
            and created['document']['model'][:4]==drawing['model'] and created['document']['layouts']==drawing['layouts'])
        check('initial solid independently measures volume, area and closed topology',created['measurements']['volume_mm3']==115200.0
            and created['measurements']['surface_area_mm2']==24000.0 and created['measurements']['closed_oriented_manifold'] and created['measurements']['euler_characteristic']==2)
        created_path,_=save('created-solid.json',created['document']);created_data=created_path.read_bytes()
        first_obj=native.export_panel_obj(created_path,created_data,handle,width=120,height=80,depth=12);(out/'created-panel.obj').write_bytes(first_obj['data'])
        check('native OBJ geometry equals editable native source',first_obj['native_mesh_equal'] and first_obj['units']=='mm' and first_obj['geometry_only'])
        cases.append({'case':'initial','dimensions_mm':[120,80,12],**created['measurements']})
        changed=panel.parameter_edit(created['document'],'width',150,expected_expression='120')
        changed=panel.parameter_edit(changed,'height',90,expected_expression='80');changed_path,changed_bytes=save('parameter-revised.json',changed)
        refused('cannot extrude unsolved parameter revision',lambda:native.extrude_panel(changed_path,changed_bytes,recipe,width=150,height=90,depth=20,mesh_handle=handle),'solved sketch dimensions')
        solved=native.solve_panel(changed_path,changed_bytes,recipe,width=150,height=90,mesh_handle=handle)
        solved_path,_=save('solved-sketch.json',solved['document'])
        check('native solve changes sketch while preserving existing mesh and depth parameter',solved['document']['model'][-1]==created['document']['model'][-1]
              and solved['document']['parametric']['parameters'][-1]==created['document']['parametric']['parameters'][-1]
              and solved['measurements']['maximum_endpoint_error_mm']<=1e-6)
        updated=native.extrude_panel(solved_path,solved_path.read_bytes(),recipe,width=150,height=90,depth=20,mesh_handle=handle)
        updated_path,updated_data=save('revised-solid.json',updated['document'])
        check('solid revision preserves handle, order and every unrelated field',updated['mesh_handle']==handle and updated['document']['handseed']==created['document']['handseed']
              and updated['measurements']['unrelated_state_exact'] and updated['document']['parametric']['parameters'][-1]['expr']=='20')
        mesh=updated['document']['model'][-1]['kind'];measured=updated['measurements']
        check('revised native solid has requested dimensions and independently measured volume',measured['dimensions_mm']==[150.0,90.0,20.0]
              and measured['volume_mm3']==270000.0 and measured['surface_area_mm2']==36600.0 and measured['edges']==12)
        delivered=native.export_panel_obj(updated_path,updated_data,handle,width=150,height=90,depth=20);(out/'revised-panel.obj').write_bytes(delivered['data'])
        repeat=native.export_panel_obj(updated_path,updated_data,handle,width=150,height=90,depth=20)
        check('two cold native OBJ exports are byte equal',repeat['data']==delivered['data'])
        check('OBJ contains actual depth and revised dimensions',max(v['z'] for v in solid.inspect_obj(delivered['data'],width=150,height=90,depth=20)['mesh']['vertices'])==20.0)
        cases.append({'case':'revised',**measured})
        for label,w,h,d in [('small',.1,.2,.3),('large',10000,9000,8000)]:
            fixture=panel.create(base,w,h);path,data=save(label+'-sketch.json',fixture['document'])
            result=native.extrude_panel(path,data,fixture['recipe'],width=w,height=h,depth=d)
            solid_path,solid_bytes=save(label+'-solid.json',result['document'])
            delivery=native.export_panel_obj(solid_path,solid_bytes,result['mesh_handle'],width=w,height=h,depth=d);(out/(label+'.obj')).write_bytes(delivery['data'])
            check(label+' panel has checked topology and dimensions',delivery['measurements']['closed_oriented_manifold'] and delivery['measurements']['dimensions_mm']==[w,h,d])
            cases.append({'case':label,**result['measurements']})
        request=solid.request(drawing,recipe,width=120,height=80,depth=12)
        for label,mutate in [
            ('wrong units',lambda d:d['header']['vars'].update(INSUNITS=1)),
            ('open sketch',lambda d:d['model'][0]['kind']['b'].update(x=119.0)),
            ('nonplanar sketch',lambda d:d['model'][0]['kind']['b'].update(z=1.0)),
            ('duplicate global handle',lambda d:d['layouts'][0]['entities'][0].update(handle=256)),
            ('handle overflow',lambda d:d.update(handseed=2**64-1)),
            ('existing depth name',lambda d:d['parametric']['parameters'].append({'name':'depth','expr':'12','description':''}))]:
            bad=copy.deepcopy(drawing);mutate(bad);native_refusal(label,'panel-solid',bad,request)
        for label,request_change in [('negative depth',{'depth':-1}),('non-numeric depth',{'depth':True}),('zero depth',{'depth':0}),
                                     ('wrong target parameter',{'width':121}),('duplicate sketch selector',{'sketch_handles':[256]*4}),
                                     ('extra command field',{'script':'arbitrary'}),('line selected as mesh',{'mesh_handle':256})]:
            native_refusal(label,'panel-solid',drawing,{**request,**request_change})
        for label,mutate in [
            ('inward face',lambda m:m['faces'][0].reverse()),('missing boundary',lambda m:m['faces'].pop()),
            ('repeated vertex',lambda m:m['vertices'].__setitem__(1,copy.deepcopy(m['vertices'][0]))),
            ('invalid index',lambda m:m['faces'][0].__setitem__(0,9)),('folded face',lambda m:m['faces'][0].__setitem__(slice(None),[1,3,4,2])),
            ('wrong depth',lambda m:m['vertices'][4].update(z=21.0))]:
            bad=copy.deepcopy(mesh);mutate(bad)
            refused(label,lambda bad=bad:solid.inspect_mesh(bad,width=150,height=90,depth=20))
            document=copy.deepcopy(updated['document']);document['model'][-1]['kind']=bad;native_refusal(label+' export','panel-obj',document)
        for label,payload in [('external OBJ material',delivered['data'].replace(b'o panel_',b'mtllib panel_',1)),
                              ('OBJ false units',delivered['data'].replace(b'millimetres',b'metres')),
                              ('OBJ missing face',b'\n'.join(delivered['data'].splitlines()[:-1])+b'\n'),
                              ('OBJ nonfinite vertex',delivered['data'].replace(b'v 0 0 0',b'v nan 0 0'))]:
            refused(label,lambda payload=payload:solid.inspect_obj(payload,width=150,height=90,depth=20))
        for label,mutate in [('boolean report version',lambda r:r.update(schema_version=True)),('falsified volume',lambda r:r.update(volume_mm3=1)),('lost note',lambda r:r['document'].update(read_notes=[])),
                            ('renumbered mesh',lambda r:r.update(mesh_handle=999)),('mutated paper',lambda r:r['document']['layouts'][0]['entities'].clear())]:
            report=copy.deepcopy(created['report']);mutate(report);refused(label,lambda report=report:solid.verify(drawing,report,request))
        invalid_mesh=copy.deepcopy(updated['document']);invalid_mesh['model'][-1]['kind']['vertices'][6]=None
        refused('malformed existing solid corner',lambda:solid.request(invalid_mesh,recipe,width=150,height=90,depth=20,mesh_handle=handle),'corner fields differ')
        invalid_solve=copy.deepcopy(solved['report']);invalid_solve['document']['model'][-1]['kind']['vertices'][0]['z']=1.0
        refused('solver changed existing solid',lambda:solid.verify_solve(changed,invalid_solve,recipe,handle,width=150,height=90),'unrelated entity')
        check('original, created and revised native inputs remain immutable',original_path.read_bytes()==original and created_path.read_bytes()==created_data and updated_path.read_bytes()==updated_data)
        check('all native scratch directories removed',not list(out.glob('.cad-*')))
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':native.calls+raw_calls,'cases':cases,'engine':binding.PIN,
                  'binary_sha256':source.sha(exe.read_bytes()),'native_closed_polyface_solid':True,'native_obj_delivery':True,
                  'independent_dimensions_volume_area_topology':True,'exact_unrelated_state_preserved':True,'stable_mesh_revision':True,
                  'brep_qualified':False,'general_manufacturing_qualified':False,'public_runtime_qualified':False,'installed_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':native.calls+raw_calls}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':native.calls+raw_calls},indent=2)+'\n');raise


if __name__=='__main__':main()
