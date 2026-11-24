"""Cold replay of portable native histories on a disposable copy.

This module does not grant hosted operation admission. Callers must explicitly
select the families qualified for their execution profile. Original artifacts
are never replaced with inspection outputs or a silently migrated native model.
"""
import hashlib
from pathlib import Path
import shutil
import tempfile


FAMILIES = {'write': 'wordcraft', 'slides': 'deckcraft', 'cad': 'cadcraft', 'sheets': 'gridcraft',
            'pdf': 'pdfcraft', 'material': 'materialcraft', 'texture': 'texturecraft',
            'layout': 'designcraft', 'interface': 'figcraft', 'animate': 'anicraft',
            'audio': 'soundcraft', 'photo': 'lightcraft', 'inspect': 'craft-anything', 'video': 'filmcraft', 'motion': 'effectcraft'}
HISTORY_FAMILIES = {'write', 'slides', 'cad', 'sheets'}


def adapters():
    from . import write, slides, cad, sheets, pdf, material, texture, layout, interface, animate, audio, photo_library, inspection, video, motion
    return {'write': write, 'slides': slides, 'cad': cad, 'sheets': sheets,
            'pdf': pdf, 'material': material, 'texture': texture,
            'layout': layout, 'interface': interface, 'animate': animate, 'audio': audio, 'photo': photo_library, 'inspect': inspection, 'video': video, 'motion': motion}


def pdf_deliveries(root, replay_root, declared, result):
    """Compare every delivered PDF/report and every page with native replay."""
    from . import photo
    roles = {'export', 'preview'}
    expected = {entry['path']: entry['role'] for entry in result['artifacts'] if entry['role'] in roles}
    actual = {path: entry['role'] for path, entry in declared.items() if entry['role'] in roles}
    if actual != expected:
        raise ValueError('PDF delivery inventory differs from native replay')
    for path, role in expected.items():
        original, replayed = root/path, replay_root/path
        if role == 'preview':
            from .bundle import png_dimensions
            if (png_dimensions(original) != png_dimensions(replayed)
                    or photo.pixel_hash(original) != photo.pixel_hash(replayed)):
                raise ValueError('PDF page preview differs from native replay')
        elif original.read_bytes() != replayed.read_bytes():
            raise ValueError('PDF delivery differs from native replay')


def audio_deliveries(root, replay_root, declared, result):
    """Require complete source inventory and the entire regenerated mix PCM."""
    from . import audio
    for roles, label in (({'asset'}, 'source'), ({'export', 'preview'}, 'delivery')):
        expected = {entry['path']: entry['role'] for entry in result['artifacts'] if entry['role'] in roles}
        actual = {path: entry['role'] for path, entry in declared.items() if entry['role'] in roles}
        if actual != expected:
            raise ValueError('Audio '+label+' inventory differs from native replay')
        for path in expected:
            if label == 'source':
                if (root/path).read_bytes() != (replay_root/path).read_bytes():
                    raise ValueError('Audio source bytes differ from native replay')
            elif audio.wav_info(root/path, audio.MAX_OUTPUT_SAMPLES) != audio.wav_info(replay_root/path, audio.MAX_OUTPUT_SAMPLES):
                raise ValueError('Audio delivery PCM differs from native replay')


def photo_deliveries(root, replay_root, declared, result):
    """Compare all originals and full-precision PNGs, including color metadata."""
    from . import photo_library
    expected = {entry['path']: entry['role'] for entry in result['artifacts']
                if entry['role'] in ('asset', 'export', 'preview')}
    actual = {path: entry['role'] for path, entry in declared.items()
              if entry['role'] in ('asset', 'export', 'preview')}
    if actual != expected:
        raise ValueError('Photo source/delivery inventory differs from native replay')
    for path, role in expected.items():
        if role == 'asset':
            if (root/path).read_bytes() != (replay_root/path).read_bytes():
                raise ValueError('Photo original source bytes differ from native replay')
        elif photo_library.png_info(root/path) != photo_library.png_info(replay_root/path):
            raise ValueError('Photo delivery pixels or metadata differ from native replay')


def engine_versions(families):
    if (not isinstance(families, (list, tuple)) or any(type(f) is not str for f in families)
            or len(set(families)) != len(families) or set(families) - set(FAMILIES)):
        raise ValueError('explicit supported native replay families required')
    modules = adapters() if families else {}
    return {FAMILIES[family]: modules[family].VERSION for family in families}


def replay(root, manifest, scratch, families, *, authorizations=None):
    """Replay an already bounded, hash-verified extraction with fixed adapters."""
    versions = engine_versions(families)
    identity = manifest['engine']
    if identity['name'] not in versions or identity['version'] != versions[identity['name']]:
        raise ValueError('native replay engine is not admitted for this profile')
    family = next(f for f in families if FAMILIES[f] == identity['name'])
    root, scratch = Path(root), Path(scratch)
    replay_root = scratch/'native-replay'
    replay_root.mkdir(mode=0o700)
    declared = {file['path']: file for file in manifest['files']}
    for path in declared:
        destination = replay_root/path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/path, destination)
    # History-based adapters check the archive, source pin and typed history.
    # PDF instead admits static structure and observes all current editable
    # records and page pixels in two separate native processes.
    # Inspecting the copy may replace reports/recipes there; originals stay intact.
    module = adapters()[family]
    options = {}
    if family == 'pdf':
        from .write_binding import resolve_pdf
        options['executable'] = resolve_pdf()['executable']
    elif family in ('material', 'texture'):
        from .surface_binding import resolve
        options['executable'] = resolve(family)['executable']
    elif family in ('layout', 'interface', 'animate'):
        from .publication_binding import resolve
        options['executable'] = resolve(family)['executable']
        if family == 'layout':
            from .write_binding import resolve_pdf
            options['pdf_executable'] = resolve_pdf()['executable']
    if family == 'audio':
        from .media_binding import resolve_audio
        options['executable'] = resolve_audio()['executable']
        result = module.observe(replay_root, replay_backups=True, **options)
    elif family == 'photo':
        from .media_binding import resolve_photo
        result = module.observe(replay_root, executable=resolve_photo()['executable'])
    elif family in ('video', 'motion'):
        from . import media_binding, media_decoders
        media_decoders.resolve()
        result = module.observe(replay_root, executable=getattr(media_binding, 'resolve_'+family)()['executable'])
    elif family == 'inspect':
        from .inspect_bundle import admit
        result = module.execute(replay_root, 'inspect.inspect', admit(authorizations))
    else:
        result = module.execute(replay_root, family+'.inspect', {}, **options)
    validation = result.get('validation')
    required = ('passed', 'native_cold_reopen', 'native_model_equal', 'initial_source_preserved')
    if family == 'pdf':
        required = ('passed', 'native_cold_reopen', 'pixel_roundtrip_equal',
                    'static_structure_admitted', 'document_scripts_disabled',
                    'source_bytes_unchanged', 'untargeted_page_pixels_verified')
    elif family in ('video', 'motion'):
        required = ('passed', 'native_cold_reopen', 'native_state_equal', 'native_unchanged_on_reopen',
                    'portable_media_verified', 'sampled_cold_reopen_equal', 'glyph_coverage_verified')
    elif family == 'inspect':
        required += ('native_report_replayed', 'annotation_history_replayed', 'profile_admission_complete')
    elif family == 'photo':
        required = ('passed', 'native_cold_reopen', 'native_state_equal', 'pixel_roundtrip_equal',
                    'source_hashes_preserved', 'editable_photo_ids_and_history_preserved')
    elif family == 'audio':
        required = ('passed', 'native_cold_reopen', 'native_state_equal', 'pcm_roundtrip_equal',
                    'editable_audio_unchanged_on_reopen', 'source_audio_hashes_preserved', 'retained_backups_observed')
    elif family == 'material':
        required += ('source_members_equal',)
    elif family == 'texture':
        required = ('passed', 'native_cold_reopen', 'native_state_equal',
                    'source_bytes_unchanged', 'native_resource_geometry_agreement')
    elif family in ('layout', 'interface', 'animate'):
        required = ('passed', 'native_cold_reopen', 'native_state_equal', 'source_bytes_unchanged')
        if family == 'layout':
            required += ('pixel_roundtrip_equal', 'idml_pixel_roundtrip_equal',
                         'exact_bundled_fonts', 'independent_pdf_validation')
        elif family == 'interface':
            required += ('pixel_roundtrip_equal',)
        else:
            required += ('selected_preview_pixels_equal',)
    if (not isinstance(validation, dict)
            or any(validation.get(key) is not True for key in required)
            or result.get('engine', {}).get('name') != identity['name']
            or result['engine'].get('version') != identity['version']):
        raise ValueError('complete native replay did not pass')
    native = {entry['path'] for entry in result['artifacts'] if entry['role'] == 'native'}
    if native != {path for path, entry in declared.items() if entry['role'] == 'native'}:
        raise ValueError('bundle native inventory differs from the complete replay')
    for path in native:
        data = (replay_root/path).read_bytes()
        if len(data) != declared[path]['bytes'] or hashlib.sha256(data).hexdigest() != declared[path]['sha256']:
            raise ValueError('native replay changed the imported editable state')
    observations = []
    retained_source = None
    inspection_validation = {}
    if family in ('write', 'slides'):
        # Their ordinary inspect routes cold-open baseline/current and validate
        # the typed history in Python. Import additionally observes every native
        # intermediate so a state later edited away is not skipped.
        history_root = scratch/'history'
        history_root.mkdir(mode=0o700)
        checked = module.project.inspect_bytes((replay_root/('native/project.dobe'+family)).read_bytes())
        engine_module = module.write_engine if family == 'write' else module.slides_engine
        engine = engine_module.Engine(root=history_root, **module.binding.resolve())
        state = checked['members']['baseline.json']
        for index, entry in enumerate(checked['manifest']['history']):
            state = module.revision.revise_bytes(state, entry['before'], entry['edits'])['data']
            if hashlib.sha256(state).hexdigest() != entry['after']:
                raise ValueError('portable native history differs from its exact chain')
            path = history_root/f'state-{index}.json'
            path.write_bytes(state)
            observed = engine.observe(path, state)
            if observed.get('complete_model_equal') is not True or path.read_bytes() != state:
                raise ValueError('native history model differs from its portable state')
            observations.append({'index': index, 'sha256': entry['after']})
        if state != checked['members']['document.json']:
            raise ValueError('portable history does not reach its imported current state')
    if family == 'inspect':
        from .inspect_bundle import deliveries
        inspection_validation = deliveries(root, replay_root, declared)
    elif family in ('video', 'motion'):
        from .movie_replay import deliveries
        inspection_validation = deliveries(root, replay_root, declared, result, family)
    elif family == 'audio':
        audio_deliveries(root, replay_root, declared, result)
    elif family == 'photo':
        photo_deliveries(root, replay_root, declared, result)
    elif family == 'pdf':
        pdf_deliveries(root, replay_root, declared, result)
    elif family == 'texture':
        # The ordinary inspect preserves the retained original without opening
        # it. Portable replay also admits and cold-opens that archive. Embedded
        # recipes cannot grant consent for generated UVs or linked execution.
        with tempfile.TemporaryDirectory(prefix='.source-replay-', dir=replay_root) as temporary:
            source_validation = module.workflow.prepare(
                replay_root, replay_root/'native/source.tcraft', Path(temporary)/'prepared',
                options['executable'], accept_generated_uvs=False)
        if any(source_validation.get(key) is not True for key in
               ('source_bytes_unchanged', 'native_state_equal', 'native_cold_reopen')):
            raise ValueError('Texture retained source did not pass native replay')
        retained_source = {'sha256': source_validation['source_sha256'], 'native_cold_reopen': True}
    elif family == 'animate':
        with tempfile.TemporaryDirectory(prefix='.source-replay-', dir=replay_root) as temporary:
            source_validation = module.project.prepare(
                replay_root, replay_root/'native/source.anicraft', Path(temporary)/'prepared',
                options['executable'])
        if any(source_validation.get(key) is not True for key in
               ('source_bytes_unchanged', 'native_state_equal', 'cold_reopen_equal')):
            raise ValueError('Animate retained source did not pass native replay')
        retained_source = {'sha256': source_validation['source']['source_sha256'], 'native_cold_reopen': True}
    return result['engine'], {
        'native_model_equal': True, 'native_inventory_equal': True,
        'native_history_replayed': family in HISTORY_FAMILIES,
        'initial_source_preserved': family in HISTORY_FAMILIES or family in ('material', 'inspect'),
        'imported_native_bytes_preserved': True,
        'replay_family': family, 'native_replay_validation': validation,
        'additional_native_history_observations': observations,
        'retained_source_replay': retained_source,
        # PDF, Audio, Photo and Inspect replay their current deliveries. History-based
        # profiles do not prove every prior PDF/HTML/OBJ export is equivalent.
        'export_semantics_replayed': family in ('pdf', 'audio', 'photo', 'inspect', 'video', 'motion'), 'visual_approval': False,
        **inspection_validation,
    }
