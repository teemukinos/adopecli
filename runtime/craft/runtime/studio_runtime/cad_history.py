"""Pure typed panel history. Saved candidates never attest to native execution.

Solid construction is predicted deterministically. Solve entries own the exact
observed endpoint values and independently check their geometry, but still need
fresh receipt-bound native replay before any execution/fidelity claim.
"""
import copy

from . import cad_source as source, cad_revision as revision, cad_parametric as panel, cad_solid as solid
from .cad_source import require

KINDS = {'panel.solid', 'panel.solve'}


def apply(document, edit):
    require(type(edit) is dict and type(edit.get('kind')) is str and edit['kind'] in KINDS, 'panel history kind invalid')
    common={'kind','recipe','width','height','mesh_handle'}
    require(set(edit)==common|({'depth'} if edit['kind']=='panel.solid' else {'geometry'}), 'panel history fields differ')
    recipe=edit['recipe'];width=panel.dimension(edit['width']);height=panel.dimension(edit['height']);mesh=edit['mesh_handle']
    if edit['kind']=='panel.solid':
        request=solid.request(document,recipe,width=width,height=height,depth=edit['depth'],mesh_handle=mesh)
        result=solid.predict(document,request)
        selected=document['handseed'] if mesh is None else mesh
        geometry=next(e['kind'] for e in result['model'] if e['handle']==selected)
        measured=solid.inspect_mesh(geometry,width=width,height=height,depth=edit['depth'])
        paths=['/model','/parametric/parameters']+(['/handseed'] if mesh is None else [])
    else:
        handles,entities=solid.select(document,recipe)
        changes=source.sequence(edit['geometry'],'solve geometry',4);require(changes,'solve history must change geometry')
        result=copy.deepcopy(document);targets={e['handle']:e for e in result['model']};used=set();paths=[]
        for change in changes:
            require(type(change) is dict and set(change)=={'handle','expected','value'}, 'solve geometry fields differ')
            handle=change['handle'];require(type(handle) is int and handle in handles and handle not in used, 'solve geometry owner invalid or duplicated')
            used.add(handle);before=entities[handle]['kind'];value=change['value']
            require(revision.canonical(before)==revision.canonical(change['expected']), 'solve geometry changed since inspection')
            require(type(value) is dict and set(value)=={'type','a','b'} and value['type']=='line', 'solve candidate must own exact line fields')
            replacement={'type':'line','a':revision.point(value['a']),'b':revision.point(value['b'])}
            require(revision.canonical(replacement)!=revision.canonical(before), 'solve entry contains unchanged geometry')
            targets[handle]['kind']=replacement
            index=next(i for i,e in enumerate(result['model']) if e['handle']==handle);paths.append(f'/model/{index}/kind')
        if mesh is None:measured=panel.verify_geometry(document,result,recipe,width=width,height=height)
        else:measured=solid.verify_solve_geometry(document,result,recipe,mesh,width=width,height=height)
        require(set(measured['changed_entities'])==used, 'solve candidate changed unselected geometry')
    return {'document':result,'changed_paths':paths,'measurements':measured,'native_recipe_replay_required':True}


def capture_solve(before, after, recipe, *, width, height, mesh_handle=None):
    """Encode exact candidate changes; only the observer can prove native replay."""
    original=source.inspect_bytes(before,'json')['document'];candidate=source.inspect_bytes(after,'json')['document']
    handles,entities=solid.select(original,recipe);targets={e['handle']:e for e in candidate['model']};changes=[]
    require(all(h in targets for h in handles), 'solve candidate lost sketch handles')
    for handle in handles:
        old=entities[handle]['kind'];new=targets[handle]['kind']
        if revision.canonical(old)!=revision.canonical(new):changes.append({'handle':handle,'expected':copy.deepcopy(old),'value':copy.deepcopy(new)})
    edit={'kind':'panel.solve','recipe':copy.deepcopy(recipe),'width':width,'height':height,'mesh_handle':mesh_handle,'geometry':changes}
    predicted=apply(original,edit)['document']
    require(revision.canonical(predicted)==revision.canonical(candidate), 'solve capture changed unrelated source state')
    return edit
