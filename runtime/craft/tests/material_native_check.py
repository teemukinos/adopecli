#!/usr/bin/env python3
"""Exercise the maintained Material engine; no public runtime qualification implied."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); engine = args.engine.resolve(); out = args.output.resolve(); out.mkdir(parents=True)
    checks = []; calls = []; started = time.monotonic()

    def check(value, label):
        if not value: raise AssertionError(label)
        checks.append(label)

    def call(*arguments, fail=None, env=None):
        before = time.monotonic()
        result = subprocess.run([str(engine), *map(str, arguments)], capture_output=True, timeout=90, env=env)
        number = len(calls); (out/f'{number:03}.stdout').write_bytes(result.stdout); (out/f'{number:03}.stderr').write_bytes(result.stderr)
        calls.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode, 'seconds': time.monotonic()-before})
        if fail is not None:
            check(result.returncode != 0 and fail in result.stderr.decode(), 'refused: '+str(arguments[:2])); return
        if result.returncode != 0: raise AssertionError(result.stderr.decode()[:1000])
        return result.stdout

    def value(*arguments): return json.loads(call(*arguments))
    def info(path):
        result = value('info', path)
        check(not result['package']['warnings'] and all(not n['cooked'] or not n['cooked']['error'] for n in result['graph']['nodes']), 'native open/cook has no warnings or node errors: '+path.name)
        return result['nativePackage']
    def edit(source, target, command, params): return value('run', source, command, json.dumps(params), '-o', target)
    def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    def maps(source, name):
        folder = out/name
        value('export', source, folder, '--depth', '8')
        return {p.name: {'sha256': sha(p), 'pixels': Image.open(p).convert('RGBA').tobytes(), 'size': Image.open(p).size} for p in folder.iterdir()}

    try:
        check(call('--version').decode().startswith('dobe-material 0.4.1 '), 'maintained public executable identity')
        help_text = call('--help').decode()
        check('dobe-material' in help_text and 'materialcraft-cli' not in help_text, 'Dobe private help')
        for arguments in [('serve',), ('mcp',), ('mcp','--bridge','1'), ('info','sample','--token=not-a-token'), ('info','sample','--port','1')]:
            call(*arguments, fail='private engine has no editor connection or network server')
        source = out/'paint.mcraft'; value('new','pbr',source,'--size','64','--name','Paint'); original = source.read_bytes()
        before = info(source)
        check(len(before['graphs']) == 1 and len(before['graphs'][0]['nodes']) == 12, 'editable PBR graph has six connected source/output pairs')
        original_maps = maps(source, 'maps')
        expected = {'basecolor':(188,188,188,255),'normal':(128,128,255,255),'roughness':(128,128,128,255),
                    'metallic':(0,0,0,255),'height':(0,0,0,255),'ambientocclusion':(255,255,255,255)}
        check(len(original_maps) == len(expected), 'all six PBR maps exported')
        for name,pixel in expected.items():
            data = original_maps['Paint_'+name+'.png']
            check(data['size'] == (64,64) and data['pixels'] == bytes(pixel)*(64*64), 'independent analytic PBR pixels: '+name)
        cold = out/'cold.mcraft'; edit(source,cold,'file.save',{'path':str(cold)})
        check(info(cold) == before, 'all serialized native fields survive cold archive reopen')
        check(maps(cold,'cold-maps') == original_maps, 'all encoded map bytes and pixels survive cold reopen')
        revised = out/'red.mcraft'; edit(source,revised,'graph.node.param',{'id':1,'param':'color','value':[1,0,0,1]})
        predicted = copy.deepcopy(before); predicted['graphs'][0]['nodes'][0]['params']['color']['v']=[1,0,0,1]
        check(info(revised) == predicted, 'precise color revision preserves every other native field')
        revised_maps = maps(revised,'red-maps')
        check(revised_maps['Paint_basecolor.png']['pixels'] == bytes((255,0,0,255))*(64*64), 'revised base color matches analytic red')
        check(all(revised_maps[name] == data for name,data in original_maps.items() if name != 'Paint_basecolor.png'), 'five unrequested PBR map files remain byte-identical')
        for name,path in [('preview',revised),('cold-preview',revised)]:
            value('render',path,out/(name+'.png'),'--size','64x64','--scene','sphere','--full')
        image=Image.open(out/'preview.png').convert('RGBA')
        check(image.size == (64,64) and len(set(zip(*(iter(image.tobytes()),)*4))) > 16, 'CPU material sphere has spatially varying pixels')
        check(sha(out/'preview.png') == sha(out/'cold-preview.png'), 'fresh-process CPU preview is repeatable')
        atomic=out/'atomic.mcraft';value('new','atomics',atomic,'--size','64','--name','Atomic')
        atomic_before=info(atomic); atomic_maps=maps(atomic,'atomic-maps')
        check(any(len(set(data['pixels'])) > 16 for data in atomic_maps.values()), 'native function/pattern sample produces nonuniform maps')
        atomic_cold=out/'atomic-cold.mcraft';edit(atomic,atomic_cold,'file.save',{'path':str(atomic_cold)})
        check(info(atomic_cold) == atomic_before and maps(atomic_cold,'atomic-cold-maps') == atomic_maps, 'function/pattern graph fields and maps survive cold reopen')
        material=out/'paint.mcmat';value('run',revised,'file.exportMaterial',json.dumps({'path':str(material),'size':64}))
        with zipfile.ZipFile(material) as archive:
            manifest=json.loads(archive.read('material.json'))
            check(manifest['version'] == 2 and len(manifest['maps']) == 6 and 'source.sbs' in archive.namelist(), 'portable material contains six maps and editable SBS source')
            native=out/'portable-source.sbs';native.write_bytes(archive.read('source.sbs'))
        check(info(native) == predicted, 'portable material source retains revised native state')
        call('info',material,fail='explicit portable-material source admission')
        call('run',source,'file.sendToTextureCraft','{}',fail='managed cross-application publication')
        # Create a genuine saved cross-package instance from two native documents.
        # Reopening resolves only the exact archived dependency bytes.
        linked_package=out/'linked-package.mcraft'; script=out/'linked-package.json'
        script.write_text(json.dumps({'open':str(source),'steps':[
            {'id':'file.newPackage','params':{'name':'Dependent'}},
            {'id':'graph.instance.add','params':{'document':1,'graph':'Paint'}}],
            'save':str(linked_package)}))
        value('batch',script)
        linked_info=value('snapshot',linked_package)
        check(len(linked_info['archivedPackages'])==2 and linked_info['loadWarnings']==[] and linked_info['cookedNodeCount']==0, 'immutable archived dependency reopens without a cook or ambient alias')
        call('run',source,'file.open',json.dumps({'path':'sbs://functions.sbs'}),fail='automatic libraries are disabled')
        catalog=value('nodes');check({'uniform','pixel_processor','fx_map','output'} <= {n['id'] for n in catalog}, 'native primitive catalog includes editable graph processors')
        fake_library=out/'library';fake_library.mkdir();(fake_library/'functions.sbs').write_text('<invalid/>')
        environment=dict(os.environ);environment['MATERIALCRAFT_SBS_DIR']=str(fake_library)
        check(json.loads(call('run','sample','library.functions','{}',env=environment)) == [], 'ambient library override cannot supply unqualified converted functions')
        external=out/'external.png';Image.new('RGBA',(2,2),(255,0,0,255)).save(external)
        embedded=out/'embedded.mcraft';edit(source,embedded,'file.importBitmap',{'path':str(external),'name':'Reference'})
        embedded_before=info(embedded)
        check(len(embedded_before['resources']) == 1, 'explicit admitted bitmap remains an editable embedded resource')
        with zipfile.ZipFile(embedded) as archive:
            check(any(archive.read(name) == external.read_bytes() for name in archive.namelist() if name.startswith('resources/')), 'archive retains original imported image bytes')
        embedded_cold=out/'embedded-cold.mcraft';edit(embedded,embedded_cold,'file.save',{'path':str(embedded_cold)})
        check(info(embedded_cold) == embedded_before and maps(embedded_cold,'embedded-maps') == original_maps, 'embedded resource native fields and unrelated maps survive cold reopen')
        linked=out/'linked.sbs';linked.write_text('<package><content><resource><identifier v="external"/><filepath v="external.png"/></resource></content></package>')
        call('info',linked,fail='refuses recovered or unsupported content')
        unknown=out/'unknown.sbs';unknown.write_text('<package><content><future><identifier v="unknown"/></future></content></package>')
        call('info',unknown,fail='refuses recovered or unsupported content')
        check(source.read_bytes() == original, 'all probes leave original native input unchanged')
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'seconds':time.monotonic()-started,'catalog_nodes':len(catalog),
                  'scope':'private macOS ARM64 engine; no runtime, installed, Linux/Cloud, arbitrary-import or full native-CI claim','remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps({'passed':len(checks),'native_calls':len(calls),'evidence':str(out/'evidence.json')}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:
        (out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__ == '__main__':main()
