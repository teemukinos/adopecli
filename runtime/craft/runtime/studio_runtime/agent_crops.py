"""Lossless, bounded inspection crops from immutable published image bytes."""
import hashlib
import io
from PIL import Image
from .store import Conflict


MAX_PIXELS = 16_777_216
CONTRACT = {'version': 2, 'maximum_previews': 8,
            'crop_coordinates': 'integer [left, top, width, height] in original image pixels',
            'crop_scope': 'published PNG/JPEG exports; no resize, enhancement or new render',
            'maximum_source_pixels': MAX_PIXELS}


def dimensions(raw):
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in ('PNG', 'JPEG') or source.width * source.height > MAX_PIXELS:
            raise ValueError('Inspection requires a PNG/JPEG with at most 16777216 pixels')
        return list(source.size)


def pin(revision, requested_revision, regions, entries):
    """Resolve exact published paths once, then persist their immutable hashes."""
    if requested_revision != revision:
        raise Conflict('Crop selection belongs to another revision')
    if not isinstance(regions, list) or not 1 <= len(regions) <= 8:
        raise ValueError('Inspect crops must contain one to eight regions')
    available = {e['path']: e for e in entries}
    pinned = []; seen = set()
    for region in regions:
        if not isinstance(region, dict) or set(region) != {'path', 'box'}:
            raise ValueError('Each crop requires exactly path and box')
        path = region['path']; box = region['box']
        if not isinstance(path, str) or path not in available:
            raise ValueError('Crop must reference an exact published image path')
        if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box)
                or min(box[:2]) < 0 or min(box[2:]) < 1):
            raise ValueError('Crop box must be integer [left, top, width, height] with positive extent')
        key = (path, *box)
        if key in seen: raise ValueError('Duplicate crop region')
        seen.add(key)
        pinned.append({'path': path, 'box': box.copy(), 'sha256': available[path]['sha256']})
    return {'revision': revision, 'regions': pinned}


def render(raw, region, revision):
    if hashlib.sha256(raw).hexdigest() != region['sha256']:
        raise Conflict('Crop source hash differs')
    size = dimensions(raw)
    left, top, width, height = region['box']
    if left + width > size[0] or top + height > size[1]:
        raise ValueError('Crop box exceeds original image bounds')
    with Image.open(io.BytesIO(raw)) as source:
        source.load()  # Fail closed for truncated images before deriving evidence.
        cropped = source.crop((left, top, left + width, top + height))
        output = io.BytesIO()
        cropped.save(output, format='PNG')
    data = output.getvalue()
    provenance = {'revision': revision, 'source_path': region['path'],
                  'source_sha256': region['sha256'], 'source_dimensions': size,
                  'box': region['box'], 'dimensions': [width, height],
                  'sha256': hashlib.sha256(data).hexdigest(), 'resampled': False}
    return data, provenance
