"""Compare immutable archive packages using stable native reference identities.

Saved paths resolve only against the already admitted archive inventory. No path
is opened, rewritten in source XML, fetched or resolved through a library here.
"""
import copy

from .material_container import require
from . import material_model as model, material_resources as resources

PREFIX = 'mcraft://dobe-archive!/'


def predicted(profile):
    packages = copy.deepcopy(profile['model']['packages'])
    if profile['container']['format'] != 'mcraft':
        require(not profile['references']['requires_external_handoff'], 'bare source cannot resolve archived dependencies')
        return {'packages':packages}
    for owner, package in packages.items():
        pending = [package]
        while pending:
            item = pending.pop()
            if type(item) is list:
                pending.extend(item)
            elif type(item) is dict:
                instance = item.get('instance')
                if type(instance) is dict and instance.get('package'):
                    target = resources.resolve(owner,instance['package'])
                    require(target in packages, 'native dependency is outside the admitted package inventory')
                    instance['package'] = PREFIX+target
                # The pinned archive reader also remaps the legacy package
                # parameter. Preserve every other parameter and model field.
                parameter = item.get('sbs_package')
                if type(parameter) is dict and parameter.get('t') == 'text' and parameter.get('v'):
                    target = resources.resolve(owner,parameter['v'])
                    require(target in packages, 'native package parameter is outside the admitted inventory')
                    parameter['v'] = PREFIX+target
                pending.extend(item.values())
    return {'packages':packages}


def fields(profile):
    return {'archivedPackages'} if len(profile['model']['packages']) > 1 else set()


def check_reply(profile, reply):
    expected = predicted(profile)
    root = profile['container']['root']
    model.check_native(expected,root,reply['nativePackage'])
    if fields(profile):
        observed = reply.get('archivedPackages')
        require(type(observed) is dict and set(observed) == {PREFIX+key for key in expected['packages']},
                'native archived package inventory differs')
        for key in expected['packages']:
            model.check_native(expected,key,observed[PREFIX+key])
    else:
        require('archivedPackages' not in reply, 'native introduced an unadmitted package inventory')
    return {'serialized_native_model_equal':True, 'native_packages_compared':sorted(expected['packages']),
            'immutable_archive_dependencies':len(expected['packages'])-1,
            'resource_bytes_compared':False, 'engine_admission_complete':False}
