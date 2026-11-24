"""Typed version-2 Material handoff into an independently predicted Texture fill.

The runtime admits the portable manifest and verifies its maps with Material.
Texture receives a fully admitted native document, never its legacy v1 reader or
an ambient recook request. Exact bundle bytes remain a project-owned asset.
"""
import array
import copy
import hashlib
import io
from pathlib import Path
import re

from . import material_bundle as bundle, material_container, texture_authoring as authoring, texture_document as document
from . import texture_structure as structure, texture_workflow as workflow, texture_layers as layers
from .texture_structure import require

USAGES={key[0].lower()+key[1:]:key for key in structure.CHANNELS}
USAGES['diffuse']='BaseColor'
COLORS={'BaseColor','Emissive','Specular','SheenColor'}


def validate(params):
    require(type(params) is dict and {'asset','expected_sha256','texture_set'}<=set(params)<=
            {'asset','expected_sha256','texture_set','layer','name','height_mode','accept_generated_uvs'}, 'material handoff has missing or unexpected fields')
    require(type(params['expected_sha256']) is str and re.fullmatch('[0-9a-f]{64}',params['expected_sha256']), 'material handoff needs exact Texture source digest')
    require(type(params['texture_set']) is int and 0<=params['texture_set']<16, 'material texture set is invalid')
    if 'layer' in params:require(type(params['layer']) is int and 0<params['layer']<structure.MAX_ID, 'material replacement layer is invalid')
    require(not ('layer' in params and 'name' in params), 'material replacement preserves the existing layer name')
    if 'name' in params:layers.text(params['name'],128)
    if 'height_mode' in params:require(params['height_mode'] in ('unsigned','signed'), 'height mode must be unsigned or signed')


def height_image(data):
    """Encode unsigned physical height for Texture's signed image sampler."""
    from PIL import Image
    require(data[25]==0, 'unsigned height handoff needs a grayscale PNG16 map')
    with Image.open(io.BytesIO(data)) as image:
        values=array.array('H',((int(v)+65536)//2 for v in image.get_flattened_data()))
        if __import__('sys').byteorder!='little':values.byteswap()
        converted=Image.frombytes('I;16',image.size,values.tobytes());output=io.BytesIO();converted.save(output,format='PNG')
    return output.getvalue()


def apply(root,source,asset,params,texture_engine,material_engine,*,accept_generated_uvs=False):
    validate(params);root=Path(root);root.mkdir()
    before=document.read_native(source);workflow.admission(before,accept_generated_uvs=accept_generated_uvs)
    require(before['source_sha256']==params['expected_sha256'], 'material handoff source digest changed')
    original=material_container.read_bytes(asset);admitted=bundle.verify(root,original,material_engine)
    manifest=admitted['manifest'];project=copy.deepcopy(before['structure']['project']);members=dict(before['members'])
    index=params['texture_set'];require(index<len(project['texture_sets']), 'material texture set is absent')
    selected={}
    for item in admitted['maps']:
        require(item['usage'] in USAGES, 'portable material usage is not supported by Texture: '+item['usage'])
        channel=USAGES[item['usage']];require(channel not in selected, 'portable material aliases target the same Texture channel')
        require(item['colorSpace']==('srgb' if channel in COLORS else 'linear'), 'portable map transfer does not match Texture channel interpretation')
        selected[channel]=item
    require(('Height' in selected)==('height_mode' in params), 'a height map requires an explicit signed or unsigned height mode')
    if 'layer' in params:
        identity=params['layer'];require(str(identity) in project['layers'], 'material replacement layer is absent')
        layer=project['layers'][str(identity)]
        require(before['structure']['ids'][identity]['texture_set']==index, 'material replacement belongs to another texture set')
        require(type(layer['kind']) is dict and 'Fill' in layer['kind'] and layer['kind']['Fill'].get('link') is not None, 'replacement needs an existing material-linked fill')
        require(set(layer['kind']['Fill']['sources'])==set(selected), 'material replacement must retain the existing channel set')
        fill=layer['kind']['Fill']
    else:
        identity=project['next_id'];require(type(identity) is int and identity<structure.MAX_ID-1, 'material layer allocator has no headroom')
        name=params.get('name',manifest['name']);layers.text(name,128)
        fill={'sources':{},'projection':copy.deepcopy(authoring.UV)}
        layer={'id':identity,'name':name,'visible':True,'kind':{'Fill':fill},'channels':{k:{'mode':'Normal','opacity':1.} for k in selected},
               'mask':None,'content_effects':[],'color_tag':None,'height_mask':{'enabled':False,'contrast':1.,'offset':0.},'geometry_mask':None}
        project['layers'][str(identity)]=layer;project['next_id']=identity+1;project['texture_sets'][index]['stack'].append(identity)
    added=[];reused=[];conversions=[]
    def resource(data,extension):
        name='dobe-'+hashlib.sha256(data).hexdigest()+'.'+extension;key='resources/'+name
        if key in members:require(members[key]==data, 'material resource digest collision');reused.append(name)
        else:members[key]=data;added.append(name)
        return name
    package=resource(admitted['members']['source.mcraft'],'mcraft')
    sources={}
    for channel,item in selected.items():
        data=admitted['members'][item['file']]
        if channel=='Height' and params['height_mode']=='unsigned':
            converted=height_image(data);conversions.append({'channel':channel,'policy':'unsigned height to signed Texture image','input_sha256':bundle.sha(data),'output_sha256':bundle.sha(converted),'maximum_value_error':1/65535});data=converted
        sources[channel]={'Image':{'name':resource(data,'png'),'normal_format':'OpenGl'}}
    parameters=[];projected=[]
    for p in manifest['parameters']:
        parameters.append({k:copy.deepcopy(p.get(k,default)) for k,default in {'id':'','label':'','group':'','value':None,'default':None,'min':0.,'max':1.,'options':[]}.items()})
        omitted=sorted(set(p)-set(parameters[-1]))
        if omitted:projected.append({'id':p['id'],'fields_retained_in_source_and_bundle':omitted})
    ids={p['id'] for p in parameters}
    require(all(set(p['values'])<=ids for p in manifest['presets']), 'linked preset references nonportable controls')
    fill['sources']=sources;fill['link']={'name':manifest['name'],'package':package,'graph':manifest['graph'],'params':parameters,
        'presets':copy.deepcopy(manifest['presets']),'inputs':[p['identifier'] for p in manifest['inputs']],'size':manifest['size'][0]}
    channels=project['texture_sets'][index]['channels'];present={p[0] for p in channels}
    for channel in structure.CHANNELS:
        if channel in selected and channel not in present:
            fmt='Rgb16F' if channel in ('Normal','CoatNormal') else 'L16F' if channel=='Height' else 'Srgb8' if channel in COLORS else 'L8'
            channels.append([channel,fmt])
    candidate=root/'authored.tcraft';proposed=authoring.write_project(candidate,members,project);workflow.admission(proposed,accept_generated_uvs=accept_generated_uvs)
    process=workflow.Engine(texture_engine,root);saved_path=root/'canonical.tcraft';saved=process.save(candidate,saved_path)
    predicted=copy.deepcopy(project);actual_link=saved['structure']['project']['layers'][str(identity)]['kind']['Fill']['link']
    rounding=authoring.native_float_equivalence(fill['link'],actual_link)
    predicted['layers'][str(identity)]['kind']['Fill']['link']=actual_link
    document.check_preservation(proposed,saved,expected_project=predicted)
    require(material_container.read_bytes(asset)==original and source.read_bytes()==before['source_bytes'], 'material handoff changed an input')
    return saved_path,{'source_sha256':before['source_sha256'],'bundle_sha256':admitted['sha256'],'material_source_sha256':admitted['source_sha256'],
        'manifest_version':2,'source_map_size':manifest['size'],'texture_resolution':project['texture_sets'][index]['resolution'],
        'linked_size_projection':'width; full dimensions retained in source and bundle','normal_convention':'OpenGl',
        'height_mode':params.get('height_mode'),'existing_compositing_preserved':True,'texture_set':index,'layer':identity,'replacement':'layer' in params,'channels':list(selected),'new_resources':added,'reused_resources':reused,
        'map_conversions':conversions,'linked_control_projection':projected,'native_float_rounding':rounding,'bounded_source_cook_verified':True,
        'material_native_calls':admitted['native_calls'],'texture_native_calls':process.calls,'original_source_and_bundle_preserved':True,
        'unrequested_native_fields_verified':True,'ambient_recook_authorized':False,'legacy_v1_reader_used':False,'visual_approval':False}
