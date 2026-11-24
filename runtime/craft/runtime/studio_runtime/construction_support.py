"""Pinned supporting binaries and bounded offline process calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from .construction_schema import require
from . import offline

DATA=Path(__file__).with_name('construction_data')
PROFILE=offline.PROFILE

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def binary(name):
    require(sys.platform=='darwin','Construction offline process boundary is qualified on macOS only')
    pin=json.loads((DATA/'support.json').read_text())['engines'][name]
    # Discovery never relaxes the exact binary pin. Conventional installation
    # paths replace a developer's version-specific Homebrew Cellar path.
    candidates=[]
    resources=os.environ.get('STUDIO_BUNDLE_RESOURCES')
    if resources:candidates.append(Path(resources)/'support'/name/'bin'/name)
    found=shutil.which(name)
    if found:candidates.append(Path(found))
    if name=='blender':candidates.append(Path('/Applications/Blender.app/Contents/MacOS/Blender'))
    else:candidates.extend(Path(base)/name for base in ('/opt/homebrew/bin','/usr/local/bin'))
    # Retained development manifests remain usable without being rewritten.
    if pin.get('path'):candidates.append(Path(pin['path']))
    for p in candidates:
        if p.is_file() and sha(p)==pin['sha256']:return str(p.resolve())
    raise ValueError('Supporting engine missing or differs from pinned build: '+name)

def run(root, argv, label, timeout=1800):
    root=Path(root).resolve();logs=root/'logs';logs.mkdir(exist_ok=True)
    path=logs/(label+'.log');start=time.monotonic()
    env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','TMPDIR','TZ')}
    env['HOME']=str(root)
    with path.open('wb') as log:
        p=subprocess.Popen(offline.command(argv),cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        try:
            while p.poll() is None:
                require(time.monotonic()-start<timeout and path.stat().st_size<32<<20,'Construction process exceeded time/log budget')
                time.sleep(.1)
            require(p.returncode==0,label+' failed: '+path.read_text(errors='replace')[-1300:])
        finally:
            if p.poll() is None:p.kill();p.wait()
    return {'step':label,'seconds':round(time.monotonic()-start,3),'exit_code':p.returncode,'network':'denied','model_requests':0}

def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
