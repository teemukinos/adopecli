"""Full bounded image-resource checks; native decoding must independently agree."""
import hashlib
import io
import math

from .texture_structure import require
from .texture_image_codecs import dimensions, exr, hdr

MAX_IMAGE_BYTES = 64 << 20
MAX_TOTAL_TEXELS = 33_554_432
FORMATS = ('PNG', 'JPEG', 'TGA', 'TIFF', 'BMP', 'WEBP')


def inspect_bytes(data):
    require(isinstance(data, bytes) and 1 <= len(data) <= MAX_IMAGE_BYTES, 'image byte size exceeds its budget')
    if data.startswith(b'#?'):
        report = hdr(data)
    elif data.startswith(b'\x76\x2f\x31\x01'):
        report = exr(data)
    else:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(data)) as image:
                require(image.format in FORMATS, 'image format is not qualified')
                dimensions(image.width, image.height)
                require(getattr(image, 'n_frames', 1) == 1, 'animated or multipage image resources are not qualified')
                report = {'format': image.format, 'width': image.width, 'height': image.height,
                          'sample_type': image.mode, 'linear': image.mode == 'F'}
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.mode == 'F':
                    require(all(math.isfinite(value) for value in image.get_flattened_data()), 'image contains NaN or infinity')
        except (OSError, SyntaxError, Image.DecompressionBombError) as error:
            raise ValueError('Texture image resource cannot be decoded') from error
    return {**report, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'decoded_rgba_bytes': report['width'] * report['height'] * 16}


def inspect_resources(members, structure):
    images = {}; packages = {}; total = 0
    for key, data in members.items():
        if not key.startswith('resources/'):
            continue
        name = key[len('resources/'):]
        require(1 <= len(name) <= 120 and not name.startswith('.') and all(c.isascii() and (c.isalnum() or c in '_.-') for c in name),
                'resource name would be changed by the native writer')
        if name.endswith('.mcraft'):
            # The native reader treats this exact suffix as opaque. Do not
            # decompress it or mistake it for an image. Cooking remains blocked.
            require(isinstance(data, bytes) and 0 < len(data) <= MAX_IMAGE_BYTES, 'linked package exceeds its byte budget')
            packages[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'opaque': True, 'cook_authorized': False}
        else:
            report = inspect_bytes(data)
            total += report['width'] * report['height']
            require(total <= MAX_TOTAL_TEXELS, 'aggregate image texels exceed their budget')
            images[name] = report
    for name in structure['image_references']:
        require(name in images, 'image reference has no matching decoded embedded image')
    for name in structure['linked_packages']:
        require(name in packages, 'linked material has no matching opaque embedded package')
    return {'images': images, 'packages': packages, 'texels': total, 'decoded_rgba_bytes': total * 16}


def check_native_resources(preflight, resources):
    """Require a private resource.list reply to agree with admitted source bytes.

    Native sync_images logs decoder failures rather than failing project open.
    A successful open/save therefore cannot replace this explicit decoder check.
    This check does not replace native field and embedded-byte preservation.
    """
    require(type(resources) is list and len(resources) == len(preflight['images']) + len(preflight['packages']),
            'native resource count disagrees with the admitted document')
    seen = set()
    for resource in resources:
        require(type(resource) is dict and type(resource.get('name')) is str, 'native resource response is malformed')
        name = resource['name']
        require(name not in seen, 'native resource response has duplicate names')
        seen.add(name)
        expected = preflight['images'].get(name) or preflight['packages'].get(name)
        require(expected is not None, 'native resource response contains an unexpected name')
        for key in ('bytes', 'width', 'height'):
            require(type(resource.get(key)) is int and resource[key] == expected.get(key, 0),
                    'native resource decoder disagrees with admitted image dimensions or byte size')
    return {'images': len(preflight['images']), 'opaque_packages': len(preflight['packages'])}
