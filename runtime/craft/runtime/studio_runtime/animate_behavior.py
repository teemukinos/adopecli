"""Bounded stored actions, scripts, linkage and publish settings for Animate.

Inspect after graph admission. Nothing here resolves action targets, compiles or
runs scripts, loads plugins, or authorizes publishing. Stored output templates
are document data, never filesystem authority. Closed runtime operations must
choose attempt-owned outputs independently and prove complete native readback.
"""
import math
import re

from .animate_graph import fields, sequence
from .animate_properties import boolean, choice, f32
from .animate_unicode import ALPHABETIC, NUMERIC, contains, trim

MAX_ACTIONS = 32768
MAX_SOURCE_BYTES = 4 << 20
MAX_METADATA_BYTES = 4 << 20
EVENTS = ('click', 'press', 'release', 'over', 'out')
PROPERTY_RANGES = {'x': (-1e6, 1e6), 'y': (-1e6, 1e6), 'alpha': (0, 1),
                   'visible': (0, 1), 'rotation': (-36000, 36000),
                   'scale_x': (-1000, 1000), 'scale_y': (-1000, 1000)}
FORMATS = {
    'html': ('title', 'sound', 'fit'),
    'gif': ('range', 'scale', 'loop'),
    'video': ('range', 'scale', 'audio'),
    'lottie': ('range', 'background'),
    'sprite_sheet': ('range', 'scale', 'columns', 'padding', 'background'),
    'png_sequence': ('range', 'scale'),
    'png': ('frame', 'scale'),
    'svg': ('frame',),
    'audio': ('range', 'rate', 'bits'),
}


def text(value, limit, label, *, printable=False):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Animate ' + label + ' exceeds its text budget')
    if printable and (not trim(value) or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)):
        raise ValueError('Animate ' + label + ' must contain printable text')
    return value


def uint(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Animate ' + label + ' exceeds its integer range')
    return value


def class_name(value, *, empty=False):
    text(value, 256, 'class name')
    if empty and value == '':
        return
    for part in value.split('.'):
        if not part or not (part[0] in '_$' or contains(ALPHABETIC, part[0])):
            raise ValueError('Animate class name would be discarded')
        if any(c not in '_$' and not contains(ALPHABETIC, c) and not contains(NUMERIC, c) for c in part):
            raise ValueError('Animate class name would be discarded')


def target(value):
    # Limit raw whitespace too: the native parser bounds only the trimmed text.
    text(value, 1024, 'raw action target'); value = trim(value)
    text(value, 256, 'action target')
    if not value:
        return
    depth = 0
    for index, raw in enumerate(value.split('.')):
        part = trim(raw)
        if index == 0 and part == 'this':
            continue
        if not ((index == 0 and part in ('root', '_root')) or part in ('parent', '_parent')):
            if (not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]{0,63}', part)
                    or part in ('this', 'root', '_root')):
                raise ValueError('Animate action target contains an invalid step')
        depth += 1
        if depth > 16:
            raise ValueError('Animate action target exceeds its depth budget')


def actions(value, budget, *, nonempty=False):
    sequence(value, 256, 'action list')
    if nonempty and not value:
        raise ValueError('Animate empty frame actions would be discarded')
    budget['actions'] += len(value)
    if budget['actions'] > MAX_ACTIONS:
        raise ValueError('Animate document exceeds its stored action budget')
    for action in value:
        if not isinstance(action, dict):
            raise ValueError('Animate action must be an object')
        op = action.get('op')
        if op in ('stop', 'play', 'next_frame', 'prev_frame'):
            fields(action, ('op',), ('target',), 'timeline action')
        elif op in ('goto_and_play', 'goto_and_stop'):
            fields(action, ('op',), ('target', 'frame', 'scene'), 'goto action')
            at = action.get('frame', 0)
            if isinstance(at, str):
                text(at, 256, 'action frame label', printable=True)
            else:
                uint(at, 100000, 'action frame')
            scene = action.get('scene')
            if scene is not None:
                text(scene, 256, 'action scene', printable=True)
        elif op in ('next_scene', 'prev_scene'):
            fields(action, ('op',), (), 'scene action')
        elif op == 'trace':
            fields(action, ('op',), ('message',), 'trace action')
            text(action.get('message', ''), 1000, 'trace message')
        elif op == 'set_property':
            fields(action, ('op', 'property', 'value'), ('target',), 'property action')
            choice(action['property'], PROPERTY_RANGES, 'action property')
            number = action['value']
            if type(number) not in (int, float) or not math.isfinite(number):
                raise ValueError('Animate action value must be finite')
            lo, hi = PROPERTY_RANGES[action['property']]
            # Native check_actions accepts finite out-of-range values. A clean
            # list keeps them on load; playback clamps them. Do not invent a
            # load-repair claim or lose the stored value.
            if not lo <= number <= hi:
                budget['playback_clamped_values'] += 1
        else:
            raise ValueError('Animate action operation is invalid')
        if 'target' in action:
            target(action['target'])
        budget['metadata_bytes'] += sum(len(v.encode('utf-8')) for v in action.values() if isinstance(v, str))


def script(value, budget):
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError('Animate frame script must have one variant')
    if 'actions' in value:
        actions(value['actions'], budget, nonempty=True)
    elif 'plugin' in value:
        plugin = value['plugin']; fields(plugin, ('id',), ('entry',), 'plugin reference')
        if (not isinstance(plugin['id'], str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', plugin['id'])
                or not isinstance(plugin.get('entry', 'main'), str)
                or not re.fullmatch(r'[A-Za-z0-9_]{1,32}', plugin.get('entry', 'main'))):
            raise ValueError('Animate plugin reference would be discarded')
        budget['plugin_references'] += 1
    elif 'source' in value:
        source = value['source']; fields(source, (), ('language', 'text'), 'source script')
        choice(source.get('language', 'actionscript3'), ('actionscript3', 'actionscript1or2', 'other'), 'script language')
        content = source.get('text', '')
        if not isinstance(content, str) or not trim(content) or len(content.encode('utf-8')) > 1 << 20:
            raise ValueError('Animate source script would be discarded')
        budget['source_bytes'] += len(content.encode('utf-8')); budget['source_scripts'] += 1
        if budget['source_bytes'] > MAX_SOURCE_BYTES:
            raise ValueError('Animate document exceeds its stored source budget')
    else:
        raise ValueError('Animate frame script variant is invalid')


def publish_profile(value):
    """Validate preserved settings, without resolving templates or exporting.

    Native load preserves even unusable paths and frames beyond the movie. Report
    enabled formats only as stored preferences. Allocation, supported exports and
    output location require independent checks in a closed export operation.
    """
    fields(value, (), FORMATS, 'publish profile'); enabled = []
    for format, options in FORMATS.items():
        settings = value.get(format, {})
        fields(settings, (), ('enabled', 'output') + options, 'publish ' + format)
        on = settings.get('enabled', format == 'html'); boolean(on, 'publish enabled')
        if on:
            enabled.append(format)
        if 'output' in settings:
            output = text(settings['output'], 512, 'publish output template')
            if not trim(output):
                raise ValueError('Animate empty publish output would be replaced')
        for name in ('sound', 'fit', 'loop', 'audio', 'background'):
            if name in settings:
                boolean(settings[name], 'publish ' + name)
        if 'title' in settings:
            text(settings['title'], 256, 'publish title')
        if 'scale' in settings:
            scale = settings['scale']
            if type(scale) not in (int, float) or not math.isfinite(scale) or not 0 < scale <= 16 or not 0 < f32(scale) <= 8:
                raise ValueError('Animate publish scale would be replaced or clamped')
        if 'range' in settings:
            interval = settings['range']; fields(interval, (), ('from', 'to'), 'publish frame range')
            first, last = interval.get('from'), interval.get('to')
            for at in (first, last):
                if at is not None:
                    uint(at, 0xffffffff, 'publish frame')
            if first is not None and last is not None and last < first:
                raise ValueError('Animate publish range would be reordered')
        for name, limit in (('frame', 0xffffffff), ('columns', 10000), ('padding', 256), ('rate', 192000), ('bits', 32)):
            if name in settings:
                uint(settings[name], limit, 'publish ' + name)
        if 'rate' in settings and settings['rate'] < 8000:
            raise ValueError('Animate publish sample rate would be clamped')
        if 'bits' in settings and settings['bits'] not in (16, 24, 32):
            raise ValueError('Animate publish sample depth would be replaced')
    return {'enabled_formats': enabled, 'execution_authorized': False,
            'output_templates_trusted': False, 'export_budget_verified': False}


def inspect_behavior(document):
    """Check stored behavior and settings after structural graph admission."""
    budget = dict(actions=0, handlers=0, source_bytes=0, source_scripts=0,
                  plugin_references=0, metadata_bytes=0, playback_clamped_values=0)
    name = document.get('document_class', ''); class_name(name, empty=True)
    budget['metadata_bytes'] += len(name.encode('utf-8'))
    for symbol in document['library']:
        linkage = symbol.get('linkage')
        if linkage is not None:
            fields(linkage, ('class',), ('base',), 'symbol linkage')
            class_name(linkage['class']); class_name(linkage.get('base', ''), empty=True)
            budget['metadata_bytes'] += sum(len(v.encode('utf-8')) for v in linkage.values())
    for owner in document['scenes'] + document['library']:
        for layer in owner['timeline']['layers']:
            for key in layer['keyframes']:
                label = text(key.get('label', ''), 1024, 'stored frame label')
                budget['metadata_bytes'] += len(label.encode('utf-8'))
                if key.get('script') is not None:
                    script(key['script'], budget)
                for element in key.get('elements', []):
                    kind = element['kind']
                    if not isinstance(kind, dict) or 'Symbol' not in kind:
                        continue
                    handlers = sequence(kind['Symbol'].get('events', []), 5, 'event handlers')
                    seen = set(); budget['handlers'] += len(handlers)
                    for handler in handlers:
                        fields(handler, ('event',), ('actions',), 'event handler')
                        event = handler['event']; choice(event, EVENTS, 'event')
                        if event in seen:
                            raise ValueError('Animate duplicate event handler would be discarded')
                        seen.add(event); actions(handler.get('actions', []), budget)
                if budget['metadata_bytes'] > MAX_METADATA_BYTES or budget['handlers'] > 8192:
                    raise ValueError('Animate document exceeds its behavior metadata budget')
    return {'budget': budget, 'publish': publish_profile(document.get('publish', {})),
            'action_targets_resolved': False, 'scripts_executed': False,
            'plugins_loaded': False, 'interactive_playback_verified': False}
