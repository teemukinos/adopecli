#!/usr/bin/env python3
"""Local checks for Texture JSON, graph, allocation and binary pixel preflight."""
import argparse
import copy
import json
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import texture_archive, texture_pixels as pixels, texture_structure as structure


def layer(lid, kind='Paint'):
    return {'id': lid, 'name': str(lid), 'visible': True, 'kind': kind, 'channels': {'BaseColor': {'mode': 'Normal', 'opacity': 1}}}


def project():
    return {'format_version': 2, 'name': 'Structural fixture', 'mesh': 'builtin:plane', 'normal_format': 'OpenGl',
            'texture_sets': [{'name': 'Plane', 'material': 0, 'resolution': 128, 'channels': [['BaseColor','Srgb8']], 'stack':[1]}],
            'layers': {'1': layer(1)}, 'next_id': 2, 'display': {'environment': 'Studio Soft'}, 'cameras': []}


def paint(width=128, height=128, components=4, positions=((0, 0),)):
    return (b'TCTX' + struct.pack('<5I', 1, width, height, components, len(positions))
            + b''.join(struct.pack('<2I', *position) + b'\x80\x80' * (4096 * components) for position in positions))


def baked(width=2, height=2, components=1, bits=0x3f000000):
    return b'TCTX' + struct.pack('<5I', 1, width, height, components, 0) + struct.pack('<I', bits) * (width * height * components)


def change(data, offset, value):
    value_bytes = bytearray(data); struct.pack_into('<I', value_bytes, offset, value); return bytes(value_bytes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, action='append', default=[])
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args(); checks = []; started = time.monotonic()
    def check(label, valid):
        assert valid, label
        checks.append(label)
    def inspect(value):
        return structure.inspect_json(json.dumps(value).encode())
    def refused(label, action):
        try: action()
        except ValueError: checks.append(label)
        else: raise AssertionError('unexpected admission: ' + label)
    def mutate(label, edit):
        p = project(); edit(p); refused(label, lambda: inspect(p))
    result = inspect(project())
    check('single layer budgets include alpha coverage', result['budgets'] == {'atlas_texels':16384, 'component_texels':65536, 'render_work':65536})
    for label, data in [
        ('duplicate JSON keys', b'{"a":1,"a":2}'), ('nonfinite JSON', b'{"x":NaN}'),
        ('overflowed JSON float', b'{"x":1e400}'), ('invalid UTF8', b'"\xff"'),
        ('surrogate JSON', b'"\\ud800"'), ('oversized integer', b'{"x":18446744073709551616}'),
        ('deep JSON', b'[' * 65 + b'0' + b']' * 65), ('many JSON items', b'[' + b'0,' * 100001 + b'0]'),
        ('JSON bytes budget', b' ' * (texture_archive.MAX_JSON + 1)), ('JSON root must be object', b'[]'),
    ]: refused(label, lambda data=data: structure.inspect_json(data))
    for value in (True, 0, 1, 3, '2'):
        mutate('unsupported version ' + repr(value), lambda p,value=value:p.update(format_version=value))
    for key in ('01', '-1', '0', '１', '18446744073709551616'):
        mutate('noncanonical layer key ' + key, lambda p,key=key:p.update(layers={key:layer(1)}))
    mutate('layer ID disagrees with key', lambda p:p['layers']['1'].update(id=2))
    mutate('boolean layer ID', lambda p:p['layers']['1'].update(id=True))
    for value in (0, 1, True, structure.MAX_ID):
        mutate('invalid next ID ' + repr(value), lambda p,value=value:p.update(next_id=value))
    mutate('missing layer', lambda p:p['texture_sets'][0].update(stack=[2]))
    mutate('duplicated root', lambda p:p['texture_sets'][0].update(stack=[1,1]))
    mutate('orphan layer', lambda p:p['texture_sets'][0].update(stack=[]))
    mutate('self group cycle', lambda p:p['layers']['1'].update(kind={'Group':{'children':[1], 'collapsed':False}}))
    mutate('self instance cycle', lambda p:p['layers']['1'].update(kind={'Instance':{'source':1}}))
    mutate('missing instance source', lambda p:p['layers']['1'].update(kind={'Instance':{'source':2}}))
    mutate('unknown layer variant', lambda p:p['layers']['1'].update(kind={'Future':{}}))
    mutate('ambiguous layer variant', lambda p:p['layers']['1'].update(kind={'Group':{},'Instance':{}}))
    for count, allowed in ((17,True),(18,False)):
        p=project(); p['layers']={str(i):layer(i, 'Paint' if i==1 else {'Instance':{'source':i-1}}) for i in range(1,count+1)}
        p['texture_sets'][0]['stack']=list(range(1,count+1));p['next_id']=count+1
        if allowed: check('cached instance graph exact depth limit', inspect(p)['atlases'][0]['expanded_nodes']==count*(count+1)//2)
        else: refused('cached instance graph cannot hide depth',lambda p=p:inspect(p))
    p=project();p['layers']['1']['kind']={'Group':{'children':[2], 'collapsed':False}};p['layers']['2']=layer(2,{'Instance':{'source':1}});p['next_id']=3
    refused('mixed group and instance cycle',lambda:inspect(p))
    p=project();last=1;next_id=2
    for level in range(5):
        child_ids=list(range(next_id,next_id+10)); group_id=next_id+10
        for lid in child_ids:p['layers'][str(lid)]=layer(lid,{'Instance':{'source':last}})
        p['layers'][str(group_id)]=layer(group_id,{'Group':{'children':child_ids,'collapsed':False}})
        p['texture_sets'][0]['stack'].append(group_id);last=group_id;next_id=group_id+1
    p['next_id']=next_id
    refused('compact DAG cannot cause unbounded instance expansion',lambda:inspect(p))
    p=project();p['layers']['2']=layer(2,{'Instance':{'source':1}});p['next_id']=3
    second=copy.deepcopy(p['texture_sets'][0]);second.update(name='Second',material=1,resolution=256,stack=[2]);p['texture_sets'].append(second)
    result=inspect(p)
    check('cross-set instance uses target atlas and retains distinct ownership',result['ids'][1]['texture_set']==0 and result['ids'][2]['texture_set']==1 and result['atlases'][1]['expanded_nodes']==2 and result['budgets']['render_work']==128*128*4+256*256*4*2)
    p=project();p['texture_sets']*=2
    refused('cross-set ownership duplicate',lambda:inspect(p))
    for value in (0,127,129,16384,True):
        mutate('invalid resolution '+repr(value),lambda p,value=value:p['texture_sets'][0].update(resolution=value))
    for tiles in ([1000],[2001],[1002,1001],[1001,1001],[True]):
        mutate('invalid UDIM set '+repr(tiles),lambda p,tiles=tiles:p['texture_sets'][0].update(uv_tiles=tiles))
    mutate('UDIM holes count toward atlas side',lambda p:p['texture_sets'][0].update(uv_tiles=[1001,2000]))
    p=project();p['texture_sets'][0]['uv_tiles']=[1001,1023]
    check('UDIM holes count toward exact atlas area',inspect(p)['budgets']['atlas_texels']==384*384)
    p=project();p['texture_sets'][0].update(uv_tiles=[1001,1002],tile_resolutions={'1001':1024,'1002':512})
    check('largest tile defines every atlas block',inspect(p)['atlases'][0]['width']==2048 and inspect(p)['atlases'][0]['height']==1024)
    p['texture_sets'][0].update(resolution=8192,tile_resolutions={'1001':128,'1002':128})
    check('all overrides replace unused base block size',inspect(p)['atlases'][0]['width']==256)
    mutate('override absent tile',lambda p:p['texture_sets'][0].update(tile_resolutions={'1001':128}))
    mutate('exclude absent tile',lambda p:p['texture_sets'][0].update(bake_excluded_tiles=[1001]))
    mutate('unknown channel',lambda p:p['texture_sets'][0].update(channels=[['Unknown','L8']]))
    mutate('channel wrong type',lambda p:p['texture_sets'][0].update(channels=[[{},'L8']]))
    mutate('unknown channel format',lambda p:p['texture_sets'][0].update(channels=[['BaseColor','Unknown']]))
    mutate('duplicate channel',lambda p:p['texture_sets'][0].update(channels=[['BaseColor','L8']]*2))
    mutate('no channels',lambda p:p['texture_sets'][0].update(channels=[]))
    mutate('unknown baked map',lambda p:p['texture_sets'][0].update(baked=['Unknown']))
    mutate('duplicate baked map',lambda p:p['texture_sets'][0].update(baked=['Height','Height']))
    mutate('atlas total limit',lambda p:p['texture_sets'][0].update(resolution=8192))
    p=project();p['texture_sets'][0].update(resolution=4096,channels=[[name,'Rgb32F'] for name in structure.CHANNELS])
    refused('component allocation limit',lambda:inspect(p))
    p=project();p['layers']={str(i):layer(i) for i in range(1,18)};p['texture_sets'][0].update(resolution=4096,stack=list(range(1,18)));p['next_id']=18
    refused('expanded compositing work limit',lambda:inspect(p))
    effect={'id':2,'name':'Anchor','visible':True,'kind':'Anchor','blend':'Normal','opacity':1}
    p=project();p['layers']['1']['content_effects']=[effect];p['next_id']=3
    check('effect IDs share ownership space',inspect(p)['ids'][2]=={'layer':1,'role':'content','texture_set':0})
    p['layers']['1']['content_effects'].append(copy.deepcopy(effect))
    refused('duplicated effect ID',lambda:inspect(p))
    p=project();p['layers']['1']['content_effects']=[{**effect,'id':1}]
    refused('effect collides with layer ID',lambda:inspect(p))
    p=project();p['layers']['1']['kind']={'Fill':{'sources':{'BaseColor':{'Anchor':{'anchor':2,'channel':'BaseColor'}}},'projection':{'Uv':{'scale':[1,1],'rotation':0,'offset':[0,0]}}}}
    refused('missing anchor',lambda:inspect(p))
    p['layers']['1']['content_effects']=[effect];p['next_id']=3
    check('existing anchor reference retained',inspect(p)['project']==p)
    p=project();p['layers']['1']['kind']={'Fill':{'sources':{'BaseColor':{'Image':{'name':'palette.png'}}}}};p['display']['environment']='resource:sky.hdr'
    check('image and environment dependencies recorded',inspect(p)['resource_references']==['palette.png','sky.hdr'])
    p['layers']['1']['kind']['Fill']['sources']['BaseColor']['Image']['name']='../palette.png'
    refused('external image reference',lambda:inspect(p))
    p=project();p['future_metadata']={'keep':[1,2,3]}
    check('uninterpreted fields retained for later native preservation gate',inspect(p)['project']==p)

    s=inspect(project()); valid=paint(); name='pixels/layer_1_baseColor.bin'
    check('paint tile admitted without changing bytes',pixels.inspect_members({name:valid},s)['allocated_tiles']==1 and pixels.sparse(valid,128,128,4)['components']==4)
    check('empty sparse image admitted',pixels.sparse(paint(positions=()),128,128,4)['allocated_tiles']==0)
    for label, value in [('wrong magic',b'BAD!'+valid[4:]),('old binary version',change(valid,4,0)),('future binary version',change(valid,4,2)),
        ('paint wrong width',change(valid,8,256)),('paint wrong height',change(valid,12,256)),('paint wrong components',change(valid,16,2)),
        ('paint impossible tile count',change(valid,20,5)),('paint truncated',valid[:-1]),('paint trailing data',valid+b'x'),
        ('paint duplicate tile',paint(positions=((0,0),(0,0)))),('paint outside tile',paint(positions=((2,0),)))]:
        refused(label,lambda value=value:pixels.inspect_members({name:value},s))
    for bad_name in ('pixels/layer_2_baseColor.bin','pixels/layer_01_baseColor.bin','pixels/layer_1_unknown.bin','pixels/mask_0.bin','pixels/bogus.bin'):
        refused('invalid paint ownership/name '+bad_name,lambda bad_name=bad_name:pixels.inspect_members({bad_name:valid},s))
    p=project();p['layers']['1']['mask']={'enabled':True,'background':'White','effects':[{**effect,'kind':'Paint'}]};p['next_id']=3
    check('mask effect resolves to layer atlas',pixels.inspect_members({'pixels/mask_2.bin':paint(components=2)},inspect(p))['allocated_tiles']==1)
    for bits in (0,0x80000000,1,0x3f800000,0xbf800000,0x7f7fffff):
        check('finite f32 bits preserved '+hex(bits),pixels.dense(baked(bits=bits),1)['width']==2)
    for bits in (0x7f800000,0xff800000,0x7fc00000,0x7f800001):
        refused('nonfinite f32 '+hex(bits),lambda bits=bits:pixels.dense(baked(bits=bits),1))
    dense=baked(); bake_name='baked/0_ambientOcclusion.bin'
    check('dense baked map admitted',pixels.inspect_members({bake_name:dense},s)['members'][bake_name]['bytes']==40)
    for label,value in [('zero bake width',change(dense,8,0)),('huge bake width',change(dense,8,0xffffffff)),('wrong bake components',change(dense,16,3)),
                         ('reserved bake count',change(dense,20,1)),('truncated bake',dense[:-1]),('bake trailing bytes',dense+b'x')]:
        refused(label,lambda value=value:pixels.inspect_members({bake_name:value},s))
    for bad_name in ('baked/1_ambientOcclusion.bin','baked/00_ambientOcclusion.bin','baked/0_ao.bin','bake_paint/0_other.bin'):
        refused('invalid bake ownership/name '+bad_name,lambda bad_name=bad_name:pixels.inspect_members({bad_name:dense},s))
    refused('one set has mismatched baked sizes',lambda:pixels.inspect_members({bake_name:dense,'baked/0_height.bin':baked(width=3)},s))
    check('bake paint has independent dimensions',pixels.inspect_members({bake_name:dense,'bake_paint/0_cage.bin':baked(width=3)},s)['members']['bake_paint/0_cage.bin']['width']==3)
    previous=pixels.MAX_PIXEL_BYTES
    try:
        pixels.MAX_PIXEL_BYTES=len(valid)
        refused('aggregate pixel bytes limit',lambda:pixels.inspect_members({name:valid,'pixels/layer_1_normal.bin':valid},s))
    finally:pixels.MAX_PIXEL_BYTES=previous
    native_files=[]
    for path in args.native:
        before=path.read_bytes();a=texture_archive.read_native(path);s=structure.inspect_json(a['members']['project.json']);p=pixels.inspect_members(a['members'],s)
        check('real archive structure and pixels: '+path.name,path.read_bytes()==before and json.loads(a['members']['project.json'])==s['project'])
        native_files.append({'path':str(path),'sha256':a['source_sha256'],'budgets':s['budgets'],'pixels':p})
    report={'passed':True,'checks':len(checks),'cases':checks,'native_archives':native_files,'seconds':round(time.monotonic()-started,4),
            'scope':'JSON/graph/allocation and binary pixel preflight only','engine_execution_authorized':False,'goal_complete':False}
    if args.evidence:args.evidence.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('passed','checks','seconds','scope')}))


if __name__=='__main__':main()
