"""Bound TrueType outlines and composite expansion without executing hint programs."""
from collections import deque
import hashlib
import struct

from .write_container import require

MAX_POINTS = 2_000_000
MAX_COMPONENTS = 200_000
MAX_DEPTH = 16


class Reader:
    def __init__(self, data): self.data = data; self.offset = 0

    def take(self, size):
        require(0 <= size <= len(self.data)-self.offset, 'font outline record exceeds owned bytes')
        result = self.data[self.offset:self.offset+size]; self.offset += size; return result

    def read(self, pattern): return struct.unpack(pattern, self.take(struct.calcsize(pattern)))

    def padding(self):
        remaining = self.data[self.offset:]
        require(len(remaining) <= 3 and not any(remaining), 'font outline has nonzero or excessive trailing bytes')


def program(data):
    """Check immediate operand ownership only; jumps/functions are not executed."""
    require(len(data) <= 256 << 10, 'font hint program exceeds byte budget')
    reader = Reader(data); instructions = 0
    while reader.offset < len(data):
        opcode = reader.read('>B')[0]; instructions += 1
        if opcode in (0x40, 0x41):
            count = reader.read('>B')[0]; reader.take(count*(2 if opcode == 0x41 else 1))
        elif 0xb0 <= opcode <= 0xb7: reader.take(opcode-0xb0+1)
        elif 0xb8 <= opcode <= 0xbf: reader.take(2*(opcode-0xb8+1))
    return {'bytes': len(data), 'opcodes': instructions, 'sha256': hashlib.sha256(data).hexdigest()}


def inspect(tables, offsets):
    limits = struct.unpack('>13H', tables['maxp'][6:32])
    max_points, max_contours, max_comp_points, max_comp_contours, zones, twilight, storage, functions, definitions, stack, max_instructions, max_components, max_depth = limits
    require(zones in (1, 2) and twilight <= 1024 and storage <= 16_384 and functions <= 4096 and definitions <= 256 and stack <= 4096,
            'font hint allocation declarations exceed profile bounds')
    require(max_components <= 128 and max_depth <= MAX_DEPTH, 'font composite declarations exceed profile bounds')
    glyf = tables['glyf']; glyph_count = len(offsets)-1
    records = []; simple_points = 0; component_count = 0; program_bytes = 0; program_ops = 0
    for glyph_id, (start, end) in enumerate(zip(offsets, offsets[1:])):
        if start == end:
            records.append({'points': 0, 'contours': 0, 'children': [], 'bound': 0, 'composite': False}); continue
        reader = Reader(glyf[start:end]); contours, xmin, ymin, xmax, ymax = reader.read('>hhhhh')
        require(xmin <= xmax and ymin <= ymax, 'font outline bounds are inverted')
        children = []; instructions = b''; bound = max(map(abs, (xmin, ymin, xmax, ymax)))
        if contours >= 0:
            require(contours <= max_contours, 'font outline contours exceed maxp declaration')
            ends = [reader.read('>H')[0] for _ in range(contours)]
            require(all(a < b for a, b in zip(ends, ends[1:])), 'font outline contour endpoints are unordered')
            points = ends[-1]+1 if ends else 0
            require(points <= max_points, 'font outline points exceed maxp declaration')
            simple_points += points; require(simple_points <= MAX_POINTS, 'font outlines exceed aggregate point budget')
            length = reader.read('>H')[0]; instructions = reader.take(length)
            flags = []
            while len(flags) < points:
                flag = reader.read('>B')[0]
                require(flag & 0x80 == 0, 'font cubic outline flags need separate qualification')
                repeats = reader.read('>B')[0] if flag & 8 else 0
                require(len(flags)+repeats+1 <= points, 'font outline flag repeat exceeds point count')
                flags.extend([flag]*(repeats+1))
            # Coordinate deltas are decoded independently, not merely skipped.
            for short, same, low, high in ((2, 16, xmin, xmax), (4, 32, ymin, ymax)):
                position = 0
                for flag in flags:
                    if flag & short:
                        delta = reader.read('>B')[0]; delta = delta if flag & same else -delta
                    else: delta = 0 if flag & same else reader.read('>h')[0]
                    position += delta
                    require(low <= position <= high, 'font outline coordinate escapes declared bounds')
        else:
            require(contours == -1, 'font outline contour type is unsupported')
            points = 0
            while True:
                flags, child = reader.read('>HH')
                require(flags & ~0x1fef == 0 and child < glyph_count, 'font composite flags or glyph reference are invalid')
                require(sum(bool(flags & bit) for bit in (8, 64, 128)) <= 1 and flags & 0x1800 != 0x1800,
                        'font composite transform flags conflict')
                require(not (flags & 256 and flags & 32), 'font composite instructions precede its final component')
                xy = bool(flags & 2); words = bool(flags & 1)
                args = reader.read('>hh' if xy and words else '>bb' if xy else '>HH' if words else '>BB')
                matrix = (1.0, 0.0, 0.0, 1.0)
                if flags & 8:
                    scale = reader.read('>h')[0]/16384; matrix = (scale, 0.0, 0.0, scale)
                elif flags & 64:
                    x, y = reader.read('>hh'); matrix = (x/16384, 0.0, 0.0, y/16384)
                elif flags & 128: matrix = tuple(x/16384 for x in reader.read('>hhhh'))
                children.append({'glyph': child, 'xy': xy, 'args': args, 'matrix': matrix, 'scaled': bool(flags & 2048)})
                component_count += 1
                require(len(children) <= max_components and component_count <= MAX_COMPONENTS, 'font composite components exceed budget or declaration')
                if not flags & 32: break
            if flags & 256: instructions = reader.take(reader.read('>H')[0])
        require(len(instructions) <= max_instructions, 'font glyph instructions exceed maxp declaration')
        hint = program(instructions); program_bytes += hint['bytes']; program_ops += hint['opcodes']
        require(program_bytes <= 8 << 20, 'font glyph instructions exceed aggregate byte budget')
        reader.padding()
        records.append({'points': points, 'contours': max(contours, 0), 'children': children, 'bound': bound, 'composite': contours < 0})

    # Resolve a DAG iteratively. Repeated references remain repeated expansion;
    # only dependency scheduling deduplicates them. No recursion or outline copies.
    remaining = []; parents = [[] for _ in records]; ready = deque(); resolved = [None]*glyph_count
    for index, record in enumerate(records):
        dependencies = {c['glyph'] for c in record['children']}; remaining.append(len(dependencies))
        for child in dependencies: parents[child].append(index)
        if not dependencies: ready.append(index)
    visited = 0; expanded_points = 0; expanded_nodes = 0; point_attachments = 0; deepest = 0
    while ready:
        index = ready.popleft(); record = records[index]; points = record['points']; contours = record['contours']; depth = 0; nodes = 1; bound = record['bound']
        for component in record['children']:
            child = resolved[component['glyph']]; nodes += child['nodes']; depth = max(depth, child['depth']+1)
            if not component['xy']:
                first, second = component['args']; point_attachments += 1
                require(first < points and second < child['points'], 'font composite point attachment is outside owned outlines')
            points += child['points']; contours += child['contours']
            matrix = component['matrix']; scale = max(abs(matrix[0])+abs(matrix[2]), abs(matrix[1])+abs(matrix[3]))
            if component['xy']:
                shift = max(map(abs, component['args']))*(max(1, scale) if component['scaled'] else 1)
            else: shift = bound+child['bound']*scale
            bound = max(bound, child['bound']*scale+shift)
            require(points <= max_comp_points and contours <= max_comp_contours and nodes <= 4096 and depth <= max_depth and depth <= MAX_DEPTH,
                    'font composite expansion exceeds budget or maxp declaration')
            require(bound <= 1_000_000, 'font composite transformed coordinates exceed budget')
        expanded_points += points; expanded_nodes += nodes
        require(expanded_points <= MAX_POINTS and expanded_nodes <= 2_000_000, 'font composite aggregate expansion exceeds budget')
        resolved[index] = {'points': points, 'contours': contours, 'nodes': nodes, 'depth': depth, 'bound': bound}; visited += 1; deepest = max(deepest, depth)
        for parent in parents[index]:
            remaining[parent] -= 1
            if remaining[parent] == 0: ready.append(parent)
    require(visited == glyph_count, 'font composite graph contains a cycle')
    programs = {}
    for tag in ('fpgm', 'prep'):
        if tag in tables: programs[tag] = program(tables[tag])
    if 'cvt ' in tables:
        require(len(tables['cvt ']) % 2 == 0 and len(tables['cvt ']) <= 131_070, 'font control-value table has invalid length')
    return {'glyphs': glyph_count, 'simple_points': simple_points, 'expanded_points': expanded_points,
            'components': component_count, 'expanded_nodes': expanded_nodes, 'maximum_depth': deepest,
            'point_attachments': point_attachments, 'glyph_instruction_bytes': program_bytes, 'glyph_instruction_opcodes': program_ops,
            'programs': programs, 'hint_execution_qualified': False,
            'pending_qualification': ['font-hint-execution', 'font-outline-renderer-comparison', 'font-layout-and-variation-tables']}
