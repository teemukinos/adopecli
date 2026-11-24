#!/usr/bin/env python3
"""Independent malformed-container checks; no native process or external I/O."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import random
import stat
import struct
import sys
import tempfile
import time
import zipfile
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from studio_runtime import material_container as container
sys.path.insert(0,str(Path(__file__).resolve().parent))
from texture_archive_check import fixture, crafted, change, directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,action='append',default=[])
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();checks=[];started=time.monotonic();native=[]
    def check(label,value):
        if not value:raise AssertionError(label)
        checks.append(label)
    def refused(label,data,operation=container.inspect_bytes):
        try:operation(data)
        except ValueError:checks.append(label)
        else:raise AssertionError('accepted '+label)
    def bounded(label,key,limit,data):
        old=getattr(container,key);setattr(container,key,limit)
        try:refused(label,data)
        finally:setattr(container,key,old)
    def embedded(data,declared=None,tail=b''):
        raw=(len(data) if declared is None else declared).to_bytes(4,'big')+zlib.compress(data)+tail
        return base64.b64encode(raw).decode()
    def xml_resource(value):return ('<package><content><resource><source><binembedded><strdata v="'+value+'"/></binembedded></source></resource></content></package>').encode()
    xml=b'<?xml version="1.0" encoding="utf-8"?><!--before--><package><identifier v="Paint"/><content/><!--after--></package>'
    members=[('package.sbs',xml),('resources/data.bin',bytes(range(256))*4)]
    for method in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
        for stream in (False,True):
            for zip64 in (False,True):
                data=fixture(members,compression=method,stream=stream,zip64=zip64)
                result=container.inspect_bytes(data)
                check(f'exact snapshot: {method}/{stream}/{zip64}',result['source_bytes'] is data and result['members']==dict(members)
                      and result['source_sha256']==hashlib.sha256(data).hexdigest() and not result['engine_admission_complete'])
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    check(f'independent ZIP agreement: {method}/{stream}/{zip64}',{name:archive.read(name) for name in archive.namelist()}==result['members'])
    sink=io.BytesIO()
    with zipfile.ZipFile(sink,'w') as archive:
        archive.writestr('resources/',b'');archive.writestr('package.sbs',xml);archive.writestr('resources/original.bin',b'original')
    result=container.inspect_bytes(sink.getvalue())
    check('ordinary directory is retained separately',result['directories']==['resources/'] and len(result['members'])==2)
    result=container.inspect_bytes(xml)
    check('bare XML and ordered comments retained',result['format']=='sbs' and result['xml']['source.sbs']['document'][0]=={'comment':'before'}
          and result['xml']['source.sbs']['root']['content'][-1]=={'comment':'after'})
    annotated=b'<package unknown="retain">left<?source retained?><unrecognized a="1"/>right<![CDATA[<raw>]]></package>'
    result=container.inspect_bytes(annotated)['xml']['source.sbs']['root']
    check('unknown elements, attributes, PI and text inventoried',result['attributes']=={'unknown':'retain'}
          and result['content'][1]=={'instruction':'source','data':'retained'} and result['content'][-1]['text']=='right<raw>')
    check('predefined references decode consistently',container.parse_xml(b'<package><x v="&amp;&lt;&#65;"/></package>')['elements'][1]['attributes']['v']=='&<A')
    for label,data in [('malformed XML',b'<package>'),('DTD',b'<!DOCTYPE package><package/>'),
        ('external entity',b'<!DOCTYPE package [<!ENTITY e SYSTEM "file:///not-authorized">]><package>&e;</package>'),
        ('entity expansion',b'<!DOCTYPE package [<!ENTITY a "AAAA">]><package>&a;</package>'),
        ('namespace',b'<package xmlns="urn:test"/>'),('prefixed namespace',b'<x:package xmlns:x="urn:test"/>'),
        ('duplicate attribute',b'<package a="1" a="2"/>'),('multiple roots',b'<package/><package/>'),
        ('wrong root',b'<graph/>'),('UTF16',b'\xff\xfe<\x00p\x00'),('wrong declared encoding',b'<?xml version="1.0" encoding="latin-1"?><package/>'),
        ('XML11',b'<?xml version="1.1"?><package/>'),('null',b'<package>\0</package>'),('bytearray',bytearray(xml)),('empty',b'')]:
        refused(label,data)
    bounded('XML byte limit','MAX_XML',16,xml)
    bounded('XML depth limit','MAX_XML_DEPTH',2,b'<package><x><x/></x></package>')
    bounded('XML node limit','MAX_XML_NODES',3,b'<package><x/><x/><x/></package>')
    bounded('XML comment node limit','MAX_XML_NODES',2,b'<package><!--a--><!--b--></package>')
    bounded('XML attribute limit','MAX_ATTRIBUTES',1,b'<package a="1" b="2"/>')
    bounded('aggregate XML bytes','MAX_XML',30,fixture([('package.sbs',b'<package>123456789</package>'),('resources/other.sbs',b'<package/>')]))
    bounded('aggregate XML nodes','MAX_XML_NODES',3,fixture([('package.sbs',b'<package><x/></package>'),('resources/other.sbs',b'<package><x/></package>')]))
    raw=bytes(range(256))*64;value=embedded(raw);result=container.inspect_bytes(xml_resource(value))
    check('embedded original bytes retained',list(result['embedded'].values())==[raw] and result['embedded_bytes']==len(raw))
    check('native-compatible base64 whitespace',container.embedded_bytes(' \n'+value+'\n')==raw)
    for label,value in [('truncated header',base64.b64encode(b'123').decode()),('invalid base64','###'),
        ('short embedded data',embedded(raw,declared=len(raw)-1)),('long embedded data',embedded(raw,declared=len(raw)+1)),
        ('extra zlib tail',embedded(raw,tail=b'garbage')),('second zlib stream',embedded(raw,tail=zlib.compress(b'second'))),
        ('declared resource budget',embedded(b'',declared=container.MAX_EMBEDDED+1)),
        ('broken zlib',base64.b64encode(b'\0\0\0\4bad').decode())]:
        refused(label,xml_resource(value))
    correct=xml_resource(embedded(raw)).replace(b'<binembedded>',b'<binembedded><datalength v="16384"/>')
    check('redundant embedded length agrees',container.inspect_bytes(correct)['embedded_bytes']==len(raw))
    refused('redundant embedded length mismatch',correct.replace(b'v="16384"',b'v="1"'))
    refused('duplicate embedded length',correct.replace(b'<binembedded>',b'<binembedded><datalength v="16384"/>'))
    refused('duplicate embedded stream',xml_resource(embedded(raw)).replace(b'</binembedded>',('<strdata v="'+embedded(raw)+'"/></binembedded>').encode()))
    check('DTD text inside comment remains inert',container.inspect_bytes(b'<package><!--<!DOCTYPE ignored>--></package>')['xml_nodes']==2)
    bounded('embedded resource aggregate budget','MAX_EMBEDDED_TOTAL',len(raw)-1,xml_resource(embedded(raw)))
    refused('ambiguous embedded fields',b'<package><strdata v="AAAAAA==" other="ignored"/></package>')
    refused('embedded child content',b'<package><strdata v="AAAAAA=="><x/></strdata></package>')
    data=crafted(name=b'package.sbs',payload=xml);central=directory(data);end=len(data)-22
    for label,position,layout,value in [
        ('multi disk',end+4,'<H',1),('entry count',end+10,'<H',4097),('directory size',end+12,'<I',2**22),
        ('directory offset',end+16,'<I',central+1),('member disk',central+34,'<H',1),
        ('member checksum',14,'<I',0),('member size',22,'<I',99999),('member method',8,'<H',0),
        ('member offset',central+42,'<I',central),('member flag mismatch',6,'<H',1),('unavailable extra',28,'<H',65535)]:
        refused(label,change(data,position,layout,value))
    for label,blob in [('truncated ZIP',data[:-1]),('ZIP trailer',data+b'trailer'),('ZIP preamble',b'preamble'+data),
        ('missing SBS',fixture([('other.txt',b'a')])),('multiple root SBS',fixture([('a.sbs',xml),('b.sbs',xml)])),
        ('case collision',fixture([('package.sbs',xml),('PACKAGE.sbs',xml)])),
        ('file-directory collision',fixture([('package.sbs',xml),('resources',b'x'),('resources/x',b'y')])),
        ('directory with data',fixture([('package.sbs',xml),('resources/',b'hidden')])),
        ('duplicate name',fixture([('package.sbs',xml),('package.sbs',xml)]))]:refused(label,blob)
    for name in (b'../package.sbs',b'/package.sbs',b'a//b',b'a\\b',b'a:package.sbs',b'package.sbs\x00tail',b'a\n',b'a'*513):
        refused('unsafe ZIP name '+repr(name[:30]),crafted(name=name,payload=xml))
    for mode in (stat.S_IFLNK,stat.S_IFCHR,stat.S_IFIFO,stat.S_IFSOCK):
        refused('ZIP special file '+str(mode),crafted(name=b'package.sbs',payload=xml,attributes=mode<<16))
    refused('unbounded ZIP expansion',crafted(name=b'package.sbs',payload=xml,declared=container.MAX_XML+1))
    refused('ZIP compression tail',crafted(name=b'package.sbs',payload=xml,encoded=zlib.compress(xml)[2:-4]+b'trailing'))
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);p=root/'native.sbs';p.write_bytes(xml)
        check('regular file read exact',container.read_native(p)['source_bytes']==xml and p.read_bytes()==xml)
        link=root/'link';link.symlink_to(p);refused('final symlink',link,container.read_native)
        fifo=root/'fifo';os.mkfifo(fifo);refused('FIFO without blocking',fifo,container.read_native)
        refused('directory path',root,container.read_native)
    for path in args.native:
        source=path.read_bytes();result=container.inspect_bytes(source)
        check('real native snapshot '+path.name,result['source_bytes']==source and path.read_bytes()==source and not result['engine_admission_complete'])
        if result['format']=='mcraft':
            with zipfile.ZipFile(io.BytesIO(source)) as archive:
                check('real native member agreement '+path.name,result['members']=={n:archive.read(n) for n in archive.namelist() if not n.endswith('/')})
        native.append({'path':str(path),'sha256':result['source_sha256'],'members':len(result['members']),'xml_nodes':result['xml_nodes'],'embedded_bytes':result['embedded_bytes']})
    rng=random.Random(50617);accepted=0;rejected=0
    for _ in range(1000):
        changed=bytearray(data);index=rng.randrange(len(changed));changed[index]^=rng.randrange(1,256)
        try:result=container.inspect_bytes(bytes(changed))
        except ValueError:rejected+=1;continue
        with zipfile.ZipFile(io.BytesIO(changed)) as archive:
            assert result['members']=={n:archive.read(n) for n in archive.namelist()}
        accepted+=1
    check('1000 deterministic mutations agree or refuse',accepted+rejected==1000)
    result={'passed':True,'checks':checks,'native':native,'mutations':{'accepted':accepted,'refused':rejected},'seconds':time.monotonic()-started,'engine_started':False,'engine_admission_complete':False}
    args.evidence.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':len(checks),'native':len(native),'mutations':1000,'evidence':str(args.evidence)}))


if __name__=='__main__':main()
