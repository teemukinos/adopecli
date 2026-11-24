"""Persist worker contract keys without changing public operation names.

Older runtimes match the jobs.operation column literally. A qualified key keeps
new work queued during rollback instead of letting an older adapter reject it
after claiming. Historical unqualified jobs retain their existing behavior.
"""
import hashlib

SLIDES_OPERATIONS = frozenset((
    'slides.create', 'slides.import', 'slides.inspect', 'slides.edit',
    'slides.bundle', 'slides.export', 'slides.migrate',
))


def dispatch_key(operation):
    if operation not in SLIDES_OPERATIONS:
        return operation
    from .slides_binding import LOCK_SHA256
    # Change this contract when the runtime adds incompatible semantics even if
    # the native engine is unchanged. Engine upgrades also change the key.
    contract = 'slides-raster-v2-chain-v1:' + LOCK_SHA256
    return operation + '@' + hashlib.sha256(contract.encode('ascii')).hexdigest()


def supported_operations(operations):
    operations = tuple(operations)
    return tuple(dict.fromkeys((*operations, *(dispatch_key(operation) for operation in operations))))
