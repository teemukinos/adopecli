#!/usr/bin/env python3
"""Qualify strict Write PNG/PDF delivery with real engines and durable jobs."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('resources', 'project', 'embedded', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True)
    runtime = args.resources.resolve()/'runtime'; sys.path.insert(0, str(runtime))
    from studio_runtime import write_binding, write_engine, write_exports as delivery, write_project as project
    from studio_runtime.store import Store
    from studio_runtime.worker import Worker
    checks = []; refusals = []; reports = []; jobs = []; native_calls = 0
    original = args.project.read_bytes(); checked = project.inspect_bytes(original); source = checked['members']['document.json']
    trusted = write_binding.resolve(); state = out/'state'; store = Store(state)
    substitutions = [{'requested':name, 'actual':'Source Sans 3'} for name in ('Aptos', 'Aptos Display')]
    code = "import sys;sys.path.insert(0,sys.argv[1]);from studio_runtime.store import Store;from studio_runtime.mcp import serve;serve(Store(sys.argv[2]),product='dobe')"

    def check(label, condition=True):
        if not condition: raise AssertionError(label)
        checks.append(label)

    def refused(label, operation, expected):
        try: operation()
        except ValueError as error:
            check(label+' fails at intended boundary', expected in str(error)); refusals.append({'case': label, 'error': str(error)})
        else: raise AssertionError('accepted '+label)

    def export(name, data, params):
        nonlocal native_calls
        folder = out/name; folder.mkdir(); path = folder/'source.json'; path.write_bytes(data)
        native = write_engine.Engine(root=folder, **trusted)
        if name != 'unapproved-fonts': params = {'font_substitutions':substitutions, **params}
        try: report = delivery.deliver(native, path, data, folder/'delivery', params)
        finally: native_calls += native.calls
        reports.append({'case': name, 'report': report})
        check(name+' keeps exact editable source', path.read_bytes() == data)
        check(name+' reports decoder/glyph evidence without artistic or source-fidelity claim', report['strict_native_export'] and report['complete_output_decode']
              and report['actual_font_identity_verified'] and not report['visual_approval'] and not report['source_format_fidelity_qualified'])
        return report

    def tool(name, params):
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(runtime), str(state)],
            input=(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'dope_'+name,'arguments':params}})+'\n').encode(), capture_output=True, timeout=30)
        if result.returncode: raise AssertionError(result.stderr.decode()[:2000])
        response = json.loads(result.stdout)['result']
        if response.get('isError'): raise ValueError(response['content'][0]['text'])
        return json.loads(response['content'][0]['text'])

    def job(identity, operation, params, key, previous=None, success=True):
        request = {'project': identity, 'operation': operation, 'parameters': params, 'idempotency_key': key}
        if previous: request['source_revision'] = previous['id']
        submitted = tool('submit_job', request); Worker(store).run_one(); actual = tool('get_job', {'job': submitted['id']}); jobs.append(actual)
        check(key+' durable outcome '+str(actual.get('error')), actual['state'] == ('succeeded' if success else 'failed'))
        if not success:
            check(key+' no failed artifact publication', actual['result_revision'] is None and store.get_project('local', identity)['head'] == previous['id'])
            return actual
        return tool('get_revision', {'revision': actual['result_revision']})

    try:
        one = export('png', source, {'format':'png'})
        check('A4 PNG has predicted independent dimensions', [(p['width'],p['height']) for p in one['outputs']] == [(596,842)])
        check('cold PNG bytes are identical', all(p['cold_bytes_equal'] for p in one['outputs']))
        check('actual substitutions are explicit and exact', one['accepted_font_substitutions'] == substitutions)
        refused('unapproved fallback', lambda: export('unapproved-fonts', source, {'format':'png'}), 'font substitutions differ from explicit request')
        check('unapproved fallback leaves no delivered page', not (out/'unapproved-fonts/delivery').exists())
        two = export('png-double', source, {'format':'png','scale':2})
        check('scale is applied without native downsampling', [(p['width'],p['height']) for p in two['outputs']] == [(1191,1684)])
        pdf_report = export('pdf', source, {'format':'pdf'})
        check('PDF has two independent cold reads and rendered pixel comparisons', len(pdf_report['independent_pdf_checks']) == 2
              and pdf_report['outputs'][0]['independent_cold_state_equal'])
        from studio_runtime import pdf
        original_path = os.environ.get('PATH')
        os.environ['PATH'] = str(write_binding.resolve_pdf()['executable'].parent)+':/usr/bin:/bin'
        try:
            with pdf.Engine(out) as reader:
                document, admitted = reader.open(out/'pdf/delivery/document.pdf')
                snapshot = pdf.snapshot(reader, document)
                check('existing PDF adapter default executable route still cold-opens exported PDF', len(admitted['pages']) == 1
                      and 'Ceramic production brief' in snapshot['text'][0]['text'])
        finally:
            if original_path is None: os.environ.pop('PATH', None)
            else: os.environ['PATH'] = original_path
        embedded = args.embedded.read_bytes(); embedded_report = export('embedded', embedded, {'format':'png'})
        faces = json.loads((out/'embedded/delivery/glyphs.json').read_bytes())['faces']
        check('actual embedded alias survives strict delivery', any(face['family'] == 'Dobe Original Embedded Fixture' for face in faces))
        # Force a section-independent second page while retaining all existing
        # comments, artwork and tables. Page ordering remains the caller's order.
        multiple = copy.deepcopy(checked['current']['document'])
        paragraph = copy.deepcopy(multiple['body'][1]); paragraph['props']['pageBreakBefore'] = True
        paragraph['text'] = 'Second page proof'; paragraph['runs'] = [{'len':17}]; multiple['body'].append(paragraph)
        multiple_bytes = (json.dumps(multiple)+'\n').encode()
        multi = export('ordered-pages', multiple_bytes, {'format':'png','pages':[2,1]})
        check('page selection preserves requested ordering', multi['page_count'] == 2 and [p['page'] for p in multi['outputs']] == [2,1])
        export('multipage-pdf', multiple_bytes, {'format':'pdf'})

        for label, params in [('scale clamp', {'format':'png','scale':8}), ('zero scale', {'format':'png','scale':0}),
                              ('Boolean page', {'format':'png','pages':[True]}), ('duplicate pages', {'format':'png','pages':[1,1]}),
                              ('PDF raster options', {'format':'pdf','scale':1}), ('arbitrary path', {'format':'png','path':'/tmp/output'})]:
            refused(label, lambda p=params: delivery.validate(p), 'export')
        refused('missing page', lambda: export('missing-page', source, {'format':'png','pages':[2]}), 'missing page')
        check('missing page leaves no partial delivery', not (out/'missing-page/delivery').exists())
        refused('pixel budget', lambda: delivery.geometry([[1584,1584]], [1], 4), 'pixel budget')
        refuse_root = out/'refusals'; refuse_root.mkdir(); path = refuse_root/'source.json'; path.write_bytes(source)
        native = write_engine.Engine(root=refuse_root, **trusted)
        destination = refuse_root/'existing'; destination.mkdir(); sentinel = destination/'owner'; sentinel.write_bytes(b'original')
        refused('existing destination', lambda: delivery.deliver(native, path, source, destination, {'format':'png'}), 'new disposable destination')
        check('existing owner files unchanged', sentinel.read_bytes() == b'original')
        refused('stale model bytes', lambda: delivery.deliver(native, path, source+b' ', refuse_root/'stale', {'format':'png'}), 'differs from complete predicted model')
        packet = native._run('glyphs', path, limit=64 << 20); damaged = bytearray(packet); damaged[-1] ^= 1
        refused('unowned font payload', lambda: delivery.owned_fonts(bytes(damaged), project.native_profile(source)), 'outside pinned builtins')
        native_calls += native.calls
        identity = tool('create_project', {'name':'Write page delivery'})['id']
        asset_path = out/'import.dobewrite'; asset_path.write_bytes(original)
        asset = store.import_asset('local', identity, asset_path)['id']
        initial = job(identity, 'write.import', {'asset':asset,'format':'dobewrite'}, 'import')
        raster = job(identity, 'write.export', {'format':'png','pages':[1],'scale':1,'font_substitutions':substitutions}, 'png', initial)
        vector = job(identity, 'write.export', {'format':'pdf','font_substitutions':substitutions}, 'pdf', raster)
        delivered = out/'public-pdf'; store.checkout('local', vector['id'], delivered)
        check('public PDF job publishes delivery and original together', (delivered/'exports/delivery/document.pdf').is_file()
              and (delivered/'native/project.dobewrite').read_bytes() == original and vector['validation']['render_qualified'])
        check('previous raster is not mislabeled as latest PDF delivery', not any(f['path'].endswith('page-001.png') for f in vector['files']))
        check('native diagnostics and complete inventory accompany public delivery', (delivered/'exports/delivery/glyphs.json').is_file()
              and (delivered/'exports/delivery/pictures.json').is_file())
        broken = copy.deepcopy(checked['current']['document']); broken['body'][1]['text'] = '\U0010fffd'; broken['body'][1]['runs'] = [{'len':4}]
        broken_path = out/'missing-glyph.json'; broken_path.write_text(json.dumps(broken))
        bad_id = tool('create_project', {'name':'Missing glyph'})['id']; bad_asset = store.import_asset('local', bad_id, broken_path)['id']
        bad_initial = job(bad_id, 'write.import', {'asset':bad_asset,'format':'json'}, 'missing-import')
        job(bad_id, 'write.export', {'format':'png'}, 'strict-refusal', bad_initial, success=False)
        check('all owner inputs remain unchanged', args.project.read_bytes() == original and args.embedded.read_bytes() == embedded)
        evidence = {'passed':True,'checks':checks,'refusals':refusals,'native_calls':native_calls,
                    'durable_jobs':len(jobs),'succeeded':sum(j['state']=='succeeded' for j in jobs),'remote_actions':False,
                    'installed_qualification':False,'source_format_fidelity_qualified':False,'visual_approval':False}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps({'passed':len(checks),'refusals':len(refusals),'native_calls':native_calls,'durable_jobs':len(jobs)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals},indent=2)+'\n'); raise
    finally:
        (out/'reports.json').write_text(json.dumps(reports,indent=2)+'\n'); (out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')


if __name__ == '__main__': main()
