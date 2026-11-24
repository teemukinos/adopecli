"""Owned Slides raster images and independent native decoder comparison.

Resources remain embedded original bytes. Names are labels, never paths to open.
This profile admits still PNG/JPEG pictures with explicit placement and crop.
Color-managed, oriented and high-bit-depth inputs need separate qualification.
"""
import copy
import math
from pathlib import Path
import re

from . import slides_source as source, write_resources
from .slides_source import require

MAX_ITEMS = 128
MAX_BYTES = 16 << 20
MAX_PIXELS = 33_554_432
DEFAULT_ADJUST = {'brightness': 0.0, 'contrast': 0.0, 'saturation': None,
                  'grayscale': False, 'duotone': None, 'clearColor': None, 'sharpen': 0.0}


def decode(item, *, remaining_pixels=MAX_PIXELS):
    require(type(item) is dict and set(item) == {'id', 'name', 'contentType', 'link', 'dataHex'}, 'picture resource fields differ')
    source.identity(item['id'], 'picture resource')
    require(type(item['name']) is str and 0 < len(item['name'].encode()) <= 1024
            and not any(ord(c) < 32 or ord(c) == 127 for c in item['name']), 'picture name must be a bounded label')
    require(item['link'] is None, 'picture requires owned embedded bytes; external links are refused')
    require(item['contentType'] in ('image/png', 'image/jpeg'), 'picture requires PNG or JPEG content type')
    value = item['dataHex']
    require(type(value) is str and 0 < len(value) <= 2*MAX_BYTES and len(value) % 2 == 0
            and re.fullmatch('[0-9a-f]+', value) is not None, 'picture needs bounded canonical dataHex')
    data = bytes.fromhex(value)
    report, rgba = write_resources.decode_image(data, remaining_pixels=remaining_pixels)
    require(report['format'] == {'image/png': 'PNG', 'image/jpeg': 'JPEG'}[item['contentType']], 'picture MIME differs from decoded bytes')
    require(not report['pending_qualification'], 'picture color profile, orientation or sample depth needs separate qualification')
    return data, report, rgba


def inventory(document):
    require(type(document['media']) is list and len(document['media']) <= MAX_ITEMS, 'picture resource count exceeds budget')
    result = {}; pixels = 0; size = 0
    for item in document['media']:
        data, report, _ = decode(item, remaining_pixels=MAX_PIXELS-pixels)
        size += len(data); pixels += report['width']*report['height']
        require(size <= MAX_BYTES and item['id'] not in result, 'picture aggregate bytes or identity invalid')
        result[item['id']] = report
    return result


def fill(value, media):
    require(type(value) is dict and set(value) == {'media', 'crop', 'mode', 'alpha', 'adjust'}, 'picture fill fields differ')
    source.identity(value['media'], 'picture media')
    require(value['media'] in media, 'picture reference has no owned resource')
    crop = value['crop']
    require(type(crop) is list and len(crop) == 4 and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v < 1 for v in crop)
            and crop[0]+crop[2] < 1 and crop[1]+crop[3] < 1, 'picture crop must retain a positive source rectangle')
    mode=value['mode']
    require(type(mode) is dict and set(mode)=={'kind','fill_rect'} and mode['kind']=='stretch'
            and type(mode['fill_rect']) is list and len(mode['fill_rect'])==4
            and all(type(v) is float and v==0 for v in mode['fill_rect']), 'picture stretch mode needs explicit full destination')
    alpha = value['alpha']
    require(alpha is None or type(alpha) in (int, float) and math.isfinite(alpha) and 0 <= alpha <= 1, 'picture opacity exceeds bounds')
    require(type(value['adjust']) is dict and set(value['adjust']) == set(DEFAULT_ADJUST)
            and all(type(value['adjust'][k]) is type(v) and value['adjust'][k] == v for k, v in DEFAULT_ADJUST.items()),
            'picture corrections need separate qualification')


def supplied(value, identity):
    require(type(value) is dict and set(value) == {'name', 'contentType', 'dataHex'}, 'picture input fields differ')
    item = {**value, 'id': identity, 'link': None}
    decode(item)
    return item


def insert(document, slide, value):
    from . import slides_recipes as recipes, slides_revision as revision
    require(type(value) is dict and set(value) == {'image', 'transform'}, 'picture insertion fields differ')
    transform = revision.transform(value['transform'])
    require(transform is not None and transform['w'] > 0 and transform['h'] > 0, 'picture requires positive explicit placement')
    data = Path(__file__).with_name('slides_recipe_base.json').read_bytes()
    require(source.sha(data) == recipes.BASE_SHA256, 'picture native defaults differ from pinned template')
    shape = copy.deepcopy(source.strict_json(data)['slides'][0]['shapes'][0])
    media = supplied(value['image'], source.identity(document['nextId']+1, 'new media'))
    shape_id = source.identity(document['nextId']+2, 'new picture')
    shape.update(id=shape_id, name=media['name'], ph=None, text=None, textBox=False, xfrm=transform, fill=None,
                 kind={'type': 'picture', 'fill': {'media': media['id'], 'crop': [0.0]*4,
                       'mode': {'kind': 'stretch', 'fill_rect': [0.0]*4}, 'alpha': None, 'adjust': dict(DEFAULT_ADJUST)}})
    document['media'].append(media); slide['shapes'].append(shape); document['nextId'] = shape_id


def replace(document, shape, value):
    media = supplied(value, source.identity(document['nextId']+1, 'replacement media'))
    document['media'].append(media); document['nextId'] = media['id']
    shape['kind']['fill']['media'] = media['id']


def compare(packet, item):
    data, expected, independent = decode(item)
    require(type(packet) is bytes and 12 <= len(packet) <= (64 << 20)+65548 and packet[:8] == b'DOBESPI1', 'native picture packet invalid')
    size = int.from_bytes(packet[8:12], 'little')
    require(0 < size <= 65536 and 12+size <= len(packet), 'native picture header exceeds bounds')
    header = source.strict_json(packet[12:12+size]); rgba = packet[12+size:]
    require(type(header) is dict and set(header) == {'schemaVersion', 'width', 'height', 'sourceBytes', 'pixelFormat', 'pixelBytes'},
            'native picture header fields differ')
    for key, value in [('schemaVersion', 1), ('width', expected['width']), ('height', expected['height']),
                       ('sourceBytes', len(data)), ('pixelBytes', len(independent))]:
        require(type(header[key]) is int and header[key] == value, 'native picture differs from independent '+key)
    require(header['pixelFormat'] == 'RGBA8' and len(rgba) == len(independent), 'native picture payload size or encoding differs')
    require(rgba[3::4] == independent[3::4], 'native picture alpha differs')
    maximum = 0; total = 0
    for actual, wanted in zip(rgba, independent):
        delta = abs(actual-wanted); maximum = max(maximum, delta); total += delta
    mean = total / len(rgba)
    require((maximum <= 3 and mean <= .5) if expected['format'] == 'JPEG' else maximum == 0,
            'native picture pixels differ from independent decoder')
    return {'media': item['id'], 'source_sha256': source.sha(data), 'width': expected['width'], 'height': expected['height'],
            'rgba8_sha256': source.sha(rgba), 'max_channel_error': maximum, 'mean_channel_error': mean,
            'decoder_agreement': True, 'color_managed': False, 'source_bytes_preserved': True}
