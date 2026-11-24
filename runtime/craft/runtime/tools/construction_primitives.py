"""Exercise all typed Blender primitives; arguments: output-directory, input-PNG."""
import json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio_runtime.construction import execute
from studio_runtime.construction_schema import digest
root=Path(sys.argv[1]);root.mkdir();asset='1234567890abcdef1234567890abcdef';assets=root/'construction/assets';assets.mkdir(parents=True)
shutil.copyfile(sys.argv[2],assets/asset)
objects=[{'id':'background','kind':'gradient','width':640,'height':360,'x':320,'y':180,'z':-100,'color':'#090B0E','color2':'#304070'},
{'id':'group','kind':'group','x':180,'y':170,'keys':{'x':[[0,180,'CONSTANT'],[2,200,'CONSTANT']],'scale':[[0,1,'LINEAR'],[2,1.05,'LINEAR']]}},
{'id':'picture','kind':'image','parent':'group','x':0,'y':0,'width':250,'height':140,'asset':asset,'opacity':.8,'mask':[.05,.05,.95,.95],'keys':{'opacity':[[0,.3,'LINEAR'],[2,.8,'LINEAR']]}},
{'id':'path','kind':'path','points':[[-60,40],[0,-50],[60,40]],'closed':True,'stroke':3,'x':470,'y':170,'color':'#FF6A2B','keys':{'x':[[0,460,'CONSTANT'],[2,480,'CONSTANT']],'opacity':[[0,.5,'LINEAR'],[2,1,'LINEAR']]}},
{'id':'text','kind':'text','x':320,'y':300,'text':'Editable primitives','size':34,'color':'#F4F3EA'},
{'id':'ellipse','kind':'ellipse','x':470,'y':170,'width':150,'height':150,'color':'#6EA8FF','stroke':2},
{'id':'glow','kind':'glow','x':470,'y':170,'z':-10,'radius':75,'color':'#6EA8FF','opacity':.2,'mask':[.1,.1,.9,.9]},
{'id':'rectangle','kind':'rectangle','x':320,'y':340,'width':100,'height':3,'color':'#FF6A2B'},
{'id':'noise','kind':'noise','x':320,'y':180,'z':-90,'width':640,'height':360,'color':'#090B0E','color2':'#20242B','opacity':.3,'seed':1.29}]
doc={'schema_version':1,'policy':{'media_generation':'disabled','network':'offline'},'components':[{'id':'art','engine':'blender','parameters':{'width':640,'height':360,'fps':24,'frames':3,'samples':8,'preview_frame':1,'objects':objects}}]}
print(execute(root,'construct.create',{'document':doc})['validation'],flush=True)
(root/'input.json').write_text(json.dumps(doc,indent=2))
revised=root.with_name(root.name+'-revised');shutil.copytree(root,revised)
edit={'document_sha256':digest(doc),'edits':[{'component':'art','action':'set','path':['parameters','objects',3,'points',1,1],'before':-50,'value':-65}]}
print(execute(revised,'construct.edit',edit)['validation'],flush=True)
