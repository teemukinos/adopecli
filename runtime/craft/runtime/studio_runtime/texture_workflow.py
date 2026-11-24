"""Prepare Texture revisions with native agreement and cold preservation.

Only this module selects private engine commands. Input documents cannot choose
paths, executables, preset files or commands. The durable worker owns publication.
This is bounded local execution, not a hostile-process sandbox.
"""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time

from PIL import Image

from . import animate_format, texture_archive, texture_document as document, texture_images, texture_mesh
from .animate_process import run
from .texture_structure import require, integer

VERSION = '0.6.1'
MAX_EXPORT_PIXELS = 33_554_432
MAX_EXPORT_BYTES = 128 << 20
EXPORT_OPTIONS = {'preset': 'Document channels + Normal + AO', 'format': 'png', 'bitDepth': 8, 'padding': 'none'}


def owned(root, path):
    path = Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError('Texture paths must stay inside the attempt') from error
    require(relative.parts and '..' not in relative.parts, 'Texture path must name an attempt descendant')
    current = root
    for part in relative.parts:
        current /= part
        require(not current.is_symlink(), 'Texture paths cannot contain symbolic links')
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Engine:
    def __init__(self, executable, root, *, seconds=120, cancelled=lambda: False):
        self.executable = str(Path(executable).resolve(strict=True))
        self.root = Path(root).resolve(strict=True)
        self.deadline = time.monotonic() + seconds
        self.cancelled = cancelled
        self.calls = 0
        require(self.invoke('--version').strip() == ('dobe-texture ' + VERSION).encode(),
                'Texture requires the maintained engine version')

    def invoke(self, *arguments):
        self.calls += 1
        try:
            return run([self.executable, *map(str, arguments)], self.root, deadline=self.deadline,
                       cancelled=self.cancelled, stdout_limit=16 << 20, stderr_limit=1 << 20,
                       file_limit=texture_archive.MAX_ARCHIVE)
        except ValueError as error:
            raise ValueError(str(error).replace('Animate native', 'Texture native')) from error

    def value(self, *arguments):
        return animate_format.strict_json(self.invoke(*arguments), max_items=500_000)

    def command(self, source, command, parameters):
        require(command in ('resource.list', 'export.plan', 'file.exportTextures'), 'Texture private command is not qualified')
        return self.value('run', owned(self.root, source), command, json.dumps(parameters, allow_nan=False))

    def observe(self, source, profile):
        info = self.value('info', owned(self.root, source))
        require(type(info) is dict and info.get('kind') == 'project', 'Texture native inspection is malformed')
        project = profile['structure']['project']
        require(info.get('project') == project['name'] and info.get('mesh', {}).get('source') == project['mesh'],
                'Texture native project identity disagrees with source')
        actual_sets = info.get('textureSets')
        require(type(actual_sets) is list and len(actual_sets) == len(project['texture_sets']),
                'Texture native texture-set inventory disagrees with source')
        for index, (actual, expected) in enumerate(zip(actual_sets, project['texture_sets'])):
            require(type(actual) is dict and actual.get('index') == index and actual.get('name') == expected['name']
                    and actual.get('resolution') == expected['resolution'], 'Texture native texture set changed')
        meshes = profile['meshes']
        primary = [item for item in meshes['members'].values() if item['role'] == 'primary']
        mesh = texture_mesh.check_native(primary[0], info) if primary else None
        bake = texture_mesh.check_native_bake(meshes, info)
        resources = texture_images.check_native_resources(profile['resources'], self.command(source, 'resource.list', {}))
        return {'mesh': mesh, 'bake_meshes': bake, 'resources': resources, 'uv_report': info.get('uv')}

    def save(self, source, target):
        source = owned(self.root, source); target = owned(self.root, target)
        require(not target.exists(), 'Texture native save destination already exists')
        recipe = target.with_suffix('.recipe.json')
        require(not recipe.exists(), 'Texture native save recipe already exists')
        recipe.write_text(json.dumps({'open': str(source), 'steps': [], 'save': str(target)}) + '\n')
        reply = self.value('batch', recipe)
        require(type(reply) is dict and reply.get('failed') is None and reply.get('completed') == 0,
                'Texture native save did not complete without recovery')
        return document.read_native(target)


def mapping(profile):
    structure = profile['structure']
    return {'texture_sets': [{'index': i, 'name': item['name'], 'material': item['material']}
                             for i, item in enumerate(structure['project']['texture_sets'])],
            'objects': [{'id': identity, **item} for identity, item in sorted(structure['ids'].items())]}


def admission(profile, *, accept_generated_uvs=False):
    require(type(accept_generated_uvs) is bool, 'Texture generated UV acceptance must be boolean')
    require(not profile['project_semantics']['missing_defaults'],
            'Texture import requires explicit conversion of missing project defaults before native execution')
    generated = any(item['requires_generated_uv_acceptance'] for item in profile['meshes']['members'].values())
    require(not generated or accept_generated_uvs, 'Texture mesh requires explicit acceptance of generated UVs')
    return {'generated_uvs_accepted': generated and accept_generated_uvs,
            'default_conversion': False, 'path_replay_authorized': False, 'linked_cooking_authorized': False}


def exported(engine, source, profile, directory):
    """Export fixed document maps; check native planning before pixel allocation."""
    directory = owned(engine.root, directory)
    require(not directory.exists(), 'Texture export directory already exists')
    plan = engine.command(source, 'export.plan', EXPORT_OPTIONS)
    require(type(plan) is list and 0 < len(plan) <= 256, 'Texture map export count is outside its budget')
    names = set(); pixels = 0; tile_positions = {}; dimensions = {}
    for item in plan:
        require(type(item) is dict and not item.get('warnings'), 'Texture export plan reports warnings')
        name = item.get('file'); index = item.get('ts')
        require(type(name) is str and 1 <= len(name) <= 240 and name.endswith('.png') and not name.startswith('.')
                and all(c.isascii() and (c.isalnum() or c in '_.-') for c in name)
                and name.casefold() not in names, 'Texture export filename is unsafe or collides')
        names.add(name.casefold())
        require(integer(index, 0, len(profile['structure']['atlases'])-1) and item.get('format') == 'png'
                and item.get('bitDepth') == 8, 'Texture native export plan changed the requested format')
        atlas = profile['structure']['atlases'][index]
        texture_set = profile['structure']['project']['texture_sets'][index]
        tiles = texture_set.get('uv_tiles') or [None]
        require(integer(item.get('map'), 0, 255), 'Texture export map identity is invalid')
        key = (index, item['map']); position = tile_positions.get(key, 0)
        require(position < len(tiles), 'Texture export plan duplicates a tile')
        tile_positions[key] = position + 1
        dimensions[name] = texture_set.get('tile_resolutions', {}).get(str(tiles[position]), texture_set['resolution'])
        # UDIM maps are per tile. Charge the complete atlas for each planned
        # output conservatively, including holes and unused tile allocation.
        pixels += atlas['width'] * atlas['height']
        require(pixels <= MAX_EXPORT_PIXELS, 'Texture map exports exceed the aggregate pixel budget')
    require(all(count == len(profile['structure']['project']['texture_sets'][index].get('uv_tiles') or [None])
                for (index, _), count in tile_positions.items()), 'Texture export plan omits a tile')
    directory.mkdir()
    reply = engine.command(source, 'file.exportTextures', {**EXPORT_OPTIONS, 'dir': str(directory)})
    expected = {str(directory / item['file']) for item in plan}
    require(type(reply) is dict and not reply.get('warnings') and type(reply.get('files')) is list
            and len(reply['files']) == len(expected) and set(reply['files']) == expected,
            'Texture map export differs from its plan or reports warnings')
    require({str(path) for path in directory.iterdir()} == expected, 'Texture export produced unplanned files')
    records = []; total = 0
    for item in plan:
        path = owned(engine.root, directory / item['file'])
        require(path.is_file() and path.stat().st_size <= MAX_EXPORT_BYTES, 'Texture export is not a bounded regular file')
        data = path.read_bytes(); total += len(data)
        require(total <= MAX_EXPORT_BYTES, 'Texture exports exceed their total byte budget')
        metadata = texture_images.inspect_bytes(data)
        side = dimensions[item['file']]
        require(metadata['format'] == 'PNG' and (metadata['width'], metadata['height']) == (side, side),
                'Texture exported map dimensions disagree with the native project')
        with Image.open(io.BytesIO(data)) as image:
            rgba = image.convert('RGBA').tobytes()
        records.append({'file': item['file'], 'texture_set': item['ts'], 'map': item['map'],
                        'width': side, 'height': side, 'bytes': len(data), 'sha256': digest(data),
                        'pixel_sha256': digest(rgba)})
    return records


def prepare(root, source, destination, executable, *, accept_generated_uvs=False, export_maps=False,
            seconds=120, cancelled=lambda: False):
    root = Path(root).resolve(strict=True)
    source = owned(root, source); destination = owned(root, destination)
    require(not destination.exists() and destination.parent.is_dir(), 'Texture preparation requires a new owned destination')
    require(type(export_maps) is bool, 'Texture export selection must be boolean')
    # Complete source validation and execution admission precede even --version.
    profile = document.read_native(source)
    policy = admission(profile, accept_generated_uvs=accept_generated_uvs)
    with tempfile.TemporaryDirectory(prefix='.texture-prepare-', dir=root) as temporary:
        scratch = Path(temporary); snapshot = scratch / 'source.tcraft'; snapshot.write_bytes(profile['source_bytes'])
        process = Engine(executable, scratch, seconds=seconds, cancelled=cancelled)
        observation = process.observe(snapshot, profile)
        saved_path = scratch / 'saved.tcraft'; saved = process.save(snapshot, saved_path)
        document.check_preservation(profile, saved)
        cold_observation = process.observe(saved_path, saved)
        require(observation == cold_observation, 'Texture native resource or geometry report changes on cold reopen')
        cold = process.save(saved_path, scratch / 'cold.tcraft')
        document.check_preservation(saved, cold)
        maps = []
        if export_maps:
            maps = exported(process, snapshot, profile, scratch / 'warm-maps')
            cold_maps = exported(process, saved_path, saved, scratch / 'cold-maps')
            require(maps == cold_maps, 'Texture cold reopen changes exported map bytes or pixels')
        require(texture_archive.read_bytes(source) == profile['source_bytes'], 'Texture preparation changed original input bytes')
        require(not cancelled() and time.monotonic() < process.deadline, 'Texture preparation cancelled or timed out')
        result = scratch / 'prepared'; (result / 'native').mkdir(parents=True); (result / 'exports').mkdir()
        (result / 'native/source.tcraft').write_bytes(profile['source_bytes'])
        (result / 'native/document.tcraft').write_bytes(saved['source_bytes'])
        objects = mapping(saved)
        (result / 'native/objects.json').write_text(json.dumps(objects, sort_keys=True) + '\n')
        for item in maps:
            target = result / 'exports/maps' / item['file']; target.parent.mkdir(exist_ok=True)
            target.write_bytes((scratch / 'warm-maps' / item['file']).read_bytes())
        report = {'source_sha256': profile['source_sha256'], 'native_sha256': saved['source_sha256'],
                  'inventory': profile['inventory'], 'mapping': objects, 'project': saved['structure']['project'],
                  'execution_policy': policy,
                  'observation': observation, 'maps': maps, 'native_calls': process.calls,
                  'source_bytes_unchanged': True, 'native_state_equal': True, 'native_cold_reopen': True,
                  'export_pixels_equal': True if export_maps else None,
                  'thumbnail_provenance': 'retained imported source preview; not regenerated' if profile['thumbnail'] else None,
                  'visual_approval': False, 'publication_authorized': False}
        (result / 'exports/inspection.json').write_text(json.dumps(report, sort_keys=True) + '\n')
        require(not destination.exists() and not destination.is_symlink(), 'Texture preparation destination appeared during execution')
        result.rename(destination)
    return report
