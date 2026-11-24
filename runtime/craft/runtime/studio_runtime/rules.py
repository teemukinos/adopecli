"""Editing rules: the fixed rule vocabulary and the submit-time checks that refuse a violation.

The CLI and the MCP server call check_submit before they persist a job. A refusal is a
RuleViolation, which carries the rule id, a one-sentence fix and machine-readable details.
"""
import json
from . import capabilities

SCHEMA_VERSION = 1

RULES = [
    {'id': 'one_create_per_project',
     'summary': 'A create or import operation runs only on a project that has no head revision yet.',
     'fix': 'Create a new project for the new document, or revise the existing head with --source.',
     'example': 'dope create-project Poster && dope submit PROJECT vector.create --parameters create.json --key first'},
    {'id': 'source_required',
     'summary': 'Every operation that is not a create or import needs a source revision.',
     'fix': 'Pass the project head as --source (MCP: source_revision); "dope project PROJECT" shows the head.',
     'example': 'dope submit PROJECT vector.revise_text --parameters edit.json --key edit-1 --source HEAD'},
    {'id': 'revise_from_head',
     'summary': "The source revision must be the project's current head revision.",
     'fix': 'Submit again with details.head as the source revision.',
     'example': 'dope project PROJECT   # read "head", then submit with --source set to that id'},
    {'id': 'edit_requires_previous_hash',
     'summary': "An edit that carries expected_sha256 or document_sha256 must give the sha256 of the source revision's native document.",
     'fix': 'Submit again with details.current as the hash; "dope revision SOURCE" shows it as native_document.sha256.',
     'example': 'dope revision SOURCE   # copy native_document.sha256 into expected_sha256'},
]
RULE_IDS = tuple(rule['id'] for rule in RULES)
_FIX = {rule['id']: rule['fix'] for rule in RULES}

# Families whose engine compares expected_sha256 with the sha256 of this native file.
# Other families (material, texture, construction) check their hash in the engine.
HASHED_DOCUMENT = {
    'write': 'native/project.dobewrite',
    'sheets': 'native/project.dobesheets',
    'slides': 'native/project.dobeslides',
    'cad': 'native/project.dobecad',
    'inspect': 'native/project.dobeinspect',
}


class RuleViolation(ValueError):
    def __init__(self, rule, message, details=None):
        super().__init__(message)
        self.rule, self.details = rule, details or {}

    def payload(self):
        return {'error': type(self).__name__, 'message': str(self), 'rule': self.rule,
                'fix': _FIX[self.rule], 'details': self.details}


def describe():
    # Sorted keys make the CLI and MCP output byte-identical.
    return json.loads(json.dumps({'schema_version': SCHEMA_VERSION, 'rules': RULES}, sort_keys=True))


def native_document(manifest):
    """The revision's one native document, or None. JSON members and sidecars do not count."""
    found = [f for f in manifest.get('files', ())
             if f.get('role') == 'native' and not f.get('path', '').endswith('.json')]
    return {'path': found[0]['path'], 'sha256': found[0]['sha256']} if len(found) == 1 else None


def with_native_document(manifest):
    document = native_document(manifest)
    return {**manifest, 'native_document': document} if document else manifest


def _source_required(operation):
    from . import descriptors
    return descriptors.describe(operation)['source_required']


def check_submit(store, workspace, project, operation, parameters, source_revision, idempotency_key):
    """Validate a submit request and refuse editing-rule violations before the job is stored.

    A repeated idempotency key skips the rules, so a retry returns the original job.
    """
    enforce = not store.has_job_key(workspace, project, idempotency_key)
    if enforce and source_revision is None and _source_required(operation):
        raise RuleViolation('source_required', f'{operation} edits an existing revision and needs a source revision')
    capabilities.validate_for_project(store, workspace, project, operation, parameters, source_revision)
    if not enforce:
        return
    head = store.get_project(workspace, project)['head']
    if source_revision is None:
        if head is not None:
            raise RuleViolation('one_create_per_project', f'project already has a head revision; {operation} only runs on an empty project',
                                {'head': head})
        return
    if source_revision != head:
        raise RuleViolation('revise_from_head', 'the source revision is not the current head of the project',
                            {'head': head, 'source_revision': source_revision})
    expected = HASHED_DOCUMENT.get(operation.split('.')[0])
    provided = parameters.get('expected_sha256')
    if expected is None or not isinstance(provided, str):
        return
    document = native_document(store.get_revision(workspace, source_revision))
    if document and document['path'] == expected and provided != document['sha256']:
        raise RuleViolation('edit_requires_previous_hash', "expected_sha256 is not the sha256 of the source revision's native document",
                            {'parameter': 'expected_sha256', 'provided': provided, 'current': document['sha256']})
