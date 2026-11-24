#!/usr/bin/env python3
"""Qualify reusable Write typography, editable models and real durable delivery."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('resources','request','output'): parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args(); out=args.output.resolve();out.mkdir(parents=True)
    runtime=args.resources.resolve()/'runtime';sys.path.insert(0,str(runtime))
    from studio_runtime import write_recipes as recipes,write_revision as revision,write_project as project,write_binding,write_engine
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    checks=[];refusals=[];jobs=[];request=json.loads(args.request.read_bytes());state=out/'state';store=Store(state)
    code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
    def check(label,value=True):
        if not value:raise AssertionError(label)
        checks.append(label)
    def tool(name,params):
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(runtime),str(state)],input=(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':params}})+'\n').encode(),capture_output=True,timeout=30)
        if result.returncode:raise AssertionError(result.stderr.decode()[:1000])
        reply=json.loads(result.stdout)['result']
        if reply.get('isError'):raise ValueError(reply['content'][0]['text'])
        return json.loads(reply['content'][0]['text'])
    def job(identity,operation,params,key,previous=None):
        args={'project':identity,'operation':operation,'parameters':params,'idempotency_key':key}
        if previous:args['source_revision']=previous['id']
        submitted=tool('submit_job',args);check(key+' is idempotent',tool('submit_job',args)['id']==submitted['id'])
        Worker(store).run_one();actual=tool('get_job',{'job':submitted['id']});jobs.append(actual)
        check(key+' durable native success '+str(actual.get('error')),actual['state']=='succeeded')
        return tool('get_revision',{'revision':actual['result_revision']})
    def checkout(name,value):
        path=out/name;store.checkout('local',value['id'],path);return path
    def refused(label,params):
        try:recipes.normalize(params)
        except ValueError as error:checks.append(label);refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    try:
        model,production=recipes.compile_recipe(request)
        check('same request compiles to identical complete model and selectors',recipes.compile_recipe(request)==(model,production))
        check('recipe invents no creation timestamp',model['core']['created']==model['core']['modified']=='' and model['core']['revision']==0)
        for item,selectors in zip(request['sections'],production['selectors']['sections']):
            check('authored heading and paragraphs retain exact user text',revision.locate(model,selectors['heading'])['text']==item['heading']
                  and [revision.locate(model,p)['text'] for p in selectors['paragraphs']]==item['paragraphs'])
        for item,selectors in zip(request['deliverables'],production['selectors']['deliverables']):
            check('table selectors address exact editable cells',all(revision.locate(model,path)['text']==item[key] for key,path in selectors.items()))
        identity=tool('create_project',{'name':'Coherent visual production'})['id']
        created=job(identity,'write.create',request,'create');initial=checkout('created',created)
        check('complete authored model cold-opens without normalization',json.loads((initial/'native/document.json').read_bytes())==model)
        rendered=job(identity,'write.export',{'format':'png'},'png',created);raster=checkout('png',rendered)
        report=json.loads((raster/'exports/delivery/delivery.json').read_bytes())
        check('designed brief fits one A4 page without font substitutions',report['page_count']==1 and report['accepted_font_substitutions']==[]
              and [(p['width'],p['height']) for p in report['outputs']]==[(596,842)])
        glyphs=json.loads((raster/'exports/delivery/glyphs.json').read_bytes())
        check('actual serif and sans faces match recipe typography',{face['family'] for face in glyphs['faces']}=={'Source Sans 3','Source Serif 4'})
        printed=job(identity,'write.export',{'format':'pdf'},'pdf',rendered);pdf=checkout('pdf',printed)
        check('independent PDF reader sees all recipe text',json.loads((pdf/'exports/delivery/delivery.json').read_bytes())['independent_pdf_checks'][0]['text_checks'][0]['normalized_character_inventory_equal'])
        recorded=(initial/'recipes/write-production.json').read_bytes()
        check('recipe keeps selectors, normalized controls and source hash',json.loads(recorded)['source_model_sha256']==project.sha((initial/'native/document.json').read_bytes()))
        path=production['selectors']['sections'][0]['paragraphs'][0];text=revision.locate(model,path)['text'];start=text.encode().index(b'restrained colour')
        edit={'expected_sha256':project.sha((pdf/'native/project.dobewrite').read_bytes()),'edits':[{'kind':'text.replace','path':path,'start':start,'end':start+len(b'restrained colour'),'expected':'restrained colour','value':'warm monochrome'}]}
        edited=job(identity,'write.edit',edit,'edit',printed);changed=checkout('edited',edited)
        predicted=copy.deepcopy(model);para=revision.locate(predicted,path);para['text']=text.replace('restrained colour','warm monochrome');para['runs'][0]['len']=len(para['text'].encode())
        check('precise edit changes only selected recipe paragraph',json.loads((changed/'native/document.json').read_bytes())==predicted)
        check('source and production recipe remain immutable after delivery and revision',(changed/'native/original.json').read_bytes()==(initial/'native/original.json').read_bytes()
              and (changed/'recipes/write-production.json').read_bytes()==recorded)
        portable=store.import_project('local',changed,'Portable designed brief')
        inspected=job(portable['project']['id'],'write.inspect',{},'portable',portable['revision'])
        check('transferred recipe stays editable and attributable',(checkout('portable',inspected)/'recipes/write-production.json').read_bytes()==recorded)
        bright=copy.deepcopy(request);bright['controls']={'paper':'letter','margin':37.123456,'body_size':10.678901,'accent':'#F5D442','heading_face':'sans'}
        variant,variant_report=recipes.compile_recipe(bright)
        check('bright accent keeps exact table fill and uses readable text',variant_report['header_text_color']==[0,0,0] and variant_report['header_contrast']>=4.5
              and variant_report['heading_contrast']>=4.5 and variant_report['heading_color']!=[245,212,66])
        variant_id=tool('create_project',{'name':'Light accent letter brief'})['id'];variant_revision=job(variant_id,'write.create',bright,'variant')
        variant_path=checkout('variant',variant_revision)
        check('fractional controls match complete native binary32 model',revision.canonical(json.loads((variant_path/'native/document.json').read_bytes()))==revision.canonical(variant))
        variant_export=job(variant_id,'write.export',{'format':'png'},'variant-png',variant_revision);variant_png=checkout('variant-png',variant_export)
        variant_delivery=json.loads((variant_png/'exports/delivery/delivery.json').read_bytes())
        check('letter and sans variant renders without font substitutions',variant_delivery['page_count']==1 and variant_delivery['accepted_font_substitutions']==[]
              and [(p['width'],p['height']) for p in variant_delivery['outputs']]==[(612,792)])
        for label,change in [('unknown recipe',{'recipe':'unknown'}),('boolean version',{'version':True}),('unknown content field',{'private_path':'/tmp/source'}),
                             ('unknown control',{'controls':{'font_path':'/tmp/font'}}),('invalid accent',{'controls':{'accent':'red'}}),
                             ('nonfinite margin',{'controls':{'margin':float('nan')}}),('invalid body size',{'controls':{'body_size':100}}),
                             ('empty sections',{'sections':[]}),('inline marker title',{'title':'unsafe\ufffc'}),('multiline title',{'title':'two\nlines'})]:
            refused(label,{**request,**change})
        check('template stays identical to pinned native defaults',project.sha((runtime/'studio_runtime/write_recipe_base.json').read_bytes())==recipes.BASE_SHA256)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'durable_jobs':len(jobs),'succeeded':len(jobs),
                  'native_model_exact':True,'no_font_substitutions':True,'deterministic_recipe':True,'remote_actions':False,
                  'installed_qualification':False,'source_format_fidelity_qualified':False,'visual_approval':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'refusals':len(refusals),'durable_jobs':len(jobs)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals},indent=2)+'\n');raise
    finally:(out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__=='__main__':main()
