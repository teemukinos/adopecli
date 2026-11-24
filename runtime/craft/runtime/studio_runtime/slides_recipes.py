"""Deterministic, editable presentation recipes with caller-owned content.

The pinned native defaults and layout configuration are reusable. Caller content
is neither a shared template nor cached globally. Compilation does not authorize
native execution or certify text fit, font coverage or export fidelity.
"""
import copy
from pathlib import Path
import re

from . import slides_source as source, slides_revision as revision
from .slides_source import require
from .write_container import read_bytes

VERSION = 1
FONT = 'Inter'
BASE_SHA256 = 'c1abdcef0f3423c8dcc9e82d17b195c1a6377b59bdafb44b8dd973a9b15f0dec'
SOURCE_REVISION = '7cc73ab1895ed2e30c8afbcada20c70b9ea0a440'
FONT_REVISION = '37827adc41fd165f9a9234ac40f94dbad353aa69'
INK = '#17282B'
PAPER = '#F6F5F0'
TYPE = {'metadata':16.0, 'body':20.0, 'lead':25.0, 'heading':31.25, 'cover':48.828125}
PARA_FIELDS = ('align marginLeft marginRight indent lineSpacing spaceBefore spaceAfter bullet bulletFont bulletFontFollowText '
               'bulletColor bulletColorFollowText bulletSize bulletSizePoints bulletSizeFollowText tabs defaultTab rtl fontAlign '
               'eastAsianLineBreak latinLineBreak hangingPunct').split()


def catalog():
    return [{'id':'production_proposal', 'version':VERSION, 'name':'Production proposal',
             'description':'An editable cover, section pages with speaker notes, and paginated delivery specifications.',
             'required':['title','sections'], 'optional':['subtitle','label','author','deliverables','controls'],
             'controls':{'accent':{'default':'#D8E96B','type':'hex RGB'}}, 'canvas':{'width':960,'height':540,'unit':'points'},
             'fonts':[FONT], 'editable':True, 'shares_user_content':False, 'visual_approval':False,
             'text_fit_qualified':False, 'engine_admission_complete':False}]


def text(value, label, maximum):
    require(type(value) is str and bool(value.strip()) and not any(ord(c)<32 or ord(c)==127 or 0xd800<=ord(c)<=0xdfff or c=='\ufffc' for c in value),
            'recipe '+label+' must be plain paragraph text')
    require(len(value.encode('utf-8')) <= maximum, 'recipe '+label+' exceeds its byte budget')
    return value


def normalize(params):
    require(type(params) is dict and {'recipe','version','title','sections'} <= set(params)
            <= {'recipe','version','title','subtitle','label','author','sections','deliverables','controls'}, 'recipe fields differ')
    require(params['recipe']=='production_proposal' and type(params['version']) is int and params['version']==VERSION, 'recipe identity/version unsupported')
    result={'recipe':'production_proposal','version':VERSION,'title':text(params['title'],'title',512)}
    for key,maximum in (('subtitle',2048),('label',256),('author',512)):
        if key in params:result[key]=text(params[key],key,maximum)
    sections=params['sections'];require(type(sections) is list and 1<=len(sections)<=24,'recipe needs 1 to 24 sections')
    result['sections']=[]
    for section in sections:
        require(type(section) is dict and {'heading','paragraphs'} <= set(section) <= {'heading','paragraphs','notes'},'recipe section fields differ')
        paragraphs=section['paragraphs'];require(type(paragraphs) is list and 1<=len(paragraphs)<=6,'recipe section needs 1 to 6 paragraphs')
        item={'heading':text(section['heading'],'heading',512),'paragraphs':[text(p,'paragraph',8192) for p in paragraphs]}
        if 'notes' in section:item['notes']=text(section['notes'],'speaker notes',16384)
        result['sections'].append(item)
    deliverables=params.get('deliverables',[]);require(type(deliverables) is list and len(deliverables)<=28,'recipe deliverables exceed budget')
    result['deliverables']=[]
    for item in deliverables:
        require(type(item) is dict and set(item)=={'asset','source','delivery'},'recipe deliverable fields differ')
        result['deliverables'].append({key:text(item[key],key,1024) for key in ('asset','source','delivery')})
    controls=params.get('controls',{});require(type(controls) is dict and set(controls)<= {'accent'},'recipe controls unknown')
    accent=controls.get('accent','#D8E96B')
    require(type(accent) is str and re.fullmatch('#[0-9A-Fa-f]{6}',accent) is not None,'recipe accent must be hexadecimal RGB')
    result['controls']={'accent':accent.upper()}
    require(len(revision.encoded(result)) <= 96<<10,'recipe aggregate content exceeds byte budget')
    return result


def solid(hex_color):
    channels=[int(hex_color[i:i+2],16) for i in (1,3,5)]
    return {'kind':'solid','color':{'base':{'kind':'rgb','rgb':dict(zip(('r','g','b','a'),[*channels,255]))}}}


def contrast_ink(accent):
    values=[int(accent[i:i+2],16)/255 for i in (1,3,5)]
    luminance=sum(weight*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4) for weight,v in zip((.2126,.7152,.0722),values))
    return '#FFFFFF' if 1.05/(luminance+.05) >= (luminance+.05)/.05 else '#000000'


def compile_recipe(params):
    request=normalize(params);base=read_bytes(Path(__file__).with_name('slides_recipe_base.json'))
    require(source.sha(base)==BASE_SHA256,'recipe native defaults differ from pinned template')
    document=source.strict_json(base);slide_template=copy.deepcopy(document['slides'][0]);shape_template=copy.deepcopy(slide_template['shapes'][0])
    body_template=copy.deepcopy(shape_template['text']['body']);document['slides']=[]
    document['props'].update(title=request['title'],author=request.get('author',''),lastModifiedBy=request.get('author','Dobe User'))
    document['slideSize']={'width':960.0,'height':540.0}
    blank=next(layout['id'] for layout in document['masters'][0]['layouts'] if layout['kind']=='blank')
    accent=request['controls']['accent'];accent_ink=contrast_ink(accent);selectors={'sections':[],'deliverables':[]};boxes=[]
    identity=document['nextId']
    def next_id():
        nonlocal identity
        identity+=1;return identity
    def page(name, background=PAPER):
        slide=copy.deepcopy(slide_template);slide.update(id=next_id(),name=name,layout=blank,shapes=[],showMasterShapes=False,
            background={'kind':'fill','fill':solid(background)})
        document['slides'].append(slide);return slide
    def shape(slide,name,x,y,width,height,fill=None):
        item=copy.deepcopy(shape_template);item.update(id=next_id(),name=name,ph=None,text=None,textBox=False,
            xfrm={'x':float(x),'y':float(y),'w':float(width),'h':float(height)},fill=solid(fill) if fill else {'kind':'none'})
        slide['shapes'].append(item);return item
    def textbox(slide,name,value,x,y,width,height,role='body',color=INK,bold=False):
        values=value if type(value) is list else [value]
        item=shape(slide,name,x,y,width,height);item['textBox']=True
        body=copy.deepcopy(body_template);body.update(insetL=0.0,insetR=0.0,insetT=0.0,insetB=0.0,anchor='top',wrap=True,
            autofit={'kind':'none'},vert='horizontal',vertOverflow='overflow',horzOverflow='overflow')
        props={key:None for key in revision.RUN_FIELDS};props.update(font=FONT,size=TYPE[role],bold=bold,fill=solid(color))
        paragraph={key:None for key in PARA_FIELDS};paragraph.update(align='left',lineSpacing={'kind':'pct','v':1.4 if role in ('body','metadata') else 1.15},
            spaceAfter={'kind':'pts','v':16.0},bullet={'kind':'none'})
        item['text']={'body':body,'paragraphs':[{'level':0,'props':copy.deepcopy(paragraph),'runs':[{'text':v,'props':copy.deepcopy(props)}]} for v in values]}
        path='/slides/'+str(len(document['slides'])-1)+'/shapes/'+str(len(slide['shapes'])-1)
        boxes.append({'path':path,'name':name,'x':float(x),'y':float(y),'width':float(width),'height':float(height),'role':role,'point_size':TYPE[role],
                      'text_fit_qualified':False})
        return {'shape':path,'runs':[path+'/text/paragraphs/'+str(i)+'/runs/0' for i in range(len(values))]}
    def footer(slide,inverse=False):
        color=PAPER if inverse else INK
        shape(slide,'Footer rule',48,476,864,1,accent if inverse else '#C7CDC9')
        textbox(slide,'Footer label',request.get('label','Production proposal'),48,492,760,32,'metadata',color)
        textbox(slide,'Page number',str(len(document['slides'])),872,492,40,32,'metadata',color)
    slide=page('Cover',INK)
    shape(slide,'Accent tab',48,48,864,6,accent)
    textbox(slide,'Proposal label',request.get('label','Production proposal'),48,76,864,34,'metadata',PAPER)
    selectors['title']=textbox(slide,'Proposal title',request['title'],48,150,864,170,'cover',PAPER,True)
    if 'subtitle' in request:selectors['subtitle']=textbox(slide,'Proposal subtitle',request['subtitle'],48,338,790,90,'lead',PAPER)
    if 'author' in request:selectors['author']=textbox(slide,'Prepared by',request['author'],48,435,790,28,'metadata',PAPER)
    footer(slide,True)
    for index,item in enumerate(request['sections']):
        slide=page(item['heading']);shape(slide,'Section marker',48,48,68,40,accent)
        textbox(slide,'Section number',str(index+1).zfill(2),62,52,42,36,'lead',accent_ink,True)
        heading=textbox(slide,'Section heading',item['heading'],48,135,248,265,'heading',INK,True)
        paragraphs=textbox(slide,'Section body',item['paragraphs'],348,138,564,312,'body')
        selector={'heading':heading,'paragraphs':paragraphs}
        if 'notes' in item:
            slide['notes']['paragraphs']=[{'level':0,'runs':[{'text':item['notes']}]}]
            selector['notes']='/slides/'+str(len(document['slides'])-1)+'/notes/paragraphs/0/runs/0'
        selectors['sections'].append(selector);footer(slide)
    for offset in range(0,len(request['deliverables']),4):
        slide=page('Deliverables '+str(offset//4+1))
        textbox(slide,'Delivery heading','Deliverables',48,48,864,56,'heading',INK,True)
        for label,x,width in (('Asset',48,260),('Editable source',340,260),('Delivery',632,280)):
            textbox(slide,label+' column',label,x,123,width,32,'metadata',INK,True)
        for row,item in enumerate(request['deliverables'][offset:offset+4]):
            y=176+row*72;shape(slide,'Delivery row rule',48,y-12,864,1,'#C7CDC9');paths={}
            for name,x,width in (('asset',48,260),('source',340,260),('delivery',632,280)):
                paths[name]=textbox(slide,'Deliverable '+str(offset+row+1)+' '+name,item[name],x,y,width,58,'body')
            selectors['deliverables'].append(paths)
        footer(slide)
    document['nextId']=identity;data=revision.encoded(document);profile=source.inspect_bytes(data,'json')
    return {'request':request,'document':document,'data':data,'selectors':selectors,'text_boxes':boxes,
            'provenance':{'recipe':'production_proposal','version':VERSION,'base_sha256':BASE_SHA256,'native_source_revision':SOURCE_REVISION,
                          'font_source_revision':FONT_REVISION,'fonts':[FONT],'shared_user_content':False},
            'slide_count':len(document['slides']),'engine_admission_complete':False,'text_fit_qualified':False,
            'pending_qualification':sorted(set(profile['pending_qualification'])|{'native-text-fit','glyph-identity-and-coverage'})}
