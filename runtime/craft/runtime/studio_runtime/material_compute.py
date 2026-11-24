"""Full-size Material evaluation through the maintained bounded native route.

Native evaluation resolves dynamic bases in its own order. Shared counters are
charged after that resolution and across nested instances, before raster work.
The supervisor separately enforces aggregate RSS, disk, CPU and wall limits.
"""
from pathlib import Path

from . import material_document as document, material_dependencies as dependencies
from .material_container import require

LIMITS = {'node_visits':16_384,'node_texels':16_777_216,'output_texels':67_108_864}


def validate(params):
    require(type(params) is dict and set(params)=={'graph'} and type(params['graph']) is str
            and 1<=len(params['graph'].encode('utf-8'))<=4096, 'cook requires one explicit graph path')


def integer(value, low, high): return type(value) is int and low<=value<=high


def cook(root, path, graph, executable, *, seconds=120, cancelled=lambda:False):
    validate({'graph':graph});root=Path(root).resolve(strict=True);path=document.owned(root,path)
    profile=document.read_native(path);package=profile['container']['root']
    graphs=profile['model']['packages'][package]['graphs']
    choices=[(index,item) for index,item in enumerate(graphs) if '/'.join(filter(None,(item.get('folder'),item['name'])))==graph]
    require(len(choices)==1 and choices[0][1].get('function') is None, 'cook graph is absent or is a standalone function')
    index,_=choices[0]
    process=document.Engine(executable,root,seconds=seconds,cancelled=cancelled)
    process.observe(path,profile)
    reply=document.snapshot_json(process._run('evaluate',path,index))
    nodes,usage=validate_reply(profile,index,reply)
    require(document.container.read_bytes(path)==profile['container']['source_bytes'] and not cancelled(), 'evaluation source changed or was cancelled')
    return {'schema_version':1,'document_sha256':profile['container']['source_sha256'],'graph':graph,'native_graph_index':index,
            'nodes':nodes,'usage':usage,'limits':LIMITS,'native_calls':process.calls,'full_size':True,'finite_outputs':True,
            'native_model_equal':True,'source_bytes_unchanged':True,'native_dynamic_base_order':True,
            'raster_counters_include_instances':True,'temporary_allocation_bound':False,'outer_worker_limits_required':True,
            'cook_performed':True,'map_export_performed':False,'preview_performed':False,'visual_approval':False}


def validate_reply(profile,index,reply):
    """Check the full native model, finite raster diagnostics and shared budget."""
    require(type(reply) is dict and set(reply)=={'nativePackage','graph','nodes','usage','limits','fullSize','finiteOutputs','sourceSaved'} | dependencies.fields(profile), 'evaluation envelope differs')
    package=profile['container']['root'];expected=profile['model']['packages'][package]['graphs'][index]
    dependencies.check_reply(profile,reply)
    require(type(reply['graph']) is int and reply['graph']==index and reply['fullSize'] is True and reply['finiteOutputs'] is True
            and reply['sourceSaved'] is False and reply['limits']==LIMITS, 'evaluation changed its graph or execution policy')
    nodes=reply['nodes'];require(type(nodes) is list and len(nodes)==len(expected['nodes']), 'evaluation node inventory differs')
    total=0
    for row,node in zip(nodes,expected['nodes']):
        require(type(row) is dict and set(row)=={'id','base','baseValues','parameters','cached','outputs'} and type(row['id']) is int
                and row['id']==node['id'] and type(row['cached']) is bool, 'evaluation node identity or fields differ')
        require(type(row['base']) is dict and type(row['baseValues']) is dict and type(row['parameters']) is dict
                and type(row['outputs']) is list, 'evaluation diagnostics are malformed')
        for output in row['outputs']:
            require(type(output) is dict, 'evaluation output is malformed')
            if set(output)=={'value'}:
                require(type(output['value']) is dict and set(output['value'])=={'t','v'}, 'evaluation value lacks its native type')
            else:
                require(set(output)=={'width','height','channels','minimum','maximum'} and integer(output['width'],1,8192)
                        and integer(output['height'],1,8192) and type(output['channels']) is int and output['channels'] in (1,4), 'evaluation raster fields differ')
                pixels=output['width']*output['height'];total+=pixels
                require(pixels<=LIMITS['node_texels'] and type(output['minimum']) in (int,float) and type(output['maximum']) in (int,float)
                        and output['minimum']<=output['maximum'], 'evaluation raster exceeds its budget or has invalid bounds')
    usage=reply['usage'];require(type(usage) is dict and set(usage)=={'node_visits','output_texels'}
        and integer(usage['node_visits'],len(nodes),LIMITS['node_visits']) and integer(usage['output_texels'],total,LIMITS['output_texels']), 'evaluation aggregate counters differ')
    return nodes,usage
