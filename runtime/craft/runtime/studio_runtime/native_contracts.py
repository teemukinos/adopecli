"""Complete native-engine identities, separate from hosted release admission.

This catalog is not an allowlist for customer execution. The hosted operation
list, SQL admission and qualified worker image remain separate gates. Optional
construction and synthesis routes need different worker isolation/provisioning.
"""

FAMILIES = {
    'image': ('adjust', 'revise', 'create', 'edit'),
    'vector': ('create', 'revise_text', 'revise_geometry'),
    'video': ('create', 'edit'),
    'motion': ('create', 'edit'),
    'audio': ('create', 'edit'),
    'photo': ('create', 'edit'),
    'pdf': ('create', 'import', 'inspect', 'merge', 'extract', 'edit'),
    'layout': ('create', 'import', 'inspect', 'edit'),
    'interface': ('create', 'import', 'inspect', 'edit'),
    'animate': ('create', 'import', 'inspect', 'edit', 'export'),
    'texture': ('create', 'import', 'inspect', 'edit', 'export', 'render', 'bake', 'material'),
    'material': ('create', 'import', 'inspect', 'edit', 'cook', 'export', 'preview', 'bundle'),
    'write': ('create', 'import', 'inspect', 'edit', 'bundle', 'export'),
    'slides': ('create', 'import', 'inspect', 'edit', 'bundle', 'export', 'migrate'),
    'cad': ('create', 'import', 'inspect', 'edit', 'solve', 'solid', 'export', 'bundle', 'migrate'),
    'sheets': ('create', 'import', 'inspect', 'edit', 'calculate', 'export', 'bundle'),
    'inspect': ('analyze', 'import', 'inspect', 'annotate', 'export', 'bundle'),
}
OPERATIONS = tuple(family + '.' + action for family, actions in FAMILIES.items() for action in actions)


def require_operation(operation):
    if type(operation) is not str or operation not in OPERATIONS:
        raise ValueError('operation is not part of the native worker contract')


def engine_identity(operation):
    require_operation(operation)
    from . import capabilities
    return capabilities.engine_identity(operation)


def validate_source(operation, manifest):
    """Bind a revision to its family; the adapter validates version/migration.

    Prior versions are deliberately not silently upgraded here. Explicit migration
    operations must still inspect their native version, receipts and complete state.
    """
    expected = engine_identity(operation)
    engine = manifest.get('engine') if isinstance(manifest, dict) else None
    if not isinstance(engine, dict) or engine.get('name') != expected['name']:
        raise ValueError('source revision belongs to another engine')


def validate_result(operation, manifest, *, import_parameters=None):
    """Check native publication identity without granting operation admission."""
    validation = manifest.get('validation') if isinstance(manifest, dict) else None
    if not isinstance(validation, dict) or validation.get('passed') is not True:
        raise ValueError('passing native validation required')
    engine = manifest.get('engine')
    if operation == 'project.import':
        from . import portable_contract
        from .bundle import ENGINES
        family = portable_contract.validate_parameters(import_parameters) if import_parameters is not None else None
        name = engine.get('name') if isinstance(engine, dict) else None
        if type(name) is not str or validation.get('original_files_unchanged') is not True:
            raise ValueError('qualified native import validation required')
        if family is None:
            if name not in ENGINES:
                raise ValueError('qualified native import validation required')
            expected = {'name': name, 'version': ENGINES[name]}
        else:
            expected = engine_identity(family+'.'+FAMILIES[family][0])
            if family not in portable_contract.LEGACY:
                if (validation.get('replay_family') != family or any(validation.get(key) is not True for key in
                        ('native_cold_reopen', 'native_model_equal', 'native_inventory_equal', 'imported_native_bytes_preserved'))):
                    raise ValueError('complete selected native import validation required')
        if import_parameters is not None and validation.get('portable_import_request_sha256') != portable_contract.request_sha256(import_parameters):
            raise ValueError('native import result differs from its authorized request')
    else:
        expected = engine_identity(operation)
    if not isinstance(engine, dict) or any(engine.get(k) != v for k, v in expected.items()):
        raise ValueError('qualified engine identity required')
