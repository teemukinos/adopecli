"""Write page setup, settings and metadata values; no external resolution."""
from .write_container import require
from .write_properties import (ALIGN, DESCRIPTION, IDENTITY, POINTS, RGB, boolean, borders,
                               enum, fields, format_revision, integer, optional, scalar, vector, words)
from .write_structure import number, record, sequence, text, uint

# Native serialized variants from the pinned document model. Accepting a variant
# here does not establish the native renderer's fidelity for its number labels.
NUMBER_FORMAT = enum('decimal upperRoman lowerRoman upperLetter lowerLetter ordinal cardinalText ordinalText '
                     'decimalZero bullet none hex chicago ideographDigital japaneseCounting aiueo iroha decimalFullWidth '
                     'decimalHalfWidth japaneseLegal japaneseDigitalTenThousand decimalEnclosedCircle decimalFullWidth2 '
                     'aiueoFullWidth irohaFullWidth ganada chosung decimalEnclosedFullstop decimalEnclosedParen '
                     'decimalEnclosedCircleChinese ideographEnclosedCircle ideographTraditional ideographZodiac '
                     'ideographZodiacTraditional taiwaneseCounting ideographLegalTraditional taiwaneseCountingThousand '
                     'taiwaneseDigital chineseCounting chineseLegalSimplified chineseCountingThousand koreanDigital '
                     'koreanCounting koreanLegal koreanDigital2 vietnameseCounting russianLower russianUpper numberInDash '
                     'hebrew1 hebrew2 arabicAlpha arabicAbjad hindiVowels hindiConsonants hindiNumbers hindiCounting '
                     'thaiLetters thaiNumbers thaiCounting bahtText dollarText')


def note(value):
    fields(value, {'pos': optional(enum('pageBottom beneathText sectEnd docEnd')), 'numFmt': optional(NUMBER_FORMAT),
                   'numStart': optional(integer(0, 2**32-1)), 'numRestart': optional(enum('continuous eachSect eachPage'))}, 'note settings')


def line_numbers(value):
    fields(value, {'countBy': integer(1, 100), 'start': integer(1, 32767), 'distance': POINTS,
                   'restart': enum('page section continuous')}, 'line numbers')


def document_grid(value):
    def char_space(value):
        require(type(value) is int and -1584*4096 <= value <= 1584*4096, 'document grid character spacing is out of range')
    fields(value, {'type': enum('default lines linesAndChars snapToChars'),
                   'linePitch': scalar(1, 1584), 'charSpace': char_space}, 'document grid')


def section(value, pending):
    # Geometry and owned story references are checked by the structural visitor,
    # including old section properties. They are not repeated or normalized here.
    structural = words('columns headers footers', lambda v: require(type(v) is dict, 'section structure must be an object'))
    fields(value, {**structural, 'start': enum('nextPage continuous evenPage oddPage nextColumn'),
                   **words('pageW pageH', scalar(1, 1584)),
                   **words('marginTop marginBottom marginLeft marginRight header footer headerGap footerGap gutter', POINTS),
                   **words('landscape titlePage pageNumSet rtl textDirectionSet', boolean),
                   'pageNumStart': optional(integer(0, 2**32-1)), 'pageNumFormat': NUMBER_FORMAT,
                   'chapterStyle': optional(integer(1, 9)), 'chapterSep': optional(enum('hyphen period colon emDash enDash')),
                   'lineNumbers': optional(line_numbers), 'valign': enum('top center justify bottom'),
                   'formProt': optional(boolean), 'pageBorders': optional(borders),
                   'textDirection': enum('horizontal down up'), 'fmtChange': optional(format_revision),
                   'docGrid': optional(document_grid), 'footnotePr': note, 'endnotePr': note,
                   **words('paperSrcFirst paperSrcOther', optional(integer(0, 65535))),
                   **words('noEndnote balanceColumns', optional(boolean)), 'footnoteColumns': optional(integer(0, 45))}, 'section properties')
    if value.get('docGrid') is not None: pending.add('resolved-document-grid')
    if value.get('formProt'): pending.add('document-protection')
    pending.add('number-label-fidelity')


def metadata(document, properties):
    pending = properties.pending; settings = document['settings']; backgrounds = set()

    def colors(value):
        for color in sequence(value, 256, 'theme colors'): RGB(color)

    def fonts(value):
        for family in sequence(value, 4096, 'roman font families'): properties.font(family)

    def background(value):
        # PagePicture intentionally retains snake_case native fields.
        fields(value, {'media': IDENTITY, 'fill_type': enum('tile frame'), 'title': DESCRIPTION}, 'page background')
        require(type(value.get('media')) is str and value['media'] in properties.media, 'page background references missing media')
        backgrounds.add(value['media']); pending.add('page-picture-layout')

    def watermark(value):
        fields(value, {'text': DESCRIPTION, 'font': properties.font, 'color': RGB,
                       'diagonal': boolean, 'semitransparent': boolean,
                       'size': optional(vector(scalar(.01, 2000), 2))}, 'watermark')
        pending.add('watermark-layout')

    def template(value):
        text(value, 'attached template', 4096)
        require(not value, 'external attached templates require a managed handoff')

    def link_styles(value):
        boolean(value); require(not value, 'automatic template style updates are not admitted')

    def tab(value):
        number(value, 1, 1584, 'default tab interval'); require(value > 1, 'default tab interval would use a native fallback')

    def protection_hash(value):
        seen = set()
        for pair in sequence(value, 64, 'document protection attributes'):
            sequence(pair, 2, 'protection attribute pair', 2); IDENTITY(pair[0]); text(pair[1], 'protection attribute', 8192)
            require(pair[0] not in seen, 'document protection attribute is duplicated'); seen.add(pair[0])
        if value: pending.add('document-protection')

    fields(settings, {**words('trackChanges trackMoves evenOddHeaders mirrorMargins autoHyphenation hyphenateCaps protectFormatting sumParagraphSpacing doNotExpandShiftReturn allowSpaceOfSameStyleInTable removePersonalInfo removeDateTime', boolean),
                      'defaultTab': tab, 'hyphenationZone': POINTS, 'consecutiveHyphenLimit': integer(0, 2**32-1),
                      'pageColor': optional(RGB), 'pagePicture': optional(background), 'watermark': optional(watermark),
                      **words('majorFont minorFont', properties.font), 'themeColors': colors, 'themeName': DESCRIPTION,
                      **words('footnoteFormat endnoteFormat', NUMBER_FORMAT), **words('footnotePr endnotePr', note),
                      'protection': optional(enum('readOnly comments trackedChanges forms none')), 'protectHash': protection_hash,
                      'compatMode': integer(0, 65535), 'romanFonts': fonts, **words('gridH gridV', scalar(.01, 1584)),
                      'math': optional(properties.deferred('math-settings')), 'bibStyle': optional(DESCRIPTION),
                      'attachedTemplate': optional(template), 'linkStyles': link_styles,
                      'zoom': optional(lambda v: fields(v, {'percent': integer(1, 1000), 'fit': optional(enum('onePage pageWidth textWidth'))}, 'zoom')),
                      'odf': optional(lambda v: fields(v, {'tabsFromIndent': boolean}, 'ODF layout'))}, 'document settings')
    if settings.get('autoHyphenation'): pending.add('hyphenation-resource-isolation')
    if settings.get('protection') is not None or settings.get('protectFormatting'): pending.add('document-protection')
    pending.add('number-label-fidelity')
    fields(document['core'], {**words('title subject creator keywords description category lastModifiedBy created modified', DESCRIPTION),
                              'revision': integer(0, 2**32-1)}, 'core metadata')
    tags = set(); names = set()
    source_fields = 'tag kind author corporate title year publisher city journal volume pages url editor edition issue month day accessed doi'
    for source in sequence(document['sources'], 4096, 'bibliography sources'):
        fields(source, words(source_fields, DESCRIPTION), 'bibliography source')
        tag = source.get('tag'); require(type(tag) is str and tag and tag not in tags, 'bibliography source tag is empty or duplicated')
        tags.add(tag)
    if tags: pending.add('bibliography-field-fidelity')
    for item in sequence(document['customProps'], 4096, 'custom properties'):
        record(item, {'name', 'kind', 'value'}, {'linkTarget', 'odfUserField'}, 'custom property')
        IDENTITY(item['name']); IDENTITY(item['kind']); text(item['value'], 'custom property value', 1 << 20)
        require(item['name'] and item['name'] not in names, 'custom property name is empty or duplicated'); names.add(item['name'])
        if item.get('linkTarget') is not None: IDENTITY(item['linkTarget']); pending.add('custom-property-bookmark')
        if 'odfUserField' in item: boolean(item['odfUserField'])
        if item['kind'] != 'lpwstr': pending.add('typed-custom-properties')
    return {'source_tags': sorted(tags), 'custom_properties': sorted(names), 'page_picture_media': sorted(backgrounds),
            'engine_admission_complete': False}


def style_metadata(style):
    for key in ('quick', 'hidden', 'builtin', 'locked', 'default'):
        if key in style: boolean(style[key])
    if style['priority'] is not None: uint(style['priority'], 2**32-1, 'style priority')


def list_level(value):
    NUMBER_FORMAT(value['format']); ALIGN(value['align']); enum('tab space nothing')(value['suffix'])
    boolean(value['restart']); boolean(value['legal'])
    if value.get('tab') is not None: number(value['tab'], -1584, 1584, 'list tab stop')


def list_metadata(value):
    for key in ('name', 'nsid', 'tmpl'):
        if value.get(key) is not None: IDENTITY(value[key])
    if value.get('multi_level_type') is not None: enum('singleLevel multilevel hybridMultilevel')(value['multi_level_type'])
