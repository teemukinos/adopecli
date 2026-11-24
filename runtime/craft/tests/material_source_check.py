#!/usr/bin/env python3
"""Original structured Material authoring, atomic topology changes and real pixels."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_source as source, material_document as document
from studio_runtime import material_container as container
sys.path.insert(0,str(Path(__file__).resolve().parent))
from material_procedural_check import body


def element(tag,*children,**attributes):
    return {'tag':tag,'attributes':attributes,'children':list(children)}


def scalar(tag,value):return element(tag,v=str(value))


def parameter(name,tag,value):
    return element('parameter',scalar('name',name),scalar('relativeTo',0),element('paramValue',scalar('constantValue'+tag,value)))


def uniform(identity,output,color,gray=False):
    return element('compNode',scalar('uid',identity),element('GUILayout',scalar('gpos','50 40 0')),
                   element('compOutputs',element('compOutput',scalar('uid',output),scalar('comptype',2 if gray else 1))),
                   element('compImplementation',element('compFilter',scalar('filter','uniform'),element('parameters',
                   parameter('outputcolor','Float4',color),parameter('colorswitch','Bool',0 if gray else 1)))))


def bridge(identity,output,node,port):
    return element('compNode',scalar('uid',identity),element('GUILayout',scalar('gpos','270 40 0')),
                   element('connections',element('connection',scalar('identifier','inputNodeOutput'),scalar('connRef',node),scalar('connRefOutput',port))),
                   element('compImplementation',element('compOutputBridge',scalar('output',output))))


def recipe():
    outputs=[('basecolor',20,'baseColor',1),('roughness',21,'roughness',2)]
    graph=element('graph',scalar('identifier','Original'),scalar('uid',2),scalar('graphtype','material'),element('attributes'),element('paraminputs'),
        element('graphOutputs',*(element('graphoutput',scalar('identifier',name),scalar('uid',uid),element('attributes',scalar('label',name)),
            element('usages',element('usage',scalar('components','RGBA'),scalar('name',usage))),scalar('group','Material'),scalar('channels',code)) for name,uid,usage,code in outputs)),
        element('compNodes',uniform(3,4,'1 0 0 1'),uniform(7,8,'0 0 1 1'),uniform(11,12,'0 0 0 1',True),bridge(30,20,3,4),bridge(31,21,11,12)),
        element('baseParameters'),element('GUIObjects'),element('options',element('option',scalar('name','defaultParentSize'),scalar('value','5x5'))),
        element('root',element('rootOutputs',*(element('rootOutput',scalar('output',uid),scalar('format',0),scalar('usertag','')) for _,uid,_,_ in outputs))))
    return element('package',scalar('identifier','Original'),scalar('formatVersion','1.1.0.202401'),scalar('updaterVersion','0.4.1'),scalar('fileUID',0),scalar('versionUID',0),
        element('dependencies',element('dependency',scalar('filename','?himself'),scalar('uid',1),scalar('type','package'),scalar('fileUID',0),scalar('versionUID',0))),element('content',graph))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','atomic','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True);checks=[];calls=[];original_run=document.run
    def tracked(command,*a,**kw):
        calls.append(list(map(str,command)));return original_run(command,*a,**kw)
    document.run=tracked
    def check(label,ok):
        if not ok:raise AssertionError(label)
        checks.append(label)
    def native(*arguments):
        command=[str(args.engine.resolve()),*map(str,arguments)];calls.append(command)
        result=subprocess.run(command,capture_output=True,timeout=60)
        (out/f'native-{len(calls)}.stdout').write_bytes(result.stdout);(out/f'native-{len(calls)}.stderr').write_bytes(result.stderr)
        check('native '+str(arguments[0])+' succeeds',result.returncode==0)
        return json.loads(result.stdout)
    def pixels(label,path,color):
        folder=out/(label+'-pixels');native('export',path,folder,'--depth','8')
        files=sorted(p.name for p in folder.glob('*.png'));check(label+' exports both maps',files==['Original_basecolor.png','Original_roughness.png'])
        for name,pixel in [('basecolor',color),('roughness',(0,0,0,255))]:
            with Image.open(folder/('Original_'+name+'.png')) as image:
                check(label+' '+name+' exact analytic pixels',image.size==(32,32) and image.convert('RGBA').tobytes()==bytes(pixel)*1024)
    def prepare(label,data,report,original=None):
        destination=out/label;retained=None
        if original is not None:
            retained=out/(label+'.input');retained.write_bytes(original)
        proof=source.prepare(out,data,destination,args.engine,report,source=retained)
        check(label+' fresh native reopen',proof['native_verified'] and proof['native_cold_reopen'] and not proof['engine_admission_complete'])
        if retained:check(label+' input unchanged',retained.read_bytes()==original)
        check(label+' staging cleaned',not (out/(label+'.source-input')).exists())
        profile=document.read_native(destination/'native/document.mcraft')
        index=json.loads((destination/'native/source-index.json').read_bytes())
        check(label+' selector digest binds retained document',index['source_sha256']==hashlib.sha256((destination/'native/document.mcraft').read_bytes()).hexdigest())
        for package,items in index['packages'].items():
            parsed=profile['container']['xml'][package];raw=profile['container']['members'][package]
            check(label+' selector count '+package,len(items)==len(parsed['elements']))
            valid=True
            for identity,(item,node,(a,b)) in enumerate(zip(items,parsed['elements'],parsed['spans'])):
                valid &= item['element']==identity and item['tag']==node['tag'] and item['sha256']==hashlib.sha256(raw[a:b]).hexdigest() and (
                    item['parent'] is None and identity==0 or item['parent'] is not None and any(c is node for c in parsed['elements'][item['parent']]['content']))
            check(label+' every source selector has exact index parent tag and digest',valid)
        return destination/'native/document.mcraft'
    def find(data,tag,uid=None):
        p=document.inspect_bytes(data)['container'];package=p['root'];parsed=p['xml'][package]
        for i,node in enumerate(parsed['elements']):
            if node['tag']==tag and (uid is None or any(c.get('tag')=='uid' and c['attributes'].get('v')==str(uid) for c in node['content'])):
                a,b=parsed['spans'][i];return {'package':package,'element':i,'expected_sha256':hashlib.sha256(p['members'][package][a:b]).hexdigest()}
        raise AssertionError('missing '+tag)
    def op(data,kind,tag,value=None,uid=None,before=None):
        result={'kind':kind,**find(data,tag,uid)}
        if kind!='remove':result['value']=value
        if kind=='insert':result['before']=before
        return result
    def revised(label,data,operations):
        changed,report=source.revise(data,hashlib.sha256(data).hexdigest(),operations)
        return changed,prepare(label,changed,report,data)
    def refused(label,call):
        count=len(calls)
        try:call()
        except (ValueError,FileExistsError):check(label+' refused before native',len(calls)==count)
        else:raise AssertionError('accepted '+label)
    def reject(label,data,operations,digest=None):
        refused(label,lambda:source.revise(data,digest or hashlib.sha256(data).hexdigest(),operations))
    try:
        original,report=source.create({'package.sbs':recipe()});(out/'original.mcraft').write_bytes(original)
        check('original authoring deterministic',source.create({'package.sbs':recipe()})[0]==original)
        original_path=prepare('original',original,report);pixels('original',original_path,(255,0,0,255))
        profile=document.inspect_bytes(original);root=profile['container']['xml']['package.sbs']['elements'][0]
        check('typed tree readback exact',source.tree(root)==recipe())
        metadata=[op(original,'insert','attributes',scalar('label','Original — surface')),
                  op(original,'insert','attributes',scalar('description','Precise <finish> & "detail"\nNext\tline')),
                  op(original,'insert','baseParameters',parameter('randomseed','Int32',17))]
        changed,path=revised('metadata',original,metadata)
        check('empty container insertion order preserved',b'<label v=' in document.inspect_bytes(changed)['container']['members']['package.sbs'])
        raw=profile['container']['members']['package.sbs'];changed_raw=document.inspect_bytes(changed)['container']['members']['package.sbs']
        check('only requested empty containers expanded',changed_raw==raw.replace(b'<attributes/>',b'<attributes>'+source.encode(metadata[0]['value'])+source.encode(metadata[1]['value'])+b'</attributes>',1)
              .replace(b'<baseParameters/>',b'<baseParameters>'+source.encode(metadata[2]['value'])+b'</baseParameters>',1))
        pixels('metadata',path,(255,0,0,255))
        additions=[op(changed,'insert','compNodes',uniform(40,41,'1 1 1 1'),before=find(changed,'compNode',30)['element']),
                   op(changed,'replace','compNode',bridge(30,20,40,41),uid=30),op(changed,'remove','compNode',uid=7)]
        structural,path=revised('topology',changed,additions);pixels('topology',path,(255,255,255,255))
        def png(color):
            stream=io.BytesIO();Image.new('RGBA',(32,32),color).save(stream,format='PNG');return stream.getvalue()
        green=png((0,255,0,255));red=png((255,0,0,255));member='resources/swatch.png'
        resource=element('group',scalar('identifier','Resources'),scalar('uid',90),element('content',element('resource',scalar('identifier','Swatch'),scalar('uid',91),
            scalar('type','bitmap'),scalar('format','png'),scalar('filepath',''),element('source',element('externalcopy',scalar('filename',member))))))
        bitmap=uniform(40,41,'1 1 1 1');bitmap['children'][-1]=element('compImplementation',element('compFilter',scalar('filter','bitmap'),element('parameters',
            parameter('bitmapresourcepath','String','pkg:///Resources/Swatch'),parameter('colorswitch','Bool',1),parameter('colorspace','Int32',0))))
        resource_ops=[op(structural,'insert','content',resource),op(structural,'replace','compNode',bitmap,uid=40),{'kind':'asset.add','member':member,'data':green}]
        resource_data,path=revised('resource',structural,resource_ops);pixels('resource',path,(0,255,0,255))
        asset_ops=[{'kind':'asset.replace','member':member,'expected_sha256':hashlib.sha256(green).hexdigest(),'data':red}]
        swapped,path=revised('asset-replaced',resource_data,asset_ops);pixels('asset-replaced',path,(255,0,0,255))
        check('binary revision preserves all SBS bytes',document.inspect_bytes(swapped)['container']['members']['package.sbs']==document.inspect_bytes(resource_data)['container']['members']['package.sbs'])
        removed,path=revised('resource-removed',swapped,[op(swapped,'remove','group',uid=90),op(swapped,'replace','compNode',uniform(40,41,'0 0 1 1'),uid=40),
            {'kind':'asset.remove','member':member,'expected_sha256':hashlib.sha256(red).hexdigest()}]);pixels('resource-removed',path,(0,0,255,255))
        # A bare input can gain an owned resource without pretending the SBS
        # alone contains its asset. Its revised member bytes remain explicit.
        bare=document.inspect_bytes(structural)['container']['members']['package.sbs'];bare_resource_ops=copy.deepcopy(resource_ops)
        for operation in bare_resource_ops:
            if 'package' in operation:operation['package']='source.sbs'
        wrapped,wrapper_report=source.revise(bare,hashlib.sha256(bare).hexdigest(),bare_resource_ops)
        check('bare resource addition declares lossless wrapper',wrapper_report['container_conversion']=='lossless-sbs-wrapper' and document.inspect_bytes(wrapped)['container']['members'][member]==green)
        prepare('bare-resource',wrapped,wrapper_report,bare)
        atomic=args.atomic.read_bytes();dynamic=body([(1,'const_float1',[],('float',.25),256),(2,'const_float1',[],('float',.5),256),(3,'add',[1,2],None,256)],3)
        parsed=container.parse_xml(b'<package>'+ET.tostring(dynamic,encoding='utf-8')+b'</package>')
        procedural,path=revised('procedural',atomic,[op(atomic,'replace','dynamicValue',source.tree(parsed['elements'][1]))])
        info=native('info',path)
        (out/'procedural-info.json').write_text(json.dumps(info,indent=2)+'\n')
        # Assertions use the actual native cook record, not source prediction.
        processors=[n for n in info['graph']['nodes'] if n.get('def')=='value_processor']
        check('procedural topology cooks exact sum',len(processors)>0 and any(n.get('cooked',{}).get('value')=={'t':'float','v':.75} for n in processors) and not any(n.get('cooked',{}).get('error') for n in info['graph']['nodes']))
        reject('whole source stale',original,metadata,digest='0'*64)
        bad=copy.deepcopy(metadata);bad[0]['expected_sha256']='0'*64;reject('subtree stale',original,bad)
        replace=op(original,'replace','compNode',uniform(3,4,'0 1 0 1'),uid=3)
        reject('overlapping edits',original,[replace,replace])
        reject('duplicate node identity',original,[op(original,'insert','compNodes',uniform(3,44,'0 1 0 1'))])
        reject('dangling output wire',original,[op(original,'remove','compNode',uid=3)])
        reject('non-child anchor',original,[op(original,'insert','compNodes',uniform(40,41,'1 1 1 1'),before=0)])
        reject('orphan asset',original,[{'kind':'asset.add','member':member,'data':green}])
        reject('asset traversal',original,[{'kind':'asset.add','member':'../escape.png','data':green}])
        reject('stale asset',resource_data,[{**asset_ops[0],'expected_sha256':'0'*64}])
        reject('duplicate asset target',resource_data,asset_ops*2)
        reject('asset removes source',original,[{'kind':'asset.remove','member':'package.sbs','expected_sha256':hashlib.sha256(raw).hexdigest()}])
        reject('nested overlap',original,[op(original,'remove','compNodes'),replace])
        reject('empty insert conflicting replacement',original,[metadata[0],op(original,'replace','attributes',element('attributes'))])
        for label,value in [('unknown tree field',{**recipe(),'extra':True}),('namespace',element('package',xmlns='bad')),('namespace tag',element('x:package')),
                            ('invalid XML value',element('package',v='bad\0value')),('Boolean attribute',element('package',v=True))]:
            refused(label,lambda value=value:source.create({'package.sbs':value}))
        refused('duplicate case archive',lambda:source.archive({'package.sbs':raw,'PACKAGE.SBS':raw}))
        refused('NUL archive path',lambda:source.archive({'package.sbs\0hidden':raw}))
        occupied=out/'occupied';occupied.mkdir();(occupied/'sentinel').write_text('keep')
        refused('existing destination',lambda:source.prepare(out,original,occupied,args.engine,report));check('existing destination preserved',(occupied/'sentinel').read_text()=='keep')
        stage=out/'blocked.source-input';stage.write_text('keep')
        refused('existing staging file',lambda:source.prepare(out,original,out/'blocked',args.engine,report));check('existing stage preserved',stage.read_text()=='keep')
        refused('pre-cancel',lambda:source.prepare(out,original,out/'cancel',args.engine,report,cancelled=lambda:True))
        check('cancel cleanup',not (out/'cancel').exists() and not (out/'cancel.source-input').exists())
        refused('report digest mismatch',lambda:source.prepare(out,original,out/'wrong-report',args.engine,{**report,'source_sha256':'0'*64}))
        # Mutating the independently retained input during native verification
        # must invalidate this attempt even when its staged document is intact.
        retained=out/'mutating.input';retained.write_bytes(original)
        changed_once=False
        def mutate_original(command,*a,**kw):
            nonlocal changed_once
            result=tracked(command,*a,**kw)
            if command[1]=='snapshot' and not changed_once:
                retained.write_bytes(b'changed by another writer');changed_once=True
            return result
        document.run=mutate_original
        try:source.prepare(out,original,out/'mutated',args.engine,report,source=retained)
        except ValueError:check('changed original invalidates native verification',changed_once and not (out/'mutated').exists() and not (out/'mutated.source-input').exists())
        else:raise AssertionError('accepted changed original')
        finally:document.run=tracked
        check('cleanup does not overwrite concurrently changed original',retained.read_bytes()==b'changed by another writer')
        check('upstream atomic fixture unchanged',args.atomic.read_bytes()==atomic)
        evidence={'passed':True,'checks':checks,'native_calls':len(calls),'structural_kinds':['replace','remove','insert','asset.add','asset.replace','asset.remove'],
                  'remote_actions':False,'engine_admission_complete':False,'runtime_registered':False,
                  'scope':'original typed tree authoring, structural revisions, preserved unrequested bytes, full cold models and trusted small native pixel/processor examples; public runtime and bounded general cook remain pending'}
        (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native_calls':len(calls)}))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks},indent=2)+'\n');raise
    finally:
        document.run=original_run;(out/'calls.json').write_text(json.dumps(calls,indent=2)+'\n')


if __name__=='__main__':main()
