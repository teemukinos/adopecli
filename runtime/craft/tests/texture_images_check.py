#!/usr/bin/env python3
"""Local Texture image admission checks, with optional retained fixtures."""
import argparse
import io
import json
from pathlib import Path
import struct
import sys
import time
import zlib
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from studio_runtime import texture_images as images, texture_image_codecs as codecs


def rle_pack(data):
    """Independent fixture encoder for OpenEXR's signed PackBits runs."""
    out=bytearray();cursor=0
    while cursor<len(data):
        end=cursor+1
        while end<len(data) and end-cursor<128 and data[end]==data[cursor]:end+=1
        if end-cursor>=3:
            out.extend((end-cursor-1,data[cursor]));cursor=end
        else:
            start=cursor;cursor=end
            while cursor<len(data) and cursor-start<128:
                if cursor+2<len(data) and data[cursor]==data[cursor+1]==data[cursor+2]:break
                cursor+=1
            out.append(256-(cursor-start));out.extend(data[start:cursor])
    return bytes(out)


def exr_fixture(width=16, height=8, compression=3, sample_size=2, values=(0.75,0.5,0.25), display=None,
                extra_attributes=(), tiles=None, reverse_storage=False, pixel_values=None):
    def attribute(name, kind, data):
        return name.encode()+b'\0'+kind.encode()+b'\0'+struct.pack('<I',len(data))+data
    names=(b'A',b'B',b'G',b'R') if len(values)==4 else (b'B',b'G',b'R')
    channels=b''.join(name+b'\0'+struct.pack('<IB3sii',1 if sample_size==2 else 2,0,b'\0'*3,1,1) for name in names)+b'\0'
    window=struct.pack('<4i',0,0,width-1,height-1)
    attrs=[('channels','chlist',channels),('compression','compression',bytes([compression])),('dataWindow','box2i',window),
           ('displayWindow','box2i',window if display is None else struct.pack('<4i',*display)),('lineOrder','lineOrder',b'\0'),
           ('pixelAspectRatio','float',struct.pack('<f',1)),('screenWindowCenter','v2f',struct.pack('<2f',0,0)),('screenWindowWidth','float',struct.pack('<f',1))]
    if tiles:attrs.extend([('tiles','tiledesc',struct.pack('<IIB',*tiles,0)),('type','string',b'tiledimage')])
    attrs.extend(extra_attributes)
    header=b'\x76\x2f\x31\x01'+struct.pack('<I',0x202 if tiles else 2)+b''.join(attribute(*a) for a in attrs)+b'\0'
    block_width,block_height=tiles if tiles else (width,16 if compression==3 else 1);blocks=[]
    for y in range(0,height,block_height):
        for x in range(0,width,block_width):
            row=b''.join(struct.pack('<e' if sample_size==2 else '<f',value)*min(block_width,width-x) for value in values)
            raw=row*min(block_height,height-y)
            if pixel_values is not None:
                raw=b''.join(struct.pack('<e' if sample_size==2 else '<f',pixel_values(xx,yy)[channel])
                    for yy in range(y,min(height,y+block_height)) for channel in range(len(values)) for xx in range(x,min(width,x+block_width)))
            if compression:
                shuffled=raw[::2]+raw[1::2]
                predicted=bytes([shuffled[0]])+bytes((shuffled[i]-shuffled[i-1]+128)&255 for i in range(1,len(shuffled)))
                compressed=rle_pack(predicted) if compression==1 else zlib.compress(predicted)
                encoded=compressed if len(compressed)<len(raw) else raw
            else:encoded=raw
            chunk=struct.pack('<4iI',x//block_width,y//block_height,0,0,len(encoded)) if tiles else struct.pack('<iI',y,len(encoded))
            blocks.append(chunk+encoded)
    start=len(header)+8*len(blocks);offsets=[0]*len(blocks);physical=[]
    for index in reversed(range(len(blocks))) if reverse_storage else range(len(blocks)):
        offsets[index]=start;physical.append(blocks[index]);start+=len(blocks[index])
    return header+b''.join(struct.pack('<Q',offset) for offset in offsets)+b''.join(physical)


def hdr_fixture(width=16,height=8,rle=True):
    header=f'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y {height} +X {width}\n'.encode()
    if rle:
        row=b'\x02\x02'+struct.pack('>H',width)+b''.join(bytes([128+width,value]) for value in (64,128,192,128))
    else:row=bytes([64,128,192,128])*width
    return header+row*height


def fixtures():
    result={}
    for fmt,extension in (('PNG','png'),('JPEG','jpg'),('TGA','tga'),('TIFF','tif'),('BMP','bmp'),('WEBP','webp')):
        output=io.BytesIO();Image.new('RGB',(16,8),(137,188,225)).save(output,format=fmt,quality=100,subsampling=0,lossless=True)
        result['sample.'+extension]=output.getvalue()
    result['sample.hdr']=hdr_fixture()
    result['sample.exr']=exr_fixture()
    return result


def replace_attribute(data,name,value):
    data=bytearray(data);position=8
    while data[position]:
        end=data.index(0,position);key=bytes(data[position:end]).decode();position=end+1
        end=data.index(0,position);position=end+1
        length=struct.unpack_from('<I',data,position)[0];position+=4
        if key==name:
            assert len(value)==length;data[position:position+length]=value;return bytes(data)
        position+=length
    raise AssertionError(name)


def exr_table(data):
    position=8
    while data[position]:
        position=data.index(0,position)+1;position=data.index(0,position)+1
        length=struct.unpack_from('<I',data,position)[0];position+=4+length
    return position+1


def changed(data,position,layout,value):
    result=bytearray(data);struct.pack_into(layout,result,position,value);return bytes(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--fixtures',type=Path);parser.add_argument('--native',type=Path,action='append',default=[]);parser.add_argument('--evidence',type=Path)
    args=parser.parse_args();checks=[];started=time.monotonic();samples=fixtures()
    def check(label,value):assert value,label;checks.append(label)
    def refused(label,data):
        try:images.inspect_bytes(data)
        except ValueError:checks.append(label)
        else:raise AssertionError('unexpected image admission: '+label)
    for name,data in samples.items():
        r=images.inspect_bytes(data);check('complete resource '+name,(r['width'],r['height'],r['decoded_rgba_bytes'])==(16,8,2048))
        refused('truncated resource '+name,data[:len(data)//2])
    for compression in (0,1,2,3):
        for size in (2,4):
            data=exr_fixture(compression=compression,sample_size=size)
            check(f'EXR compression {compression}, sample bytes {size}',images.inspect_bytes(data)['compression']==compression)
            for value in (float('nan'),float('inf'),float('-inf')):
                refused(f'EXR nonfinite {value}, compression {compression}, size {size}',exr_fixture(compression=compression,sample_size=size,values=(value,0.5,0.25)))
    refused('EXR hidden tile metadata without flags',exr_fixture(extra_attributes=[('tiles','tiledesc',struct.pack('<IIB',16,8,0))]))
    refused('EXR hidden deep metadata without flags',exr_fixture(extra_attributes=[('maxSamplesPerPixel','int',struct.pack('<i',100))]))
    check('EXR display and data windows are independent',images.inspect_bytes(exr_fixture(display=(-1,-1,17,9)))['width']==19)
    exr=samples['sample.exr'];table=exr_table(exr);offset=struct.unpack_from('<Q',exr,table)[0]
    for label,data in [('EXR flags',changed(exr,4,'<I',0x202)),('EXR enormous chunk offset',changed(exr,table,'<Q',1<<63)),
        ('EXR offset into directory',changed(exr,table,'<Q',table)),('EXR bad chunk row',changed(exr,offset,'<i',1)),
        ('EXR huge packed size',changed(exr,offset+4,'<I',0xffffffff)),('EXR trailing bytes',exr+b'x'),
        ('EXR unsupported compression',replace_attribute(exr,'compression',b'\x04')),
        ('EXR huge data window',replace_attribute(exr,'dataWindow',struct.pack('<4i',0,0,9000,7))),
        ('EXR huge display window',replace_attribute(exr,'displayWindow',struct.pack('<4i',0,0,9000,7))),
        ('EXR reversed window',replace_attribute(exr,'dataWindow',struct.pack('<4i',16,0,15,7))),
        ('EXR nonfinite metadata',replace_attribute(exr,'screenWindowWidth',struct.pack('<f',float('nan'))))]:refused(label,data)
    two=exr_fixture(height=32);table=exr_table(two);first=struct.unpack_from('<Q',two,table)[0]
    refused('EXR aliased chunks',changed(two,table+8,'<Q',first))
    refused('EXR truncated offset table',two[:table+7])
    corrupt=bytearray(exr);corrupt[offset+8]^=0xff;refused('EXR corrupt ZIP stream',bytes(corrupt))
    # A second ZIP stream must not be silently ignored.
    extra=zlib.compress(b'ignored');with_extra=exr+extra
    with_extra=changed(with_extra,offset+4,'<I',len(exr)-offset-8+len(extra));refused('EXR concatenated ZIP stream',with_extra)
    for tiles in ((16,8),(64,64),(1,1),(256,256)):
        for compression in (0,1,2,3):
            for size in (2,4):
                data=exr_fixture(width=35,height=19,tiles=tiles,compression=compression,sample_size=size,reverse_storage=True)
                report=images.inspect_bytes(data)
                check(f'EXR tiled edge blocks {tiles} compression {compression} sample {size}',report['storage']=='tiles' and report['width']==35 and report['height']==19
                      and report['chunks']==((35+tiles[0]-1)//tiles[0])*((19+tiles[1]-1)//tiles[1]))
                for value in (float('nan'),float('inf'),float('-inf')):
                    refused(f'EXR tiled nonfinite {value} {tiles} {compression} {size}',exr_fixture(width=35,height=19,tiles=tiles,compression=compression,sample_size=size,values=(0.75,value,0.25)))
    for compression in (0,1,2,3):
        for size in (2,4):
            data=exr_fixture(width=35,height=19,tiles=(13,9),compression=compression,sample_size=size,values=(.5,.75,.5,.25))
            check(f'EXR RGBA tiles compression {compression} sample {size}',images.inspect_bytes(data)['chunks']==9)
            for value in (float('nan'),float('inf'),float('-inf')):
                refused(f'EXR tiled nonfinite alpha {value} {compression} {size}',exr_fixture(tiles=(13,9),compression=compression,sample_size=size,values=(value,.75,.5,.25)))
    tile=exr_fixture(width=35,height=19,tiles=(16,8),compression=1,sample_size=4)
    table=exr_table(tile);offset=struct.unpack_from('<Q',tile,table)[0]
    for label,data in [('EXR tile flag absent',changed(tile,4,'<I',2)),('EXR deep flag',changed(tile,4,'<I',0xa02)),
        ('EXR tile alias',changed(tile,table+8,'<Q',offset)),('EXR tile offset into table',changed(tile,table,'<Q',table)),
        ('EXR tile truncated header',tile[:offset+19]),('EXR tile negative column',changed(tile,offset,'<i',-1)),
        ('EXR tile wrong row',changed(tile,offset+4,'<i',1)),('EXR tile nonzero x level',changed(tile,offset+8,'<i',1)),
        ('EXR tile nonzero y level',changed(tile,offset+12,'<i',1)),('EXR tile huge packed size',changed(tile,offset+16,'<I',1<<31)),
        ('EXR tile trailing bytes',tile+b'x'),('EXR tile wrong part type',tile.replace(b'tiledimage',b'deeptilexx'))]:refused(label,data)
    for tw,th,mode in ((0,8,0),(16,0,0),(257,8,0),(16,257,0),(16,8,1),(16,8,2),(16,8,32),(16,8,255)):
        refused('EXR invalid tile dimensions or mode '+str((tw,th,mode)),replace_attribute(tile,'tiles',struct.pack('<IIB',tw,th,mode)))
    check('EXR single-level round-up mode',images.inspect_bytes(replace_attribute(tile,'tiles',struct.pack('<IIB',16,8,16)))['chunks']==9)
    many=replace_attribute(tile,'tiles',struct.pack('<IIB',1,1,0))
    many=replace_attribute(many,'dataWindow',struct.pack('<4i',0,0,1023,1023))
    refused('EXR tile count budget before offset allocation',many)
    for compression in (1,2,3):
        original=bytes(range(256))*3+b'\x19'*401
        shuffled=original[::2]+original[1::2]
        predicted=bytes([shuffled[0]])+bytes((shuffled[i]-shuffled[i-1]+128)&255 for i in range(1,len(shuffled)))
        encoded=rle_pack(predicted) if compression==1 else zlib.compress(predicted)
        check('EXR complete byte reconstruction '+str(compression),codecs.exr_block(encoded,len(original),compression)==original)
    for label,encoded,expected in [('missing repeat value',b'\x05',6),('truncated literal',b'\xfd\x01',4),
        ('repeat overflow',b'\x7f\0',12),('literal overflow',b'\xfdabc',2),('underfilled output',b'\0x',4),
        ('trailing RLE token',b'\x09x\0y',10)]:
        try:codecs.exr_block(encoded,expected,1)
        except ValueError:checks.append('EXR RLE '+label)
        else:raise AssertionError('accepted RLE '+label)
    check('HDR old flat scanlines',images.inspect_bytes(hdr_fixture(rle=False))['format']=='HDR')
    hdr=samples['sample.hdr'];body=hdr.index(b'+X 16\n')+len(b'+X 16\n')
    for label,data in [('HDR huge dimensions',hdr.replace(b'+X 16',b'+X 99999')),('HDR unsupported orientation',hdr.replace(b'-Y 8',b'+Y 8')),
        ('HDR unsupported format',hdr.replace(b'32-bit_rle_rgbe',b'32-bit_rle_xyze')),('HDR missing format',hdr.replace(b'FORMAT=32-bit_rle_rgbe\n',b'')),
        ('HDR duplicate format',hdr.replace(b'FORMAT=',b'FORMAT=32-bit_rle_rgbe\nFORMAT=')),('HDR trailing bytes',hdr+b'x'),
        ('HDR mismatched scanline width',hdr[:body+3]+b'\x11'+hdr[body+4:]),
        ('HDR empty run',hdr[:body+4]+b'\0'+hdr[body+5:]),('HDR overlong run',hdr[:body+4]+b'\xff'+hdr[body+5:]),
        ('HDR nonfinite exposure',hdr.replace(b'FORMAT=',b'EXPOSURE=NaN\nFORMAT=')),
        ('HDR huge header',hdr.replace(b'FORMAT=',b'#'+b'x'*1025+b'\nFORMAT='))]:refused(label,data)
    raw=hdr_fixture(width=4,height=1,rle=False);body=raw.index(b'+X 4\n')+len(b'+X 4\n')
    repeated=raw[:body]+raw[body:body+4]+bytes([1,1,1,3])
    check('HDR old repeat scanline',images.inspect_bytes(repeated)['width']==4)
    refused('HDR old repeat first pixel',raw[:body]+bytes([1,1,1,4]))
    refused('HDR old repeat overflow',raw[:body]+raw[body:body+4]+bytes([1,1,1,4]))
    refused('HDR zero repeat amplification',raw[:body]+raw[body:body+4]+bytes([1,1,1,0])*8)
    for fmt in ('PNG','TIFF','WEBP'):
        output=io.BytesIO();Image.new('RGB',(2,2),'red').save(output,format=fmt,save_all=True,append_images=[Image.new('RGB',(2,2),'blue')])
        refused('multiple frames '+fmt,output.getvalue())
    for data in (b'',b'garbage',b'GIF89a'+b'\0'*30):refused('invalid or unsupported image '+repr(data[:10]),data)
    structure={'image_references':['sample.png'],'linked_packages':['source.mcraft']}
    members={'resources/sample.png':samples['sample.png'],'resources/source.mcraft':b'opaque unexecuted package'}
    check('image and opaque package admitted distinctly',images.inspect_resources(members,structure)['packages']['source.mcraft']['cook_authorized'] is False)
    def resource_refused(label,members,structure):
        try:images.inspect_resources(members,structure)
        except ValueError:checks.append(label)
        else:raise AssertionError(label)
    preflight=images.inspect_resources(members,structure)
    native_resources=[{'name':'sample.png','width':16,'height':8,'bytes':len(samples['sample.png'])},{'name':'source.mcraft','width':0,'height':0,'bytes':len(members['resources/source.mcraft'])}]
    check('native decoder and opaque package agreement',images.check_native_resources(preflight,native_resources)=={'images':1,'opaque_packages':1})
    for label,rows in [('native missing resource',native_resources[:1]),('native duplicate resource',[native_resources[0]]*2),
        ('native zero-size decode failure',[{**native_resources[0],'width':0},native_resources[1]]),
        ('native boolean dimension',[{**native_resources[0],'width':True},native_resources[1]]),
        ('native truncated resource',[{**native_resources[0],'bytes':1},native_resources[1]]),
        ('native unexpected resource',[{**native_resources[0],'name':'other.png'},native_resources[1]]),
        ('native package decoded as image',[native_resources[0],{**native_resources[1],'width':16}])]:
        try:images.check_native_resources(preflight,rows)
        except ValueError:checks.append(label)
        else:raise AssertionError(label)
    resource_refused('missing image',{},structure)
    resource_refused('package cannot also serve as image',members,{'image_references':['source.mcraft'],'linked_packages':['source.mcraft']})
    resource_refused('image cannot serve as package',members,{'image_references':['sample.png'],'linked_packages':['sample.png']})
    resource_refused('noncanonical resource filename',{'resources/.hidden.png':samples['sample.png']},{'image_references':[],'linked_packages':[]})
    limit=images.MAX_TOTAL_TEXELS
    try:
        images.MAX_TOTAL_TEXELS=128
        resource_refused('aggregate image allocation',{'resources/a.png':samples['sample.png'],'resources/b.png':samples['sample.png']},{'image_references':[],'linked_packages':[]})
    finally:images.MAX_TOTAL_TEXELS=limit
    native=[]
    for path in args.native:
        before=path.read_bytes();report=images.inspect_bytes(before);check('native image '+path.name,path.read_bytes()==before);native.append({'path':str(path),**report})
    if args.fixtures:
        args.fixtures.mkdir()
        for name,data in samples.items():(args.fixtures/name).write_bytes(data)
    report={'passed':True,'checks':len(checks),'cases':checks,'native_images':native,'seconds':round(time.monotonic()-started,4),
            'scope':'image resource validation; native decoder agreement remains required','runtime_available':False,'goal_complete':False}
    if args.evidence:args.evidence.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','checks','seconds','scope')}))


if __name__=='__main__':main()
