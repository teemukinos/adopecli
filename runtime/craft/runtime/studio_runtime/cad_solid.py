"""Native panel-solid predictions and independent geometry/OBJ verification.

A closed polyface panel is a bounded editable solid representation. It is not
an ACIS/B-rep, general CSG, certified manufacturing model or full CAD admission.
"""
from collections import Counter
import copy
import math
import re

from . import cad_source as source, cad_revision as revision, cad_parametric as panel
from .cad_source import require

RECIPE = 'rectangular_panel_solid'
VERSION = 1
FACES = [[1,4,3,2],[5,6,7,8],[1,2,6,5],[2,3,7,6],[3,4,8,7],[4,1,5,8]]


def vertices(width, height, depth):
    return [{'x':float(x),'y':float(y),'z':float(z)} for x,y,z in
            ((0,0,0),(width,0,0),(width,height,0),(0,height,0),(0,0,depth),(width,0,depth),(width,height,depth),(0,height,depth))]


def numeric(value):
    require(type(value) in (int,float) and math.isfinite(value), 'mesh coordinates must be finite')
    return float(value)


def subtract(a,b): return tuple(x-y for x,y in zip(a,b))
def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def dot(a,b): return math.fsum(x*y for x,y in zip(a,b))


def inspect_mesh(mesh, *, width, height, depth):
    """Measure actual geometry, oriented edges, volume and face planes.

    This algorithm does not trust native dimension reports or the construction
    face order. Each of the six outward rectangular boundary planes occurs once.
    """
    dimensions = [panel.dimension(v) for v in (width,height,depth)]
    require(type(mesh) is dict and set(mesh)=={'type','vertices','faces'} and mesh['type']=='polyfaceMesh', 'solid needs a native polyface mesh')
    raw = source.sequence(mesh['vertices'],'panel vertices',8); faces = source.sequence(mesh['faces'],'panel faces',6)
    require(len(raw)==8 and len(faces)==6, 'panel needs eight vertices and six faces')
    points=[]
    for value in raw:
        require(type(value) is dict and set(value)=={'x','y','z'}, 'mesh point fields differ')
        points.append(tuple(numeric(value[key]) for key in ('x','y','z')))
    require(len(set(points))==8, 'panel vertices overlap')
    bounds=[(min(p[i] for p in points),max(p[i] for p in points)) for i in range(3)]
    require(all(low==0.0 and high==size for (low,high),size in zip(bounds,dimensions)), 'mesh bounds differ from requested dimensions')
    require(all(all(p[i] in (0.0,dimensions[i]) for i in range(3)) for p in points), 'mesh vertex is not a panel corner')
    edges=Counter();planes=set();volumes=[];areas=[]
    center=tuple(size/2 for size in dimensions)
    for face in faces:
        require(type(face) is list and len(face)==4 and all(type(i) is int and 1<=i<=8 for i in face) and len(set(face))==4,
                'mesh face indices must name four distinct owned vertices')
        selected=[points[i-1] for i in face]
        flat=[i for i in range(3) if len({p[i] for p in selected})==1]
        require(len(flat)==1, 'panel face must occupy one boundary plane')
        plane=(flat[0],selected[0][flat[0]])
        require(plane not in planes, 'panel has duplicate boundary faces');planes.add(plane)
        a,b,c,d=selected
        normal=cross(subtract(b,a),subtract(c,a))
        require(dot(normal,subtract(a,center))>0, 'panel face is degenerate or inward')
        require(dot(normal,cross(subtract(c,a),subtract(d,a)))>0, 'panel face is folded or self-crossing')
        for start,end in zip(face,face[1:]+face[:1]):edges[(start,end)]+=1
        for triangle in ((a,b,c),(a,c,d)):
            x,y,z=triangle;volumes.append(dot(x,cross(y,z))/6)
            n=cross(subtract(y,x),subtract(z,x));areas.append(math.sqrt(dot(n,n))/2)
    require(len(edges)==24 and all(count==1 and edges[(b,a)]==1 for (a,b),count in edges.items()), 'mesh is open, duplicated or inconsistently oriented')
    edge_count=len(edges)//2;require(len(points)-edge_count+len(faces)==2, 'panel Euler characteristic differs')
    volume=math.fsum(volumes);area=math.fsum(areas);w,h,d=dimensions
    expected_volume=w*h*d;expected_area=2*(w*h+w*d+h*d)
    require(math.isclose(volume,expected_volume,rel_tol=1e-12,abs_tol=1e-9), 'mesh measured volume differs')
    require(math.isclose(area,expected_area,rel_tol=1e-12,abs_tol=1e-9), 'mesh measured surface area differs')
    return {'dimensions_mm':dimensions,'volume_mm3':volume,'surface_area_mm2':area,'vertices':8,'edges':edge_count,'faces':6,
            'triangles':12,'euler_characteristic':2,'closed_oriented_manifold':True,'boundary_planes':6,
            'general_manufacturing_qualified':False,'brep_qualified':False}


def select(document, recipe):
    source.model_inventory(document)
    require(type(recipe) is dict and recipe.get('id')==panel.RECIPE and type(recipe.get('version')) is int and recipe['version']==panel.VERSION
            and recipe.get('units')=='mm' and recipe.get('fixed_origin')==[0.0,0.0], 'solid needs the known millimetre sketch recipe')
    owners=recipe.get('entities');require(type(owners) is dict and set(owners)=={'bottom','right','top','left'}, 'solid sketch selectors differ')
    handles=[owners[name] for name in ('bottom','right','top','left')]
    require(all(type(h) is int and 0<h<2**64 for h in handles) and len(set(handles))==4, 'solid sketch handles invalid')
    require(document['constraints']==panel.constraints(handles), 'solid sketch constraints differ from recipe')
    require(type(document['header']) is dict and document['header'].get('vars',{}).get('INSUNITS')==4, 'solid requires millimetres')
    entities={e['handle']:e for e in document['model']}
    require(all(h in entities and set(entities[h]['kind'])=={'type','a','b'} and entities[h]['kind']['type']=='line' for h in handles), 'solid needs four owned model lines')
    return handles,entities


def request(document, recipe, *, width, height, depth, mesh_handle=None):
    width,height,depth=[panel.dimension(v) for v in (width,height,depth)]
    handles,entities=select(document,recipe)
    require(type(document['parametric']) is dict, 'solid parametric settings invalid')
    rows=document['parametric'].get('parameters')
    names=['width','height']+(['depth'] if mesh_handle is not None else [])
    require(type(rows) is list and all(type(row) is dict for row in rows) and [row.get('name') for row in rows]==names, 'solid parameter inventory differs')
    for row,target in zip(rows,(width,height)):
        require(type(row.get('expr')) is str and len(row['expr'])<=64, 'solid parameter must be a bounded numeric literal')
        try:value=float(row['expr'])
        except ValueError as error:raise ValueError('CAD solid parameter must be a numeric literal') from error
        require(math.isfinite(value) and value==target, 'solid dimension differs from source parameter')
    corners=vertices(width,height,0)[:4]
    for i,handle in enumerate(handles):
        for key,expected in (('a',corners[i]),('b',corners[(i+1)%4])):
            actual=entities[handle]['kind'][key]
            require(type(actual) is dict and set(actual)=={'x','y','z'} and all(abs(numeric(actual[k])-expected[k])<=panel.TOLERANCE_MM for k in actual),
                    'solid extrusion requires solved sketch dimensions')
    if mesh_handle is not None:
        require(type(mesh_handle) is int and mesh_handle in entities and mesh_handle not in handles, 'solid mesh selector is invalid')
        mesh=entities[mesh_handle]['kind']
        require(mesh.get('type')=='polyfaceMesh' and type(mesh.get('vertices')) is list and len(mesh['vertices'])==8, 'solid revision needs an existing panel mesh')
        corner=mesh['vertices'][6]
        require(type(corner) is dict and set(corner)=={'x','y','z'}, 'solid opposite corner fields differ')
        inspect_mesh(mesh,width=corner['x'],height=corner['y'],depth=corner['z'])
    return {'width':float(width),'height':float(height),'depth':float(depth),'sketch_handles':handles,'mesh_handle':mesh_handle}


def depth_expression(value):
    value=float(value)
    return str(int(value)) if value.is_integer() else str(value)


def predict(document, requested):
    """Predict only a previously validated panel request; no engine claim is made."""
    width,height,depth=[requested[key] for key in ('width','height','depth')]
    prior=requested['mesh_handle'];handle=document['handseed'] if prior is None else prior
    predicted=copy.deepcopy(document);rows=predicted['parametric']['parameters'];expression=depth_expression(depth)
    geometry={'type':'polyfaceMesh','vertices':vertices(width,height,depth),'faces':copy.deepcopy(FACES)}
    if prior is None:
        first=next(e for e in predicted['model'] if e['handle']==requested['sketch_handles'][0])
        predicted['model'].append({'handle':handle,'common':copy.deepcopy(first['common']),'kind':geometry});predicted['handseed']+=1
        rows.append({'name':'depth','expr':expression,'description':'Panel depth in millimetres'})
    else:
        selected=next(e for e in predicted['model'] if e['handle']==handle);selected['kind']=geometry
        next(p for p in rows if p['name']=='depth')['expr']=expression
    source.model_inventory(predicted)
    return predicted


def verify(document, report, requested):
    fields={'schema_version','document','mesh_handle','dimensions_mm','volume_mm3','surface_area_mm2','vertices','faces','representation','complete_native_cold_equal','brep_qualified','general_manufacturing_qualified'}
    require(type(report) is dict and set(report)==fields and type(report.get('schema_version')) is int and report['schema_version']==1 and report.get('complete_native_cold_equal') is True
            and report.get('representation')=='closed-polyface-panel' and report.get('brep_qualified') is False
            and report.get('general_manufacturing_qualified') is False, 'native solid report fields differ')
    width,height,depth=[requested[key] for key in ('width','height','depth')]
    dimensions=[width,height,depth];prior=requested['mesh_handle'];handle=document['handseed'] if prior is None else prior
    require(type(report.get('mesh_handle')) is int and report['mesh_handle']==handle, 'native solid handle differs')
    predicted=predict(document,requested);expression=depth_expression(depth)
    require(revision.canonical(report.get('document'))==revision.canonical(predicted), 'native solid changed unrelated state or differs from prediction')
    actual=next(e['kind'] for e in report['document']['model'] if e['handle']==handle)
    measured=inspect_mesh(actual,width=width,height=height,depth=depth)
    require(type(report['dimensions_mm']) is list and all(type(v) in (int,float) for v in report['dimensions_mm'])
            and report['dimensions_mm']==dimensions and type(report['vertices']) is int and report['vertices']==8
            and type(report['faces']) is int and report['faces']==6 and type(report['volume_mm3']) in (int,float) and type(report['surface_area_mm2']) in (int,float)
            and report.get('volume_mm3')==width*height*depth and report.get('surface_area_mm2')==2*(width*height+width*depth+height*depth), 'native solid measurements differ from requested geometry')
    source.model_inventory(predicted)
    return {**measured,'mesh_handle':handle,'unrelated_state_exact':True,'depth_expression':expression}


def solve_projection(document, solved, recipe, mesh_handle):
    """Isolate the known sketch only after proving all other state unchanged."""
    handles,entities=select(document,recipe)
    require(type(mesh_handle) is int and mesh_handle in entities and entities[mesh_handle]['kind']['type']=='polyfaceMesh', 'solid solve mesh selector invalid')
    require(type(solved) is dict and set(solved)==set(document), 'solid solve document fields differ')
    source.model_inventory(solved)
    for key in document:
        if key!='model':require(revision.canonical(solved[key])==revision.canonical(document[key]), 'solid solve changed unrelated '+key)
    require([e['handle'] for e in solved['model']]==[e['handle'] for e in document['model']], 'solid solve changed entity order')
    for before,after in zip(document['model'],solved['model']):
        if before['handle'] not in handles:require(revision.canonical(before)==revision.canonical(after), 'solid solve changed unrelated entity')
    def projection(value):
        projected=copy.deepcopy(value);rows=projected['parametric']['parameters']
        require(type(rows) is list and [r.get('name') for r in rows]==['width','height','depth'], 'solid solve parameter inventory differs')
        projected['parametric']['parameters']=rows[:2]
        by_handle={e['handle']:e for e in projected['model']};projected['model']=[by_handle[h] for h in handles]
        return projected
    return projection(document),projection(solved)


def verify_solve_geometry(document, solved, recipe, mesh_handle, *, width, height):
    before,after=solve_projection(document,solved,recipe,mesh_handle)
    return panel.verify_geometry(before,after,recipe,width=width,height=height)


def verify_solve(document, report, recipe, mesh_handle, *, width, height):
    require(type(report) is dict, 'solid solve report must be an object')
    before,after=solve_projection(document,report.get('document'),recipe,mesh_handle)
    return panel.verify(before,{**report,'document':after},recipe,width=width,height=height)


def inspect_obj(data, *, width, height, depth):
    require(type(data) is bytes and 0<len(data)<=1<<20, 'OBJ exceeds byte budget')
    try:lines=data.decode('ascii').splitlines()
    except UnicodeError as error:raise ValueError('CAD panel OBJ must be ASCII') from error
    require(len(lines)==16 and lines[0]=='# Dobe panel mesh; coordinates in millimetres'
            and re.fullmatch(r'o panel_[1-9][0-9]{0,19}',lines[1]), 'OBJ identity, units or record count differs')
    points=[];faces=[]
    for line in lines[2:]:
        fields=line.split()
        if fields and fields[0]=='v':
            require(len(fields)==4 and not faces, 'OBJ vertex fields or order differs')
            try:point={key:float(value) for key,value in zip(('x','y','z'),fields[1:])}
            except ValueError as error:raise ValueError('CAD OBJ coordinate is malformed') from error
            points.append(point)
        else:
            require(len(fields)==5 and fields[0]=='f' and all(re.fullmatch('[1-8]',v) for v in fields[1:]), 'OBJ has unsupported or external records')
            faces.append([int(value) for value in fields[1:]])
    source.identity(int(lines[1].split('_')[1]), 'OBJ mesh handle')
    mesh={'type':'polyfaceMesh','vertices':points,'faces':faces};measured=inspect_mesh(mesh,width=width,height=height,depth=depth)
    return {'mesh':mesh,'measurements':measured,'sha256':source.sha(data),'units':'mm','mesh_handle':int(lines[1].split('_')[1])}
