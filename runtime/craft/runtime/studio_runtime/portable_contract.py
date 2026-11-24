"""Typed portable-import requests shared by API, queue and isolated workers.

Families are selected by authenticated requests and immutable image declarations.
An archive cannot select an executable, widen its worker profile or grant consent.
"""
import hashlib
import json
from uuid import UUID

from . import native_contracts

FAMILIES = tuple(native_contracts.FAMILIES)
LEGACY = ('image', 'vector')


def families(value):
    if (type(value) not in (list, tuple) or any(type(name) is not str for name in value)
            or len(set(value)) != len(value) or set(value)-set(FAMILIES)):
        raise ValueError('unique supported portable import families required')
    return tuple(value)


def validate_parameters(parameters, source_revision=None):
    if (source_revision is not None or type(parameters) is not dict or 'asset' not in parameters
            or set(parameters)-{'asset', 'family', 'authorization'}):
        raise ValueError('project import requires a bundle asset and an empty project')
    if type(parameters['asset']) is not str:
        raise ValueError('portable import requires an asset UUID')
    UUID(parameters['asset'])
    family = parameters.get('family')
    if 'family' in parameters and (type(family) is not str or family not in FAMILIES):
        raise ValueError('supported explicit portable import family required')
    if family == 'inspect':
        from .inspect_bundle import authorizations
        if 'authorization' not in parameters:
            raise ValueError('fresh Inspect import authorization required')
        authorizations(('inspect',), {'inspect': parameters['authorization']})
    elif 'authorization' in parameters:
        raise ValueError('authorization requires an explicit Inspect import family')
    return family


def select(parameters, supported):
    family = validate_parameters(parameters)
    admitted = families(supported)
    if family is None:
        if not set(LEGACY) <= set(admitted):
            raise ValueError('legacy import requires both image and vector support')
    elif family not in admitted:
        raise ValueError('import family absent from the bound worker image contract')
    return family


def request_sha256(parameters):
    validate_parameters(parameters)
    return hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def execute(source, destination, maximum, parameters, supported):
    """Observe the selected family and bind its result to the exact new request."""
    family = select(parameters, supported)
    expected = (native_contracts.engine_identity(family+'.'+native_contracts.FAMILIES[family][0])
                if family is not None else None)
    selected = (family,) if family is not None and family not in LEGACY else ()
    consent = {'inspect': parameters['authorization']} if family == 'inspect' else None
    from . import bundle
    result = bundle.execute(source, destination, maximum, replay_families=selected,
                            replay_authorizations=consent, expected_engine=expected)
    result['validation']['portable_import_request_sha256'] = request_sha256(parameters)
    native_contracts.validate_result('project.import', result, import_parameters=parameters)
    return result
