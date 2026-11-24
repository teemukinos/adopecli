"""Source-preserving 2D/3D CPU previews from one bounded native cook."""
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile

from . import material_document as document, material_compute as compute, material_maps as maps, texture_images
from .material_container import require
from .material_graphs import USAGES

SCENES=('material_ball','sphere','cube','rounded_cube','cylinder','torus','plane','crate','udim_plane')
ENVIRONMENTS=('studio','contrast','overcast','sunset','warehouse','night')
CHANNELS=('baseColor','normal','roughness','metallic','height','ambientOcclusion','emissive','opacity')
LIMITS={'pixels':16_777_216,'samples':67_108_864,'rayWork':1_073_741_824,'bytes':64<<20}
DEFAULTS={'scene':'sphere','environment':'studio','yaw':35.,'pitch':25.,'distance':3.2,'target':[0.,0.,0.],'tiling':1.,'exposure':0.,
          'environment_rotation':0.,'normal_y_flip':False,'show_environment':False,'supersample':2,'ao_rays':0,'key_light':0.,
          'transparency':True,'alpha_view':False,'displacement':0.,'displacement_level':0.,'triangles':500_000,'channels':{}}
RANGES={'yaw':(-360.,360.),'pitch':(-89.,89.),'distance':(1.05,50.),'tiling':(.1,64.),'exposure':(-16.,16.),
        'environment_rotation':(-360.,360.),'key_light':(0.,16.),'displacement':(0.,.5),'displacement_level':(0.,1.)}


def number(v,lo,hi):return type(v) in (int,float) and math.isfinite(v) and lo<=v<=hi


def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]


def normalize(params):
    require(type(params) is dict and {'graph','view','width','height'}<=set(params), 'preview requires graph, view and exact dimensions')
    compute.validate({'graph':params['graph']})
    require(type(params['view']) is str and params['view'] in ('2d','3d'), 'preview view must be 2d or 3d')
    require(all(type(params[k]) is int and 1<=params[k]<=4096 for k in ('width','height')), 'preview dimensions exceed their budget')
    pixels=params['width']*params['height'];require(pixels<=LIMITS['pixels'], 'preview pixels exceed their budget')
    request={'view':params['view'],'width':params['width'],'height':params['height'],'output':None,'look':None}
    if params['view']=='2d':
        require(set(params)=={'graph','view','width','height','output'} and maps.label(params['output']), '2d preview requires exactly one output identifier')
        request['output']=params['output']
    else:
        require(set(params)<={'graph','view','width','height',*DEFAULTS}, '3d preview contains unknown or 2d settings')
        look={**copy.deepcopy(DEFAULTS),**{k:v for k,v in params.items() if k in DEFAULTS}}
        require(type(look['scene']) is str and look['scene'] in SCENES and type(look['environment']) is str and look['environment'] in ENVIRONMENTS,
                'preview scene or environment is unknown')
        for name,(lo,hi) in RANGES.items():
            require(number(look[name],lo,hi), 'preview '+name+' exceeds its finite range');look[name]=f32(look[name])
        for name in ('normal_y_flip','show_environment','transparency','alpha_view'):require(type(look[name]) is bool, 'preview '+name+' must be boolean')
        require(type(look['target']) is list and len(look['target'])==3 and all(number(v,-10,10) for v in look['target']), 'preview target exceeds its range')
        look['target']=[f32(v) for v in look['target']]
        require(type(look['supersample']) is int and 1<=look['supersample']<=4 and type(look['ao_rays']) is int and 0<=look['ao_rays']<=32
                and type(look['triangles']) is int and 64<=look['triangles']<=2_000_000, 'preview sample or geometry settings exceed their range')
        require(type(look['channels']) is dict and all(k in CHANNELS and maps.label(v) for k,v in look['channels'].items()), 'preview channel mapping is invalid')
        samples=pixels*look['supersample']**2;rays=samples*8*(1+look['ao_rays']+(look['key_light']>0))
        require(samples<=LIMITS['samples'] and rays<=LIMITS['rayWork'], 'preview sample or ray-work budget exceeded')
        request['look']=look
    return request


def validate(params):normalize(params)


def render(root,path,destination,params,executable,*,seconds=120,cancelled=lambda:False):
    request=normalize(params);root=Path(root).resolve(strict=True);path=document.owned(root,path);destination=document.owned(root,destination)
    require(destination.parent.is_dir() and not destination.exists(), 'preview requires a new owned destination')
    profile=document.read_native(path);package=profile['container']['root'];graphs=profile['model']['packages'][package]['graphs']
    choices=[(i,g) for i,g in enumerate(graphs) if '/'.join(filter(None,(g.get('folder'),g['name'])))==params['graph'] and g.get('function') is None]
    require(len(choices)==1, 'preview graph is absent or is a standalone function');index,graph=choices[0]
    process=document.Engine(executable,root,seconds=seconds,cancelled=cancelled);process.observe(path,profile)
    try:
        with tempfile.TemporaryDirectory(prefix='.material-preview-options-',dir=root) as temporary:
            options=Path(temporary)/'request.json';options.write_text(json.dumps(request,allow_nan=False))
            reply=document.snapshot_json(process._run('preview',path,index,options,destination))
        require(type(reply) is dict and set(reply)=={'evaluation','request','selection','geometry','file','bytes','pixels','samples','rayWork','finiteDisplaySamples','limits'},
                'preview envelope differs')
        nodes,usage=compute.validate_reply(profile,index,reply['evaluation'])
        require(reply['request']==request and reply['limits']==LIMITS and reply['finiteDisplaySamples'] is True, 'preview settings or execution policy differ')
        by_node={n['id']:n for n in nodes};outputs={}
        for node in graph['nodes']:
            if node['def']!='output':continue
            name=node['params']['identifier']['v'];require(name not in outputs, 'preview output identifiers are ambiguous')
            images=[v for v in by_node[node['id']]['outputs'] if 'width' in v];require(len(images)<=1, 'preview output has ambiguous rasters')
            usage_name=USAGES[node['params']['usage']['v']]
            outputs[name]=(node,images[0] if images else None,usage_name)
        selection=[];pixels=request['width']*request['height'];samples=pixels;rays=0
        if request['view']=='2d':
            require(request['output'] in outputs and outputs[request['output']][1] is not None, 'preview output is absent or is not a raster')
            node,image,usage_name=outputs[request['output']]
            selection=[{'identifier':request['output'],'node':node['id'],'usage':usage_name,'width':image['width'],'height':image['height']}]
            require(reply['geometry'] is None, '2d preview unexpectedly contains geometry')
        else:
            look=request['look'];samples=pixels*look['supersample']**2;rays=samples*8*(1+look['ao_rays']+(look['key_light']>0))
            for channel in sorted(CHANNELS):
                if channel in look['channels']:
                    name=look['channels'][channel];require(name in outputs and outputs[name][1] is not None, 'preview channel output is absent or not a raster')
                else:
                    matches=[name for name,(_,image,usage_name) in outputs.items() if image is not None and ('baseColor' if usage_name=='diffuse' else usage_name)==channel]
                    require(len(matches)<=1, 'preview usage needs an explicit channel mapping')
                    if not matches:continue
                    name=matches[0]
                node,image,_=outputs[name];selection.append({'channel':channel,'identifier':name,'node':node['id'],'width':image['width'],'height':image['height']})
            require(selection, 'preview has no assigned material channels')
            geometry=reply['geometry'];require(type(geometry) is dict and set(geometry)=={'baseTriangles','triangles','vertices','displaced'}, 'preview geometry fields differ')
            require(all(type(geometry[k]) is int for k in ('baseTriangles','triangles','vertices'))
                    and 1<=geometry['baseTriangles']<=geometry['triangles']<=look['triangles'] and 1<=geometry['vertices']<=geometry['triangles']*3
                    and type(geometry['displaced']) is bool and geometry['displaced']==(look['displacement']>0), 'preview geometry budget or displacement differs')
            if look['displacement']>0:require(any(s['channel']=='height' for s in selection), 'preview displacement has no height map')
        require(reply['selection']==selection and reply['file']=='preview.png' and all(type(reply[k]) is int and reply[k]==v for k,v in
                [('pixels',pixels),('samples',samples),('rayWork',rays)]), 'preview selection or work counters differ')
        require(sorted(p.name for p in destination.iterdir())==['preview.png'], 'preview output inventory differs')
        file=document.owned(root,destination/'preview.png');require(file.is_file() and file.stat().st_nlink==1 and 0<file.stat().st_size<=LIMITS['bytes'], 'preview file exceeds its ownership or byte budget')
        data=document.container.read_bytes(file);decoded=texture_images.inspect_bytes(data)
        require(decoded['format']=='PNG' and decoded['width']==request['width'] and decoded['height']==request['height'] and data[24:26]==bytes((8,6))
                and type(reply['bytes']) is int and reply['bytes']==len(data), 'preview pixels or byte size differ')
        require(document.container.read_bytes(path)==profile['container']['source_bytes'] and not cancelled(), 'preview source changed or render was cancelled')
        return {'schema_version':1,'document_sha256':profile['container']['source_sha256'],'graph':params['graph'],'native_graph_index':index,
                'request':request,'selection':selection,'geometry':reply['geometry'],'file':'preview.png','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'decoded':decoded,'pixels':pixels,'samples':samples,'ray_work':rays,'preview_limits':LIMITS,'evaluation_usage':usage,'evaluation_limits':compute.LIMITS,
                'native_calls':process.calls,'native_model_equal':True,'source_bytes_unchanged':True,'full_size_cook':True,'finite_display_samples':True,
                'complete_decoding':True,'cook_performed':True,'preview_performed':True,'visual_approval':False,'outer_worker_limits_required':True}
    except BaseException:
        shutil.rmtree(destination,ignore_errors=True);raise
