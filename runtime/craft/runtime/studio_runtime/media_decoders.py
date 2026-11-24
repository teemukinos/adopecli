"""Fixed media decoders for full-frame portable replay.

macOS retains its exact existing binary pins. Linux uses the worker's fixed
receipt and immutable base image, never a project path, PATH or environment
override. Receipt consistency does not establish provenance or Linux execution.

Linux packs are built from an upstream FFmpeg release with one fixed LGPL
configuration limited to the replay profile: MOV input, H.264 and AAC decoding,
raw frame hashes and float PCM output. Debian's GPL build (schema 1) is refused.
"""
from pathlib import Path
import platform
import re
import stat

from . import write_container, write_engine

PRODUCT = 'dobe-media-decoders'
PROFILE = 'h264-yuv420p-aac-48000-v1'
TOOLS = ('ffmpeg', 'ffprobe')
IMAGE = r'[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}'
SCHEMA = 2
LICENSE = 'LGPL-2.1-or-later'
LICENSE_TEXT = b'LGPL version 2.1 or later'
# Exact configure arguments. FFmpeg embeds this string in both programs, so the
# pack check can compare the receipt with the bytes it is about to trust.
CONFIGURATION = (
    '--disable-everything', '--disable-autodetect', '--disable-doc', '--disable-network',
    '--disable-avdevice', '--disable-postproc', '--disable-ffplay', '--disable-x86asm',
    '--enable-static', '--disable-shared', '--enable-ffmpeg', '--enable-ffprobe',
    '--enable-protocol=file,pipe', '--enable-demuxer=mov', '--enable-decoder=h264,aac',
    '--enable-parser=h264,aac', '--enable-encoder=rawvideo,pcm_f32le',
    '--enable-muxer=framemd5,pcm_f32le', '--enable-filter=aresample,scale')


def embedded_configuration():
    """The configuration string as FFmpeg's configure embeds it: comma lists are single-quoted."""
    return ' '.join("%s='%s'" % tuple(a.split('=', 1)) if ',' in a else a for a in CONFIGURATION)


REFUSED_CONFIGURATION = (b'--enable-gpl', b'--enable-nonfree', b'--enable-version3')
NOTICES = ('notices/LICENSE.md', 'notices/COPYING.LGPLv2.1')


def require(condition, message):
    if not condition:
        raise ValueError('media decoders: '+message)


def record(path):
    digest, size, _ = write_engine.executable_digest(path)
    return {'bytes': size, 'sha256': digest}


def metadata(path, maximum=1 << 20):
    require(path.stat().st_size <= maximum, 'metadata exceeds its bound')
    return write_container.strict_json(write_container.read_bytes(path))


def inventory(root):
    root = Path(root)
    require(not root.is_symlink() and root.is_dir(), 'regular pack directory required')
    result = {}
    total = 0
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        require(stat.S_ISREG(mode), 'pack links and special files are refused')
        require(len(result) < 128, 'pack inventory exceeds its bound')
        total += path.stat().st_size
        require(total <= 512 << 20, 'pack bytes exceed their bound')
        result[path.relative_to(root).as_posix()] = record(path)
    return result


def validate_executable(path):
    with path.open('rb') as stream:
        header = stream.read(64)
    require(len(header) == 64 and header[:7] == b'\x7fELF\x02\x01\x01'
            and int.from_bytes(header[18:20], 'little') == 62
            and path.stat().st_mode & stat.S_IXUSR, 'executable Linux x86-64 ELF required')


def validate_pack(root, base_image):
    """Validate bytes/architecture without executing either decoder."""
    require(type(base_image) is str and re.fullmatch(IMAGE, base_image), 'immutable base image required')
    root = Path(root)
    files = inventory(root)
    value = metadata(root/'decoder.json')
    require(type(value) is dict and value.get('schema_version') == SCHEMA,
            'only the LGPL source-built decoder pack is accepted')
    require(set(value) == {
        'schema_version', 'product', 'profile', 'platform', 'base_image', 'source', 'build', 'tools', 'files'},
        'unsupported pack fields')
    require(value['product'] == PRODUCT and value['profile'] == PROFILE
            and value['platform'] == 'linux-amd64' and value['base_image'] == base_image,
            'pack identity, profile or base image differs')
    source = value['source']
    require(type(source) is dict and set(source) == {
        'name', 'version', 'origin', 'archive_name', 'archive_sha256', 'archive_bytes'}, 'source identity required')
    require(source['name'] == 'ffmpeg' and source['origin'] == 'upstream-release'
            and type(source['version']) is str and re.fullmatch(r'[0-9]+\.[0-9]+(\.[0-9]+)?', source['version'])
            and source['archive_name'] == 'ffmpeg-%s.tar.xz' % source['version']
            and type(source['archive_sha256']) is str and re.fullmatch('[a-f0-9]{64}', source['archive_sha256'])
            and type(source['archive_bytes']) is int and 0 < source['archive_bytes'] <= 64 << 20,
            'invalid source identity')
    build = value['build']
    require(type(build) is dict and set(build) == {'license', 'configuration', 'compiler'}
            and build['license'] == LICENSE and build['configuration'] == list(CONFIGURATION)
            and type(build['compiler']) is str and 0 < len(build['compiler']) <= 256 and '\n' not in build['compiler'],
            'decoder build must use the fixed LGPL replay configuration')
    declared = value['files']
    require(type(declared) is dict and declared == {k: v for k, v in files.items() if k != 'decoder.json'},
            'pack inventory differs from its receipt')
    require(set(declared) == {'bin/ffmpeg', 'bin/ffprobe', *NOTICES},
            'the two decoders and the FFmpeg licence notices are required')
    tools = value['tools']
    require(type(tools) is dict and set(tools) == set(TOOLS), 'complete decoder tool map required')
    for name in TOOLS:
        tool = tools[name]
        require(type(tool) is dict and set(tool) == {'path', 'version'}
                and tool['path'] == 'bin/'+name and type(tool['version']) is str
                and 1 <= len(tool['version']) <= 2048 and '\n' not in tool['version']
                and tool['version'].startswith(name+' version '), 'invalid fixed decoder tool')
        path = root/tool['path']
        validate_executable(path)
        validate_build(path)
    return value, files


def validate_build(path):
    """Read the configuration and licence FFmpeg embeds; never execute the tool."""
    require(path.stat().st_size <= 128 << 20, 'decoder exceeds its bound')
    data = path.read_bytes()
    require(embedded_configuration().encode() in data and LICENSE_TEXT in data
            and not any(flag in data for flag in REFUSED_CONFIGURATION),
            'decoder bytes do not carry the fixed LGPL configuration')


def linux(resources):
    """Resolve only the distribution's fixed location; caller checks host."""
    resources = Path(resources)
    require(resources.name == 'dobe' and resources.parent.name == 'lib', 'bundled worker layout required')
    package = resources.parent.parent
    path = write_engine.owned(package, resources/'bundle.json')
    bundle = metadata(path, 16 << 20)
    require(type(bundle) is dict and type(bundle.get('schema_version')) is int and bundle['schema_version'] == 1
            and bundle.get('product') == 'dobe' and bundle.get('distribution') == 'dobe-worker'
            and bundle.get('platform') == 'linux-amd64', 'worker identity differs')
    require(type(bundle.get('files')) is dict and type(bundle.get('components')) is list,
            'worker receipt inventory required')
    components = [c for c in bundle['components'] if type(c) is dict and c.get('name') == PRODUCT]
    require(len(components) == 1, 'exactly one decoder component required')
    root = write_engine.owned(package, resources/'media-decoders')
    value, files = validate_pack(root, bundle.get('base_image'))
    require(components[0] == {'name': PRODUCT, 'version': PROFILE,
            'decoder_manifest_sha256': files['decoder.json']['sha256']}, 'decoder component differs from worker receipt')
    for name, expected in files.items():
        path = write_engine.owned(package, root/name)
        require(bundle['files'].get(path.relative_to(package).as_posix()) == expected,
                'decoder file differs from worker receipt')
    return {name: root/value['tools'][name]['path'] for name in TOOLS}


def resolve():
    host = platform.system(), platform.machine()
    if host == ('Darwin', 'arm64'):
        from . import construction_support
        return {name: Path(construction_support.binary(name)) for name in TOOLS}
    require(host == ('Linux', 'x86_64'), 'unsupported replay host')
    return linux(Path(__file__).resolve().parents[2])
