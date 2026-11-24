"""Bounded decoding of Animate envelopes and native path geometry.

This is the first admission layer, not permission to open a document in the
engine. Timeline structure, symbol expansion, embedded media, shaping and native
repair/preservation checks must also pass before a production operation opens it.
No operation is registered by this module. Inputs are never rewritten.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct

MAX_JSON = 64 << 20
MAX_ITEMS = 400_000
MAX_REPORT_ITEMS = 1_000_000
MAX_DEPTH = 64
MAX_PATH_BYTES = 2 << 20
MAX_PATHS = 8192
MAX_PATH_COMMANDS = 50_000
MAX_TOTAL_COMMANDS = 250_000
MAX_COORDINATE = 1_000_000
MAX_ID = 2**64 - 1


def number(value, low, high):
    return type(value) in (int, float) and low <= value <= high and math.isfinite(value)


def _preflight(data, max_items):
    """Limit nesting and allocations before json.loads builds Python objects."""
    depth = count = 0
    quoted = escaped = atom = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
            continue
        if byte in (123, 91):
            depth += 1; count += 1; atom = False
            if depth > MAX_DEPTH:
                raise ValueError('Animate JSON exceeds its nesting budget')
        elif byte in (125, 93):
            depth -= 1; atom = False
        elif byte == 34:
            quoted = True; atom = False; count += 1
        elif byte in (9, 10, 13, 32, 44, 58):
            atom = False
        elif not atom:
            atom = True; count += 1
        if count > max_items:
            raise ValueError('Animate JSON exceeds its item budget')


def strict_json(data, *, max_items=MAX_ITEMS):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Animate JSON contains duplicate keys')
            result[key] = value
        return result

    def integer(token):
        if len(token.lstrip('-')) > 20 or not -MAX_ID <= int(token) <= MAX_ID:
            raise ValueError('Animate JSON contains an unsupported integer')
        return int(token)

    def floating(token):
        result = float(token)
        if not number(result, -MAX_ID, MAX_ID):
            raise ValueError('Animate JSON contains an unsupported number')
        return result

    def constant(_):
        raise ValueError('Animate JSON contains nonfinite numbers')

    # File/envelope callers retain MAX_ITEMS. Only the private glyph diagnostic
    # reader requests the larger bounded report allowance.
    if type(max_items) is not int or not 1 <= max_items <= MAX_REPORT_ITEMS:
        raise ValueError('Animate JSON item budget is invalid')
    try:
        if isinstance(data, str):
            data = data.encode('utf-8')
        if not isinstance(data, bytes) or len(data) > MAX_JSON:
            raise ValueError('Animate JSON exceeds 64 MiB or is not UTF-8 data')
        _preflight(data, max_items)
        value = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                           parse_int=integer, parse_float=floating, parse_constant=constant)
    except (RecursionError, UnicodeError) as error:
        raise ValueError('Animate JSON is invalid or nested too deeply') from error
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item); pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and any(0xd800 <= ord(c) <= 0xdfff for c in item):
            raise ValueError('Animate JSON contains invalid Unicode')
    return value


def read_bytes(path):
    """Read one bounded regular file, refusing final symlinks and special files.

    The caller owns and resolves the containing directory. This is not a sandbox
    against hostile concurrent changes to ancestor directories.
    """
    try:
        descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_JSON:
                raise ValueError('Animate input requires a regular file of at most 64 MiB')
            data = stream.read(MAX_JSON + 1)
            after = os.fstat(stream.fileno())
        if (len(data) != before.st_size or len(data) > MAX_JSON
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('Animate input changed while it was read')
        return data
    except OSError as error:
        raise ValueError('Animate input cannot be read as a regular file') from error


@dataclass(frozen=True)
class NativePath:
    # Each tuple holds a native command and its f32 coordinates. Repeated M
    # commands stay M: unlike general SVG, AniCraft does not turn them into L.
    commands: tuple
    control_bounds: tuple | None

    @property
    def digest(self):
        digest = hashlib.sha256()
        for command, coordinates in self.commands:
            digest.update(command.encode('ascii'))
            digest.update(struct.pack('<' + 'f' * len(coordinates), *coordinates))
        return digest.hexdigest()


_ARITY = {'M': 2, 'L': 2, 'Q': 4, 'C': 6, 'Z': 0}
# Consume the same candidate number as the native scanner, including malformed
# decimals/exponents. A conventional SVG token regex could wrongly split 1.2.3
# into two valid numbers even though the native parser rejects it.
_NUMBER = re.compile(r'[-+]?[0-9.](?:[0-9.eE]|(?<=[eE])[-+])*', re.ASCII)


def _coordinate(value):
    if not number(value, -MAX_COORDINATE, MAX_COORDINATE):
        raise ValueError('Animate path coordinate exceeds its budget')
    return struct.unpack('<f', struct.pack('<f', value))[0]


def native_path(value):
    """Decode the native absolute SVG subset or its legacy tagged equivalent."""
    commands = []
    bounds = None

    def emit(command, coordinates):
        nonlocal bounds
        if len(commands) >= MAX_PATH_COMMANDS:
            raise ValueError('Animate path exceeds its command budget')
        points = tuple(_coordinate(v) for v in coordinates)
        commands.append((command, points))
        for index in range(0, len(points), 2):
            x, y = points[index:index + 2]
            bounds = (x, y, x, y) if bounds is None else (
                min(bounds[0], x), min(bounds[1], y), max(bounds[2], x), max(bounds[3], y))

    if isinstance(value, str):
        if len(value) > MAX_PATH_BYTES or not value.isascii():
            raise ValueError('Animate path requires bounded ASCII geometry')
        position = 0; current = None; coordinates = []; groups = 0

        def finish():
            if current == 'Z':
                emit('Z', ())
            elif current is not None and (coordinates or groups == 0):
                raise ValueError('Animate path command has incomplete coordinates')

        while position < len(value):
            char = value[position]
            if char in ' ,\n\r\t':
                position += 1
                continue
            if char in 'MLQCZz':
                finish(); current = char.upper(); groups = 0; coordinates = []
                position += 1
                continue
            match = _NUMBER.match(value, position)
            if match is None or current is None or current == 'Z':
                raise ValueError('Animate path contains an unsupported command or number')
            try:
                coordinates.append(float(match.group()))
            except ValueError as error:
                raise ValueError('Animate path contains an invalid number') from error
            position = match.end()
            if len(coordinates) == _ARITY[current]:
                emit(current, coordinates); coordinates = []; groups += 1
        finish()
    elif isinstance(value, dict) and set(value) == {'cmds'} and isinstance(value['cmds'], list):
        if len(value['cmds']) > MAX_PATH_COMMANDS:
            raise ValueError('Animate path exceeds its command budget')
        tags = {'MoveTo': ('M', 1), 'LineTo': ('L', 1), 'QuadTo': ('Q', 2), 'CubicTo': ('C', 3)}
        for item in value['cmds']:
            if item == 'Close':
                emit('Z', ()); continue
            if not isinstance(item, dict) or len(item) != 1 or next(iter(item)) not in tags:
                raise ValueError('Animate legacy path command is invalid')
            name = next(iter(item)); command, count = tags[name]
            points = [item[name]] if count == 1 else item[name]
            if (not isinstance(points, list) or len(points) != count
                    or any(not isinstance(p, dict) or set(p) != {'x', 'y'} for p in points)):
                raise ValueError('Animate legacy path coordinates are invalid')
            emit(command, [v for point in points for v in (point['x'], point['y'])])
    else:
        raise ValueError('Animate path requires native SVG data or tagged commands')
    return NativePath(tuple(commands), bounds)


class PathTable:
    """Bound shared and inline geometry without expanding shared references."""

    def __init__(self, paths):
        if not isinstance(paths, list) or len(paths) > MAX_PATHS:
            raise ValueError('Animate path table exceeds its entry budget')
        self.commands = 0
        self.used = set()
        self.paths = tuple(self._parse(path) for path in paths)

    def _parse(self, value):
        path = native_path(value)
        self.commands += len(path.commands)
        if self.commands > MAX_TOTAL_COMMANDS:
            raise ValueError('Animate geometry exceeds its total command budget')
        return path

    def resolve(self, value):
        if type(value) is int:
            if not 0 <= value < len(self.paths):
                raise ValueError('Animate shared path reference is out of range')
            self.used.add(value)
            return self.paths[value]
        return self._parse(value)

    def fork(self):
        """Start an independent admission pass sharing only immutable geometry."""
        result = object.__new__(PathTable)
        result.paths = self.paths
        result.commands = sum(len(path.commands) for path in self.paths)
        result.used = set()
        return result

    def require_used(self):
        if len(self.used) != len(self.paths):
            raise ValueError('Animate path table contains unused geometry that native save would discard')


def decode_envelope(data):
    """Decode format 3 and its path table; document admission remains separate."""
    envelope = strict_json(data)
    if (not isinstance(envelope, dict)
            or set(envelope) != {'format', 'version', 'generator', 'paths', 'document'}
            or envelope['format'] != 'anicraft' or type(envelope['version']) is not int
            or envelope['version'] != 3 or not isinstance(envelope['document'], dict)
            or not isinstance(envelope['generator'], str) or not 1 <= len(envelope['generator']) <= 256):
        raise ValueError('Animate requires a complete native format 3 envelope')
    # The native deserializer is streaming. A reference is invalid if document
    # precedes paths, even though an ordinary JSON dictionary accepts that order.
    fields = list(envelope)
    if fields.index('paths') > fields.index('document'):
        raise ValueError('Animate native path table must precede its document')
    return envelope, PathTable(envelope['paths'])


def read_envelope(path):
    data = read_bytes(path)
    envelope, paths = decode_envelope(data)
    return envelope, paths, hashlib.sha256(data).hexdigest()
