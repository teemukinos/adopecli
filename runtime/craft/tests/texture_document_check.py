#!/usr/bin/env python3
"""Local Texture compound inventory and preservation checks; no engine launch."""
import argparse
import copy
import io
import json
from pathlib import Path
import sys
import time
import zipfile
from unittest.mock import patch
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import texture_document as document
from texture_structure_check import project


def packed(members):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,value in members.items():z.writestr(name,value)
    return out.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--native',type=Path,action='append',default=[]);parser.add_argument('--evidence',type=Path);args=parser.parse_args()
    checks=[];started=time.monotonic();image=io.BytesIO();Image.new('RGB',(2,2),'red').save(image,format='PNG');png=image.getvalue()
    source={'project.json':json.dumps(project()).encode(),'thumbnail.png':png}
    def check(label,valid):assert valid,label;checks.append(label)
    def refused(label,action):
        try:action()
        except ValueError:checks.append(label)
        else:raise AssertionError(label)
    before=document.inspect_bytes(packed(source))
    check('compound snapshot retains original source and thumbnail',before['members']==source and before['thumbnail']['format']=='PNG' and before['engine_admission_complete'] is False)
    check('equal project and payload inventory passes',document.check_preservation(before,document.inspect_bytes(packed(source)))['members']==2)
    with patch.object(document.texture_images, 'MAX_TOTAL_TEXELS', 4):
        check('thumbnail counts toward exact aggregate image limit',document.inspect_bytes(packed(source))['image_texels']==4)
        refused('resource plus thumbnail exceeds shared image budget',lambda:document.inspect_bytes(packed({**source,'resources/extra.png':png})))
    for name in ('unknown/future-data','mesh.bin','cage/a/b.obj','highpoly/.hidden.obj','highpoly/a b.obj'):
        refused('unqualified member '+name,lambda name=name:document.inspect_bytes(packed({**source,name:b'data'})))
    refused('primary mesh conflicts with built-in',lambda:document.inspect_bytes(packed({**source,'mesh.obj':b'data'})))
    refused('multiple cages',lambda:document.inspect_bytes(packed({**source,'cage/a.obj':b'data','cage/b.obj':b'data'})))
    refused('empty cage',lambda:document.inspect_bytes(packed({**source,'cage/a.obj':b''})))
    p=project();p['mesh']='mesh.obj';data={**source,'project.json':json.dumps(p).encode(),'mesh.obj':b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'}
    check('mesh body is inventoried but not authorized',document.inspect_bytes(packed(data))['mesh_members']==['mesh.obj'] and not document.inspect_bytes(packed(data))['engine_admission_complete'])
    refused('multiple primary meshes',lambda:document.inspect_bytes(packed({**data,'mesh.glb':b'data'})))
    refused('missing primary mesh',lambda:document.inspect_bytes(packed({**source,'project.json':json.dumps(p).encode()})))
    refused('empty primary mesh',lambda:document.inspect_bytes(packed({**data,'mesh.obj':b''})))
    p=project();p['mesh']='builtin:unknown'
    refused('unknown builtin',lambda:document.inspect_bytes(packed({**source,'project.json':json.dumps(p).encode()})))
    p=project();p['mesh_path']='/nonexistent/provenance/model.obj';p['mesh_file']='model.obj'
    check('inert original mesh path retained without dereference',document.inspect_bytes(packed({**source,'project.json':json.dumps(p).encode()}))['structure']['project']==p)
    p['mesh_path']='bad\x00path'
    refused('malformed mesh provenance',lambda:document.inspect_bytes(packed({**source,'project.json':json.dumps(p).encode()})))
    jpg=io.BytesIO();Image.new('RGB',(2,2),'red').save(jpg,format='JPEG')
    refused('thumbnail extension/content mismatch',lambda:document.inspect_bytes(packed({**source,'thumbnail.png':jpg.getvalue()})))
    dropped=document.inspect_bytes(packed({'project.json':source['project.json']}))
    refused('native thumbnail loss detected',lambda:document.check_preservation(before,dropped))
    changed=io.BytesIO();Image.new('RGB',(2,2),'blue').save(changed,format='PNG')
    after=document.inspect_bytes(packed({**source,'thumbnail.png':changed.getvalue()}))
    refused('unapproved thumbnail rewrite detected',lambda:document.check_preservation(before,after))
    p=project();p['name']='Revision';after=document.inspect_bytes(packed({**source,'project.json':json.dumps(p).encode()}))
    refused('unapproved project field edit',lambda:document.check_preservation(before,after))
    check('independently predicted edit accepted',document.check_preservation(before,after,expected_project=p)['embedded_bytes_preserved'])
    for value in (1, 1.0):
        # Exercise the independent preservation comparison as well as the
        # compound reader, which now refuses this type change before execution.
        after=copy.deepcopy(before);after['structure']['project']['layers']['1']['visible']=value
        refused('scalar type change cannot pass preservation '+repr(value),lambda:document.check_preservation(before,after))
    added=document.inspect_bytes(packed({**source,'resources/extra.png':png}))
    refused('introduced embedded member detected',lambda:document.check_preservation(before,added))
    native=[]
    for path in args.native:
        original=path.read_bytes();report=document.read_native(path);check('actual native inventory '+path.name,path.read_bytes()==original and report['source_bytes']==original)
        native.append({'path':str(path),'sha256':report['source_sha256'],'members':len(report['members']),'thumbnail':report['thumbnail'] is not None})
    report={'passed':True,'checks':len(checks),'cases':checks,'native_archives':native,'seconds':round(time.monotonic()-started,4),'engine_admission_complete':False,'goal_complete':False}
    if args.evidence:args.evidence.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','checks','seconds')}))


if __name__=='__main__':main()
