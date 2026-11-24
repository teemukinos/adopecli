#!/usr/bin/env python3
"""Real local Texture import/export jobs, portable sources and refusal fences."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import texture, texture_document as document, texture_workflow as workflow
from studio_runtime.store import Store
from studio_runtime.worker import Worker


def packed(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items(): archive.writestr(name, data)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--fixtures', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve(); root.mkdir(); fixtures = args.fixtures.resolve(); engine = args.engine.resolve(strict=True)
    os.environ['PATH'] = str(engine.parent) + ':/usr/bin:/bin'
    checks = []; started = time.monotonic()

    def check(label, value=True):
        assert value, label
        checks.append(label)

    def refused(label, action):
        try: action()
        except ValueError: checks.append(label)
        else: raise AssertionError('unexpected acceptance: ' + label)

    try:
        source = root / 'source.tcraft'; source.write_bytes((fixtures / 'texture-layers-check-5/uniform/cold.tcraft').read_bytes())
        profile = document.read_native(source)
        report = workflow.prepare(root, source, root/'prepared', engine, export_maps=True)
        check('native save and cold map exports preserve complete source', report['native_state_equal'] and report['export_pixels_equal'])
        check('portable original source bytes exact', (root/'prepared/native/source.tcraft').read_bytes() == source.read_bytes())
        check('native layer selector remains stable', report['mapping']['objects'] == [{'id': 1, 'layer': 1, 'role': 'layer', 'texture_set': 0}])
        basecolor = next(item for item in report['maps'] if 'baseColor' in item['file'])
        with Image.open(root/'prepared/exports/maps'/basecolor['file']) as image:
            check('actual BaseColor pixels agree with independent linear-to-sRGB oracle', image.convert('RGB').tobytes() == bytes((137,188,225)) * (image.width * image.height))
        check('preservation is not visual approval or publication', not report['visual_approval'] and not report['publication_authorized'])

        for name, relative, generated in [
            ('thumbnail', 'texture-document-native-1/input.tcraft', False),
            ('paint', 'texture-archive-native-2/native.tcraft', False),
            ('obj', 'texture-mesh-check-5/panel-cold.tcraft', False),
            ('udim', 'texture-mesh-check-5/udim-cold.tcraft', False),
            ('stl', 'texture-mesh-check-5/binary-cold.tcraft', True),
            ('baked', 'texture-project-check-3/baked-cold.tcraft', False),
            ('bake-meshes', 'texture-mesh-check-5/bake-meshes-cold.tcraft', False),
        ]:
            fixture = fixtures/relative
            if not fixture.exists():
                # A missing evidence fixture is a harness failure, never a skip.
                raise AssertionError('missing native fixture: ' + str(fixture))
            current = root/(name+'.tcraft'); current.write_bytes(fixture.read_bytes())
            if generated:
                with patch.object(workflow, 'Engine', side_effect=AssertionError('native launched before acceptance')):
                    refused('generated UV refusal precedes native launch', lambda: workflow.prepare(root,current,root/'uv-refused',engine))
            actual = workflow.prepare(root,current,root/(name+'-prepared'),engine,accept_generated_uvs=generated,export_maps=True)
            check(name+' actual native cold save and decoded map equality', actual['native_cold_reopen'] and actual['export_pixels_equal'])
            if name == 'thumbnail': check('imported thumbnail provenance remains explicit', actual['thumbnail_provenance'] is not None)

        udim = document.read_native(root/'udim.tcraft'); mixed = json.loads(udim['members']['project.json'])
        mixed['texture_sets'][0]['tile_resolutions'] = {'1001': 128, '1003': 256}
        mixed_path = root/'mixed-udim.tcraft'
        mixed_path.write_bytes(packed({**udim['members'], 'project.json': json.dumps(mixed).encode()}))
        actual = workflow.prepare(root,mixed_path,root/'mixed-udim-prepared',engine,export_maps=True)
        check('mixed UDIM resolutions retain independently predicted export sizes', {item['width'] for item in actual['maps']}=={128,256})

        missing = json.loads(profile['members']['project.json']); del missing['display']['fov']
        invalid = [
            ('unknown member', packed({**profile['members'], 'future': b'keep me'})),
            ('missing default', packed({**profile['members'], 'project.json': json.dumps(missing).encode()})),
        ]
        for index, (label, data) in enumerate(invalid):
            path = root/('invalid-'+str(index)+'.tcraft'); path.write_bytes(data)
            with patch.object(workflow, 'Engine', side_effect=AssertionError('native launched for invalid source')):
                refused(label+' refused before native launch', lambda: workflow.prepare(root,path,root/('invalid-result-'+str(index)),engine))
            check(label+' refusal leaves no prepared result', not (root/('invalid-result-'+str(index))).exists())
        symlink = root/'source-link.tcraft'; symlink.symlink_to(source)
        refused('source symlink refused', lambda: workflow.prepare(root,symlink,root/'symlink-result',engine))
        refused('existing destination refused', lambda: workflow.prepare(root,source,root/'prepared',engine))
        refused('cancelled preparation never publishes', lambda: workflow.prepare(root,source,root/'cancelled',engine,cancelled=lambda: True))
        check('cancelled destination absent', not (root/'cancelled').exists())
        with patch.object(workflow, 'MAX_EXPORT_PIXELS', 1):
            refused('aggregate map allocation budget enforced', lambda: workflow.prepare(root,source,root/'over-budget',engine,export_maps=True))
        check('over-budget destination absent', not (root/'over-budget').exists())
        refused('arbitrary native command refused by public contract', lambda: texture.validate('texture.inspect',{'command':'file.open'},'source'))
        refused('native import cannot target revision', lambda: texture.validate('texture.import',{'asset':'a'*64},'source'))
        refused('inspection requires source revision', lambda: texture.validate('texture.inspect',{},None))

        state = root/'store'; store = Store(state)
        code = "import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        def request(method, params):
            child = subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).resolve().parents[1]/'runtime'),str(state)],
                                   input=(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n').encode(),
                                   capture_output=True, timeout=20)
            assert child.returncode == 0, child.stderr
            response = json.loads(child.stdout); assert 'error' not in response, response
            return response['result']
        def call(name, arguments):
            result = request('tools/call', {'name':'dope_'+name,'arguments':arguments})
            assert not result.get('isError'), result
            return json.loads(result['content'][0]['text'])
        tools = request('tools/list', {})['tools']
        operations = next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
        check('same public MCP exposes seven typed Texture operations', set(texture.OPERATIONS) <= set(operations) and len(tools)==15)
        project = call('create_project',{'name':'Texture native proof'})['id']
        asset = store.import_asset('local',project,source)['id']
        def job(operation, parameters, key, revision=None):
            arguments={'project':project,'operation':operation,'parameters':parameters,'idempotency_key':key}
            if revision: arguments['source_revision']=revision
            first=call('submit_job',arguments)
            assert call('submit_job',arguments)['id']==first['id']
            Worker(store).run_one()
            result=call('get_job',{'job':first['id']}); assert result['state']=='succeeded',result
            return call('get_revision',{'revision':result['result_revision']})
        first=job('texture.import',{'asset':asset},'import')
        second=job('texture.inspect',{},'inspect',first['id'])
        third=job('texture.export',{},'export',second['id'])
        check('three durable jobs survive submitting client disconnection and preserve idempotency')
        checkout=root/'checkout';call('export_project',{'revision':third['id'],'destination':str(checkout)})
        check('durable original source retained after inspect/export', (checkout/'native/source.tcraft').read_bytes()==source.read_bytes())
        check('durable original revision stays immutable',call('get_revision',{'revision':first['id']})==first)
        actual=json.loads((checkout/'exports/inspection.json').read_text())
        check('durable map export is cold qualified',actual['export_pixels_equal'] and actual['maps']==report['maps'])
        imported=store.import_project('local',checkout,'Portable Texture')
        check('portable project reimport retains Texture engine identity', imported['revision']['engine']['name']=='texturecraft')
        portable = call('submit_job',{'project':imported['project']['id'],'operation':'texture.inspect','parameters':{},
                                     'idempotency_key':'portable-reopen','source_revision':imported['revision']['id']})
        Worker(store).run_one()
        check('portable bundle reopens through a fresh durable native job', call('get_job',{'job':portable['id']})['state']=='succeeded')
        bad_project=call('create_project',{'name':'Rejected native import'})['id']
        bad_asset=store.import_asset('local',bad_project,root/'invalid-0.tcraft')['id']
        rejected=call('submit_job',{'project':bad_project,'operation':'texture.import','parameters':{'asset':bad_asset},'idempotency_key':'invalid'})
        Worker(store).run_one();failed=call('get_job',{'job':rejected['id']})
        check('failed native admission publishes no revision or project head', failed['state']=='failed' and failed['result_revision'] is None
              and store.get_project('local',bad_project)['head'] is None)
        check('all original bytes unchanged',source.read_bytes()==profile['source_bytes'])
        result={'passed':True,'checks':len(checks),'cases':checks,'seconds':round(time.monotonic()-started,3),
                'durable_jobs':5,'public_tools':15,'installed_qualification':False,'goal_complete':False}
        (root/'evidence.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='cases'}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'passed':False,'cases':checks,'error':str(error)},indent=2)+'\n');raise


if __name__=='__main__':main()
