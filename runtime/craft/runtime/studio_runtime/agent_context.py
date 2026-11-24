"""Decision context projections; complete evidence stays in the existing Store."""
import copy


def previews(images):
    """Send byte-identical images once while retaining every sampled frame label."""
    unique = []; by_hash = {}; aliases = {}
    for image in images:
        previous = by_hash.get(image['sha256'])
        if previous is None:
            by_hash[image['sha256']] = image
            unique.append(image)
        else:
            if previous['content'] != image['content']:
                raise ValueError('Identical evidence hashes have different image content')
            aliases[image['path']] = previous['path']
    return unique, aliases


def changes(before, after, path=''):
    """Retain every changed native value, without repeating unchanged snapshots."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            child = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if key not in before:
                result.append({'path': child, 'added': after[key]})
            elif key not in after:
                result.append({'path': child, 'removed': before[key]})
            else:
                result.extend(changes(before[key], after[key], child))
        return result
    return [{'path': path, 'before': before, 'after': after}]


def contract(descriptor, reviewing=False):
    """Remove accounting metadata; select an explicit edit contract when safe."""
    text = descriptor['contract']
    # These are explicit authored sections, not schemas inferred from validators.
    # Scene and interaction edits still need their complete parameter limits.
    markers = {'image': 'image.edit parameters', 'video': 'video.edit ', 'document': 'write.edit '}
    marker = markers.get(descriptor['workflow']) if reviewing else None
    if marker and marker in text:
        text = marker + text.split(marker, 1)[1]
    return {'descriptor_version': descriptor['descriptor_version'],
            'workflow': descriptor['workflow'], 'operations': descriptor['operations'],
            'contract': text,
            'inspection_contract': copy.deepcopy(descriptor.get('inspection_contract')),
            'native_validation_required': True, 'creative_acceptance_required': True}


def evidence(observed, workflow):
    """Preserve creative evidence, warnings, geometry and native validation.

    Editor selection/history defaults and cryptographic inventory are not creative
    inputs. The coordinator validates hashes and binds revisions deterministically.
    """
    value = copy.deepcopy(observed)
    value.pop('revision', None)
    value['artifacts'] = [{k: entry[k] for k in ('path', 'role')} for entry in value.get('artifacts', [])]
    metrics = value.get('technical_evidence', {})
    readback = metrics.get('production/native/readback.json')
    if workflow == '3d' and isinstance(readback, dict):
        # Keep actual native IDs, transforms, editable text/material/camera/light
        # values and render settings. Mesh digests are validated locally.
        for item in readback.get('geometry', {}).values():
            if isinstance(item, dict): item.pop('mesh_sha256', None)
    proof = metrics.get('production/revision-proof.json')
    if workflow == '3d' and isinstance(proof, dict) and isinstance(proof.get('before'), dict) and isinstance(proof.get('after'), dict):
        before, after = proof['before'], proof['after']
        metrics['production/revision-proof.json'] = {
            **{key: item for key, item in proof.items() if key not in ('before', 'after')},
            'native_changes': changes(before, after),
            'object_identity_preserved': before['objects'] == after['objects'] if 'objects' in before and 'objects' in after else None,
            'current_object_ids': after.get('objects'),
            'render_settings_preserved': before['render'] == after['render'] if 'render' in before and 'render' in after else None,
            'full_evidence_artifact': 'production/revision-proof.json',
        }
    structure = metrics.get('native/structure.json')
    if workflow == 'image' and isinstance(structure, dict) and isinstance(structure.get('layers'), list):
        fields = ('width', 'height', 'depth', 'mode', 'resolution', 'warnings')
        compact = {key: structure[key] for key in fields if key in structure}
        layer_fields = ('id', 'name', 'kind', 'bounds', 'text', 'visible', 'opacity',
                        'fill', 'blend', 'clipped', 'hasMask', 'hasVectorMask')
        compact['layers'] = [{key: layer[key] for key in layer_fields if key in layer} for layer in structure['layers']]
        compact['full_evidence_artifact'] = 'native/structure.json'
        metrics['native/structure.json'] = compact
    return value
