"""Versioned operation descriptors and derived function interfaces.

These schemas describe the coordinator's bounded top-level inputs. Native
validators and the authored profile contract validate nested creative documents;
the schemas are not inferred from Python validation code.
"""
import copy

OBJECT = {'type': 'object'}
ARRAY = {'type': 'array', 'items': OBJECT}
HASH = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
ARTIFACTS = {
    'image': ['native/document.pcraft', 'exports/document.png'],
    'video': ['native/document.fcproj', 'exports/document.mp4', 'exports/frame-*.png'],
    'animation': ['construction/document.json', 'construction/components/*/native/scene.rml',
                  'construction/components/*/exports/construction.riv', 'construction/components/*/exports/web/index.html'],
    '3d': ['production/recipe.json', 'production/native/scene.blend', 'production/exports/photograph.png'],
    'document': ['native/document.json', 'native/project.dobewrite', 'page exports selected by write.export'],
}


def schema(properties, required=()):
    return {'type': 'object', 'properties': copy.deepcopy(properties),
            'required': list(required), 'additionalProperties': False}


def parameters(operation, selected):
    if operation in selected.get('parameter_schemas', {}):
        return copy.deepcopy(selected['parameter_schemas'][operation])
    if operation == 'image.create':
        return schema({'width': {'type': 'integer', 'minimum': 1, 'maximum': 8192},
                       'height': {'type': 'integer', 'minimum': 1, 'maximum': 8192},
                       'background': {'type': 'string'}, 'layers': {**ARRAY, 'minItems': 1, 'maxItems': 64}},
                      ('width', 'height', 'background', 'layers'))
    if operation == 'video.create':
        dimensions = {'type': 'integer', 'minimum': 16, 'maximum': 1920, 'multipleOf': 2}
        return schema({'width': dimensions, 'height': dimensions,
                       'fps': {'type': 'integer', 'enum': [24, 25, 30, 50, 60]},
                       'clips': {**ARRAY, 'minItems': 1, 'maxItems': 100},
                       'titles': {**ARRAY, 'maxItems': 32}, 'audio': {**ARRAY, 'maxItems': 32}},
                      ('width', 'height', 'fps', 'clips'))
    if operation in ('construct.create', 'production.create'):
        return schema({'document': OBJECT}, ('document',))
    if operation == 'write.create':
        result = schema({'document': OBJECT, 'recipe': {'type': 'string', 'enum': ['production_brief']},
                         'version': {'type': 'integer', 'enum': [1]}, 'title': {'type': 'string'},
                         'sections': ARRAY, 'subtitle': {'type': 'string'}, 'author': {'type': 'string'},
                         'deliverables': ARRAY, 'controls': OBJECT})
        result['anyOf'] = [{'required': ['document']}, {'required': ['recipe', 'version', 'title', 'sections']}]
        return result
    if operation.endswith('.edit'):
        properties = {'edits': {**ARRAY, 'minItems': 1}}
        guard = {'production.edit': 'recipe_sha256', 'construct.edit': 'document_sha256', 'write.edit': 'expected_sha256'}.get(operation)
        if guard: properties[guard] = HASH
        return schema(properties, properties)
    if operation == 'construct.render':
        return schema({'outputs': {**ARRAY, 'minItems': 1}}, ('outputs',))
    if operation == 'write.export':
        return schema({'format': {'type': 'string', 'enum': ['png', 'pdf']},
                       'pages': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1, 'maximum': 256}, 'uniqueItems': True},
                       'scale': {'type': 'number', 'minimum': .25, 'maximum': 4}, 'font_substitutions': ARRAY}, ('format',))
    if operation.endswith(('.inspect', '.verify', '.render', '.bundle')):
        return schema({})
    # An extension supplies its own schema in its descriptor. Without one, do
    # not invent parameter names or claim complete schema coverage.
    return {'type': 'object', 'additionalProperties': True}


def descriptors(workflow, selected):
    return [{'version': 1, 'operation': operation, 'parameters': parameters(operation, selected),
             'parameter_scope': 'top-level inputs; nested profile rules require native validation',
             'profile_contract_ref': '#/contract',
             'source_revision': 'coordinator-managed current revision; creation starts without a source',
             'supported_edits': 'guarded changes in the selected profile' if operation.endswith('.edit') else None,
             'output_artifacts': selected.get('artifacts', ARTIFACTS.get(workflow, [])),
             'inspection': selected.get('inspection', []),
             'qualification_limits': 'existing bounded local operation; registration does not establish availability or creative qualification'}
            for operation in selected['operations']]


def tools(descriptors):
    return [{'type': 'function', 'name': item['operation'].replace('.', '_'),
             'description': item['operation'] + '. Submit an ordinary runtime job. ' + item['parameter_scope'] + '.',
             'parameters': copy.deepcopy(item['parameters']), 'strict': False} for item in descriptors]
