"""Qualify all seven Sheets operations through a sealed package's public CLI.

Run with bundled Python: sheets_acceptance.py PACKAGE NEW_OUTPUT [--resume].
Original workbook recipes and refusal inputs are generated locally. No network, editor windows or service installation. Completed jobs are
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
import csv
from html.parser import HTMLParser

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
package = args.package.resolve(strict=True)
sys.path.insert(0, str(package / 'lib/dobe/runtime'))
from studio_runtime import sheets_source, sheets_project
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
          and v['source_backed'] and v['native_history_replayed'] and v['profile_admission_complete']
          and not v['general_admission_complete'] and not v['visual_approval'],
          label + ' preserves source and complete native model through cold history replay')
    old['checkout'] = str(destination)
    save('jobs.json', jobs)
    return result['result_revision'], destination


def model(directory):
    return json.loads((directory / 'native/document.json').read_text())


def portable(directory):
    return directory / 'native/project.dobesheets'


def request(directory, **values):
    return {'expected_sha256': digest(portable(directory)), **values}


def coordinate(address):
    letters = ''.join(c for c in address if c.isalpha()).upper()
    col = 0
    for char in letters: col = col * 26 + ord(char) - 64
    return int(address[len(letters):]) - 1, col - 1


def cells(document, sheet=0):
    return {(int(row), int(col)): cell for band in document['sheets'][sheet]['cells']['bands'].values()
            for row, columns in band['rows'].items() for col, cell in columns.items()}


def cell(document, address, sheet=0):
    return cells(document, sheet)[coordinate(address)]


def value(document, address, expected, sheet=0):
    actual = cell(document, address, sheet)['value']
    tag = 'Bool' if type(expected) is bool else 'Number' if type(expected) in (int, float) else 'Text'
    assert actual == {'t': tag, 'v': expected}, (address, actual, expected)


def normalized(document):
    result = copy.deepcopy(document)
    styles = result.pop('styles')['styles']
    for index, sheet in enumerate(result['sheets']):
        sheet['cells'] = {str(row)+','+str(col): {**copy.deepcopy(c), 'style': copy.deepcopy(styles[c['style']])}
                          for (row, col), c in cells(document, index).items()}
    return result


def predict(before, after, edits, recalculated):
    """Independent full-model oracle, using explicit numeric expectations only."""
    expected = normalized(before)
    for edit in edits:
        si = edit['sheet']; row, col = coordinate(edit['cell']); key = str(row)+','+str(col)
        target = expected['sheets'][si]['cells'].get(key, {'value': {'t':'Empty'}, 'formula':None,
                   'style':copy.deepcopy(before['styles']['styles'][0])})
        if 'value' in edit:
            v = edit['value']; tag = 'Empty' if v is None else 'Bool' if type(v) is bool else 'Number' if type(v) in (int,float) else 'Text'
            target['value'] = {'t':tag} if v is None else {'t':tag,'v':float(v) if tag=='Number' else v}
            target['formula'] = None
        if 'formula' in edit: target['formula'] = {'text':edit['formula'], 'array':None}
        fmt = edit.get('format', {})
        for name in ('bold','italic'):
            if name in fmt: target['style']['font'][name] = fmt[name]
        if 'number_format' in fmt: target['style']['num_fmt'] = fmt['number_format']
        if target == {'value':{'t':'Empty'},'formula':None,'style':before['styles']['styles'][0]}:
            expected['sheets'][si]['cells'].pop(key, None)
        else: expected['sheets'][si]['cells'][key] = target
    for si, address, tag, amount in recalculated:
        row,col = coordinate(address)
        expected['sheets'][si]['cells'][str(row)+','+str(col)]['value'] = {'t':tag,'v':amount}
    assert normalized(after) == expected, 'unexpected authored or calculated workbook change'
    assert after['styles']['styles'][:len(before['styles']['styles'])] == before['styles']['styles'], 'existing style table changed'


def stable_source(before, after):
    for name in ('native/original.json','recipes/origin-sheets-operation.json','recipes/sheets-production.json'):
        if (before/name).exists(): assert (after/name).read_bytes() == (before/name).read_bytes(), name


def totals(directory, numbers):
    d = model(directory)
    for address, amount in zip(('D3','D4','D5','D7','D8','D9'),numbers): value(d,address,amount)
    check(True,directory.name+' matches independently calculated line, subtotal, tax and total values')


def export(label, project, revision, directory, kind):
    result, folder = job(label,project,'sheets.export',request(directory,format=kind),revision)
    check(portable(folder).read_bytes() == portable(directory).read_bytes(),label+' preserves exact portable history')
    check(json.loads((folder/'project.json').read_text())['validation']['delivery_verified'],label+' verifies native values before delivery')
    return result,folder


class Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.rows=[]; self.current=None; self.buffer=None; self.scripts=0
    def handle_starttag(self,tag,attrs):
        if tag=='script': self.scripts+=1
        if tag=='tr': self.current=[]
        if tag in ('td','th'): self.buffer=[]
    def handle_data(self,data):
        if self.buffer is not None: self.buffer.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.buffer is not None:
            self.current.append(''.join(self.buffer)); self.buffer=None
        if tag=='tr' and self.current is not None:
            self.rows.append(self.current); self.current=None


def csv_values(directory, expected):
    rows = list(csv.reader(io.StringIO((directory/'exports/workbook.csv').read_text())))
    for address, desired in expected.items():
        row,col=coordinate(address); assert rows[row][col]==desired,(address,rows[row][col],desired)
    check(True,directory.name+' independently parses exact CSV values and quoted Unicode text')
    return rows


def import_asset(label, owner, data, extension):
    path=out/'sources'/(label+'.'+extension); immutable(path,data)
    return call(label+' asset','import-asset',owner,path)['id']


def refuse(label, operation, parameters, source, expected):
    before=call(label+' old head','project',owner)['head']
    result=job(label,owner,operation,parameters,source,success=False)
    check(expected in result['error']['message'],label+' reports the expected refusal')
    check(call(label+' current head','project',owner,fresh=True)['head']==before,label+' leaves project head unchanged')


def admission(label, project, operation, parameters, source, expected):
    path=out/(label+'-request.json'); immutable(path,(json.dumps(parameters,sort_keys=True)+'\n').encode())
    arguments=[cli,'--state',state,'submit',project,operation,'--parameters',path,'--key',label]
    if source: arguments+=['--source',source]
    run(label+' refusal',arguments,expected=1)
    entry=next(x for x in logs if x['label']==label+' refusal')
    check(expected in entry['stderr'],label+' is refused before job admission')


verification=run('verify payload before',[package/'bin/a-dope-guard','verify'],fresh=True)
check(verification['verified'],'complete sealed payload verifies before Sheets acceptance')
save('verification-before.json',verification)
creation={'recipe':'production_budget','version':1,'title':'ATELIER / 02 — <study> & light','currency':'EUR','tax_rate':.2,
          'items':[{'name':'Porcelain — stills','quantity':10,'unit_price':12.5},
                   {'name':'Motion, "quiet"\nloop','quantity':4,'unit_price':20},
                   {'name':'Packaging / façade','quantity':2,'unit_price':35.75}]}
owner=call('budget project','create-project','ATELIER / 02 editable budget')['id']
r0,d0=job('original',owner,'sheets.create',creation)
original=model(d0);total0=(125.,80.,71.5,276.5,55.3,331.8);totals(d0,total0)
check([s['name'] for s in original['sheets']]==['Budget','Rates'],'recipe retains separate editable Budget and Rates sheets')
value(original,'A4',creation['items'][1]['name']);value(original,'B2',.2,1)
check(cell(original,'D8')['formula']['text']=='ROUND(D7*Rates!B2,2)','tax remains an editable cross-sheet formula')
r0csv,d0csv=export('original-csv',owner,r0,d0,'csv')
csv_values(d0csv,{'A1':creation['title'],'A4':creation['items'][1]['name'],'D9':'331.8'})
r0html,d0html=export('original-html',owner,r0csv,d0csv,'html')
html0=(d0html/'exports/workbook.html').read_text();table=Table();table.feed(html0)
check(table.scripts==0 and any(creation['title'] in row for row in table.rows)
      and '&lt;study&gt;' in html0 and '331.80' in html0,'HTML escapes authored markup and displays the formatted budget')

edits=[{'sheet':0,'cell':'B3','value':12},{'sheet':0,'cell':'C4','value':22.5},
       {'sheet':1,'cell':'B2','value':.25},{'sheet':0,'cell':'A3','format':{'italic':True}}]
r1,d1=job('quantity-price-rate',owner,'sheets.edit',request(d0html,edits=edits),r0html)
total1=(150.,90.,71.5,311.5,77.88,389.38);totals(d1,total1)
predict(original,model(d1),edits,[(0,a,'Number',v) for a,v in zip(('D3','D4','D5','D7','D8','D9'),total1)])
stable_source(d0,d1);check(True,'quantity, price, rate and style revision preserves all unrelated fields and original inputs')
r1csv,d1csv=export('revised-csv',owner,r1,d1,'csv');csv_values(d1csv,{'D9':'389.38','B3':'12','C4':'22.5'})
r1html,d1html=export('revised-html',owner,r1csv,d1csv,'html')
formula_edits=[{'sheet':0,'cell':'D5','formula':'ROUND(B5*C5*0.9,2)'}]
r2,d2=job('formula-revision',owner,'sheets.edit',request(d1html,edits=formula_edits),r1html)
total2=(150.,90.,64.35,304.35,76.09,304.35+76.09);totals(d2,total2)
predict(model(d1),model(d2),formula_edits,[(0,a,'Number',v) for a,v in zip(('D3','D4','D5','D7','D8','D9'),total2)])
check(True,'formula revision preserves every other authored field and calculates exact expected dependents')
round_total=[{'sheet':0,'cell':'D9','formula':'ROUND(D7+D8,2)'}]
rrounded,drounded=job('rounded-total',owner,'sheets.edit',request(d2,edits=round_total),r2)
predict(model(d2),model(drounded),round_total,[(0,'D9','Number',380.44)])
check(True,'explicit total rounding removes binary64 addition residue without changing other cells')
r2,d2=rrounded,drounded
r3,d3=job('calculated',owner,'sheets.calculate',request(d2),r2)
check(model(d3)==model(d2),'explicit calculation leaves already-correct complete model unchanged')
r2csv,d2csv=export('final-csv',owner,r3,d3,'csv');csv_values(d2csv,{'D5':'64.35','D9':'380.44'})
r2html,d2html=export('final-html',owner,r2csv,d2csv,'html')
check('380.44' in (d2html/'exports/workbook.html').read_text(),'final HTML shows the revised total')
rinspect,dinspect=job('inspected',owner,'sheets.inspect',{},r2html)
rb,db=job('bundled',owner,'sheets.bundle',{},rinspect)
check(portable(db).read_bytes()==portable(d3).read_bytes()==(db/'exports/workbook.dobesheets').read_bytes(),'inspect and bundle preserve exact current native history')

# Transfer complete ownership to a second state, then reverse all authored changes.
state=out/'portable-state'
moved=call('portable transfer','import-project',db,'Portable production budget')
check(not moved['revision']['validation'].get('native_model_equal',False),'whole-project import claims integrity only until native reopening')
restore=[{'sheet':0,'cell':'B3','value':10},{'sheet':0,'cell':'C4','value':20},{'sheet':1,'cell':'B2','value':.2},
         {'sheet':0,'cell':'A3','format':{'italic':False}},{'sheet':0,'cell':'D5','formula':'ROUND(B5*C5,2)'},{'sheet':0,'cell':'D9','formula':'D7+D8'}]
rrestore,drestore=job('portable-restored',moved['project']['id'],'sheets.edit',request(db,edits=restore),moved['revision']['id'])
check(normalized(model(drestore))==normalized(original),'portable revision restores every original authored cell, style and cached value')
stable_source(d0,drestore)
rrcsv,drcsv=export('restored-csv',moved['project']['id'],rrestore,drestore,'csv')
check((drcsv/'exports/workbook.csv').read_bytes()==(d0csv/'exports/workbook.csv').read_bytes(),'restored portable budget delivers byte-identical original CSV')
state=out/'state'

for kind,data in [('json',(d0/'native/document.json').read_bytes()),('dobesheets',portable(db).read_bytes())]:
    recipient=call(kind+' project','create-project','Budget '+kind+' import')['id']
    asset=import_asset(kind,recipient,data,kind)
    ri,di=job(kind+'-import',recipient,'sheets.import',{'asset':asset,'format':kind})
    check(model(di)==(original if kind=='json' else model(db)),kind+' import preserves complete native model')
    check((di/'native/original.json').read_bytes()==data if kind=='json' else portable(di).read_bytes()==data,kind+' retains exact imported bytes')

# Independent fixed-value oracle covers every declared scalar function family.
lab=call('formula lab project','create-project','Scalar formula qualification')['id']
rl,dl=job('formula-lab',lab,'sheets.create',{'document':original})
formula_cases=[('SUM(B3:B5)',16.),('AVERAGE(B3:B5)',16./3),('MIN(B3:B5)',2.),('MAX(B3:B5)',10.),
               ('COUNT(B3:B5)',3.),('COUNTA(A3:A5)',3.),('IF(B3>5,7,9)',7.),('IFERROR(1/0,42)',42.),
               ('ROUND(2.125,2)',2.13),('ABS(-8)',8.),('B3>=10',True),('1/0','Div0')]
labedits=[{'sheet':0,'cell':'F'+str(i+1),'formula':f} for i,(f,_) in enumerate(formula_cases)]
labedits += [{'sheet':0,'cell':'G1','value':True},{'sheet':0,'cell':'G2','value':'Åäö — line\n"quoted", text'},
             {'sheet':0,'cell':'G3','value':17}]
rl2,dl2=job('scalar-formulas',lab,'sheets.edit',request(dl,edits=labedits),rl)
recalculated=[]
for i,(_,amount) in enumerate(formula_cases):
    tag='Bool' if type(amount) is bool else 'Error' if type(amount) is str else 'Number'
    assert cell(model(dl2),'F'+str(i+1))['value']=={'t':tag,'v':amount}
    recalculated.append((0,'F'+str(i+1),tag,amount))
predict(model(dl),model(dl2),labedits,recalculated)
check(True,'all declared scalar functions, comparisons and division error match independent expected values')
rlcsv,dlcsv=export('scalar-csv',lab,rl2,dl2,'csv')
csv_values(dlcsv,{'G2':'Åäö — line\n"quoted", text','G3':'17'})
clear=[{'sheet':0,'cell':'G'+str(i),'value':None} for i in range(1,4)]
rlclear,dlclear=job('cleared-scalars',lab,'sheets.edit',request(dlcsv,edits=clear),rlcsv)
predict(model(dl2),model(dlclear),clear,[])
check(all(coordinate('G'+str(i)) not in cells(model(dlclear)) for i in range(1,4)),'clearing scalar cells restores sparse storage without changing formulas')

refuse('stale-hash','sheets.calculate',{'expected_sha256':'0'*64},rb,'portable hash is stale')
refuse('unsupported-atomic','sheets.edit',request(db,edits=[{'sheet':0,'cell':'B3','value':99},
       {'sheet':0,'cell':'D3','formula':'WEBSERVICE("https://invalid.example")'}]),rb,'outside the supported profile')
refuse('missing-sheet','sheets.edit',request(db,edits=[{'sheet':7,'cell':'A1','value':99}]),rb,'sheet index outside workbook')
admission('precision-loss',owner,'sheets.edit',request(db,edits=[{'sheet':0,'cell':'B3','value':2**53+1}]),rb,'lose integer precision')
admission('invalid-address',owner,'sheets.edit',request(db,edits=[{'sheet':0,'cell':'A513','value':1}]),rb,'supported grid')

# Rehashed forged cache must fail real native replay, not merely checksum validation.
forged=sheets_project.inspect_bytes(portable(db).read_bytes());manifest=copy.deepcopy(forged['manifest'])
members={k:v for k,v in forged['members'].items() if k!='project.json'};step=manifest['history'][-1]
fake_model=json.loads(members[step['state']]);cell(fake_model,'D9')['value']={'t':'Number','v':1.0}
fake=sheets_source.encoded(fake_model);members[step['state']]=fake;members['document.json']=fake
step['after']=sheets_source.sha(fake);manifest['current']=sheets_source.sha(fake)
for name in (step['state'],'document.json'):manifest['members'][name]=sheets_project.record(fake)
forged_data=sheets_project.pack(manifest,members);badowner=call('forged project','create-project','Refuse forged cache')['id']
badasset=import_asset('forged',badowner,forged_data,'dobesheets')
bad=job('forged-cache',badowner,'sheets.import',{'asset':badasset,'format':'dobesheets'},success=False)
check('native history replay differs' in bad['error']['message'],'rehashed forged formula cache is refused by native replay')
check(call('forged head','project',badowner)['head'] is None,'forged import publishes no initial head')
admission('cross-project',owner,'sheets.import',{'asset':badasset,'format':'dobesheets'},None,'asset')

# History-free import preserves unproven caches; export must refuse until calculation.
uncalculated=sheets_project.create(fake,engine=sheets_project.PIN)
rawowner=call('uncalculated project','create-project','Unproven formula caches')['id']
rawasset=import_asset('uncalculated',rawowner,uncalculated,'dobesheets')
ru,du=job('uncalculated-import',rawowner,'sheets.import',{'asset':rawasset,'format':'dobesheets'})
check(not json.loads((du/'project.json').read_text())['validation']['native_calculation_verified']
      and portable(du).read_bytes()==uncalculated,'history-free import preserves exact bytes without claiming calculation')
failed_export=job('uncalculated-export',rawowner,'sheets.export',request(du,format='csv'),ru,success=False)
check('caches are stale' in failed_export['error']['message'] and call('uncalculated head','project',rawowner)['head']==ru,
      'stale-cache export refuses without changing the imported head')
rclean,dclean=job('repaired-cache',rawowner,'sheets.calculate',request(du),ru)
check(model(dclean)==model(db) and (dclean/'native/original.json').read_bytes()==fake,
      'explicit calculation repairs the false total and preserves the exact stale original')
rclean_csv,dclean_csv=export('repaired-csv',rawowner,rclean,dclean,'csv')
csv_values(dclean_csv,{'D9':'380.44'})

# Fresh MCP clients discover the same operations and retrieve the CLI job.
def mcp(label,method,params):
    message=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n'
    p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=message,text=True,capture_output=True,env=env,timeout=30)
    assert p.returncode==0,(label,p.stderr)
    response=json.loads(p.stdout);assert 'error' not in response,response
    save(label+'.json',response);return response['result']
tools=mcp('mcp-discovery','tools/list',{})['tools']
operations=next(t for t in tools if t['name']=='dope_submit_job')['inputSchema']['properties']['operation']['enum']
check(len(tools)==18 and set('sheets.'+x for x in ('create','import','inspect','edit','calculate','export','bundle'))<=set(operations),'same eighteen MCP tools expose all seven Sheets operations')
request_mcp={'name':'dope_get_job','arguments':{'job':jobs[0]['id']}}
first=mcp('mcp-first','tools/call',request_mcp);second=mcp('mcp-reconnected','tools/call',request_mcp)
check(first==second and json.loads(first['content'][0]['text'])['state']=='succeeded','disconnected MCP clients retrieve the same durable CLI result')

groups=[]
for directory in (out/'state',out/'portable-state'):
    with sqlite3.connect('file:'+str(directory/'studio.sqlite3')+'?mode=ro',uri=True) as db:
        check(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],directory.name+' database integrity passes')
        groups += [r[0] for r in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
for group in groups:
    try:os.killpg(group,0)
    except ProcessLookupError:pass
    else:raise AssertionError('native execution group remains: '+str(group))
check(len(groups)==len(jobs),'every durable native execution group is accounted for and absent')
for record in jobs:
    if 'checkout' in record:verify_checkout(Path(record['checkout']))
check(True,'all successful checkout receipts remain exact')
check(run('verify payload after',[package/'bin/a-dope-guard','verify'],fresh=True)==verification,'entire sealed package remains unchanged')
save('context.json',{'creation':creation,'edits':edits,'formulaEdits':formula_edits,'roundTotal':round_total,'restore':restore,
                    'originalTotals':total0,'revisedTotals':total1,'preRoundingTotals':total2,'finalTotals':list(total2[:-1])+[380.44],'formulaCases':formula_cases})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'durableJobs':len(jobs),'admissionRefusals':3,
 'successfulJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedJobs':sum(j['result']['state']=='failed' for j in jobs),
 'operations':sorted({j['operation'] for j in jobs}),'allNativeGroupsAbsent':True,'groups':groups,'verification':verification,
 'ownerVisualApproval':False,'generalXLSXFidelityQualified':False,'completeReleaseQualified':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'durableJobs':len(jobs)}))
