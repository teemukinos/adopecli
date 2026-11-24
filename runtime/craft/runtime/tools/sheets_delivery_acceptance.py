"""Qualify the declared Sheets numeric formats through an installed CLI/MCP.

Use a sealed package and a new private output directory. Collection runs once;
verification reads the completed evidence without repeating native jobs. No
browser, network, rendering, editor or application database mutation is used.
"""
import argparse
import copy
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from html.parser import HTMLParser

FORMATS = ['General', '0', '0.00', '#,##0', '#,##0.00', '0%', '0.00%']
TEXT = 'Åäö — <script>literal</script> & "quoted", text\nsecond line'
VALUES = [1234.567, -1234.567, 0.0, 0.1256]
# Fixed independent expectations, not values calculated by production code.
DISPLAY = [
    ['1234.567', '1235', '1234.57', '1,235', '1,234.57', '123457%', '123456.70%'],
    ['-1234.567', '-1235', '-1234.57', '-1,235', '-1,234.57', '-123457%', '-123456.70%'],
    ['0', '0', '0.00', '0', '0.00', '0%', '0.00%'],
    ['0.1256', '0', '0.13', '0', '0.13', '13%', '12.56%'],
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cells(document, sheet=0):
    return {(int(row), int(col)): cell
            for band in document['sheets'][sheet]['cells']['bands'].values()
            for row, columns in band['rows'].items() for col, cell in columns.items()}


def expanded(document):
    result = copy.deepcopy(document)
    styles = result.pop('styles')['styles']
    for i, sheet in enumerate(result['sheets']):
        sheet['cells'] = {str(r) + ',' + str(c): dict(copy.deepcopy(cell),
                          style=copy.deepcopy(styles[cell['style']]))
                          for (r, c), cell in cells(document, i).items()}
    return result


def create_model(package):
    model = json.loads((package / 'lib/dobe/runtime/studio_runtime/sheets_base.json').read_text())
    model['sheets'].append(copy.deepcopy(model['sheets'][0]))
    model['sheets'][0]['name'] = 'Formats'
    model['sheets'][1]['name'] = 'Retained source'
    rows = {}
    for row in range(8):
        rows[str(row)] = {}
        for col, fmt in enumerate(FORMATS):
            style = copy.deepcopy(model['styles']['styles'][0])
            style['num_fmt'] = fmt
            style['font']['bold'] = row in (1, 4)
            style['font']['italic'] = row in (2, 4)
            model['styles']['styles'].append(style)
            value = ({'t': 'Text', 'v': fmt} if row == 0 else
                     {'t': 'Number', 'v': VALUES[row - 1]} if row < 5 else
                     {'t': 'Empty'} if row == 5 else
                     {'t': 'Text', 'v': TEXT} if row == 6 else {'t': 'Bool', 'v': True})
            formula = {'text': chr(65 + col) + '2+' + chr(65 + col) + '3', 'array': None} if row == 5 else None
            rows[str(row)][str(col)] = {'value': value, 'formula': formula,
                                       'style': len(model['styles']['styles']) - 1}
    model['sheets'][0]['cells'] = {'bands': {'0': {'rows': rows}}, 'len': 56}
    model['sheets'][1]['cells'] = {'bands': {'0': {'rows': {'0': {
        '0': {'value': {'t': 'Text', 'v': 'UNEXPORTED_SOURCE'}, 'formula': None, 'style': 0}}}}}, 'len': 1}
    return model


class Table(HTMLParser):
    """Read static table bytes only; never load or execute the document."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.tags = [], None, None, []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th'):
            self.cell = {'text': '', 'attributes': dict(attrs)}

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'] += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--expect-verification', required=True, type=Path)
    parser.add_argument('--stage', choices=['collect', 'verify'], required=True)
    args = parser.parse_args()
    package, out = args.package.resolve(strict=True), args.output.absolute()
    out.mkdir(mode=0o700, exist_ok=args.stage == 'verify')
    lock = (out / 'fixture.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cases = []

    def save(name, value):
        temporary = out / (name + '.tmp')
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.replace(out / name)

    def check(value, label):
        if not value:
            raise AssertionError(label)
        cases.append(label)
        save(args.stage + '-cases.json', cases)

    env = {'HOME': str(out / 'home'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
    commands, jobs = [], []
    state = out / 'state'

    def command(label, arguments, input_text=None):
        start = time.monotonic()
        kwargs = {'stdin': subprocess.DEVNULL} if input_text is None else {'input': input_text}
        process = subprocess.run(list(map(str, arguments)), env=env, capture_output=True,
                                 text=True, timeout=600, **kwargs)
        commands.append({'label': label, 'arguments': list(map(str, arguments)),
                         'input': input_text, 'exit': process.returncode,
                         'stdout': process.stdout, 'stderr': process.stderr,
                         'seconds': time.monotonic() - start})
        save(args.stage + '-commands.json', commands)
        if process.returncode:
            raise AssertionError((label, process.returncode, process.stderr))
        return json.loads(process.stdout) if process.stdout.strip() else None

    def cli(label, *arguments):
        return command(label, [package / 'bin/a-dope-cli', '--state', state, *arguments])

    def mcp(label, name, arguments):
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                   'params': {'name': name, 'arguments': arguments}}
        response = command(label, [package / 'bin/a-dope-cli', '--state', state, 'mcp'],
                           json.dumps(request) + '\n')
        check(response.get('id') == 1 and 'error' not in response
              and not response['result'].get('isError'), label + ' MCP succeeds')
        return json.loads(response['result']['content'][0]['text'])

    def checkout(folder):
        receipt = json.loads((folder / 'project.json').read_text())
        for entry in receipt['files']:
            p = folder / entry['path']
            if p.stat().st_size != entry['bytes'] or digest(p) != entry['sha256']:
                raise AssertionError('checkout changed: ' + entry['path'])
        return receipt

    def job(label, project, operation, parameters, source=None, through_mcp=False):
        path = out / (label + '-request.json')
        save(path.name, parameters)
        if through_mcp:
            submitted = mcp(label + ' submit', 'dope_submit_job', {
                'project': project, 'operation': operation, 'parameters': parameters,
                'source_revision': source, 'idempotency_key': label})
        else:
            arguments = ['submit', project, operation, '--parameters', path, '--key', label]
            if source:
                arguments += ['--source', source]
            submitted = cli(label + ' submit', *arguments)
        record = {'label': label, 'id': submitted['id'], 'state_directory': str(state),
                  'operation': operation, 'parameters': parameters, 'source': source}
        jobs.append(record)
        save('jobs.json', jobs)
        cli(label + ' worker', 'worker', '--once')
        result = cli(label + ' result', 'job', submitted['id'])
        record['result'] = result
        save('jobs.json', jobs)
        check(result['state'] == 'succeeded' and result['attempt'] == 1,
              label + ' succeeds in one actual native attempt')
        folder = out / label
        cli(label + ' checkout', 'checkout', result['result_revision'], folder)
        receipt = checkout(folder)
        validation = receipt['validation']
        check(all(validation.get(k) for k in ('native_cold_reopen', 'native_model_equal',
              'initial_source_preserved', 'native_history_replayed', 'profile_admission_complete'))
              and not validation.get('visual_approval'), label + ' native replay validates without visual approval')
        return result['result_revision'], folder

    def parameters(folder, **extra):
        return dict(expected_sha256=digest(folder / 'native/project.dobesheets'), **extra)

    def exports(label, project, source, folder):
        for kind in ('csv', 'html'):
            source, folder = job(label + '-' + kind, project, 'sheets.export',
                                 parameters(folder, format=kind), source)
        return source, folder

    verification = command('verify package', [package / 'bin/a-dope-guard', 'verify'])
    check(verification == json.loads(args.expect_verification.read_text()) and verification['verified'],
          'exact expected package seal and guard verify')
    if args.stage == 'collect':
        (out / 'home').mkdir()
        original = create_model(package)
        save('original-model.json', original)
        project = cli('create project', 'create-project', 'Seven-format delivery')['id']
        source, folder = job('original', project, 'sheets.create', {'document': original})
        source, folder = exports('original', project, source, folder)
        edits = [{'sheet': 0, 'cell': chr(65 + c) + '2',
                  'format': {'number_format': FORMATS[(c + 1) % 7], 'bold': False, 'italic': True}}
                 for c in range(7)]
        source, folder = job('format-only', project, 'sheets.edit', parameters(folder, edits=edits), source, True)
        source, folder = exports('format-only', project, source, folder)
        edits = [{'sheet': 0, 'cell': 'A2', 'value': 1234}, {'sheet': 0, 'cell': 'A3', 'value': -234}]
        source, folder = job('value-revision', project, 'sheets.edit', parameters(folder, edits=edits), source, True)
        source, folder = exports('value-revision', project, source, folder)
        state = out / 'transferred-state'
        moved = cli('transfer project', 'import-project', folder, 'Transferred seven-format delivery')
        check(not moved['revision']['validation'].get('native_model_equal'), 'transfer claims integrity only before native replay')
        restore = [{'sheet': 0, 'cell': chr(65 + c) + '2', 'value': VALUES[0],
                    'format': {'number_format': fmt, 'bold': True, 'italic': False}}
                   for c, fmt in enumerate(FORMATS)]
        restore.append({'sheet': 0, 'cell': 'A3', 'value': VALUES[1]})
        source, folder = job('restored', moved['project']['id'], 'sheets.edit', parameters(folder, edits=restore),
                             moved['revision']['id'], True)
        source, folder = exports('restored', moved['project']['id'], source, folder)
        first = mcp('reconnected result', 'dope_get_job', {'job': jobs[-1]['id']})
        second = mcp('second reconnected result', 'dope_get_job', {'job': jobs[-1]['id']})
        check(first == second == jobs[-1]['result'], 'separate MCP clients recover the exact durable CLI result')
        save('collection.json', {'passed': True, 'jobs': len(jobs), 'checks': len(cases),
                                'verification': verification, 'completed': time.time()})
    else:
        collection = json.loads((out / 'collection.json').read_text())
        jobs = json.loads((out / 'jobs.json').read_text())
        check(collection['passed'] and collection['jobs'] == len(jobs) == 12,
              'all twelve jobs completed before read-only verification')
        original = json.loads((out / 'original-model.json').read_text())
        expected = expanded(original)
        for col in range(7):
            expected['sheets'][0]['cells']['5,' + str(col)]['value'] = {'t': 'Number', 'v': 0.0}
        models = {}
        for label in ('original', 'format-only', 'value-revision', 'restored'):
            models[label] = json.loads((out / label / 'native/document.json').read_text())
        check(expanded(models['original']) == expected,
              'creation changes only seven explicitly expected formula caches')
        rotated = copy.deepcopy(expected)
        for col in range(7):
            style = rotated['sheets'][0]['cells']['1,' + str(col)]['style']
            style['num_fmt'] = FORMATS[(col + 1) % 7]
            style['font'].update(bold=False, italic=True)
        check(expanded(models['format-only']) == rotated,
              'format-only revision changes exactly seven selected styles, with all values and formulas preserved')
        changed = copy.deepcopy(rotated)
        for key, value in [('1,0', 1234.0), ('2,0', -234.0), ('5,0', 1000.0)]:
            changed['sheets'][0]['cells'][key]['value'] = {'t': 'Number', 'v': value}
        check(expanded(models['value-revision']) == changed,
              'value revision changes only two inputs and their one expected formula cache')
        check(expanded(models['restored']) == expected,
              'transferred project restores all original cells, formulas, styles and other native fields')
        original_styles = models['original']['styles']['styles']
        for label, model in models.items():
            check(model['styles']['styles'][:len(original_styles)] == original_styles,
                  label + ' retains original style-table entries')

        csv_original = [FORMATS, *[[str(v).removesuffix('.0')] * 7 for v in VALUES],
                        ['0'] * 7, [TEXT] * 7, ['TRUE'] * 7]
        parsed = {}
        for label in models:
            folder = out / (label + '-html')
            csv_path = out / (label + '-csv') / 'exports/workbook.csv'
            actual_csv = list(csv.reader(io.StringIO(csv_path.read_text())))
            wanted_csv = copy.deepcopy(csv_original)
            if label == 'value-revision':
                wanted_csv[1][0], wanted_csv[2][0], wanted_csv[5][0] = '1234', '-234', '1000'
            check(actual_csv == wanted_csv, label + ' CSV preserves exact active-sheet raw values and quoted Unicode text')
            html = (folder / 'exports/workbook.html').read_text()
            table = Table()
            table.feed(html)
            table.close()
            parsed[label] = table.rows
            check(len(table.rows) == 8 and all(len(row) == 7 for row in table.rows),
                  label + ' static HTML table has exact active-sheet dimensions')
            check('script' not in table.tags and 'UNEXPORTED_SOURCE' not in html
                  and '&lt;script&gt;' in html and '&amp;' in html and '&quot;' in html,
                  label + ' HTML escapes literal content and excludes the other sheet')
            wanted = [list(row) for row in [FORMATS, *DISPLAY, DISPLAY[2], [TEXT] * 7, ['TRUE'] * 7]]
            if label in ('format-only', 'value-revision'):
                wanted[1] = DISPLAY[0][1:] + DISPLAY[0][:1]
            if label == 'value-revision':
                wanted[1][0], wanted[2][0], wanted[5][0] = '1234', '-234', '1000'
            check([[cell['text'] for cell in row] for row in table.rows] == wanted,
                  label + ' seven formats match fixed positive, negative, zero, fractional and formula display expectations')
            for row in range(8):
                for col in range(7):
                    style = dict(part.split(':', 1) for part in
                                 table.rows[row][col]['attributes'].get('style', '').split(';') if part)
                    bold, italic = row in (1, 4), row in (2, 4)
                    if label in ('format-only', 'value-revision') and row == 1:
                        bold, italic = False, True
                    if (style.get('font-weight') == 'bold') != bold or (style.get('font-style') == 'italic') != italic:
                        raise AssertionError((label, row, col, 'static style declaration differs'))
            check(True, label + ' all 56 cells declare the expected bold and italic styles')
            check(not json.loads((folder / 'project.json').read_text())['validation'].get('pinned_font_rendering_verified'),
                  label + ' does not claim pinned-font rendering')
        save('static-tables.json', parsed)
        for kind in ('csv', 'html'):
            name = 'exports/workbook.' + kind
            check((out / ('original-' + kind) / name).read_bytes()
                  == (out / ('restored-' + kind) / name).read_bytes(),
                  'restored ' + kind + ' is byte-identical to the original delivery')
        check((out / 'original-csv/exports/workbook.csv').read_bytes()
              == (out / 'format-only-csv/exports/workbook.csv').read_bytes(),
              'format-only revision leaves raw CSV bytes unchanged')
        original_bytes = (out / 'original/native/original.json').read_bytes()
        check(json.loads(original_bytes) == original, 'retained original contains the exact authored model')
        for record in jobs:
            folder = out / record['label']
            receipt = checkout(folder)
            check((folder / 'native/original.json').read_bytes() == original_bytes,
                  record['label'] + ' preserves exact original source bytes and checkout receipts')
            if record['operation'] == 'sheets.export':
                parent = record['label'].rsplit('-', 1)[0]
                check((folder / 'native/project.dobesheets').read_bytes()
                      == (out / parent / 'native/project.dobesheets').read_bytes()
                      and receipt['validation']['delivery_verified'],
                      record['label'] + ' preserves exact editable archive and verifies native values')

        groups, snapshots = [], {}
        for state_name in ('state', 'transferred-state'):
            database = out / state_name / 'studio.sqlite3'
            check(not Path(str(database) + '-wal').exists(), state_name + ' has no pending SQLite WAL')
            before = digest(database)
            copy_path = out / (state_name + '-snapshot.sqlite3')
            copy_path.write_bytes(database.read_bytes())
            with sqlite3.connect(copy_path.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
                db.row_factory = sqlite3.Row
                check(tuple(db.execute('PRAGMA quick_check').fetchone()) == ('ok',), state_name + ' database integrity passes')
                snapshot = {name: [dict(row) for row in db.execute('SELECT * FROM ' + name)]
                            for name in ('jobs', 'attempts', 'attempt_executions', 'revisions', 'projects')}
            check(digest(database) == before == digest(copy_path), state_name + ' query-only snapshot leaves source bytes unchanged')
            groups.extend(row['process_group'] for row in snapshot['attempt_executions'])
            snapshots[state_name] = {'sha256': before, 'tables': snapshot}
        check(len(groups) == 12 and len(set(groups)) == 12 and all(groups), 'all twelve actual native process groups are recorded')
        for group in groups:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('owned native group remains: ' + str(group))
        check(True, 'all actual native process groups are absent')
        journal_jobs = [job for snapshot in snapshots.values() for job in snapshot['tables']['jobs']]
        expected_ids = {job['id'] for job in jobs}
        native_jobs = [job for job in journal_jobs if job['id'] in expected_ids]
        transfer_jobs = [job for job in journal_jobs if job['id'] not in expected_ids]
        check(len(native_jobs) == len(expected_ids) == 12 and
              all(job['state'] == 'succeeded' and job['attempt'] == 1 for job in native_jobs),
              'query-only journals confirm one successful native attempt per Sheets job')
        check(len(transfer_jobs) == 1 and transfer_jobs[0]['operation'] == 'project.import'
              and transfer_jobs[0]['state'] == 'succeeded' and transfer_jobs[0]['attempt'] == 0,
              'portable transfer has its own durable integrity-only record without a native attempt')
        save('journal-snapshots.json', snapshots)
        check(command('verify package after', [package / 'bin/a-dope-guard', 'verify']) == verification,
              'complete sealed package remains unchanged')
        save('evidence.json', {'passed': True, 'collection_checks': collection['checks'],
             'verification_checks': len(cases), 'sheets_jobs': len(jobs),
             'durable_jobs': len(journal_jobs), 'formats': FORMATS,
             'native_groups': groups, 'all_native_groups_absent': True, 'verification': verification,
             'browser_used': False, 'rendered_html_qualified': False, 'owner_visual_approval': False,
             'general_xlsx_qualified': False, 'linux_cloud_qualified': False, 'full_release_qualified': False})
    print(json.dumps({'stage': args.stage, 'passed': True, 'checks': len(cases)}))


if __name__ == '__main__':
    main()
