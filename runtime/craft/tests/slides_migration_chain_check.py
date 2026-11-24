#!/usr/bin/env python3
"""Qualify real maintained Slides migration chains and bounded portable replay."""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from unittest.mock import patch
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('resources','prior','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();out=args.output.resolve();out.mkdir();resources=args.resources.resolve()
    sys.path.insert(0,str(resources/'runtime'))
    from studio_runtime import slides,slides_project as project,slides_revision as revision
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    os.environ['PATH']='/usr/bin:/bin';store=Store(out/'state');checks=[];refusals=[];jobs=[]
    sha=lambda data:hashlib.sha256(data).hexdigest()
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError as error:refusals.append({'case':label,'error':str(error)})
        else:raise AssertionError('accepted '+label)
    def call(name,params):
        code="import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"
        response=subprocess.run([sys.executable,'-I','-B','-c',code,str(resources/'runtime'),str(out/'state')],
            input=(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':params}})+'\n').encode(),capture_output=True,timeout=30)
        assert response.returncode==0,response.stderr
        result=json.loads(response.stdout);assert 'error' not in result,result
        result=result['result']
        if result.get('isError'):raise ValueError(result['content'][0]['text'])
        return json.loads(result['content'][0]['text'])
    def job(owner,operation,params,previous=None):
        request={'project':owner,'operation':operation,'parameters':params,'idempotency_key':'chain-'+str(len(jobs))}
        if previous:request['source_revision']=previous['id']
        submitted=call('submit_job',request);assert call('submit_job',request)['id']==submitted['id']
        Worker(store).run_one();actual=call('get_job',{'job':submitted['id']});jobs.append(actual);assert actual['state']=='succeeded',actual
        return call('get_revision',{'revision':actual['result_revision']})
    def checkout(label,state):
        target=out/label;call('export_project',{'revision':state['id'],'destination':str(target)});return target
    def mutate(label,change):
        checked=project.inspect_bytes(chain);manifest=copy.deepcopy(checked['manifest']);members={k:v for k,v in checked['members'].items() if k!='project.json'}
        change(manifest,members);manifest['members']={name:project.record(value) for name,value in members.items()}
        refused(label,lambda:project.inspect_bytes(project.pack(manifest,members)))
    try:
        original=args.prior.read_bytes();old=project.inspect_bytes(original)
        check('input is a real prior migration followed by an authored revision',old['migration_count']==1
              and old['revision_count']>old['migration']['revision_count'])
        leaf=old['predecessor'];chain=project.migrate(original,sha(original),engine=slides.binding.PIN);current=project.inspect_bytes(chain)
        (out/'chain.dobeslides').write_bytes(chain)
        check('two maintained transitions preserve exact predecessor archives',current['migration_count']==2
              and current['members']['predecessor.dobeslides']==original
              and current['predecessor']['members']['predecessor.dobeslides']==old['members']['predecessor.dobeslides']
              and current['predecessor']['predecessor']['sha256']==leaf['sha256'])
        check('every original, baseline and authored edit survives both transitions',current['source_sha256']==old['source_sha256']==leaf['source_sha256']
              and current['members']['baseline.json']==old['members']['baseline.json']
              and current['members']['document.json']==old['members']['document.json']
              and current['manifest']['history']==old['manifest']['history'])
        check('chain construction is deterministic',project.migrate(original,sha(original),engine=slides.binding.PIN)==chain)
        refused('stale predecessor',lambda:project.migrate(original,'0'*64,engine=slides.binding.PIN))
        refused('same engine',lambda:project.migrate(chain,sha(chain),engine=slides.binding.PIN))
        refused('unqualified downgrade',lambda:project.migrate(chain,sha(chain),engine=old['manifest']['engine']))
        refused('unknown engine edge',lambda:project.migrate(original,sha(original),engine={**slides.binding.PIN,'source_lock_sha256':'f'*64}))
        mutate('changed transition hash',lambda m,b:m['migration'].update(predecessor_sha256='0'*64))
        mutate('changed transition history count',lambda m,b:m['migration'].update(revision_count=0))
        mutate('changed transition target',lambda m,b:m['migration']['to_engine'].update(source_lock_sha256='0'*64))
        def trim_history(manifest,members):
            manifest['history']=[];members['document.json']=members['baseline.json']
        mutate('pruned predecessor edit history',trim_history)
        mutate('substituted inner ancestor',lambda m,b:b.update({'predecessor.dobeslides':old['members']['predecessor.dobeslides']}))
        with patch.object(project,'MAX_MIGRATIONS',1):refused('bounded chain depth',lambda:project.inspect_bytes(chain))
        with patch.object(project,'MAX_CHAIN_BYTES',len(chain)):refused('shared archive budget includes ancestors',lambda:project.inspect_bytes(chain))
        compressed=io.BytesIO()
        with zipfile.ZipFile(compressed,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in current['members'].items():archive.writestr(name,data)
        compressed_bytes=compressed.getvalue()
        check('compressed outer archive preserves the same exact migration chain',project.inspect_bytes(compressed_bytes)['migration_count']==2)
        archive_total=len(compressed_bytes)+len(original)+len(old['members']['predecessor.dobeslides'])
        expanded_outer=sum(map(len,current['members'].values()))
        expansion_limit=max(archive_total,expanded_outer)+1
        assert expansion_limit<expanded_outer+sum(map(len,old['members'].values()))
        with patch.object(project,'MAX_CHAIN_BYTES',expansion_limit):refused('shared expanded byte budget includes ancestors',lambda:project.inspect_bytes(compressed_bytes))
        own_replay=len(current['members']['baseline.json'])
        replay=current['members']['baseline.json']
        for entry in current['manifest']['history']:
            replay=revision.revise_bytes(replay,entry['before'],entry['edits'])['data'];own_replay+=len(replay)
        with patch.object(project,'MAX_REPLAY',own_replay):refused('shared replay budget includes ancestors',lambda:project.inspect_bytes(chain))
        owner=call('create_project',{'name':'Existing migration chain'})['id'];asset=store.import_asset('local',owner,args.prior)['id']
        migrated=job(owner,'slides.migrate',{'asset':asset,'expected_sha256':sha(original)});folder=checkout('migrated',migrated)
        check('durable asset migration matches private prediction and native cold reopen',(folder/'native/project.dobeslides').read_bytes()==chain
              and migrated['validation']['engine_migration_verified'] and migrated['validation']['native_cold_reopen'])
        report=json.loads((folder/'exports/inspection.json').read_bytes());check('public evidence records both transitions',report['migration_count']==2)
        transferred=store.import_project('local',args.prior.resolve().parent.parent,'Prior migrated project')
        resumed=job(transferred['project']['id'],'slides.migrate',{'expected_sha256':sha(original)},transferred['revision'])
        check('migration of an existing durable revision matches asset migration',(checkout('source-migrated',resumed)/'native/project.dobeslides').read_bytes()==chain)
        buffer=io.BytesIO();Image.new('RGB',(32,24),(32,130,80)).save(buffer,format='PNG')
        insertion={'kind':'picture.insert','path':'/slides/0','expected':sha(revision.encoded(current['current']['document']['slides'][0])),
            'value':{'image':{'name':'Owned proof.png','contentType':'image/png','dataHex':buffer.getvalue().hex()},
                     'transform':{'x':600.0,'y':200.0,'w':128.0,'h':96.0}}}
        revised=job(owner,'slides.edit',{'expected_sha256':sha(chain),'edits':[insertion]},migrated);edited=checkout('edited',revised)
        edited_bytes=(edited/'native/project.dobeslides').read_bytes();edited_profile=project.inspect_bytes(edited_bytes)
        check('new image edit preserves both old engines and all old history',edited_profile['migration_count']==2
              and edited_profile['members']['predecessor.dobeslides']==original
              and edited_profile['manifest']['history'][:-1]==old['manifest']['history'])
        bundled=job(owner,'slides.bundle',{},revised);portable=checkout('portable',bundled)
        check('portable bundle remains exact',(portable/'exports/presentation.dobeslides').read_bytes()==edited_bytes)
        recipient=call('create_project',{'name':'Reopened two-migration project'})['id']
        uploaded=store.import_asset('local',recipient,portable/'exports/presentation.dobeslides')['id']
        imported=job(recipient,'slides.import',{'asset':uploaded,'format':'dobeslides'})
        exported=job(recipient,'slides.export',{'format':'png','slides':[1]},imported);delivered=checkout('delivered',exported)
        with Image.open(delivered/'exports/delivery/slide-001.png') as image:pixel=image.convert('RGB').getpixel((640,240))
        check('reopened chain renders newly authored image and retains full project',pixel==(32,130,80)
              and (delivered/'native/project.dobeslides').read_bytes()==edited_bytes)
        check('prior package and original first revision remain unchanged',args.prior.read_bytes()==original and store.get_revision('local',migrated['id'])==migrated)
        evidence={'passed':True,'checks':checks,'refusals':refusals,'jobs':[{'id':j['id'],'operation':j['operation'],'state':j['state']} for j in jobs],
                  'migration_count':2,'replayed_bytes':current['replayed_bytes'],'chain_bytes':len(chain),'original_sha256':sha(original),
                  'source_runtime_qualified':True,'installed_qualified':False,'remote_actions':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'jobs':len(jobs)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'jobs':jobs},indent=2)+'\n');raise


if __name__=='__main__':main()
