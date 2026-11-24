"""CLI and MCP interfaces for workflow receipts and native text checks."""
import json
from pathlib import Path
from . import usage, native_ocr


def add_parser(sub):
    parser = sub.add_parser('usage', help='Record and compare workflow usage without making provider calls')
    actions = parser.add_subparsers(dest='usage_action', required=True)
    for name in ('start', 'record', 'receipt', 'assess', 'compare', 'inspect'):
        action = actions.add_parser(name); action.add_argument('--project', required=True)
        if name != 'compare': action.add_argument('--workflow', required=name != 'receipt')
        if name == 'start':
            action.add_argument('--scope', choices=('production', 'development'), required=True)
            action.add_argument('--workload', required=True)
            action.add_argument('--quality-contract', required=True)
            action.add_argument('--compute-microusd-per-hour', type=int)
        if name in ('record', 'assess'): action.add_argument('--file', required=True, help='JSON entry or quality/coverage assessment')
        if name == 'receipt': action.add_argument('--details', action='store_true')
        if name == 'compare':
            action.add_argument('--baseline', required=True); action.add_argument('--candidate', required=True)
        if name == 'inspect':
            action.add_argument('--revision', required=True); action.add_argument('--path', required=True)
            action.add_argument('--expected-text', action='append', default=[])
            action.add_argument('--expected-dimensions', nargs=2, type=int)


def command(store, args):
    options = vars(args).copy()
    action = options.pop('usage_action')
    for field in ('command', 'state'): options.pop(field, None)
    if action in ('record', 'assess'):
        value = json.loads(Path(options.pop('file')).read_text())
        if action == 'record': options['entry'] = value
        else:
            if not isinstance(value, dict) or set(value) != {'quality', 'evidence', 'coverage'}:
                raise ValueError('Assessment requires quality, evidence and coverage')
            options.update(value)
    return invoke(store, action, options)


def invoke(store, action, args):
    options = args.copy(); project = options.pop('project')
    key = options.pop('workflow', None)
    if action == 'start': return usage.start(store, 'local', project, key, **options)
    if action == 'record': return usage.record(store, 'local', project, key, **options)
    if action == 'receipt': return usage.receipt(store, 'local', project, key, **options)
    if action == 'assess': return usage.assess(store, 'local', project, key, **options)
    if action == 'compare': return usage.compare(store, 'local', project, **options)
    if action == 'inspect': return native_ocr.inspect_revision(store, 'local', project, workflow=key, **options)
    raise ValueError('Unsupported usage action')


def tools(schema, string):
    common = {'project': string, 'workflow': string}
    definitions = {
        'start': ('Start an idempotent production or development usage workflow.',
                  {'scope': string, 'workload': string, 'quality_contract': string, 'compute_microusd_per_hour': {'type': 'integer', 'minimum': 0}}, ['scope', 'workload', 'quality_contract']),
        'record': ('Import one incremental external usage entry. Never import a cumulative parent total alongside child calls. Source IDs must be unique within the project.',
                   {'entry': {'type': 'object'}}, ['entry']),
        'receipt': ('Read automatic agent, native attempt and OCR accounting plus imported external usage. Null means unknown, not free.',
                    {'details': {'type': 'boolean'}}, []),
        'assess': ('Attest equivalent quality and telemetry coverage for the current receipt. Later activity invalidates this assessment.',
                   {'quality': string, 'evidence': string, 'coverage': {'type': 'object'}}, ['quality', 'evidence', 'coverage']),
        'compare': ('Compare matched observed workflows. Savings remain null without current passing assessments and sufficient coverage.',
                    {'baseline': string, 'candidate': string}, ['baseline', 'candidate']),
        'inspect': ('Check an immutable published PNG/JPEG with local Apple Vision OCR and deterministic dimensions/hash checks. No quality approval. First use compiles a local helper when swiftc is available.',
                    {'revision': string, 'path': string, 'expected_text': {'type': 'array', 'items': string},
                     'expected_dimensions': {'type': 'array', 'items': {'type': 'integer'}}}, ['revision', 'path']),
    }
    result = []
    for name, (description, fields, required) in definitions.items():
        properties = {**common, **fields}
        if name == 'compare': properties.pop('workflow')
        result.append({'name': 'studio_usage_' + name, 'description': description,
                       'inputSchema': schema(properties, ['project'] + ([] if name in ('compare', 'receipt') else ['workflow']) + required)})
    return result
