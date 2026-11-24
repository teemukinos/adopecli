#!/usr/bin/env python3
"""Generate a source-bound operation inventory without running production engines.

Registration, hosted admission, installed availability and release qualification
are different facts. This inventory records the first two; it never infers the
last two from source code or from the existence of a check script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

# Adapter-specific descriptions point to the complete parameter validators.
# These describe bounded routes, not all features of the upstream application.
PROFILES = {
    'vector': ('vector', 'README.md', 'Named rectangles, ellipses, polygons and text; text or geometry revisions', '.vectorcraft; SVG and PNG'),
    'photo': ('image', 'README.md', 'Imported 8-bit images; bounded adjustment and resize', '.pcraft; PNG'),
    'image_layers': ('image', 'README.md', 'Named solid, embedded asset and text layers; controlled revisions', '.pcraft; PNG'),
    'video': ('video', 'VIDEO.md', 'Typed timeline, imported project assets, named clip and title revisions', '.fcproj; MP4'),
    'motion': ('motion', 'MOTION.md', 'Typed layers and property/keyframe revisions', '.ecproj; PNG frames and MP4'),
    'audio': ('audio', 'README.md', 'Owned audio tracks, clip placement, gain and fades', '.scraft; WAV'),
    'photo_library': ('photo', 'README.md', 'Owned photo library and bounded development edits; DNG profile', 'Native library and owned originals; PNG'),
    'pdf': ('pdf', 'PDF.md', 'Bounded static PDF creation, import, merge, extraction and edits', 'PDF; inspection and previews'),
    'layout': ('layout', 'LAYOUT.md', 'Admitted page/story/image models; bounded IDML interchange', '.designcraft; PDF, IDML and PNG previews'),
    'interface': ('interface', 'INTERFACE.md', 'Admitted interface documents and named edits', '.figcraft; inspection and previews'),
    'animate': ('animate', 'README.md', 'Admitted native animation and explicit export profiles', '.anicraft; profile-specific raster/video exports'),
    'texture': ('texture', 'TEXTURE.md', 'Texture creation, edits, export, CPU preview, baking and material handoff', 'Native texture project; PNG and handoff artifacts'),
    'material': ('material', 'MATERIAL.md', 'Bounded material source, evaluation, maps and CPU previews', 'Portable material project; maps and preview'),
    'write': ('write', 'WRITE.md', 'Receipt-bound document models, edits and portable originals', '.dobewrite; PNG and PDF'),
    'slides': ('slides', 'SLIDES.md', 'Admitted presentations, precise edits and explicit engine migration', '.dobeslides; PNG and PDF'),
    'cad': ('cad', 'CAD.md', 'Admitted drawing/panel models, solver, solid and explicit migration', '.dobecad; OBJ'),
    'sheets': ('sheets', 'SHEETS.md', 'Typed cells, bounded formulas, recalculation and edits', '.dobesheets; CSV and HTML'),
    'inspection': ('inspect', 'INSPECT.md', 'Explicitly authorized native/WASM/JavaScript analysis; annotations, no target execution', '.dobeinspect; JSON and HTML'),
    'construction': ('construction', 'CONSTRUCTION.md', 'Editable compositions and explicit Blender/Rive supporting profiles', 'Recipe and profile-specific editable sources/exports'),
    'production': ('production', 'CONSTRUCTION.md', 'Bounded Blender product scenes; material/light revisions preserve composition', '.blend and recipe; PNG'),
    'synthesis': ('synthesis', 'CONSTRUCTION.md', 'Explicitly provisioned offline SDXL generation and masked editing; macOS CPU/MPS only', 'Raster PNG and recipe; no editable 3D scene'),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('inventory input must be a regular file: ' + path.relative_to(ROOT).as_posix())
    data = path.read_bytes()
    if len(data) != path.stat().st_size:
        raise ValueError('inventory input changed during reading')
    return data


def fingerprints():
    inputs = {Path(__file__).resolve(), ROOT / 'craft/engines/catalog.sources.json', ROOT / 'craft/hosted/studio_hosted/operations.py'}
    inputs.update((ROOT / 'craft/runtime/studio_runtime').glob('*.py'))
    inputs.update((ROOT / 'craft/runtime').glob('*.md'))
    inputs.update((ROOT / 'craft/engines').glob('*.lock.json'))
    inputs.update((ROOT / 'craft/engines').glob('*.patch'))
    return {path.relative_to(ROOT).as_posix(): digest(read(path)) for path in sorted(inputs)}


def generate():
    hashes = fingerprints()
    sys.path.insert(0, str(ROOT / 'craft/runtime'))
    sys.path.insert(0, str(ROOT / 'craft/hosted'))
    from studio_runtime import capabilities
    from studio_hosted import operations as hosted

    local = capabilities.OPERATIONS
    if len(set(local)) != len(local) or len(set(hosted.OPERATIONS)) != len(hosted.OPERATIONS):
        raise ValueError('duplicate operation registration')
    if set(hosted.OPERATIONS) - set(local) != {'project.import'}:
        raise ValueError('update the explicit hosted-only operation contract')
    catalog_path = ROOT / 'craft/engines/catalog.sources.json'
    entries = json.loads(read(catalog_path))['applications']
    catalog = {entry['application']: entry for entry in entries}
    if len(catalog) != len(entries):
        raise ValueError('duplicate native family')
    groups, rows, used = {}, [], set()
    for operation in local:
        adapter = capabilities.adapter(operation)
        key = adapter.__name__.rsplit('.', 1)[-1]
        if key not in PROFILES:
            raise ValueError('operation has no documented profile: ' + operation)
        family, document, scope, artifacts = PROFILES[key]
        used.add(key)
        module = Path(adapter.__file__).resolve().relative_to(ROOT).as_posix()
        contract = 'craft/runtime/' + document
        if not (ROOT / contract).is_file() or not callable(adapter.validate):
            raise ValueError('operation lacks a readable contract or parameter validator')
        identity = capabilities.engine_identity(operation)
        row = {'operation': operation, 'family': family, 'adapter': module,
               'parameter_validator': module + ':validate', 'contract': contract,
               'scope': scope, 'deliverables': artifacts, 'engine': identity,
               'local_registered': True, 'hosted_admitted': operation in hosted.OPERATIONS,
               'installed_availability': 'query_the_installed_package',
               'release_qualification': 'not_established_by_this_inventory'}
        if family in catalog:
            entry = catalog[family]
            lock_path = ROOT / 'craft/engines' / entry['maintained_lock']
            lock_bytes = read(lock_path)
            lock = json.loads(lock_bytes)
            if (lock['engine_version'] != identity['version']
                    or lock['source']['revision'] != entry['source_revision']
                    or lock['source']['url'] != entry['upstream_url']):
                raise ValueError('catalog, lock and adapter identity differ: ' + family)
            patch = ROOT / 'craft/engines' / lock['patch']['file']
            if digest(read(patch)) != lock['patch']['sha256']:
                raise ValueError('maintained patch differs from source lock: ' + family)
            binding = getattr(adapter, 'binding', None)
            if binding is not None and binding.PIN['source_lock_sha256'] != digest(lock_bytes):
                raise ValueError('runtime binding differs from source lock: ' + family)
            row['source'] = {'url': entry['upstream_url'], 'revision': entry['source_revision'],
                             'lock': lock_path.relative_to(ROOT).as_posix(), 'lock_sha256': digest(lock_bytes)}
        rows.append(row)
        group = groups.setdefault(family, {'family': family, 'engine': identity, 'operations': []})
        if group['engine'] != identity:
            raise ValueError('family has inconsistent engine versions')
        group['operations'].append(operation)
    if used != set(PROFILES) or set(catalog) != set(groups) - {'construction', 'production', 'synthesis'}:
        raise ValueError('documented profiles and native catalog no longer match operation routing')
    if capabilities.write.binding.PDF_LOCK_SHA256 != digest(read(ROOT / 'craft/engines/pdf.lock.json')):
        raise ValueError('document PDF dependency differs from source lock')

    if hashes != fingerprints():
        raise ValueError('source changed while generating the capability inventory')
    value = {'schema_version': 1, 'product': 'A dope CLI', 'basis': 'current_source_registration',
             'native_families': len(catalog), 'local_operations': len(rows),
             'hosted_operations': len(hosted.OPERATIONS), 'families': list(groups.values()),
             'operations': rows, 'hosted_only': [{'operation': 'project.import',
                 'contract': 'craft/hosted/README.md', 'scope': 'Isolated portable project import',
                 'release_qualification': 'not_established_by_this_inventory'}],
             'source_files': hashes, 'source_sha256': digest(json.dumps(hashes, sort_keys=True).encode()),
             'qualification': {'engines_executed': False, 'installed_package_verified': False,
                 'macos_release_qualified': False, 'linux_release_qualified': False,
                 'supabase_deployment_verified': False, 'visual_acceptance': False}}
    lines = ['# A dope CLI operation inventory', '',
             'Generated by `python3 -B craft/capability_inventory.py`. Run with `--check` to reject stale inventory.', '',
             f"Current source registers **{len(rows)} local operations** across **{len(catalog)} native application families** and three additional production profiles. "
             f"Hosted admission explicitly allows **{len(hosted.OPERATIONS)} operations**, including portable project import.", '',
             'These are source contracts, not installed availability or release qualification. '
             'Query the actual package for availability. Never infer Linux, Supabase, clean-machine or visual acceptance from registration.', '',
             'Inputs, revision preconditions and bounds are defined by each linked parameter validator and contract. '
             'Deliverables depend on the selected operation and profile; an inspection operation need not render every listed format.', '',
             '| Family / version | Registered operations | Hosted admission | Contract and deliverables |',
             '| --- | --- | --- | --- |']
    for family, group in groups.items():
        selected = [r for r in rows if r['family'] == family]
        descriptions = list(dict.fromkeys((r['contract'], r['deliverables']) for r in selected))
        contracts = '; '.join(f"[Contract]({p.removeprefix('craft/')}) — {artifacts}" for p, artifacts in descriptions)
        hosted_names = [r['operation'] for r in selected if r['hosted_admitted']]
        lines.append('| ' + family + ' / ' + group['engine']['version'] + ' | '
                     + ', '.join('`' + op + '`' for op in group['operations']) + ' | '
                     + (', '.join('`' + op + '`' for op in hosted_names) or 'Not admitted') + ' | ' + contracts + ' |')
    lines += ['', 'Hosted-only `project.import` has its own portable import contract (`craft/hosted/README.md`, not part of the open-source tree).', '',
              'Exact operation-to-validator mappings, native source revisions, lock hashes and the complete source fingerprint are in '
              '[CAPABILITIES.json](CAPABILITIES.json). Source changes require regeneration and new qualification of affected routes.', '',
              'The source inventory does not alter the installed preview, enable models, widen the hosted allowlist or clear release gates. '
              'See [qualification and historical evidence](QUALIFICATION.md).', '']
    document = '\n'.join(lines)
    value['documentation_sha256'] = digest(document.encode())
    return json.dumps(value, indent=2) + '\n', document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Read only; fail if either generated inventory differs')
    args = parser.parse_args()
    outputs = dict(zip(('CAPABILITIES.json', 'CAPABILITIES.md'), generate()))
    for name, content in outputs.items():
        path = ROOT / 'craft' / name
        if path.is_symlink():
            raise ValueError('refusing an inventory symlink')
        if args.check:
            if not path.is_file() or read(path).decode() != content:
                raise ValueError('stale capability inventory: ' + name)
        else:
            path.write_text(content)
    print(json.dumps({'checked' if args.check else 'generated': list(outputs), 'engines_executed': False, 'network': False}))


if __name__ == '__main__':
    main()
