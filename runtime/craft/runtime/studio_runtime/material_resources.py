"""SBS package/resource inventory before graph and execution admission.

Only snapshot members are resolved. No saved path grants filesystem access.
Graph bodies remain opaque here; this module never authorizes native execution.
"""
import hashlib
import json

from . import material_container as container, texture_images
from .material_container import require

MAX_PACKAGES = 64
MAX_ITEMS = 4096
MAX_RESOURCES = 256
MAX_RESOURCE_BYTES = 128 << 20
MAX_TEXELS = 33_554_432
EXTENSIONS = {'png':'PNG','jpg':'JPEG','jif':'JPEG','jpeg':'JPEG','jpe':'JPEG',
              'tga':'TGA','targa':'TGA','tif':'TIFF','tiff':'TIFF','bmp':'BMP','webp':'WEBP','exr':'EXR','hdr':'HDR'}


def children(element):
    require(not element['attributes'], 'container element has unknown attributes: '+element['tag'])
    result=[]
    for item in element['content']:
        if 'tag' in item:result.append(item)
        else:require('text' in item and not item['text'].strip(), 'non-element XML content requires an explicit preservation policy')
    return result


def fields(element, required, optional=()):
    result={}
    for item in children(element):
        tag=item['tag'];require(tag in required or tag in optional,'unknown '+element['tag']+' field: '+tag)
        require(tag not in result,'duplicate '+element['tag']+' field: '+tag);result[tag]=item
    require(set(required)<=result.keys(),'missing required '+element['tag']+' fields')
    return result


def scalar(element):
    require(set(element['attributes'])=={'v'} and not element['content'],'scalar XML field has missing or extra content: '+element['tag'])
    return element['attributes']['v']


def identifier(value):
    require(0<len(value)<=512 and value==value.strip() and value not in ('.','..')
            and not any(c in '/\\' or ord(c)<32 or ord(c)==127 for c in value),'item identifier would be recovered or has an ambiguous path')
    return value


def uid(element):
    value=scalar(element)
    require(value.isascii() and value.isdecimal() and len(value)<=20 and int(value)<=2**64-1,'UID is not an unsigned 64-bit integer')
    require(str(int(value))==value,'UID requires canonical decimal spelling for native reference agreement')
    return int(value)


def resolve(owner, reference):
    require(type(reference) is str and 0<len(reference)<=4096 and not reference.startswith('/')
            and not any(c in reference for c in ('\\',':','\0')),'reference needs an explicitly admitted external dependency')
    parts=owner.split('/')[:-1]
    for part in reference.split('/'):
        if part in ('','.'):continue
        if part=='..':
            require(parts,'archive reference escapes its root');parts.pop()
        else:parts.append(part)
    require(parts,'archive reference is empty')
    return '/'.join(parts)


def inspect(profile):
    members=profile['members']; pending=[profile['root']]; used=set(); packages={}; resources={}; total_bytes=0;texels=0;items=0
    while pending:
        path=pending.pop()
        if path in packages:continue
        require(len(packages)<MAX_PACKAGES,'package dependency count exceeds its budget')
        require(path in profile['xml'],'package dependency is missing or is not SBS XML')
        parsed=profile['xml'][path];root=fields(parsed['root'],('identifier','formatVersion','updaterVersion','fileUID','versionUID','dependencies','content'))
        name=identifier(scalar(root['identifier']));used.add(path)
        package={'name':name,'metadata':{key:scalar(root[key]) for key in ('formatVersion','updaterVersion','fileUID','versionUID')},
                 'dependencies':{},'graphs':{},'folders':{},'resources':{}}
        uid(root['fileUID']);uid(root['versionUID']);packages[path]=package
        seen_uids=set();seen_paths=set();resource_names=set();self_count=0
        for entry in children(root['dependencies']):
            require(entry['tag']=='dependency','unknown dependency entry')
            record=fields(entry,('filename','uid','type','fileUID','versionUID'));identity=uid(record['uid'])
            require(identity not in seen_uids,'duplicate package UID');seen_uids.add(identity)
            require(scalar(record['type'])=='package','dependency type is unqualified');uid(record['fileUID']);uid(record['versionUID'])
            reference=scalar(record['filename'])
            if reference=='?himself':target=path;self_count+=1
            else:
                require(profile['format']=='mcraft','bare SBS cannot resolve external package paths')
                target=resolve(path,reference);require(target in profile['xml'],'archive package dependency is missing');pending.append(target)
            package['dependencies'][identity]={'reference':reference,'member':target}
        require(self_count==1,'package requires exactly one self dependency')
        stack=[('',root['content'])]
        element_indices={id(element):index for index,element in enumerate(parsed['elements'])}
        while stack:
            folder,content=stack.pop()
            for item in children(content):
                items+=1;require(items<=MAX_ITEMS,'package item count exceeds its budget')
                kind=item['tag'];require(kind in ('graph','function','group','resource'),'unknown package item: '+kind)
                if kind in ('graph','function'):
                    # Graph semantics are a later prerequisite. Do not assume
                    # that successful metadata/resource admission can cook it.
                    values=children(item); ids=[v for v in values if v['tag']=='identifier'];uids=[v for v in values if v['tag']=='uid']
                    require(len(ids)==1 and len(uids)==1,'graph identity is missing or duplicated')
                    label=identifier(scalar(ids[0]));identity=uid(uids[0]);record=None
                else:
                    record=fields(item,('identifier','uid','content') if kind=='group' else ('identifier','uid','type','format','filepath','source'),('desc',) if kind=='group' else ())
                    label=identifier(scalar(record['identifier']));identity=uid(record['uid'])
                full=folder+'/'+label if folder else label
                require(full not in seen_paths,'duplicate package item path');seen_paths.add(full)
                require(identity not in seen_uids,'duplicate package item UID');seen_uids.add(identity)
                if kind=='group':
                    package['folders'][full]=scalar(record['desc']) if 'desc' in record else ''
                    stack.append((full,record['content']));continue
                if kind in ('graph','function'):
                    package['graphs'][full]={'kind':kind,'uid':identity,'element':item};continue
                require(label not in resource_names,'duplicate resource name would be renamed by native loading');resource_names.add(label)
                require(len(resources)<MAX_RESOURCES,'resource count exceeds its budget')
                require(scalar(record['type'])=='bitmap','SVG resources require separate vector admission')
                extension=scalar(record['format']);require(extension in EXTENSIONS,'resource format requires additional qualification: '+extension)
                require(not scalar(record['filepath']),'legacy or redundant resource filepath requires explicit conversion')
                source=children(record['source']);require(len(source)==1,'resource needs one unambiguous byte source')
                source=source[0]
                if source['tag']=='binembedded':
                    embedded=fields(source,('datalength','strdata'));key=path+':'+str(element_indices[id(embedded['strdata'])])
                    require(key in profile['embedded'],'embedded resource payload is absent')
                    data=profile['embedded'][key];member=None
                else:
                    require(source['tag']=='externalcopy' and profile['format']=='mcraft','resource path requires an admitted archive member')
                    reference=scalar(fields(source,('filename',))['filename']);member=resolve(path,reference)
                    require(member in members and member not in profile['xml'],'resource member is missing or is an SBS package')
                    data=members[member];used.add(member)
                total_bytes+=len(data);require(total_bytes<=MAX_RESOURCE_BYTES,'resource bytes exceed the aggregate budget')
                # Match the native decoder's SVG sniff before any image decode.
                # Valid HDR comments (and some binary headers) can contain text
                # that the native reader would otherwise reinterpret as SVG.
                try: head=data[:4096].decode('utf-8')
                except UnicodeError: head=''
                require('<svg' not in head,'resource would enter the unqualified native SVG decoder')
                decoded=texture_images.inspect_bytes(data)
                require(decoded['format']==EXTENSIONS[extension],'declared resource format disagrees with decoded bytes')
                texels+=decoded['width']*decoded['height'];require(texels<=MAX_TEXELS,'decoded resource texels exceed the aggregate budget')
                native_file=''.join(c if c.isalnum() or c in '._- ' else '_' for c in label+'.'+extension).lstrip('.') or 'resource'
                resource={'name':label,'folder':folder,'file':native_file,'member':member,'bytes':len(data),
                          'sha256':hashlib.sha256(data).hexdigest(),'decoded':decoded,'original_bytes':data}
                resources[json.dumps([path,full],ensure_ascii=False,separators=(',',':'))]=resource;package['resources'][label]=resource
    require(used==set(members),'archive has unreferenced or unknown members that native save could drop')
    return {'packages':packages,'resources':resources,'resource_bytes':total_bytes,'texels':texels,
            'decoded_rgba_bytes':texels*16,'engine_admission_complete':False}


def check_native(profile, inspection, package):
    """Match native resource inventory; exact bytes still need cold member checks."""
    require(type(inspection) is dict and type(inspection.get('package')) is dict, 'native package inspection is malformed')
    expected=profile['packages'][package]['resources'];observed=inspection['package'].get('resources')
    require(type(observed) is list and len(observed)==len(expected),'native resource inventory count differs')
    seen=set()
    for item in observed:
        require(type(item) is dict and type(item.get('name')) is str and type(item.get('bytes')) is int, 'native resource record is malformed')
        name=item.get('name');require(name in expected and name not in seen,'native resource name differs or repeats');seen.add(name)
        resource=expected[name]
        require(all(item.get(key)==resource[key] for key in ('name','folder','file','bytes')) and item.get('missing') is False,
                'native resource metadata differs or resource is missing')
    return {'native_resource_inventory_equal':True,'resource_count':len(expected),'engine_admission_complete':False}
