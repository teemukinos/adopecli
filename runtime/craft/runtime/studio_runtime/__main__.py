"""CLI for the durable runtime. The worker runs separately from submitting clients."""
import argparse
import json
import os
from pathlib import Path
import sys
from .store import Store
from . import capabilities, on_demand_worker

# Commands shown by --help, in this order. Everything else is advanced.
USER_COMMANDS = {
    "create-project": "Create a project and print its id",
    "projects": "List projects",
    "project": "Show a project and its head revision",
    "submit": "Submit a job: an operation with JSON parameters",
    "job": "Show a job, its state and its result",
    "cancel": "Cancel a queued or running job",
    "events": "List the events of a job",
    "revision": "Show a revision, its files and its native document",
    "checkout": "Copy the files of a revision to a folder",
    "retry": "Retry a failed job with a new key",
    "import-asset": "Import a file into a project",
    "import-project": "Import a project bundle as a new project",
    "capabilities": "List the operations, engines and storage",
    "describe": "Show an operation's parameter schema, example and editing rules",
    "rules": "List the editing rules that submit enforces",
    "doctor": "Check the sandbox, the state directory and the engines",
    "mcp": "Serve the MCP tools on stdin and stdout",
    "worker": "Run the job worker",
    "help": "Show help for a command; \"help advanced\" lists the advanced commands",
}
ADVANCED_COMMANDS = {
    "cloud": "Use an explicitly configured hosted workspace",
    "agent": "Create and resume bounded creative runs",
    "usage": "Record and compare workflow usage without making provider calls",
    "attempt-holds": "List job attempts held for reconciliation",
    "reconcile-attempt": "Resolve a held job attempt (stop the worker first)",
    "project-state": "Mark a project active or archived",
    "delete-project-artifacts": "Delete the stored files of a project (a dry run without --apply)",
    "erase-project": "Erase a project and its records (a dry run without --apply)",
    "recover": "Reconcile jobs left running by a stopped worker",
    "construct": "Plan a construction from a spec file",
    "production": "Plan a production from a spec file",
    "synthesis": "Plan a synthesis from a spec file",
    "cleanup": "Remove old temporary files (a dry run without --apply)",
    "limits": "Show or change the local execution limits",
}


def advanced_help(prog):
    width = max(map(len, ADVANCED_COMMANDS)) + 2
    lines = [f"Advanced commands. Run \"{prog} COMMAND --help\" for the options of each.", ""]
    lines += [f"  {name.ljust(width)}{summary}" for name, summary in ADVANCED_COMMANDS.items()]
    return "\n".join(lines) + "\n"


def read_parameters(value):
    """--parameters takes inline JSON (starting with "{"), "-" for stdin, or a file path."""
    if value.lstrip().startswith("{"):
        text = value
    elif value == "-":
        text = sys.stdin.read()
    else:
        text = Path(value).read_text()
    return json.loads(text)


def main(argv=None, product='studio', checkout=False):
    """checkout=True is the open-source clone route (bin/dope): the public dope
    identity, a state directory apart from packaged installs, and no service commands."""
    if product not in ('studio', 'dobe') or checkout and product != 'dobe':
        raise ValueError('unknown runtime identity')
    if checkout:
        default_state = Path.home() / '.local/share/a-dope-cli/state'
    else:
        default_state = (Path.home() / 'Library/Application Support/Dobe Local/state' if product == 'dobe'
                         else Path.home() / '.studio/runtime')
    prog = 'dope' if product == 'dobe' else 'studio-runtime'
    epilog = f'Run "{prog} help advanced" for the advanced commands.'
    if product == 'dobe' and not checkout:
        epilog += ' Service installation and management: dope local --help'
    parser = argparse.ArgumentParser(prog=prog, epilog=epilog,
        description='Make and revise creative files with local engines. Every job runs in a network-deny sandbox.')
    # DOPE_STATE_DIR is the public name; DOBE_STATE_DIR keeps working for existing installs.
    state_env = (os.environ.get('DOPE_STATE_DIR') or os.environ.get('DOBE_STATE_DIR') if product == 'dobe'
                 else os.environ.get('STUDIO_STATE_DIR'))
    parser.add_argument("--state", default=state_env or str(default_state))
    sub = parser.add_subparsers(dest="command", required=True, metavar="{" + ",".join(USER_COMMANDS) + "}")
    add_parser = sub.add_parser

    def add_command(name, **kwargs):
        # User commands carry a help line; advanced commands stay out of the top-level help.
        if name in USER_COMMANDS:
            kwargs["help"] = USER_COMMANDS[name]
        else:
            kwargs.pop("help", None)
            kwargs.setdefault("description", ADVANCED_COMMANDS[name])
        return add_parser(name, **kwargs)
    sub.add_parser = add_command
    from . import cloud
    cloud.parser(sub)
    from . import agent
    agent.add_parser(sub)
    from . import usage_cli
    usage_cli.add_parser(sub)
    holds = sub.add_parser("attempt-holds"); holds.add_argument("--after")
    reconciliation = sub.add_parser("reconcile-attempt")
    reconciliation.add_argument("job"); reconciliation.add_argument("--attempt", type=int, required=True)
    reconciliation.add_argument("--apply", action="store_true")
    reconciliation.add_argument("--confirm-local-origin", action="store_true")
    create = sub.add_parser("create-project"); create.add_argument("name")
    project = sub.add_parser("project"); project.add_argument("id")
    projects = sub.add_parser("projects"); projects.add_argument("--after")
    state = sub.add_parser("project-state"); state.add_argument("project"); state.add_argument("project_state", choices=('active', 'archived'))
    deletion = sub.add_parser("delete-project-artifacts"); deletion.add_argument("project"); deletion.add_argument("--apply", action='store_true')
    erasure = sub.add_parser("erase-project"); erasure.add_argument("project"); erasure.add_argument("--apply", action='store_true')
    submit = sub.add_parser("submit")
    submit.add_argument("project")
    submit.add_argument("operation", choices=capabilities.OPERATIONS, metavar="OPERATION",
                        help=f'An operation name; run "{prog} capabilities" to list them')
    submit.add_argument("--parameters", required=True, metavar="JSON",
                        help='Inline JSON (starting with "{"), a JSON file path, or - to read stdin')
    submit.add_argument("--key", required=True); submit.add_argument("--source")
    submit.add_argument("--timeout", type=float, default=600)
    submit.add_argument('--usage-workflow', help='Account for all job attempts in this usage workflow')
    for name in ("job", "cancel", "events", "revision"):
        cmd = sub.add_parser(name); cmd.add_argument("id")
    export = sub.add_parser("checkout"); export.add_argument("revision"); export.add_argument("destination")
    retry = sub.add_parser("retry"); retry.add_argument("job"); retry.add_argument("--key", required=True)
    asset = sub.add_parser("import-asset"); asset.add_argument("project"); asset.add_argument("source")
    imported = sub.add_parser("import-project"); imported.add_argument("bundle"); imported.add_argument("name")
    worker = sub.add_parser("worker"); worker.add_argument("--once", action="store_true")
    worker.add_argument("--idle-exit", type=float, metavar="SECONDS",
                        help="stop after this many seconds without work")
    sub.add_parser("recover")
    sub.add_parser("mcp")
    sub.add_parser("capabilities")
    describe = sub.add_parser("describe")
    describe.add_argument("operation", nargs="?"); describe.add_argument("--all", action="store_true", help="Describe every operation")
    sub.add_parser("doctor")
    sub.add_parser("rules")
    topic = sub.add_parser("help"); topic.add_argument("topic", nargs="?", help='"advanced", or a command name')
    construct=sub.add_parser("construct");construct.add_argument("action",choices=["plan"]);construct.add_argument("--spec",required=True)
    production=sub.add_parser("production");production.add_argument("action",choices=["plan"]);production.add_argument("--spec",required=True)
    synthesis=sub.add_parser("synthesis");synthesis.add_argument("action",choices=["plan"]);synthesis.add_argument("--spec",required=True)
    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("--apply", action="store_true")
    cleanup.add_argument("--older-than-hours", type=float, default=24)
    policy = sub.add_parser("limits")
    from . import limits
    for name in limits.DEFAULTS:
        policy.add_argument("--" + name.replace("_", "-"), type=int)
    args = parser.parse_args(argv)
    if args.command == "help":
        if args.topic == "advanced":
            sys.stdout.write(advanced_help(prog))
        elif args.topic in sub.choices and args.topic != "help":
            sub.choices[args.topic].print_help()
        elif args.topic is None:
            parser.print_help()
        else:
            parser.error(f'unknown help topic {args.topic!r}; try "advanced" or a command name')
        return 0
    try:
        if args.command == "cloud":
            return cloud.run(args, product)
        if args.command == "synthesis":
            from .synthesis import plan
            print(json.dumps(plan(json.loads(Path(args.spec).read_text())),sort_keys=True));return 0
        if args.command == "production":
            from .production import plan
            print(json.dumps(plan(json.loads(Path(args.spec).read_text())),sort_keys=True));return 0
        if args.command == "construct":
            from .construction import plan
            print(json.dumps(plan(json.loads(Path(args.spec).read_text())),sort_keys=True));return 0
        if args.command == "doctor":
            from .doctor import report
            print(json.dumps(report(args.state), sort_keys=True)); return 0
        if args.command == "rules":
            from . import rules
            print(json.dumps(rules.describe(), sort_keys=True)); return 0
        if args.command == "describe":
            from . import descriptors
            if args.all == bool(args.operation):
                raise ValueError('give one OPERATION or --all')
            result = descriptors.describe_all() if args.all else descriptors.describe(args.operation)
            print(json.dumps(result, sort_keys=True)); return 0
        store = Store(args.state)
        if args.command == "mcp":
            from .mcp import serve
            serve(store, product=product, on_submit=(lambda: on_demand_worker.ensure(store.root)) if checkout else None)
            return 0
        if args.command == "usage": result = usage_cli.command(store,args)
        elif args.command == "agent": result = agent.command(store,args)
        elif args.command == "create-project": result = store.create_project("local", args.name)
        elif args.command == "attempt-holds":
            from .reconciliation import list_holds
            result = list_holds(store, 'local', args.after)
        elif args.command == "reconcile-attempt":
            from .reconciliation import reconcile
            result = reconcile(store, 'local', args.job, args.attempt, args.apply, args.confirm_local_origin)
        elif args.command == "project": result = store.get_project("local", args.id)
        elif args.command == "projects": result = store.projects("local", args.after)
        elif args.command == "project-state":
            from .projects import set_state
            result = set_state(store, 'local', args.project, args.project_state)
        elif args.command == "delete-project-artifacts":
            from .projects import delete_artifacts
            result = delete_artifacts(store, 'local', args.project, args.apply)
        elif args.command == "erase-project":
            from .erasure import erase_project
            result = erase_project(store, 'local', args.project, args.apply)
        elif args.command == "submit":
            parameters = read_parameters(args.parameters)
            from . import rules
            rules.check_submit(store, "local", args.project, args.operation, parameters, args.source, args.key)
            result = store.submit("local", args.project, args.operation, parameters, args.key, args.source, args.timeout, usage_workflow=args.usage_workflow)
        elif args.command == "job": result = store.get_job("local", args.id)
        elif args.command == "cancel": result = store.cancel("local", args.id)
        elif args.command == "events": result = store.events("local", args.id)
        elif args.command == "revision":
            from .rules import with_native_document
            result = with_native_document(store.get_revision("local", args.id))
        elif args.command == "checkout": result = store.checkout("local", args.revision, args.destination)
        elif args.command == "recover": result = {"reconciled": store.recover("local")}
        elif args.command == "capabilities":
            from .capacity import describe
            result = {**capabilities.describe(product=product), "storage": describe(store.root)}
        elif args.command == "cleanup":
            from .maintenance import collect
            result = collect(store, args.apply, args.older_than_hours)
        elif args.command == "limits":
            changes = {name: getattr(args, name) for name in limits.DEFAULTS if getattr(args, name) is not None}
            result = limits.save(store.root, changes) if changes else limits.load(store.root)
        elif args.command == "retry": result = store.retry("local", args.job, args.key, capabilities.RETRY_SAFE)
        elif args.command == "import-asset": result = store.import_asset("local", args.project, args.source)
        elif args.command == "import-project": result = store.import_project("local", args.bundle, args.name)
        elif args.command == "worker":
            from .worker import Worker
            Worker(store).run(args.once, idle_exit=args.idle_exit)
            return 0
        if checkout and args.command in ('submit', 'retry'):
            on_demand_worker.ensure(store.root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as e:
        from .rules import RuleViolation
        error = e.payload() if isinstance(e, RuleViolation) else {"error": type(e).__name__, "message": str(e)}
        print(json.dumps(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
