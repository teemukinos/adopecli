"""Qualify exact Layout artwork revision through a private sealed CLI package.

Use the package's Python (Pillow included), then pass PACKAGE NEW_OUTPUT and two
720-pixel square PNGs from the Interface acceptance fixture: the original and
component-revision campaign exports. The fixture generates its own wide Vector
artwork for fitting checks. No network, installed services or editor windows.
Failed evidence remains in OUTPUT. Do not restart an uncertain native job.
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
parser.add_argument('original_artwork',type=Path)
parser.add_argument('revised_artwork',type=Path)
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

import zipfile
from PIL import Image, ImageChops

verification=run('verify package before',[package/'bin/a-dope-guard','verify']);save('verification-before.json',verification)
check(verification['verified'],'sealed package verifies before native jobs')
for name in ('layout','pdf','vector'):
 lock=json.loads((root/'craft/engines'/f'{name}.lock.json').read_text());engine=json.loads((package/'lib/dobe/engines'/name/'engine.json').read_text())
 check(engine['source_lock']==lock,name+' engine matches the maintained source lock')
original_artwork=args.original_artwork.resolve(strict=True);revised_artwork=args.revised_artwork.resolve(strict=True)
for path in (original_artwork,revised_artwork):assert Image.open(path).size==(720,720)
old_hash=digest(original_artwork);new_hash=digest(revised_artwork);assert old_hash!=new_hash
p=call('publication project','create-project','A dope CLI / Editable publication')['id']
a=call('original artwork','import-asset',p,original_artwork)['id'];b=call('revised artwork','import-asset',p,revised_artwork)['id']
def txt(name,value,rect,size,color='#18202A'):
 return {'name':name,'type':'text','rect':rect,'text':value,'font_family':'Inter','font_style':'Regular','size':size,'color':color}
params={'title':'A dope CLI / One brief. Still editable.','width':612,'height':792,'pages':[{'objects':[
 txt('brand','A dope CLI / Production notes',[36,32,576,56],12,'#1A4FFF'),
 txt('heading','One brief. Still editable.',[36,68,576,110],28),
 txt('description','Revise the artwork. Keep the publication.',[36,116,576,140],12,'#58616C'),
 {'name':'cover','type':'image','rect':[36,150,576,690],'asset':a,'fit':'contain'},
 txt('footer','01 / Native source, PDF, IDML and page previews',[36,720,576,746],11,'#58616C')]},
 {'objects':[txt('appendix-heading','Original source / retained',[36,68,576,110],28),
 {'name':'reference','type':'image','rect':[36,150,306,420],'asset':a,'fit':'contain'},
 txt('appendix-copy','This placement stays unchanged when the cover changes.',[36,452,576,486],14),
 txt('appendix-footer','02 / Independent placement, shared source artwork',[36,720,576,746],11,'#58616C')]}]}
r,d=job('original',p,'layout.create',params)
def native(directory):
 with zipfile.ZipFile(directory/'native/document.designcraft') as z:return json.loads(z.read('document.json')),{n:z.read(n) for n in z.namelist() if n.startswith('assets/')}
def mapping(directory):return json.loads((directory/'native/objects.json').read_text())
def item(state,identity):return next(i for s in state['spreads'] for i in s['items'] if i['id']==identity)
def pixels(directory,page):return Image.open(directory/'exports'/f'page-{page:03}.png').convert('RGBA')
def replacement(name,expected,asset,fit='contain'):return {'name':name,'action':'replace_image','expected_sha256':expected,'asset':asset,'fit':fit}
def snapshot(directory):return {str(f.relative_to(directory)):digest(f) for f in directory.rglob('*') if f.is_file()}
base,base_blobs=native(d);original_files=snapshot(d);ids=mapping(d);cover=ids['cover']['id'];reference=ids['reference']['id']
check(len(base['assets'])==1 and item(base,cover)['content']['asset']==item(base,reference)['content']['asset'],'creation shares one embedded asset across two independent placements')
r1,d1=job('revised',p,'layout.edit',{'edits':[replacement('cover',old_hash,b)]},r)
changed,changed_blobs=native(d1);old_id=str(item(base,cover)['content']['asset']);new_id=str(item(changed,cover)['content']['asset'])
check(changed['assets'][old_id]==base['assets'][old_id] and item(changed,reference)==item(base,reference),'replacement leaves the other shared-image placement and its asset record exact')
check(len(changed['assets'])==2 and hashlib.sha256(next(v for k,v in changed_blobs.items() if k.startswith('assets/'+new_id+'.'))).hexdigest()==new_hash,'replacement embeds exact revised artwork beside the retained original')
expected=copy.deepcopy(base);expected['nextId']+=1;expected['assets'][new_id]=changed['assets'][new_id];item(expected,cover)['content']['asset']=int(new_id)
check(expected==changed and mapping(d1)==ids,'same-size replacement changes only requested asset reference, new asset and allocation counter')
check(pixels(d1,2).tobytes()==pixels(d,2).tobytes(),'untargeted appendix remains pixel-identical')
diff=ImageChops.difference(pixels(d1,1),pixels(d,1)).convert('RGB');bounds=diff.getbbox();check(bounds is not None and bounds[0]>=36 and bounds[1]>=150 and bounds[2]<=576 and bounds[3]<=690,'cover changes only within the unchanged image frame')
check(all(json.loads((d1/'project.json').read_text())['validation'][k] for k in ('native_cold_reopen','native_state_equal','pixel_roundtrip_equal','idml_pixel_roundtrip_equal','independent_pdf_validation','source_bytes_unchanged')),'native reopening, IDML pixels, PDF inspection and source preservation all pass')
r2,d2=job('restore',p,'layout.edit',{'edits':[replacement('cover',new_hash,a)]},r1)
restored,restored_blobs=native(d2);expected=copy.deepcopy(base);expected['nextId']+=2
check(restored==expected and restored_blobs==base_blobs,'restoring a retained asset merges duplicate bytes and removes only unused revised artwork')
check(all(pixels(d2,page).tobytes()==pixels(d,page).tobytes() for page in (1,2)),'restoration reproduces both original pages exactly')
r3,d3=job('reuse-revised',p,'layout.edit',{'edits':[replacement('cover',old_hash,b)]},r2)
check(all(pixels(d3,page).tobytes()==pixels(d1,page).tobytes() for page in (1,2)),'previously retained replacement asset can be used again without a file collision')
r4,d4=job('same-image',p,'layout.edit',{'edits':[replacement('cover',new_hash,b)]},r3)
same,_=native(d4);expected=copy.deepcopy(native(d3)[0]);expected['nextId']+=1
check(same==expected and native(d4)[1]==native(d3)[1],'same-image replacement keeps existing asset identities and all document state except allocation counter')
# A non-square native Vector export distinguishes contain, cover and stretch.
vp=call('fitting vector project','create-project','Wide fitting artwork')['id']
vp_params={'width':240,'height':120,'objects':[{'type':'rectangle','name':'background','x':0,'y':0,'width':240,'height':120,'color':'#F2F0EA'},
 {'type':'rectangle','name':'left','x':0,'y':0,'width':60,'height':120,'color':'#1A4FFF'},
 {'type':'rectangle','name':'right','x':180,'y':0,'width':60,'height':120,'color':'#18202A'}]}
vr,vd=job('wide-artwork',vp,'vector.create',vp_params);wide=vd/'exports/document.png';wh=digest(wide);wa=call('wide artwork asset','import-asset',p,wide)['id']
fits={};current=r4;expected_hash=new_hash
for fit,transform in [('contain',[2.25,0,0,2.25,36,285]),('cover',[4.5,0,0,4.5,-234,150]),('stretch',[2.25,0,0,4.5,36,150])]:
 current,fd=job('fit-'+fit,p,'layout.edit',{'edits':[replacement('cover',expected_hash,wa,fit)]},current);expected_hash=wh;fits[fit]=fd
 state_doc,_=native(fd);g=item(state_doc,cover)['content']
 check(g['size']==[240,120] and g['xf']==transform,fit+' produces the independently calculated graphic transform')
 check(item(state_doc,cover)['path']==item(base,cover)['path'] and item(state_doc,cover)['xf']==item(base,cover)['xf'],fit+' preserves the frame path and transform')
 check(pixels(fd,2).tobytes()==pixels(d,2).tobytes(),fit+' preserves unrelated appendix pixels')
check(pixels(fits['contain'],1).getpixel((100,200))==(255,255,255,255) and pixels(fits['contain'],1).getpixel((100,400))==(26,79,255,255),'contain centers the whole wide artwork with white space above')
check(pixels(fits['cover'],1).crop((40,154,572,686)).getextrema()==((242,242),(240,240),(234,234),(255,255)) and pixels(fits['cover'],1).getpixel((30,400))==(255,255,255,255),'cover crops the enlarged artwork at the unchanged frame')
check(pixels(fits['stretch'],1).getpixel((100,200))==(26,79,255,255),'stretch fills the frame without preserving the source aspect ratio')
# Replace both placements in one batch; no unrelated native fields may change.
br,bd=job('shared-batch',p,'layout.edit',{'edits':[replacement('cover',wh,b),replacement('reference',old_hash,b)]},current)
batch,batch_blobs=native(bd);check(len(batch['assets'])==1 and item(batch,cover)['content']['asset']==item(batch,reference)['content']['asset'],'batch replacement merges matching new artwork and prunes both unused sources')
check(next(iter(batch_blobs.values()))==revised_artwork.read_bytes(),'batch embeds the exact original replacement file')
mr,md=job('move-frame',p,'layout.edit',{'edits':[{'name':'cover','action':'move','dx':0,'dy':4}]},br)
rr,rd=job('replace-moved-frame',p,'layout.edit',{'edits':[replacement('cover',new_hash,a)]},mr)
check(item(native(rd)[0],cover)['xf']==[1,0,0,1,0,4],'replacement preserves a prior frame movement')
# Failures must not publish a partially modified document.
head=call('head before refusals','project',p)
bad=out/'invalid.png';bad.write_bytes(b'\x89PNG\r\n\x1a\ninvalid');bad_asset=call('malformed asset','import-asset',p,bad)['id']
for label,edits,reason in [
 ('stale-hash',[replacement('cover',new_hash,b)],'expected SHA-256'),
 ('text-target',[replacement('heading',old_hash,b)],'graphic frame'),
 ('malformed-image',[replacement('cover',old_hash,bad_asset)],'raster cannot be decoded'),
 ('partial-batch',[replacement('cover',old_hash,b),replacement('absent',old_hash,b)],'unknown Layout edit target')]:
 failed=job(label,p,'layout.edit',{'edits':edits},rr,False)
 check(reason.lower() in json.dumps(failed).lower(),label+' explains its refusal')
 check(call(label+' head','project',p)==head,label+' keeps the complete accepted project record unchanged')
foreign=call('foreign project','create-project','Foreign asset')['id'];foreign_asset=call('foreign artwork','import-asset',foreign,revised_artwork)['id'];f=out/'foreign.json';f.write_text(json.dumps({'edits':[replacement('cover',old_hash,foreign_asset)]}))
call('foreign asset refusal','submit',p,'layout.edit','--source',rr,'--parameters',f,'--key','foreign',expected=1)
check('asset not found in project' in logs[-1]['stderr'] and call('foreign head','project',p)==head,'foreign project asset is refused before execution without changing the head')
# Imported native and IDML deliveries remain coherent; neither is a flat PDF.
for fmt,filename in [('native','native/document.designcraft'),('idml','exports/document.idml')]:
 ip=call(fmt+' import project','create-project',fmt+' editable publication')['id'];ia=call(fmt+' source','import-asset',ip,d1/filename)['id']
 ir,im=job(fmt+'-import',ip,'layout.import',{'asset':ia,'format':fmt})
 check(all(pixels(im,page).tobytes()==pixels(d1,page).tobytes() for page in (1,2)),fmt+' import exactly reproduces both revised publication pages')
 if fmt=='native':check(native(im)==native(d1),'native import preserves every document field and embedded byte')
# Portable integrity import followed by a fresh worker proves continuing editability.
state=out/'portable-state';imported=call('portable import','import-project',d1,'Portable publication');pp=imported['project']['id'];pr=imported['revision']['id']
check(imported['revision']['validation']['scope']=='bundle_integrity' and not imported['revision']['validation']['native_cold_reopen'],'portable import claims only integrity before native execution')
pa=call('portable replacement asset','import-asset',pp,original_artwork)['id']
pr2,pd=job('portable-revision',pp,'layout.edit',{'edits':[replacement('cover',new_hash,pa)]},pr)
check(all(pixels(pd,page).tobytes()==pixels(d,page).tobytes() for page in (1,2)),'portable project revises in a fresh state and reproduces the original publication')
ir,ind=job('inspect-portable',pp,'layout.inspect',{},pr2)
check(native(ind)==native(pd) and all(pixels(ind,page).tobytes()==pixels(pd,page).tobytes() for page in (1,2)),'inspection preserves portable native state, embedded bytes and both page images')
check(snapshot(d)==original_files and digest(original_artwork)==old_hash and digest(revised_artwork)==new_hash,'all original inputs and the original delivered project remain byte-identical')
all_groups=[]
for directory in (out/'state',out/'portable-state'):
 with sqlite3.connect('file:'+str(directory/'studio.sqlite3')+'?mode=ro',uri=True) as db:groups=[x[0] for x in db.execute('SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL')]
 for group in groups:
  try:os.killpg(group,0)
  except ProcessLookupError:pass
  else:raise AssertionError('native process group remains: '+str(group))
 all_groups+=groups
check(len(all_groups)==len(jobs),'every native job has an execution receipt and its process group is absent')
check(run('verify package after',[package/'bin/a-dope-guard','verify'])==verification,'all successful and refused jobs leave the sealed package unchanged')
save('context.json',{'original':str(d),'revised':str(d1),'portable':str(pd),'vector':str(vd),'parameters':params,'project':p,'originalRevision':r,'revisedRevision':r1,'originalSHA256':old_hash,'revisedSHA256':new_hash,'originalAsset':a,'revisedAsset':b})
save('evidence.json',{'passed':True,'checks':len(cases),'cases':cases,'nativeJobs':len(jobs),'successfulNativeJobs':sum(j['result']['state']=='succeeded' for j in jobs),'expectedFailedNativeJobs':sum(j['result']['state']=='failed' for j in jobs),'groups':all_groups,'allNativeGroupsAbsent':True,'package':str(package),'verification':verification,'wholeLayoutQualified':False,'completeReleaseQualified':False,'ownerDesignApproval':False,'network':False})
print(json.dumps({'passed':True,'checks':len(cases),'nativeJobs':len(jobs),'revised':str(d1)}))
