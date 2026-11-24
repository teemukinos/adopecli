"""Trusted Blender adapter program; only typed local requests, no evaluated code."""
import bpy
import hashlib
import json
import math
import os
from pathlib import Path
import sys


def rgb(value):
    def linear(v):
        return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
    return tuple(linear(int(value[i:i+2], 16) / 255) for i in (1, 3, 5)) + (1,)


def node(tree, kind, name):
    n = tree.nodes.new(kind); n.name = name; n.label = name
    return n


def material(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    m.node_tree.nodes.clear()
    out = node(m.node_tree, 'ShaderNodeOutputMaterial', 'Surface')
    return m, m.node_tree, out


def key(socket, values):
    for at, value in values:
        socket.default_value = value
        socket.keyframe_insert('default_value', frame=at)


def emission(name, color, values):
    m, t, out = material(name)
    light = node(t, 'ShaderNodeEmission', 'Color')
    light.inputs['Color'].default_value = rgb(color)
    light.inputs['Strength'].default_value = 1
    transparent = node(t, 'ShaderNodeBsdfTransparent', 'Transparent')
    mix = node(t, 'ShaderNodeMixShader', 'Opacity')
    t.links.new(transparent.outputs[0], mix.inputs[1]); t.links.new(light.outputs[0], mix.inputs[2])
    t.links.new(mix.outputs[0], out.inputs['Surface'])
    key(mix.inputs[0], values)
    m['color_srgb'] = color
    return m


def plane(name, z, width=19.2, height=10.8):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-width/2,-height/2,z),(width/2,-height/2,z),(width/2,height/2,z),(-width/2,height/2,z)],[],[(0,1,2,3)])
    mesh.update(); uv=mesh.uv_layers.new(name='UVMap')
    for loop,xy in zip(uv.data,((0,0),(1,0),(1,1),(0,1))):loop.uv=xy
    obj = bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(obj)
    obj['element_id'] = name
    return obj


# Pixel coordinates are top-left for roots and local offsets for children.
def location(o,doc):
    return ((o.get('x',0) if o.get('parent') else o.get('x',doc['width']/2)-doc['width']/2)/100,
            (-o.get('y',0) if o.get('parent') else doc['height']/2-o.get('y',doc['height']/2))/100,o.get('z',0)/100)

def make(o,doc,root):
    kind=o['kind'];name=o['id'];color=o.get('color','#FFFFFF')
    if kind=='group':obj=bpy.data.objects.new(name,None);bpy.context.collection.objects.link(obj)
    elif kind=='text':
        data=bpy.data.curves.new(name,'FONT');data.body=o['text'];data.size=o['size']/100;data.align_x='CENTER';data.align_y='CENTER'
        data.font=bpy.data.fonts.load(str(root/'fonts/archivo-variable.ttf'));data.font.pack()
        obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    elif kind in ('ellipse','path'):
        data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D';data.resolution_u=48;data.bevel_depth=o.get('stroke',2)/200
        spline=data.splines.new('BEZIER');points=o.get('points')
        if kind=='ellipse':points=[[o['width']/2*math.cos(i*math.pi/2),o['height']/2*math.sin(i*math.pi/2)] for i in range(4)]
        spline.bezier_points.add(len(points)-1);spline.use_cyclic_u=kind=='ellipse' or o.get('closed',False)
        for v,p in zip(spline.bezier_points,points):v.co=(p[0]/100,-p[1]/100,0);v.handle_left_type='AUTO';v.handle_right_type='AUTO'
        obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj)
    else:
        width=o.get('width',o.get('radius',100)*3);height=o.get('height',width)
        obj=plane(name,0,width/100,height/100)
    if kind!='group':
        m=emission(name+'-paint',color,[(0,o.get('opacity',1))]);obj.data.materials.append(m);t=m.node_tree
        coord=node(t,'ShaderNodeTexCoord','Coordinates');light=t.nodes['Color'];opacity=t.nodes['Opacity'].inputs[0]
        if kind in ('noise','gradient'):
            ramp=node(t,'ShaderNodeValToRGB','Palette');ramp.color_ramp.elements[0].color=rgb(color);ramp.color_ramp.elements[1].color=rgb(o.get('color2','#20242B'))
            if kind=='noise':
                source=node(t,'ShaderNodeTexNoise','Noise');source.noise_dimensions='4D';source.inputs['Scale'].default_value=o.get('noise_scale',.45);source.inputs['W'].default_value=o.get('seed',1.29);t.links.new(coord.outputs['Object'],source.inputs['Vector'])
                t.links.new(source.outputs['Fac'],ramp.inputs[0])
            else:
                source=node(t,'ShaderNodeSeparateXYZ','Gradient');t.links.new(coord.outputs['Generated'],source.inputs[0]);t.links.new(source.outputs['X'],ramp.inputs[0])
            t.links.new(ramp.outputs[0],light.inputs['Color'])
        elif kind=='glow':
            length=node(t,'ShaderNodeVectorMath','Radius');length.operation='LENGTH';t.links.new(coord.outputs['Object'],length.inputs[0])
            delta=node(t,'ShaderNodeMath','Distance');delta.operation='SUBTRACT';delta.inputs[1].default_value=o['radius']/100;t.links.new(length.outputs['Value'],delta.inputs[0])
            square=node(t,'ShaderNodeMath','Squared');square.operation='MULTIPLY';t.links.new(delta.outputs[0],square.inputs[0]);t.links.new(delta.outputs[0],square.inputs[1])
            fall=node(t,'ShaderNodeMath','Falloff');fall.operation='MULTIPLY';fall.inputs[1].default_value=o.get('falloff',-18);t.links.new(square.outputs[0],fall.inputs[0])
            exp=node(t,'ShaderNodeMath','Halo');exp.operation='EXPONENT';t.links.new(fall.outputs[0],exp.inputs[0])
            gain=node(t,'ShaderNodeMath','Gain');gain.operation='MULTIPLY';gain.inputs[1].default_value=o.get('opacity',.3);t.links.new(exp.outputs[0],gain.inputs[0]);t.links.new(gain.outputs[0],opacity)
        elif kind=='image':
            image=node(t,'ShaderNodeTexImage','Image');image.extension=o.get('image_extension','repeat').upper();image.interpolation='Linear';image.projection='FLAT';image.image=bpy.data.images.load(str(root/'assets'/o['asset']));image.image.pack();t.links.new(coord.outputs['UV'],image.inputs['Vector']);t.links.new(image.outputs['Color'],light.inputs['Color']);gain=node(t,'ShaderNodeMath','Gain');gain.operation='MULTIPLY';gain.inputs[1].default_value=o.get('opacity',1);t.links.new(image.outputs['Alpha'],gain.inputs[0]);t.links.new(gain.outputs[0],opacity)
        if 'mask' in o:
            xyz=node(t,'ShaderNodeSeparateXYZ','Mask coordinates');t.links.new(coord.outputs['Generated'],xyz.inputs[0]);previous=None
            for index,(axis,operation,bound) in enumerate((('X','GREATER_THAN',o['mask'][0]),('Y','GREATER_THAN',o['mask'][1]),('X','LESS_THAN',o['mask'][2]),('Y','LESS_THAN',o['mask'][3]))):
                compare=node(t,'ShaderNodeMath','Mask '+str(index));compare.operation=operation;compare.inputs[1].default_value=bound;t.links.new(xyz.outputs[axis],compare.inputs[0])
                if previous:
                    mul=node(t,'ShaderNodeMath','Mask combine '+str(index));mul.operation='MULTIPLY';t.links.new(previous,mul.inputs[0]);t.links.new(compare.outputs[0],mul.inputs[1]);previous=mul.outputs[0]
                else:previous=compare.outputs[0]
            gain=node(t,'ShaderNodeMath','Masked opacity');gain.operation='MULTIPLY';gain.inputs[1].default_value=o.get('opacity',1)
            if opacity.is_linked:t.links.new(opacity.links[0].from_socket,gain.inputs[1])
            t.links.new(previous,gain.inputs[0]);t.links.new(gain.outputs[0],opacity)
    configure(obj,o,doc)
    return obj

def configure(obj,o,doc):
    obj['element_id']=o['id'];obj['construction']=json.dumps(o,sort_keys=True)
    obj.location=location(o,doc);obj.scale=(o.get('scale',1),)*3;obj.rotation_euler.z=-math.radians(o.get('rotation',0))
    if o['kind']=='text':obj.data.body=o['text']
    if obj.type!='EMPTY':
        m=obj.data.materials[0];m['color_srgb']=o.get('color','#FFFFFF');m.node_tree.nodes['Color'].inputs['Color'].default_value=rgb(o.get('color','#FFFFFF'))
        if o['kind']=='image':m.node_tree.nodes['Image'].extension=o.get('image_extension','repeat').upper()
    for prop,keys in o.get('keys',{}).items():
        for frame,value,interpolation in keys:
            if prop in ('scale','x','y','rotation'):
                target=obj
                if prop=='scale':key_path='scale';key_index=None;obj.scale=(value,)*3;target.keyframe_insert('scale',frame=frame)
                elif prop=='rotation':key_path='rotation_euler';key_index=2;obj.rotation_euler.z=-math.radians(value);target.keyframe_insert('rotation_euler',index=2,frame=frame)
                else:
                    index=0 if prop=='x' else 1;key_path='location';key_index=index;fake={**o,prop:value};obj.location[index]=location(fake,doc)[index];target.keyframe_insert('location',index=index,frame=frame)
            else:
                t=obj.data.materials[0].node_tree
                target=t.nodes['Noise'].inputs['W'] if prop=='seed' else t.nodes['Gain'].inputs[1] if o['kind'] in ('glow','image') else t.nodes['Masked opacity'].inputs[1] if 'mask' in o else t.nodes['Opacity'].inputs[0]
                key_path=target.path_from_id('default_value');key_index=0
                target.default_value=value;target.keyframe_insert('default_value',frame=frame)
                target=t
            action=target.animation_data.action if getattr(target,'animation_data',None) else None
            if action:
                for layer in action.layers:
                    for strip in layer.strips:
                        for slot in action.slots:
                            bag=strip.channelbag(slot)
                            if bag:
                                for curve in bag.fcurves:
                                    for k in curve.keyframe_points:
                                        if curve.data_path==key_path and (key_index is None or curve.array_index==key_index) and k.co.x==frame:k.interpolation=interpolation

def validate_native(doc, root):
    """Check actual native data and evaluated keyframes, not saved metadata alone."""
    scene=bpy.context.scene
    dependencies={}
    assert scene.render.resolution_x==doc['width'] and scene.render.resolution_y==doc['height'] and scene.render.fps==doc['fps'] and scene.frame_end+1==doc['frames'], 'Native canvas/timing differs'
    def close(actual,expected):return abs(actual-expected)<1e-5
    camera=scene.camera
    assert camera is not None and camera.type=='CAMERA' and camera.data.type=='ORTHO', 'Native orthographic camera differs'
    # AUTO sensor fit uses the larger image dimension. Width-only scale crops
    # portrait canvases even when every object and output dimension is correct.
    assert camera.data.sensor_fit=='AUTO' and close(camera.data.ortho_scale,max(doc['width'],doc['height'])/100), 'Native camera canvas coverage differs'
    assert all(close(v,e) for v,e in zip(camera.location,(0,0,20))) and all(close(v,0) for v in camera.rotation_euler) and all(close(v,1) for v in camera.scale) and camera.parent is None, 'Native camera transform differs'
    assert close(camera.data.shift_x,0) and close(camera.data.shift_y,0) and close(scene.render.pixel_aspect_x,1) and close(scene.render.pixel_aspect_y,1), 'Native camera projection differs'
    for o in doc['objects']:
        obj=bpy.data.objects[o['id']];kind=o['kind'];scene.frame_set(0)
        for index,prop in enumerate(('x','y','z')):
            if prop not in o.get('keys',{}):assert close(obj.location[index],location(o,doc)[index]), 'Native position differs'
        if 'scale' not in o.get('keys',{}):assert all(close(v,o.get('scale',1)) for v in obj.scale), 'Native scale differs'
        if 'rotation' not in o.get('keys',{}):assert close(obj.rotation_euler.z,-math.radians(o.get('rotation',0))), 'Native rotation differs'
        assert (obj.parent.name if obj.parent else None)==o.get('parent'), 'Native parent differs'
        if kind=='text':
            assert obj.data.body==o['text'] and close(obj.data.size,o['size']/100) and obj.data.font.packed_file, 'Native text differs'
            expected=hashlib.sha256((root/'fonts/archivo-variable.ttf').read_bytes()).hexdigest()
            actual=hashlib.sha256(obj.data.font.packed_file.data).hexdigest()
            assert actual==expected, 'Native packed font differs from declared font: '+o['id']
            dependencies[o['id']]={'kind':'font','sha256':actual,'declared_sha256':expected}
        if kind in ('rectangle','noise','gradient','image'):
            verts=obj.data.vertices
            assert len(verts)==4 and close(max(v.co.x for v in verts)-min(v.co.x for v in verts),o['width']/100) and close(max(v.co.y for v in verts)-min(v.co.y for v in verts),o['height']/100), 'Native plane differs'
        if kind in ('ellipse','path'):
            expected=o.get('points') or [[o['width']/2*math.cos(i*math.pi/2),o['height']/2*math.sin(i*math.pi/2)] for i in range(4)]
            points=obj.data.splines[0].bezier_points
            assert len(points)==len(expected) and all(close(p.co.x,v[0]/100) and close(p.co.y,-v[1]/100) for p,v in zip(points,expected)), 'Native curve differs'
            assert close(obj.data.bevel_depth,o.get('stroke',2)/200) and obj.data.splines[0].use_cyclic_u==(kind=='ellipse' or o.get('closed',False)), 'Native stroke/closure differs'
        if kind!='group':
            tree=obj.data.materials[0].node_tree
            assert all(close(a,b) for a,b in zip(tree.nodes['Color'].inputs['Color'].default_value,rgb(o.get('color','#FFFFFF')))), 'Native paint differs'
            if kind in ('noise','gradient'):
                ramp=tree.nodes['Palette'].color_ramp
                for entry,color in zip(ramp.elements,(o.get('color','#FFFFFF'),o.get('color2','#20242B'))):assert all(close(a,b) for a,b in zip(entry.color,rgb(color))), 'Native gradient differs'
            if kind=='glow':assert close(tree.nodes['Distance'].inputs[1].default_value,o['radius']/100) and close(tree.nodes['Falloff'].inputs[1].default_value,o.get('falloff',-18)), 'Native glow differs'
            if 'mask' in o:
                for i,value in enumerate(o['mask']):assert close(tree.nodes['Mask '+str(i)].inputs[1].default_value,value), 'Native mask differs'
            if 'opacity' not in o.get('keys',{}):
                socket=(tree.nodes['Gain'].inputs[1] if kind in ('glow','image') else tree.nodes['Masked opacity'].inputs[1] if 'mask' in o else tree.nodes['Opacity'].inputs[0])
                expected=o.get('opacity',.3 if kind=='glow' else 1)
                assert close(socket.default_value,expected), 'Native static opacity differs: '+o['id']
                # Static construction opacity must remain constant at every
                # frame, not merely agree at frame zero. Ordinary materials
                # have one implicit initial key; gain sockets may have none.
                animation=tree.animation_data
                if animation:
                    path=socket.path_from_id('default_value')
                    assert not animation.nla_tracks and not any(c.data_path==path for c in animation.drivers), 'Native static opacity has unsupported animation: '+o['id']
                    action=animation.action
                    if action:
                        for layer in action.layers:
                            for strip in layer.strips:
                                for slot in action.slots:
                                    bag=strip.channelbag(slot)
                                    if bag:
                                        for curve in bag.fcurves:
                                            if curve.data_path==path:
                                                assert not curve.modifiers and all(close(k.co.y,expected) and close(k.handle_left.y,expected) and close(k.handle_right.y,expected) for k in curve.keyframe_points), 'Native static opacity animation differs: '+o['id']
            if kind=='image':
                image_node=tree.nodes['Image']
                assert image_node.extension==o.get('image_extension','repeat').upper(), 'Native image extension differs: '+o['id']
                assert image_node.interpolation=='Linear' and image_node.projection=='FLAT', 'Native image sampling differs: '+o['id']
                links=image_node.inputs['Vector'].links
                assert len(links)==1 and links[0].from_node==tree.nodes['Coordinates'] and links[0].from_socket.name=='UV', 'Native image coordinates differ: '+o['id']
                uv=obj.data.uv_layers.active
                expected_uv=((0,0),(1,0),(1,1),(0,1))
                assert uv is not None and len(uv.data)==4 and all(close(p.uv.x,x) and close(p.uv.y,y) for p,(x,y) in zip(uv.data,expected_uv)), 'Native image UV mapping differs: '+o['id']
                packed=image_node.image.packed_file
                assert packed, 'Native image is not embedded'
                expected=hashlib.sha256((root/'assets'/o['asset']).read_bytes()).hexdigest()
                actual=hashlib.sha256(packed.data).hexdigest()
                assert actual==expected, 'Native packed image differs from declared asset: '+o['id']
                dependencies[o['id']]={'kind':'image','asset':o['asset'],'sha256':actual,'declared_sha256':expected}
        for prop,keys in o.get('keys',{}).items():
            for frame,expected,interpolation in keys:
                scene.frame_set(frame)
                if prop=='x':actual=obj.location.x*100+(0 if o.get('parent') else doc['width']/2)
                elif prop=='y':actual=-obj.location.y*100+(0 if o.get('parent') else doc['height']/2)
                elif prop=='rotation':actual=-math.degrees(obj.rotation_euler.z)
                elif prop=='scale':actual=obj.scale.x
                elif prop=='seed':actual=tree.nodes['Noise'].inputs['W'].default_value
                else:actual=(tree.nodes['Gain'].inputs[1] if kind in ('glow','image') else tree.nodes['Masked opacity'].inputs[1] if 'mask' in o else tree.nodes['Opacity'].inputs[0]).default_value
                assert abs(actual-expected)<.001, 'Native key differs: '+o['id']+'/'+prop
    scene.frame_set(doc.get('preview_frame',0))
    return dependencies


def inventory(doc):
    s=bpy.context.scene;s.frame_set(doc.get('preview_frame',0));bpy.context.view_layer.update();out={}
    for obj in s.objects:
        if not obj.get('construction'):continue
        row={'construction':json.loads(obj['construction']),'native_type':obj.type,'location':list(obj.location),'scale':list(obj.scale),'dimensions':list(obj.dimensions),'parent':obj.parent.name if obj.parent else None}
        if obj.type=='FONT':row.update(text=obj.data.body,font_packed=obj.data.font.packed_file is not None)
        if obj.type=='CURVE':row['curves']=[{'points':[list(p.co) for p in c.bezier_points],'closed':c.use_cyclic_u} for c in obj.data.splines]
        if obj.type!='EMPTY':row['color']=list(obj.data.materials[0].node_tree.nodes['Color'].inputs['Color'].default_value)
        out[obj['element_id']]=row
    actions={}
    for a in bpy.data.actions:
        curves=[]
        for l in a.layers:
            for st in l.strips:
                for sl in a.slots:
                    bag=st.channelbag(sl)
                    if bag:
                        for c in bag.fcurves:curves.append([c.data_path,c.array_index,[[float(k.co.x),float(k.co.y),k.interpolation] for k in c.keyframe_points]])
        if a.users:actions[a.name]=curves
    camera=s.camera
    return {'pid':os.getpid(),'frames':s.frame_end+1,'ids':sorted(out),'objects':out,'actions':actions,
            'camera':{'type':camera.data.type,'sensor_fit':camera.data.sensor_fit,'ortho_scale':camera.data.ortho_scale,
                      'location':list(camera.location),'rotation':list(camera.rotation_euler),'scale':list(camera.scale),
                      'shift':[camera.data.shift_x,camera.data.shift_y],
                      'pixel_aspect':[s.render.pixel_aspect_x,s.render.pixel_aspect_y]}}

def main():
    req=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text());root=Path(req['root']);doc=json.loads((root/'document.json').read_text());mode=req['mode'];s=bpy.context.scene
    if mode=='create':
        bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
        s.render.engine='CYCLES';s.cycles.device='CPU';s.cycles.samples=doc.get('samples',32);s.cycles.use_denoising=False;s.cycles.seed=129
        s.view_settings.view_transform='Standard';s.view_settings.look='None';s.render.film_transparent=True
        camera=bpy.data.cameras.new('$construction-camera');camera.type='ORTHO';camera.sensor_fit='AUTO';camera.ortho_scale=max(doc['width'],doc['height'])/100
        ob=bpy.data.objects.new('$construction-camera',camera);bpy.context.collection.objects.link(ob);ob.location=(0,0,20);s.camera=ob
        for o in doc['objects']:make(o,doc,root)
    else:
        bpy.ops.wm.open_mainfile(filepath=str(root/'native/scene.blend'),load_ui=False,use_scripts=False);s=bpy.context.scene
    if mode=='edit':
        old=req['previous'];canvas_changed=(old['width'],old['height'])!=(doc['width'],doc['height']);before=inventory(old);oldmap={o['id']:o for o in old['objects']};newmap={o['id']:o for o in doc['objects']}
        for name in oldmap.keys()-newmap.keys():bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
        for name,o in newmap.items():
            prev=oldmap.get(name)
            if prev==o:
                if canvas_changed and not o.get('parent'):configure(bpy.data.objects[name],o,doc)
                continue
            if prev is not None and set(k for k in set(prev)|set(o) if prev.get(k)!=o.get(k))<={'text','color','image_extension'}:configure(bpy.data.objects[name],o,doc)
            else:
                if name in bpy.data.objects:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
                make(o,doc,root)
        for o in doc['objects']:
            bpy.data.objects[o['id']].parent=bpy.data.objects[o['parent']] if o.get('parent') else None
        for o in doc['objects']:
            if o['kind']=='image':
                node=bpy.data.objects[o['id']].data.materials[0].node_tree.nodes['Image']
                node.image=bpy.data.images.load(str(root/'assets'/o['asset']));node.image.pack()
        after=inventory({**doc,'preview_frame':old.get('preview_frame',0)})
        for name in oldmap.keys()&newmap.keys():
            if oldmap[name]==newmap[name] and not oldmap[name].get('parent') and not canvas_changed:
                assert before['objects'][name]==after['objects'][name], 'Unchanged native element differs: '+name
        (root/'native/revision-proof.json').write_text(json.dumps({'before':before,'after':after,'unchanged_objects_verified':True,'dependent_canvas_adjustment':canvas_changed},indent=2))
    if mode in ('create','edit'):
        for o in doc['objects']:
            if o.get('parent'):bpy.data.objects[o['id']].parent=bpy.data.objects[o['parent']]
        s.camera.data.sensor_fit='AUTO';s.camera.data.ortho_scale=max(doc['width'],doc['height'])/100;s.cycles.samples=doc.get('samples',32)
        s.frame_start=0;s.frame_end=doc['frames']-1;s.render.fps=doc['fps'];s.render.fps_base=1
        s.render.resolution_x=doc['width'];s.render.resolution_y=doc['height'];s.render.resolution_percentage=100
        s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGBA';s.render.image_settings.color_depth='8'
        s.frame_set(doc.get('preview_frame',0));bpy.ops.wm.save_as_mainfile(filepath=str(root/'native/scene.blend'))
    dependencies=validate_native(doc,root)
    checked=inventory(doc);checked['native_geometry_and_keys_verified']=True
    checked['native_dependency_bytes_verified']=True
    checked['native_static_opacity_verified']=True
    checked['native_image_sampling_verified']=True
    checked['native_dependency_bindings']=dependencies
    (root/'native/inspection.json').write_text(json.dumps(checked,indent=2))
    if mode=='inspect' or req['output']['format']=='native':return
    output=req['output'];final=mode=='render'
    if final and output['format']=='mp4':
        directory=root/'frames';directory.mkdir(exist_ok=True)
        for frame in range(doc['frames']):
            s.frame_set(frame);s.render.filepath=str(directory/f'{frame:06d}.png');bpy.ops.render.render(write_still=True)
    else:
        s.frame_set(output.get('frame',doc.get('preview_frame',0)))
        if not final:s.render.resolution_percentage=min(100,max(1,round(960/doc['width']*100)))
        s.render.filepath=str(root/'exports'/('still.png' if final else 'preview.png'));bpy.ops.render.render(write_still=True)

if __name__=='__main__':main()
