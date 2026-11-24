"""Source-preserving map exports from one bounded native evaluation.

Every selected raster is decoded completely before a durable revision can be
published. Native map labels remain metadata; filenames use fixed node IDs.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from . import material_document as document, material_compute as compute, texture_images
from .material_container import require
from .material_graphs import USAGES

DEPTHS={'png':(8,16),'jpg':(8,),'tga':(8,),'bmp':(8,),'webp':(8,),'exr':(32,),'hdr':(32,)}
FORMATS={'png':'PNG','jpg':'JPEG','tga':'TGA','bmp':'BMP','webp':'WEBP','exr':'EXR','hdr':'HDR'}
LIMITS={'maps':256,'texels':33_554_432,'fileBytes':64<<20,'totalBytes':512<<20}


def label(value):return type(value) is str and 1<=len(value.encode('utf-8'))<=4096


def validate(params):
    require(type(params) is dict and {'graph','format','depth'}<=set(params)<=
            {'graph','format','depth','outputs','color_spaces','discard_alpha'}, 'map export has missing or unexpected fields')
    compute.validate({'graph':params['graph']})
    require(type(params['format']) is str and params['format'] in DEPTHS and type(params['depth']) is int
            and params['depth'] in DEPTHS[params['format']], 'map format/depth combination is unsupported')
    if 'outputs' in params:
        values=params['outputs'];require(type(values) is list and 1<=len(values)<=LIMITS['maps'] and all(label(v) for v in values)
            and len(set(values))==len(values), 'map output selection must contain unique bounded identifiers')
    values=params.get('color_spaces',{})
    require(type(values) is dict and len(values)<=LIMITS['maps'] and all(label(k) and type(v) is str and v in ('srgb','linear','raw') for k,v in values.items()),
            'map color-space overrides are invalid')
    require(type(params.get('discard_alpha',False)) is bool, 'map alpha discard must be explicit boolean')
    require(len(json.dumps(params,allow_nan=False).encode('utf-8'))<=1<<20, 'map options exceed their byte budget')


def export(root,path,destination,params,executable,*,seconds=120,cancelled=lambda:False):
    validate(params);root=Path(root).resolve(strict=True);path=document.owned(root,path);destination=document.owned(root,destination)
    require(destination.parent.is_dir() and not destination.exists(), 'map export requires a new owned destination')
    profile=document.read_native(path);package=profile['container']['root']
    graphs=profile['model']['packages'][package]['graphs']
    choices=[(i,g) for i,g in enumerate(graphs) if '/'.join(filter(None,(g.get('folder'),g['name'])))==params['graph']
             and g.get('function') is None]
    require(len(choices)==1, 'map graph is absent or is a standalone function');index,graph=choices[0]
    process=document.Engine(executable,root,seconds=seconds,cancelled=cancelled)
    process.observe(path,profile)
    try:
        with tempfile.TemporaryDirectory(prefix='.material-map-options-',dir=root) as temporary:
            options=Path(temporary)/'request.json';options.write_text(json.dumps({k:v for k,v in params.items() if k!='graph'},allow_nan=False))
            reply=document.snapshot_json(process._run('maps',path,index,options,destination))
        require(type(reply) is dict and set(reply)=={'evaluation','maps','skipped','format','depth','texels','bytes','limits'}, 'map export envelope differs')
        nodes,usage=compute.validate_reply(profile,index,reply['evaluation'])
        require(reply['format']==params['format'] and type(reply['depth']) is int and reply['depth']==params['depth'] and reply['limits']==LIMITS,
                'map export policy differs')
        by_node={node['id']:node for node in nodes};bridges=[node for node in graph['nodes'] if node['def']=='output']
        # Output identity and usage come from the independently predicted graph.
        expected=[];skipped=[];names=set();requested=set(params.get('outputs',[]))
        for bridge in bridges:
            values=bridge['params'];name=values['identifier']['v']
            require(label(name) and name not in names, 'map output identifiers are empty or ambiguous');names.add(name)
            if 'outputs' in params and name not in requested:continue
            row=by_node[bridge['id']];rasters=[o for o in row['outputs'] if 'width' in o]
            if not rasters:
                require('outputs' not in params, 'selected map has no raster output')
                skipped.append({'node':bridge['id'],'identifier':name,'reason':'non-raster-output'});continue
            require(len(rasters)==1, 'output bridge raster inventory differs')
            expected.append((bridge,name,rasters[0]))
        require(not requested-names and 1<=len(expected)<=LIMITS['maps'], 'selected map inventory is absent or oversized')
        require(set(params.get('color_spaces',{}))<={name for _,name,_ in expected}, 'map color override does not name a selected raster')
        require(reply['skipped']==skipped and type(reply['maps']) is list and len(reply['maps'])==len(expected), 'map export omitted or added outputs')
        records=[];total_bytes=0;texels=0;filenames=[]
        for actual,(bridge,name,raster) in zip(reply['maps'],expected):
            fields={'node','identifier','usage','file','width','height','sourceChannels','colorSpace','bytes','alphaDiscarded','encoding','integerClamping'}
            require(type(actual) is dict and set(actual)==fields and type(actual['node']) is int and actual['node']==bridge['id']
                    and actual['identifier']==name, 'map record identity or fields differ')
            filename=f"map-{bridge['id']}.{params['format']}";require(actual['file']==filename, 'map filename is not its fixed node identifier')
            require(all(type(actual[k]) is int and actual[k]==raster[k] for k in ('width','height'))
                    and type(actual['sourceChannels']) is int and actual['sourceChannels']==raster['channels'], 'map dimensions or source channels differ')
            expected_usage=USAGES[bridge['params']['usage']['v']]
            require(actual['usage']==expected_usage and type(actual['alphaDiscarded']) is bool
                    and (not actual['alphaDiscarded'] or params.get('discard_alpha') is True), 'map usage or alpha policy differs')
            floating=params['format'] in ('exr','hdr')
            space=params.get('color_spaces',{}).get(name)
            if space is None:space='raw' if raster['channels']==1 else 'linear' if floating else ('srgb' if actual['usage'] in SRGB_USAGES else 'raw')
            require(actual['colorSpace']==space and not (space=='srgb' and raster['channels']==1), 'map color-space policy differs')
            encoding='rgbe-shared-exponent' if params['format']=='hdr' else 'float32-rgb' if params['format']=='exr' else 'lossy-unorm8' if params['format']=='jpg' else 'unorm'+str(params['depth'])
            require(actual['encoding']==encoding and actual['integerClamping'] is (not floating), 'map sample encoding policy differs')
            item=document.owned(root,destination/filename);require(item.is_file() and item.stat().st_nlink==1, 'map must be one owned regular file')
            require(0<item.stat().st_size<=LIMITS['fileBytes'], 'encoded map exceeds its byte budget')
            data=document.container.read_bytes(item);decoded=texture_images.inspect_bytes(data)
            require(decoded['format']==FORMATS[params['format']] and decoded['width']==actual['width'] and decoded['height']==actual['height']
                    and type(actual['bytes']) is int and actual['bytes']==len(data), 'decoded map format dimensions or bytes differ')
            if params['format']=='png':require(data[24]==params['depth'], 'PNG sample depth differs')
            if params['format']=='exr':require(decoded['channels']==['B','G','R'] and decoded['channel_sample_bytes']==[4,4,4], 'EXR samples are not RGB float32')
            total_bytes+=len(data);texels+=actual['width']*actual['height'];filenames.append(filename)
            require(total_bytes<=LIMITS['totalBytes'] and texels<=LIMITS['texels'], 'map aggregate budgets differ')
            records.append({**actual,'sha256':hashlib.sha256(data).hexdigest(),'decoded':decoded})
        require(sorted(p.name for p in destination.iterdir())==sorted(filenames), 'map output directory has an unexpected inventory')
        require(type(reply['bytes']) is int and reply['bytes']==total_bytes and type(reply['texels']) is int and reply['texels']==texels, 'map totals differ')
        require(document.container.read_bytes(path)==profile['container']['source_bytes'] and not cancelled(), 'map source changed or export was cancelled')
        return {'schema_version':1,'document_sha256':profile['container']['source_sha256'],'graph':params['graph'],'native_graph_index':index,
                'maps':records,'skipped':skipped,'format':params['format'],'depth':params['depth'],'bytes':total_bytes,'texels':texels,
                'usage':usage,'evaluation_limits':compute.LIMITS,'export_limits':LIMITS,'native_calls':process.calls,'native_model_equal':True,
                'full_size':True,'finite_outputs':True,'complete_decoding':True,'source_bytes_unchanged':True,'cook_performed':True,
                'map_export_performed':True,'preview_performed':False,'visual_approval':False,'outer_worker_limits_required':True}
    except BaseException:
        shutil.rmtree(destination,ignore_errors=True);raise


# Match the pinned native usage policy; checked against output bridge semantics.
SRGB_USAGES={'baseColor','diffuse','emissive','specular','specularEdgeColor','scatteringColor','absorptionColor','coatColor','sheenColor','reflection','ambient'}
