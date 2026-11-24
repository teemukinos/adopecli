#!/usr/bin/env python3
"""Execute one authored attempt with fixed paths and validated artifact handles.

No scene defaults, provider fallback, artistic decisions, retries or recovery.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from production_file_io import inside, png_bytes, publish_files, json_bytes, image_path_from_hint


def now():
    return datetime.now(timezone.utc).isoformat()


def execute(root, operation, attempt, payload):
    root = Path(root).resolve()
    config = json.loads((root / 'run-config.json').read_text())
    if type(attempt) is not int or attempt not in (1, 2):
        raise ValueError('Attempt must be 1 or 2')
    prefix = f'attempt-{attempt:02d}'
    if operation == 'render':
        if config['route'] != 'adopecli':
            raise ValueError('Render requires the CLI route')
        if os.path.lexists(root / prefix) or os.path.lexists(root / (prefix + '.run')):
            raise FileExistsError('Attempt output already exists')
        document, notes = payload['document'], payload['notes']
        if not isinstance(document, dict) or not isinstance(notes, str):
            raise ValueError('A complete authored document and notes are required')
        publish_files(root, {prefix+'.json':json_bytes(document), prefix+'-notes.md':notes.encode()})
        args = [config['python'], config['render_helper'], '--cli', config['cli'],
                '--state', str(root/'state'), '--spec', str(root/(prefix+'.json')),
                '--output', str(root/prefix)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=7350)
        publish_files(root, {prefix+'-execution.stdout':result.stdout.encode(),
                             prefix+'-execution.stderr':result.stderr.encode()})
        if result.returncode:
            raise RuntimeError('Render failed; preserved execution logs identify the failure')
        record_path = root/(prefix+'.run')/'run.json'
        record = json.loads(record_path.read_text())
        if record['status'] != 'succeeded' or not record.get('revision'):
            raise ValueError('Render did not publish')
        preview = inside(root, record['final_image'])
        _, dimensions = png_bytes(preview)
        native = inside(root, record['native_scene'])
        if not native.is_file():
            raise ValueError('Native scene is missing')
        return {'status':'succeeded','attempt':attempt,'preview_path':str(preview),
                'run_record':str(record_path),'dimensions':dimensions}
    if config['route'] != 'imagegen':
        raise ValueError('Image operations require the imagegen route')
    if operation == 'prepare-image':
        prompt, notes = payload['prompt'], payload['notes']
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(notes, str):
            raise ValueError('An authored prompt and notes are required')
        publish_files(root, {prefix+'-prompt.txt':prompt.encode(), prefix+'-notes.md':notes.encode(),
                             prefix+'-prepared.json':json_bytes({'prepared_at':now()})})
        return {'status':'prepared','attempt':attempt}
    if operation == 'record-image':
        prompt = root/(prefix+'-prompt.txt')
        if not prompt.is_file() or not (root/(prefix+'-prepared.json')).is_file():
            raise ValueError('Prepare the prompt before generation')
        source = image_path_from_hint(payload['output_hint'])
        allowed = (Path.home()/'.codex/generated_images'/config['session_id']).resolve()
        if not (source.is_relative_to(root) or source.is_relative_to(allowed)):
            raise ValueError('Image must belong to this fresh run')
        raw, dimensions = png_bytes(source)
        start, end = payload['started_at'], payload['finished_at']
        elapsed = (datetime.fromisoformat(end.replace('Z','+00:00')) - datetime.fromisoformat(start.replace('Z','+00:00'))).total_seconds()
        if elapsed < 0:
            raise ValueError('Generation timestamps are reversed')
        metadata = {'output_hint':payload['output_hint'],'source_image':str(source),
                    'prompt_path':str(prompt),'started_at':start,'finished_at':end,
                    'elapsed_seconds':elapsed,'actual_dimensions':dimensions}
        publish_files(root, {prefix+'-original.png':raw,prefix+'-metadata.json':json_bytes(metadata)})
        return {'status':'recorded','attempt':attempt,'dimensions':dimensions}
    raise ValueError('Unknown operation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--operation', choices=['render','prepare-image','record-image'], required=True)
    parser.add_argument('--attempt', type=int, required=True)
    parser.add_argument('--payload', required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.root,args.operation,args.attempt,json.loads(args.payload))))


if __name__ == '__main__':
    main()
