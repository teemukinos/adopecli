"""Closed requests and interpretation of maintained native evaluation reports.

Counts are deterministic work units, not measured memory, CPU time or prices.
Frame reports qualify only the requested static frames. Soundtrack layout covers
the stored movie; mix work and output samples refer to the selected range.
Neither report establishes pixels, audio samples or interactive playback fidelity.
"""
import math

from .animate_graph import fields

EVALUATION_LIMITS = {'timelines': 65536, 'layers': 1_000_000, 'elements': 1_000_000,
    'continuity': 1_000_000, 'bounds': 1_000_000, 'helpers': 20_000_000,
    'items': 32768, 'structures': 32768, 'copy_bytes_reserved': 64 << 20,
    'decoded_pixels': 64_000_000, 'encoded_bytes': 48 << 20}
GEOMETRY_LIMITS = {'path_commands': 2_000_000, 'flatten_points': 2_000_000,
    'morph_steps': 20_000_000, 'sliced_commands': 2_000_000, 'walk_steps': 10_000_000}
SOUND_LIMITS = {'timeline_calls': 100_000, 'layer_visits': 1_000_000,
    'keyframe_visits': 1_000_000, 'element_visits': 1_000_000, 'continuity_steps': 1_000_000,
    'placements': 8192, 'envelope_points': 262144, 'resolution_checks': 2_000_000,
    'decoded_samples': 67_108_864}
MAX_FRAME_REQUESTS = 600
MAX_OUTPUT_FRAMES = 33_554_432
MAX_SAMPLE_WORK = 268_435_456


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Animate ' + label + ' must be an integer within its budget')
    return value


def frame_start(frame, fps, rate):
    # Native uses f64 arithmetic with the stored f32 fps, then round() (ties
    # away from zero). Python round() uses ties to even and is not equivalent.
    value = frame * float(rate) / fps
    whole = math.floor(value)
    return whole + (value - whole >= .5)


def request(profile, frames=(), soundtrack=None):
    total = profile['graph']['frames']
    if not isinstance(frames, (list, tuple)) or len(frames) > MAX_FRAME_REQUESTS:
        raise ValueError('Animate frame diagnostics require at most 600 movie frames')
    frames = [integer(frame, 0, total - 1, 'diagnostic frame') for frame in frames]
    if len(set(frames)) != len(frames):
        raise ValueError('Animate frame diagnostics must not repeat frames')
    audio = None
    if soundtrack is not None:
        fields(soundtrack, (), ('from', 'to', 'rate'), 'soundtrack request')
        first = integer(soundtrack.get('from', 0), 0, total - 1, 'soundtrack first frame')
        last = integer(soundtrack.get('to', total - 1), first, total - 1, 'soundtrack last frame')
        rate = integer(soundtrack.get('rate', 44100), 8000, 192000, 'soundtrack sample rate')
        count = frame_start(last + 1, profile['graph']['fps'], rate) - frame_start(first, profile['graph']['fps'], rate)
        if not 1 <= count <= MAX_OUTPUT_FRAMES:
            raise ValueError('Animate soundtrack exceeds its output-frame budget')
        audio = {'from': first, 'to': last, 'rate': rate}
    return {'frames': frames, 'soundtrack': audio}


def counters(value, limits, label):
    fields(value, limits, (), label)
    for key, maximum in limits.items():
        integer(value[key], 0, maximum, label + ' ' + key)


def frame_report(report, frame, profile):
    fields(report, ('frame', 'items', 'groups', 'clips', 'evaluation', 'geometry',
                    'evaluation_budget_verified', 'render_budget_verified', 'media_integrity_verified',
                    'document_changed'), (), 'frame report')
    integer(report['frame'], frame, frame, 'reported frame')
    for key in ('items', 'groups', 'clips'):
        integer(report[key], 0, 32768, 'reported ' + key)
    counters(report['evaluation'], EVALUATION_LIMITS, 'evaluation work')
    counters(report['geometry'], GEOMETRY_LIMITS, 'geometry work')
    work = report['evaluation']
    encoded_images = sum(item['encoded_bytes'] for item in profile['media']['images'].values())
    if (report['items'] != work['items'] or report['groups'] + report['clips'] != work['structures']
            or work['decoded_pixels'] > profile['media']['decoded_pixels'] or work['encoded_bytes'] > encoded_images
            or report['evaluation_budget_verified'] is not True or report['render_budget_verified'] is not False
            or report['media_integrity_verified'] is not False or report['document_changed'] is not False):
        raise ValueError('Animate native frame report disagrees with its admitted source or qualification scope')
    return report


def soundtrack_report(report, requested, profile):
    fields(report, ('rate', 'from', 'to', 'output_frames', 'voices', 'sample_work', 'layout',
                    'block_voice_checks', 'layout_complete', 'document_changed'), (), 'soundtrack report')
    for key in ('rate', 'from', 'to'):
        integer(report[key], requested[key], requested[key], 'reported soundtrack ' + key)
    expected = frame_start(requested['to'] + 1, profile['graph']['fps'], requested['rate']) - frame_start(
        requested['from'], profile['graph']['fps'], requested['rate'])
    integer(report['output_frames'], expected, expected, 'soundtrack output frames')
    integer(report['voices'], 0, 8192, 'soundtrack voices')
    integer(report['sample_work'], 0, MAX_SAMPLE_WORK, 'soundtrack sample work')
    blocks = ((expected + 65535) // 65536) * report['voices']
    integer(report['block_voice_checks'], blocks, blocks, 'soundtrack block checks')
    counters(report['layout'], SOUND_LIMITS, 'soundtrack layout')
    if (report['voices'] > report['layout']['placements']
            or report['layout']['decoded_samples'] > profile['media']['decoded_samples']
            or report['sample_work'] > 10 * expected * report['voices']
            or report['layout_complete'] is not True or report['document_changed'] is not False):
        raise ValueError('Animate native soundtrack report disagrees with its admitted source or range')
    return report


def interpret(reports, requested, profile):
    count = len(requested['frames']) + (requested['soundtrack'] is not None)
    if not isinstance(reports, list) or len(reports) != count:
        raise ValueError('Animate native diagnostics returned an incomplete batch')
    frames = [frame_report(report, frame, profile) for report, frame in zip(reports, requested['frames'])]
    audio = None
    if requested['soundtrack'] is not None:
        audio = {'report': soundtrack_report(reports[-1], requested['soundtrack'], profile),
                 'expanded_voice_budget_verified': True, 'mix_work_budget_verified': True,
                 'mix_fidelity_verified': False}
    return {'source_sha256': profile['source_sha256'], 'frames': frames, 'soundtrack': audio,
            'all_static_movie_frames_checked': len(frames) == profile['graph']['frames'],
            'aggregate_export_budget_verified': False, 'render_fidelity_verified': False,
            'interactive_playback_verified': False}
