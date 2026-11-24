"""Qualify all six typed PDF operations through a sealed package's public CLI.

Run with bundled Python: pdf_acceptance.py PACKAGE NEW_OUTPUT [--resume].
Own source documents and an inert active-content refusal fixture are generated
locally. No network, editor windows or service installation. Completed jobs are
reused on resume; admitted nonterminal work is never replayed automatically.
"""
import argparse
import copy
import fcntl
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
    check(v['native_cold_reopen'] and v['pixel_roundtrip_equal'] and v['source_bytes_unchanged']
          and v['static_structure_admitted'] and v['document_scripts_disabled'],
          label + ' admits static structure and preserves native source through cold reopening')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def read(directory, relative):
    return json.loads((directory / relative).read_text())


def pixels(directory):
    result = []
    for path in sorted((directory / 'exports').glob('page-*.png')):
        with Image.open(path) as image:
            result.append({'size': list(image.size), 'sha256': hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()})
    return result


def item(directory, name):
    identity = read(directory, 'native/objects.json')[name]
    key = 'content' if identity['type'] == 'text' else 'comments'
    return next(v for v in read(directory, 'exports/inspection.json')[key]
                if (v['page'], v['index']) == (identity['page'], identity['index']))


def unchanged_items(before, after, excluded):
    mapping = read(before, 'native/objects.json')
    newer = read(after, 'native/objects.json')
    for name, identity in mapping.items():
        assert newer[name] == identity, name
        if name not in excluded:
            assert item(before, name) == item(after, name), name


def text_object(name, value, x, y, width=516, height=50, size=14, bold=False, color='#292722'):
    return {'name': name, 'type': 'text', 'text': value, 'rect': [x, y, x + width, y + height],
            'font': 'helvetica', 'size': size, 'bold': bold, 'color': color}


def inert_action_pdf(path):
    """Valid minimal PDF whose inert OpenAction must be refused before opening."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R /OpenAction 5 0 R >>',
               b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> /Contents 4 0 R >>',
               b'<< /Length 0 >>\nstream\n\nendstream',
               b'<< /S /JavaScript /JS (void 0;) >>']
    data = bytearray(b'%PDF-1.7\n'); offsets = [0]
    for n, body in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f'{n} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = len(data)
    data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]: data.extend(f'{offset:010} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    immutable(path, bytes(data))


verification = run('verify payload before', [package / 'bin/a-dope-guard', 'verify'], fresh=True)
check(verification['verified'], 'complete sealed package verifies before PDF acceptance')
save('verification-before.json', verification)
project = call('brief project', 'create-project', 'A dope CLI / Editable production brief')['id']
creation = {'metadata': {'Title': 'ATELIER / 01 production notes', 'Author': 'A dope CLI', 'Subject': 'Draft'},
 'pages': [
    {'width': 612, 'height': 792, 'objects': [
        text_object('brand', 'ATELIER / 01', 48, 48, size=12, bold=True),
        text_object('headline', 'Product notes.', 48, 120, height=70, size=36, bold=True),
        text_object('intro', 'A study in quiet detail.', 48, 198, size=18, color='#706B61'),
        text_object('section', '01   THE DIRECTION', 48, 286, size=11, bold=True, color='#A44A32'),
        text_object('brief', 'Warm glass. Soft light. Room to breathe.\nKeep material, silhouette and label distinct.', 48, 326, height=70, size=16),
        text_object('revision_note', 'Revise one decision at a time.\nPreserve the composition and editable source.', 48, 432, height=70, size=14),
        {'name': 'review', 'type': 'rectangle', 'rect': [48, 566, 564, 680],
         'color': '#706B61', 'fill': 'none', 'width': 1, 'contents': 'Draft review area'},
        text_object('review_label', 'REVIEW / DRAFT', 66, 586, size=11, bold=True),
        text_object('review_detail', 'Named text and annotation remain editable.', 66, 622, width=470, size=13),
        text_object('folio_1', 'PRODUCTION NOTES                                      01 / 02', 48, 738, size=9)]},
    {'width': 612, 'height': 792, 'objects': [
        text_object('appendix_brand', 'ATELIER / 01', 48, 48, size=12, bold=True),
        text_object('appendix_title', 'Delivery standard.', 48, 120, height=70, size=32, bold=True),
        text_object('appendix_intro', 'The work stays open to revision.', 48, 198, size=18, color='#706B61'),
        text_object('source_section', '01   EDITABLE SOURCE', 48, 292, size=11, bold=True, color='#A44A32'),
        text_object('source_detail', 'Native document, stable object names\nand original source material travel together.', 48, 330, height=70, size=16),
        text_object('export_section', '02   REVIEW OUTPUT', 48, 438, size=11, bold=True, color='#A44A32'),
        text_object('export_detail', 'PDF for review. PNG for inspection.\nA receipt binds every delivered file.', 48, 476, height=70, size=16),
        {'name': 'outline', 'type': 'oval', 'rect': [48, 622, 74, 648], 'color': '#A44A32', 'fill': 'none', 'width': 1.5},
        text_object('outline_note', 'Retain the original. Deliver the revision.', 90, 626, width=470, size=12),
        text_object('folio_2', 'PRODUCTION NOTES                                      02 / 02', 48, 738, size=9)]}]}
r0, d0 = job('original', project, 'pdf.create', creation)
p0 = pixels(d0)
check(len(p0) == 2 and all(p['size'] == [612, 792] for p in p0), 'two pages render at exact native dimensions')
check(item(d0, 'outline')['fill_rgb'] is None, 'unfilled native oval remains transparent')
changes = {'edits': [{'name': 'headline', 'type': 'text', 'text': 'Production ready.', 'color': '#A44A32'},
                     {'name': 'review', 'type': 'annotation', 'color': '#A44A32', 'contents': 'Approved review area'}],
           'metadata': {'Subject': 'Precise revision'}}
r1, d1 = job('revised', project, 'pdf.edit', changes, r0)
check((d1/'native/document.pdf').read_bytes().startswith((d0/'native/document.pdf').read_bytes()), 'named edit retains original PDF bytes as an incremental prefix')
unchanged_items(d0, d1, {'headline', 'review'})
check(True, 'named revision preserves every untargeted editable record and original object identities')
check(item(d1, 'headline')['text'] == 'Production ready.' and item(d1, 'review')['contents'] == 'Approved review area', 'named text and annotation edits persist in actual native inspection')
check(pixels(d1)[1] == p0[1] and pixels(d1)[0] != p0[0], 'only the targeted first page changes pixels')
replacement = {'replacements': [{'find': 'Production ready.', 'replace': 'Release candidate.', 'pages': [1], 'expected_matches': 1}]}
r2, d2 = job('replacement', project, 'pdf.edit', replacement, r1)
check((d2/'native/document.pdf').read_bytes().startswith((d1/'native/document.pdf').read_bytes()), 'counted text replacement retains the previous incremental document')
check(item(d2, 'headline')['text'] == 'Release candidate.', 'replacement changes the exact requested text')
unchanged_items(d1, d2, {'headline'})
check(True, 'replacement preserves all other editable records including annotation identity')
restyle = {'edits': [{'name': 'headline', 'type': 'text', 'color': '#364F56'}]}
r_style, d_style = job('replacement-restyled', project, 'pdf.edit', restyle, r2)
check(item(d_style, 'headline')['text'] == 'Release candidate.', 'color-only revision retains the replacement in editable text')
unchanged_items(d2, d_style, {'headline'})
page_text = ' '.join(read(d_style, 'exports/inspection.json')['text'][0]['text'].split())
check(page_text.count('Release candidate.') == 1 and 'Production ready.' not in page_text,
      'color-only revision neither resurrects old wording nor duplicates the replacement')
check(pixels(d_style)[1] == pixels(d2)[1] and pixels(d_style)[0] != pixels(d2)[0],
      'replacement restyle changes only its targeted page')
# The style revision is now the head. An older explicit source must not replace it.
stale = job('inspection', project, 'pdf.inspect', {}, r2, False)
check('project head changed' in json.dumps(stale), 'stale-source inspection is refused instead of replacing newer work')
check(call('head after stale source', 'project', project)['head'] == r_style, 'stale-source refusal preserves the latest style revision')
r3, d3 = job('inspection-latest', project, 'pdf.inspect', {}, r_style)
check((d3/'native/document.pdf').read_bytes() == (d_style/'native/document.pdf').read_bytes() and pixels(d3) == pixels(d_style), 'inspection preserves every source byte and page pixel')
r4, d4 = job('reordered', project, 'pdf.extract', {'pages': [2, 1]}, r3)
check(pixels(d4) == list(reversed(pixels(d3))), 'page extraction follows requested order with exact pixels')
old_mapping = read(d3, 'native/objects.json'); remapped = read(d4, 'native/objects.json')
check(remapped == {name: {**value, 'page': 3-value['page']} for name,value in old_mapping.items()}, 'extraction preserves editable identities and remaps page numbers exactly')
# Import and merge use only project-owned imported assets.
import_project = call('import project', 'create-project', 'Imported production brief')['id']
asset = call('PDF source asset', 'import-asset', import_project, d0/'native/document.pdf')['id']
r5, d5 = job('imported', import_project, 'pdf.import', {'asset': asset})
check((d5/'native/document.pdf').read_bytes() == (d0/'native/document.pdf').read_bytes() and pixels(d5) == p0, 'PDF import retains exact original bytes and pixels')
addition = {'additions': [text_object('approval', 'APPROVED FOR PRODUCTION', 48, 698, height=25, size=10, bold=True, color='#A44A32') | {'page': 2}]}
r6, d6 = job('addition', import_project, 'pdf.edit', addition, r5)
unchanged_items(d5, d6, set())
check(item(d6, 'approval')['text'] == 'APPROVED FOR PRODUCTION', 'imported PDF accepts a new precisely named editable text object')
check(pixels(d6)[0] == p0[0] and pixels(d6)[1] != p0[1], 'addition preserves the untargeted page pixel-for-pixel')
merge_project = call('merge project', 'create-project', 'Merged production packet')['id']
a1 = call('merge first asset', 'import-asset', merge_project, d0/'native/document.pdf')['id']
a2 = call('merge second asset', 'import-asset', merge_project, d2/'native/document.pdf')['id']
r7, d7 = job('merged', merge_project, 'pdf.merge', {'assets': [a1, a2]})
check(pixels(d7) == p0 + pixels(d2), 'merged packet preserves all four page pixels in source order')
# Hand off the complete bundle to another private state and restore the design.
state = out/'portable-state'
imported = call('portable import', 'import-project', d2, 'Portable production brief')
check(imported['revision']['validation']['scope'] == 'bundle_integrity' and not imported['revision']['validation']['native_cold_reopen'], 'portable import claims only integrity before native reopening')
restore = {'edits': [{'name': 'headline', 'type': 'text', 'text': 'Product notes.', 'color': '#292722'},
                     {'name': 'review', 'type': 'annotation', 'color': '#706B61', 'contents': 'Draft review area'}],
           'metadata': {'Subject': 'Draft'}}
r8, d8 = job('portable-restored', imported['project']['id'], 'pdf.edit', restore, imported['revision']['id'])
check(pixels(d8) == p0, 'fresh-state native revision restores every original page pixel')
check(read(d8, 'native/objects.json') == read(d0, 'native/objects.json'), 'portable revision retains every named editable identity')
unchanged_items(d0, d8, {'review'})
check(True, 'restoration recovers original editable content; only annotation modification time may advance')
# Refused jobs must not publish partial work or move their project head.
state = out/'state'
head = call('head before refusals', 'project', project)
for label, parameters, error in [
 ('partial-batch', {'edits': [{'name':'headline','type':'text','text':'Must not publish'}, {'name':'missing','type':'text','text':'Bad target'}]}, 'unknown PDF edit target'),
 ('wrong-count', {'replacements':[{'find':'Release candidate.','replace':'Must not publish','pages':[2],'expected_matches':2}]}, 'exact requested match count'),
 ('unsupported-glyph', {'edits':[{'name':'headline','type':'text','text':'Unsupported \U0001f600'}]}, 'standard fonts')]:
    failed = job(label, project, 'pdf.edit', parameters, r4, False)
    check(error in json.dumps(failed).replace('\\\\', '\\'), label + ' reports the expected native refusal')
    check(call(label + ' head', 'project', project) == head, label + ' leaves the published project head unchanged')
active = out/'sources/inert-action.pdf'; inert_action_pdf(active)
active_project = call('active PDF project', 'create-project', 'Inert action refusal')['id']
a = call('active PDF asset', 'import-asset', active_project, active)['id']
active_head = call('active PDF head before', 'project', active_project)
failed = job('active-content', active_project, 'pdf.import', {'asset': a}, success=False)
check('automatic actions, dynamic content, attached files or signing permissions' in json.dumps(failed), 'static admission refuses the inert action before publishing')
check(call('active PDF head after', 'project', active_project) == active_head, 'active-content refusal publishes no document')
# Consistent hashes do not make a false native object mapping valid.
malformed = out/'duplicate-mapping-bundle'
if not malformed.exists(): shutil.copytree(d2, malformed)
model = read(d2, 'native/objects.json'); model['duplicate_target'] = copy.deepcopy(model['headline'])
changed = malformed/'native/objects.json'; changed.write_text(json.dumps(model, sort_keys=True)+'\n')
receipt = read(d2, 'project.json'); record = next(f for f in receipt['files'] if f['path']=='native/objects.json')
record.update(bytes=changed.stat().st_size, sha256=digest(changed));(malformed/'project.json').write_text(json.dumps(receipt,indent=2)+'\n');verify_checkout(malformed)
malformed_project = call('duplicate mapping import', 'import-project', malformed, 'Duplicate native identity')
pid=malformed_project['project']['id'];bad_head=call('duplicate mapping head before', 'project', pid)
failed=job('duplicate-mapping',pid,'pdf.inspect',{},malformed_project['revision']['id'],False)
check('duplicate PDF object target' in json.dumps(failed), 'native inspection rejects duplicate targets despite a valid portable receipt')
check(call('duplicate mapping head after','project',pid)==bad_head, 'duplicate mapping refusal preserves its imported head')
groups=[]
for directory in (out/'state',out/'portable-state'):
    with sqlite3.connect('file:'+str(directory/'studio.sqlite3')+'?mode=ro',uri=True) as db:
        check(db.execute('PRAGMA quick_check').fetchall()==[('ok',)], directory.name+' database integrity passes')
        groups += [r[0] for r in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
for group in groups:
    try: os.killpg(group,0)
    except ProcessLookupError: pass
    else: raise AssertionError('native execution group remains: '+str(group))
check(len(groups)==len(jobs), 'every durable job has an execution record and all execution groups are absent')
for record in jobs:
    if 'checkout' in record: verify_checkout(Path(record['checkout']))
check(True,'all successful portable receipts remain exact')
check(run('verify payload after',[package/'bin/a-dope-guard','verify'],fresh=True)==verification, 'all sealed payload entries remain unchanged after PDF acceptance')
save('context.json',{'creation':creation,'revision':changes,'replacement':replacement,'restyle':restyle,'addition':addition,'restoration':restore,'originalPixels':p0})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'nativeJobs':len(jobs),
 'successfulNativeJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedNativeJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'allNativeGroupsAbsent':True,'groups':groups,'verification':verification,
 'ownerVisualApproval':False,'generalPDFFidelityQualified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'nativeJobs':len(jobs)}))
