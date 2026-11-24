#!/usr/bin/env python3
"""Run an immutable predecessor worker against a new Slides request contract."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('resources','previous','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--expect',choices=('held','failed'),default='held');args=parser.parse_args()
    resources=args.resources.resolve();previous=args.previous.resolve();out=args.output.resolve();out.mkdir()
    sys.path.insert(0,str(resources/'runtime'))
    from studio_runtime import slides,slides_revision as revision,capabilities
    from studio_runtime.store import Store,Conflict
    from studio_runtime.worker import Worker
    os.environ['PATH']='/usr/bin:/bin';store=Store(out/'state');checks=[]
    recipe={'recipe':'production_proposal','version':1,'title':'Versioned work','sections':[{'heading':'Retained work','paragraphs':['Exact image ownership.']} ]}
    model=slides.recipes.compile_recipe(recipe)['document'];source=revision.encoded(model)
    image=io.BytesIO();Image.new('RGB',(32,24),(20,140,90)).save(image,format='PNG')
    edit={'kind':'picture.insert','path':'/slides/0','expected':hashlib.sha256(revision.encoded(model['slides'][0])).hexdigest(),
          'value':{'image':{'name':'Owned proof.png','contentType':'image/png','dataHex':image.getvalue().hex()},
                   'transform':{'x':600.0,'y':200.0,'w':128.0,'h':96.0}}}
    model=revision.revise_bytes(source,hashlib.sha256(source).hexdigest(),[edit])['document'];params={'document':model}
    slides.validate('slides.create',params,None)
    owner=store.create_project('local','Queued image contract')['id'];job=store.submit('local',owner,'slides.create',params,'owned-image')
    assert job['operation']=='slides.create' and job['request']['operation']=='slides.create'
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.worker import Worker;store=Store(sys.argv[2]);print(json.dumps({'ran':Worker(store).run_one(),'job':store.get_job('local',sys.argv[3])}))"
    response=subprocess.run([str(previous/'lib/dobe/python/bin/python3'),'-I','-B','-c',code,str(previous/'lib/dobe/runtime'),str(out/'state'),job['id']],
                            capture_output=True,text=True,timeout=60,env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin'})
    assert response.returncode==0,response.stderr;old=json.loads(response.stdout);actual=store.get_job('local',job['id'])
    assert store.get_project('local',owner)['head'] is None
    if args.expect=='failed':
        assert old['ran'] and actual['state']=='failed' and actual['attempt']==1,actual
        (out/'evidence.json').write_text(json.dumps({'reproduced':True,'older_worker_consumed_new_contract':True,'job':actual,
                                                   'previous':str(previous),'remote_actions':False},indent=2)+'\n')
        print(json.dumps({'reproduced':True,'state':actual['state'],'error':actual['error']}));return
    assert not old['ran'] and actual['state']=='queued' and actual['attempt']==0,old
    checks.append('actual dev51 worker leaves new image contract queued without an attempt or publication')
    assert store.submit('local',owner,'slides.create',params,'owned-image')['id']==job['id']
    with sqlite3.connect((out/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        dispatch=db.execute('SELECT operation FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]
    assert dispatch!='slides.create' and dispatch.startswith('slides.create@')
    assert dispatch not in capabilities.OPERATIONS and actual['operation']=='slides.create'
    checks.append('public operation and idempotency remain stable while persisted dispatch requires the qualified worker')
    assert Worker(store).run_one();completed=store.get_job('local',job['id']);assert completed['state']=='succeeded' and completed['attempt']==1,completed
    state=store.get_revision('local',completed['result_revision']);folder=out/'completed';store.checkout('local',state['id'],folder)
    assert json.loads((folder/'native/document.json').read_bytes())==model
    checks.append('current worker completes the same persisted job with exact image-bearing model')
    owner2=store.create_project('local','Explicit retry')['id'];retry=store.submit('local',owner2,'slides.create',params,'retry-image');store.cancel('local',retry['id'])
    store.retry('local',retry['id'],'explicit-retry',capabilities.RETRY_SAFE)
    assert Worker(store).run_one();retried=store.get_job('local',retry['id']);assert retried['state']=='succeeded',retried
    checks.append('qualified dispatch supports explicit safe retry with unchanged public operation')
    owner3=store.create_project('local','Unknown future contract')['id'];future=store.submit('local',owner3,'slides.create',params,'future-image')
    with store.transaction() as db:db.execute('UPDATE jobs SET operation=? WHERE id=?',('slides.create@unqualified-future',future['id']))
    assert not Worker(store).run_one()
    assert store.get_job('local',future['id'])['state']=='queued' and store.get_job('local',future['id'])['attempt']==0
    store.cancel('local',future['id'])
    try:store.retry('local',future['id'],'future-retry',capabilities.RETRY_SAFE)
    except Conflict:pass
    else:raise AssertionError('unqualified future contract admitted for retry')
    checks.append('public operation alone cannot authorize claim or retry of an unknown persisted contract')
    owner4=store.create_project('local','Legacy queued document')['id']
    legacy_code="import sys,json;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;print(json.dumps(Store(sys.argv[2]).submit('local',sys.argv[3],'slides.create',{'document':json.loads(sys.argv[4])},'legacy-text')))"
    response=subprocess.run([str(previous/'lib/dobe/python/bin/python3'),'-I','-B','-c',legacy_code,
                            str(previous/'lib/dobe/runtime'),str(out/'state'),owner4,source.decode()],
                           capture_output=True,text=True,timeout=60,env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin'})
    assert response.returncode==0,response.stderr;legacy=json.loads(response.stdout)
    with sqlite3.connect((out/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('SELECT operation FROM jobs WHERE id=?',(legacy['id'],)).fetchone()[0]=='slides.create'
    assert Worker(store).run_one();legacy=store.get_job('local',legacy['id']);assert legacy['state']=='succeeded',legacy
    checks.append('current worker completes a real unqualified text request submitted by the predecessor store')
    unrelated=store.submit('local',owner3,'vector.create',{},'unrelated-operation')
    with sqlite3.connect((out/'state/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('SELECT operation FROM jobs WHERE id=?',(unrelated['id'],)).fetchone()[0]=='vector.create'
    assert store.claim('local','slides-only',('slides.create',)) is None
    store.cancel('local',unrelated['id'])
    checks.append('unrelated operation keeps its original dispatch key and cannot be claimed by a Slides-only worker')
    (out/'evidence.json').write_text(json.dumps({'passed':True,'checks':checks,'old_worker_claimed':False,'dispatch':dispatch,
        'completed_job':completed,'retried_job':retried,'legacy_job':legacy,'unknown_contract_job':future['id'],
        'unrelated_job':unrelated['id'],'remote_actions':False},indent=2)+'\n')
    print(json.dumps({'passed':True,'checks':len(checks),'old_worker_claimed':False}))


if __name__=='__main__':main()
