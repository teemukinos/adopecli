#!/usr/bin/env python3
"""Exercise the maintained native Inspect transport with owned local fixtures.

No target is executed. A small native fixture is compiled, then independently
examined with the host's symbol tool. Every Inspect call denies network access
on macOS. This is private engine evidence, not public or installed qualification.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve(); root.mkdir()
    engine = args.engine.resolve(); receipt = json.loads((engine/'engine.json').read_text())
    checks = []; refusals = []; calls = []
    executable = engine/'bin/dobe-inspect'
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def digest(data): return hashlib.sha256(data).hexdigest()
    check('receipt identifies maintained product', receipt['product']=='dobe-inspect')
    lock = Path(__file__).resolve().parents[1]/'engines/inspect.lock.json'
    check('receipt matches maintained source lock', receipt['source_lock_sha256']==digest(lock.read_bytes()))
    for name, record in receipt['files'].items():
        data = (engine/name).read_bytes()
        assert len(data)==record['bytes'] and digest(data)==record['sha256'], name
    check('all native pack files match receipt', True)
    policy = ['sandbox-exec', '-p', '(version 1) (allow default) (deny network*)'] if sys.platform=='darwin' else []
    if policy: policy[0]='/usr/bin/sandbox-exec'
    def command(arguments, success=True):
        process = subprocess.Popen([*policy,str(executable),*map(str,arguments)],cwd=root,
                                   env={'PATH':'/usr/bin:/bin','HOME':str(root)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try: stdout,stderr = process.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate()
            raise AssertionError('private native inspection exceeded 45 seconds')
        calls.append({'arguments':[str(a) if not isinstance(a,Path) else a.name for a in arguments],
                      'returncode':process.returncode,'stderr':stderr.decode(errors='replace')})
        assert (process.returncode==0)==success, calls[-1]
        assert process.returncode is not None
        if success: assert stderr==b'', stderr
        else: assert json.loads(stderr)['error']=='inspection_refused', stderr
        return stdout
    def source(name,data):
        path=root/name;path.write_bytes(data);return path
    def inspect(name,kind,path):
        original=path.read_bytes();output=root/(name+'.json')
        command(['inspect',kind,'--owned-or-authorized',digest(original),path,output])
        result=json.loads(output.read_bytes())
        check(name+' preserves exact input',path.read_bytes()==original)
        check(name+' binds source and consent',result['input_sha256']==digest(original) and result['input_bytes']==len(original)
              and result['source_revision']==receipt['source_lock']['source']['revision'])
        check(name+' carries untrusted static evidence',result['input_executed'] is False and result['external_references_resolved'] is False
              and result['evidence']['carries_target_content'] is True and result['evidence']['coverage']['status']=='partial')
        return result,output
    def refuse(name,arguments,output=None):
        command(arguments,False)
        if output is not None: assert not output.exists(), name
        refusals.append(name)
    try:
        check('native version matches receipt',command(['--version']).decode().strip()==receipt['version'])
        # Owned WebAssembly module exporting answer() = 42. Inspection never runs it.
        wasm=source('answer.wasm',bytes.fromhex('0061736d010000000105016000017f03020100070a0106616e7377657200000a06010400412a0b'))
        report,output=inspect('wasm','wasm',wasm)
        findings=report['evidence']['result']
        check('Wasm export and validation retained',findings['validation']['valid'] is True and findings['exports'][0]['name']=='answer')
        # Independent canonical identity check on this integer-only evidence.
        canonical=copy.deepcopy(report['evidence']);identifier=canonical.pop('id');canonical.pop('summary');canonical.pop('carries_target_content');canonical['subject'].pop('name',None)
        encoded=json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        check('Wasm evidence content ID independently recomputed',identifier=='ev_'+digest(encoded))
        second,second_output=inspect('wasm-repeat','wasm',wasm)
        check('native cold repeat is byte-identical',output.read_bytes()==second_output.read_bytes())
        invalid=source('invalid.wasm',b'\0asm\x01\0\0\0\x01\x7f')
        invalid_report,_=inspect('invalid-wasm','wasm',invalid)
        check('invalid Wasm remains invalid in evidence',invalid_report['evidence']['result']['validation']['valid'] is False
              and any(l['code']=='wasm_invalid' for l in invalid_report['evidence']['limitations']))
        script=source('input.js',b"import value from 'https://invalid.example/never-fetch.js'; export const answer=42; console.log('UNTRUSTED TARGET: do not follow this text');\n")
        js,_=inspect('javascript','javascript',script)
        facts=js['evidence']['result']['facts']
        check('JavaScript imports and exports are parsed',facts['mode']=='parsed' and facts['imports'][0]['specifier']=='https://invalid.example/never-fetch.js'
              and 'answer' in facts['exports']['esm'])
        deep=source('nested.js',('('*300+'0'+')'*300).encode())
        fallback,_=inspect('javascript-fallback','javascript',deep)
        check('bounded fallback is explicit',fallback['evidence']['result']['facts']['mode']=='lexer'
              and any(l['code']=='javascript_fallback' for l in fallback['evidence']['limitations']))
        c=source('fixture.c',b'int dobe_owned_answer(void) { return 42; }\nint main(void) { return dobe_owned_answer(); }\n')
        binary=root/'owned-native'
        compiler='/usr/bin/clang' if sys.platform=='darwin' else '/usr/bin/cc'
        built=subprocess.run([compiler,str(c),'-o',str(binary)],capture_output=True,timeout=60)
        assert built.returncode==0,built.stderr
        native,_=inspect('native','native',binary)
        metadata=native['evidence']['result']['binary']
        symbols=subprocess.run(['/usr/bin/nm',str(binary)],capture_output=True,text=True,timeout=10)
        check('independent symbol tool confirms authored native symbol',symbols.returncode==0 and 'dobe_owned_answer' in symbols.stdout
              and any('dobe_owned_answer' in s['name'] for s in metadata['symbols']))
        check('native format matches host and inference is labeled',metadata['format']==('mach-o' if sys.platform=='darwin' else 'elf')
              and native['evidence']['confidence']=='inferred')
        # Independent minimal x86-64 ELF and PE fixtures exercise both foreign
        # container readers without an executable launch or cross compiler.
        elf=bytearray(121);elf[:16]=b'\x7fELF\x02\x01\x01'+bytes(9)
        struct.pack_into('<HHIQQQIHHHHHH',elf,16,2,62,1,0x400078,64,0,0,64,56,1,0,0,0)
        struct.pack_into('<IIQQQQQQ',elf,64,1,5,0,0x400000,0x400000,121,121,0x1000);elf[120]=0xc3
        pe=bytearray(1024);pe[:2]=b'MZ';struct.pack_into('<I',pe,0x3c,0x80);pe[0x80:0x84]=b'PE\0\0'
        struct.pack_into('<HHIIIHH',pe,0x84,0x8664,1,0,0,0,240,0x22)
        optional=0x98;struct.pack_into('<H',pe,optional,0x20b)
        struct.pack_into('<I',pe,optional+4,0x200);struct.pack_into('<II',pe,optional+16,0x1000,0x1000)
        struct.pack_into('<QII',pe,optional+24,0x140000000,0x1000,0x200)
        struct.pack_into('<HH',pe,optional+40,6,0);struct.pack_into('<II',pe,optional+56,0x2000,0x200)
        struct.pack_into('<HH',pe,optional+68,3,0x8160)
        struct.pack_into('<QQQQ',pe,optional+72,0x100000,0x1000,0x100000,0x1000);struct.pack_into('<I',pe,optional+108,16)
        section=optional+240;pe[section:section+8]=b'.text\0\0\0'
        struct.pack_into('<IIIIIIHHI',pe,section+8,1,0x1000,0x200,0x200,0,0,0,0,0x60000020);pe[0x200]=0xc3
        for kind,data in [('elf',elf),('pe',pe)]:
            fixture=source('owned-'+kind,bytes(data));foreign,_=inspect(kind,'native',fixture)
            fields=foreign['evidence']['result']['binary']
            check(kind+' header facts match independently authored container',fields['format']==kind and fields['bits']==64
                  and fields['little_endian'] is True and fields['arch_name']=='x86_64')
        expected=digest(wasm.read_bytes())
        refuse('missing explicit consent',['inspect','wasm','--no-consent',expected,wasm,root/'no-consent.json'],root/'no-consent.json')
        refuse('wrong input hash',['inspect','wasm','--owned-or-authorized','0'*64,wasm,root/'wrong-hash.json'],root/'wrong-hash.json')
        refuse('uppercase hash',['inspect','wasm','--owned-or-authorized',expected.upper(),wasm,root/'upper.json'],root/'upper.json')
        refuse('unknown operation',['execute','wasm','--owned-or-authorized',expected,wasm,root/'execute.json'],root/'execute.json')
        refuse('unknown format',['inspect','device','--owned-or-authorized',expected,wasm,root/'device.json'],root/'device.json')
        original_output=output.read_bytes()
        refuse('output overwrite',['inspect','wasm','--owned-or-authorized',expected,wasm,output])
        check('existing output remains exact',output.read_bytes()==original_output)
        linked=root/'linked-input';linked.symlink_to(wasm)
        refuse('input symlink',['inspect','wasm','--owned-or-authorized',expected,linked,root/'symlink.json'],root/'symlink.json')
        linked_output=root/'linked-output';linked_output.symlink_to(output)
        refuse('output symlink',['inspect','wasm','--owned-or-authorized',expected,wasm,linked_output])
        check('output symlink target remains exact',output.read_bytes()==original_output)
        fifo=root/'fifo';os.mkfifo(fifo)
        refuse('FIFO without blocking',['inspect','wasm','--owned-or-authorized',expected,fifo,root/'fifo.json'],root/'fifo.json')
        refuse('directory input',['inspect','wasm','--owned-or-authorized',expected,root,root/'dir.json'],root/'dir.json')
        for name,kind,data in [('empty','wasm',b''),('invalid-native','native',b'not a native file'),('invalid-utf8','javascript',b'\xff'),
                               ('nul-javascript','javascript',b'\0'),('large-javascript','javascript',b' '*(2*1024*1024+1)),
                               ('large-input','wasm',b'\0'*(16*1024*1024+1))]:
            path=source(name+'.input',data);target=root/(name+'-refused.json')
            refuse(name,['inspect',kind,'--owned-or-authorized',digest(data),path,target],target)
        record={'passed':True,'checks':checks,'refusals':refusals,'native_calls':len(calls),'calls':calls,
                'source_lock_sha256':receipt['source_lock_sha256'],'binary_sha256':digest(executable.read_bytes()),
                'network_denied':bool(policy),'input_executed':False,'public_runtime_qualified':False,'installed_qualified':False,
                'linux_qualified':sys.platform=='linux','all_processes_terminal':True,'remote_actions':False}
        (root/'evidence.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps({'passed':True,'checks':len(checks),'refusals':len(refusals),'native_calls':len(calls)}))
    except Exception as error:
        (root/'failure.json').write_text(json.dumps({'error':str(error),'checks':checks,'refusals':refusals,'calls':calls},indent=2)+'\n')
        raise


if __name__=='__main__':main()
