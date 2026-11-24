"""Compare complete admitted format-3 meaning with a native cold save.

The schema follows the pinned native serde definitions, not rendered pixels.
Defaults, f32 storage, path table identities and legacy color effects have explicit
representations. Every other stored field is retained. This module accepts only
profiles produced by complete admission; it is not an independent JSON validator.
"""
import hashlib
import json

from .animate_format import native_path
from .animate_properties import f32, WHITE, BLACK, IDENTITY
from .animate_unicode import trim

MODEL = 'anicraft-0.2.1/format-3/native-semantics-v1'


def exact(value):
    return value


def single(value):
    value = f32(value)
    return 0.0 if value == 0 else value


def double(value):
    value = float(value)
    return 0.0 if value == 0 else value


def many(convert):
    return lambda values: [convert(v) for v in values]


def optional(convert):
    return lambda value: None if value is None else convert(value)


def object_value(value, required, defaults=None):
    """Fill only documented defaults; never silently drop an unknown field."""
    defaults = defaults or {}
    if not isinstance(value, dict) or value.keys() - required.keys() - defaults.keys() or required.keys() - value.keys():
        raise ValueError('Animate semantic schema has missing or unknown fields')
    result = {key: convert(value[key]) for key, convert in required.items()}
    result.update({key: convert(value.get(key, default)) for key, (default, convert) in defaults.items()})
    return result


def numeric(value):
    # Used only for fully numeric geometric structures already schema-admitted.
    if isinstance(value, dict):
        return {key: numeric(item) for key, item in value.items()}
    if isinstance(value, list):
        return [numeric(item) for item in value]
    return single(value)


def easing(value):
    return value if isinstance(value, str) else numeric(value)


def color(value):
    """Keep the native authored style, including neutral Alpha/Tint/Advanced."""
    alpha = single(value.get('alpha', 1)); amount = single(value.get('tint_amount', 0))
    tint = numeric(value.get('tint', WHITE)); style = value.get('style')
    if style is None:
        if alpha == 1 and amount == 0:
            style = 'none'
        elif amount == 0:
            style = 'alpha'
        elif alpha == 1:
            style = 'tint'
        else:
            # Native legacy alpha+tint becomes Advanced. Every operation rounds
            # to f32 as in ColorTransform::concat, including the identity step.
            k = single(1-amount)
            mul = [k,k,k,alpha]
            add = [single(amount*tint[c]) for c in ('r','g','b')] + [0.0]
            return {'style': 'advanced', 'multiply': mul, 'offset': add}
    if style == 'none':
        return {'style': style}
    if style == 'alpha':
        return {'style': style, 'alpha': alpha}
    if style == 'tint':
        return {'style': style, 'tint': tint, 'amount': amount}
    if style == 'brightness':
        return {'style': style, 'brightness': single(value['brightness'])}
    if style == 'advanced':
        return {'style': style, 'multiply': numeric(value['multiply']), 'offset': numeric(value['offset'])}
    raise ValueError('Animate semantic color style is unknown')


def stroke(value):
    def dash(v):
        if v['kind'] == 'dashed':
            return object_value(v, {'kind': exact, 'lengths': numeric}, {'offset': (0, single)})
        return object_value(v, {'kind': exact, 'spacing': single})
    def style(v):
        return object_value(v, {}, {'cap': ('round',exact), 'join': ('round',exact),
            'miter_limit': (3,single), 'dash': (None,optional(dash))})
    return object_value(value, {'color': numeric, 'width': single},
        {'profile': (None,optional(numeric)), 'style': ({},style)})


def paint(value):
    tag = next(iter(value)); body = value[tag]
    if tag == 'Bitmap':
        body = object_value(body, {'bitmap': exact}, {'repeat': (False,exact), 'matrix': (IDENTITY,numeric)})
    else:
        body = numeric(body)
    return {tag: body}


BLUR = {'blur_x': (5,single), 'blur_y': (5,single), 'quality': (1,exact)}
EDGE = {**BLUR, 'strength': (1,single), 'angle': (45,single), 'distance': (5,single),
        'side': ('inner',exact), 'knockout': (False,exact)}
FILTER_DEFAULTS = {
    'blur': BLUR,
    'drop_shadow': {**BLUR, 'strength': (1,single), 'angle': (45,single), 'distance': (4,single),
                    'color': (BLACK,numeric), 'inner': (False,exact), 'knockout': (False,exact), 'hide_object': (False,exact)},
    'glow': {**BLUR, 'strength': (1,single), 'color': (BLACK,numeric), 'inner': (False,exact), 'knockout': (False,exact)},
    'bevel': {**EDGE, 'shadow_color': (BLACK,numeric), 'highlight_color': (WHITE,numeric)},
    'gradient_glow': {**EDGE, 'side': ('outer',exact), 'stops': ([{'offset':0,'color':{**WHITE,'a':0}}, {'offset':1,'color':BLACK}],numeric)},
    'gradient_bevel': {**EDGE, 'stops': ([{'offset':0,'color':WHITE},{'offset':.5,'color':{**BLACK,'a':0}}, {'offset':1,'color':BLACK}],numeric)},
    'adjust_color': {key:(0,single) for key in ('brightness','contrast','saturation','hue')},
}


def effect(value):
    return object_value(value, {'type': exact}, FILTER_DEFAULTS[value['type']])


def action(value):
    op = value['op']; required = {'op':exact}; defaults = {}
    # Only self targets disappear during serialization. Preserve every other
    # spelling verbatim, including aliases and whitespace in non-self paths.
    target = lambda v: '' if trim(v) in ('','this') else v
    if op in ('stop','play','next_frame','prev_frame','goto_and_play','goto_and_stop','set_property'):
        defaults['target'] = ('',target)
    if op in ('goto_and_play','goto_and_stop'):
        defaults.update(frame=(0,exact), scene=(None,exact))
    if op == 'trace':
        defaults['message'] = ('',exact)
    if op == 'set_property':
        required.update(property=exact, value=double)
    return object_value(value, required, defaults)


def script(value):
    tag = next(iter(value)); body = value[tag]
    if tag == 'actions':
        body = many(action)(body)
    elif tag == 'plugin':
        body = object_value(body, {'id':exact}, {'entry':('main',exact)})
    else:
        body = object_value(body, {}, {'language':('actionscript3',exact), 'text':('',exact)})
    return {tag:body}


def frame_sound(value):
    def effect(v):
        if isinstance(v,str):
            return v
        return object_value(v, {'custom':many(lambda p:object_value(p, {'at':double,'left':single,'right':single}))})
    return object_value(value, {'sound':exact}, {'sync':('event',exact), 'repeat':(1,exact),
        'loop':(False,exact), 'effect':('none',effect)})


def armature(value):
    def bone(v):
        return object_value(v, {'id':exact,'parent':exact,'child':exact,'head':numeric,'tail':numeric,'rest':numeric},
            {'name':('',exact),'limits':(None,optional(numeric)),'pinned':(False,exact)})
    return object_value(value, {}, {'bones':([],many(bone))})


def motion(value):
    def track(v):
        key = lambda k:object_value(k, {'frame':exact,'value':single}, {'ease':('Linear',easing)})
        return object_value(v, {'property':exact}, {'keys':([],many(key))})
    return object_value(value, {'target':exact}, {'tracks':([],many(track)),
        'path':(None,optional(lambda p:native_path(p).digest)), 'orient':(False,exact), 'pins':([],exact)})


OUTPUTS = {'html':'{name}.html','gif':'{name}.gif','video':'{name}.webm','lottie':'{name}.json',
           'sprite_sheet':'{name}_sheet.png','png_sequence':'{name}_frames','png':'{name}.png','svg':'{name}.svg','audio':'{name}.wav'}
RANGE = ({},lambda v:object_value(v, {}, {'from':(None,exact),'to':(None,exact)}))
PUBLISH_OPTIONS = {
    'html': {'title':('',exact),'sound':(True,exact),'fit':(True,exact)},
    'gif': {'range':RANGE,'scale':(1,single),'loop':(True,exact)},
    'video': {'range':RANGE,'scale':(1,single),'audio':(True,exact)},
    'lottie': {'range':RANGE,'background':(False,exact)},
    'sprite_sheet': {'range':RANGE,'scale':(1,single),'columns':(0,exact),'padding':(0,exact),'background':(False,exact)},
    'png_sequence': {'range':RANGE,'scale':(1,single)},
    'png': {'frame':(0,exact),'scale':(1,single)}, 'svg': {'frame':(0,exact)},
    'audio': {'range':RANGE,'rate':(44100,exact),'bits':(16,exact)},
}


def publish(value):
    converters = {name:({},lambda v,name=name,options=options:object_value(v, {},
        {'enabled':(name=='html',exact),'output':(OUTPUTS[name],exact),**options})) for name,options in PUBLISH_OPTIONS.items()}
    return object_value(value, {}, converters)


def normalized(profile):
    """All admitted stored document fields, in their native semantic types."""
    slots = profile['graph']['path_slots']
    def timeline(value,owner):
        def layer(v):
            def key(k,index):
                def element(e,ei):
                    def kind(value):
                        if value == 'Camera':return value
                        tag = next(iter(value)); body = value[tag]
                        if tag == 'Shape':
                            body = object_value(body, {'path':lambda _:slots[(owner,v['id'],index,ei)].digest},
                                {'fill':(None,optional(paint)),'stroke':(None,optional(stroke)),
                                 'fill_rule':('NonZero',exact),'merge':(False,exact)})
                        elif tag == 'Text':
                            body = object_value(body, {'text':exact,'font':exact,'size':single,'color':numeric,
                                'outline':lambda _:slots[(owner,v['id'],index,ei)].digest,'box_width':single,'box_height':single},
                                {'bold':(False,exact),'italic':(False,exact),'align':('left',exact),
                                 'letter_spacing':(0,single),'line_spacing':(0,single),'width':(None,optional(single))})
                        else:
                            event=lambda h:object_value(h,{'event':exact},{'actions':([],many(action))})
                            body = object_value(body, {'symbol':exact}, {'loop_mode':('Loop',exact),'first_frame':(0,exact),
                                'blend':('normal',exact),'filters':([],many(effect)),'events':([],many(event))})
                        return {tag:body}
                    return object_value(e, {'id':exact,'kind':kind},
                        {'name':('',exact),'transform':(IDENTITY,numeric),'color':({},color)})
                tween=lambda t:object_value(t, {}, {'easing':('Linear',easing),'kind':('Classic',exact),'orient':(False,exact)})
                pose=lambda p:object_value(p, {'bone':exact,'angle':single})
                return object_value(k, {'start':exact,'duration':exact}, {
                    'elements':([],lambda es:[element(e,ei) for ei,e in enumerate(es)]),
                    'tween':(None,optional(tween)),'motion':(None,optional(motion)),'hints':([],numeric),
                    'label':('',exact),'sound':(None,optional(frame_sound)),'script':(None,optional(script)),'pose':([],many(pose))})
            return object_value(v, {'id':exact,'name':exact}, {'kind':('Normal',exact),'parent':(None,exact),
                'visible':(True,exact),'locked':(False,exact),'outline':(False,exact),
                'color':({'r':f32(79/255),'g':f32(163/255),'b':1,'a':1},numeric),
                'keyframes':([],lambda ks:[key(k,i) for i,k in enumerate(ks)]),
                'depth':(0,single),'volume':(1,single),'muted':(False,exact),'armature':(None,optional(armature))})
        return object_value(value, {'layers':many(layer)})
    def symbol(s):
        linkage=lambda v:object_value(v,{'class':exact},{'base':('',exact)})
        return object_value(s, {'id':exact,'name':exact,'timeline':lambda t:timeline(t,('symbol',s['id']))},
            {'kind':('Graphic',exact),'linkage':(None,optional(linkage)),
             'scale_grid':(None,optional(numeric)),'scale_grid_kept':(None,optional(numeric))})
    def tree(value):
        folder=lambda f:object_value(f,{'id':exact,'name':exact},{'parent':(None,exact)})
        # Native BTreeMap orders placements by variant then ID; list order is not
        # authored structure. Duplicates have already been refused by admission.
        def placed(values):
            def key(v):
                tag=next(k for k in v if k!='folder');return (('symbol','bitmap','sound').index(tag),v[tag])
            return sorted(values,key=key)
        return object_value(value,{}, {'folders':([],many(folder)),'placed':([],placed)})
    stage=lambda v:object_value(v,{'width':exact,'height':exact,'fps':single,'background':numeric})
    scenes=lambda ss:[object_value(s,{'name':exact,'timeline':lambda t:timeline(t,('scene',i))}) for i,s in enumerate(ss)]
    bitmap=lambda v:object_value(v,dict.fromkeys(('id','name','width','height','png'),exact),{'smoothing':(True,exact)})
    return object_value(profile['envelope']['document'], {'stage':stage,'scenes':scenes,'library':many(symbol),'next_id':exact},
        {'bitmaps':([],many(bitmap)),'sounds':([],exact),'library_tree':({},tree),'document_class':('',exact),'publish':({},publish)})


def digest(value):
    result=hashlib.sha256()
    for piece in json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).iterencode(value):
        result.update(piece.encode('utf-8'))
    return result.hexdigest()


def difference(left, right, path=''):
    """Locate the first changed semantic field without exposing its contents."""
    if type(left) is not type(right):
        return path or '/'
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return path or '/'
        for key in left:
            found = difference(left[key], right[key], path+'/'+key.replace('~','~0').replace('/','~1'))
            if found is not None:
                return found
    elif isinstance(left, list):
        if len(left) != len(right):
            return path or '/'
        for index,(a,b) in enumerate(zip(left,right)):
            found = difference(a,b,path+'/'+str(index))
            if found is not None:
                return found
    elif left != right:
        return path or '/'
    return None


def compare(source, saved):
    before=normalized(source);after=normalized(saved)
    changed = difference(before,after)
    if changed is not None:
        raise ValueError('Animate native cold save changed admitted document semantics at '+changed)
    return {'source_sha256':source['source_sha256'],'native_saved_sha256':saved['source_sha256'],
            'semantic_model':MODEL,'semantic_sha256':digest(before),'source_semantics_preserved':True,
            'raw_bytes_preserved':source['source_bytes']==saved['source_bytes'],
            'generator_preserved':source['envelope']['generator']==saved['envelope']['generator'],
            'publication_authorized':False,'interactive_playback_verified':False}
