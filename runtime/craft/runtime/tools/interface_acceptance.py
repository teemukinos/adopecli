"""Qualify a bounded editable Interface suite through an installed sealed CLI.

Run with the package's private Python (which includes Pillow), the explicit
package directory and a new output directory. No installation, service changes,
network requests or editor windows are needed. All work uses private states.

The fixture covers all four Interface operations, a native Vector handoff,
component propagation, instance overrides, clipping, exact pixels, portable
revision, MCP disconnection/replay and bounded failure without publication.
Evidence remains in the output directory if a check fails. Inspect its durable
job records before continuing; never restart an uncertain native job.

This is one application profile, not complete application or release approval.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('package',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
root=Path(__file__).resolve().parents[3]
package=args.package.resolve(strict=True)
out=args.output.absolute()
out.mkdir(parents=True,exist_ok=False,mode=0o700)
(out/'home').mkdir(mode=0o700)
cli=package/'bin/a-dope-cli'
state=out/'state'
env={'HOME':str(out/'home'),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'}
logs=[];jobs=[];cases=[]

def save(name,value):(out/name).write_text(json.dumps(value,indent=2)+'\n')
def check(value,label):assert value,label;cases.append(label);save('cases.json',cases)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run(label,args,expected=0):
 started=time.monotonic();p=subprocess.run(list(map(str,args)),stdin=subprocess.DEVNULL,env=env,capture_output=True,text=True,timeout=600);logs.append({'label':label,'args':list(map(str,args)),'exit':p.returncode,'seconds':time.monotonic()-started,'stdout':p.stdout,'stderr':p.stderr});save('commands.json',logs);assert p.returncode==expected,(label,p.returncode,p.stderr);return json.loads(p.stdout) if p.stdout.strip() else None
def call(label,*args,expected=0):return run(label,[cli,'--state',state,*args],expected)
def job(label,project,operation,parameters,source_revision=None,success=True):
 request=out/(label+'-request.json');request.write_text(json.dumps(parameters));args=['submit',project,operation,'--parameters',request,'--key',label]
 if source_revision:args+=['--source',source_revision]
 ident=call(label+' submit',*args)['id'];call(label+' worker','worker','--once');value=call(label+' result','job',ident);jobs.append({'label':label,'stateDirectory':str(state),'operation':operation,'parameters':parameters,'result':value});save('jobs.json',jobs);assert value['state']==('succeeded' if success else 'failed'),value
 if not success:check(value.get('result_revision') is None,label+' publishes no result revision');return value
 revision=value['result_revision'];destination=out/label;call(label+' export','checkout',revision,destination);manifest=json.loads((destination/'project.json').read_text())
 for f in manifest['files']:
  data=(destination/f['path']).read_bytes();assert len(data)==f['bytes'] and hashlib.sha256(data).hexdigest()==f['sha256'],f
 check(manifest['validation']['native_cold_reopen'],label+' cold reopens native source')
 jobs[-1]['checkout']=str(destination);save('jobs.json',jobs);return revision,destination


verification=run('verify installed payload',[package/'bin/a-dope-guard','verify']);save('verification-before.json',verification)
check(verification['verified'],'installed sealed package verifies before native jobs')
lock=json.loads((root/'craft/engines/interface.lock.json').read_text());manifest=json.loads((package/'lib/dobe/engines/interface/engine.json').read_text());check(manifest['source_lock']==lock,'installed Interface engine binds the maintained source lock')
mark={'width':64,'height':64,'objects':[{'type':'rectangle','name':'bar-'+str(i),'x':8+16*i,'y':8,'width':8,'height':48-16*i,'color':'#1A4FFF'} for i in range(3)]}
vp=call('create mark project','create-project','Interface suite mark')['id'];vr,vd=job('vector-mark',vp,'vector.create',mark)
p=call('create interface project','create-project','Editable campaign suite')['id'];save('projects.json',{'vector':vp,'interface':p})
asset=call('import exact native mark','import-asset',p,vd/'exports/document.png')['id']
def node(name,kind,x,y,w,h,parent=None,**props):
 d={'name':name,'type':kind,'x':x,'y':y,'width':w,'height':h,**props}
 if parent is not None:d['parent']=parent
 return d
def text_node(name,value,x,y,w,h,size,parent,color='#18202A'):
 return node(name,'text',x,y,w,h,parent,text=value,font_family='Inter',font_style='Regular',font_size=size,color=color,text_resize='fixed')
nodes=[
 node('asset-card','component',850,0,288,240,color='#F2F0EA',radius=20,clip=True),
 node('card-mark','image',24,24,48,48,'asset-card',asset=asset,fit='contain'),
 text_node('card-title','Editable',24,112,240,40,28,'asset-card'),
 text_node('card-copy','Source stays with you.',24,164,240,48,18,'asset-card'),
 node('campaign','frame',0,0,720,720,color='#18202A',clip=True),
 node('campaign-mark','image',48,40,48,48,'campaign',asset=asset,fit='contain'),
 text_node('headline-one','One brief.',48,132,624,72,56,'campaign','#F2F0EA'),
 text_node('headline-two','A whole suite.',48,204,624,72,56,'campaign','#F2F0EA'),
 text_node('subheading','Native assets. Precise revisions.',48,288,624,32,20,'campaign','#AAB3BF'),
 node('card-left','instance',48,336,288,240,'campaign',component='asset-card'),
 node('card-right','instance',384,336,288,240,'campaign',component='asset-card'),
 node('footer-rule','rectangle',48,608,624,1,'campaign',color='#58616C'),
 text_node('footer','A dope CLI / Editable source / 01',48,632,624,32,18,'campaign','#AAB3BF'),
 node('identity','frame',0,800,320,320,color='#F2F0EA',clip=True),
 node('identity-mark','image',128,80,64,64,'identity',asset=asset,fit='contain'),
 text_node('identity-name','A dope CLI',64,176,224,48,30,'identity'),
 text_node('identity-detail','Make. Revise. Keep.',64,236,224,32,18,'identity','#58616C'),
 node('crop-window','frame',240,32,32,32,'identity',color='#F2F0EA',clip=True),
 node('crop-bar','rectangle',16,0,32,32,'crop-window',color='#1A4FFF'),
]
params={'title':'A dope CLI / Editable suite','nodes':nodes,'previews':['campaign','identity']}
r,d=job('original',p,'interface.create',params)
save('context.json',{'project':p,'revision':r,'delivery':str(d),'vectorProject':vp,'vectorRevision':vr,'vectorDelivery':str(vd),'markAsset':asset,'parameters':params,'markParameters':mark})
print(json.dumps({'created':True,'delivery':str(d),'checks':len(cases),'nativeJobs':len(jobs)}))

import zipfile
from PIL import Image,ImageChops
context=json.loads((out/'context.json').read_text());project=context['project'];original=Path(context['delivery'])
def native(directory):
 with zipfile.ZipFile(directory/'native/document.figcraft') as z:return json.loads(z.read('document.json')),{n:z.read(n) for n in z.namelist() if n.startswith('images/')}
def mapping(directory):return json.loads((directory/'native/objects.json').read_text())
def preview(directory,name):
 return Image.open(directory/'exports'/('node-'+str(mapping(directory)[name]['id'])+'.png')).convert('RGBA')
def target(directory,name,parent):
 doc,_=native(directory);ids={node['id'] for node in doc['nodes'].values() if node['name']==parent};nodes=[n for n in doc['nodes'].values() if n['name']==name and n.get('parent') in ids];assert len(nodes)==1
 return next(key for key,value in mapping(directory).items() if value['id']==nodes[0]['id'])
def text_edit(name,expected,value):return {'name':name,'action':'replace_text','expected':expected,'text':value}
def snapshot(directory):return {str(p.relative_to(directory)):digest(p) for p in directory.rglob('*') if p.is_file()}
def next_job(label,operation,params,source,project_id=project):
 prior=next((x for x in jobs if x['label']==label),None)
 if prior:
  assert prior['operation']==operation and prior['parameters']==params and prior['result']['state']=='succeeded'
  return prior['result']['result_revision'],Path(prior['checkout'])
 return job(label,project_id,operation,params,source)
def retain(key,value):context[key]=value;save('context.json',context)
base,assets=native(original);original_hashes=snapshot(original);mark=Path(context['vectorDelivery'])/'exports/document.png'
check(assets=={'images/'+digest(mark):mark.read_bytes()},'native Interface embeds the exact Vector PNG once for every linked use')
check(preview(original,'campaign').size==(720,720) and preview(original,'identity').size==(320,320),'both selected artboards export at exact requested dimensions')
tile=preview(original,'identity');check(tile.getpixel((264,48))==(26,79,255,255) and tile.getpixel((280,48))==(242,240,234,255),'nested frame clips the overflowing rectangle at its exact right edge')
expected=Image.new('RGBA',(64,64),(242,240,234,255));expected.alpha_composite(Image.open(mark).convert('RGBA'));check(tile.crop((128,80,192,144)).tobytes()==expected.tobytes(),'native embedded artwork reproduces exact source pixels over the requested background')
right_title=target(original,'card-title','card-right');right_copy=target(original,'card-copy','card-right');main_title=target(original,'card-title','asset-card');main_copy=target(original,'card-copy','asset-card')
r1,d1=next_job('instance-override','interface.edit',{'edits':[text_edit(right_title,'Editable','Shareable'),text_edit(right_copy,'Source stays with you.','Exports ready to use.')],'previews':['campaign','identity']},context['revision'])
diff=ImageChops.difference(preview(original,'campaign'),preview(d1,'campaign')).convert('RGB');bounds=diff.getbbox();check(bounds is not None and bounds[0]>=408 and bounds[1]>=448 and bounds[2]<=648 and bounds[3]<=548,'instance text overrides change pixels only inside the requested right-card text regions')
r2,d2=next_job('component-revision','interface.edit',{'edits':[text_edit(main_title,'Editable','Revisable'),text_edit(main_copy,'Source stays with you.','Change only what matters.'),{'name':'asset-card','action':'fill','expected':'#F2F0EA','color':'#DDE5F2'}],'previews':['campaign','identity']},r1)
changed,changed_assets=native(d2);assert changed_assets==assets
check(set(base['nodes'])==set(changed['nodes']) and mapping(original)==mapping(d2),'all native node identities and editable mapping survive component revision')
for parent,title,body in [('asset-card','Revisable','Change only what matters.'),('card-left','Revisable','Change only what matters.'),('card-right','Shareable','Exports ready to use.')]:
 for name,value in [('card-title',title),('card-copy',body)]:
  identity=mapping(d2)[target(d2,name,parent)]['id'];check(changed['nodes'][str(identity)]['characters']==value,parent+' preserves the expected '+name)
allowed={}
for parent in ('asset-card','card-left','card-right'):
 identity=mapping(original)[parent]['id'];allowed[identity]={'fills'}
 for name in ('card-title','card-copy'):
  identity=mapping(original)[target(original,name,parent)]['id'];allowed[identity]={'characters','overrides'}
a=copy.deepcopy(base);b=copy.deepcopy(changed)
for identity,fields in allowed.items():
 for field in fields:a['nodes'][str(identity)].pop(field,None);b['nodes'][str(identity)].pop(field,None)
check(a==b,'all other native fields, geometry, source links, metadata and artwork remain exactly equal')
left=(48,336,336,576);right=(384,336,672,576);diff=ImageChops.difference(preview(original,'campaign'),preview(d2,'campaign')).convert('RGB')
for box in (left,right):diff.paste((0,0,0),box)
check(diff.getbbox() is None,'component revisions change no campaign pixels outside the two cards')
check(all(preview(d,'identity').tobytes()==tile.tobytes() for d in (d1,d2)),'untouched identity artboard remains pixel-identical through both revisions')

for parent in ('asset-card','card-left','card-right'):
 for name in ('card-title','card-copy'):
  identity=mapping(d2)[target(d2,name,parent)]['id']
  expected_overrides=[] if parent=='card-left' else ['characters']
  check(changed['nodes'][str(identity)].get('overrides',[])==expected_overrides,parent+' has only the expected character override metadata for '+name)
check(all(preview(d2,'campaign').getpixel(point)==(221,229,242,255) for point in ((180,420),(520,420))),'both component instances render the exact requested revised fill color')

r3,d3=next_job('inspect-revision','interface.inspect',{'previews':['campaign','identity']},r2)
check(native(d3)==native(d2),'inspection preserves the complete editable native document and embedded bytes')
check(all(preview(d3,name).tobytes()==preview(d2,name).tobytes() for name in ('campaign','identity')),'inspection independently cold-reopens both artboards with exact pixels')
check(original_hashes==snapshot(original),'original delivered project remains byte-identical after later jobs')
retain('revised',{'revision':r2,'delivery':str(d2),'inspectRevision':r3,'inspectDelivery':str(d3),'rightTitle':right_title,'rightCopy':right_copy,'mainTitle':main_title,'mainCopy':main_copy,'originalHashes':original_hashes})
print(json.dumps({'passed':True,'checks':len(cases),'nativeJobs':len(jobs),'revised':str(d2)}))

revised=context['revised'];source=Path(revised['delivery']);source_hashes=snapshot(source)
# Native import exercises the native-file contract independently of portable manifests.
np=call('native import project','create-project','Native Interface import')['id'];na=call('native import asset','import-asset',np,source/'native/document.figcraft')['id']
nr,nd=job('native-import',np,'interface.import',{'asset':na,'previews':['campaign','identity','crop-bar']})
check(native(nd)==native(source),'native import preserves every native field and embedded image')
for name in ('campaign','identity'):check(preview(nd,name).tobytes()==preview(source,name).tobytes(),'native import exactly reproduces '+name+' pixels')
bar=preview(nd,'crop-bar');check(bar.size==(32,32) and bar.getextrema()==((26,26),(79,79),(255,255),(255,255)),'explicit child preview exports its subtree without ancestor clipping, as documented')
# A fresh private state receives the portable project. The submitting MCP client exits first.
state=out/'portable-state';imported=call('portable import','import-project',source,'Portable editable suite');pp=imported['project']['id'];pr=imported['revision']['id']
check(imported['revision']['validation']=={'passed':True,'scope':'bundle_integrity','native_cold_reopen':False},'portable import records integrity only until a new native job runs')
params={'edits':[text_edit(revised['mainTitle'],'Revisable','Editable')],'previews':['campaign','identity']}
request={'project':pp,'operation':'interface.edit','parameters':params,'idempotency_key':'portable-mcp','source_revision':pr}
messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'interface-qualification','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'dope_submit_job','arguments':request}}]
def mcp_submit(label):
 start=time.monotonic();p=subprocess.run([str(cli),'--state',str(state),'mcp'],input=''.join(json.dumps(m)+'\n' for m in messages),env=env,capture_output=True,text=True,timeout=180)
 logs.append({'label':label,'exit':p.returncode,'seconds':time.monotonic()-start,'stdout':p.stdout,'stderr':p.stderr});save('commands.json',logs);assert p.returncode==0,p.stderr
 response=next(json.loads(line) for line in p.stdout.splitlines() if json.loads(line).get('id')==2)['result'];assert not response.get('isError'),response
 return json.loads(response['content'][0]['text'])
submitted=mcp_submit('MCP submit then disconnect');replayed=mcp_submit('MCP replay after disconnect');check(submitted['id']==replayed['id'],'independent MCP clients return one durable idempotent job')
check(call('queued after MCP exit','job',submitted['id'])['state']=='queued','native work remains queued after both submitting clients exit')
call('MCP native worker','worker','--once');value=call('MCP native result','job',submitted['id']);assert value['state']=='succeeded',value
pd=out/'portable-mcp';call('MCP portable checkout','checkout',value['result_revision'],pd);jobs.append({'label':'portable-mcp','stateDirectory':str(state),'operation':'interface.edit','parameters':params,'result':value,'checkout':str(pd)});save('jobs.json',jobs)
check(json.loads((pd/'project.json').read_text())['validation']['native_cold_reopen'],'MCP-directed portable revision reopens the native document')
right_id=mapping(pd)[revised['rightTitle']]['id'];check(native(pd)[0]['nodes'][str(right_id)]['characters']=='Shareable','portable master revision preserves the explicit instance override')
rr,rd=job('restore-instance',pp,'interface.edit',{'edits':[text_edit(revised['rightTitle'],'Shareable','Editable'),text_edit(revised['rightCopy'],'Exports ready to use.','Change only what matters.')],'previews':['campaign','identity']},value['result_revision'])
restored=native(rd)[0];check(all('characters' not in restored['nodes'][str(mapping(rd)[key]['id'])].get('overrides',[]) for key in (revised['rightTitle'],revised['rightCopy'])),'restoring current master values clears both instance overrides')
fr,fd=job('portable-propagation',pp,'interface.edit',{'edits':[text_edit(revised['mainTitle'],'Editable','Revisable'),{'name':'footer','action':'move','dx':8,'dy':0}],'previews':['campaign','identity']},rr)
final=native(fd)[0]
check(all(final['nodes'][str(mapping(fd)[target(fd,'card-title',parent)]['id'])]['characters']=='Revisable' for parent in ('asset-card','card-left','card-right')),'later master text revision propagates to both linked instances after restoration')
left=native(rd)[0];right=copy.deepcopy(final);left=copy.deepcopy(left)
for parent in ('asset-card','card-left','card-right'):
 identity=mapping(fd)[target(fd,'card-title',parent)]['id'];left['nodes'][str(identity)].pop('characters');right['nodes'][str(identity)].pop('characters')
footer=mapping(fd)['footer']['id'];a=left['nodes'][str(footer)];b=right['nodes'][str(footer)];keys={k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)}
check(keys=={'transform'} and b['transform'][:4]==a['transform'][:4] and b['transform'][4]==a['transform'][4]+8 and b['transform'][5]==a['transform'][5],'footer move changes only the requested native translation')
a.pop('transform');b.pop('transform');check(left==right,'portable revision preserves all other native fields and component links')
check(all(preview(d,'identity').tobytes()==preview(source,'identity').tobytes() for d in (pd,rd,fd)),'identity pixels remain exact through portable import, override restoration and move')
# Failure after a valid earlier edit must not partially publish.
for label,parameters,reason in [
 ('partial-batch',{'edits':[text_edit('headline-one','One brief.','A wrong partial change.'),text_edit('absent','Missing','No')],'previews':['campaign','identity']},'unknown Interface edit target'),
 ('missing-glyph',{'edits':[text_edit('headline-one','One brief.','Missing '+chr(0x10ffff))]},'text qualification')]:
 before=call(label+' head before','project',pp);failed=job(label,pp,'interface.edit',parameters,fr,False);check(reason in json.dumps(failed),label+' reports the bounded refusal');check(before==call(label+' head after','project',pp),label+' leaves the accepted project head unchanged')
# Missing font is rejected in a new project with its own authorized source asset.
bp=call('missing font project','create-project','Missing font refusal')['id'];ba=call('missing font artwork','import-asset',bp,Path(context['vectorDelivery'])/'exports/document.png')['id'];bad=copy.deepcopy(context['parameters'])
for node in bad['nodes']:
 if node['type']=='image':node['asset']=ba
 if node['type']=='text':node['font_family']='Unavailable Interface Qualification Font'
before=call('missing font head before','project',bp);failed=job('missing-font',bp,'interface.create',bad,success=False);check('font' in json.dumps(failed).lower(),'missing font fails without silent substitution');check(before==call('missing font head after','project',bp),'missing font publishes no project head')
foreign=out/'foreign.figcraft'
with zipfile.ZipFile(source/'native/document.figcraft') as reader,zipfile.ZipFile(foreign,'x',zipfile.ZIP_DEFLATED) as writer:
 for name in reader.namelist():
  data=reader.read(name)
  if name=='document.json':doc=json.loads(data);doc['unsupported_qualification_field']='must survive or fail';data=json.dumps(doc).encode()
  writer.writestr(name,data)
xp=call('foreign native project','create-project','Foreign field refusal')['id'];xa=call('foreign native asset','import-asset',xp,foreign)['id'];before=call('foreign head before','project',xp)
failed=job('foreign-native',xp,'interface.import',{'asset':xa,'previews':[]},success=False);check(before==call('foreign head after','project',xp),'silently dropped native fields cannot produce an accepted head')
check(snapshot(source)==source_hashes and snapshot(original)==revised['originalHashes'],'all earlier delivered native sources, pixels and receipts remain unchanged')
all_groups=[]
for directory in (out/'state',out/'portable-state'):
 with sqlite3.connect('file:'+str(directory/'studio.sqlite3')+'?mode=ro',uri=True) as db:groups=[x[0] for x in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
 for group in groups:
  try:os.killpg(group,0)
  except ProcessLookupError:pass
  else:raise AssertionError('native process group remains: '+str(group))
 all_groups+=groups
check(len(all_groups)==len(jobs),'every native job has an execution receipt and its process group is absent')
check(run('verify final installed payload',[package/'bin/a-dope-guard','verify'])==json.loads((out/'verification-before.json').read_text()),'all successful and refused jobs leave the installed payload unchanged')

for record in jobs:
 if 'checkout' not in record:continue
 directory=Path(record['checkout']);receipt=json.loads((directory/'project.json').read_text())
 for item in receipt['files']:
  data=(directory/item['path']).read_bytes()
  assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],item
check(True,'every successful checkout, including the MCP result, matches every artifact length and hash')

retain('portableFinal',{'revision':fr,'delivery':str(fd),'project':pp});save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'nativeJobs':len(jobs),'successfulNativeJobs':sum(x['result']['state']=='succeeded' for x in jobs),'expectedFailedNativeJobs':sum(x['result']['state']=='failed' for x in jobs),'groups':all_groups,'allNativeGroupsAbsent':True,'package':str(package),'verification':json.loads((out/'verification-before.json').read_text()),'wholeInterfaceQualified':False,'completeReleaseQualified':False,'ownerDesignApproval':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'nativeJobs':len(jobs),'delivery':str(source)}))
