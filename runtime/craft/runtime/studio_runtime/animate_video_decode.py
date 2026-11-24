"""Bind complete native packet decoding to a qualified owned MP4 container."""
import json
import math
import re

from . import animate_format as format, animate_video_container as container
from . import animate_exports as exports


def inspect(root, movie, planned, checked, native, *, deadline, cancelled):
    manifest = checked.pop('decode_manifest')
    path = root/'decode-manifest.json'
    payload = json.dumps(manifest, separators=(',', ':')).encode()
    if len(payload) > 4 << 20:
        raise ValueError('Animate video decode manifest exceeds its byte budget')
    path.write_bytes(payload)
    raw = native(['inspect-owned-video', str(movie), str(path)], limit=1 << 20)
    result = format.strict_json(raw, max_items=10000)
    keys = {'schema', 'bytes', 'complete_decode_verified', 'decoder', 'threads', 'pictures', 'macroblocks',
            'audio_packets', 'decoded_audio_frames', 'presented_audio_frames', 'audio_fnv1a64', 'audio_peak'}
    if not isinstance(result, dict) or set(result) != keys:
        raise ValueError('Animate video returned an incomplete native decode report')
    audio = checked['tracks'].get('audio')
    expected = {'schema': 1, 'bytes': checked['bytes'], 'threads': 2,
                'macroblocks': ((planned['encoded_size'][0]+15)//16)*((planned['encoded_size'][1]+15)//16)*planned['frames'],
                'audio_packets': audio['coded_samples'] if audio else 0,
                'decoded_audio_frames': audio['coded_samples']*1024 if audio else 0,
                'presented_audio_frames': planned['audio_samples'] or 0}
    if (any(type(result[key]) is not int or result[key] != value for key, value in expected.items())
            or result['complete_decode_verified'] is not True or result['decoder'] != 'native-software-h264-aac'):
        raise ValueError('Animate video native decode counts disagree with the container')

    def checksum(value):
        return isinstance(value, str) and re.fullmatch('[0-9a-f]{16}', value) is not None

    pictures = result['pictures']
    if not isinstance(pictures, list) or len(pictures) != planned['frames']:
        raise ValueError('Animate video native decode omitted pictures')
    for i, row in enumerate(pictures):
        expected_pts = checked['tracks']['video']['media_start']+i*planned['frame_rate']['den']
        if (not isinstance(row, dict) or set(row) != {'pts', 'yuv_fnv1a64'} or type(row['pts']) is not int
                or row['pts'] != expected_pts or not checksum(row['yuv_fnv1a64'])):
            raise ValueError('Animate video native decode changed picture timing or checksums')
    peak = result['audio_peak']
    if (not checksum(result['audio_fnv1a64']) or type(peak) not in (int, float)
            or not math.isfinite(peak) or peak < 0 or not audio and peak != 0):
        raise ValueError('Animate video native decode returned invalid audio evidence')
    # The native decoder reports diagnostic FNV checksums, not file identity.
    # Reinspect and SHA-256 the complete file to bind both passes to unchanged bytes.
    if container.inspect(movie, planned, deadline=deadline, cancelled=cancelled) != checked:
        raise ValueError('Animate video output changed during native decoding')
    if exports.read_output(path, 4 << 20) != payload:
        raise ValueError('Animate video native decoding changed its sample manifest')
    return result
