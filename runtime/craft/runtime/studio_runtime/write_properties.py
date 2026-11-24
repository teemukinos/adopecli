"""Typed Write formatting values, with explicit budgets and deferred payloads.

These checks do not resolve inherited layout, decode media/fonts, or authorize
native execution. They preserve native values, including false, zero and null.
"""
from collections import Counter

from .write_container import require
from .write_opc import external_hyperlink
from .write_structure import number, record, sequence, text, uint


def boolean(value):
    require(type(value) is bool, 'formatting boolean has the wrong type')


def enum(names):
    choices = frozenset(names.split())
    def check(value):
        require(type(value) is str and value in choices, 'formatting enum value is unknown')
    return check


def scalar(low, high):
    return lambda value: number(value, low, high, 'formatting dimension')


def integer(low, high):
    def check(value):
        uint(value, high, 'formatting integer')
        require(value >= low, 'formatting integer is below its minimum')
    return check


def optional(check):
    return lambda value: None if value is None else check(value)


def vector(check, length):
    def validate(value):
        for item in sequence(value, length, 'formatting vector', length): check(item)
    return validate


def fields(value, schema, label):
    record(value, set(), set(schema), label)
    for name, item in value.items(): schema[name](item)


def words(names, check):
    return dict.fromkeys(names.split(), check)


ALIGN = enum('left center right justify distribute')
RGB = vector(integer(0, 255), 3)
POINTS = scalar(0, 1584)
OFFSET = scalar(-1584, 1584)
IDENTITY = lambda value: text(value, 'formatting identity', 512)
DESCRIPTION = lambda value: text(value, 'formatting text', 8192)
BORDER_STYLE = enum('none single double dotted dashed thick triple dotDash wave thinThickSmallGap '
                    'thickThinSmallGap thinThickThinSmallGap thinThickMediumGap thickThinMediumGap '
                    'thinThickThinMediumGap thinThickLargeGap thickThinLargeGap thinThickThinLargeGap')


def border(value):
    fields(value, {'style': BORDER_STYLE, 'width': scalar(0, 12), 'color': optional(RGB), 'space': POINTS}, 'border')


def borders(value):
    # Borders is not camelCase in the pinned native serializer.
    fields(value, words('top left bottom right between inside_v', optional(border)), 'borders')


def color(value):
    if value == 'Auto': return
    record(value, {'Rgb'}, set(), 'text color'); RGB(value['Rgb'])


def line_spacing(value):
    record(value, {'rule', 'value'}, set(), 'line spacing')
    enum('multiple atLeast exactly')(value['rule'])
    low, high = {'multiple': (.06, 132), 'atLeast': (0, 1584), 'exactly': (.7, 1584)}[value['rule']]
    number(value['value'], low, high, 'line spacing')


def tabs(value):
    for item in sequence(value, 256, 'tab stops'):
        record(item, {'pos'}, {'align', 'leader'}, 'tab stop'); OFFSET(item['pos'])
        if 'align' in item: enum('left center right decimal bar clear')(item['align'])
        if 'leader' in item: enum('none dot hyphen underscore middleDot')(item['leader'])


def frame(value):
    fields(value, {'w': optional(POINTS), 'h': optional(POINTS), 'hExact': boolean,
                  'x': OFFSET, 'y': OFFSET, 'xAlign': optional(enum('left center right inside outside')),
                  'yAlign': optional(enum('top center bottom inside outside inline')),
                  'hAnchor': enum('text margin page'), 'vAnchor': enum('text margin page'),
                  'wrap': enum('around auto notBeside none tight through'), 'anchorLock': optional(boolean),
                  'hSpace': POINTS, 'vSpace': POINTS}, 'paragraph frame')


def table_float(value):
    anchor = enum('column margin page paragraph leftMargin rightMargin topMargin bottomMargin insideMargin outsideMargin character line')
    align = optional(enum('start center end inside outside'))
    fields(value, {'hRel': anchor, 'vRel': anchor, 'x': OFFSET, 'y': OFFSET,
                  'hAlign': align, 'vAlign': align, 'dist': vector(POINTS, 4), 'overlap': boolean}, 'floating table')


def format_revision(value):
    record(value, {'rev', 'old'}, set(), 'format revision'); uint(value['rev'], 2**32-1, 'revision identity')
    require(type(value['old']) is dict, 'old formatting must be an object')
    # The structural visitor checks revision ownership and recursively visits old.


def numbering(value):
    record(value, {'num', 'level'}, set(), 'numbering reference')
    uint(value['num'], 2**32-1, 'numbering identity'); uint(value['level'], 8, 'numbering level')


def numbering_revision(value):
    record(value, {'rev', 'original'}, set(), 'numbering revision')
    uint(value['rev'], 2**32-1, 'revision identity'); DESCRIPTION(value['original'])


class Validator:
    def __init__(self, media, pending):
        self.media = media; self.pending = pending
        self.counts = Counter(); self.fonts = set(); self.links = set(); self.pictures = set()
        self.schemas = {}

    def font(self, value):
        IDENTITY(value)
        require(value.strip() and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'font family is empty or has controls')
        self.fonts.add(value)

    def link(self, value):
        text(value, 'hyperlink', 2048)
        if value.startswith('#'):
            require(len(value) > 1 and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'bookmark hyperlink is invalid')
        else: external_hyperlink(value)
        self.links.add(value)

    def deferred(self, name):
        def check(value):
            require(type(value) is dict, name+' must be an object')
            self.pending.add(name)
        return check

    def picture(self, value):
        fields(value, {'media': IDENTITY, 'size': vector(scalar(.01, 2000), 2),
                       'repeat': enum('none tile stretch'), 'align': vector(scalar(0, 1), 2)}, 'cell picture')
        require(type(value.get('media')) is str and value['media'] in self.media, 'cell picture references missing media')
        require('size' in value, 'cell picture must declare its native dimensions')
        self.pictures.add(value['media'])
        self.pending.add('cell-picture-tiling-budget')

    def check(self, value, kind):
        self.counts[kind] += 1
        require(sum(self.counts.values()) <= 500_000, 'aggregate formatting budget exceeded')
        if kind == 'paragraph' and any(value.get(k) is not None for k in ('indentLeftChars', 'indentRightChars', 'indentFirstChars')):
            self.pending.add('resolved-character-indent-budget')
        if kind in self.schemas:
            fields(value, self.schemas[kind], kind+' properties')
            return
        common = {'fmtChange': optional(format_revision)}
        if kind == 'character':
            schema = {**words('style lang langBidi langEa', IDENTITY),
                      **words('font symFont fontCs fontEa', self.font),
                      **words('size sizeCs', scalar(1, 1638)),
                      **words('bold italic strike doubleStrike caps smallCaps hidden webHidden snapToGrid outline shadow emboss engrave noProof rtl cs boldCs italicCs', boolean),
                      **words('underlineColor shading', RGB),
                      'underline': enum('none single words double thick dotted dash dotDash dotDotDash wave doubleWave'),
                      'color': color, 'highlight': enum('none yellow brightGreen turquoise pink blue red darkBlue teal green violet darkRed darkYellow gray50 gray25 black white'),
                      'border': border, 'vertAlign': enum('baseline superscript subscript'), 'spacing': scalar(-100, 100),
                      'scale': scalar(1, 600), 'position': scalar(-800, 800), 'kern': scalar(0, 1638),
                      'emphasis': enum('none dot comma circle underDot'),
                      'ligatures': lambda v: fields(v, words('standard contextual historical discretional', boolean), 'ligatures'),
                      'eastAsianLayout': self.deferred('east-asian-layout'), 'textEffects': self.deferred('text-effects'),
                      'link': self.link, **words('ins del', integer(0, 2**32-1))}
            schema = {k: optional(v) for k, v in schema.items()} | common
        elif kind == 'paragraph':
            schema = {'style': IDENTITY, 'align': ALIGN,
                      **words('indentLeft indentRight indentFirst indentLeftChars indentRightChars indentFirstChars', OFFSET),
                      **words('spaceBefore spaceAfter dropCapDistance', POINTS),
                      **words('spaceBeforeAuto spaceAfterAuto contextualSpacing mirrorIndents adjustRightIndent keepNext keepLines pageBreakBefore widowControl suppressHyphens suppressLineNumbers bidi dropCapMargin kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN snapToGrid', boolean),
                      'lineSpacing': line_spacing, 'outlineLevel': integer(0, 9), 'numbering': numbering,
                      'tabs': tabs, 'shading': RGB, 'borders': borders,
                      'textDirection': enum('lrTb lrTbV tb tbRl tbRlV tbLr tbLrV btLr tbV rl rlV lr lrV'),
                      'dropCap': integer(0, 10), 'dropCapFont': self.font, 'frame': frame,
                      'numChange': numbering_revision, 'textAlignment': enum('auto top center baseline bottom')}
            schema = {k: optional(v) for k, v in schema.items()} | common
        elif kind == 'table':
            schema = {'style': optional(IDENTITY), 'width': optional(POINTS), 'widthPct': optional(scalar(0, 1000)),
                      'align': optional(ALIGN), 'indent': optional(OFFSET), 'borders': optional(borders),
                      'cellMargins': optional(vector(POINTS, 4)), 'fixed': boolean,
                      'look': lambda v: fields(v, words('headerRow totalRow bandedRows firstColumn lastColumn bandedColumns', boolean), 'table look'),
                      'shading': optional(RGB), 'caption': optional(DESCRIPTION), 'description': optional(DESCRIPTION),
                      'float': optional(table_float), 'bidiVisual': boolean,
                      'spaceBefore': optional(POINTS), 'spaceAfter': optional(POINTS), **common}
        elif kind == 'row':
            schema = {'height': optional(POINTS), 'heightRule': enum('auto atLeast exact'), 'header': boolean,
                      'cantSplit': boolean, 'exceptions': optional(lambda v: require(type(v) is dict, 'row exceptions must be properties')),
                      **words('gridBefore gridAfter', integer(0, 63)), **words('wBefore wAfter', optional(POINTS)), **common}
        elif kind == 'cell':
            schema = {'width': optional(POINTS), 'widthPct': optional(scalar(0, 1000)), 'span': integer(1, 63),
                      'vmerge': enum('none restart continue'), 'shading': optional(RGB), 'borders': optional(borders),
                      'valign': optional(enum('top center bottom')), 'margins': optional(vector(POINTS, 4)),
                      'partialMargins': optional(vector(optional(POINTS), 4)), 'textDirection': enum('horizontal down up'),
                      **words('textDirectionSet noWrap hideMark', boolean), 'picture': optional(self.picture), **common}
        else: raise ValueError('Write formatting kind is unknown')
        self.schemas[kind] = schema
        fields(value, schema, kind+' properties')

    def table_style(self, value, props):
        schema = {'borders': optional(borders), 'fill': optional(RGB), 'cellMargins': optional(vector(POINTS, 4)),
                  **words('bandSize colBandSize', optional(integer(1, 8192))), 'totalBorderTop': optional(border)}
        for region in ('header', 'band', 'firstCol', 'lastCol', 'total', 'colBand'):
            schema[region+'Fill'] = optional(RGB); schema[region+'Borders'] = optional(borders)
            schema[region+'Chr'] = lambda v: props(v, 'character')
        def regions(value):
            record(value, set(), set('wholeTable firstRow lastRow firstCol lastCol band1Vert band2Vert band1Horz band2Horz neCell nwCell seCell swCell'.split()), 'conditional table regions')
            for part in value.values():
                fields(part, {'chr': lambda v: props(v, 'character'), 'fill': optional(RGB), 'borders': optional(borders),
                              'align': optional(ALIGN), 'vAlign': optional(enum('top center bottom'))}, 'conditional table formatting')
        schema['regions'] = regions
        fields(value, schema, 'table style')

    def finish(self, bookmarks):
        for link in self.links:
            if link.startswith('#'): require(link[1:] in bookmarks, 'hyperlink references a missing bookmark')
        return {'counts': dict(self.counts), 'font_requests': sorted(self.fonts), 'hyperlinks': sorted(self.links),
                'cell_picture_media': sorted(self.pictures), 'engine_admission_complete': False}
