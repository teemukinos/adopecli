"""Bounded inspection of the runtime's owned, progressive H.264/AAC MP4 files.

Validate complete sample tables, coded byte ownership and exact presentation
timing before decoding. This deliberately does not claim codec or player fidelity.
"""
import hashlib
import os
import stat
import struct
import time

MAX_BYTES = 512 << 20
MAX_METADATA = 4 << 20
MAX_SAMPLES = 40000
IDENTITY = struct.pack('>9i', 65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824)


def require(condition, message):
    if not condition:
        raise ValueError('Animate MP4 ' + message)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


class Reader:
    def __init__(self, stream, length, deadline, cancelled):
        self.stream = stream; self.length = length; self.deadline = deadline; self.cancelled = cancelled
        self.box_count = 0; self.metadata_bytes = 0

    def check(self):
        require(not self.cancelled() and time.monotonic() < self.deadline, 'inspection cancelled or timed out')

    def read(self, at, size):
        self.check()
        require(0 <= at <= self.length and 0 <= size <= self.length-at, 'read exceeds file bounds')
        self.stream.seek(at); data = self.stream.read(size)
        require(len(data) == size, 'has a truncated payload')
        return data

    def boxes(self, start, end):
        entries = []; at = start
        while at < end:
            require(end-at >= 8 and self.box_count < 4096, 'box count or boundary is invalid')
            self.box_count += 1
            size, kind = struct.unpack('>I4s', self.read(at, 8)); header = 8
            if size == 1:
                require(end-at >= 16, 'extended box header is truncated')
                size = struct.unpack('>Q', self.read(at+8, 8))[0]; header = 16
            require(header <= size <= end-at, 'box size is invalid')
            entries.append((kind, at+header, at+size, at)); at += size
        return entries

    def children(self, box, allowed):
        entries = self.boxes(box[1], box[2])
        require(all(row[0] in allowed for row in entries), 'contains an unsupported box')
        return entries

    def one(self, entries, kind, optional=False):
        found = [row for row in entries if row[0] == kind]
        require(len(found) == 1 or optional and not found, 'requires exactly one '+kind.decode('ascii', 'replace')+' box')
        return found[0] if found else None

    def payload(self, box):
        size = box[2]-box[1]; self.metadata_bytes += size
        require(size <= 1 << 20 and self.metadata_bytes <= MAX_METADATA, 'metadata exceeds its byte budget')
        return self.read(box[1], size)

    def table(self, box, width, maximum, *, versions=(0,)):
        data = self.payload(box)
        require(len(data) >= 8 and data[0] in versions and data[1:4] == b'\0'*3, 'sample table header is invalid')
        count = struct.unpack_from('>I', data, 4)[0]
        require(0 < count <= maximum and len(data) == 8+count*width, 'sample table length is invalid')
        return data, count


def time_header(data, movie=False):
    require(len(data) >= 4 and data[0] in (0, 1) and data[1:4] == b'\0'*3, 'time header is invalid')
    version = data[0]; expected = (100 if movie else 24) + 12*version
    require(len(data) == expected, 'time header length is invalid')
    rate, duration = struct.unpack_from('>IQ' if version else '>II', data, 20 if version else 12)
    require(0 < rate <= 2147483647 and duration > 0, 'timebase or duration is invalid')
    if movie:
        offset = 32 if version else 20
        require(data[offset:offset+6] == b'\0\1\0\0\1\0' and data[offset+16:offset+52] == IDENTITY,
                'movie rate, volume or transform is unsupported')
    return rate, duration


def avc_config(data):
    require(7 <= len(data) <= 65536 and data[0] == 1 and data[4] == 255 and data[5] & 224 == 224,
            'AVC configuration is invalid')
    at = 6; sps = data[5] & 31
    require(sps > 0, 'AVC configuration has no SPS')

    def units(count, kind):
        nonlocal at
        for _ in range(count):
            require(at+2 <= len(data), 'AVC parameter length is truncated')
            size = struct.unpack_from('>H', data, at)[0]; at += 2
            require(size > 0 and at+size <= len(data) and data[at] & 128 == 0 and data[at] & 31 == kind,
                    'AVC parameter set is invalid')
            at += size
    units(sps, 7)
    require(at < len(data) and data[at] > 0, 'AVC configuration has no PPS')
    count = data[at]; at += 1; units(count, 8)
    if at < len(data):
        require(data[1] in (100, 110, 122, 144) and at+4 <= len(data)
                and data[at] & 252 == 252 and data[at+1] & 248 == 248 and data[at+2] & 248 == 248,
                'AVC extension is invalid')
        count = data[at+3]; at += 4; units(count, 13)
    require(at == len(data), 'AVC configuration has trailing data')
    return hashlib.sha256(data).hexdigest()


def aac_config(data):
    require(data[:4] == b'\0'*4, 'AAC descriptor header is invalid')

    def descriptor(at, end, tag):
        require(at < end and data[at] == tag, 'AAC descriptor tag is invalid')
        at += 1; size = 0
        for index in range(4):
            require(at < end, 'AAC descriptor size is truncated')
            byte = data[at]; at += 1; size = (size << 7) | (byte & 127)
            if byte & 128 == 0:
                break
            require(index < 3, 'AAC descriptor size is excessive')
        require(size <= end-at, 'AAC descriptor exceeds its parent')
        return at, at+size

    start, end = descriptor(4, len(data), 3)
    require(end == len(data) and start+3 <= end and data[start:start+3] == b'\0\1\0', 'AAC ES descriptor is unsupported')
    config, config_end = descriptor(start+3, end, 4)
    require(config+13 <= config_end and data[config:config+2] == b'\x40\x15', 'AAC decoder configuration is unsupported')
    asc, asc_end = descriptor(config+13, config_end, 5)
    require(asc_end == config_end and data[asc:asc_end] == b'\x11\x90', 'requires AAC-LC stereo at 48000 Hz')
    sl, sl_end = descriptor(config_end, end, 6)
    require(sl_end == end and data[sl:sl_end] == b'\x02', 'AAC synchronization descriptor is unsupported')
    return hashlib.sha256(data[asc:asc_end]).hexdigest()


def description(reader, table, picture, size):
    box = reader.one(table, b'stsd'); data = reader.payload(box)
    require(data[:8] == b'\0\0\0\0\0\0\0\1', 'requires one sample description')
    entries = reader.boxes(box[1]+8, box[2]); entry = reader.one(entries, b'avc1' if picture else b'mp4a')
    require(len(entries) == 1, 'has extra sample descriptions')
    length = 78 if picture else 28
    require(entry[2]-entry[1] >= length, 'sample description is truncated')
    header = reader.read(entry[1], length)
    require(header[:8] == b'\0'*6+b'\0\1', 'uses an external data reference')
    if picture:
        require(list(struct.unpack_from('>HH', header, 24)) == size, 'coded dimensions disagree with the request')
        require(header[8:24] == b'\0'*16 and header[28:42] == struct.pack('>IIIH', 72 << 16, 72 << 16, 0, 1)
                and header[74:] == b'\0\x18\xff\xff', 'visual sample description is unsupported')
    else:
        require(header[8:16] == b'\0'*8 and struct.unpack_from('>HH', header, 16) == (2, 16)
                and header[20:24] == b'\0'*4
                and struct.unpack_from('>I', header, 24)[0] == 48000 << 16, 'audio sample description is unsupported')
    children = reader.boxes(entry[1]+length, entry[2])
    allowed = (b'avcC', b'colr', b'pasp', b'btrt') if picture else (b'esds',)
    require(all(row[0] in allowed for row in children), 'sample description has unsupported extensions')
    for kind in allowed:
        extra = reader.one(children, kind, optional=True)
        if extra is not None and kind == b'pasp':
            require(reader.payload(extra) == struct.pack('>II', 1, 1), 'pixel aspect ratio is not square')
        elif extra is not None and kind == b'colr':
            require(reader.payload(extra) == b'nclx'+struct.pack('>HHHB', 1, 1, 1, 0), 'color signal is not limited-range Rec.709')
        elif extra is not None and kind == b'btrt':
            require(len(reader.payload(extra)) == 12, 'bitrate metadata is malformed')
    if picture:
        reader.one(children, b'colr')
    codec = reader.payload(reader.one(children, b'avcC' if picture else b'esds'))
    return (avc_config(codec) if picture else aac_config(codec)), codec


def track(reader, box, movie_rate, planned, mdat):
    entries = reader.children(box, (b'tkhd', b'edts', b'mdia'))
    header = reader.payload(reader.one(entries, b'tkhd'))
    require(len(header) >= 4 and header[0] in (0, 1) and header[1:4] == b'\0\0\3', 'track header is invalid')
    version = header[0]
    require(len(header) == 84+12*version and header[-44:-8] == IDENTITY, 'track dimensions or transform is invalid')
    identity = struct.unpack_from('>I', header, 20 if version else 12)[0]
    track_duration = struct.unpack_from('>Q' if version else '>I', header, 28 if version else 20)[0]
    mdia = reader.children(reader.one(entries, b'mdia'), (b'mdhd', b'hdlr', b'minf'))
    handler = reader.payload(reader.one(mdia, b'hdlr'))
    require(24 <= len(handler) <= 256 and handler[:8] == b'\0'*8 and handler[12:24] == b'\0'*12
            and handler[8:12] in (b'vide', b'soun'), 'track handler is unsupported')
    picture = handler[8:12] == b'vide'; name = 'video' if picture else 'audio'
    require(identity > 0 and (picture or planned['audio_samples'] is not None), 'contains an unexpected track')
    dimensions = struct.unpack_from('>II', header, len(header)-8)
    expected_dimensions = tuple(side << 16 for side in planned['encoded_size']) if picture else (0, 0)
    require(dimensions == expected_dimensions, 'track display dimensions disagree with the request')
    rate, duration = time_header(reader.payload(reader.one(mdia, b'mdhd')))
    minf = reader.children(reader.one(mdia, b'minf'), (b'vmhd', b'smhd', b'dinf', b'stbl'))
    media_header = reader.payload(reader.one(minf, b'vmhd' if picture else b'smhd'))
    require(media_header == (b'\0\0\0\1'+b'\0'*8 if picture else b'\0'*8), 'media header is unsupported')
    require(not any(row[0] == (b'smhd' if picture else b'vmhd') for row in minf), 'media header disagrees with its handler')
    dinf = reader.children(reader.one(minf, b'dinf'), (b'dref',))
    require(reader.payload(reader.one(dinf, b'dref')) == b'\0\0\0\0\0\0\0\1\0\0\0\x0curl \0\0\0\1',
            'data references are not self-contained')
    table = reader.children(reader.one(minf, b'stbl'), (b'stsd', b'stts', b'ctts', b'stss', b'stsc', b'stsz', b'stco', b'co64'))
    config_hash, codec = description(reader, table, picture, planned['encoded_size'])
    sizes = reader.payload(reader.one(table, b'stsz'))
    require(len(sizes) >= 12 and sizes[:4] == b'\0'*4, 'sample sizes header is invalid')
    constant, count = struct.unpack_from('>II', sizes, 4)
    require(0 < count <= MAX_SAMPLES and len(sizes) == (12 if constant else 12+4*count), 'sample sizes table is invalid')
    lengths = [constant]*count if constant else list(struct.unpack_from('>'+str(count)+'I', sizes, 12))
    require(all(0 < size <= MAX_BYTES for size in lengths), 'has an empty or excessive coded sample')
    timing, rows = reader.table(reader.one(table, b'stts'), 8, count)
    deltas = []
    for n in range(rows):
        repeat, delta = struct.unpack_from('>II', timing, 8+8*n)
        require(repeat > 0 and delta > 0 and len(deltas)+repeat <= count, 'decode timing runs are invalid')
        deltas.extend([delta]*repeat)
    require(len(deltas) == count and sum(deltas) == duration, 'media duration disagrees with decode timing')
    offsets = [0]*count; composition = reader.one(table, b'ctts', optional=True)
    if composition is not None:
        require(picture, 'audio has unexpected composition offsets')
        values, rows = reader.table(composition, 8, count, versions=(0, 1)); offsets = []
        for n in range(rows):
            repeat, offset = struct.unpack_from('>Ii' if values[0] else '>II', values, 8+8*n)
            require(repeat > 0 and len(offsets)+repeat <= count, 'composition timing runs are invalid')
            offsets.extend([offset]*repeat)
        require(len(offsets) == count, 'composition timing has missing samples')
    keys = reader.one(table, b'stss', optional=True); sync = set(range(1, count+1))
    if keys is not None:
        require(picture, 'audio has unexpected sync samples')
        values, rows = reader.table(keys, 4, count); ordered = list(struct.unpack_from('>'+str(rows)+'I', values, 8))
        require(ordered == sorted(set(ordered)) and ordered[0] == 1 and ordered[-1] <= count, 'sync sample indices are invalid')
        sync = set(ordered)
    position = 0; pts = []
    for delta, offset in zip(deltas, offsets):
        pts.append(position+offset); position += delta
    edit = reader.one(entries, b'edts', optional=True); media_start = 0; presented = track_duration
    if edit is not None:
        edits = reader.children(edit, (b'elst',)); values = reader.payload(reader.one(edits, b'elst'))
        require(len(values) >= 8 and values[0] in (0, 1) and values[1:8] == b'\0\0\0\0\0\0\1', 'edit list is unsupported')
        require(len(values) == (28 if values[0] else 20), 'edit list length is invalid')
        presented, media_start, speed = struct.unpack_from('>Qqi' if values[0] else '>Iii', values, 8)
        require(media_start >= 0 and speed == 65536 and presented == track_duration, 'presentation edit is invalid')
    if picture:
        num, den = planned['frame_rate']['num'], planned['frame_rate']['den']
        require(count == planned['frames'] and rate == num and all(delta == den for delta in deltas), 'video rate or frame count disagrees with the request')
        require(sorted(pts) == [media_start+n*den for n in range(count)], 'video presentation has gaps or repeated frames')
        require(presented*num == count*den*movie_rate, 'video edit changes exact picture duration')
    else:
        samples = planned['audio_samples']
        require(edit is not None and rate == 48000 and media_start == 1024 and all(delta == 1024 for delta in deltas), 'AAC priming or sample timing is incorrect')
        require(0 <= duration-media_start-samples < 1024, 'AAC padding does not match the requested samples')
        require(presented == (samples*movie_rate+24000)//48000, 'audio edit changes the exact sample endpoint')
    small = reader.one(table, b'stco', optional=True); large = reader.one(table, b'co64', optional=True)
    require((small is None) != (large is None), 'requires exactly one chunk offset table')
    values, chunks = reader.table(small or large, 4 if small else 8, count)
    starts = list(struct.unpack_from('>'+str(chunks)+('I' if small else 'Q'), values, 8))
    values, rows = reader.table(reader.one(table, b'stsc'), 12, chunks)
    mapping = [struct.unpack_from('>III', values, 8+12*n) for n in range(rows)]
    require(mapping[0][0] == 1 and all(1 <= first <= chunks and 1 <= amount <= count and description_id == 1
            for first, amount, description_id in mapping) and all(a[0] < b[0] for a, b in zip(mapping, mapping[1:])), 'chunk mapping is invalid')
    spans = []; coded = []; sample = 0; rule = 0; nal_count = 0
    for chunk, start in enumerate(starts, 1):
        while rule+1 < len(mapping) and mapping[rule+1][0] <= chunk:
            rule += 1
        amount = mapping[rule][1]; end_sample = sample+amount
        require(end_sample <= count, 'chunk mapping has excessive samples')
        for index in range(sample, end_sample):
            end = start+lengths[index]
            require(mdat[1] <= start < end <= mdat[2], 'coded sample lies outside media data')
            if picture:
                at = start; has_picture = False; idr = False
                while at < end:
                    require(end-at >= 5 and nal_count < 1_000_000, 'NAL framing is truncated or excessive')
                    length = struct.unpack('>I', reader.read(at, 4))[0]; at += 4
                    require(0 < length <= end-at, 'NAL length exceeds its sample')
                    header_byte = reader.read(at, 1)[0]; kind = header_byte & 31
                    require(header_byte & 128 == 0 and kind in (1, 5, 6, 7, 8, 9, 12), 'NAL type is unsupported')
                    has_picture |= kind in (1, 5); idr |= kind == 5; nal_count += 1; at += length
                require(has_picture and ((index+1 in sync) == idr), 'coded picture and sync metadata disagree')
            coded.append([start, lengths[index], pts[index], index+1 in sync] if picture else [start, lengths[index]])
            spans.append((start, end)); start = end
        sample = end_sample
    require(sample == count, 'chunk mapping omits coded samples')
    return name, {'track_id': identity, 'coded_samples': count, 'media_timescale': rate, 'media_duration': duration,
        'media_start': media_start, 'presentation_duration': presented, 'coded_bytes': sum(lengths),
        'configuration_sha256': config_hash, 'nal_count': nal_count if picture else None,
        'sample_frames': None if picture else planned['audio_samples']}, spans, {'samples': coded, 'config': list(codec)}


def inspect(path, planned, *, deadline, cancelled=lambda: False, decode_manifest=False):
    require(isinstance(planned, dict), 'expected output is invalid')
    size = planned.get('encoded_size'); rate = planned.get('frame_rate', {})
    require(isinstance(size, list) and len(size) == 2 and all(integer(n, 2, 32768) and n % 2 == 0 for n in size), 'expected dimensions are invalid')
    require(integer(planned.get('frames'), 1, 600) and size[0]*size[1] <= 16777216
            and size[0]*size[1]*planned['frames'] <= 552960000, 'expected frame budget is invalid')
    require(isinstance(rate, dict) and integer(rate.get('num'), 1, 2147483647) and integer(rate.get('den'), 1, 4294967295)
            and rate['den'] <= rate['num'] <= 240*rate['den'], 'expected frame rate is invalid')
    require(planned.get('audio_samples') is None or integer(planned['audio_samples'], 1, 33554432), 'expected audio sample count is invalid')
    planned = {**planned, 'audio_samples': planned.get('audio_samples')}
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and 16 <= before.st_size <= MAX_BYTES, 'requires a bounded regular file')
            reader = Reader(stream, before.st_size, deadline, cancelled)
            top = reader.boxes(0, before.st_size)
            require(all(box[0] in (b'ftyp', b'moov', b'free', b'mdat') for box in top), 'contains an unsupported top-level box')
            ftyp = reader.one(top, b'ftyp'); moov = reader.one(top, b'moov'); mdat = reader.one(top, b'mdat')
            require(ftyp[3] == 0 and moov[2] <= mdat[3], 'metadata is not before media data')
            require(moov[2]-moov[1] <= MAX_METADATA, 'movie metadata exceeds its byte budget')
            require(all(box[2]-box[1] <= MAX_METADATA for box in top if box[0] == b'free'), 'padding exceeds its byte budget')
            brands = reader.payload(ftyp)
            require(8 <= len(brands) <= 256 and len(brands) % 4 == 0 and brands[:4] == b'isom', 'file brand is unsupported')
            metadata = reader.children(moov, (b'mvhd', b'trak', b'udta'))
            user = reader.one(metadata, b'udta', optional=True)
            if user is not None:
                tags = reader.children(user, (b'\xa9too',))
                tag = reader.payload(reader.one(tags, b'\xa9too'))
                require(4 <= len(tag) <= 256 and struct.unpack_from('>H', tag)[0] == len(tag)-4,
                        'encoder metadata is malformed')
            movie_rate, movie_duration = time_header(reader.payload(reader.one(metadata, b'mvhd')), movie=True)
            tracks = [box for box in metadata if box[0] == b'trak']
            require(len(tracks) == (1 if planned.get('audio_samples') is None else 2), 'track count disagrees with the request')
            reports = {}; spans = []; coded = {}
            for box in tracks:
                name, report, used, samples = track(reader, box, movie_rate, planned, mdat)
                require(name not in reports and report['track_id'] not in [row['track_id'] for row in reports.values()], 'has duplicate track identities or handlers')
                reports[name] = report; spans.extend(used); coded[name] = samples
            require('video' in reports and movie_duration == max(row['presentation_duration'] for row in reports.values()), 'movie duration disagrees with its tracks')
            require(len(spans) <= MAX_SAMPLES, 'aggregate sample count exceeds its budget')
            at = mdat[1]
            for start, end in sorted(spans):
                require(start == at, 'coded bytes overlap or leave unclaimed media data'); at = end
            require(at == mdat[2], 'media data has an unclaimed tail')
            digest = hashlib.sha256(); at = 0
            while at < before.st_size:
                block = reader.read(at, min(1<<20, before.st_size-at)); digest.update(block); at += len(block)
            after = os.fstat(stream.fileno())
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'changed during inspection')
            result = {'bytes': before.st_size, 'sha256': digest.hexdigest(), 'movie_timescale': movie_rate,
                    'movie_duration': movie_duration, 'tracks': reports, 'container_timing_verified': True,
                    'sample_tables_verified': True, 'avc_nal_framing_verified': True, 'complete_decode_verified': False}
            if decode_manifest:
                result['decode_manifest'] = {'schema': 1, 'width': size[0], 'height': size[1], 'frames': planned['frames'],
                    'rate_num': rate['num'], 'rate_den': rate['den'], 'media_start': reports['video']['media_start'],
                    'media_begin': mdat[1], 'media_end': mdat[2], 'avcc': coded['video']['config'],
                    'video': coded['video']['samples'], 'audio': coded.get('audio', {}).get('samples', []),
                    'audio_frames': planned['audio_samples']}
            return result
    except OSError as error:
        raise ValueError('Animate MP4 cannot read its owned output') from error
