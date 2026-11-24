"""Managed version-2 portable materials with exact source and bounded cooked maps.

The public adapter owns the format boundary. It never uses the legacy native
portable exporter, which cooks again and rewrites source through a lossy writer.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from . import material_container as container, material_document as document, material_maps as maps, texture_images
from .material_container import require
from .material_graphs import USAGES

PORTABLE = {'float','float2','float3','float4','int','int2','bool','color','enum'}
MAX_MANIFEST = 1 << 20
MAX_SOURCE = 64 << 20


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(data):return hashlib.sha256(data).hexdigest()


def validate(params):
    require(type(params) is dict and {'graph'}<=set(params)<={'graph','outputs'}, 'material bundle requires graph and optional outputs')
    maps.validate({**params,'format':'png','depth':16})


def graph_of(profile,name):
    graphs=profile['model']['packages'][profile['container']['root']]['graphs']
    found=[g for g in graphs if '/'.join(filter(None,(g.get('folder'),g['name'])))==name and g.get('function') is None]
    require(len(found)==1, 'bundle graph is absent or is a standalone function')
    return found[0]


def outputs_of(graph):
    result={}
    for node in graph['nodes']:
        if node['def']!='output':continue
        name=node['params']['identifier']['v'];usage=USAGES[node['params']['usage']['v']]
        require(maps.label(name) and name not in result, 'bundle output identifiers are ambiguous')
        result[name]={'node':node['id'],'usage':usage,'file':f"maps/map-{node['id']}.png"}
    return result


def metadata(graph,name):
    parameters=[{**copy.deepcopy(p),'value':copy.deepcopy(graph.get('inputs',{}).get(p['id'],p['default']))}
                for p in graph['exposed'] if p['default']['t'] in PORTABLE]
    inputs=[]
    for node in graph['nodes']:
        if node['def'] not in ('input_grayscale','input_color'):continue
        identifier=node['params']['identifier']['v'];kind='gray' if node['def']=='input_grayscale' else 'color'
        require(not any(i['identifier']==identifier and i['kind']!=kind for i in inputs), 'bundle input identifier has conflicting image types')
        if not any(i['identifier']==identifier for i in inputs):inputs.append({'identifier':identifier,'kind':kind})
    return {'format':'craft-material','version':2,'name':graph['name'].replace('_',' '),'graph':name,
            'parameters':parameters,'inputs':inputs,'presets':copy.deepcopy(graph.get('presets',[])),'source':'source.mcraft'}


def pack(manifest,members):
    require('material.json' not in members, 'manifest conflicts with package member')
    data=canonical(manifest).encode();require(len(data)<=MAX_MANIFEST, 'bundle manifest exceeds its budget')
    output=io.BytesIO();total=0
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as archive:
        for name,value in {'material.json':data,**members}.items():
            total+=len(value);require(total<=container.MAX_SOURCE, 'bundle expanded bytes exceed budget')
            entry=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));entry.create_system=3;entry.external_attr=0o100600<<16
            container._name(entry);archive.writestr(entry,value)
    result=output.getvalue();require(len(result)<=container.MAX_SOURCE, 'bundle archive exceeds budget');return result


def inspect_bytes(data):
    members,directories,_=container.archive_members(data)
    require(not directories and 'material.json' in members and len(members['material.json'])<=MAX_MANIFEST, 'bundle manifest or directory inventory is invalid')
    manifest=document.snapshot_json(members['material.json'])
    require(type(manifest) is dict and set(manifest)=={'format','version','name','graph','size','maps','parameters','inputs','presets','source'}, 'bundle manifest fields differ')
    require(manifest['format']=='craft-material' and type(manifest['version']) is int and manifest['version']==2, 'bundle format/version is not qualified')
    require(manifest['source']=='source.mcraft' and 'source.mcraft' in members and 0<len(members['source.mcraft'])<=MAX_SOURCE, 'bundle needs bounded exact source.mcraft')
    profile=document.inspect_bytes(members['source.mcraft']);require(profile['container']['format']=='mcraft', 'bundle source must own its embedded resources')
    graph=graph_of(profile,manifest['graph']);expected=metadata(graph,manifest['graph'])
    require(canonical({k:manifest[k] for k in expected})==canonical(expected), 'bundle metadata disagrees with editable source')
    require(type(manifest['size']) is list and len(manifest['size'])==2 and all(type(v) is int and 1<=v<=8192 for v in manifest['size']), 'bundle dimensions are invalid')
    records=manifest['maps'];require(type(records) is list and 1<=len(records)<=48, 'bundle map inventory is empty or oversized')
    outputs=outputs_of(graph);by_file={r['file']:(name,r) for name,r in outputs.items()};seen=set();files=set();texels=0;decoded=[]
    for item in records:
        require(type(item) is dict and set(item)=={'usage','file','colorSpace'} and type(item['file']) is str and item['file'] in by_file, 'bundle map does not name a source output')
        name,output=by_file[item['file']]
        require(item['usage']==output['usage'] and item['usage']!='any' and item['usage'] not in seen and item['file'] not in files, 'bundle usage is absent, ambiguous or duplicated')
        require(item['file'] in members, 'bundle map bytes are absent');seen.add(item['usage']);files.add(item['file'])
        image=members[item['file']];observed=texture_images.inspect_bytes(image)
        require(observed['format']=='PNG' and [observed['width'],observed['height']]==manifest['size'] and image[24]==16 and image[25] in (0,6), 'bundle needs matching PNG16 gray/RGBA maps')
        color='srgb' if image[25]==6 and item['usage'] in maps.SRGB_USAGES else 'linear'
        require(item['colorSpace']==color, 'bundle map transfer disagrees with its admitted profile')
        texels+=observed['width']*observed['height'];require(texels<=maps.LIMITS['texels'], 'bundle decoded texels exceed budget')
        decoded.append({**item,'identifier':name,'node':output['node'],'decoded':observed})
    require(set(members)=={'material.json','source.mcraft',*files}, 'bundle contains unaccounted members')
    return {'manifest':manifest,'members':members,'profile':profile,'maps':decoded,'source_sha256':sha(members['source.mcraft']),
            'sha256':sha(data),'bytes':len(data),'texels':texels,'source_bytes_unchanged':True,'cook_verified':False}


def export(root,path,destination,params,executable,*,seconds=120,cancelled=lambda:False):
    validate(params);root=Path(root).resolve(strict=True);path=document.owned(root,path);destination=document.owned(root,destination)
    require(destination.parent.is_dir() and not destination.exists(), 'bundle requires a new owned output file')
    profile=document.read_native(path);source=profile['container']['source_bytes']
    require(profile['container']['format']=='mcraft' and len(source)<=MAX_SOURCE, 'bundle source must be an owned archive within 64 MiB')
    graph=graph_of(profile,params['graph']);outputs=outputs_of(graph)
    selected=params.get('outputs',[name for name,r in outputs.items() if r['usage']!='any'])
    require(selected and all(name in outputs and outputs[name]['usage']!='any' for name in selected), 'bundle selection needs named material usages')
    require(len({outputs[name]['usage'] for name in selected})==len(selected), 'bundle has duplicate usages; select explicit outputs')
    with tempfile.TemporaryDirectory(prefix='.material-bundle-',dir=root) as temporary:
        target=Path(temporary)/'maps';report=maps.export(root,path,target,{'graph':params['graph'],'outputs':selected,'format':'png','depth':16},executable,seconds=seconds,cancelled=cancelled)
        sizes={(m['width'],m['height']) for m in report['maps']};require(len(sizes)==1, 'portable material maps must have matching dimensions')
        manifest={**metadata(graph,params['graph']),'size':list(next(iter(sizes))),'maps':[]};members={'source.mcraft':source}
        for item in report['maps']:
            name='maps/'+item['file'];members[name]=container.read_bytes(target/item['file'])
            manifest['maps'].append({'usage':item['usage'],'file':name,'colorSpace':'srgb' if item['colorSpace']=='srgb' else 'linear'})
        data=pack(manifest,members);checked=inspect_bytes(data)
        require(checked['members']=={'material.json':canonical(manifest).encode(),**members}, 'bundle changed exact source or map bytes')
        require(container.read_bytes(path)==source and not cancelled(), 'bundle source changed or operation cancelled')
        created=False
        try:
            with destination.open('xb') as stream:
                created=True;stream.write(data);stream.flush();os.fsync(stream.fileno())
        except BaseException:
            if created:destination.unlink(missing_ok=True)
            raise
    return {'schema_version':1,'format':'craft-material','version':2,'file':destination.name,'sha256':sha(data),'bytes':len(data),
            'source_sha256':sha(source),'manifest':manifest,'maps':report,'native_calls':report['native_calls'],
            'exact_editable_source':True,'source_bytes_unchanged':True,'bounded_cook_verified':True,'complete_decoding':True,
            'visual_approval':False,'external_native_reader_qualified':False}


def verify(root,data,executable,*,seconds=120,cancelled=lambda:False):
    """Prove imported maps agree with one fresh bounded cook of the owned source."""
    checked=inspect_bytes(data);root=Path(root).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='.material-bundle-verify-',dir=root) as temporary:
        folder=Path(temporary);path=folder/'source.mcraft';path.write_bytes(checked['members']['source.mcraft'])
        result=maps.export(root,path,folder/'maps',{'graph':checked['manifest']['graph'],'outputs':[m['identifier'] for m in checked['maps']],'format':'png','depth':16},executable,seconds=seconds,cancelled=cancelled)
        for item in result['maps']:
            require(container.read_bytes(folder/'maps'/item['file'])==checked['members']['maps/'+item['file']], 'bundle maps disagree with a fresh bounded source cook')
        require(not cancelled(), 'bundle verification cancelled')
    checked['cook_verified']=True;checked['native_calls']=result['native_calls'];return checked
