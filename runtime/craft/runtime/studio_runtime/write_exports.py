"""Strict Write page delivery with owned font/picture evidence and full decoding.

Native observations establish actual selection, not independent shaping or
artistic approval. Editable originals remain authoritative and are never saved
through a lossy export conversion. The worker owns final publication.
"""
from collections import Counter
import json
import math
from pathlib import Path
import queue
import shutil
import struct
import time
import unicodedata

from . import pdf, write_binding, write_builtin_fonts, write_container as container
from . import write_engine, write_fonts, write_glyphs, write_project as project, write_resources as resources
from .write_container import require

MAX_TOTAL_PIXELS = 64_000_000
MAX_OUTPUT_BYTES = 128 << 20


def validate(params):
    require(type(params) is dict and params.get('format') in ('png', 'pdf'), 'export requires explicit png/pdf format')
    allowed = {'format', 'pages', 'scale', 'font_substitutions'} if params['format'] == 'png' else {'format', 'font_substitutions'}
    require(set(params) <= allowed, 'export has unsupported parameters')
    if 'pages' in params:
        pages = params['pages']
        require(type(pages) is list and 1 <= len(pages) <= 256 and all(type(p) is int and 1 <= p <= 256 for p in pages)
                and len(set(pages)) == len(pages), 'export pages must be ordered unique numbers from 1 to 256')
    scale = params.get('scale', 1)
    require(type(scale) in (int, float) and math.isfinite(scale) and .25 <= scale <= 4, 'export scale must be finite from 0.25 to 4 pixels per point')
    substitutions = params.get('font_substitutions', [])
    require(type(substitutions) is list and len(substitutions) <= 256, 'export font substitutions exceed budget')
    pairs = set()
    for item in substitutions:
        require(type(item) is dict and set(item) == {'requested', 'actual'} and all(type(value) is str and 0 < len(value) <= 256
                and not any(ord(c) < 32 or ord(c) == 127 for c in value) for value in item.values()), 'export font substitution fields are invalid')
        pair = (item['requested'], item['actual']); require(pair not in pairs, 'export font substitutions are duplicated'); pairs.add(pair)


def f32(value): return struct.unpack('<f', struct.pack('<f', value))[0]


def geometry(pages, selected, scale):
    result = []; total = 0
    for page in selected:
        require(page <= len(pages), 'export requests a missing page')
        width, height = [math.ceil(f32(f32(value)*f32(scale))) for value in pages[page-1]]
        pixels = width*height; total += pixels
        require(0 < width <= resources.MAX_SIDE and 0 < height <= resources.MAX_SIDE and pixels <= resources.MAX_PIXELS
                and total <= MAX_TOTAL_PIXELS, 'export exceeds its page or aggregate pixel budget')
        result.append((page, width, height))
    return result


def owned_fonts(packet, profile):
    require(type(packet) is bytes and 12 <= len(packet) <= 64 << 20 and packet[:8] == b'DOBEGLY1', 'export glyph packet is invalid')
    size = int.from_bytes(packet[8:12], 'little')
    require(0 < size <= 16 << 20 and 12+size <= len(packet), 'export glyph header exceeds budget')
    header = container.strict_json(packet[12:12+size]); raw = packet[12+size:]
    require(type(header) is dict and type(header.get('faces')) is list and len(header['faces']) <= 64, 'export font inventory exceeds budget')
    embedded = {item['decoded_sha256']: item['data'] for item in profile['retained']['embedded_fonts']}
    selected = []
    for face in header['faces']:
        require(type(face) is dict and type(face.get('offset')) is int and type(face.get('bytes')) is int
                and 0 <= face['offset'] < len(raw) and 0 < face['bytes'] <= 32 << 20
                and face['offset']+face['bytes'] <= len(raw), 'export font range is invalid')
        data = raw[face['offset']:face['offset']+face['bytes']]; digest = project.sha(data)
        builtin = write_builtin_fonts.FONTS.get(digest)
        require((builtin is not None and builtin['bytes'] == len(data)) or embedded.get(digest) == data,
                'export selected a font outside pinned builtins and owned embedded fonts')
        selected.append(data)
    return selected


def png(path, width, height):
    data = container.read_bytes(path); report, _ = resources.decode_image(data)
    require(report['format'] == 'PNG' and (report['width'], report['height']) == (width, height)
            and not report['pending_qualification'], 'export PNG disagrees with predicted geometry or color profile')
    return report


class PDFReader(pdf.Engine):
    """Use the maintained PDF reader with the Write attempt's shared deadline."""
    def __init__(self, root, executable, native):
        self.native = native
        super().__init__(root, executable=executable)

    def call(self, method, params):
        self.counter += 1; request = self.counter
        require(not self.native.cancelled() and time.monotonic() < self.native.deadline, 'PDF validation cancelled or timed out')
        self.send({'jsonrpc': '2.0', 'id': request, 'method': method, 'params': params})
        while True:
            require(not self.native.cancelled() and time.monotonic() < self.native.deadline, 'PDF validation cancelled or timed out')
            try: response = self.messages.get(timeout=min(.05, max(.001, self.native.deadline-time.monotonic())))
            except queue.Empty: continue
            require(response is not None, 'PDF reader exited before responding')
            if response.get('id') == request:
                require('error' not in response, 'PDF reader refused: '+str(response.get('error', ''))[:500])
                return response['result']


def letters(text):
    return Counter(c for c in unicodedata.normalize('NFKC', text) if not c.isspace())


def deliver(native, source, expected, destination, params):
    validate(params)
    source = write_engine.owned(native.root, source); destination = write_engine.owned(native.root, destination)
    require(not destination.exists(), 'export needs a new disposable destination')
    require(container.read_bytes(source) == expected, 'export source differs from complete predicted model')
    profile = project.native_profile(expected); destination.mkdir(mode=0o700)
    calls_before = native.calls; independent = []; picture_reports = []
    probes = destination/'probes'; probes.mkdir()
    try:
        for index, (name, item) in enumerate(resources.decode_store(profile['document'].get('media', {}), 'media').items()):
            require(not profile['resources']['images'][name]['pending_qualification'], 'export picture color/orientation/depth needs separate qualification')
            path = probes/f'picture-{index}.input'; path.write_bytes(item['data'])
            report = resources.compare_picture(native._run('picture', path, limit=64 << 20), item['data'])
            picture_reports.append({'name': name, **report})
        packet = native._run('glyphs', source, limit=64 << 20)
        fonts = owned_fonts(packet, profile); trace = write_glyphs.inspect(packet, fonts)
        pairs = lambda values: sorted((item['requested'], item['actual']) for item in values)
        require(pairs(trace['substitutions']) == pairs(params.get('font_substitutions', [])),
                'export font substitutions differ from explicit request: '+json.dumps(trace['substitutions'], ensure_ascii=True))
        require(write_builtin_fonts.SOURCE_REVISION == native.pin['source_revision'], 'font identity inventory differs from engine source')
        selected = params.get('pages', list(range(1, len(trace['pages'])+1)))
        scale = f32(params.get('scale', 1)); sizes = geometry(trace['pages'], selected, scale)
        total_bytes = 0; outputs = []
        if params['format'] == 'png':
            for page, width, height in sizes:
                path = destination/f'page-{page:03}.png'; cold = probes/f'cold-{page:03}.png'
                for target in (path, cold):
                    reply = container.strict_json(native._run('render', source, target, '--page', page, '--scale', scale, '--strict', limit=8192))
                    require(type(reply) is dict and set(reply) == {'path', 'width', 'height', 'bytes'} and reply['path'] == str(target)
                            and all(type(reply[k]) is int for k in ('width', 'height', 'bytes')), 'native PNG response fields differ')
                    report = png(target, width, height)
                    require((reply['width'], reply['height'], reply['bytes']) == (width, height, report['bytes']), 'native PNG response differs from decoded bytes')
                require(path.read_bytes() == cold.read_bytes(), 'cold native PNG export changed bytes')
                report = png(path, width, height); total_bytes += report['bytes']
                require(total_bytes <= MAX_OUTPUT_BYTES, 'export exceeds aggregate output byte budget')
                outputs.append({'file': path.name, 'page': page, **report, 'cold_bytes_equal': True})
        else:
            require(all(write_fonts.inspect(data)['embedding_bits'] & 0x302 == 0 for data in fonts),
                    'PDF font declares restricted, bitmap-only or no-subsetting embedding')
            trusted_pdf = write_binding.resolve_pdf()
            path = destination/'document.pdf'; native._run('convert', source, path, '--strict', limit=8192)
            pdf_bytes = container.read_bytes(path); require(len(pdf_bytes) <= 64 << 20, 'PDF exceeds independent reader byte budget')
            first_state = None; first_pixels = None
            for cold in range(2):
                digest, _, _ = write_engine.executable_digest(trusted_pdf['executable'])
                require(digest == trusted_pdf['expected_binary_sha256'], 'PDF reader changed after receipt verification')
                with PDFReader(native.root, trusted_pdf['executable'], native) as reader:
                    document, admitted = reader.open(path); state = pdf.snapshot(reader, document)
                    require(len(admitted['pages']) == len(trace['pages']), 'PDF page count differs from native layout')
                    require(len(state['text']) == len(trace['pages']), 'PDF text extraction page inventory differs')
                    pixels = []; text_checks = []
                    for page, width, height in sizes:
                        actual = admitted['pages'][page-1]; predicted = trace['pages'][page-1]
                        require(abs(actual['width']-predicted[0]) < .02 and abs(actual['height']-predicted[1]) < .02
                                and actual['rotation'] == 0, 'PDF page geometry differs from native layout')
                        expected_text = ''.join(run['text'] for run in trace['runs'] if run['page'] == page-1)
                        extracted = state['text'][page-1]['text']
                        require(letters(extracted) == letters(expected_text), 'PDF text inventory differs from actual native page glyph text')
                        text_checks.append({'page': page, 'normalized_character_inventory_equal': True})
                        preview = probes/f'pdf-{cold}-{page:03}.png'; reader.render(document, page, preview)
                        pixels.append(png(preview, width, height)['rgba8_sha256'])
                    if cold == 0: first_state = state; first_pixels = pixels
                    else: require(state == first_state and pixels == first_pixels, 'PDF cold reader changed complete state or rendered pixels')
                independent.append({'cold_pass': cold+1, 'pages': len(sizes), 'text_checks': text_checks, 'rgba8_sha256': pixels})
                digest, _, _ = write_engine.executable_digest(trusted_pdf['executable'])
                require(digest == trusted_pdf['expected_binary_sha256'], 'PDF reader changed during validation')
            require(container.read_bytes(path) == pdf_bytes, 'PDF reader changed exported bytes')
            outputs.append({'file': path.name, **project.record(pdf_bytes), 'pages': len(sizes), 'independent_cold_state_equal': True})
            total_bytes = len(pdf_bytes)
        native.observe(source, expected)
        pending = sorted(set(profile['pending_qualification']) | set(trace['pending_qualification']))
        pending = [item for item in pending if item not in ('native-picture-comparison', 'font-identity-and-glyphs', 'native-model-comparison')]
        if params['format'] == 'pdf': pending.append('pdf-reading-order')
        report = {'schema_version': 1, 'format': params['format'], 'source_model_sha256': project.sha(expected),
                  'native_calls': native.calls-calls_before, 'page_count': len(trace['pages']), 'selected_pages': selected,
                  'effective_scale': scale, 'outputs': outputs, 'output_bytes': total_bytes,
                  'actual_font_identity_verified': True, 'picture_decoder_agreement': True, 'strict_native_export': True,
                  'accepted_font_substitutions': trace['substitutions'],
                  'complete_output_decode': True, 'independent_pdf_checks': independent,
                  'pending_qualification': pending, 'source_format_fidelity_qualified': False, 'visual_approval': False}
        (destination/'glyphs.json').write_text(json.dumps(trace, sort_keys=True, allow_nan=False)+'\n')
        (destination/'pictures.json').write_text(json.dumps(picture_reports, sort_keys=True, allow_nan=False)+'\n')
        (destination/'delivery.json').write_text(json.dumps(report, sort_keys=True, allow_nan=False)+'\n')
        shutil.rmtree(probes)
        return report
    except BaseException:
        shutil.rmtree(destination)
        raise
