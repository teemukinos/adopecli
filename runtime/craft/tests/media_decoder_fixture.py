"""Synthetic ELF-shaped receipts for static checks, never executed as Linux code."""
import json
from studio_runtime import media_decoders

BASE = 'example/native@sha256:'+'1'*64


def tool_bytes(configuration=None, license_text=media_decoders.LICENSE_TEXT):
    header = bytearray(64)
    header[:7] = b'\x7fELF\x02\x01\x01'
    header[18:20] = (62).to_bytes(2, 'little')
    configuration = media_decoders.embedded_configuration() if configuration is None else configuration
    return bytes(header)+b'static test only; not executable code\0'+configuration.encode()+b'\0'+license_text+b'\0'


def create(root):
    (root/'bin').mkdir(parents=True)
    (root/'notices').mkdir()
    for name in media_decoders.TOOLS:
        path = root/'bin'/name
        path.write_bytes(tool_bytes())
        path.chmod(0o755)
    for notice in media_decoders.NOTICES:
        (root/notice).write_text('Synthetic test notice, not an upstream license.\n')
    value = {'schema_version': media_decoders.SCHEMA, 'product': media_decoders.PRODUCT,
             'profile': media_decoders.PROFILE, 'platform': 'linux-amd64', 'base_image': BASE,
             'source': {'name': 'ffmpeg', 'version': '7.1.5', 'origin': 'upstream-release',
                        'archive_name': 'ffmpeg-7.1.5.tar.xz', 'archive_sha256': '0'*64, 'archive_bytes': 1},
             'build': {'license': media_decoders.LICENSE, 'configuration': list(media_decoders.CONFIGURATION),
                       'compiler': 'cc (fixture) 1.0'},
             'tools': {name: {'path': 'bin/'+name, 'version': name+' version fixture'}
                       for name in media_decoders.TOOLS},
             'files': media_decoders.inventory(root)}
    (root/'decoder.json').write_text(json.dumps(value)+'\n')
    return value
