#!/usr/bin/env python3
"""Managed portable material roundtrip, real Texture layers and exact revisions."""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from studio_runtime import material_bundle as bundle, material_source as source, material_recipes as recipes
from studio_runtime import texture_material as handoff, texture_document as texture_document
from studio_runtime.store import Store
from studio_runtime.worker import Worker
from material_recipes_check import oracle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('material','texture','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=args.output.resolve();root.mkdir(parents=True);material=args.material.resolve();texture=args.texture.resolve();checks=[];jobs=[]
    os.environ['PATH']=str(material.parent)+':'+str(texture.parent)+':/usr/bin:/bin'
    def check(label,ok=True):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def refused(label,action,part=None):
        try:action()
        except ValueError as error:check(label,part is None or part in str(error))
        else:raise AssertionError('accepted '+label)
    state=root/'store';store=Store(state);runtime=Path(__file__).resolve().parents[1]/'runtime'
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
    def call(name,arguments):
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':arguments}}
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps(request)+'\n').encode(),capture_output=True,timeout=30)
        check('public MCP exits',result.returncode==0);reply=json.loads(result.stdout)
        if 'error' in reply:raise AssertionError(reply)
        value=reply['result']
        if value.get('isError'):raise ValueError(value['content'][0]['text'])
        return json.loads(value['content'][0]['text'])
    def job(project,operation,params,key,previous=None,success=True,cli=False):
        arguments={'project':project,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:arguments['source_revision']=previous['id']
        if cli:
            spec=root/(key+'.json');spec.write_text(json.dumps(params));program="import sys;sys.path.insert(0,sys.argv.pop(1));from studio_runtime.__main__ import main;raise SystemExit(main(product='dobe'))"
            argv=[sys.executable,'-I','-B','-c',program,str(runtime),'--state',str(state),'submit',project,operation,'--parameters',str(spec),'--key',key]
            if previous:argv+=['--source',previous['id']]
            result=subprocess.run(argv,capture_output=True,timeout=30);check(key+' CLI submit exits',result.returncode==0);submitted=json.loads(result.stdout)
        else:submitted=call('submit_job',arguments)
        check(key+' idempotency after client exit',call('submit_job',arguments)['id']==submitted['id'])
        Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual)
        if actual['state']!=('succeeded' if success else 'failed'):raise AssertionError(actual)
        check(key+' terminal expected state')
        if not success:
            check(key+' failure preserves head',actual['result_revision'] is None and store.get_project('local',project)['head']==previous['id']);return actual
        return call('get_revision',{'revision':actual['result_revision']})
    def checkout(label,rev):
        path=root/label;call('export_project',{'revision':rev['id'],'destination':str(path)});return path
    def asset(project,path):return call('import_asset',{'project':project,'source':str(path)})['id']
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def inspect(path):return texture_document.read_native(path/'native/document.tcraft')
    def pixels(path):
        report=json.loads((path/'exports/inspection.json').read_text());result={}
        for item in report['maps']:
            channel=item['file'].split('_')[-1].removesuffix('.png')
            with Image.open(path/'exports/maps'/item['file']) as image:result[channel]=image.convert('RGBA').tobytes()
        return result
    try:
        params={'recipe':'ceramic_tiles','version':1,'resolution':128,'controls':{'repeat':4,'relief':.35}}
        project=call('create_project',{'name':'Material bundle'})['id'];first=job(project,'material.create',params,'source')
        bundled=job(project,'material.bundle',{'graph':'Surface'},'bundle',first,cli=True);files=checkout('material',bundled)
        data=(files/'exports/material.mcmat').read_bytes();admitted=bundle.inspect_bytes(data);original=admitted['members']['source.mcraft'];manifest=admitted['manifest']
        check('version2 bundle owns exact editable source',manifest['version']==2 and original==(files/'native/document.mcraft').read_bytes() and len(admitted['maps'])==6)
        check('public bundle reports bounded actual cook',bundled['validation']['bundle_export_performed'] and bundled['validation']['cook_performed'])
        second=root/'cold.mcmat';bundle.export(root,files/'native/document.mcraft',second,{'graph':'Surface'},material)
        check('bundle archive byte reproducible',second.read_bytes()==data)
        source_profile=admitted['profile'];graph=bundle.graph_of(source_profile,'Surface')
        check('exposed metadata including descriptions retained',manifest['parameters']==[{**p,'value':p['default']} for p in graph['exposed']])
        def altered(change):
            m=copy.deepcopy(manifest);members={k:v for k,v in admitted['members'].items() if k!='material.json'};change(m,members);return bundle.pack(m,members)
        for label,change in [
            ('version downgrade',lambda m,b:m.update(version=1)),('boolean version',lambda m,b:m.update(version=True)),
            ('metadata drift',lambda m,b:m['parameters'][0].update(label='Wrong')),
            ('map alias',lambda m,b:m['maps'][0].update(usage='normal')),
            ('map traversal',lambda m,b:m['maps'][0].update(file='../map.png')),
            ('duplicate map',lambda m,b:m['maps'].append(copy.deepcopy(m['maps'][0]))),
            ('wrong color transfer',lambda m,b:m['maps'][0].update(colorSpace='linear')),
            ('unknown metadata',lambda m,b:m.update(future=True)),
            ('unaccounted payload',lambda m,b:b.update({'extra.bin':b'owned'})),
            ('size mismatch',lambda m,b:m.update(size=[64,128])),
            ('truncated image',lambda m,b:b.update({m['maps'][0]['file']:b'broken'})),
            ('truncated source',lambda m,b:b.update({'source.mcraft':b'broken'})),
        ]:refused(label,lambda change=change:bundle.inspect_bytes(altered(change)))
        def wrong_pixels(m,members):
            item=next(i for i in m['maps'] if i['usage']=='roughness');stream=io.BytesIO();Image.new('I;16',(128,128),1).save(stream,format='PNG');members[item['file']]=stream.getvalue()
        bad=altered(wrong_pixels);check('structural admission is not a cook proof',not bundle.inspect_bytes(bad)['cook_verified'])
        refused('fresh bounded cook detects substituted map',lambda:bundle.verify(root,bad,material),'fresh bounded source cook')
        bad_path=root/'substituted.mcmat';bad_path.write_bytes(bad)
        # Import the complete bundle as an editable Material project, then revise it.
        returned=call('create_project',{'name':'Recovered material source'})['id'];a=asset(returned,files/'exports/material.mcmat')
        imported=job(returned,'material.import',{'asset':a,'format':'mcmat'},'bundle-import');back=checkout('reopened-material',imported)
        check('bundle import retains entire original and exact inner source',(back/'native/original.input').read_bytes()==data and (back/'native/document.mcraft').read_bytes()==original)
        controls=recipes.normalize(params)['controls'];edit={'expected_sha256':hashlib.sha256(original).hexdigest(),'edits':[{'kind':'input.default','package':'package.sbs','graph':'Surface','name':'color_r','expected':{'t':'float','v':controls['color_r']},'value':{'t':'float','v':.75}}]}
        revised=job(returned,'material.edit',edit,'recolor',imported);rebundled=job(returned,'material.bundle',{'graph':'Surface'},'rebundle',revised);blue=checkout('blue-material',rebundled)
        check('later revision preserves original complete imported bundle',(blue/'native/original.input').read_bytes()==data)
        # Texture uses the managed v2 reader and actual native Texture rendering.
        target=call('create_project',{'name':'Coherent Texture'})['id']
        base=job(target,'texture.create',{'name':'Coherent Texture','mesh':'plane','resolution':128,'layers':[{'name':'Undercoat','sources':{'BaseColor':{'Uniform':[.25,.25,.25]}}}]},'texture-create')
        before=checkout('texture-before',base);before_doc=inspect(before);a=asset(target,files/'exports/material.mcmat')
        apply={'asset':a,'expected_sha256':before_doc['source_sha256'],'texture_set':0,'height_mode':'unsigned'}
        applied=job(target,'texture.material',apply,'apply',base);painted=checkout('texture-applied',applied);current=inspect(painted)
        report=json.loads((painted/'exports/inspection.json').read_text())['material_handoff'];layer=report['layer']
        check('real managed handoff and no legacy recook',applied['validation']['material_handoff_verified'] and report['bounded_source_cook_verified'] and not report['ambient_recook_authorized'] and not report['legacy_v1_reader_used'])
        check('old layer and initial Texture preserved',current['structure']['project']['layers']['1']==before_doc['structure']['project']['layers']['1'] and (painted/'native/source.tcraft').read_bytes()==(before/'native/source.tcraft').read_bytes())
        check('every prior embedded member preserved',all(current['members'][k]==v for k,v in before_doc['members'].items() if k!='project.json'))
        fill=current['structure']['project']['layers'][str(layer)]['kind']['Fill']
        check('linked exact source retained',current['members']['resources/'+fill['link']['package']]==original)
        expected=oracle('ceramic_tiles',controls,128);rendered=pixels(painted)
        for channel in ('baseColor','roughness','metallic','ambientOcclusion'):
            check('actual Texture all-pixel '+channel,max(abs(a-b) for a,b in zip(expected[channel],rendered[channel]))<=1)
        height=next(m for m in admitted['maps'] if m['usage']=='height');himage=Image.open(io.BytesIO(admitted['members'][height['file']]))
        expected_height=bytes(c for value in himage.get_flattened_data() for c in [int((int(value)/65535*.5+.5)*255+.5)]*3+[255])
        check('unsigned height arrives with explicit signed export encoding',max(abs(a-b) for a,b in zip(expected_height,rendered['height']))<=1)
        for item in admitted['maps']:
            channel=handoff.USAGES[item['usage']]
            if channel=='Height':continue
            check('exact embedded map '+channel,current['members']['resources/'+fill['sources'][channel]['Image']['name']]==admitted['members'][item['file']])
        # Replacing a material keeps the same layer and all surrounding work.
        a2=asset(target,blue/'exports/material.mcmat');replace={'asset':a2,'expected_sha256':current['source_sha256'],'texture_set':0,'height_mode':'unsigned','layer':layer}
        replaced=job(target,'texture.material',replace,'replace',applied,cli=True);after=checkout('texture-replaced',replaced);after_doc=inspect(after);recolored=pixels(after)
        check('replace changes baseColor only',recolored['baseColor']!=rendered['baseColor'] and all(recolored[k]==rendered[k] for k in rendered if k!='baseColor'))
        check('replace retains layer allocator and old resource bytes',after_doc['structure']['project']['next_id']==current['structure']['project']['next_id'] and all(after_doc['members'][k]==v for k,v in current['members'].items() if k!='project.json'))
        repeated=job(target,'texture.material',{**replace,'expected_sha256':after_doc['source_sha256']},'same-bundle',replaced);same=checkout('texture-same',repeated)
        same_report=json.loads((same/'exports/inspection.json').read_text())['material_handoff']
        check('immutable resources reused within project',same_report['new_resources']==[] and len(same_report['reused_resources'])==7)
        check('repeat replacement preserves entire native project',inspect(same)['structure']['project']==after_doc['structure']['project'])
        bad_asset=asset(target,bad_path)
        job(target,'texture.material',{**replace,'asset':bad_asset,'expected_sha256':inspect(same)['source_sha256']},'bad-map',repeated,success=False)
        job(target,'texture.material',{**replace,'expected_sha256':'0'*64},'stale-source',repeated,success=False)
        unrelated=call('create_project',{'name':'Different owner scope'})['id'];foreign=asset(unrelated,files/'exports/material.mcmat')
        refused('foreign project asset denied',lambda:call('submit_job',{'project':target,'operation':'texture.material','parameters':{**replace,'asset':foreign},'idempotency_key':'foreign','source_revision':repeated['id']}))
        portable=store.import_project('local',same,'Portable Texture');inspected=job(portable['project']['id'],'texture.inspect',{},'portable-inspect',portable['revision']);portable_files=checkout('portable-texture',inspected)
        check('portable linked source and resources independent of old asset IDs',inspect(portable_files)['members']==inspect(same)['members'])
        # Direct structural preconditions and deliberate height policy are explicit.
        for label,delta in [('missing height mode',{'height_mode':None}),('wrong set',{'texture_set':1}),('not linked target',{'layer':1})]:
            opts={**replace,'expected_sha256':after_doc['source_sha256'],**delta}
            if opts['height_mode'] is None:del opts['height_mode']
            refused(label,lambda label=label,opts=opts:handoff.apply(root/label,after/'native/document.tcraft',blue/'exports/material.mcmat',opts,texture,material))
        result={'passed':True,'checks':checks,'durable_jobs':len(jobs),'successful_jobs':sum(j['state']=='succeeded' for j in jobs),
                'public_cli_mcp':True,'bundle_version':2,'bounded_import_recook':True,'exact_originals':True,'material_texture_handoff':True,
                'native_engines_unchanged':True,'installed_qualification':False,'visual_approval':False,'remote_actions':False,'goal_complete':False}
        (root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks),'jobs':len(jobs),'successful':result['successful_jobs']}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:(root/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
