"""Complete execution checks for the editable Slides raster model profile.

This profile owns every field it sends to native code. It admits native shapes,
plain text, notes and owned still PNG/JPEG pictures over pinned default masters.
Unsupported resources, effects, charts, tables and custom masters remain preserved by the source layer
but are refused here. This is not general DeckCraft/PPTX admission.
"""
from pathlib import Path
import math

from . import slides_source as source, slides_revision as revision, slides_recipes as recipes, slides_pictures as pictures
from .slides_source import require
from .write_container import read_bytes

PROFILE = 'editable-raster-slides-v2'
MAX_TEXT = 100_000
MAX_SHAPES = 2048


def same(actual,expected,label):require(revision.canonical(actual)==revision.canonical(expected),'admission '+label+' needs separate qualification')
def fields(value,names,label):require(type(value) is dict and set(value)==set(names),'admission '+label+' fields differ')
def number(value,low,high,label):require(type(value) in (int,float) and math.isfinite(value) and low<=value<=high,'admission '+label+' exceeds finite bounds')
def boolean(value,label):require(type(value) is bool,'admission '+label+' must be boolean')
def plain(value,maximum,label):
    require(type(value) is str and len(value)<=maximum and not any(ord(c)<32 or ord(c)==127 or c=='\ufffc' for c in value),
            'admission '+label+' must be bounded plain text')


def color(value):
    fields(value,('base',),'color');base=value['base'];fields(base,('kind','rgb'),'color base');same(base['kind'],'rgb','color kind')
    fields(base['rgb'],('r','g','b','a'),'color channels')
    require(all(type(v) is int and 0<=v<=255 for v in base['rgb'].values()),'admission color channels must be byte integers')


def fill(value):
    if value is None:return
    require(type(value) is dict and value.get('kind') in ('none','solid'),'admission fill needs separate qualification')
    fields(value,('kind',) if value['kind']=='none' else ('kind','color'),'fill')
    if value['kind']=='solid':color(value['color'])


def run_props(value):
    fields(value,revision.RUN_FIELDS,'run properties')
    for key,item in value.items():
        if item is None:continue
        if key in ('font','fontEa','fontCs','fontSym'):same(item,'Inter','font family')
        elif key in ('bold','italic','noProof','normalizeHeight'):boolean(item,key)
        elif key in ('lang','altLang'):plain(item,256,key)
        elif key=='fill':fill(item)
        elif key in ('highlight','underlineColor'):color(item)
        elif key in ('size','spacing','kern','baseline'):
            low,high={'size':(1,256),'spacing':(-128,128),'kern':(0,256),'baseline':(-1,1)}[key];number(item,low,high,key)
        else:raise ValueError('Slides admission run property '+key+' needs separate qualification')


def spacing(value,label):
    fields(value,('kind','v'),label);require(value['kind'] in ('pct','pts'),'admission spacing kind unsupported')
    number(value['v'],0,1000,label)


def paragraph_props(value):
    fields(value,recipes.PARA_FIELDS,'paragraph properties')
    for key,item in value.items():
        if item is None:continue
        if key=='align':require(item in ('left','center','right','justify','distributed','thaiDistributed','justLow'),'admission alignment unsupported')
        elif key in ('lineSpacing','spaceBefore','spaceAfter'):spacing(item,key)
        elif key in ('marginLeft','marginRight','indent'):number(item,-4032,4032,key)
        elif key=='defaultTab':number(item,1,4032,key)
        elif key=='bullet':same(item,{'kind':'none'},'bullet')
        elif key in ('rtl','eastAsianLineBreak','latinLineBreak','hangingPunct'):boolean(item,key)
        else:raise ValueError('Slides admission paragraph property '+key+' needs separate qualification')


def body_props(value,template):
    fields(value,template,'text body properties')
    for key,item in value.items():
        if item is None:continue
        if key in ('insetL','insetR','insetT','insetB','colSpacing'):number(item,0,4032,key)
        elif key=='anchor':require(item in ('top','middle','bottom','justified','distributed'),'admission anchor unsupported')
        elif key=='columns':require(type(item) is int and 1<=item<=8,'admission column count unsupported')
        elif key=='rot':number(item,-360,360,key)
        elif key=='autofit':same(item,{'kind':'none'},'automatic text fitting')
        elif key=='vert':same(item,'horizontal','vertical text')
        elif key in ('vertOverflow','horzOverflow'):same(item,'overflow','text clipping')
        elif key in ('anchorCtr','wrap','rtlCol','upright','spaceFirstLast','compatLnSpc'):boolean(item,key)
        else:raise ValueError('Slides admission text body property '+key+' needs separate qualification')


def inspect(data):
    checked=source.inspect_bytes(data,'json');document=checked['document']
    base_bytes=read_bytes(Path(__file__).with_name('slides_recipe_base.json'))
    require(source.sha(base_bytes)==recipes.BASE_SHA256,'admission native defaults changed')
    base=source.strict_json(base_bytes);fields(document,base,'presentation')
    mutable={'slides','slideSize','notesSize','props','nextId','media'}
    for key in set(base)-mutable:same(document[key],base[key],'presentation '+key)
    fields(document['props'],base['props'],'document properties')
    for key,value in document['props'].items():
        if key=='revision':require(type(value) is int and 0<=value<2**32,'admission document revision invalid')
        else:plain(value,4096,'document '+key)
    require(1<=len(document['slides'])<=32,'admission needs 1 to 32 slides')
    shape_template=base['slides'][0]['shapes'][0];slide_template=base['slides'][0]
    media=pictures.inventory(document)
    total_text=0;total_runs=0;total_shapes=0;total_paragraphs=0;picture_count=0
    def text_body(value):
        nonlocal total_text,total_runs,total_paragraphs
        fields(value,('body','paragraphs'),'text body');body_props(value['body'],shape_template['text']['body'])
        for paragraph in source.sequence(value['paragraphs'],'admitted paragraphs',4096):
            require(type(paragraph) is dict and {'level','runs'}<=set(paragraph)<={'level','runs','props','defProps','endProps'},'admission paragraph fields differ')
            require(type(paragraph['level']) is int and 0<=paragraph['level']<=8,'admission paragraph level invalid')
            total_paragraphs+=1;require(total_paragraphs<=4096,'admission aggregate paragraph budget exceeded')
            if 'props' in paragraph:paragraph_props(paragraph['props'])
            for key in ('defProps','endProps'):
                if key in paragraph:run_props(paragraph[key])
            for run in source.sequence(paragraph['runs'],'admitted text runs',8192):
                require(type(run) is dict and {'text'}<=set(run)<={'text','props','kind'},'admission text run fields differ')
                if 'kind' in run:same(run['kind'],{'kind':'text'},'non-plain run')
                plain(run['text'],MAX_TEXT,'run text');total_text+=len(run['text']);total_runs+=1
                require(total_text<=MAX_TEXT and total_runs<=8192,'admission aggregate text/run budget exceeded')
                if 'props' in run:run_props(run['props'])
    for slide in document['slides']:
        fields(slide,slide_template,'slide')
        for key in ('animations','transition','comments'):same(slide[key],slide_template[key],'slide '+key)
        plain(slide['name'],1024,'slide name');boolean(slide['hidden'],'slide hidden');boolean(slide['showMasterShapes'],'master visibility')
        if slide['background'] is not None:
            fields(slide['background'],('kind','fill'),'background');same(slide['background']['kind'],'fill','background kind');fill(slide['background']['fill'])
        text_body(slide['notes'])
        for shape in slide['shapes']:
            total_shapes+=1;require(total_shapes<=MAX_SHAPES,'admission aggregate shape budget exceeded')
            fields(shape,shape_template,'shape')
            if shape['kind']['type']=='picture':
                fields(shape['kind'],('type','fill'),'picture kind');pictures.fill(shape['kind']['fill'],media);picture_count+=1
                same(shape['geom'],{'kind':'preset','name':'rect'},'picture geometry')
                for key in ('text','ph','fill'):same(shape[key],None,'picture '+key)
                same(shape['textBox'],False,'picture text box')
                transform=revision.transform(shape['xfrm'])
                require(transform is not None and transform['w']>0 and transform['h']>0, 'picture needs positive explicit placement')
                require(not any(transform.get(key) for key in ('rot','flipH','flipV')), 'rotated or flipped pictures need separate qualification')
            else:same(shape['kind'],{'type':'shape'},'shape kind')
            fields(shape['geom'],('kind','name'),'shape geometry');same(shape['geom']['kind'],'preset','geometry kind')
            require(shape['geom']['name'] in ('rect','roundRect','ellipse','triangle','diamond','line'),'admission preset geometry unsupported')
            for key in ('line','effects','style','click','hover'):same(shape[key],None,'shape '+key)
            for key in ('name','descr','title'):plain(shape[key],4096,'shape '+key)
            for key in ('hidden','locked','textBox','decorative'):boolean(shape[key],key)
            if shape['ph'] is not None:
                ph=shape['ph'];fields(ph,shape_template['ph'],'placeholder')
                require(ph['kind'] in ('title','ctrTitle','subTitle','body','obj','footer','header','slideNum','date'),'admission placeholder kind unsupported')
                source.identity(ph['idx'],'placeholder index');boolean(ph['vertical'],'placeholder vertical');boolean(ph['hasCustomPrompt'],'custom prompt')
                require(ph['size'] in (None,'quarter','half','full'),'admission placeholder size unsupported')
            revision.transform(shape['xfrm']);fill(shape['fill'])
            if shape['text'] is not None:text_body(shape['text'])
    return {'profile':PROFILE,'profile_admission_complete':True,'general_admission_complete':False,'source_sha256':checked['source_sha256'],
            'slides':len(document['slides']),'shapes':total_shapes,'paragraphs':total_paragraphs,'runs':total_runs,'characters':total_text,
            'owned_resources':len(media),'pictures':picture_count,'embedded_fonts':0,'system_fonts':False,'source_format_fidelity_qualified':False,
            'render_qualified':False,'pending_qualification':['complete-source-format-fidelity','rendered-fidelity','broader-model-and-resource-admission']}


def inspect_project(checked):
    baseline=inspect(checked['members']['baseline.json']);current=inspect(checked['members']['document.json'])
    # Independent source reconstruction, enforced by portable inspection, binds
    # this baseline to the original JSON or native container before execution.
    return {'profile':PROFILE,'baseline':baseline,'current':current,'profile_admission_complete':True,'general_admission_complete':False}
