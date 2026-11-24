"""Pinned MaterialCraft v0.4.1 intrinsic connector contract (MIT upstream).

Source: crates/nodes/src/function/catalog.rs at
65f7bfd3e5f40d695d03162285879f0f8079ff6c. No converted function bodies.

MIT License

Copyright (c) 2026 ArtCraft Team and the MaterialCraft contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
SOURCE_SHA256 = 'ff490fcaeb6c4fa599df1bef429c2f976f32d4f73364ff59a602da228333f25c'
INPUTS = {
    'const_float1': (),
    'const_float2': (),
    'const_float3': (),
    'const_float4': (),
    'const_int1': (),
    'const_int2': (),
    'const_int3': (),
    'const_int4': (),
    'const_bool': (),
    'const_string': (),
    'vector2': ('componentsin', 'componentslast'),
    'vector3': ('componentsin', 'componentslast'),
    'vector4': ('componentsin', 'componentslast'),
    'swizzle1': ('vector',),
    'swizzle2': ('vector',),
    'swizzle3': ('vector',),
    'swizzle4': ('vector',),
    'ivector2': ('componentsin', 'componentslast'),
    'ivector3': ('componentsin', 'componentslast'),
    'ivector4': ('componentsin', 'componentslast'),
    'iswizzle1': ('vector',),
    'iswizzle2': ('vector',),
    'iswizzle3': ('vector',),
    'iswizzle4': ('vector',),
    'set': ('value',),
    'get_float1': (),
    'get_float2': (),
    'get_float3': (),
    'get_float4': (),
    'get_integer1': (),
    'get_integer2': (),
    'get_integer3': (),
    'get_integer4': (),
    'get_bool': (),
    'get_string': (),
    'isdefined': (),
    'samplelum': ('pos',),
    'samplecol': ('pos',),
    'tofloat': ('value',),
    'tofloat2': ('value',),
    'tofloat3': ('value',),
    'tofloat4': ('value',),
    'toint1': ('value',),
    'toint2': ('value',),
    'toint3': ('value',),
    'toint4': ('value',),
    'add': ('a', 'b'),
    'sub': ('a', 'b'),
    'mul': ('a', 'b'),
    'mulscalar': ('a', 'scalar'),
    'div': ('a', 'b'),
    'neg': ('a',),
    'mod': ('a', 'b'),
    'dot': ('a', 'b'),
    'and': ('a', 'b'),
    'or': ('a', 'b'),
    'not': ('a',),
    'eq': ('a', 'b'),
    'noteq': ('a', 'b'),
    'gt': ('a', 'b'),
    'gteq': ('a', 'b'),
    'lr': ('a', 'b'),
    'lreq': ('a', 'b'),
    'abs': ('a',),
    'floor': ('a',),
    'ceil': ('a',),
    'cos': ('a',),
    'sin': ('a',),
    'tan': ('a',),
    'atan2': ('a',),
    'cartesian': ('rho', 'theta'),
    'sqrt': ('a',),
    'log': ('a',),
    'exp': ('a',),
    'log2': ('a',),
    'pow2': ('a',),
    'pow': ('a', 'b'),
    'lerp': ('a', 'b', 'x'),
    'min': ('a', 'b'),
    'max': ('a', 'b'),
    'rand': ('a',),
    'sequence': ('seqin', 'seqlast'),
    'ifelse': ('condition', 'ifpath', 'elsepath'),
    'while': ('init', 'cond', 'loop'),
    'passthrough': ('input',),
}
