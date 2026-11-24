#!/usr/bin/env python3
"""Exercise a maintained CAD binary and complete editable native model transport.

This qualifies controlled private engine behavior. It is not public source
admission, manufacturing accuracy, DWG fidelity, or installed runtime evidence.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    exe = args.engine.resolve(); calls = 0; checks = []; refusals = []
    def check(label, condition):
        assert condition, label
        checks.append(label)
    def invoke(*arguments, fail=False):
        nonlocal calls
        calls += 1
        result = subprocess.run([str(exe), *map(str, arguments)], capture_output=True, timeout=120,
                                env={'PATH':'/usr/bin:/bin', 'HOME':str(out), 'CADCRAFT_SHXPATH':str(out/'untrusted-fonts')})
        (out/f'call-{calls:02d}.stdout').write_bytes(result.stdout)
        (out/f'call-{calls:02d}.stderr').write_bytes(result.stderr)
        if fail:
            assert result.returncode == 2, (arguments, result.returncode, result.stderr)
            refusals.append(result.stderr.decode().strip())
        else:
            assert result.returncode == 0, (arguments, result.stderr)
        return result
    def save(name, model):
        path = out/name; path.write_text(json.dumps(model)+'\n'); return path
    try:
        version = invoke('--version').stdout.decode().strip()
        check('private product version', version == 'dobe-cad 0.20.1')
        invoke('new', 'metric', out/'metric.json'); metric = json.loads((out/'metric.json').read_bytes())
        invoke('new', 'imperial', out/'imperial.json'); imperial = json.loads((out/'imperial.json').read_bytes())
        check('metric and imperial drawing defaults remain distinct', metric != imperial)
        check('complete native drawing fields retained', set(metric) == {'constraints', 'read_notes', 'plot_style_tables', 'mline_styles', 'refedit', 'skipped_records', 'blocks', 'portable_fonts', 'foreign', 'table_styles', 'active_layout', 'scales', 'layouts', 'parametric', 'layers', 'views', 'mleader_styles', 'linetypes', 'dim_styles', 'model', 'vports', 'groups', 'layer_states', 'rasters', 'header', 'text_styles', 'handseed', 'ucss', 'hidden_objects'})
        # Entirely original synthetic source. Native parser supplies all defaults.
        groups = [(0,'SECTION'),(2,'HEADER'),(9,'$ACADVER'),(1,'AC1032'),(9,'$INSUNITS'),(70,'4'),(0,'ENDSEC'),
                  (0,'SECTION'),(2,'ENTITIES'),(0,'LINE'),(5,'100'),(8,'0'),(10,'0'),(20,'0'),(30,'0'),(11,'100'),(21,'0'),(31,'0'),
                  (0,'CIRCLE'),(5,'101'),(8,'0'),(10,'50'),(20,'30'),(30,'0'),(40,'15'),
                  (0,'TEXT'),(5,'102'),(8,'0'),(10,'0'),(20,'60'),(30,'0'),(40,'5'),(1,'Workshop / 100 mm'),
                  (0,'ENDSEC'),(0,'EOF')]
        source=out/'original.dxf';source.write_text(''.join(f'{code}\n{value}\n' for code,value in groups))
        original=source.read_bytes();invoke('snapshot','dxf',source,out/'source-model.json')
        model=json.loads((out/'source-model.json').read_bytes())
        check('native DXF parser retains original geometry', len(model['model'])==3)
        check('known line endpoint exact',model['model'][0]['kind']['b']=={'x':100.0,'y':0.0,'z':0.0})
        invoke('encode',out/'source-model.json',out/'cold.json')
        check('complete cold native model equality',json.loads((out/'cold.json').read_bytes())==model)
        # Exercise state previously skipped by upstream JSON serialization.
        complete=copy.deepcopy(model); entity=copy.deepcopy(model['model'][0]);entity['handle']=1024
        complete['layouts'][0]['entities']=[entity]
        complete['layouts'][0]['page']['filePaper']=[210.0,297.0,1]
        block_entity=copy.deepcopy(entity);block_entity['handle']=1025
        complete['blocks']['OwnedBlock']={'name':'OwnedBlock','annotative':False,'base':{'x':0.0,'y':0.0,'z':0.0},
            'entities':[block_entity],'description':'Original editable fixture','xrefOverlay':False,'xrefStatus':'notLoaded',
            'anonymous':False,'xrefPath':None,'explodable':True,'units':4}
        complete['rasters']={'owned-pixels':{'width':2,'height':1,'rgba':[16,32,48,255,64,80,96,128],'opaque':False}}
        complete['read_notes']=['Original source observation'];complete['skipped_records']={'OBJECTS':2};complete['hidden_objects']=[256]
        extra={'xdict':None,'reactors':[],'xdata':[],'color_book':None,'props':[{'code':347,'value':'CAFE'}]}
        complete['foreign']['records']=[[['LAYER','SOURCE'],extra]]
        complete['foreign']['classes']=[[{'code':1,'value':'OriginalFixture'}]]
        complete['foreign']['objects']=[{'handle':2048,'kind':'XRECORD','tags':[{'code':1,'value':'opaque original record'}]}]
        full=save('complete.json',complete);invoke('encode',full,out/'complete-cold.json')
        check('paper entities, source paper geometry, decoded pixels and foreign records survive cold reopen',json.loads((out/'complete-cold.json').read_bytes())==complete)
        revised=copy.deepcopy(model);revised['model'][0]['kind']['b']['x']=120.0
        revision=save('revision.json',revised);invoke('encode',revision,out/'revised.json')
        check('precise endpoint change preserves every unrelated field',json.loads((out/'revised.json').read_bytes())==revised)
        for label,path in [('original',out/'source-model.json'),('revised',out/'revised.json')]:
            invoke('render',path,out/(label+'.png'),1200,800)
            with Image.open(out/(label+'.png')) as image:
                image.load();check(label+' PNG independently decodes with geometry and content',image.size==(1200,800) and len(image.getcolors(960000) or [])>1)
        invoke('render',out/'source-model.json',out/'repeat.png',1200,800)
        check('two cold renders byte equal',(out/'repeat.png').read_bytes()==(out/'original.png').read_bytes())
        check('precise endpoint revision changes rendered geometry',(out/'revised.png').read_bytes()!=(out/'original.png').read_bytes())
        for fmt in ('dxf','svg','pdf'):invoke('convert',fmt,out/'source-model.json',out/('delivery.'+fmt))
        check('real PDF header observed',(out/'delivery.pdf').read_bytes().startswith(b'%PDF-'))
        check('SVG markup observed',b'<svg' in (out/'delivery.svg').read_bytes())
        invoke('snapshot','dxf',out/'delivery.dxf',out/'dxf-cold.json');converted=json.loads((out/'dxf-cold.json').read_bytes())
        check('controlled DXF export reopens identical entity geometry',converted['model']==model['model'])
        # Full DXF semantics remain explicitly unqualified: record every change.
        differences=[key for key in model if model[key]!=converted[key]]
        (out/'dxf-differences.json').write_text(json.dumps({'changed_root_fields':differences,'full_fidelity_qualified':False},indent=2)+'\n')
        for label,mutate in [('unknown',lambda d:d.update(unowned=True)),
                             ('missing',lambda d:d.pop('handseed')),
                             ('duplicate-handles',lambda d:d['model'].append(copy.deepcopy(d['model'][0]))),
                             ('bad-raster',lambda d:d.update(rasters={'bad':{'width':2,'height':2,'rgba':[0,0,0,255],'opaque':True}})),
                             ('duplicate-foreign',lambda d:d['foreign'].update(records=copy.deepcopy(complete['foreign']['records'])*2))]:
            broken=copy.deepcopy(model);mutate(broken);path=save(label+'.json',broken)
            target=out/(label+'-output.json');invoke('encode',path,target,fail=True);check(label+' creates no output',not target.exists())
        for command in [('mcp',),('app',),('run','arbitrary'),('convert','dwg',out/'source-model.json',out/'bad.dwg'),('render',out/'source-model.json',out/'bad.png',8192,8192)]:invoke(*command,fail=True)
        preserved=(out/'cold.json').read_bytes();invoke('encode',out/'source-model.json',out/'cold.json',fail=True)
        check('existing output and original source never overwritten',(out/'cold.json').read_bytes()==preserved and source.read_bytes()==original)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'native_calls':calls,'version':version,'binary_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                  'complete_controlled_model_equal':True,'cold_png_equal':True,'dxf_changed_root_fields':differences,
                  'full_dxf_fidelity_qualified':False,'independent_pdf_reader_qualified':False,'public_runtime_qualified':False,'installed_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':calls}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'native_calls':calls},indent=2)+'\n');raise


if __name__=='__main__':main()
