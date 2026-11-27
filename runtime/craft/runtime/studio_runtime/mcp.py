"""Local stdio MCP entry point. Jobs run in a worker: a source checkout starts it on submit."""
import json
import sys
from . import capabilities
from .store import Store


def schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
TOOLS = [
    {"name":"studio_plan_synthesis","description":"Validate an explicit offline SDXL request and report dependency gates. No download or inference occurs.","inputSchema":schema({"document":{"type":"object"}},["document"])},
    {"name":"studio_plan_production","description":"Validate an offline editable 3D photographic recipe without submitting work. Visual quality needs review.","inputSchema":schema({"document":{"type":"object"}},["document"])},
    {"name":"studio_plan_construction","description":"Validate and plan typed editable construction without submitting work.","inputSchema":schema({"document":{"type":"object"}},["document"])},
    {"name": "studio_list_attempt_holds", "description": "List up to 100 unresolved local attempts, including historical attempts of jobs that later succeeded. Pass next_cursor as after to continue.",
     "inputSchema": schema({'after': STRING}, [])},
    {"name": "studio_reconcile_attempt", "description": "With the worker stopped, preview whether local execution is proved stopped or never admitted. apply=true records immutable evidence and fails that attempt without publishing, retrying or deleting files. Live or uncertain process groups remain held. Only set confirm_local_origin after the owner confirms a legacy attempt ran on this machine; it records a baseline and still requires a later boot before settlement.",
     "inputSchema": schema({'job': STRING, 'attempt': {'type': 'integer', 'minimum': 1},
                            'apply': {'type': 'boolean', 'default': False},
                            'confirm_local_origin': {'type': 'boolean', 'default': False}}, ['job', 'attempt'])},
    {"name": "studio_list_projects", "description": "List up to 100 local projects and their archival/deletion state. Pass next_project as after to continue.",
     "inputSchema": schema({'after': STRING}, [])},
    {"name": "studio_set_project_state", "description": "Archive an idle local project or restore an archived project to active. Archived projects remain exportable.",
     "inputSchema": schema({'project': STRING, 'state': {'type': 'string', 'enum': ['active', 'archived']}}, ['project', 'state'])},
    {"name": "studio_delete_project_artifacts", "description": "Preview deletion of retained project blobs and known processing folders. With apply=true, permanently delete unshared files after the worker stops. Shared blobs and metadata remain. Uncertain attempts block deletion. External exports and unknown staging files are not removed.",
     "inputSchema": schema({'project': STRING, 'apply': {'type': 'boolean', 'default': False}}, ['project'])},
    {"name": "studio_erase_project", "description": "Preview complete local project erasure. apply=true explicitly removes settled project records and unshared managed files after the worker stops. Shared blobs, external exports, original imports and backups remain. Interrupted cleanup stays pending and must be resumed; no physical media erasure is promised.",
     "inputSchema": schema({'project': STRING, 'apply': {'type': 'boolean', 'default': False}}, ['project'])},
    {"name": "studio_capabilities", "description": "List supported local durable operations and engine availability.",
     "inputSchema": schema({}, [])},
    {"name": "studio_describe_operation", "description": "Describe one operation: its parameter JSON Schema, a working example, whether it needs a source revision and the editing rules that apply.",
     "inputSchema": schema({"operation": STRING}, ["operation"])},
    {"name": "studio_rules", "description": "List the editing rules that job submission enforces, each with a fix and an example.",
     "inputSchema": schema({}, [])},
    {"name": "studio_create_project", "description": "Create a durable local project without a cloud account.",
     "inputSchema": schema({"name": STRING}, ["name"])},
    {"name": "studio_submit_job", "description": "Persist a typed job and return its ID. A separate Studio worker executes it.",
     "inputSchema": schema({"project": STRING, "operation": {"type": "string", "enum": list(capabilities.OPERATIONS)},
                            "parameters": {"type": "object"}, "idempotency_key": STRING,
                            "source_revision": STRING, "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 86400}},
                           ["project", "operation", "parameters", "idempotency_key"])},
    {"name": "studio_import_asset", "description": "Import a local file into a project's immutable asset store.",
     "inputSchema": schema({"project": STRING, "source": STRING}, ["project", "source"])},
    {"name": "studio_import_project", "description": "Verify a portable directory bundle and import it as a new project. Native engine validation remains pending until a worker reopens it.",
     "inputSchema": schema({"bundle": STRING, "name": STRING}, ["bundle", "name"])},
    {"name": "studio_retry_job", "description": "Explicitly retry an isolated local operation, with an idempotency key and three-attempt limit. External provider operations are excluded.",
     "inputSchema": schema({"job": STRING, "idempotency_key": STRING}, ["job", "idempotency_key"])},
    {"name": "studio_get_job", "description": "Read persistent job status, cancellation state and result revision.",
     "inputSchema": schema({"job": STRING}, ["job"])},
    {"name": "studio_cancel_job", "description": "Request cancellation; running jobs are cancelled only after their process group stops.",
     "inputSchema": schema({"job": STRING}, ["job"])},
    {"name": "studio_get_revision", "description": "Read immutable native and exported artifact metadata with hashes.",
     "inputSchema": schema({"revision": STRING}, ["revision"])},
    {"name": "studio_export_project", "description": "Write a revision and portable manifest to a new local directory. Existing paths are refused.",
     "inputSchema": schema({"revision": STRING, "destination": STRING}, ["revision", "destination"])},
]

from . import usage_cli
TOOLS.extend(usage_cli.tools(schema, STRING))
next(t for t in TOOLS if t['name'] == 'studio_submit_job')['inputSchema']['properties']['usage_workflow'] = STRING


def invoke(store, name, args, product='studio'):
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if tool is None:
        raise ValueError("unknown tool")
    definition = tool["inputSchema"]
    if not isinstance(args, dict) or set(args) - definition["properties"].keys() or set(definition["required"]) - args.keys():
        raise ValueError("missing or unsupported tool arguments")
    for key, value in args.items():
        kind = definition["properties"][key]["type"]
        if kind == "string" and (not isinstance(value, str) or not value):
            raise ValueError(f"{key} must be a nonempty string")
        if kind == 'boolean' and type(value) is not bool:
            raise ValueError(f'{key} must be a boolean')
        if kind == 'integer' and (type(value) is not int or value < definition['properties'][key].get('minimum', 0)):
            raise ValueError(f'{key} must be a positive integer')
    if name.startswith('studio_usage_'):
        return usage_cli.invoke(store, name[len('studio_usage_'):], args)
    if name == 'studio_plan_synthesis':
        from .synthesis import plan
        return plan(args['document'])
    if name == 'studio_plan_production':
        from .production import plan
        return plan(args['document'])
    if name == 'studio_plan_construction':
        from .construction import plan
        return plan(args['document'])
    if name == 'studio_list_attempt_holds':
        from .reconciliation import list_holds
        return list_holds(store, 'local', args.get('after'))
    if name == 'studio_reconcile_attempt':
        from .reconciliation import reconcile
        return reconcile(store, 'local', args['job'], args['attempt'], args.get('apply', False), args.get('confirm_local_origin', False))
    if name == 'studio_list_projects': return store.projects('local', args.get('after'))
    if name == 'studio_set_project_state':
        from .projects import set_state
        return set_state(store, 'local', args['project'], args['state'])
    if name == 'studio_delete_project_artifacts':
        from .projects import delete_artifacts
        return delete_artifacts(store, 'local', args['project'], args.get('apply', False))
    if name == 'studio_erase_project':
        from .erasure import erase_project
        return erase_project(store, 'local', args['project'], args.get('apply', False))
    if name == "studio_capabilities":
        from .capacity import describe
        return {**capabilities.describe(product=product), "storage": describe(store.root)}
    if name == "studio_describe_operation":
        from . import descriptors
        return descriptors.describe(args["operation"])
    if name == "studio_rules":
        from . import rules
        return rules.describe()
    if name == "studio_import_asset": return store.import_asset("local", args["project"], args["source"])
    if name == "studio_import_project": return store.import_project("local", args["bundle"], args["name"])
    if name == "studio_retry_job": return store.retry("local", args["job"], args["idempotency_key"], capabilities.RETRY_SAFE)
    if name == "studio_create_project": return store.create_project("local", args["name"])
    if name == "studio_submit_job":
        from . import rules
        rules.check_submit(store, "local", args["project"], args["operation"], args["parameters"], args.get("source_revision"), args["idempotency_key"])
        return store.submit("local", args["project"], args["operation"], args["parameters"],
                            args["idempotency_key"], args.get("source_revision"), args.get("timeout_seconds", 600), usage_workflow=args.get('usage_workflow'))
    if name == "studio_get_job": return store.get_job("local", args["job"])
    if name == "studio_cancel_job": return store.cancel("local", args["job"])
    if name == "studio_get_revision":
        from .rules import with_native_document
        return with_native_document(store.get_revision("local", args["revision"]))
    if name == "studio_export_project": return store.checkout("local", args["revision"], args["destination"])


# Public tool prefix and worker name for each runtime identity. The "dobe" identity is the A dope CLI.
PUBLIC = {'studio': ('studio', 'Studio'), 'dobe': ('dope', 'dope')}


def instructions(prefix, worker, starts_worker):
    """What an agent reads first. starts_worker: submitting a job starts the worker itself."""
    if not starts_worker:
        return (f"Jobs are durable. Run the local {worker} worker separately; poll {prefix}_get_job. "
                "Disconnection does not cancel a job.")
    return (f"Make files in four steps. 1. {prefix}_capabilities lists the operations and the engines that are built. "
            f"2. {prefix}_describe_operation gives an operation's parameter schema and a working example. "
            f"3. {prefix}_create_project, then {prefix}_submit_job with the operation, its parameters and an "
            "idempotency key. Submitting starts the job worker if none is running, and jobs keep running if you disconnect. "
            f"4. Poll {prefix}_get_job until its state is succeeded; result_revision names the new revision. "
            f"Call {prefix}_export_project with that revision and a new destination folder to get the files "
            f"({prefix}_get_revision lists them). Before you revise a file, read {prefix}_rules.")


def public_tools_for(product, starts_worker):
    prefix, worker = PUBLIC[product]
    tools = []
    for tool in TOOLS:
        description = tool['description'].replace('Studio', worker)
        if starts_worker and tool['name'] == 'studio_submit_job':
            description = (f'Persist a typed job and return its ID. Submitting starts the worker if none is running; '
                           f'poll {prefix}_get_job for the result.')
        tools.append({**tool, 'name': prefix + tool['name'][len('studio'):], 'description': description})
    return tools


def serve(store, product='studio', on_submit=None):
    if product not in PUBLIC:
        raise ValueError('unknown runtime identity')
    prefix, worker = PUBLIC[product]
    public_tools = public_tools_for(product, on_submit is not None)
    dispatch = {public['name']: internal['name'] for public, internal in zip(public_tools, TOOLS)}
    def reply(value):
        sys.stdout.write(json.dumps(value, allow_nan=False) + "\n"); sys.stdout.flush()
    while True:
        line = sys.stdin.buffer.readline(1 << 20)
        if not line:
            return
        if len(line) == 1 << 20 and not line.endswith(b"\n"):
            raise ValueError("MCP request exceeds the 1 MiB limit")
        try:
            message = json.loads(line)
        except ValueError:
            reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}})
            continue
        if not isinstance(message, dict):
            reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Expected a JSON-RPC object"}})
            continue
        if "id" not in message:
            continue
        response = {"jsonrpc": "2.0", "id": message["id"]}
        method = message.get("method")
        try:
            if method == "initialize":
                proposed = message.get("params", {}).get("protocolVersion")
                version = proposed if proposed in ("2024-11-05", "2025-03-26", "2025-06-18") else "2025-06-18"
                response["result"] = {"protocolVersion": version, "capabilities": {"tools": {}},
                                      "serverInfo": {"name": prefix + "-runtime", "version": "0.1.0"},
                                      "instructions": instructions(prefix, worker, on_submit is not None)}
            elif method == "ping": response["result"] = {}
            elif method == "tools/list": response["result"] = {"tools": public_tools}
            elif method == "tools/call":
                params = message.get("params", {})
                try:
                    public_name = params.get('name')
                    if not isinstance(public_name, str) or public_name not in dispatch:
                        raise ValueError('unknown tool')
                    result = invoke(store, dispatch[public_name], params.get("arguments", {}), product=product)
                    if on_submit and dispatch[public_name] in ('studio_submit_job', 'studio_retry_job'):
                        on_submit()
                    response["result"] = {"content": [{"type": "text", "text": json.dumps(result)}]}
                except (ValueError, OSError, KeyError, TypeError) as e:
                    from .rules import RuleViolation
                    text = json.dumps(e.payload()) if isinstance(e, RuleViolation) else str(e)
                    response["result"] = {"isError": True, "content": [{"type": "text", "text": text}]}
            else: response["error"] = {"code": -32601, "message": "Method not found"}
        except (ValueError, TypeError, AttributeError) as e:
            response["error"] = {"code": -32602, "message": str(e)}
        reply(response)
