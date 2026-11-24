"""Versioned document production recipes that compile to fully editable models.

Content belongs to the caller. Only reusable typography, layout and native
document configuration are shared. Compilation is deterministic and offline.
"""
import copy
import json
import math
from pathlib import Path
import re
import struct

from . import write_container as container, write_project as project
from .write_container import require

VERSION = 1
BODY_FONT = 'Source Sans 3'
TITLE_FONT = 'Source Serif 4'
BASE_SHA256 = '476f4fe96af0d8142628c2cfe968badddd996aba6fad2e619d06fc317db2b9a8'


def native_float(value):
    """Return the shortest decimal that round-trips to the target binary32."""
    packed = struct.pack('<f', value); value = struct.unpack('<f', packed)[0]
    for digits in range(1, 10):
        candidate = float(format(value, '.'+str(digits)+'g'))
        if struct.pack('<f', candidate) == packed: return candidate
    raise ValueError('Write recipe could not represent a finite native scalar')


def catalog():
    return [{'id': 'production_brief', 'version': VERSION, 'name': 'Production brief',
             'description': 'An editable brief with title hierarchy, written direction and a deliverables table.',
             'required': ['title', 'sections'], 'optional': ['subtitle', 'author', 'deliverables', 'controls'],
             'controls': {'paper': {'default': 'a4', 'choices': ['a4', 'letter']},
                          'margin': {'default': 54, 'minimum': 36, 'maximum': 90, 'unit': 'points'},
                          'body_size': {'default': 11, 'minimum': 9, 'maximum': 14, 'unit': 'points'},
                          'accent': {'default': '#123E49', 'type': 'hex RGB'},
                          'heading_face': {'default': 'editorial', 'choices': ['editorial', 'sans']}},
             'fonts': [BODY_FONT, TITLE_FONT], 'editable': True, 'shares_user_content': False,
             'visual_approval': False}]


def text(value, label, maximum):
    require(type(value) is str and bool(value.strip()) and len(value.encode('utf-8')) <= maximum
            and not any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff or c == '\ufffc' for c in value),
            'recipe '+label+' must be bounded plain paragraph text')
    return value


def normalize(params):
    require(type(params) is dict and {'recipe', 'version', 'title', 'sections'} <= set(params)
            <= {'recipe', 'version', 'title', 'subtitle', 'author', 'sections', 'deliverables', 'controls'}, 'recipe fields differ')
    require(params['recipe'] == 'production_brief' and type(params['version']) is int and params['version'] == VERSION, 'recipe identity/version is unsupported')
    result = {'recipe': 'production_brief', 'version': VERSION, 'title': text(params['title'], 'title', 512)}
    for name in ('subtitle', 'author'):
        if name in params: result[name] = text(params[name], name, 1024)
    sections = params['sections']; require(type(sections) is list and 1 <= len(sections) <= 32, 'recipe needs 1 to 32 sections')
    result['sections'] = []; total = sum(len(value.encode('utf-8')) for name,value in result.items() if name in ('title','subtitle','author'))
    for section in sections:
        require(type(section) is dict and set(section) == {'heading', 'paragraphs'}, 'recipe section fields differ')
        heading = text(section['heading'], 'heading', 512); paragraphs = section['paragraphs']
        require(type(paragraphs) is list and 1 <= len(paragraphs) <= 32, 'recipe section needs 1 to 32 paragraphs')
        paragraphs = [text(value, 'paragraph', 8192) for value in paragraphs]
        total += len(heading.encode('utf-8'))+sum(len(value.encode('utf-8')) for value in paragraphs)
        result['sections'].append({'heading': heading, 'paragraphs': paragraphs})
    deliverables = params.get('deliverables', []); require(type(deliverables) is list and len(deliverables) <= 128, 'recipe deliverables exceed budget')
    result['deliverables'] = []
    for item in deliverables:
        require(type(item) is dict and set(item) == {'asset', 'editable_source', 'delivery'}, 'recipe deliverable fields differ')
        checked = {name: text(value, name, 2048) for name,value in item.items()}
        total += sum(len(value.encode('utf-8')) for value in checked.values()); result['deliverables'].append(checked)
    require(total <= 64 << 10, 'recipe content exceeds aggregate text budget')
    controls = params.get('controls', {})
    require(type(controls) is dict and set(controls) <= {'paper', 'margin', 'body_size', 'accent', 'heading_face'}, 'recipe controls are unknown')
    normalized = {'paper': 'a4', 'margin': 54, 'body_size': 11, 'accent': '#123E49', 'heading_face': 'editorial', **controls}
    require(normalized['paper'] in ('a4','letter') and normalized['heading_face'] in ('editorial','sans'), 'recipe paper or heading face is unsupported')
    require(type(normalized['accent']) is str and re.fullmatch('#[0-9A-Fa-f]{6}', normalized['accent']) is not None, 'recipe accent must be hexadecimal RGB')
    for name, low, high in (('margin',36,90), ('body_size',9,14)):
        value = normalized[name]
        require(type(value) in (int,float) and math.isfinite(value) and low <= value <= high, 'recipe '+name+' exceeds its finite range')
        normalized[name] = native_float(value)
    normalized['accent'] = normalized['accent'].upper(); result['controls'] = normalized
    return result


def luminance(rgb):
    def linear(value):
        value /= 255
        return value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4
    return sum(weight*linear(value) for value,weight in zip(rgb, (.2126,.7152,.0722)))


def compile_recipe(params):
    request = normalize(params); controls = request['controls']
    base = container.read_bytes(Path(__file__).with_name('write_recipe_base.json'))
    require(project.sha(base) == BASE_SHA256, 'recipe native defaults differ from the pinned template')
    document = container.strict_json(base)
    table_template = document['body'][0]; row_template = table_template['rows'][0]
    body_size = controls['body_size']; accent = [int(controls['accent'][i:i+2],16) for i in (1,3,5)]
    white_contrast = 1.05/(luminance(accent)+.05)
    header_color = [255,255,255] if white_contrast >= 4.5 else [0,0,0]
    heading_color = next(candidate for step in range(100,-1,-1)
                         if 1.05/(luminance(candidate := [round(channel*step/100) for channel in accent])+.05) >= 4.5)
    document['body'] = []; document['core'].update(title=request['title'], creator=request.get('author',''), lastModifiedBy=request.get('author','Dobe User'))
    document['settings'].update(majorFont=TITLE_FONT if controls['heading_face'] == 'editorial' else BODY_FONT, minorFont=BODY_FONT)
    document['styles']['defaultChr'] = {'font':BODY_FONT, 'size':body_size, 'sizeCs':body_size, 'color':{'Rgb':[28,34,39]}}
    document['styles']['defaultPara'] = {'lineSpacing':{'rule':'multiple','value':1.2}, 'spaceAfter':8.0, 'widowControl':True}
    document['styles']['defaultParaPresent'] = True
    normal = next(style for style in document['styles']['styles'] if style['id'] == 'Normal')
    definitions = {
        'DobeTitle': ({'font':document['settings']['majorFont'], 'size':30.0, 'sizeCs':30.0, 'color':{'Rgb':heading_color}}, {'spaceAfter':10.0,'keepNext':True,'keepLines':True}),
        'DobeSubtitle': ({'font':BODY_FONT,'size':12.0,'sizeCs':12.0,'color':{'Rgb':[80,89,96]}}, {'spaceAfter':12.0,'keepNext':True}),
        'DobeHeading': ({'font':BODY_FONT,'size':native_float(body_size+1),'sizeCs':native_float(body_size+1),'bold':True,'boldCs':True,'color':{'Rgb':heading_color}}, {'spaceBefore':18.0,'spaceAfter':6.0,'keepNext':True,'outlineLevel':0}),
        'DobeBody': ({'font':BODY_FONT,'size':body_size,'sizeCs':body_size}, {'spaceAfter':8.0,'widowControl':True}),
        'DobeTableHeader': ({'font':BODY_FONT,'size':body_size,'sizeCs':body_size,'bold':True,'boldCs':True,'color':{'Rgb':header_color}}, {'spaceBefore':2.0,'spaceAfter':2.0,'keepLines':True}),
        'DobeTableBody': ({'font':BODY_FONT,'size':body_size,'sizeCs':body_size}, {'spaceBefore':2.0,'spaceAfter':2.0,'keepLines':True})}
    for name, (character, paragraph) in definitions.items():
        style = copy.deepcopy(normal); style.update(id=name,name=name,basedOn='Normal',next='Normal',builtin=False,chr=character,para=paragraph)
        document['styles']['styles'].append(style)
    section = document['lastSection']; width,height = (595.28,841.89) if controls['paper'] == 'a4' else (612.0,792.0)
    section.update(pageW=width,pageH=height,marginTop=controls['margin'],marginBottom=controls['margin'],marginLeft=controls['margin'],marginRight=controls['margin'])
    def paragraph(value, style): return {'kind':'para','text':value,'runs':[{'len':len(value.encode('utf-8'))}],'props':{'style':style}}
    def append(value, style): document['body'].append(paragraph(value,style)); return '/body/'+str(len(document['body'])-1)
    selectors = {'title':append(request['title'],'DobeTitle'),'sections':[],'deliverables':[]}
    if 'subtitle' in request: selectors['subtitle'] = append(request['subtitle'],'DobeSubtitle')
    if 'author' in request: selectors['author'] = append('Prepared by '+request['author'],'DobeSubtitle')
    for item in request['sections']:
        selectors['sections'].append({'heading':append(item['heading'],'DobeHeading'), 'paragraphs':[append(value,'DobeBody') for value in item['paragraphs']]})
    if request['deliverables']:
        selectors['deliverables_heading'] = append('Deliverables','DobeHeading')
        table = copy.deepcopy(table_template); table['rows'] = []; available = width-2*controls['margin']
        table['grid'] = [native_float(available*weight) for weight in (.34,.36,.30)]
        table['props']['fixed'] = True; table['props']['look'].update(firstColumn=False,bandedRows=False)
        border = {'style':'single','width':.5,'color':[204,212,216],'space':0.0}
        table['props']['borders'] = {key:copy.deepcopy(border) for key in ('top','bottom','between')}
        table['props']['borders'].update({key:{'style':'none','width':0.0,'color':None,'space':0.0} for key in ('left','right','inside_v')})
        table_index = len(document['body'])
        rows = [('Asset','Editable source','Delivery')]+[tuple(item[key] for key in ('asset','editable_source','delivery')) for item in request['deliverables']]
        for index, values in enumerate(rows):
            row = copy.deepcopy(row_template); row['props'].update(header=index==0,cantSplit=True)
            selected = {}
            for column, (cell, value) in enumerate(zip(row['cells'], values)):
                cell['props']['width'] = table['grid'][column]
                cell['props']['shading'] = accent if index == 0 else [246,248,249] if index%2 == 0 else [255,255,255]
                cell['blocks'] = [paragraph(value,'DobeTableHeader' if index == 0 else 'DobeTableBody')]
                if index: selected[('asset','editable_source','delivery')[column]] = f'/body/{table_index}/rows/{index}/cells/{column}/blocks/0'
            table['rows'].append(row)
            if index: selectors['deliverables'].append(selected)
        document['body'].append(table)
        document['body'].append({'kind':'para','text':'','runs':[]})
    project.native_profile((json.dumps(document)+'\n').encode())
    return document, {'recipe':'production_brief','version':VERSION,'request':request,'selectors':selectors,
                      'fonts':[BODY_FONT,document['settings']['majorFont']], 'header_text_color':header_color,
                      'heading_color':heading_color, 'heading_contrast':1.05/(luminance(heading_color)+.05),
                      'header_contrast':white_contrast if header_color == [255,255,255] else (luminance(accent)+.05)/.05,
                      'source_backed':True,'shared_user_content':False,'visual_approval':False}
