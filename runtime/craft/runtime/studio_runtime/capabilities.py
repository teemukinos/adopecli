"""Explicit operation routing; arbitrary engine commands are never accepted."""
import shutil
from . import synthesis, production, construction, animate, audio, image_layers, interface, layout, motion, pdf, photo, photo_library, material, texture, vector, video, write, slides, cad, sheets, inspection

OPERATIONS = synthesis.OPERATIONS + production.OPERATIONS + construction.OPERATIONS + vector.OPERATIONS + photo.OPERATIONS + image_layers.OPERATIONS + video.OPERATIONS + motion.OPERATIONS + audio.OPERATIONS + photo_library.OPERATIONS + pdf.OPERATIONS + layout.OPERATIONS + interface.OPERATIONS + animate.OPERATIONS + texture.OPERATIONS + material.OPERATIONS + write.OPERATIONS + slides.OPERATIONS + cad.OPERATIONS + sheets.OPERATIONS + inspection.OPERATIONS
# These adapters write only their attempt directory and never submit paid/provider work.
RETRY_SAFE = frozenset(OPERATIONS)


def engine_identity(operation):
    if operation in synthesis.OPERATIONS:
        return {"name":"open-weight-synthesis","version":synthesis.VERSION}
    if operation in production.OPERATIONS:
        return {"name":"photographic-production","version":production.VERSION}
    if operation in construction.OPERATIONS:
        return {"name":"construction","version":construction.VERSION}
    if operation in inspection.OPERATIONS:
        return {'name': 'craft-anything', 'version': inspection.VERSION}
    if operation in sheets.OPERATIONS:
        return {'name': 'gridcraft', 'version': sheets.VERSION}
    if operation in cad.OPERATIONS:
        return {'name': 'cadcraft', 'version': cad.VERSION}
    if operation in slides.OPERATIONS:
        return {'name': 'deckcraft', 'version': slides.VERSION}
    if operation in write.OPERATIONS:
        return {'name': 'wordcraft', 'version': write.VERSION}
    if operation in material.OPERATIONS:
        return {'name': 'materialcraft', 'version': material.VERSION}
    if operation in texture.OPERATIONS:
        return {'name': 'texturecraft', 'version': texture.VERSION}
    if operation in animate.OPERATIONS:
        return {'name': 'anicraft', 'version': animate.VERSION}
    if operation in interface.OPERATIONS:
        return {'name': 'figcraft', 'version': interface.VERSION}
    if operation in layout.OPERATIONS:
        return {'name': 'designcraft', 'version': layout.VERSION}
    if operation in pdf.OPERATIONS:
        return {'name': 'pdfcraft', 'version': pdf.VERSION}
    if operation in photo_library.OPERATIONS:
        return {'name': 'lightcraft', 'version': photo_library.VERSION}
    if operation in audio.OPERATIONS:
        return {'name': 'soundcraft', 'version': audio.VERSION}
    if operation in vector.OPERATIONS:
        return {'name': 'vectorcraft', 'version': '0.24.1'}
    if operation in photo.OPERATIONS + image_layers.OPERATIONS:
        return {'name': 'photocraft', 'version': '0.23.1'}
    if operation in video.OPERATIONS:
        return {'name': 'filmcraft', 'version': video.VERSION}
    if operation in motion.OPERATIONS:
        return {'name': 'effectcraft', 'version': motion.VERSION}
    raise ValueError('unsupported capability')


def adapter(operation):
    if operation in synthesis.OPERATIONS:
        return synthesis
    if operation in production.OPERATIONS:
        return production
    if operation in construction.OPERATIONS:
        return construction
    if operation in inspection.OPERATIONS:
        return inspection
    if operation in sheets.OPERATIONS:
        return sheets
    if operation in cad.OPERATIONS:
        return cad
    if operation in slides.OPERATIONS:
        return slides
    if operation in write.OPERATIONS:
        return write
    if operation in material.OPERATIONS:
        return material
    if operation in texture.OPERATIONS:
        return texture
    if operation in animate.OPERATIONS:
        return animate
    if operation in interface.OPERATIONS:
        return interface
    if operation in layout.OPERATIONS:
        return layout
    if operation in pdf.OPERATIONS:
        return pdf
    if operation in photo_library.OPERATIONS:
        return photo_library
    if operation in audio.OPERATIONS:
        return audio
    if operation in motion.OPERATIONS:
        return motion
    if operation in video.OPERATIONS:
        return video
    if operation in vector.OPERATIONS:
        return vector
    if operation in photo.OPERATIONS:
        return photo
    if operation in image_layers.OPERATIONS:
        return image_layers
    raise ValueError("unsupported capability")


def validate(operation, parameters, source_revision):
    adapter(operation).validate(operation, parameters, source_revision)


def asset_inputs(operation, parameters):
    if operation in synthesis.OPERATIONS:
        return synthesis.assets(operation, parameters)
    if operation in production.OPERATIONS:
        return production.assets(operation, parameters)
    if operation in construction.OPERATIONS:
        return construction.assets(operation,parameters)
    if operation in inspection.OPERATIONS:
        return inspection.assets(operation, parameters)
    if operation in sheets.OPERATIONS:
        return sheets.assets(operation, parameters)
    if operation in cad.OPERATIONS:
        return cad.assets(operation, parameters)
    if operation in slides.OPERATIONS:
        return slides.assets(operation, parameters)
    if operation in write.OPERATIONS:
        return write.assets(operation, parameters)
    if operation in material.OPERATIONS:
        return material.assets(operation, parameters)
    if operation in texture.OPERATIONS:
        return texture.assets(operation, parameters)
    if operation in animate.OPERATIONS:
        return animate.assets(operation, parameters)
    if operation in interface.OPERATIONS:
        return interface.assets(operation, parameters)
    if operation in layout.OPERATIONS:
        return layout.assets(operation, parameters)
    if operation in pdf.OPERATIONS:
        return pdf.assets(operation, parameters)
    if operation in photo_library.OPERATIONS:
        return photo_library.assets(operation, parameters)
    if operation in audio.OPERATIONS:
        return audio.assets(operation, parameters)
    if operation in motion.OPERATIONS:
        return motion.assets(operation, parameters)
    if operation in video.OPERATIONS:
        return video.assets(operation, parameters)
    if operation == 'image.adjust':
        return {parameters['asset']: 'assets/input'}
    return image_layers.assets(operation, parameters)


def describe(product='studio'):
    if product == 'dobe':
        from . import descriptors
        return {'backend': 'local', 'operations': list(OPERATIONS),
                'image_synthesis': {'operations':list(synthesis.OPERATIONS),'model':synthesis.MODEL,'policy':synthesis.POLICY,'provisioned':synthesis.CONFIG.is_file(),'inference_qualified':False,'gpu_worker_qualified':False,'raster_only':True},
                'photographic_production': {'operations':list(production.OPERATIONS),'profile':production.schema.PROFILE,'policy':production.schema.POLICY,'installed_qualification':False,'visual_approval':False},
                'construction': {'operations':list(construction.OPERATIONS),'general_composition':True,'supporting_profiles':['blender','rive'],'policy':construction.schema.POLICY},
                'applications': {'inspect': {'name': 'Dobe Inspect', 'available': inspection.binding.available(),
                                             'qualification': inspection.source.PROFILE, 'explicit_input_consent_required': True,
                                             'permission_value': 'owned-or-authorized', 'input_sha256_required': True,
                                             'project_scoped_assets_only': True, 'revision_edits_available': True,
                                             'import_formats': ['native','wasm','javascript','dobeinspect'], 'export_formats': ['json','html','dobeinspect'],
                                             'target_execution': False, 'external_reference_resolution': False, 'carries_target_content': True,
                                             'profile_admission_complete': True, 'general_admission_complete': False, 'installed_qualification': False},
                                 'sheets': {'name': 'Dobe Sheets', 'available': sheets.binding.available(),
                                           'qualification': 'cells-and-formulas-v1', 'production_recipes': sheets.recipes.catalog(),
                                           'creation_available': True, 'revision_edits_available': True,
                                           'import_formats': ['json','dobesheets'], 'export_formats': ['dobesheets','csv','html'],
                                           'profile_admission_complete': True, 'general_admission_complete': False,
                                           'direct_xlsx_import_qualified': False, 'pinned_font_rendering_verified': False,
                                           'installed_qualification': False},
                                 'cad': {'name': 'Dobe CAD', 'available': cad.binding.available(),
                                        'qualification': cad.admission.PROFILE, 'production_recipes': cad.catalog(),
                                        'creation_available': True, 'revision_edits_available': True, 'explicit_engine_migration_available': True,
                                        'import_formats': ['json','dobecad'], 'export_formats': ['dobecad','obj'],
                                        'profile_admission_complete': True, 'general_admission_complete': False,
                                        'source_format_fidelity_qualified': False, 'render_qualified': False,
                                        'general_manufacturing_qualified': False, 'installed_qualification': False},
                                 'slides': {'name': 'Dobe Slides', 'available': slides.binding.available(),
                                           'qualification': slides.admission.PROFILE,
                                           'creation_available': True, 'revision_edits_available': True, 'explicit_engine_migration_available': True,
                                           'production_recipes': slides.recipes.catalog(),
                                           'import_formats': ['json', 'deckcraft', 'dobeslides'], 'export_formats': ['dobeslides', 'png', 'pdf'],
                                           'profile_admission_complete': True, 'general_admission_complete': False,
                                           'media_chart_table_import_qualified': False, 'owned_picture_formats': ['png','jpeg'],
                                           'picture_edits': ['picture.insert','picture.replace','picture.crop','shape.transform'],
                                           'direct_pptx_import_qualified': False, 'pptx_precision_report_available': True,
                                           'render_qualified': True, 'delivery_profile': slides.slides_exports.PROFILE, 'pdf_export_requires_bundled_pdf': True, 'source_format_fidelity_qualified': False,
                                           'installed_qualification': False, 'visual_approval': False},
                                 'write': {'name': 'Dobe Write', 'available': write.binding.available(),
                                          'qualification': 'receipt-bound-native-models-and-portable-originals',
                                          'creation_available': True, 'revision_edits_available': True,
                                          'production_recipes': write.recipes.catalog(),
                                          'import_formats': ['json', 'dobewrite'], 'export_formats': ['dobewrite', 'png', 'pdf'],
                                          'direct_docx_import_qualified': False, 'render_qualified': True,
                                          'pdf_export_requires_bundled_pdf': True,
                                          'source_format_fidelity_qualified': False, 'installed_qualification': False,
                                          'visual_approval': False},
                                 'material': {'name': 'Dobe Material', 'available': shutil.which(material.engine()) is not None,
                                             'qualification': 'source-authoring-bounded-evaluation-maps-and-cpu-preview', 'creation_available': True,
                                             'revision_edits_available': True, 'source_preservation': True,
                                             'production_recipes': material.recipes.catalog(), 'portable_material_version':2,
                                             'archived_dependencies_available': True,
                                             'cooking_available': True, 'export_formats': list(material.maps.DEPTHS), 'cpu_preview_available': True,
                                             'installed_qualification': False, 'visual_approval': False},
                                 'texture': {'name': 'Dobe Texture', 'available': shutil.which(texture.engine()) is not None,
                                            'qualification': 'local-development-contract', 'creation_available': True,
                                            'revision_edits_available': True, 'export_formats': ['png'],
                                            'cpu_preview_available': True, 'baking_available': True, 'material_handoff_requires_material_engine':True,
                                            'visual_approval': False},
                                 'animate': {'name': 'Dobe Animate', 'available': shutil.which(animate.engine()) is not None,
                                            'qualification': 'local-development-contract',
                                            'creation_available': True,
                                            'raster_export_formats': list(animate.native_exports.RASTER_FORMATS),
                                            'export_formats': list(animate.native_exports.FORMATS),
                                            'revision_edits_available': True, 'interactive_playback_verified': False,
                                            'visual_approval': False},
                                 'interface': {'name': 'Dobe Interface', 'available': shutil.which(interface.engine()) is not None,
                                              'qualification': 'local-development-contract', 'revision_edits_available': True,
                                              'clipping_verified': False, 'visual_approval': False},
                                 'layout': {'name': 'Dobe Layout',
                                           'available': shutil.which(layout.engine()) is not None and shutil.which(pdf.engine()) is not None,
                                           'qualification': 'local-development-contract', 'general_idml_fidelity_qualified': False},
                                 'pdf': {'name': 'Dobe PDF', 'available': shutil.which(pdf.engine()) is not None,
                                        'qualification': 'local-development-contract', 'static_pdf_only': True,
                                        'general_pdf_fidelity_qualified': False},
                                 'photo': {'name': 'Dobe Photo', 'available': shutil.which(photo_library.engine()) is not None,
                                          'qualification': 'local-development-contract', 'raw_formats': ['dng'],
                                          'general_camera_raw_fidelity_qualified': False},
                                 'image': {'name': 'Dobe Image', 'available': shutil.which(photo.engine()) is not None,
                                          'shaped_font_diagnostics': photo.engine() == 'dobe-image'},
                                 'audio': {'name': 'Dobe Audio', 'available': shutil.which(audio.engine()) is not None,
                                           'qualification': 'local-development-contract'},
                                 'motion': {'name': 'Dobe Motion', 'available': shutil.which(motion.engine()) is not None,
                                            'qualification': 'local-development-contract', 'glyph_coverage_verified': False},
                                 'video': {'name': 'Dobe Video', 'available': shutil.which(video.engine()) is not None,
                                           'qualification': 'local-development-contract', 'glyph_coverage_verified': False},
                                 'vector': {'name': 'Dobe Vector', 'available': shutil.which(vector.engine()) is not None}},
                'execution': 'separate supervisor required', 'production': 'native applications', 'model_inference': False, 'model_inference_qualification_required': True,
                'qualification': 'development-subset',
                'operation_summaries': descriptors.summaries(), 'describe': 'dope describe OPERATION'}
    return {"backend": "local", "operations": list(OPERATIONS),
            "engines": {"craft-anything": inspection.binding.available(),
                        "gridcraft": sheets.binding.available(),
                        "cadcraft": cad.binding.available(),
                        "deckcraft": slides.binding.available(),
                        "wordcraft": write.binding.available(),
                        "materialcraft": shutil.which(material.engine()) is not None,
                        "texturecraft": shutil.which(texture.engine()) is not None,
                        "anicraft": shutil.which(animate.engine()) is not None,
                        "figcraft": shutil.which(interface.engine()) is not None,
                        "designcraft": shutil.which(layout.engine()) is not None and shutil.which(pdf.engine()) is not None,
                        "pdfcraft": shutil.which(pdf.engine()) is not None,
                        "lightcraft": shutil.which(photo_library.engine()) is not None,
                        "vectorcraft": shutil.which(vector.engine()) is not None,
                        "soundcraft": shutil.which(audio.engine()) is not None,
                        "photocraft": shutil.which(photo.engine()) is not None,
                        "filmcraft": shutil.which(video.engine()) is not None,
                        "effectcraft": shutil.which(motion.engine()) is not None},
            "execution": "separate supervisor required", "generation": False, "synthesis": {"operations": list(synthesis.OPERATIONS), "qualification_required": True, "policy": synthesis.POLICY}}


def validate_for_project(store, workspace, project, operation, parameters, source_revision):
    validate(operation, parameters, source_revision)
    for asset in asset_inputs(operation, parameters):
        store.get_asset(workspace, project, asset)
    if source_revision:
        revision = store.get_revision(workspace, source_revision)
        expected = engine_identity(operation)['name']
        if revision["project"] != project or revision["engine"]["name"] != expected:
            raise ValueError("source revision belongs to another project or engine")
