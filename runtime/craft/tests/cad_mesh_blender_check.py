"""Independent Blender OBJ import, solid measurements and headless visual proof.

Run Blender with --background --factory-startup --python this_file -- --input OBJ
--output FRESH_DIRECTORY. The native Dobe CAD engine authors the OBJ; Blender
only reads, measures and presents the delivered geometry.
"""
import argparse
import json
from pathlib import Path
import sys
import bpy
import bmesh
from mathutils import Vector

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.output.resolve();out.mkdir(parents=True)
try:
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    bpy.ops.wm.obj_import(filepath=str(args.input.resolve()),forward_axis='Y',up_axis='Z')
    meshes=[obj for obj in bpy.context.scene.objects if obj.type=='MESH']
    assert len(meshes)==1,'OBJ must create one mesh'
    panel=meshes[0];bpy.context.view_layer.update()
    points=[panel.matrix_world@v.co for v in panel.data.vertices]
    dimensions=[max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)]
    assert all(abs(a-b)<1e-6 for a,b in zip(dimensions,(150,90,20))),dimensions
    mesh=bmesh.new();mesh.from_mesh(panel.data)
    assert len(mesh.verts)==8 and len(mesh.edges)==12 and len(mesh.faces)==6,'Imported topology differs'
    assert all(edge.is_manifold for edge in mesh.edges),'Imported mesh is not closed manifold'
    volume=mesh.calc_volume(signed=True);area=sum(face.calc_area() for face in mesh.faces)
    assert abs(volume-270000)<1e-6 and abs(area-36600)<1e-6,(volume,area)
    assert all(face.normal.dot(face.calc_center_median()-Vector((75,45,10)))>0 for face in mesh.faces),'Imported normals point inward'
    mesh.free()
    scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=.001
    material=bpy.data.materials.new('CAD inspection blue');material.diffuse_color=(.12,.4,.62,1);panel.data.materials.append(material)
    camera_data=bpy.data.cameras.new('Inspection camera');camera=bpy.data.objects.new('Inspection camera',camera_data);scene.collection.objects.link(camera)
    camera.location=(255,-235,215);target=Vector((75,45,10));camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type='ORTHO';camera_data.ortho_scale=240;camera_data.clip_end=2000;scene.camera=camera
    scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=960;scene.render.resolution_y=720;scene.render.resolution_percentage=100
    scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL';scene.display.shading.show_shadows=True
    scene.display.shading.show_cavity=True;scene.display.shading.cavity_type='BOTH';scene.display.shading.show_object_outline=True
    scene.display.shading.background_type='WORLD';scene.world.color=(.04,.04,.05)
    scene.render.image_settings.file_format='PNG';scene.render.filepath=str(out/'revised-panel.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'revised-panel.blend'));bpy.ops.render.render(write_still=True)
    evidence={'passed':True,'reader':'Blender '+bpy.app.version_string,'dimensions_mm':dimensions,'vertices':8,'edges':12,'faces':6,
              'volume_mm3':volume,'surface_area_mm2':area,'closed_manifold':True,'outward_normals':True,
              'renderer':'headless workbench inspection','source_modified':False,'manufacturing_qualified':False,'installed_dobe_qualified':False}
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print('PASS independent Blender OBJ geometry and headless inspection render')
except Exception as error:
    (out/'failure.json').write_text(json.dumps({'error':str(error)},indent=2)+'\n');raise
