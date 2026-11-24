"""Explicit consent and current-content verification for portable Inspect replay.

Stored recipes are data used to check a prior delivery contract. They never
supply authorization, select an executable or cause their operation to run.
"""
from . import inspection, inspect_project as project, inspect_source as source, inspect_host
from .inspect_source import require


def authorizations(families, value):
    if value is None:
        return {}
    require(type(value) is dict and not set(value)-{'inspect'}, 'replay authorization keys are invalid')
    if 'inspect' not in value:
        return {}
    require(type(families) in (tuple, list) and all(type(f) is str for f in families), 'explicit replay families required')
    require('inspect' in families, 'authorization requires an explicit Inspect replay profile')
    params = value['inspect']
    inspection.validate('inspect.inspect', params, 'source')
    return {'inspect': dict(params)}


def admit(value):
    require(type(value) is dict and 'inspect' in value, 'fresh replay input consent is required')
    params = value['inspect']
    inspection.validate('inspect.inspect', params, 'source')
    inspect_host.current()
    return dict(params)


def deliveries(root, replay_root, declared):
    """Regenerate current content and check the prior operation's report shape.

    The report's old request hash is checked for internal consistency. These
    comparisons do not authenticate that a historical invocation occurred.
    """
    checked = project.inspect_bytes(source.read_bytes(root/'native/project.dobeinspect'))
    recipe = source.strict_json(source.read_bytes(root/'recipes/last-inspect-operation.json'))
    source.fields(recipe, ('operation', 'parameters'), 'retained operation record')
    operation, params = recipe['operation'], recipe['parameters']
    new = operation in ('inspect.analyze', 'inspect.import')
    inspection.validate(operation, params, None if new else 'source')
    require(params['input_sha256'] == checked['source_sha256'], 'retained operation input hash differs')
    if operation == 'inspect.analyze':
        require(params['format'] == checked['manifest']['input_format'], 'retained analysis format differs')
    elif operation == 'inspect.annotate':
        history = checked['manifest']['history']
        require(bool(history) and source.encoded(params['edits']) == source.encoded(history[-1]['edits']),
                'retained annotation request differs from the replayed history')
    else:
        require(params['expected_sha256'] == checked['sha256'], 'retained operation project hash differs')

    # Core findings and current notes came from fresh, receipt-bound native
    # replay. Rebuild only the bounded historical envelope from its request.
    report = source.strict_json(source.read_bytes(replay_root/'exports/inspection.json'))
    retained = source.strict_json(source.read_bytes(root/'exports/inspection.json'))
    require(type(retained) is dict, 'retained inspection receipt is invalid')
    report = inspect_host.retained_receipt(report, retained, checked['members']['report.json'])
    report.update(operation=operation, native_calls=5 if operation in ('inspect.analyze', 'inspect.annotate') else 3,
                  previous_project_sha256=None if new else params['expected_sha256'])
    expected = {}
    if operation == 'inspect.export':
        data = inspection.delivery(checked, params['format'])
        expected['exports/findings.'+params['format']] = data
        report['delivery'] = {'format': params['format'], 'sha256': source.sha(data), 'bytes': len(data),
                              'untrusted_content_escaped': params['format'] == 'html'}
    elif operation == 'inspect.bundle':
        expected['exports/findings.dobeinspect'] = source.read_bytes(root/'native/project.dobeinspect')
    expected['exports/inspection.json'] = source.encoded(report)
    actual = {path: entry['role'] for path, entry in declared.items() if entry['role'] in ('asset', 'export', 'preview')}
    require(actual == {path: 'export' for path in expected}, 'source/delivery inventory differs from replay')
    for path, data in expected.items():
        require(source.read_bytes(root/path) == data, 'delivery differs from current native findings and annotations')
    return {'current_content_deliveries_replayed': True, 'historical_request_consistent': True,
            'historical_execution_authenticated': False, 'annotation_history_replayed': True}
