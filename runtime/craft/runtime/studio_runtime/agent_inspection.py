"""Deterministic local inspection, with artifacts retained in the existing Store."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def browser_tools():
    node=shutil.which('node') or '/opt/homebrew/bin/node'
    module=Path(os.environ.get('DOBE_PUPPETEER_MODULE',str(Path.home()/'studio/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js')))
    chrome=Path(os.environ.get('DOBE_CHROME_BINARY','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
    if not all(Path(p).is_file() for p in (node,module,chrome)):
        raise ValueError('Local browser inspection requires Node, puppeteer-core and headless Chrome; set DOBE_PUPPETEER_MODULE and DOBE_CHROME_BINARY')
    return [str(node),str(module),str(chrome)]


def rive(store,workspace,project,revision):
    node,module,chrome=browser_tools();started=time.monotonic();reports=[];previews=[]
    with tempfile.TemporaryDirectory(dir=store.staging,prefix='agent-inspection-') as temporary:
        root=Path(temporary);source=root/'source';store.checkout(workspace,revision,source)
        players=sorted(source.glob('construction/components/*/exports/web/index.html'))
        if not players:raise ValueError('No bounded Rive player was published')
        for index,player in enumerate(players):
            output=root/('inspection-'+str(index));log=root/('browser-'+str(index)+'.log')
            env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TZ')};env['HOME']=str(root)
            with log.open('wb') as stream:
                result=subprocess.run([node,str(Path(__file__).with_name('agent_browser.mjs')),str(player.parent),str(output),module,chrome],
                                      env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=60)
            report=json.loads((output/'report.json').read_text()) if (output/'report.json').is_file() else {'passed':False,'error':'Browser did not produce an inspection report','exit_code':result.returncode}
            report['component']=player.relative_to(source).parts[2];reports.append(report)
            store.import_asset(workspace,project,log,'inspection-'+str(index)+'.log')
            for path in sorted(output.glob('*.png')):
                asset=store.import_asset(workspace,project,path,'inspection-'+str(index)+'-'+path.name)
                previews.append({'asset':asset['id'],'project':project,'path':report['component']+'/'+path.name,'sha256':asset['sha256']})
    return {'revision':revision,'passed':all(r['passed'] for r in reports),'reports':reports,'previews':previews,'elapsed_seconds':time.monotonic()-started,'model_requests':0}


INSPECTORS={'rive':rive}


def inspect(store,workspace,project,revision,descriptor):
    name=descriptor.get('inspector')
    return INSPECTORS[name](store,workspace,project,revision) if name else None
