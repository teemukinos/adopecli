"""Selected operation contracts. Native validators remain authoritative."""
import hashlib
import inspect
import json
import os
import shutil
from pathlib import Path
from . import capabilities


WORKFLOWS = {
    'image': {'operations': ['image.create','image.edit'], 'family':'image',
              'inspection':['native layers','full PNG','text detail']},
    'video': {'operations': ['video.create','video.edit'], 'family':'video',
              'inspection':['native timeline','decoded cut frames','audio timing','playback']},
    'animation': {'operations': ['construct.create','construct.edit','construct.render','construct.inspect','construct.verify'],
                  'inspector':'rive',
                  'family':'construction-rive','inspection':['native states','transition samples','reduced motion','interaction playback']},
    '3d': {'operations':['production.create','production.edit','production.render','production.verify','production.inspect'],
           'after':{'production.create':[{'operation':'production.inspect','parameters':{}}],
                    'production.edit':[{'operation':'production.inspect','parameters':{}}]},
           'family':'photographic-production','inspection':['native objects','full PNG','multiple views','detail crops']},
    'document': {'operations':['write.create','write.edit','write.inspect','write.export','write.bundle'],
                 'after':{'write.create':[{'operation':'write.export','parameters':{'format':'png','scale':1}}],
                          'write.edit':[{'operation':'write.export','parameters':{'format':'png','scale':1}}]},
                 'family':'write','inspection':['native paragraphs','page previews','text extraction','export integrity']},
}


def contracts():
    return json.loads(Path(__file__).with_name('agent_contracts.json').read_text())


def registered():
    records=[]
    detailed={op for w in WORKFLOWS.values() for op in w['operations']}
    for op in capabilities.OPERATIONS:
        identity=capabilities.engine_identity(op)
        available=None
        records.append({'operation':op,'engine':identity,'registered':True,'available':available,
                        'agent_contract_available':op in detailed,
                        'availability_reason':'Not probed; selected workflow is validated before execution',
                        'qualified_for_agent_workflow':False,
                        'qualification':'not yet qualified by the orchestration pilot',
                        'hosted_qualified':False})
    return records


def describe(workflow):
    from .agent_crops import CONTRACT
    if workflow not in WORKFLOWS:
        raise ValueError('Unknown workflow; discover registered capabilities first')
    selected=WORKFLOWS[workflow]
    digest=hashlib.sha256()
    for op in selected['operations']:
        digest.update(inspect.getsource(capabilities.adapter(op).validate).encode())
    return {'descriptor_version':1,'workflow':workflow,**selected,
            'contract':contracts()[workflow], 'validator_sha256':digest.hexdigest(), 'inspection_contract':CONTRACT.copy(),
            'native_validation_required':True,'creative_acceptance_required':True,
            'scope':'existing local bounded profiles, not arbitrary native features or hosted qualification'}


def validate(workflow,operation,parameters,source):
    if operation not in describe(workflow)['operations']:
        raise ValueError('Operation is outside the selected workflow')
    if workflow=='animation' and operation=='construct.create':
        if any(c.get('engine')!='rive' for c in parameters.get('document',{}).get('components',[])):
            raise ValueError('Interactive animation contract supports the Rive profile only')
    capabilities.validate(operation,parameters,source)


def documentation(workflow):
    d=interface(workflow)
    return '# '+workflow+' agent contract\n\n'+json.dumps(d,indent=2)+'\n'


def interface(workflow):
    """Derive public function definitions and docs from the selected descriptors.

    The compact coordinator uses its JSON decision envelope to submit the same
    operations. It does not send this discovery inventory on every model turn.
    """
    from . import agent_operations
    selected=describe(workflow)
    operations=agent_operations.descriptors(workflow,WORKFLOWS[workflow])
    return {**selected,'operation_descriptors':operations,'tool_definitions':agent_operations.tools(operations)}


def execution_binding(workflow):
    """Pin the selected contract and, when packaged, the complete runtime bundle.

    A package change requires an explicit migration rather than silently changing
    the meaning of a pending creative decision. Source development has no sealed
    engine bundle and therefore only pins its selected operation contract.
    """
    selected=interface(workflow)
    digest=hashlib.sha256(json.dumps(selected,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    resources=os.environ.get('STUDIO_BUNDLE_RESOURCES')
    bundle=Path(resources)/'bundle.json' if resources else None
    return {'version':1,'selected_contract_sha256':digest,
            'runtime_bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest() if bundle else None}


def availability(workflow):
    """Probe only the selected engine. Registration is not availability."""
    selected=WORKFLOWS[workflow]
    try:
        if selected['family'] in ('construction-rive','photographic-production'):
            from .construction_support import binary
            binary('rive' if selected['family']=='construction-rive' else 'blender')
        else:
            adapter=capabilities.adapter(selected['operations'][0])
            if hasattr(adapter,'photo') and not hasattr(adapter,'engine'):
                adapter=adapter.photo
            if hasattr(adapter,'binding'):
                if not adapter.binding.available(): raise ValueError('Packaged engine binding unavailable')
            elif not shutil.which(adapter.engine()):
                raise ValueError('Selected engine executable unavailable')
            requirements=json.loads(Path(__file__).with_name('agent_engine_requirements.json').read_text())
            if workflow in requirements:
                executable=Path(shutil.which(adapter.engine())).resolve()
                metadata=json.loads((executable.parent.parent/'engine.json').read_text())
                if not isinstance(metadata,dict) or metadata.get('source_lock_sha256')!=requirements[workflow]['source_lock_sha256']:
                    raise ValueError('Selected engine lacks the required locked operation contract: '+requirements[workflow]['required_feature'])
        return {'available':True,'qualified_for_agent_workflow':False}
    except (ValueError,OSError) as exc:
        return {'available':False,'qualified_for_agent_workflow':False,'reason':str(exc)}
