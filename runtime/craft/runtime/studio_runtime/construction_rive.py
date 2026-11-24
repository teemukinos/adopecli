"""Script-free RML construction, state-machine compilation and portable web playback."""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from .construction_schema import require, NAME
from .construction_support import DATA, binary, run, sha, write
from .construction_blender import number

PROPS={'x':13,'y':14,'rotation':15,'scaleX':16,'scaleY':17,'opacity':18,'color':37}

def validate(p):
    require(isinstance(p,dict) and {'width','height','objects','states','input','events'}<=set(p)<={'width','height','objects','states','input','events','transition_ms'},'Rive requires dimensions, objects, states, input and events')
    require(all(type(p[k]) is int and 16<=p[k]<=4096 for k in ('width','height')),'Invalid artboard size')
    require(number(p.get('transition_ms',180),0,2000),'Invalid transition duration')
    require(isinstance(p['input'],str) and NAME.fullmatch(p['input']),'Invalid state input name')
    require(isinstance(p['objects'],list) and 1<=len(p['objects'])<=128,'Invalid Rive object count');ids=set()
    for o in p['objects']:
        require(isinstance(o,dict) and {'id','kind','x','y','color'}<=set(o)<= {'id','kind','x','y','color','width','height','text','size','opacity'},'Invalid Rive object')
        require(isinstance(o['id'],str) and NAME.fullmatch(o['id']) and o['id'] not in ids and o['kind'] in ('rectangle','ellipse','text'),'Unsupported Rive object kind/ID');ids.add(o['id'])
        require(all(number(o[k],-8192,8192) for k in ('x','y')) and re.fullmatch('#[a-fA-F0-9]{6}',o['color']),'Invalid Rive transform/color')
        require(number(o.get('opacity',1),0,1),'Invalid opacity')
        if o['kind']=='text':require(isinstance(o.get('text'),str) and 1<=len(o['text'])<=4000 and number(o.get('size'),1,512),'Invalid native text')
        else:require(all(number(o.get(k),1,8192) for k in ('width','height')),'Invalid shape dimensions')
    require(isinstance(p['states'],list) and 1<=len(p['states'])<=32,'Invalid state count');values=set();names=set()
    for s in p['states']:
        require(isinstance(s,dict) and set(s)=={'id','value','pose'} and isinstance(s['id'],str) and NAME.fullmatch(s['id']) and s['id'] not in names and type(s['value']) is int and s['value'] not in values,'Invalid state identity')
        names.add(s['id']);values.add(s['value']);require(isinstance(s['pose'],dict) and set(s['pose'])<=ids,'Pose names unknown objects')
        for obj,props in s['pose'].items():
            require(isinstance(props,dict) and set(props)<=set(PROPS),'Unsupported pose property')
            for k,v in props.items():
                require(isinstance(v,str) and re.fullmatch('#[a-fA-F0-9]{6}',v) if k=='color' else number(v,0,1) if k=='opacity' else number(v,.001,100) if k in ('scaleX','scaleY') else number(v,-8192,8192),'Invalid pose value')
    require(isinstance(p['events'],list) and len(p['events'])<=128,'Invalid listener list')
    for e in p['events']:
        require(isinstance(e,dict) and set(e)=={'target','event','value'} and e['target'] in {o['id'] for o in p['objects'] if o['kind']!='text'} and e['event'] in ('enter','exit','down','up','click') and type(e['value']) is int and e['value'] in values,'Invalid native event binding')

def compile_document(p, reduced=False):
    validate(p);root=ET.Element('Rive',version='1',kind='fragment')
    art=ET.SubElement(root,'Artboard',width=str(p['width']),height=str(p['height']),name='Construction',id='0:1',defaultStateMachineId='0:2')
    machine=ET.SubElement(art,'StateMachine',name='Construction',id='0:2');ET.SubElement(machine,'StateMachineNumber',name=p['input'],id='0:3',value=str(p['states'][0]['value']))
    layer=ET.SubElement(machine,'StateMachineLayer',name='States',id='0:4');any_state=ET.SubElement(layer,'AnyState',x='200',y='-120');ET.SubElement(layer,'ExitState',x='400',y='-120')
    entry=ET.SubElement(layer,'EntryState',x='0',y='0')
    def native_id(name):return 10000+int(hashlib.sha256(name.encode()).hexdigest()[:6],16)*4
    state_ids={s['id']:native_id('state-'+s['id']) for s in p['states']}
    ET.SubElement(entry,'StateTransition',stateToId=f"0:{state_ids[p['states'][0]['id']]}")
    mapping={o['id']:{'object':f'0:{native_id(o["id"])}','color':f'0:{native_id(o["id"])+1}'} for o in p['objects']}
    require(len({v['object'] for v in mapping.values()})==len(mapping),'Native ID collision; choose a different explicit object ID')
    # Explicit IDs remain tied to a persisted map, independent of source iteration.
    for i,s in enumerate(p['states']):
        state_id=f"0:{state_ids[s['id']]}";anim_id=f"0:{state_ids[s['id']]+1}"
        trans=ET.SubElement(any_state,'StateTransition',stateToId=state_id,duration=str(0 if reduced else p.get('transition_ms',180)));ET.SubElement(trans,'TransitionNumberCondition',inputId='0:3',opValue='equal',value=str(s['value']))
        ET.SubElement(layer,'AnimationState',animationId=anim_id,id=state_id,x=str(160+i*180),y='0')
        animation=ET.SubElement(art,'LinearAnimation',name=s['id'],id=anim_id,duration='1',fps='60')
        for o in p['objects']:
            defaults={'x':o['x'],'y':o['y'],'scaleX':1,'scaleY':1,'rotation':0,'opacity':o.get('opacity',1),'color':o['color']}
            props={**defaults,**s['pose'].get(o['id'],{})}
            for key,value in props.items():
                obj=ET.SubElement(animation,'KeyedObject',objectId=mapping[o['id']]['color' if key=='color' else 'object'])
                prop=ET.SubElement(obj,'KeyedProperty',propertyKey=str(PROPS[key]))
                ET.SubElement(prop,'KeyFrameColor' if key=='color' else 'KeyFrameDouble',value='FF'+value[1:] if key=='color' else str(value),interpolationType='hold')
    for e in p['events']:
        listener=ET.SubElement(machine,'StateMachineListenerSingle',targetId=mapping[e['target']]['object'],listenerTypeValue=e['event'],name=e['target']+'_'+e['event'])
        ET.SubElement(listener,'ListenerNumberChange',inputId='0:3',value=str(e['value']))
    for i,o in reversed(list(enumerate(p['objects']))):
        common={'id':mapping[o['id']]['object'],'name':o['id'],'x':str(o['x']),'y':str(o['y']),'opacity':str(o.get('opacity',1))}
        if o['kind']=='text':
            element=ET.SubElement(art,'Text',**common,sizingValue='autoWidth',originX='0.5',originY='0.5')
            style=ET.SubElement(element,'TextStylePaint',id=f'0:{native_id(o["id"])+2}',fontSize=str(o['size']),fontAssetId='0:2000',name='Archivo')
            fill=ET.SubElement(style,'Fill',name='Fill');ET.SubElement(element,'TextValueRun',styleId=f'0:{native_id(o["id"])+2}',text=o['text'],name='Text')
        else:
            element=ET.SubElement(art,'Shape',**common);ET.SubElement(element,'Rectangle' if o['kind']=='rectangle' else 'Ellipse',width=str(o['width']),height=str(o['height']),name='Path');fill=ET.SubElement(element,'Fill',name='Fill')
        ET.SubElement(fill,'SolidColor',id=mapping[o['id']]['color'],colorValue='FF'+o['color'][1:],name='Color')
    ET.SubElement(root,'FontAsset',id='0:2000',file='archivo-variable.ttf',name='Archivo')
    ET.indent(root);return ET.tostring(root,encoding='unicode'),mapping

def execute(root,p,mode='create',previous=None,output=None):
    validate(p);root=Path(root);native=root/'native';native.mkdir(exist_ok=True);exports=root/'exports';exports.mkdir(exist_ok=True)
    # Derived reduced-motion source must be outside the RML compiler's recursive source root.
    if (native/'reduced').exists():shutil.rmtree(native/'reduced')
    source,mapping=compile_document(p)
    if mode in ('inspect','render'):
        require((native/'scene.rml').read_text()==source+'\n','Saved RML differs from the typed native source')
    if previous is not None:
        old_source,old_map=compile_document(previous)
        require((native/'scene.rml').read_text()==old_source+'\n','Revision source differs from previous native artwork')
        require(all(old_map[k]==mapping[k] for k in old_map.keys()&mapping.keys()),'Native IDs changed')
    # Reuse native IDs for unchanged order; structural edits update the map explicitly.
    (native/'scene.rml').write_text(source+'\n');(native/'rive.yaml').write_text('name: construction\n')
    shutil.copyfile(DATA/'fonts/archivo-variable.ttf',native/'archivo-variable.ttf');shutil.copyfile(DATA/'fonts/archivo-OFL.txt',native/'archivo-OFL.txt')
    source_sha=sha(native/'scene.rml');trace=[]
    trace.append(run(root,[binary('rive'),'inspect',native,'--json'],'readback',120))
    resolved=json.loads((root/'logs/readback.log').read_text())
    require(not any(x['severity']=='error' for x in resolved.get('problems',[])),'Resolved RML has errors')
    def walk(v):
        if isinstance(v,dict):
            yield v
            for x in v.values():yield from walk(x)
        elif isinstance(v,list):
            for x in v:yield from walk(x)
    actual=list(walk(resolved))
    for obj in p['objects']:
        require(any(x.get('id')==mapping[obj['id']]['object'] and x.get('name')==obj['id'] for x in actual),'Resolved native object missing')
    require(sum(x.get('type')=='AnimationState' for x in actual)==len(p['states']),'Resolved native state count differs')
    for label,flags in [('verify',['--verify']),('compile',['--once']),('capture',['--screenshot','--advance=1'])]:
        trace.append(run(root,[binary('rive'),native,*flags],label,120))
    require(sha(native/'scene.rml')==source_sha,'Rive normalized source unexpectedly')
    shutil.copyfile(native/'build/construction.riv',exports/'construction.riv');shutil.copyfile(native/'build/construction.png',exports/'preview.png')
    reduced=root/'native-reduced';reduced.mkdir(exist_ok=True)
    (reduced/'scene.rml').write_text(compile_document(p,True)[0]+'\n');(reduced/'rive.yaml').write_text('name: reduced\n')
    shutil.copyfile(native/'archivo-variable.ttf',reduced/'archivo-variable.ttf')
    trace.append(run(root,[binary('rive'),reduced,'--once'],'reduced-compile',120))
    write(native/'objects.json',mapping);write(native/'construction.json',p)
    web=exports/'web';web.mkdir(exist_ok=True)
    assets=json.loads((DATA/'support.json').read_text()).get('web_runtime')
    require(assets is not None,'Pinned web runtime unavailable')
    for name,pin in assets['files'].items():
        path=DATA/pin['path'];require(sha(path)==pin['sha256'],'Web runtime pin differs');shutil.copyfile(path,web/name)
    shutil.copyfile(exports/'construction.riv',web/'construction.riv')
    shutil.copyfile(reduced/'build/reduced.riv',web/'reduced.riv')
    write(web/'component.json',{'input':p['input'],'states':p['states'],'objects':p['objects'],'events':p['events'],'width':p['width'],'height':p['height'],'runtime_version':assets['version']})
    shutil.copyfile(DATA/'player.html',web/'index.html')
    write(root/'trace.json',trace)
    return {'script_free':True,'native_source_sha256':source_sha,'native_compiled':True,'native_resolved_objects':True,'native_reopen_process':True,'web_runtime_version':assets['version'],'browser_qualification':'requires behavior harness','creative_status':'review_required'}
