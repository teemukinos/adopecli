"""Original, versioned editable production graphs built only from native primitives.

These graphs are authored here; no upstream converted SBS library is used.
Recipe controls become exposed SBS inputs. Generated pixels are never cached or
shared between projects. The deterministic graph specification is reusable.
"""
import hashlib
import json
import math

from .material_container import require
from .material_function_catalog import INPUTS
from .material_preview import f32

VERSION = 1
# All color components are linear-light values. Ranges are authoring limits,
# also recorded as editable native controls; later edits use normal admission.
COMMON = {'color_r': (.18, 0., 1.), 'color_g': (.32, 0., 1.), 'color_b': (.4, 0., 1.),
          'roughness': (.28, .02, 1.), 'relief': (.12, 0., 1.)}
RECIPES = {
    'ceramic_tiles': {'name': 'Ceramic tiles', 'description': 'Periodic square ceramic faces, recessed grout and rounded bevels.',
                      'controls': {**COMMON, 'repeat': (8., 1., 64.), 'grout': (.08, .01, .3), 'bevel': (.08, .01, .25)}},
    'ribbed_metal': {'name': 'Ribbed metal', 'description': 'Periodic rounded metal ribs with correlated height and roughness.',
                     'controls': {**COMMON, 'repeat': (24., 1., 128.)}},
}
OUTPUTS = ('baseColor', 'roughness', 'metallic', 'height', 'normal', 'ambientOcclusion')


def catalog():
    return [{'id': name, 'version': VERSION, 'name': spec['name'], 'description': spec['description'],
             'controls': {k: {'default': v[0], 'minimum': v[1], 'maximum': v[2], 'type': 'float', 'integral': k=='repeat'} for k,v in spec['controls'].items()},
             'outputs': list(OUTPUTS), 'default_resolution': 256, 'resolution_range': [32, 1024], 'minimum_pixels_per_repeat': 4,
             'editable': True, 'original_graph': True, 'visual_approval': False} for name,spec in RECIPES.items()]


def normalize(params):
    require(type(params) is dict and {'recipe','version'} <= set(params) <= {'recipe','version','resolution','controls'}, 'recipe needs identifier, version and optional resolution/controls')
    require(type(params['recipe']) is str and params['recipe'] in RECIPES, 'recipe identifier is unknown')
    require(type(params['version']) is int and params['version']==VERSION, 'recipe version is unsupported')
    size=params.get('resolution',256)
    require(type(size) is int and 32<=size<=1024 and size&(size-1)==0, 'recipe resolution must be a power of two from 32 to 1024')
    spec=RECIPES[params['recipe']]; values=params.get('controls',{})
    require(type(values) is dict and set(values)<=set(spec['controls']), 'recipe controls are unknown')
    controls={}
    for name,(default,low,high) in spec['controls'].items():
        value=values.get(name,default)
        require(type(value) in (float,int) and (low<=value<=high or value in (f32(low),f32(high))) and math.isfinite(value), 'recipe control '+name+' exceeds its finite range')
        if name=='repeat':require(float(value).is_integer(), 'recipe repeat must be integral for seamless tiling')
        controls[name]=f32(value)
    require(size>=controls['repeat']*4, 'recipe needs at least four pixels per repeat; raise resolution or lower repeat')
    return {'recipe':params['recipe'],'version':VERSION,'resolution':size,'controls':controls}


def element(tag,*children,**attributes):return {'tag':tag,'attributes':attributes,'children':list(children)}
def scalar(tag,value):return element(tag,v=str(value))
def parameter(name,tag,value):return element('parameter',scalar('name',name),scalar('relativeTo',0),element('paramValue',scalar('constantValue'+tag,value)))


class Function:
    """Small typed expression builder; output is ordinary editable SBS nodes."""
    def __init__(self):self.nodes=[]
    def add(self,op,*inputs,code=256,setting=None):
        identity=len(self.nodes)+1
        wires=[element('connection',scalar('identifier',port),scalar('connRef',value)) for port,value in zip(INPUTS[op],inputs)]
        require(len(inputs)==len(INPUTS[op]), 'recipe expression arity differs')
        data=[]
        if setting is not None:
            tag,value=setting
            data=[element('funcDatas',element('funcData',scalar('name',op),element('constantValue',scalar('constantValue'+tag,value))))]
        self.nodes.append(element('paramNode',scalar('uid',identity),scalar('function',op),scalar('type',code),
            element('GUILayout',scalar('gpos',f'{(identity-1)%8*160} {(identity-1)//8*120} 0')),element('connections',*wires),*data))
        return identity
    def number(self,v):return self.add('const_float1',setting=('Float1',v))
    def get(self,name):return self.add('get_float1',setting=('String',name))
    def finish(self,result):return element('dynamicValue',scalar('rootnode',result),element('paramNodes',*self.nodes))


def expression(recipe,channel):
    f=Function();zero=f.number(0);one=f.number(1)
    pos=f.add('get_float2',code=512,setting=('String','$pos'))
    x=f.add('swizzle1',pos,setting=('Int32',0));y=f.add('swizzle1',pos,setting=('Int32',1));repeat=f.get('repeat')
    if recipe=='ceramic_tiles':
        distances=[]
        for axis in (x,y):
            coordinate=f.add('mul',axis,repeat);fraction=f.add('sub',coordinate,f.add('floor',coordinate))
            distances.append(f.add('min',fraction,f.add('sub',one,fraction)))
        distance=f.add('min',*distances);edge=f.add('mul',f.get('grout'),f.number(.5))
        t=f.add('min',one,f.add('max',zero,f.add('div',f.add('sub',distance,edge),f.get('bevel'))))
        # Smoothstep makes the face/grout transition tangent-continuous.
        shape=f.add('mul',f.add('mul',t,t),f.add('sub',f.number(3),f.add('mul',f.number(2),t)))
    else:
        wave=f.add('cos',f.add('mul',f.add('mul',x,repeat),f.number(2*math.pi)))
        shape=f.add('mul',f.add('add',wave,one),f.number(.5))
    if channel=='height':result=f.add('mul',shape,f.get('relief'))
    elif channel=='roughness':result=f.add('lerp',f.number(.85 if recipe=='ceramic_tiles' else .5),f.get('roughness'),shape)
    elif channel=='ambientOcclusion':result=f.add('lerp',f.number(.75),one,shape)
    elif channel=='baseColor':
        rgb=[f.add('lerp',f.number(.035),f.get('color_'+c),shape) if recipe=='ceramic_tiles' else f.get('color_'+c) for c in 'rgb']
        result=f.add('vector4',f.add('vector3',f.add('vector2',rgb[0],rgb[1],code=512),rgb[2],code=1024),one,code=2048)
    else:raise ValueError('unknown recipe channel')
    return f.finish(result)


def compile_recipe(params):
    resolved=normalize(params);key=resolved['recipe'];spec=RECIPES[key];ports=[]
    for i,(name,value) in enumerate(resolved['controls'].items()):
        _,low,high=spec['controls'][name]
        options=[element('option',scalar('name',k),scalar('value',v)) for k,v in [('min',low),('max',high),('clamp',0)]]
        ports.append(element('paraminput',scalar('identifier',name),scalar('uid',1000+i),scalar('type',256),
            element('attributes',scalar('label',name.replace('_',' ').title()),scalar('description','Recipe '+key+' v1 control')),
            element('defaultValue',scalar('constantValueFloat1',value)),element('defaultWidget',scalar('name','slider'),element('options',*options))))
    nodes=[];outputs=[]
    for i,channel in enumerate(OUTPUTS):
        identity=10+i*10;output=identity+1;gray=channel not in ('baseColor','normal')
        parameters=[];wires=[]
        if channel=='normal':
            filter_name='normal';parameters=[parameter('intensity','Float1',1),parameter('inversedy','Bool',1),parameter('input2alpha','Bool',0)]
            wires=[element('connection',scalar('identifier','input1'),scalar('connRef',40),scalar('connRefOutput',41))]
        elif channel=='metallic':
            filter_name='uniform';parameters=[parameter('outputcolor','Float4','0 0 0 1' if key=='ceramic_tiles' else '1 1 1 1'),parameter('colorswitch','Bool',0)]
        else:
            filter_name='pixelprocessor';parameters=[parameter('colorswitch','Bool',0 if gray else 1),
                element('parameter',scalar('name','perpixel'),scalar('relativeTo',0),element('paramValue',expression(key,channel)))]
        nodes.append(element('compNode',scalar('uid',identity),element('GUILayout',scalar('gpos',f'0 {i*220} 0')),
            element('compOutputs',element('compOutput',scalar('uid',output),scalar('comptype',2 if gray else 1))),
            element('connections',*wires),element('compImplementation',element('compFilter',scalar('filter',filter_name),element('parameters',*parameters)))))
        nodes.append(element('compNode',scalar('uid',identity+2),element('GUILayout',scalar('gpos',f'300 {i*220} 0')),
            element('connections',element('connection',scalar('identifier','inputNodeOutput'),scalar('connRef',identity),scalar('connRefOutput',output))),
            element('compImplementation',element('compOutputBridge',scalar('output',200+i)))))
        outputs.append(element('graphoutput',scalar('identifier',channel),scalar('uid',200+i),element('attributes',scalar('label',channel)),
            element('usages',element('usage',scalar('components','RGBA'),scalar('name',channel))),scalar('group','Material'),scalar('channels',2 if gray else 1)))
    exponent=resolved['resolution'].bit_length()-1
    graph=element('graph',scalar('identifier','Surface'),scalar('uid',2),scalar('graphtype','material'),
        element('attributes',scalar('label',spec['name']),scalar('description',spec['description'])),element('paraminputs',*ports),
        element('graphOutputs',*outputs),element('compNodes',*nodes),element('baseParameters'),element('GUIObjects'),
        element('options',element('option',scalar('name','defaultParentSize'),scalar('value',f'{exponent}x{exponent}'))),
        element('root',element('rootOutputs',*(element('rootOutput',scalar('output',200+i),scalar('format',0),scalar('usertag','')) for i in range(len(OUTPUTS))))))
    tree=element('package',scalar('identifier','DobeRecipe'),scalar('formatVersion','1.1.0.202401'),scalar('updaterVersion','0.4.1'),scalar('fileUID',0),scalar('versionUID',0),
        element('dependencies',element('dependency',scalar('filename','?himself'),scalar('uid',1),scalar('type','package'),scalar('fileUID',0),scalar('versionUID',0))),element('content',graph))
    documents={'package.sbs':tree}
    encoded=json.dumps(documents,sort_keys=True,separators=(',',':')).encode()
    report={'schema_version':1,**resolved,'graph':'Surface','graph_specification_sha256':hashlib.sha256(encoded).hexdigest(),
            'original_graph':True,'converted_library_used':False,'generated_images_reused':False,'exposed_controls':list(resolved['controls']),
            'outputs':list(OUTPUTS),'visual_approval':False}
    return documents,report
