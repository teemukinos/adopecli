"""Qualify all six typed Write operations through a sealed package's public CLI.

Run with bundled Python: write_acceptance.py PACKAGE NEW_OUTPUT [--resume].
Original document recipes and refusal inputs are generated locally. No network, editor windows or service installation. Completed jobs are
reused on resume; admitted nonterminal work is never replayed automatically.
"""
import argparse
import base64
import io
import copy
import fcntl
import sys
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
package = args.package.resolve(strict=True)
sys.path.insert(0, str(package / 'lib/dobe/runtime'))
from studio_runtime import write_recipes
out = args.output.absolute()
out.mkdir(parents=True, exist_ok=args.resume, mode=0o700)
lock = (out / 'fixture.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
for folder in ('home', 'sources'):
    (out / folder).mkdir(exist_ok=args.resume, mode=0o700)
cli = package / 'bin/a-dope-cli'
state = out / 'state'
env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
logs = json.loads((out / 'commands.json').read_text()) if args.resume else []
jobs = json.loads((out / 'jobs.json').read_text()) if args.resume and (out / 'jobs.json').exists() else []
cases = []


def save(name, value):
    (out / name).write_text(json.dumps(value, indent=2) + '\n')


def check(value, label):
    assert value, label
    cases.append(label)
    save('cases.json', cases)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def immutable(path, data):
    if path.exists():
        assert path.read_bytes() == data, 'fixture input changed: ' + str(path)
    else:
        path.write_bytes(data)


def run(label, arguments, expected=0, fresh=False):
    arguments = list(map(str, arguments))
    files = {p: digest(p) for p in arguments if Path(p).is_file()}
    prior = next((r for r in logs if r['label'] == label), None)
    if prior and not fresh:
        assert (prior['args'], prior['files'], prior['exit']) == (arguments, files, expected), label
        return json.loads(prior['stdout']) if prior['stdout'].strip() else None
    start = time.monotonic()
    process = subprocess.run(arguments, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    logs.append({'label': label, 'args': arguments, 'files': files, 'exit': process.returncode,
                 'seconds': time.monotonic() - start, 'stdout': process.stdout, 'stderr': process.stderr})
    save('commands.json', logs)
    assert process.returncode == expected, (label, process.returncode, process.stderr)
    return json.loads(process.stdout) if process.stdout.strip() else None


def call(label, *arguments, fresh=False):
    return run(label, [cli, '--state', state, *arguments], fresh=fresh)


def verify_checkout(directory):
    receipt = json.loads((directory / 'project.json').read_text())
    for item in receipt['files']:
        p = directory / item['path']
        assert p.stat().st_size == item['bytes'] and digest(p) == item['sha256'], item['path']
    return receipt


def job(label, project, operation, parameters, source=None, success=True):
    request = out / (label + '-request.json')
    immutable(request, (json.dumps(parameters, sort_keys=True) + '\n').encode())
    old = next((j for j in jobs if j['label'] == label), None)
    if old:
        assert (old['project'], old['operation'], old['parameters'], old['source']) == (project, operation, parameters, source), label
    arguments = ['submit', project, operation, '--parameters', request, '--key', label]
    if source:
        arguments += ['--source', source]
    submitted = call(label + ' submit', *arguments)
    if not old:
        old = {'label': label, 'project': project, 'operation': operation, 'parameters': parameters,
               'source': source, 'stateDirectory': str(state), 'id': submitted['id']}
        jobs.append(old)
        save('jobs.json', jobs)
    if 'result' not in old:
        observed = call(label + ' admitted state', 'job', submitted['id'], fresh=True)
        if observed['state'] == 'queued':
            call(label + ' worker', 'worker', '--once')
        elif observed['state'] not in ('succeeded', 'failed'):
            raise RuntimeError('Reconcile admitted job before resuming: ' + json.dumps(observed))
        old['result'] = call(label + ' result', 'job', submitted['id'], fresh=True)
        save('jobs.json', jobs)
    result = old['result']
    assert result['state'] == ('succeeded' if success else 'failed'), result
    if not success:
        check(result.get('result_revision') is None, label + ' publishes no revision')
        return result
    destination = out / label
    call(label + ' checkout', 'checkout', result['result_revision'], destination)
    receipt = verify_checkout(destination)
    v = receipt['validation']
    check(v['native_cold_reopen'] and v['native_model_equal'] and v['initial_source_preserved']
          and v['source_backed'] and not v['visual_approval'] and not v['source_format_fidelity_qualified'],
          label + ' preserves complete editable model and source through cold reopening')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def read(directory, relative):
    return json.loads((directory / relative).read_text())


def model(directory):
    return read(directory, 'native/document.json')


def locate(document, path):
    current = document
    for part in path.split('/')[1:]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def text_edit(document, path, old, new):
    text = locate(document, path)['text'].encode()
    start = text.index(old.encode())
    return {'kind': 'text.replace', 'path': path, 'start': start, 'end': start + len(old.encode()),
            'expected': old, 'value': new}


def edit_request(directory, edits):
    return {'expected_sha256': digest(directory / 'native/project.dobewrite'), 'edits': edits}


def pixels(directory):
    result = []
    for path in sorted((directory / 'exports/delivery').glob('page-*.png')):
        with Image.open(path) as image:
            result.append({'file': path.name, 'size': list(image.size),
                           'sha256': hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()})
    return result


def stable_source(before, after, recipe=True):
    for path in ('native/original.json', 'native/baseline.json'):
        assert (before / path).read_bytes() == (after / path).read_bytes(), path
    if recipe:
        for path in ('recipes/origin-write-operation.json', 'recipes/write-production.json'):
            assert (before / path).read_bytes() == (after / path).read_bytes(), path


def delivery(directory, count, kind, pages=None):
    report = read(directory, 'exports/delivery/delivery.json')
    check(report['format'] == kind and report['page_count'] == count
          and report['selected_pages'] == (pages or list(range(1, count + 1)))
          and report['actual_font_identity_verified'] and report['strict_native_export']
          and report['complete_output_decode'], directory.name + ' verifies page geometry, actual fonts and complete output decode')
    if kind == 'pdf':
        check(len(report['independent_pdf_checks']) == 2
              and all(all(p['normalized_character_inventory_equal'] for p in run['text_checks'])
                      for run in report['independent_pdf_checks'])
              and report['independent_pdf_checks'][0]['rgba8_sha256'] == report['independent_pdf_checks'][1]['rgba8_sha256'],
              directory.name + ' corrected PDF dependency preserves text inventory and cold pixels')
    else:
        check(all(p['cold_bytes_equal'] for p in report['outputs']), directory.name + ' PNG cold exports match exactly')
    return report


verification = run('verify payload before', [package / 'bin/a-dope-guard', 'verify'], fresh=True)
check(verification['verified'], 'complete sealed package verifies before Write acceptance')
save('verification-before.json', verification)
creation = {
    'recipe': 'production_brief', 'version': 1, 'title': 'The quiet object.',
    'subtitle': 'ATELIER / 02    Material, light and delivery',
    'author': 'A dope CLI',
    'sections': [
        {'heading': '01 / Direction', 'paragraphs': [
            'A ceramic vessel, warm light and room to breathe. Keep the silhouette clear and the surface tactile.',
            'Use warm porcelain with a matte finish. Preserve the camera, framing and scale through every material revision.']},
        {'heading': '02 / Production notes', 'paragraphs': [
            'Review the material before approving the lighting. Keep an editable scene and a reproducible lighting recipe.',
            'Deliver the approved image with its source. The next revision must change one decision without rebuilding the work.']}],
    'deliverables': [
        {'asset': 'Product photograph', 'editable_source': 'Scene, camera and material', 'delivery': 'PNG + editable scene'},
        {'asset': 'Material revision', 'editable_source': 'Same scene and framing', 'delivery': 'PNG + revision recipe'},
        {'asset': 'Production brief', 'editable_source': 'Native editable document', 'delivery': 'PDF + portable project'}],
    'controls': {'paper': 'a4', 'margin': 54, 'body_size': 11, 'accent': '#123E49', 'heading_face': 'editorial'}}
project = call('brief project', 'create-project', 'ATELIER / 02 editable production brief')['id']
r0, d0 = job('original', project, 'write.create', creation)
production = read(d0, 'recipes/write-production.json')
selectors = production['selectors']
original = model(d0)
check(original == write_recipes.compile_recipe(creation)[0], 'complete authored model equals deterministic recipe output')
check(locate(original, selectors['title'])['text'] == creation['title']
      and all(locate(original, s['heading'])['text'] == c['heading']
              and [locate(original, p)['text'] for p in s['paragraphs']] == c['paragraphs']
              for s, c in zip(selectors['sections'], creation['sections'])), 'all requested title and section text remains exact')
r1, d1 = job('original-png', project, 'write.export', {'format': 'png'}, r0)
report = delivery(d1, 1, 'png')
check(report['accepted_font_substitutions'] == [] and pixels(d1)[0]['size'] == [596, 842], 'original editorial brief fits A4 with pinned fonts and no substitution')
# Exercise all four declared typed-edit kinds in one atomic revision.
body_path = selectors['sections'][0]['paragraphs'][1]
heading_path = selectors['sections'][1]['heading']
title_path = selectors['title']
title = locate(original, title_path)['text']
edits = [text_edit(original, body_path, 'warm porcelain', 'glazed porcelain'),
         {'kind': 'text.format', 'path': title_path, 'start': 0, 'end': len(title.encode()), 'expected': title,
          'set': {'color': {'Rgb': [164, 74, 50]}}, 'unset': []},
         {'kind': 'paragraph.properties', 'path': heading_path, 'expected': locate(original, heading_path)['props'],
          'set': {'pageBreakBefore': True}, 'unset': []},
         {'kind': 'section.properties', 'path': '/lastSection', 'expected': original['lastSection'],
          'set': {'marginTop': 60.0}, 'unset': []}]
r2, d2 = job('paginated', project, 'write.edit', edit_request(d1, edits), r1)
predicted = copy.deepcopy(original)
paragraph = locate(predicted, body_path)
paragraph['text'] = paragraph['text'].replace('warm porcelain', 'glazed porcelain')
paragraph['runs'][0]['len'] = len(paragraph['text'].encode())
locate(predicted, title_path)['runs'][0]['props'] = {'color': {'Rgb': [164, 74, 50]}}
locate(predicted, heading_path)['props']['pageBreakBefore'] = True
predicted['lastSection']['marginTop'] = 60.0
check(model(d2) == predicted, 'all four typed edits change only independently predicted model fields')
stable_source(d0, d2)
check(True, 'pagination and formatting retain complete baseline, original and production recipe')
r3, d3 = job('paginated-png', project, 'write.export', {'format': 'png'}, r2)
delivery(d3, 2, 'png')
baseline_pixels = pixels(d3)
check(len(baseline_pixels) == 2 and all(p['size'] == [596, 842] for p in baseline_pixels), 'explicit page break produces two complete A4 pages')
r4, d4 = job('paginated-pdf', project, 'write.export', {'format': 'pdf'}, r3)
delivery(d4, 2, 'pdf')
check(model(d4) == predicted, 'PNG and PDF delivery preserve exact complete editable document')
second_path = selectors['sections'][1]['paragraphs'][0]
change = text_edit(predicted, second_path, 'the material', 'the glaze')
r5, d5 = job('revised', project, 'write.edit', edit_request(d4, [change]), r4)
revised = copy.deepcopy(predicted)
paragraph = locate(revised, second_path)
paragraph['text'] = paragraph['text'].replace('the material', 'the glaze')
paragraph['runs'][0]['len'] = len(paragraph['text'].encode())
check(model(d5) == revised, 'second-page wording revision preserves every other native field')
r6, d6 = job('revised-png', project, 'write.export', {'format': 'png'}, r5)
delivery(d6, 2, 'png')
revised_pixels = pixels(d6)
check(revised_pixels[0] == baseline_pixels[0] and revised_pixels[1] != baseline_pixels[1], 'precise second-page revision preserves first page pixel-for-pixel')
r7, d7 = job('selected-png', project, 'write.export', {'format': 'png', 'pages': [2, 1], 'scale': 1.5}, r6)
selected = delivery(d7, 2, 'png', [2, 1])
check([p['page'] for p in selected['outputs']] == [2, 1]
      and [(p['width'], p['height']) for p in selected['outputs']] == [(893, 1263)] * 2,
      'requested page order and fractional scale preserve exact predicted dimensions')
r8, d8 = job('bundled', project, 'write.bundle', {}, r7)
check((d8 / 'exports/document.dobewrite').read_bytes() == (d8 / 'native/project.dobewrite').read_bytes(), 'standalone native bundle equals current editable source exactly')
r9, d9 = job('inspected', project, 'write.inspect', {}, r8)
check(model(d9) == revised, 'explicit inspection preserves current complete native model')
stable_source(d0, d9)
# Standalone delivery and native JSON import are distinct supported entry points.
standalone = call('standalone project', 'create-project', 'Standalone editable brief')['id']
asset = call('standalone asset', 'import-asset', standalone, d8 / 'exports/document.dobewrite')['id']
r10, d10 = job('standalone-import', standalone, 'write.import', {'asset': asset, 'format': 'dobewrite'})
check(model(d10) == revised, 'standalone native bundle import preserves complete revised model')
stable_source(d0, d10, recipe=False)
r11, d11 = job('standalone-pdf', standalone, 'write.export', {'format': 'pdf'}, r10)
delivery(d11, 2, 'pdf')
json_project = call('JSON project', 'create-project', 'Original JSON brief')['id']
asset = call('JSON asset', 'import-asset', json_project, d0 / 'native/original.json')['id']
r12, d12 = job('json-import', json_project, 'write.import', {'asset': asset, 'format': 'json'})
check(model(d12) == original and (d12 / 'native/original.json').read_bytes() == (d0 / 'native/original.json').read_bytes(), 'native JSON import preserves exact supplied source bytes and complete model')
# Import into a second independent state and revise its independently retained native source.
state = out / 'portable-state'
imported = call('portable import', 'import-project', d9, 'Portable editable production brief')
check(imported['revision']['validation']['scope'] == 'bundle_integrity'
      and not imported['revision']['validation']['native_cold_reopen'], 'portable import claims integrity only before native reopening')
restore = text_edit(revised, second_path, 'the glaze', 'the material')
r13, d13 = job('portable-restored', imported['project']['id'], 'write.edit', edit_request(d9, [restore]), imported['revision']['id'])
check(model(d13) == predicted, 'portable revision restores exact complete paginated model')
stable_source(d0, d13)
r14, d14 = job('portable-png', imported['project']['id'], 'write.export', {'format': 'png'}, r13)
delivery(d14, 2, 'png')
check(pixels(d14) == baseline_pixels, 'portable restoration reproduces every original paginated pixel')
state = out / 'state'
head = call('head before refusals', 'project', project)
for label, parameters, error in [
    ('stale-hash', {'expected_sha256': '0' * 64, 'edits': [change]}, 'hash'),
    ('atomic-batch', edit_request(d9, [text_edit(revised, second_path, 'the glaze', 'DO NOT PUBLISH'),
                                     {**change, 'path': '/body/999'}]), 'selector'),
    ('wrong-text', edit_request(d9, [{**change, 'expected': 'not the original'}]), 'expected text'),
    ('missing-page', {'format': 'png', 'pages': [3]}, 'missing page')]:
    failed = job(label, project, 'write.export' if label == 'missing-page' else 'write.edit', parameters, r9, False)
    check(error in json.dumps(failed), label + ' reports explicit refusal')
    check(call(label + ' head', 'project', project) == head, label + ' leaves project head unchanged')
# Reject unsupported native fields instead of silently dropping them.
bad_project = call('unsupported model project', 'create-project', 'Unsupported document field')['id']
bad_document = copy.deepcopy(original)
bad_document['unsupported_future_field'] = 'must not disappear'
bad_request = out / 'unsupported-model-request.json'
immutable(bad_request, (json.dumps({'document': bad_document}, sort_keys=True) + '\n').encode())
run('unsupported-model submit', [cli, '--state', state, 'submit', bad_project, 'write.create',
                               '--parameters', bad_request, '--key', 'unsupported-model'], expected=1)
refusal = next(record for record in logs if record['label'] == 'unsupported-model submit')
check('document has missing or unknown fields' in refusal['stderr'],
      'unknown native fields are refused at admission before any durable job')
# Actual missing font must be declared by the caller, never accepted silently.
font_request = copy.deepcopy(creation)
font_model, _ = write_recipes.compile_recipe(font_request)
font_model['styles']['defaultChr']['font'] = 'Missing Qualification Typeface'
for style in font_model['styles']['styles']:
    if style['id'].startswith('Dobe'):
        style['chr']['font'] = 'Missing Qualification Typeface'
font_project = call('font project', 'create-project', 'Explicit font substitution')['id']
r15, d15 = job('font-source', font_project, 'write.create', {'document': font_model})
font_head = call('font head before', 'project', font_project)
failed = job('unapproved-font', font_project, 'write.export', {'format': 'png'}, r15, False)
check('substitutions differ from explicit request' in json.dumps(failed), 'missing requested font is refused without explicit observed substitution')
check(call('font head after', 'project', font_project) == font_head, 'font refusal preserves editable project head')
# Explicit substitution is a delivery choice; requested source fonts remain unchanged.
r16, d16 = job('approved-font', font_project, 'write.export',
              {'format': 'png', 'font_substitutions': [{'requested': 'Missing Qualification Typeface', 'actual': 'Source Sans 3'}]}, r15)
approved = delivery(d16, 1, 'png')
check(approved['accepted_font_substitutions'] == [{'requested': 'Missing Qualification Typeface', 'actual': 'Source Sans 3'}]
      and model(d16) == font_model, 'explicit substitution renders with recorded fallback and leaves source font requests intact')
# The image-bearing native model is authored locally, not imported from another user's work.
swatch = Image.new('RGB', (480, 96), (18, 62, 73))
swatch.paste((216, 169, 103), (160, 0, 320, 96))
swatch.paste((231, 225, 214), (320, 0, 480, 96))
encoded = io.BytesIO(); swatch.save(encoded, format='PNG'); image_bytes = encoded.getvalue()
immutable(out / 'sources/material-swatches.png', image_bytes)
illustrated = copy.deepcopy(predicted)
illustrated.setdefault('media', {})['material-swatches.png'] = base64.b64encode(image_bytes).decode('ascii')
illustrated['body'][-1] = {'kind': 'para', 'text': '\ufffc', 'runs': [{'len': 3}],
                          'objects': [{'type': 'image', 'media': 'material-swatches.png', 'w': 480.0, 'h': 96.0,
                                       'alt': 'Blue-green, warm ochre and pale neutral production swatches'}]}
image_project = call('illustrated project', 'create-project', 'Illustrated material specification')['id']
failed = job('illustrated', image_project, 'write.create', {'document': illustrated}, success=False)
check('native snapshot changed the complete predicted model' in json.dumps(failed),
      'omitted image layout defaults are refused instead of silently normalized')
# Explicitly author the native image's neutral crop and inline-layout defaults.
# The preceding incomplete request remains a separate refusal counterexample.
illustrated['body'][-1]['objects'][0].update(
    crop=[0.0, 0.0, 0.0, 0.0],
    float={'wrap': 'inline', 'hRel': 'column', 'vRel': 'column', 'x': 0.0, 'y': 0.0,
           'dist': 0.0, 'distTop': 0.0, 'distBottom': 0.0, 'effect': [0.0, 0.0, 0.0, 0.0]})
r17, d17 = job('illustrated-complete', image_project, 'write.create', {'document': illustrated})
check(model(d17) == illustrated, 'image-bearing native document preserves complete model and exact embedded bytes')
r18, d18 = job('illustrated-png', image_project, 'write.export', {'format': 'png'}, r17)
delivery(d18, 2, 'png')
with Image.open(d18 / 'exports/delivery/page-002.png') as page:
    colors = {color: count for count, color in page.convert('RGB').getcolors(page.width * page.height)}
    check(colors.get((216, 169, 103), 0) >= 10000
          and colors.get((231, 225, 214), 0) >= 10000,
          'rendered second page contains both exact original swatch colors at meaningful area')
check(pixels(d18)[0] == baseline_pixels[0], 'adding image to second page leaves first-page pixels unchanged')
r19, d19 = job('illustrated-pdf', image_project, 'write.export', {'format': 'pdf'}, r18)
delivery(d19, 2, 'pdf')
check(model(d19)['media'] == illustrated['media'], 'PDF delivery retains exact embedded source image bytes')
state = out / 'portable-state'
transferred = call('illustrated portable import', 'import-project', d19, 'Portable illustrated specification')
r20, d20 = job('illustrated-portable-png', transferred['project']['id'], 'write.export', {'format': 'png'}, transferred['revision']['id'])
delivery(d20, 2, 'png')
check(pixels(d20) == pixels(d18) and model(d20) == illustrated,
      'fresh-state illustrated delivery preserves every page pixel and complete editable model')
state = out / 'state'

# Output review calls for separation between the table and its illustration.
# Make the correction through the same typed paragraph revision as customer work.
spacing_path = '/body/' + str(len(illustrated['body']) - 1)
spacing = {'kind': 'paragraph.properties', 'path': spacing_path, 'expected': {},
           'set': {'spaceBefore': 16.0}, 'unset': []}
r21, d21 = job('illustrated-spacing', image_project, 'write.edit', edit_request(d19, [spacing]), r19)
spaced = copy.deepcopy(illustrated)
spaced['body'][-1]['props'] = {'spaceBefore': 16.0}
check(model(d21) == spaced, 'review correction adds only requested space above the illustration')
r22, d22 = job('illustrated-final-png', image_project, 'write.export', {'format': 'png'}, r21)
delivery(d22, 2, 'png')
check(pixels(d22)[0] == pixels(d18)[0] and pixels(d22)[1] != pixels(d18)[1],
      'illustration spacing preserves first page and changes only second-page composition')
r23, d23 = job('illustrated-final-pdf', image_project, 'write.export', {'format': 'pdf'}, r22)
delivery(d23, 2, 'pdf')
stable_source(d17, d23, recipe=False)
check(model(d23)['media'] == illustrated['media'], 'spacing and PDF delivery retain all embedded original bytes')
state = out / 'portable-state'
final_transfer = call('illustrated final portable import', 'import-project', d23, 'Portable reviewed specification')
r24, d24 = job('illustrated-final-portable', final_transfer['project']['id'], 'write.export', {'format': 'png'}, final_transfer['revision']['id'])
delivery(d24, 2, 'png')
check(pixels(d24) == pixels(d22) and model(d24) == spaced,
      'reviewed illustrated delivery survives portable reopening with exact pixels and complete model')
state = out / 'state'

# Every successful checkout remains intact, and all execution groups must be gone.
groups = []
for directory in (out / 'state', out / 'portable-state'):
    with sqlite3.connect('file:' + str(directory / 'studio.sqlite3') + '?mode=ro', uri=True) as db:
        check(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], directory.name + ' database integrity passes')
        groups += [r[0] for r in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
for group in groups:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('native execution group remains: ' + str(group))
check(len(groups) == len(jobs), 'every durable job has an execution record and all execution groups are absent')
for record in jobs:
    if 'checkout' in record:
        verify_checkout(Path(record['checkout']))
check(True, 'all successful portable receipts remain exact')
check(run('verify payload after', [package / 'bin/a-dope-guard', 'verify'], fresh=True) == verification,
      'sealed payload remains unchanged after Write acceptance')
save('context.json', {'creation': creation, 'edits': edits, 'change': change, 'restore': restore,
                      'baselinePixels': baseline_pixels, 'revisedPixels': revised_pixels})
save('evidence.json', {'passed': True, 'checks': len(cases), 'cases': cases, 'nativeJobs': len(jobs),
    'successfulNativeJobs': sum(j['result']['state'] == 'succeeded' for j in jobs),
    'expectedFailedNativeJobs': sum(j['result']['state'] == 'failed' for j in jobs), 'admissionRefusals': 1,
    'operations': sorted({j['operation'] for j in jobs}), 'allNativeGroupsAbsent': True, 'groups': groups,
    'verification': verification, 'ownerVisualApproval': False, 'generalDOCXFidelityQualified': False,
    'completeReleaseQualified': False, 'network': False})
print(json.dumps({'passed': True, 'checks': len(cases), 'nativeJobs': len(jobs)}))
