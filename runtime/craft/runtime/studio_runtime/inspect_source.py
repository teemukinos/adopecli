"""Bounded data admission for static inspection. No input grants execution rights."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from . import animate_format

MAX_INPUT = 16 << 20
MAX_JAVASCRIPT = 2 << 20
MAX_REPORT = 32 << 20
MAX_ARCHIVE = 128 << 20
PROFILE = 'static-artifact-v1'
KINDS = ('native', 'wasm', 'javascript')
PIN = {'product':'dobe-inspect', 'version':'0.6.1', 'source_revision':'48a9c5a60ff83ff620f98661339be6281a7debc6',
       'source_lock_sha256':'5d3546292bec27b3a0e8f466e26f2013617bba464b075e1f5514ef48dc312975'}


def require(condition, message):
    if not condition: raise ValueError('Inspect '+message)


def sha(data):
    require(type(data) is bytes, 'input must be immutable bytes')
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    try: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as error: raise ValueError('Inspect value cannot be encoded') from error


def fields(value, names, label): require(type(value) is dict and set(value)==set(names), label+' fields differ')


def digest(value): require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'SHA-256 is invalid')


def pin(value):
    require(type(value) is dict and encoded(value)==encoded(PIN), 'engine pin differs')
    return dict(PIN)


def text(value, maximum, label):
    require(type(value) is str and not any(0xd800<=ord(c)<=0xdfff for c in value), label+' must be valid Unicode')
    require(len(value.encode())<=maximum and not any(ord(c)<32 and c not in '\n\t' for c in value), label+' exceeds its text profile')


def strict_json(data):
    require(type(data) is bytes and 0<len(data)<=MAX_REPORT, 'JSON exceeds byte budget')
    try: animate_format._preflight(data, 2_000_000)
    except ValueError as error: raise ValueError('Inspect JSON preflight refused: '+str(error)) from error
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result, 'JSON contains duplicate keys'); result[key]=value
        return result
    def integer(token):
        require(len(token.lstrip('-'))<=20, 'JSON integer exceeds native range')
        value=int(token); require(-2**63<=value<2**64, 'JSON integer exceeds native range'); return value
    def floating(token):
        value=float(token); require(math.isfinite(value), 'JSON number is not finite'); return value
    def constant(_): raise ValueError('Inspect JSON number is not finite')
    try: value=json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_int=integer,parse_float=floating,parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error: raise ValueError('Inspect JSON malformed: '+str(error)) from error
    pending=[value];count=0
    while pending:
        item=pending.pop();count+=1;require(count<=2_000_000, 'JSON node budget exceeded')
        if type(item) is dict:pending.extend(item);pending.extend(item.values())
        elif type(item) is list:pending.extend(item)
        elif type(item) is str:require(not any(0xd800<=ord(c)<=0xdfff for c in item), 'JSON contains invalid Unicode')
    return value


def read_bytes(path, maximum=MAX_ARCHIVE):
    descriptor=os.open(Path(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        before=os.fstat(stream.fileno());require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=maximum, 'input must be a bounded regular file')
        data=stream.read(maximum+1);after=os.fstat(stream.fileno())
        require(len(data)==before.st_size and (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'input changed while reading')
        return data


def input_bytes(data, kind, expected):
    require(type(kind) is str and kind in KINDS, 'unsupported input format');digest(expected)
    require(type(data) is bytes and 0<len(data)<=(MAX_JAVASCRIPT if kind=='javascript' else MAX_INPUT), 'input exceeds selected profile')
    require(sha(data)==expected, 'input differs from explicitly authorized SHA-256')
    if kind=='javascript':
        try: decoded=data.decode('utf-8')
        except UnicodeError as error:raise ValueError('Inspect JavaScript must be UTF-8') from error
        require('\0' not in decoded, 'JavaScript contains a NUL byte')
    return {'sha256':expected,'bytes':len(data),'format':kind}


def report_bytes(data, original, kind):
    input_bytes(original,kind,sha(original));value=strict_json(data)
    fields(value,('schema_version','product','profile','source_revision','input_sha256','input_bytes','input_executed','external_references_resolved','evidence'),'report')
    require(type(value['schema_version']) is int and value['schema_version']==1 and value['product']=='dobe-inspect'
            and value['profile']==PROFILE and value['source_revision']==PIN['source_revision'], 'report identity differs')
    require(value['input_sha256']==sha(original) and type(value['input_bytes']) is int and value['input_bytes']==len(original)
            and value['input_executed'] is False and value['external_references_resolved'] is False, 'report source or effects differ')
    evidence=value['evidence'];require(type(evidence) is dict and evidence.get('carries_target_content') is True, 'report must mark target content untrusted')
    require(type(evidence.get('id')) is str and re.fullmatch('ev_[0-9a-f]{64}',evidence['id']), 'evidence identifier invalid')
    require(evidence.get('subject')=={'kind':kind,'sha256':sha(original)} and evidence.get('operation')=='dobe_static_inspect'
            and evidence.get('authority')=='original-files', 'evidence source authority differs')
    from .inspect_host import environment
    environment(evidence.get('environment'))
    require(type(evidence.get('result')) is dict, 'report findings missing')
    return value


def pointer(report, value):
    text(value,1024,'finding pointer');require(value.startswith('/evidence/result'), 'annotation must reference native findings')
    require(value=='/evidence/result' or value.startswith('/evidence/result/'), 'finding pointer prefix invalid')
    current=report
    for token in value.split('/')[1:]:
        require(not re.search('~(?![01])',token), 'finding pointer escape invalid');token=token.replace('~1','/').replace('~0','~')
        if type(current) is dict:require(token in current, 'finding pointer missing');current=current[token]
        elif type(current) is list:
            require(re.fullmatch('0|[1-9][0-9]*',token) and len(token)<=8 and int(token)<len(current), 'finding array index invalid');current=current[int(token)]
        else:raise ValueError('Inspect finding pointer descends through a scalar')
    return current
