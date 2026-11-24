"""Trusted Blender entry point. No user code, external links or downloaded assets."""
import hashlib
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

root = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
request = json.loads((root / 'call.json').read_text())
d = json.loads((root / 'recipe.json').read_text())
mode = request['mode']
scene_file = root / 'native/scene.blend'

def write(path, data): path.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
def rgb(s):
    values = [int(s[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4 for v in values]
def aim(obj, target): obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()
def rounded(values): return [round(float(v), 7) for v in values]
def pixels(path):
    im = bpy.data.images.load(str(path), check_existing=False)
    # Hash decoded channel values, independent of PNG compression/metadata.
    import array
    values = array.array('f', [0]) * (im.size[0] * im.size[1] * 4)
    im.pixels.foreach_get(values)
    result = hashlib.sha256(values.tobytes()).hexdigest()
    bpy.data.images.remove(im)
    return result

def material(m, create=False):
    mat = bpy.data.materials.new(m['id']) if create else bpy.data.materials[m['id']]
    mat.use_nodes = True
    if create:
        mat.node_tree.nodes.clear()
        nodes = mat.node_tree.nodes
        shader = nodes.new('ShaderNodeBsdfPrincipled'); shader.name = 'Surface'
        output = nodes.new('ShaderNodeOutputMaterial'); output.name = 'Output'
        noise = nodes.new('ShaderNodeTexNoise'); noise.name = 'Grain'
        bump = nodes.new('ShaderNodeBump'); bump.name = 'Microtexture'
        mat.node_tree.links.new(shader.outputs['BSDF'], output.inputs['Surface'])
        mat.node_tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
        mat.node_tree.links.new(bump.outputs['Normal'], shader.inputs['Normal'])
    nodes = mat.node_tree.nodes; shader = nodes['Surface']
    for name, value in {'Base Color': (*rgb(m['color']), 1), 'Roughness': m['roughness'], 'Metallic': m['metallic'], 'Transmission Weight': m['transmission'], 'IOR': m['ior'], 'Coat Weight': m.get('coat', 0)}.items():
        shader.inputs[name].default_value = value
    nodes['Grain'].inputs['Scale'].default_value = m.get('bump_scale', 100)
    nodes['Grain'].inputs['Detail'].default_value = 2
    nodes['Microtexture'].inputs['Distance'].default_value = m.get('bump', 0)
    nodes['Microtexture'].inputs['Strength'].default_value = .25
    return mat

def light(row, create=False):
    if create:
        data = bpy.data.lights.new(row['id'], 'AREA'); obj = bpy.data.objects.new(row['id'], data); bpy.context.collection.objects.link(obj)
        obj['production_id'] = row['id']
    else: obj = bpy.data.objects[row['id']]
    obj.location = row['location']; aim(obj, row['target'])
    obj.data.shape = 'RECTANGLE'; obj.data.energy = row['power']; obj.data.color = rgb(row['color'])
    obj.data.size = row['size']; obj.data.size_y = row['size_y']

def object_from(row):
    kind = row['kind']
    if kind == 'box':
        bpy.ops.mesh.primitive_cube_add(size=1); obj = bpy.context.object; obj.scale = row['size']
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    elif kind == 'cylinder':
        bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=row['radius'], depth=row['depth']); obj = bpy.context.object
    elif kind == 'sphere':
        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=row['radius']); obj = bpy.context.object
    elif kind == 'lathe':
        profile = row['profile']; count = 128
        vertices = [(r*math.cos(i*2*math.pi/count), r*math.sin(i*2*math.pi/count), z) for r, z in profile for i in range(count)]
        faces = [(j*count+i, j*count+(i+1)%count, (j+1)*count+(i+1)%count, (j+1)*count+i) for j in range(len(profile)-1) for i in range(count)]
        faces += [tuple(reversed(range(count))), tuple((len(profile)-1)*count+i for i in range(count))]
        mesh = bpy.data.meshes.new(row['id']); mesh.from_pydata(vertices, [], faces); mesh.update()
        obj = bpy.data.objects.new(row['id'], mesh); bpy.context.collection.objects.link(obj)
    else:
        curve = bpy.data.curves.new(row['id'], 'FONT'); curve.body = row['text']; curve.size = row['size']; curve.align_x = 'CENTER'; curve.align_y = 'CENTER'; curve.extrude = row['extrude']
        curve.font = bpy.data.fonts.get('ProductionArchivo') or bpy.data.fonts.load(str(root/'fonts/archivo-variable.ttf'))
        curve.font.name = 'ProductionArchivo'; obj = bpy.data.objects.new(row['id'], curve); bpy.context.collection.objects.link(obj)
    obj.name = row['id']; obj['production_id'] = row['id']
    obj.location = row['location']; obj.rotation_euler = [math.radians(v) for v in row['rotation']]
    obj.data.materials.append(bpy.data.materials[row['material']])
    if kind != 'text':
        if row.get('bevel', 0):
            bevel = obj.modifiers.new('Physical edge radius', 'BEVEL'); bevel.width = row['bevel']; bevel.segments = 6
            bevel = obj.modifiers.new('Surface normals', 'WEIGHTED_NORMAL'); bevel.keep_sharp = True
        for face in obj.data.polygons: face.use_smooth = kind in ('cylinder', 'sphere', 'lathe')
    return obj

def snapshot():
    bpy.context.view_layer.update(); scene = bpy.context.scene
    geometry = {}
    for row in d['objects']:
        obj = bpy.data.objects[row['id']]
        assert obj['production_id'] == row['id']
        entry = {'type': obj.type, 'matrix': [rounded(r) for r in obj.matrix_world], 'materials': [m.name for m in obj.data.materials]}
        if obj.type == 'MESH':
            graph = bpy.context.evaluated_depsgraph_get(); evaluated = obj.evaluated_get(graph); mesh = evaluated.to_mesh()
            shape = {'v': [rounded(v.co) for v in mesh.vertices], 'p': [list(p.vertices) for p in mesh.polygons], 'smooth': [p.use_smooth for p in mesh.polygons]}
            entry['mesh_sha256'] = hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest(); evaluated.to_mesh_clear()
        else:
            entry.update(text=obj.data.body, size=round(obj.data.size, 7), extrude=round(obj.data.extrude, 7), font_packed=bool(obj.data.font.packed_file))
        geometry[row['id']] = entry
    camera = scene.camera
    camera_state = {'matrix': [rounded(r) for r in camera.matrix_world], 'lens': camera.data.lens, 'fstop': camera.data.dof.aperture_fstop, 'focus_distance': round(camera.data.dof.focus_distance, 7)}
    materials = {}
    for row in d['materials']:
        mat = bpy.data.materials[row['id']]; nodes = mat.node_tree.nodes
        materials[row['id']] = {n: rounded(nodes['Surface'].inputs[n].default_value) if n == 'Base Color' else round(nodes['Surface'].inputs[n].default_value, 7) for n in ('Base Color','Roughness','Metallic','Transmission Weight','IOR','Coat Weight')}
        materials[row['id']].update(bump=round(nodes['Microtexture'].inputs['Distance'].default_value,7), bump_scale=round(nodes['Grain'].inputs['Scale'].default_value,7))
    lights = {r['id']: {'matrix':[rounded(v) for v in bpy.data.objects[r['id']].matrix_world], 'energy':bpy.data.lights[r['id']].energy, 'color':rounded(bpy.data.lights[r['id']].color), 'size':bpy.data.lights[r['id']].size, 'size_y':bpy.data.lights[r['id']].size_y} for r in d['lights']}
    return {'geometry':geometry, 'camera':camera_state, 'materials':materials, 'lights':lights, 'objects':sorted(o.name for o in scene.objects), 'render':{'width':scene.render.resolution_x,'height':scene.render.resolution_y,'samples':scene.cycles.samples,'seed':scene.cycles.seed,'device':scene.cycles.device,'view_transform':scene.view_settings.view_transform}}

if mode == 'create':
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    for m in d['materials']: material(m, True)
    for row in d['objects']: object_from(row)
    for row in d['lights']: light(row, True)
    camera = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera')); bpy.context.collection.objects.link(camera)
    camera.location = d['camera']['location']; aim(camera, d['camera']['target']); camera.data.lens = d['camera']['lens']; camera.data.clip_start = .001
    camera.data.dof.use_dof = True; camera.data.dof.focus_distance = math.dist(d['camera']['location'], d['camera']['target']); camera.data.dof.aperture_fstop = d['camera']['fstop']
    scene = bpy.context.scene; scene.camera = camera; scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = d['render']['samples']; scene.cycles.seed = d['render']['seed']
    scene.cycles.use_denoising = True; scene.cycles.use_adaptive_sampling = False; scene.cycles.max_bounces = 12; scene.cycles.transmission_bounces = 8
    scene.render.threads_mode = 'FIXED'; scene.render.threads = 8
    scene.render.resolution_x = d['render']['width']; scene.render.resolution_y = d['render']['height']; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGBA'; scene.render.image_settings.color_depth = '8'
    scene.view_settings.view_transform = 'AgX'; scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (*rgb(d['world']['color']), 1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = d['world']['strength']
    bpy.ops.file.pack_all()
else:
    bpy.ops.wm.open_mainfile(filepath=str(scene_file), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    expected = json.loads((root/'native/readback.json').read_text())
    assert snapshot() == expected, 'Saved native scene differs from retained readback'
    if mode == 'edit':
        before = snapshot()
        prior_document = json.loads(scene['production_recipe'])
        prior_objects = {o['id']:o for o in prior_document['objects']}
        unchanged = [o['id'] for o in d['objects'] if o == prior_objects[o['id']]]
        for m in d['materials']: material(m)
        for row in d['lights']: light(row)
        for row in d['objects']:
            obj = bpy.data.objects[row['id']]
            obj.location = row['location']
            obj.rotation_euler = [math.radians(v) for v in row['rotation']]
            if row['material'] != prior_objects[row['id']]['material']:
                obj.data.materials[0] = bpy.data.materials[row['material']]
            if row['kind'] == 'text':
                obj.data.body = row['text']; obj.data.size = row['size']; obj.data.extrude = row['extrude']
        camera = scene.camera
        camera.location = d['camera']['location']; aim(camera,d['camera']['target'])
        camera.data.lens = d['camera']['lens']; camera.data.dof.aperture_fstop = d['camera']['fstop']
        camera.data.dof.focus_distance = math.dist(d['camera']['location'],d['camera']['target'])
        scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (*rgb(d['world']['color']),1)
        scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = d['world']['strength']
        after = snapshot()
        assert before['objects'] == after['objects'], 'Revision changed native object identity'
        assert all(before['geometry'][key] == after['geometry'][key] for key in unchanged), 'Revision changed an unaffected object'
        assert before['render'] == after['render'], 'Revision changed render quality'
        if prior_document['camera'] == d['camera']:
            assert before['camera'] == after['camera'], 'Revision changed an unaffected camera'
        write(root/'revision-proof.json', {'geometry_preserved':before['geometry']==after['geometry'],
              'camera_preserved':before['camera']==after['camera'], 'native_ids_preserved':True,
              'unchanged_objects_verified':unchanged, 'before':before, 'after':after})

if mode in ('create', 'edit'):
    scene['production_recipe'] = json.dumps(d, sort_keys=True)
    scene.render.filepath = '//../exports/photograph.png'
    scene.render.use_file_extension = True
    bpy.ops.wm.save_as_mainfile(filepath=str(scene_file), check_existing=False)
    write(root/'native/readback.json', snapshot())
assert json.loads(scene['production_recipe']) == d, 'Native recipe differs'
result = {'native_cold_reopen': mode not in ('create','edit'), 'composition_preserved': mode == 'edit' and before['geometry']==after['geometry'] and before['camera']==after['camera'], 'blender_version': bpy.app.version_string}
if mode not in ('inspect','views'):
    destination = root/'exports/photograph.png'
    previous_pixels = pixels(destination) if mode == 'verify' and destination.exists() else None
    scene.render.filepath = str(destination); bpy.ops.render.render(write_still=True)
    result['pixel_sha256'] = pixels(destination)
    if mode == 'verify':
        assert previous_pixels is not None and previous_pixels == result['pixel_sha256'], 'Reopened render pixels differ'
        result['reproduced_pixels'] = True
if mode=='views':
    original=snapshot();native_hash=hashlib.sha256(scene_file.read_bytes()).hexdigest()
    camera=scene.camera;saved_location=camera.location.copy();saved_rotation=camera.rotation_euler.copy()
    target=Vector(d['camera']['target']);delta=saved_location-target
    views=[]
    for index,degrees in enumerate((-15,15),1):
        angle=math.radians(degrees)
        camera.location=target+Vector((delta.x*math.cos(angle)-delta.y*math.sin(angle),delta.x*math.sin(angle)+delta.y*math.cos(angle),delta.z))
        aim(camera,target)
        destination=root/'exports'/('inspection-view-'+str(index)+'.png')
        scene.render.filepath=str(destination);bpy.ops.render.render(write_still=True)
        views.append({'path':destination.name,'azimuth_offset_degrees':degrees,'pixel_sha256':pixels(destination)})
    camera.location=saved_location;camera.rotation_euler=saved_rotation
    assert snapshot()==original,'Inspection changed scene state'
    assert hashlib.sha256(scene_file.read_bytes()).hexdigest()==native_hash,'Inspection changed native file bytes'
    result.update(inspection_views=views,inspection_quality_unchanged=True,native_bytes_preserved=True)
    write(root/'view-inspection.json',result)
write(root/'engine-result.json', result)
print('PASS production', mode)
