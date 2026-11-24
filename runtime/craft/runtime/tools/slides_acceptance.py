"""Qualify all seven typed Slides operations through a sealed package's public CLI.

Run with bundled Python: slides_acceptance.py PACKAGE NEW_OUTPUT
--predecessor ACTUAL_PREDECESSOR [--resume].
Original document recipes and refusal inputs are generated locally. No network, editor windows or service installation. Completed jobs are
reused on resume; admitted nonterminal work is never replayed automatically.
"""
import argparse
import io
import zipfile
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
parser.add_argument('--predecessor', type=Path, required=True)
args = parser.parse_args()
package = args.package.resolve(strict=True)
sys.path.insert(0, str(package / 'lib/dobe/runtime'))
from studio_runtime import slides_recipes, slides_revision, slides_source
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
    if operation == 'pdf.import':
        check(v['native_cold_reopen'] and v['pixel_roundtrip_equal'] and v['source_bytes_unchanged']
              and v['static_structure_admitted'] and v['document_scripts_disabled'],
              label + ' independently imports and rasterizes the exact PDF through the public PDF route')
    else:
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


def hash_json(value):
    return hashlib.sha256((json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode()).hexdigest()


def request(directory, edits):
    return {'expected_sha256': digest(directory / 'native/project.dobeslides'), 'edits': edits}


def text_edit(document, path, old, new):
    text = locate(document, path)['text'].encode()
    start = text.index(old.encode())
    return {'kind': 'text.replace', 'path': path, 'start': start, 'end': start + len(old.encode()), 'expected': old, 'value': new}


def pixels(directory):
    result = []
    for path in sorted((directory / 'exports/delivery').glob('slide-*.png')):
        with Image.open(path) as image:
            result.append({'file': path.name, 'size': list(image.size),
                           'sha256': hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()})
    return result


def stable_source(before, after, recipe=True):
    for name in ('native/baseline.json', 'native/original.json'):
        assert (before / name).read_bytes() == (after / name).read_bytes(), name
    if recipe:
        for name in ('recipes/origin-slides-operation.json', 'recipes/slides-production.json'):
            assert (before / name).read_bytes() == (after / name).read_bytes(), name


def delivery(directory, count, kind, slides=None):
    value = read(directory, 'exports/delivery/delivery.json')
    check(value['format'] == kind and value['slide_count'] == count
          and value['selected_slides'] == (slides or list(range(1, count + 1)))
          and value['complete_output_decode'] and value['actual_font_bytes_verified']
          and value['visible_plain_text_owners_equal'] and value['text_layout_clear']
          and value['owned_picture_decoder_agreement'], directory.name + ' verifies complete text, owned pictures and output geometry')
    if kind == 'pdf':
        cold = value['independent_pdf_checks']
        check(len(cold) == 2 and cold[0]['rgba8_sha256'] == cold[1]['rgba8_sha256']
              and all(all(p['normalized_character_inventory_equal'] for p in c['text_checks']) for c in cold),
              directory.name + ' corrected PDF reader preserves all text inventories and cold pixels')
    else:
        check(all(p['cold_bytes_equal'] for p in value['outputs']), directory.name + ' PNG bytes match across native cold renders')
    return value


def pixel(directory, slide, xy, expected):
    with Image.open(directory / f'exports/delivery/slide-{slide:03}.png') as image:
        actual = image.convert('RGB').getpixel(xy)
    assert actual == tuple(expected), (directory.name, xy, actual, expected)


verification = run('verify payload before', [package / 'bin/a-dope-guard', 'verify'], fresh=True)
check(verification['verified'], 'complete sealed package verifies before Slides acceptance')
save('verification-before.json', verification)
creation = {'recipe': 'production_proposal', 'version': 1, 'title': 'The quiet object.',
            'subtitle': 'A material study with room to breathe.', 'label': 'ATELIER / 02', 'author': 'A dope CLI',
            'sections': [
                {'heading': 'Material first.', 'paragraphs': ['Warm porcelain. Matte surface. Keep the camera, shape and label fixed.'],
                 'notes': 'Review the material before changing the light. Retain each original source.'},
                {'heading': 'Light with intent.', 'paragraphs': ['One broad source. A quiet edge highlight. Preserve the composition through each lighting revision.'],
                 'notes': 'The next revision changes one decision and retains the approved framing.'}],
            'deliverables': [{'asset': 'Product photograph', 'source': 'Editable scene', 'delivery': 'PNG + scene'},
                             {'asset': 'Material revision', 'source': 'Same camera and shape', 'delivery': 'PNG + recipe'},
                             {'asset': 'Production brief', 'source': 'Native document', 'delivery': 'PDF + source'}],
            'controls': {'accent': '#D8A967'}}
project = call('proposal project', 'create-project', 'ATELIER / 02 editable proposal')['id']
r0, d0 = job('original', project, 'slides.create', creation)
original = model(d0)
production = read(d0, 'recipes/slides-production.json')
selectors = production['selectors']
check(original == slides_recipes.compile_recipe(creation)['document'], 'complete authored presentation equals deterministic recipe output')
check(len(original['slides']) == 4 and all(locate(original, s['notes'])['text'] == c['notes']
      for s,c in zip(selectors['sections'],creation['sections'])), 'all four slides and exact editable speaker notes are preserved')
r1, d1 = job('original-png', project, 'slides.export', {'format': 'png'}, r0)
delivery(d1, 4, 'png')
original_pixels = pixels(d1)
check(all(p['size'] == [960, 540] for p in original_pixels), 'all original slides render at exact intended canvas size')
# Change one visible phrase and one speaker note; the unrelated slides remain exact.
body_path = selectors['sections'][0]['paragraphs']['runs'][0]
notes_path = selectors['sections'][0]['notes']
edits = [text_edit(original, body_path, 'Warm porcelain', 'Glazed porcelain'),
         text_edit(original, notes_path, 'the material', 'the glaze')]
r2, d2 = job('wording-revision', project, 'slides.edit', request(d1, edits), r1)
revised = copy.deepcopy(original)
locate(revised, body_path)['text'] = locate(revised, body_path)['text'].replace('Warm porcelain', 'Glazed porcelain')
locate(revised, notes_path)['text'] = locate(revised, notes_path)['text'].replace('the material', 'the glaze')
check(model(d2) == revised, 'wording and note changes preserve every other native field')
stable_source(d0, d2)
r3, d3 = job('wording-png', project, 'slides.export', {'format': 'png'}, r2)
delivery(d3, 4, 'png')
changed_pixels = pixels(d3)
check(changed_pixels[1] != original_pixels[1] and all(changed_pixels[i] == original_pixels[i] for i in (0,2,3)),
      'wording revision changes only the intended slide pixels')
# Import and embed original caller-owned pixels using the project-scoped asset route.
source_image = out / 'sources/material-swatches.png'
image = Image.new('RGB', (480, 96), (18, 62, 73))
image.paste((216, 169, 103), (160, 0, 320, 96)); image.paste((231, 225, 214), (320, 0, 480, 96))
buffer = io.BytesIO(); image.save(buffer, format='PNG'); immutable(source_image, buffer.getvalue())
asset = call('swatch asset', 'import-asset', project, source_image)['id']
insert = {'kind': 'picture.insert', 'path': '/slides/1', 'expected': hash_json(revised['slides'][1]),
          'value': {'image': {'asset': asset, 'sha256': digest(source_image), 'name': 'Material swatches', 'contentType': 'image/png'},
                    'transform': {'x': 348.0, 'y': 320.0, 'w': 480.0, 'h': 96.0}}}
r4, d4 = job('illustrated', project, 'slides.edit', request(d3, [insert]), r3)
illustrated = model(d4)
picture_path = '/slides/1/shapes/' + str(len(illustrated['slides'][1]['shapes'])-1)
media = illustrated['media'][-1]
remaining = copy.deepcopy(illustrated); remaining['slides'][1]['shapes'].pop(); remaining['media'].pop(); remaining['nextId'] = revised['nextId']
check(remaining == revised and bytes.fromhex(media['dataHex']) == source_image.read_bytes(),
      'picture insertion changes only the selected slide, new owned resource and ID allocation')
r5, d5 = job('illustrated-png', project, 'slides.export', {'format': 'png'}, r4)
delivery(d5, 4, 'png')
pixel(d5,2,(400,350),(18,62,73));pixel(d5,2,(560,350),(216,169,103));pixel(d5,2,(720,350),(231,225,214))
check(all(pixels(d5)[i] == changed_pixels[i] for i in (0,2,3)), 'embedded picture has exact source colors and preserves every other slide')
r6, d6 = job('illustrated-pdf', project, 'slides.export', {'format': 'pdf'}, r5)
delivery(d6, 4, 'pdf')
# Crop to the middle half while keeping source bytes and frame intact.
crop = {'kind': 'picture.crop', 'path': picture_path, 'expected': [0.0]*4, 'value': [.25,0.0,.25,0.0]}
r7, d7 = job('cropped', project, 'slides.edit', request(d6, [crop]), r6)
predicted_crop = copy.deepcopy(illustrated);locate(predicted_crop,picture_path)['kind']['fill']['crop']=[.25,0.0,.25,0.0]
check(model(d7)==predicted_crop, 'crop changes only the explicitly selected picture crop')
r8, d8 = job('cropped-png', project, 'slides.export', {'format':'png'}, r7)
delivery(d8,4,'png');pixel(d8,2,(588,350),(216,169,103))
# Replace the embedded image through a fresh scoped asset, then change its placement.
replacement_image = out / 'sources/revised-swatches.png'
replacement = Image.new('RGB',(480,96),(54,79,86));replacement.paste((164,74,50),(160,0,320,96));replacement.paste((231,225,214),(320,0,480,96))
buffer=io.BytesIO();replacement.save(buffer,format='PNG');immutable(replacement_image,buffer.getvalue())
asset=call('replacement asset','import-asset',project,replacement_image)['id']
replace={'kind':'picture.replace','path':picture_path,'expected':{'media':media['id'],'sha256':digest(source_image)},
         'value':{'asset':asset,'sha256':digest(replacement_image),'name':'Revised material swatches','contentType':'image/png'}}
r9,d9=job('picture-revision',project,'slides.edit',request(d8,[replace]),r8)
current=model(d9);expected=copy.deepcopy(predicted_crop)
new_media=current['media'][-1]
expected['media'].append(new_media);expected['nextId']=predicted_crop['nextId']+1
locate(expected,picture_path)['kind']['fill']['media']=expected['nextId']
check(current==expected and new_media['id']==expected['nextId'] and bytes.fromhex(new_media['dataHex'])==replacement_image.read_bytes(),
      'replacement retains all original media, crop and placement while adding exact new pixels')
transform=locate(current,picture_path)['xfrm']
move={'kind':'shape.transform','path':picture_path,'expected':transform,'value':{**transform,'y':304.0,'h':112.0}}
rename={'kind':'slide.properties','path':'/slides/1','expected':{'name':current['slides'][1]['name']},'set':{'name':'Material / revised'}}
r10,d10=job('placed',project,'slides.edit',request(d9,[move,rename]),r9)
placed=copy.deepcopy(current);locate(placed,picture_path)['xfrm']=move['value'];placed['slides'][1]['name']='Material / revised'
check(model(d10)==placed,'placement and slide-name revision preserve the complete surrounding model')
r11,d11=job('final-png',project,'slides.export',{'format':'png'},r10)
delivery(d11,4,'png');pixel(d11,2,(588,350),(164,74,50))
check(all(pixels(d11)[i]==original_pixels[i] for i in (0,2,3)), 'complete picture revision preserves every untargeted slide pixel')
r12,d12=job('selected-png',project,'slides.export',{'format':'png','slides':[4,2],'scale':1.25},r11)
selected=delivery(d12,4,'png',[4,2])
check([p['slide'] for p in selected['outputs']]==[4,2] and all((p['width'],p['height'])==(1200,675) for p in selected['outputs']),
      'ordered fractional-scale export obeys exact slide selection and dimensions')
r13,d13=job('final-pdf',project,'slides.export',{'format':'pdf'},r12);delivery(d13,4,'pdf')
r14,d14=job('bundled',project,'slides.bundle',{},r13)
check((d14/'exports/presentation.dobeslides').read_bytes()==(d14/'native/project.dobeslides').read_bytes(), 'standalone bundle is exact current editable presentation')
r15,d15=job('inspected',project,'slides.inspect',{},r14)
check(model(d15)==placed,'explicit inspection retains complete revised native model');stable_source(d0,d15)
# Continue in an independent state; existing source assets need not be re-imported.
state=out/'portable-state'
imported=call('portable import','import-project',d15,'Portable ATELIER proposal')
check(imported['revision']['validation']['scope']=='bundle_integrity' and not imported['revision']['validation']['native_cold_reopen'],
      'whole-project import declares integrity only until native reopening')
r16,d16=job('portable-png',imported['project']['id'],'slides.export',{'format':'png'},imported['revision']['id'])
delivery(d16,4,'png')
check(model(d16)==placed and pixels(d16)==pixels(d11),'portable presentation reopens with complete model and every pixel unchanged')
stable_source(d0,d16)
state=out/'state'
# Exercise native JSON and standalone bundle imports separately.
for label,kind,source_file,expected_model in [('json','json',d0/'native/original.json',original),
                                            ('standalone','dobeslides',d14/'exports/presentation.dobeslides',placed)]:
    owner=call(label+' project','create-project',label+' imported proposal')['id']
    asset=call(label+' asset','import-asset',owner,source_file)['id']
    ri,di=job(label+'-import',owner,'slides.import',{'asset':asset,'format':kind})
    check(model(di)==expected_model,label+' import preserves complete authored model')
# Explicit real predecessor migration; never fabricate a legacy engine receipt.
predecessor=args.predecessor.resolve(strict=True)
legacy_bytes=predecessor.read_bytes()
with zipfile.ZipFile(io.BytesIO(legacy_bytes)) as archive:
    legacy_manifest=json.loads(archive.read('project.json'))
    legacy_document=json.loads(archive.read('document.json'))
    legacy_original=archive.read('original.deckcraft')
legacy_owner=call('legacy project','create-project','Maintained predecessor migration')['id']
legacy_asset=call('legacy asset','import-asset',legacy_owner,predecessor)['id']
rm,dm=job('migrated',legacy_owner,'slides.migrate',{'asset':legacy_asset,'expected_sha256':digest(predecessor)})
check((dm/'native/predecessor.dobeslides').read_bytes()==legacy_bytes and model(dm)==legacy_document
      and (dm/'native/original.deckcraft').read_bytes()==legacy_original,'migration preserves actual predecessor, native model and original container exactly')
check(read(dm,'project.json')['validation']['engine_migration_verified']
      and read(dm,'exports/inspection.json')['migration_count']==2,
      'explicit maintained migration preserves both successive predecessor transitions')
rm2,dm2=job('migrated-png',legacy_owner,'slides.export',{'format':'png'},rm)
delivery(dm2,len(legacy_document['slides']),'png')
# Original native container import is independent of portable migration.
legacy_input=out/'sources/original.deckcraft';immutable(legacy_input,legacy_original)
owner=call('native container project','create-project','Original native container')['id']
asset=call('native container asset','import-asset',owner,legacy_input)['id']
rn,dn=job('native-import',owner,'slides.import',{'asset':asset,'format':'deckcraft'})
check((dn/'native/original.deckcraft').read_bytes()==legacy_original,'native-container import preserves every original byte')
# Failed requests must leave the existing main project untouched.
bad_request = out / 'missing-slide-request.json'
immutable(bad_request, (json.dumps({'format': 'png', 'slides': [99]}, sort_keys=True) + '\n').encode())
run('missing-slide submit', [cli, '--state', state, 'submit', project, 'slides.export',
                            '--parameters', bad_request, '--key', 'missing-slide', '--source', r15], expected=1)
refusal = next(record for record in logs if record['label'] == 'missing-slide submit')
check('unique ordered integers from 1 to 32' in refusal['stderr'], 'out-of-range slide selection is refused before admitting a durable job')

head=call('head before refusals','project',project)
for label,operation,params,error in [
    ('stale-hash','slides.edit',{'expected_sha256':'0'*64,'edits':edits},'hash'),
    ('wrong-picture','slides.edit',request(d15,[replace]),'expected owned bytes'),
    ('bad-batch','slides.edit',request(d15,[text_edit(placed,body_path,'Glazed porcelain','DO NOT PUBLISH'),
                                         {**edits[0],'path':'/slides/999/shapes/0/text/paragraphs/0/runs/0'}]),'owned run'),
    ('missing-slide-native','slides.export',{'format':'png','slides':[5]},'missing slide'),
    ('same-engine-migration','slides.migrate',{'expected_sha256':digest(d15/'native/project.dobeslides')},'qualified maintained transition')]:
    failed=job(label,project,operation,params,r15,False)
    check(error in json.dumps(failed),label+' reports expected refusal')
    check(call(label+' head','project',project)==head,label+' leaves published head unchanged')
# Style revision uses the seventh declared typed edit kind and preserves content.
heading_run = selectors['sections'][0]['heading']['runs'][0]
format_edit = {'kind': 'run.properties', 'path': heading_run, 'expected': locate(placed, heading_run)['props'],
               'set': {'fill': slides_recipes.solid('#A44A32')}}
rf, df = job('formatted', project, 'slides.edit', request(d15, [format_edit]), r15)
formatted = copy.deepcopy(placed)
locate(formatted, heading_run)['props']['fill'] = slides_recipes.solid('#A44A32')
check(model(df) == formatted, 'heading color revision changes only the requested text-run property')
rf_png, df_png = job('formatted-png', project, 'slides.export', {'format': 'png'}, rf)
delivery(df_png, 4, 'png')
check(pixels(df_png)[1] != pixels(d11)[1] and all(pixels(df_png)[i] == pixels(d11)[i] for i in (0, 2, 3)),
      'format revision preserves every untargeted slide pixel and keeps picture geometry')
rf_pdf, df_pdf = job('formatted-pdf', project, 'slides.export', {'format': 'pdf'}, rf_png)
delivery(df_pdf, 4, 'pdf'); stable_source(d0, df_pdf)
state = out / 'portable-state'
formatted_transfer = call('formatted portable import', 'import-project', df_pdf, 'Portable reviewed proposal')
rf_portable, df_portable = job('formatted-portable', formatted_transfer['project']['id'], 'slides.export', {'format': 'png'}, formatted_transfer['revision']['id'])
delivery(df_portable, 4, 'png')
check(model(df_portable) == formatted and pixels(df_portable) == pixels(df_png),
      'reviewed style and picture revisions survive portable reopening with exact model and pixels')
state = out / 'state'

# Cross-application delivery proves that the final PDF also contains the owned image.
pdf_project = call('PDF proof project', 'create-project', 'Independent proposal PDF raster')['id']
pdf_source = df_pdf / 'exports/delivery/presentation.pdf'
pdf_asset = call('PDF proof asset', 'import-asset', pdf_project, pdf_source)['id']
r_pdf_proof, d_pdf_proof = job('independent-pdf', pdf_project, 'pdf.import', {'asset': pdf_asset})
check((d_pdf_proof / 'native/document.pdf').read_bytes() == pdf_source.read_bytes(),
      'PDF handoff retains exact original presentation PDF bytes')
with Image.open(d_pdf_proof / 'exports/page-002.png') as picture:
    actual = picture.convert('RGB').getpixel((588, 350))
    check(max(abs(a-b) for a, b in zip(actual, (164, 74, 50))) <= 2,
          'independent PDF raster contains the requested replacement color within two channel levels')

groups=[]
for directory in (out/'state',out/'portable-state'):
    with sqlite3.connect('file:'+str(directory/'studio.sqlite3')+'?mode=ro',uri=True) as db:
        check(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],directory.name+' database integrity passes')
        groups += [r[0] for r in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
for group in groups:
    try:os.killpg(group,0)
    except ProcessLookupError:pass
    else:raise AssertionError('native execution group remains: '+str(group))
check(len(groups)==len(jobs),'all durable execution groups are accounted for and absent')
for record in jobs:
    if 'checkout' in record:verify_checkout(Path(record['checkout']))
check(True,'all successful checkout receipts remain exact')
check(predecessor.read_bytes()==legacy_bytes,'retained predecessor input remains unchanged')
check(run('verify payload after',[package/'bin/a-dope-guard','verify'],fresh=True)==verification,'complete sealed payload remains unchanged')
save('context.json',{'creation':creation,'wordingEdits':edits,'insert':insert,'crop':crop,'replace':replace,'placement':move,'rename':rename,
                     'originalPixels':original_pixels,'finalPixels':pixels(df_png),'formatEdit':format_edit,'predecessorSHA256':digest(predecessor)})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'durableJobs':len(jobs),
 'admissionRefusals':1,'slidesJobs':sum(j['operation'].startswith('slides.') for j in jobs),
 'successfulJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'allNativeGroupsAbsent':True,'groups':groups,'verification':verification,
 'ownerVisualApproval':False,'generalPPTXFidelityQualified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'durableJobs':len(jobs)}))
