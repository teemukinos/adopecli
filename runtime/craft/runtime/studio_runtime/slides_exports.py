"""Strict native Slides PNG/PDF delivery with independent output decoding.

Editable originals remain authoritative. Actual placed text must cover the visible
plain text in the admitted model, use pinned fonts and have no layout issues.
This is not general imported-presentation fidelity or independent text shaping.
"""
import json
import math
import shutil

from . import slides_admission as admission, slides_source as source, slides_text, write_binding, write_exports, write_engine, pdf
from .slides_source import require
from .write_container import read_bytes


PROFILE = 'explicit-inter-raster-slides-v2'


def validate(params):
    require(type(params) is dict and params.get('format') in ('png','pdf'),'export requires explicit png/pdf format')
    fields={'format','slides','scale'} if params['format']=='png' else {'format'}
    require(set(params)<=fields,'export has unsupported parameters')
    selected=params.get('slides')
    if 'slides' in params:
        require(type(selected) is list and 1<=len(selected)<=32 and all(type(i) is int and 1<=i<=32 for i in selected)
                and len(set(selected))==len(selected),'export slides must be unique ordered integers from 1 to 32')
    scale=params.get('scale',1)
    require(type(scale) in (int,float) and math.isfinite(scale) and .25<=scale<=4,'export scale must be finite from 0.25 to 4')


def geometry(model,selected,scale):
    width=math.ceil(model['slideSize']['width']*scale);height=math.ceil(model['slideSize']['height']*scale)
    require(0<width<=8192 and 0<height<=8192 and width*height<=16_777_216 and width*height*len(selected)<=64_000_000,
            'export exceeds individual or aggregate pixel budget')
    require(all(i<=len(model['slides']) for i in selected),'export requests a missing slide')
    return width,height


def visible_text(model,index,report):
    """Bind diagnostics to every visible plain text owner in the export profile."""
    slide=model['slides'][index];expected={}
    for shape in slide['shapes']:
        if shape['hidden'] or shape['text'] is None:continue
        paragraphs=[''.join(run['text'] for run in p['runs']) for p in shape['text']['paragraphs']]
        if not any(paragraphs):continue
        require(shape['ph'] is None and shape['xfrm'] is not None,'export inherited text placement needs separate qualification')
        require(not any(shape['xfrm'].get(key) for key in ('flipH','flipV','rot')) and shape['geom']=={'kind':'preset','name':'rect'},
                'export transformed or nonrectangular text needs separate qualification')
        body=shape['text']['body'];require(body.get('rot') in (None,0) and body.get('columns') in (None,1),
                'export rotated or multicolumn text needs separate qualification')
        expected[shape['id']]=paragraphs
    observed={text['owner']:text['paragraphs'] for text in report['texts']}
    require(len(observed)==len(report['texts']) and observed==expected,'export text owner inventory differs from complete visible source')
    require(all(face['source']=='pinned-built-in' and face['family']=='Inter' for face in report['faces']),
            'export selected fonts differ from admitted Inter typography')
    slides_text.require_clear(report)
    return '\n'.join(paragraph for paragraphs in expected.values() for paragraph in paragraphs)


def deliver(native,model_path,expected,destination,params):
    validate(params);model_path=write_engine.owned(native.root,model_path);destination=write_engine.owned(native.root,destination)
    require(not destination.exists(),'export needs a fresh disposable destination')
    require(read_bytes(model_path)==expected,'export source differs from exact predicted model')
    admitted=admission.inspect(expected);model=source.strict_json(expected);selected=params.get('slides',list(range(1,len(model['slides'])+1)))
    scale=float(params.get('scale',1));width,height=geometry(model,selected,scale)
    trusted_pdf=write_binding.resolve_pdf() if params['format']=='pdf' else None
    destination.mkdir(mode=0o700);probes=destination/'probes';probes.mkdir();calls_before=native.calls
    try:
        deck=probes/'source.deckcraft'
        native._snapshot(native._run('encode',model_path,deck),model)
        deck_bytes=read_bytes(deck);reconstructed=source.inspect_bytes(deck_bytes,'deckcraft')
        from .slides_revision import canonical
        require(canonical(reconstructed['document'])==canonical(model),'export native container differs from predicted model')
        pictures=[]
        for item in model['media']:pictures.append(native.observe_picture(item))
        traces=[];texts={}
        for page in selected:
            trace=native.observe_text(deck,deck_bytes,page-1);texts[page]=visible_text(model,page-1,trace);traces.append(trace)
            if params['format']=='pdf':
                require(all(face['embedding_bits'] & 0x302 == 0 for face in trace['faces']),
                        'PDF export font disallows embedding or subsetting')
        outputs=[];total=0;independent=[]
        if params['format']=='png':
            for page in selected:
                path=destination/f'slide-{page:03}.png';cold=probes/f'cold-{page:03}.png'
                for target in (path,cold):
                    reply=source.strict_json(native._run('render',deck,target,page-1,scale,limit=8192))
                    require(type(reply) is dict and set(reply)=={'width','height','slide','scale','bytes','sourceFidelityQualified'}
                            and all(type(reply[k]) is int for k in ('width','height','slide','bytes'))
                            and reply['sourceFidelityQualified'] is False,'native PNG response fields differ')
                    decoded=write_exports.png(target,width,height)
                    require((reply['width'],reply['height'],reply['slide'],reply['scale'],reply['bytes'])==(width,height,page-1,scale,decoded['bytes']),
                            'native PNG response differs from independently decoded output')
                require(path.read_bytes()==cold.read_bytes(),'independent cold PNG exports changed bytes')
                decoded=write_exports.png(path,width,height);total+=decoded['bytes'];require(total<=128<<20,'export aggregate output byte budget exceeded')
                outputs.append({'file':path.name,'slide':page,**decoded,'cold_bytes_equal':True})
        else:
            path=destination/'presentation.pdf';reply=source.strict_json(native._run('convert',deck,path,'pdf',limit=8192));data=read_bytes(path)
            require(type(reply) is dict and set(reply)=={'format','bytes','sourceFidelityQualified'} and reply['format']=='pdf'
                    and type(reply['bytes']) is int and reply['bytes']==len(data) and reply['sourceFidelityQualified'] is False,'native PDF response differs')
            require(len(data)<=64<<20,'PDF exceeds independent reader budget');first_state=None;first_pixels=None
            for cold in range(2):
                digest,_,_=write_engine.executable_digest(trusted_pdf['executable']);require(digest==trusted_pdf['expected_binary_sha256'],'PDF reader changed after receipt verification')
                with write_exports.PDFReader(native.root,trusted_pdf['executable'],native) as reader:
                    document,profile=reader.open(path);state=pdf.snapshot(reader,document)
                    require(len(profile['pages'])==len(model['slides']) and len(state['text'])==len(model['slides']),'PDF page/text count differs from source')
                    pixels=[];checks=[]
                    for page in selected:
                        actual=profile['pages'][page-1]
                        require(abs(actual['width']-model['slideSize']['width'])<.02 and abs(actual['height']-model['slideSize']['height'])<.02
                                and actual['rotation']==0,'PDF page geometry differs from source')
                        require(write_exports.letters(state['text'][page-1]['text'])==write_exports.letters(texts[page]),'PDF text inventory differs from complete source')
                        preview=probes/f'pdf-{cold}-{page:03}.png';reader.render(document,page,preview)
                        pixels.append(write_exports.png(preview,width,height)['rgba8_sha256']);checks.append({'slide':page,'normalized_character_inventory_equal':True})
                    if cold==0:first_state=state;first_pixels=pixels
                    else:require(state==first_state and pixels==first_pixels,'independent cold PDF reader changed state or raster pixels')
                digest,_,_=write_engine.executable_digest(trusted_pdf['executable']);require(digest==trusted_pdf['expected_binary_sha256'],'PDF reader changed during validation')
                independent.append({'cold_pass':cold+1,'text_checks':checks,'rgba8_sha256':pixels})
            require(read_bytes(path)==data,'independent reader changed PDF bytes');total=len(data)
            outputs.append({'file':path.name,'bytes':len(data),'sha256':source.sha(data),'slides':len(selected),'independent_cold_state_equal':True})
        require(read_bytes(deck)==deck_bytes,'delivery changed the native input')
        native.observe(model_path,expected)
        pending=['general-source-format-fidelity','independent-shaping','broader-render-profile','visual-approval']
        if params['format']=='pdf':pending.append('pdf-reading-order')
        report={'schema_version':1,'format':params['format'],'source_model_sha256':source.sha(expected),'admission_profile':admitted['profile'],'delivery_profile':PROFILE,
            'native_calls':native.calls-calls_before,'slide_count':len(model['slides']),'selected_slides':selected,'effective_scale':scale,
            'outputs':outputs,'output_bytes':total,'complete_output_decode':True,'visible_plain_text_owners_equal':True,
            'actual_font_bytes_verified':True,'font_embedding_checked':params['format']=='pdf','text_layout_clear':True,'independent_pdf_checks':independent,
            'pictures':pictures,'owned_picture_decoder_agreement':True,
            'source_format_fidelity_qualified':False,'independent_shaping_qualified':False,'visual_approval':False,'pending_qualification':pending}
        (destination/'text-diagnostics.json').write_text(json.dumps(traces,sort_keys=True,allow_nan=False)+'\n')
        (destination/'pictures.json').write_text(json.dumps(pictures,sort_keys=True,allow_nan=False)+'\n')
        (destination/'delivery.json').write_text(json.dumps(report,sort_keys=True,allow_nan=False)+'\n')
        shutil.rmtree(probes);return report
    except BaseException:
        shutil.rmtree(destination);raise
