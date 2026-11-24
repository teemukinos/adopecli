"""Operation descriptors: a parameter JSON Schema, a working example and the editing rules.

The schemas in operation_descriptors.json are written by hand from each family's validator.
tools/test_descriptors.py checks them against the validator.
"""
import json
from pathlib import Path
from . import capabilities

SCHEMA_VERSION = 1
HASH_PARAMETERS = ('expected_sha256', 'document_sha256')
_DATA = Path(__file__).with_name('operation_descriptors.json')
_CACHE = {}


def _entries():
    if 'entries' not in _CACHE:
        _CACHE['entries'] = json.loads(_DATA.read_text(encoding='utf-8'))
    return _CACHE['entries']


def rules(source_required, schema):
    """Editing rule ids that apply to an operation, derived from its descriptor."""
    ids = ['source_required', 'revise_from_head'] if source_required else ['one_create_per_project']
    if set(HASH_PARAMETERS) & set(schema.get('required', ())):
        ids.append('edit_requires_previous_hash')
    return ids


def describe(operation):
    entry = _entries().get(operation) if operation in capabilities.OPERATIONS else None
    if entry is None:
        raise ValueError(f'unknown operation {operation!r}; run "dope capabilities" to list the operations')
    descriptor = {'schema_version': SCHEMA_VERSION, 'operation': operation, 'family': operation.split('.')[0],
                  'summary': entry['summary'], 'source_required': entry['source_required'],
                  'parameters': entry['parameters'], 'example': entry['example'],
                  'rules': rules(entry['source_required'], entry['parameters'])}
    # Sorted keys make the CLI, describe --all and MCP output byte-identical.
    return json.loads(json.dumps(descriptor, sort_keys=True))


def describe_all():
    return {'schema_version': SCHEMA_VERSION, 'operations': [describe(op) for op in capabilities.OPERATIONS]}


def summaries():
    return {op: _entries()[op]['summary'] for op in capabilities.OPERATIONS}
