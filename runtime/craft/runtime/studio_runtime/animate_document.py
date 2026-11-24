"""Whole stored-document admission for the private Animate runtime adapter.

Every admission stage consumes the same bounded byte snapshot. Stored admission
establishes format/graph/property/behavior/media validity. The compound engine
reader additionally checks native preservation and cold-save semantics, with
optional frame/audio/text diagnostics. None authorizes publication or establishes
interactive playback fidelity. No public operation is registered by this module.
"""
import hashlib

from . import animate_animation, animate_behavior, animate_format, animate_graph
from . import animate_media, animate_properties


def inspect_bytes(data, *, inspect_sound=None):
    """Admit one UTF-8 snapshot; the sound inspector is runtime-owned, not input.

    Retain the exact bytes for an owned native handoff instead of reopening the
    original path after admission. Internal graph/path objects are not public
    JSON. Use ``summary`` when persisting diagnostics.
    """
    if not isinstance(data, bytes):
        raise ValueError('Animate document admission requires a byte snapshot')
    envelope, paths = animate_format.decode_envelope(data)
    document = envelope['document']
    graph = animate_graph.inspect_graph(document, paths)
    properties = animate_properties.inspect_static(document, graph)
    animation = animate_animation.inspect_animation(document, graph)
    behavior = animate_behavior.inspect_behavior(document)
    if document.get('sounds') and not callable(inspect_sound):
        raise ValueError('Animate embedded audio requires complete native decoding')
    media = animate_media.inspect_media(document, inspect_sound)
    return {'source_bytes': data, 'source_sha256': hashlib.sha256(data).hexdigest(),
            'envelope': envelope, 'graph': graph, 'properties': properties,
            'animation': animation, 'behavior': behavior, 'media': media}


def read_native(path, *, inspect_sound=None):
    return inspect_bytes(animate_format.read_bytes(path), inspect_sound=inspect_sound)


def read_with_engine(path, executable, root, *, cancelled=lambda: False, seconds=120, frames=(), soundtrack=None, inspect_text=False):
    """Admit, check native state and inspect selected frames/audio without publishing.

    The runtime selects its verified executable and owns ``root``. The native
    comparison covers sanitization and cold serialization. A scratch cold save
    then reconciles every admitted field with native defaults, precision and
    custom deserializer semantics. Original source bytes are never rewritten.
    ``frames`` selects at most 600 distinct zero-based movie frames; optional
    ``soundtrack`` selects inclusive from/to frames and an output sample rate.
    ``inspect_text`` checks every stored text instance, including hidden layers
    and unused symbols. Issues describe substitutions and stale cached geometry;
    the check neither repairs the document nor authorizes its publication.
    """
    from .animate_native_probe import NativeInspector
    if type(inspect_text) is not bool:
        raise ValueError('Animate text inspection option must be boolean')
    data = animate_format.read_bytes(path)
    inspector = NativeInspector(executable, root, cancelled=cancelled, seconds=seconds)
    profile = inspect_bytes(data, inspect_sound=inspector)
    profile['native_state'] = inspector.preservation(profile['source_bytes'])
    profile['native_semantics'] = inspector.reconciliation(profile)
    profile['native_diagnostics'] = inspector.diagnostics(profile, frames=frames, soundtrack=soundtrack)
    if inspect_text:
        profile['native_text'] = inspector.text(profile)
    return profile


def summary(profile):
    """JSON-safe evidence; do not confuse admission with render qualification."""
    graph = profile['graph']; media = profile['media']
    return {'source_sha256': profile['source_sha256'], 'source_bytes': len(profile['source_bytes']),
            'stage': profile['envelope']['document']['stage'],
            'frames': graph['frames'], 'scene_frames': graph['scene_frames'], 'fps': graph['fps'],
            'duration': graph['duration'], 'counts': graph['counts'],
            'requested_fonts': [list(font) for font in sorted(profile['properties']['fonts'])],
            'animation_budget': profile['animation']['budget'],
            'inactive_pose_angles': profile['animation']['inactive_pose_angles'],
            'property_keys_outside_span': profile['animation']['property_keys_outside_span'],
            'behavior': profile['behavior'],
            'media': {'images': [{'id': identity, **item} for identity, item in media['images'].items()],
                      'sounds': [{'id': identity, **item} for identity, item in media['sounds'].items()],
                      'encoded_bytes': media['encoded_bytes'], 'decoded_pixels': media['decoded_pixels'],
                      'decoded_samples': media['decoded_samples'], 'sound_placements': media['sound_placements']},
            'stored_document_admitted': True, 'complete_media_decode_verified': True,
            'native_state': profile.get('native_state'),
            'native_semantics': profile.get('native_semantics'),
            'native_diagnostics': profile.get('native_diagnostics'),
            'native_text': profile.get('native_text'),
            'native_preservation_verified': (
                profile.get('native_state', {}).get('load_sanitization_preserved') is True
                and profile.get('native_state', {}).get('save_load_preserved') is True
                and profile.get('native_semantics', {}).get('source_semantics_preserved') is True),
            'shaped_glyph_coverage_verified': False,
            'evaluation_budget_verified': False, 'render_budget_verified': False,
            'interactive_playback_verified': False, 'publication_authorized': False}
