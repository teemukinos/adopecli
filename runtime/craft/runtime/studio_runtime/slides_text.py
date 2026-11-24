"""Inspect actual native placed-text geometry and exact selected font bytes.

This is an observation of the rendering engine, not independent shaping. The
packet excludes chart labels and text converted to geometry; full render coverage
and imported-model admission must not be inferred from a successful inspection.
"""
import math

from . import slides_source as source, slides_builtin_fonts
from .slides_source import require
from .write_fonts import inspect as inspect_font


def keys(value,names,label):require(type(value) is dict and set(value)==set(names.split()),'text report '+label+' fields differ')
def integer(value,low,high,label):require(type(value) is int and low<=value<=high,'text report '+label+' integer is invalid')
def number(value,low,high,label):require(type(value) in (int,float) and math.isfinite(value) and low<=value<=high,'text report '+label+' number is invalid')
def sequence(value,maximum,label):require(type(value) is list and len(value)<=maximum,'text report '+label+' list exceeds budget')
def vector(value,count,label):
    require(type(value) is list and len(value)==count,'text report '+label+' vector differs')
    for item in value:number(item,-10_000_000,10_000_000,label)


def inspect(packet,owned_fonts=()):
    require(type(packet) is bytes and 12<=len(packet)<=48*1024*1024+12 and packet[:8]==b'DOBESLY1','text report packet is invalid')
    size=int.from_bytes(packet[8:12],'little');require(0<size<=16<<20 and 12+size<=len(packet),'text report header exceeds packet')
    value=source.strict_json(packet[12:12+size]);raw=packet[12+size:]
    keys(value,'schemaVersion scope completeRenderCoverage slide size faces fontBytes glyphCount lineCount texts','header')
    integer(value['schemaVersion'],1,1,'schema');integer(value['slide'],0,255,'slide')
    require(value['scope']=='placed-slide-text' and value['completeRenderCoverage'] is False,'text report cannot claim complete render coverage')
    vector(value['size'],2,'canvas');require(all(0<n<=8192 for n in value['size']),'text report canvas exceeds bounds')
    integer(value['fontBytes'],0,32<<20,'font bytes');require(value['fontBytes']==len(raw),'text report font byte count differs')
    integer(value['glyphCount'],0,200_000,'glyph count');integer(value['lineCount'],0,100_000,'line count')
    sequence(value['faces'],64,'faces');sequence(value['texts'],4096,'text bodies')
    require(type(owned_fonts) in (list,tuple) and len(owned_fonts)<=64,'text report owned fonts exceed budget')
    owned={};total_owned=0
    for data in owned_fonts:
        require(type(data) is bytes and 0<len(data)<=16<<20,'text report owned font size is invalid');total_owned+=len(data)
        require(total_owned<=32<<20,'text report aggregate owned font budget exceeded');owned[source.sha(data)]=data
    offset=0;faces=[]
    for face in value['faces']:
        keys(face,'family style index weight italic unitsPerEm coordinates offset bytes','face')
        integer(face['offset'],offset,offset,'font offset');integer(face['bytes'],1,16<<20,'face bytes');end=offset+face['bytes']
        require(end<=len(raw),'text report font exceeds packet');data=raw[offset:end];digest=source.sha(data)
        builtin=slides_builtin_fonts.FONTS.get(digest)
        require(owned.get(digest)==data or builtin is not None and builtin['bytes']==len(data),'text report selected an unowned font')
        integer(face['index'],0,0,'standalone font index');require(face['coordinates']==[],'text report variable fonts need separate qualification')
        require(type(face['italic']) is bool,'text report font italic must be boolean');number(face['weight'],1,1000,'font weight')
        for name in ('family','style'):require(type(face[name]) is str and 0<len(face[name])<=256,'text report font name is invalid')
        parsed=inspect_font(data)
        require(face['unitsPerEm']==parsed['units_per_em'],'text report font units differ from actual bytes')
        require(face['family'] in {n['text'] for n in parsed['names'] if n['id'] in (1,16)}
                and face['style'] in {n['text'] for n in parsed['names'] if n['id'] in (2,17)},'text report names differ from actual font')
        faces.append({**face,'sha256':digest,'glyph_count':parsed['glyph_count'],'embedding_bits':parsed['embedding_bits'],'source':'pinned-built-in' if builtin else 'owned-input'})
        offset=end
    require(offset==len(raw),'text report has unowned trailing font bytes')
    issues=[];glyph_count=0;line_count=0;text_bytes=0;used=set()
    for ti,text in enumerate(value['texts']):
        keys(text,'owner paragraphs transform inner contentWidth contentHeight fontScale lineReduction rotation overflow lines runs','text body')
        integer(text['owner'],0,2**32-1,'owner');vector(text['transform'],6,'transform');vector(text['inner'],4,'inner box')
        x0,y0,x1,y1=text['inner'];require(x0<=x1 and y0<=y1,'text report inner box is reversed')
        for key in ('contentWidth','contentHeight'):number(text[key],0,10_000_000,key)
        number(text['fontScale'],.01,10,'font scale');number(text['lineReduction'],0,1,'line reduction');number(text['rotation'],-360,360,'rotation')
        require(type(text['overflow']) is bool,'text report overflow must be boolean')
        sequence(text['paragraphs'],100_000,'paragraphs');sequence(text['lines'],100_000,'lines');sequence(text['runs'],200_000,'runs')
        for para in text['paragraphs']:
            require(type(para) is str,'text report paragraph must be a string');text_bytes+=len(para.encode())
            require(text_bytes<=4<<20,'text report paragraph byte budget exceeded')
        def issue(kind,**extra):issues.append({'kind':kind,'text':ti,'owner':text['owner'],**extra})
        if text['overflow'] or text['contentHeight']>y1-y0+.5:issue('vertical-overflow')
        if text['contentWidth']>x1-x0+.5:issue('horizontal-overflow')
        if text['fontScale']!=1 or text['lineReduction']!=0:issue('automatic-text-shrink')
        for line in text['lines']:
            keys(line,'paragraph start end top baseline bottom extent column rtl','line');integer(line['paragraph'],0,len(text['paragraphs'])-1,'line paragraph')
            length=len(text['paragraphs'][line['paragraph']]);integer(line['start'],0,length,'line start');integer(line['end'],line['start'],length,'line end')
            integer(line['column'],0,255,'column');require(type(line['rtl']) is bool,'text report line direction is invalid')
            vector(line['extent'],2,'line extent')
            for key in ('top','baseline','bottom'):number(line[key],-10_000_000,10_000_000,key)
            require(line['top']<=line['bottom'] and line['extent'][0]<=line['extent'][1],'text report line bounds reversed')
            if line['top']<y0-.5 or line['bottom']>y1+.5:issue('line-outside-vertical-box',paragraph=line['paragraph'])
            if line['extent'][0]<x0-.5 or line['extent'][1]>x1+.5:issue('line-outside-horizontal-box',paragraph=line['paragraph'])
            a,b,c,d,e,f=text['transform']
            corners=[(a*x+c*y+e,b*x+d*y+f) for x in line['extent'] for y in (line['top'],line['bottom'])]
            if any(x<-.5 or y<-.5 or x>value['size'][0]+.5 or y>value['size'][1]+.5 for x,y in corners):
                issue('line-outside-slide',paragraph=line['paragraph'])
            line_count+=1;require(line_count<=100_000,'text report aggregate line budget exceeded')
        for ri,run in enumerate(text['runs']):
            keys(run,'font size paragraph characters glyphs cells syntheticBold syntheticItalic alpha upright','run')
            integer(run['font'],0,len(faces)-1,'run font');used.add(run['font']);face=faces[run['font']]
            integer(run['paragraph'],0,len(text['paragraphs'])-1,'run paragraph');para=text['paragraphs'][run['paragraph']]
            sequence(run['characters'],2,'run characters');require(len(run['characters'])==2,'text report run range differs')
            integer(run['characters'][0],0,len(para),'run start');integer(run['characters'][1],run['characters'][0],len(para),'run end')
            number(run['size'],.01,4000,'font size');number(run['alpha'],0,1,'alpha')
            for key in ('syntheticBold','syntheticItalic','upright'):require(type(run[key]) is bool,'text report style flag invalid')
            if run['syntheticBold'] or run['syntheticItalic']:issue('synthetic-font-style',run=ri)
            sequence(run['glyphs'],200_000,'glyphs');sequence(run['cells'],200_000,'cells')
            require(len(run['cells']) in (0,len(run['glyphs'])),'text report character attribution differs from glyph count')
            for gi,glyph in enumerate(run['glyphs']):
                vector(glyph,3,'glyph');integer(glyph[0],0,face['glyph_count']-1,'glyph id')
                if glyph[0]==0:issue('missing-glyph',run=ri,glyph=gi)
                glyph_count+=1;require(glyph_count<=200_000,'text report aggregate glyph budget exceeded')
            for cell in run['cells']:
                require(type(cell) is list and len(cell)==2 and type(cell[1]) is str and len(cell[1])==1,'text report character cell invalid')
                integer(cell[0],0,len(para)-1,'cell index');require(para[cell[0]]==cell[1],'text report character cell differs from paragraph')
                require(run['characters'][0]<=cell[0]<run['characters'][1],'text report character cell lies outside its run')
    require(glyph_count==value['glyphCount'] and line_count==value['lineCount'],'text report aggregate counts differ')
    require(used==set(range(len(faces))),'text report contains unreferenced font faces')
    return {'schema_version':1,'slide':value['slide'],'size':value['size'],'texts':value['texts'],'faces':faces,'issues':issues,
            'glyph_count':glyph_count,'line_count':line_count,'packet_sha256':source.sha(packet),
            'actual_font_bytes_verified':True,'independent_shaping_qualified':False,'complete_render_coverage':False,'engine_admission_complete':False}


def require_clear(report):
    require(not report['issues'],'text delivery has '+', '.join(sorted({item['kind'] for item in report['issues']})))
    return report
