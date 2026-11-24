"""Predict numeric PPTX conversion changes without changing the native source.

The maintained writer quantizes coordinates, text sizes and percentages and clamps
some paragraph values. The native reader can clamp those values again. This
report separates exported values from cold native reopen values before conversion. It is
not a complete semantic projection, a native-load permission or a fidelity claim.
"""
import math

from . import slides_admission as admission, slides_source as source, slides_binding as binding
from .slides_source import require

PROFILE = 'simple-slides-pptx-numeric-v1'


def round_away(value):
    """Match finite binary64 conversion with ties away from zero, not bankers' rounding."""
    whole = math.floor(abs(value))
    return math.copysign(whole + (abs(value)-whole >= 0.5), value)


def inspect(data):
    admitted = admission.inspect(data); model = source.strict_json(data); changes = []; checked = 0

    def number(path, value, factor, unit, *, low=None, high=None, encoded_high=None, floor=False, denominator=1, reader_high=None):
        nonlocal checked
        checked += 1
        bounded = max(low, value) if low is not None else value
        bounded = min(high, bounded) if high is not None else bounded
        scaled = bounded*factor/denominator
        encoded = int((bounded*factor)//denominator) if floor else int(round_away(scaled))
        if encoded_high is not None: encoded = min(encoded_high, encoded)
        decoded = encoded*denominator/factor
        reopened = min(reader_high, decoded) if reader_high is not None else decoded
        if decoded != value or reopened != value:
            changes.append({'path': path, 'source_value': value, 'converted_value': decoded,
                            'native_reopen_value': reopened, 'native_reader_clamped': reopened != decoded,
                            'encoded_integer': encoded, 'units_per_source_unit': factor/denominator, 'source_unit': unit,
                            'absolute_change': abs(decoded-value), 'clamped': bounded != value or encoded_high is not None and round_away(scaled) > encoded_high,
                            'rounding': 'floor' if floor else 'nearest-ties-away-from-zero'})

    def scalar_fields(owner, path, keys, factor, unit, **kwargs):
        for key in keys:
            value = owner.get(key)
            if value is not None: number(path+'/'+key, value, factor, unit, **kwargs)

    def color(value, path):
        if value is not None:
            number(path+'/base/rgb/a', value['base']['rgb']['a'], 100000, 'alpha-byte', floor=True, denominator=255)

    def fill(value, path):
        if value is not None and value['kind'] == 'solid': color(value['color'], path+'/color')

    def run_props(value, path):
        scalar_fields(value, path, ('size', 'kern', 'spacing'), 100, 'point')
        scalar_fields(value, path, ('baseline',), 100000, 'fraction')
        fill(value.get('fill'), path+'/fill')
        for key in ('highlight', 'underlineColor'): color(value.get(key), path+'/'+key)

    def text(body, path):
        props = body['body']; prefix = path+'/body'
        scalar_fields(props, prefix, ('insetL', 'insetR', 'insetT', 'insetB', 'colSpacing'), 12700, 'point')
        scalar_fields(props, prefix, ('rot',), 60000, 'degree')
        for i, paragraph in enumerate(body['paragraphs']):
            prefix = path+'/paragraphs/'+str(i)
            props = paragraph.get('props', {})
            scalar_fields(props, prefix+'/props', ('marginLeft', 'marginRight'), 12700, 'point', low=0)
            scalar_fields(props, prefix+'/props', ('indent', 'defaultTab'), 12700, 'point')
            for key in ('lineSpacing', 'spaceBefore', 'spaceAfter'):
                item = props.get(key)
                if item is not None:
                    percent = item['kind'] == 'pct'
                    number(prefix+'/props/'+key+'/v', item['v'], 100000 if percent else 100,
                           'fraction' if percent else 'point', high=132 if percent else 1584, reader_high=132 if percent else None)
            for key in ('defProps', 'endProps'):
                if key in paragraph: run_props(paragraph[key], prefix+'/'+key)
            for j, run in enumerate(paragraph['runs']):
                if 'props' in run: run_props(run['props'], prefix+'/runs/'+str(j)+'/props')

    for key in ('slideSize', 'notesSize'): scalar_fields(model[key], '/'+key, ('width', 'height'), 12700, 'point')
    for i, slide in enumerate(model['slides']):
        path = '/slides/'+str(i); text(slide['notes'], path+'/notes')
        if slide['background'] is not None: fill(slide['background']['fill'], path+'/background/fill')
        for j, shape in enumerate(slide['shapes']):
            prefix = path+'/shapes/'+str(j)
            if shape['xfrm'] is not None:
                scalar_fields(shape['xfrm'], prefix+'/xfrm', ('x', 'y', 'w', 'h'), 12700, 'point')
                scalar_fields(shape['xfrm'], prefix+'/xfrm', ('rot',), 60000, 'degree', encoded_high=21599999)
            fill(shape['fill'], prefix+'/fill')
            if shape['text'] is not None: text(shape['text'], prefix+'/text')
    require(source.sha(data) == admitted['source_sha256'], 'precision report source changed during inspection')
    return {'schema_version': 1, 'profile': PROFILE, 'source_model_sha256': source.sha(data), 'source_lock_sha256': binding.LOCK_SHA256,
            'admission_profile': admitted['profile'], 'checked_numeric_values': checked,
            'changes': changes, 'change_count': len(changes), 'clamp_count': sum(item['clamped'] for item in changes),
            'native_reader_clamp_count': sum(item['native_reader_clamped'] for item in changes),
            'export_change_count': sum(item['source_value'] != item['converted_value'] for item in changes),
            'native_reopen_change_count': sum(item['source_value'] != item['native_reopen_value'] for item in changes),
            'source_changed': False, 'conversion_performed': False, 'numeric_changes_predicted': True,
            'complete_semantic_projection': False, 'source_format_fidelity_qualified': False,
            'pending_qualification': ['complete-pptx-semantic-projection', 'independent-xml-field-comparison',
                                     'native-reopen-comparison', 'converted-text-layout', 'rendered-fidelity']}
