"""Hosted operation allowlist, including isolated portable project import."""
from studio_runtime import capabilities, portable_contract

from studio_runtime.native_contracts import OPERATIONS as NATIVE_OPERATIONS

# This unpublished native release implements all seventeen families. Database
# startup requires migration 024; workers still claim only their immutable
# image's explicit subset. Source admission is not Linux/release qualification.
OPERATIONS = (*NATIVE_OPERATIONS, 'project.import')
RETRY_SAFE = frozenset(OPERATIONS)


def asset_inputs(operation, parameters):
    if operation == 'project.import':
        return {parameters['asset']: 'assets/bundle.zip'}
    return capabilities.asset_inputs(operation, parameters)


def validate(operation, parameters, source_revision):
    if operation not in OPERATIONS:
        raise ValueError('operation is not part of the hosted native catalog')
    if operation == 'project.import':
        portable_contract.validate_parameters(parameters, source_revision)
    else:
        capabilities.validate(operation,parameters,source_revision)
