"""Qualify packaged crop inspection against an existing immutable revision.

Reads the source Store without migration or writes. Does not call a model, render,
change native artifacts, or use these prior creative answers in a new benchmark.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
from PIL import Image


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--run',required=True)
    parser.add_argument('--artifact',required=True)
    parser.add_argument('--box',action='append',required=True,help='left,top,width,height')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();package=args.package.resolve(strict=True);root=args.state.resolve(strict=True)
    sys.path.insert(0,str(package/'lib/dobe/runtime'))
    from studio_runtime import agent_evidence
    args.output.mkdir(parents=True,exist_ok=False)
    with sqlite3.connect((root/'studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        run=db.execute('SELECT workspace,context,state FROM agent_runs WHERE id=?',(args.run,)).fetchone()
        context=json.loads(run['context']);revision=context['revision'];workspace=run['workspace']

        class ReadOnlyStore:
            blobs=root/'blobs'
            def get_revision(self,workspace,revision):
                row=db.execute('SELECT manifest FROM revisions WHERE workspace=? AND id=?',(workspace,revision)).fetchone()
                if row is None:raise ValueError('Revision is not published in this workspace')
                return json.loads(row[0])
            def get_asset(self,workspace,project,asset):
                row=db.execute('SELECT * FROM assets WHERE workspace=? AND project=? AND id=?',(workspace,project,asset)).fetchone()
                if row is None:raise ValueError('Inspection asset is not published in this project')
                return dict(row)

        store=ReadOnlyStore();manifest=store.get_revision(workspace,revision)
        # Check every native/source artifact before and after deriving previews.
        hashes={e['sha256'] for e in manifest['files']}
        before={sha:digest(store.blobs/sha) for sha in hashes}
        assert all(sha==value for sha,value in before.items())
        decision={'action':'inspect','revision':revision,'crops':[
            {'path':args.artifact,'box':[int(v) for v in box.split(',')]} for box in args.box]}
        selection=agent_evidence.inspection_selection(store,workspace,context,decision)
        observed=agent_evidence.collect(store,workspace,revision,inspection=context.get('inspection'),crops=selection['crops'])
        original=next(e for e in manifest['files'] if e['path']==args.artifact)
        with Image.open(io.BytesIO(agent_evidence.blob(store,original))) as source:
            for index,(image,region) in enumerate(zip(observed['images'],selection['crops']['regions'])):
                raw=base64.b64decode(image['content']['image_url'].split(',',1)[1]);left,top,width,height=region['box']
                with Image.open(io.BytesIO(raw)) as crop:
                    assert crop.size==(width,height)
                    assert crop.tobytes()==source.crop((left,top,left+width,top+height)).tobytes()
                (args.output/f'crop-{index}.png').write_bytes(raw)
        after={sha:digest(store.blobs/sha) for sha in hashes};assert before==after
        repeated=agent_evidence.collect(store,workspace,revision,inspection=context.get('inspection'),crops=json.loads(json.dumps(selection['crops'])))
        assert repeated['images']==observed['images']
        report={'package_manifest_sha256':digest(package/'lib/dobe/bundle.json'),'source_run':args.run,
                'source_run_state':run['state'],'revision':revision,'artifact_count_verified':len(hashes),
                'all_original_hashes_unchanged':True,'decoded_crop_pixels_equal_original_region':True,
                'serialized_selection_reproduces_identical_images':True,'selection':selection,
                'crop_evidence':observed['technical_evidence']['detail_crops'],
                'native_cold_reopen':manifest.get('validation',{}).get('native_cold_reopen'),
                'provider_requests':0,'render_jobs':0,
                'scope':'Inspection repair qualification only; prior artwork is not a fresh creative benchmark or an acceptance pass.'}
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'passed':True,'regions':len(observed['images']),'provider_requests':0}))


if __name__=='__main__':main()
