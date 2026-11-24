"""Bounded, integrity-checked evidence from published revisions, never log dumps."""
import base64
import copy
import hashlib
import json
import os
import re
import stat
from .store import Conflict
from . import agent_crops


def blob(store, entry, maximum=16 << 20):
    if not re.fullmatch('[0-9a-f]{64}',entry['sha256']):raise ValueError('Invalid evidence hash')
    path=store.blobs/entry['sha256']
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>maximum: raise ValueError('Artifact exceeds model inspection limit')
        raw=stream.read(maximum+1)
    if len(raw)>maximum:raise ValueError('Artifact exceeds model inspection limit')
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']: raise Conflict('Published evidence hash differs')
    return raw


def collect(store,workspace,revision,selection=None,inspection=None,crops=None):
    manifest=store.get_revision(workspace,revision)
    entries=manifest['files'];images=[];sources={};metrics={}
    selectable=[e for e in entries if e['path'].lower().endswith(('.png','.jpg','.jpeg')) and e['role']=='export']
    inspection_entries=[]
    if inspection:
        if inspection['revision']!=revision:raise Conflict('Inspection belongs to another revision')
        metrics['behavioral_inspection']={k:v for k,v in inspection.items() if k!='previews'}
        for entry in inspection['previews']:
            asset=store.get_asset(workspace,entry['project'],entry['asset'])
            if asset['sha256']!=entry['sha256']:raise Conflict('Inspection asset hash differs')
            inspection_entries.append({'path':'inspection/'+entry['path'],'role':'export','sha256':entry['sha256']})
        selectable.extend(inspection_entries)
    selectable.sort(key=lambda e:[int(p) if p.isdigit() else p for p in re.split(r'(\d+)',e['path'])])
    available={e['path']:e for e in selectable}
    if crops is not None:
        if not isinstance(crops,dict) or set(crops)!={'revision','regions'} or not isinstance(crops['regions'],list):
            raise ValueError('Invalid pinned crop selection')
        regions=crops['regions']
        if any(not isinstance(r,dict) or set(r)!={'path','box','sha256'} for r in regions):
            raise ValueError('Invalid pinned crop region')
        pinned=agent_crops.pin(revision,crops['revision'],[{k:r[k] for k in ('path','box')} for r in regions],selectable)
        if pinned!=crops:raise Conflict('Crop source no longer matches published evidence')
        if selection is None:selection=[]
    if selection is not None:
        if not isinstance(selection,list) or not (0 if crops else 1)<=len(selection)<=8 or not all(isinstance(p,str) for p in selection) or len(set(selection))!=len(selection) or any(p not in available for p in selection):
            raise ValueError('Inspection must select at most eight published image paths')
        selectable=[e for e in selectable if e['path'] in selection]
    elif len(selectable)>8:
        # Preserve every distinct state when duplicates would otherwise crowd a
        # keyframe out. Larger unique sequences still sample beginning/end.
        unique=[];duplicates=[];seen=set()
        for entry in selectable:
            (duplicates if entry['sha256'] in seen else unique).append(entry)
            seen.add(entry['sha256'])
        selectable=(unique+duplicates[:8-len(unique)] if len(unique)<=8 else
                    [unique[round(i*(len(unique)-1)/7)] for i in range(8)])
    if len(selectable)+len(crops['regions'] if crops else [])>8:
        raise ValueError('Inspection supports at most eight full images and crops combined')
    for entry in entries:
        name=entry['path']
        if name in ('production/recipe.json','construction/document.json','native/document.json'):
            sources[name]=json.loads(blob(store,entry,2<<20))
        elif name=='production/native/readback.json':
            # Cold reopening compares this snapshot with the saved native scene.
            # Artifact names or hashes alone cannot establish native editability.
            metrics[name]=json.loads(blob(store,entry,2<<20))
        elif name=='native/sequence.json':
            sequence=json.loads(blob(store,entry,2<<20))
            metrics[name]={'durationFrames':sequence['durationFrames'],'settings':sequence['settings'],
                          **{kind:[{'name':track['name'],'transitions':track.get('transitions',[]),
                                    'items':[{k:v for k,v in item.items() if k in ('clip','name','startFrame','endFrame','durationFrames','gainDb','sourceIn','sourceOut','enabled','speed','reverse')} for item in track['items']]}
                                   for track in sequence[kind]] for kind in ('video','audio')}}
        elif name.endswith(('metrics.json','probe.json','revision-proof.json','inspection.json','structure.json')):
            value=json.loads(blob(store,entry,2<<20))
            if name=='exports/decode-inspection.json':
                value['decoded_picture_count']=len(value.pop('pictures',[]))
            # Technical evidence is retained fully in the revision. Keep model context bounded.
            if len(json.dumps(value))<=16000: metrics[name]=value
            else: metrics[name]={'retained':True,'sha256':entry['sha256']}
    for entry in selectable:
        mime='image/png' if entry['path'].endswith('.png') else 'image/jpeg'
        raw=blob(store,entry)
        images.append({'path':entry['path'],'sha256':entry['sha256'],
                       'dimensions':agent_crops.dimensions(raw),
                       'content':{'type':'input_image','detail':'high','image_url':'data:'+mime+';base64,'+base64.b64encode(raw).decode()}})
    if crops:
        metrics['detail_crops']=[]
        for index,region in enumerate(crops['regions']):
            raw,provenance=agent_crops.render(blob(store,available[region['path']]),region,revision)
            path='crop/'+str(index)+'/'+region['path']
            metrics['detail_crops'].append({'path':path,**provenance})
            images.append({'path':path,'sha256':provenance['sha256'],'dimensions':provenance['dimensions'],
                           'content':{'type':'input_image','detail':'high','image_url':'data:image/png;base64,'+base64.b64encode(raw).decode()}})
    return {'revision':revision,'validation':manifest.get('validation',{}),
            'artifacts':[{'path':e['path'],'role':e['role'],'sha256':e['sha256']} for e in [*entries,*inspection_entries]],
            'sources':sources,'technical_evidence':metrics,'images':images}


def inspection_selection(store,workspace,context,decision):
    revision=context.get('revision')
    if not revision:raise ValueError('No revision to inspect')
    selection=decision.get('artifacts');crops=None
    if decision.get('crops') is not None:
        manifest=store.get_revision(workspace,revision)
        entries=[e for e in manifest['files'] if e['role']=='export' and e['path'].lower().endswith(('.png','.jpg','.jpeg'))]
        inspection=context.get('inspection')
        if inspection:
            if inspection['revision']!=revision:raise Conflict('Inspection belongs to another revision')
            entries.extend({'path':'inspection/'+e['path'],'sha256':e['sha256']} for e in inspection['previews'])
        crops=agent_crops.pin(revision,decision.get('revision'),decision['crops'],entries)
    # Decode and validate bounds before committing the selection. No new assets,
    # files, model calls or render jobs are created. Resume derives identical pixels.
    collect(store,workspace,revision,selection,context.get('inspection'),crops)
    selected_state(context,decision.get('focus'))
    notes=decision.get('notes','')
    if not isinstance(notes,str):raise ValueError('Inspection notes must be text')
    previous=context.get('inspection_memory') or {}
    if previous.get('revision')!=revision:previous={}
    if previous and previous.get('version')!=1:raise Conflict('Unsupported inspection memory version')
    assessments=copy.deepcopy(previous.get('assessments',[]))
    assessment={'notes':notes[:2000],'notes_truncated':len(notes)>2000,
                'reviewed':{'artifacts':copy.deepcopy(context.get('selection')),
                            'crops':copy.deepcopy((context.get('crops') or {}).get('regions',[]))}}
    # The notes describe evidence the model just reviewed, not the new selection.
    # Full paid decisions remain in the journal; only bounded summaries enter the
    # next request. Replaying a received decision must not duplicate its summary.
    if not assessments or assessment!=assessments[-1]:assessments.append(assessment)
    omitted=previous.get('omitted_assessments',0)+max(0,len(assessments)-4)
    memory={'version':1,'revision':revision,'assessments':assessments[-4:],
            'omitted_assessments':omitted,'scope':'Prior model observations, not technical proof. Null artifacts means the default published preview selection.'}
    return {'selection':selection,'focus':decision.get('focus'),'crops':crops,'inspection_memory':memory}


def selected_state(context, focus=None):
    value=copy.deepcopy(context)
    memory=value.get('inspection_memory')
    if memory:
        if memory.get('revision')!=value.get('revision'):value.pop('inspection_memory')
        elif memory.get('version')!=1:raise Conflict('Unsupported inspection memory version')
    for key in ('preflight_attempts','usage_reconciliations','revisions','consumed_call','pending_actions','reconstruction_projects','inspection','crops'):
        value.pop(key,None)
    document=value.get('document')
    if isinstance(document,dict) and {'body','lastSection','settings'}<=set(document):
        from .write_structure import inspect as structure
        from .write_revision import locate
        profile=structure(document)
        paragraphs=[]
        for entry in profile['paragraphs']:
            paragraph=locate(document,entry['path'])
            paragraphs.append({'path':entry['path'],'text':paragraph['text'],
                               'props':paragraph.get('props',{}),'runs':paragraph['runs']})
        sections=[{'path':'/lastSection','properties':document['lastSection']}]
        for entry in profile['paragraphs']:
            paragraph=locate(document,entry['path'])
            if paragraph.get('section') is not None:sections.append({'path':entry['path']+'/section','properties':paragraph['section']})
        value['document']={'paragraphs':paragraphs,'sections':sections,
                           'protected_or_tracked':bool(document['settings'].get('trackChanges') or document['settings'].get('protectFormatting'))}
        return value
    if not focus: return value
    if not isinstance(focus,list) or not all(isinstance(v,str) for v in focus):
        raise ValueError('Focus must list component identifiers')
    document=value.get('document')
    if isinstance(document,dict) and 'components' in document:
        nodes={c['id']:c for c in document['components']}
        selected={key:nodes[key] for key in focus if key in nodes}
        if set(focus)-set(selected): raise ValueError('Unknown focus component')
        pending=list(selected)
        while pending:
            for ref in nodes[pending.pop()].get('inputs',{}).values():
                dependency=ref['component']
                if dependency not in selected:
                    selected[dependency]=nodes[dependency];pending.append(dependency)
        # Shared constraints remain outside component documents; include dependency references.
        value['component_inventory']=[{'id':c['id'],'engine':c['engine']} for c in document['components']]
        value['document']={**document,'components':list(selected.values())}
    return value
