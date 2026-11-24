"""Closed construction documents, dependency ordering and optimistic revisions."""
import copy
import hashlib
import json
import re
from pathlib import PurePosixPath

POLICY = {'media_generation': 'disabled', 'network': 'offline'}
ENGINES = ('image', 'vector', 'motion', 'video', 'animate', 'blender', 'rive')
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')

def require(value, message):
    if not value: raise ValueError(message)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def relative(value):
    require(isinstance(value, str) and '\\' not in value and value and not PurePosixPath(value).is_absolute()
            and all(p not in ('', '.', '..') for p in value.split('/')), 'Invalid component artifact path')
    return value

def adapter(engine):
    from . import image_layers, vector, motion, video, animate
    return {'image':image_layers, 'vector':vector, 'motion':motion, 'video':video, 'animate':animate}.get(engine)

def validate(document):
    require(isinstance(document, dict) and set(document)=={'schema_version','policy','components'} and type(document['schema_version']) is int and document['schema_version']==1,
            'Construction requires schema_version, policy and components')
    require(document['policy']==POLICY, 'Construction requires offline execution with media generation disabled')
    nodes=document['components']; require(isinstance(nodes,list) and 1<=len(nodes)<=32, 'Provide 1–32 components')
    require(len(json.dumps(document,allow_nan=False).encode())<=1<<20, 'Construction document exceeds 1 MiB')
    by_id={}
    for n in nodes:
        require(isinstance(n,dict) and {'id','engine','parameters'}<=set(n)<= {'id','engine','parameters','inputs'}, 'Invalid component fields')
        require(isinstance(n['id'],str) and NAME.fullmatch(n['id']) and n['id'] not in by_id, 'Duplicate or invalid component ID')
        require(n['engine'] in ENGINES and isinstance(n['parameters'],dict), 'Unsupported engine profile')
        by_id[n['id']]=n
        inputs=n.get('inputs',{});require(isinstance(inputs,dict) and len(inputs)<=64,'Invalid component inputs')
        for aid,link in inputs.items():
            require(isinstance(aid,str) and re.fullmatch('[a-f0-9]{32}',aid) and isinstance(link,dict)
                    and set(link)=={'component','artifact'}, 'Inputs map local asset IDs to component artifacts')
            relative(link['artifact'])
        a=adapter(n['engine'])
        if a:a.validate(n['engine']+'.create',n['parameters'],None)
        elif n['engine']=='blender':
            from .construction_blender import validate
            validate(n['parameters'])
        else:
            from .construction_rive import validate
            validate(n['parameters'])
    ordered=[];visiting=set();done=set()
    def visit(name):
        require(name in by_id and name not in visiting, 'Missing component dependency or cycle')
        if name in done:return
        visiting.add(name)
        for link in by_id[name].get('inputs',{}).values():visit(link['component'])
        visiting.remove(name);done.add(name);ordered.append(by_id[name])
    for name in by_id:visit(name)
    return ordered

def revise(before, edits):
    require(isinstance(edits,list) and 1<=len(edits)<=128,'Provide 1–128 construction edits')
    after=copy.deepcopy(before);seen=set()
    for e in edits:
        require(isinstance(e,dict) and {'component','action'}<=set(e), 'Invalid edit')
        cid=e['component'];require(isinstance(cid,str) and NAME.fullmatch(cid),'Invalid component selector')
        nodes={n['id']:n for n in after['components']}; action=e['action']
        if action=='add':
            require(set(e)=={'component','action','value'} and cid not in nodes and e['value'].get('id')==cid,'Invalid add')
            after['components'].append(copy.deepcopy(e['value']));continue
        require(cid in nodes,'Edit component does not exist');n=nodes[cid]
        if action=='remove':
            require(set(e)=={'component','action'},'Invalid remove');after['components'].remove(n);continue
        require(action=='set' and set(e)=={'component','action','path','before','value'},'Expected explicit set with before/value')
        path=e['path'];require(isinstance(path,list) and path and path[0] in ('parameters','inputs') and len(path)<=16,'Invalid edit path')
        key=(cid,json.dumps(path));require(key not in seen,'Duplicate edit target');seen.add(key)
        target=n
        for token in path[:-1]:
            if isinstance(target,list):require(type(token) is int and 0<=token<len(target),'Invalid array selector')
            else:require(isinstance(target,dict) and token in target,'Missing edit selector')
            target=target[token]
        token=path[-1]
        if isinstance(target,list):require(type(token) is int and 0<=token<len(target),'Invalid array selector')
        else:require(isinstance(target,dict) and token in target,'Missing edit field')
        require(target[token]==e['before'],'Revision precondition does not match')
        target[token]=copy.deepcopy(e['value'])
    validate(after)
    return after
