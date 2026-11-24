"""Explicit hosted CLI calls through the same authenticated MCP service.

No database credentials, implicit payment acceptance or automatic mutation
retries. Bearer tokens come from the environment and never appear in arguments.
"""
import ipaddress
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parser(subparsers):
    cloud = subparsers.add_parser('cloud', help='Use an explicitly configured hosted workspace')
    cloud.add_argument('--url', required=True, help='HTTPS service origin, without an endpoint path')
    cloud.add_argument('--workspace', required=True)
    cloud.add_argument('--allow-loopback-http', action='store_true', help='Local qualification only: allow numeric loopback HTTP')
    commands = cloud.add_subparsers(dest='cloud_command', required=True)
    for name in ('quote', 'submit'):
        p = commands.add_parser(name)
        p.add_argument('project'); p.add_argument('operation')
        p.add_argument('--parameters', required=True, help='JSON file')
        p.add_argument('--key', required=True); p.add_argument('--source')
        p.add_argument('--timeout', type=int, default=600)
        p.add_argument('--output-bytes', type=int, default=64*1024*1024)
        if name == 'quote':
            p.add_argument('--executor', required=True)
            p.add_argument('--currency', required=True)
            p.add_argument('--maximum-minor', required=True, type=int)
        else:
            p.add_argument('--quote', help='Explicitly accept the quoted request and usage maximum; required for paid work')
    for name in ('quote-status', 'job', 'cancel'):
        commands.add_parser(name).add_argument('id')
    retry = commands.add_parser('retry'); retry.add_argument('id'); retry.add_argument('--key', required=True)
    receipts = commands.add_parser('billing-receipts', help='Workspace owner: read saved billing evidence linked to a job')
    receipts.add_argument('id'); receipts.add_argument('--cursor', help='Continue a prior receipt page; restart without it for new observations')
    notices = commands.add_parser('billing-notices', help='Workspace owner: read saved refund, dispute and fraud notices')
    notices.add_argument('--cursor', help='Continue a prior notice page; restart without it for new notices')

    plan = commands.add_parser('plan-quote', help='Quote all named steps under one shared usage maximum')
    plan.add_argument('--document', required=True, help='Versioned plan JSON file')
    plan.add_argument('--key', required=True); plan.add_argument('--currency', required=True)
    plan.add_argument('--maximum-minor', required=True, type=int)
    for name in ('plan-status', 'plan-accept', 'plan-cancel'):
        commands.add_parser(name).add_argument('id')
    step = commands.add_parser('plan-step')
    step.add_argument('id'); step.add_argument('step')
    step.add_argument('--assets', help='JSON map of declared placeholders to uploaded asset IDs')


def call(url, workspace, token, name, arguments, *, allow_loopback_http=False):
    endpoint = urlsplit(url)
    if (not endpoint.hostname or endpoint.username is not None or endpoint.password is not None or
            endpoint.query or endpoint.fragment or endpoint.path not in ('', '/') or
            any(c.isspace() for c in url)):
        raise ValueError('cloud URL must be a service origin without credentials, path, query or fragment')
    if endpoint.scheme != 'https':
        try:
            loopback = ipaddress.ip_address(endpoint.hostname).is_loopback
        except ValueError:
            loopback = False
        if endpoint.scheme != 'http' or not allow_loopback_http or not loopback:
            raise ValueError('cloud requires HTTPS; HTTP is limited to explicitly enabled numeric loopback')
    if not isinstance(token, str) or not token or any(c.isspace() for c in token):
        raise ValueError('set the cloud bearer token environment variable')
    workspace = str(UUID(workspace))
    request_id = str(uuid4())
    body = json.dumps({'jsonrpc':'2.0','id':request_id,'method':'tools/call',
                       'params':{'name':name,'arguments':arguments}}, allow_nan=False).encode()
    if len(body)>1048576:
        raise ValueError('cloud request exceeds 1 MiB')
    address = urlunsplit((endpoint.scheme, endpoint.netloc, '/mcp/'+workspace, '', ''))
    request = Request(address, data=body, method='POST', headers={
        'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream',
        'MCP-Protocol-Version':'2025-06-18'})
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=30) as response:
            if response.headers.get_content_type()!='application/json':
                raise ValueError('cloud returned a non-JSON response')
            raw=response.read(4*1024*1024+1)
    except HTTPError as error:
        # In particular, redirects never forward credentials to another origin.
        raise ValueError('cloud request refused with HTTP '+str(error.code)) from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('cloud response unavailable; inspect the original idempotency key before retrying') from None
    if len(raw)>4*1024*1024:
        raise ValueError('cloud response exceeds 4 MiB')
    try:
        reply=json.loads(raw)
        if not isinstance(reply,dict) or reply.get('jsonrpc')!='2.0' or reply.get('id')!=request_id or 'error' in reply:
            raise ValueError()
        result=reply['result']; content=result['content']
        if not isinstance(content,list) or len(content)!=1 or content[0]['type']!='text':
            raise ValueError()
        value=json.loads(content[0]['text'])
    except (ValueError, KeyError, TypeError):
        raise ValueError('cloud returned an invalid tool response') from None
    return value, bool(result.get('isError'))


def read_json(path):
    with Path(path).open('rb') as source:
        raw = source.read(1048577)
    if len(raw) > 1048576:
        raise ValueError('request document exceeds 1 MiB')
    return json.loads(raw)


def run(args, product):
    command=args.cloud_command
    if command in ('quote','submit'):
        path=Path(args.parameters)
        with path.open('rb') as source:
            raw=source.read(1048577)
        if len(raw)>1048576:
            raise ValueError('parameters exceed 1 MiB')
        arguments={'project':args.project,'operation':args.operation,'parameters':json.loads(raw),
                   'idempotency_key':args.key,'timeout_seconds':args.timeout,'output_bytes':args.output_bytes}
        if args.source is not None: arguments['source_revision']=args.source
        if command=='quote':
            name='studio_quote_job'
            arguments.update(executor=args.executor,currency=args.currency,maximum_minor=args.maximum_minor)
        else:
            name='studio_submit_job'
            if args.quote is not None: arguments['quote']=args.quote
    elif command == 'billing-receipts':
        name = 'studio_get_billing_receipts'
        arguments = {'job': args.id}
        if args.cursor is not None:
            arguments['cursor'] = args.cursor
    elif command == 'billing-notices':
        name = 'studio_list_billing_notices'
        arguments = {} if args.cursor is None else {'cursor': args.cursor}
    elif command == 'plan-quote':
        name = 'studio_quote_plan'
        arguments = {'document': read_json(args.document), 'idempotency_key': args.key,
                     'currency': args.currency, 'maximum_minor': args.maximum_minor}
    elif command in ('plan-status', 'plan-accept', 'plan-cancel', 'plan-step'):
        name = {'plan-status': 'studio_get_plan', 'plan-accept': 'studio_accept_plan',
                'plan-cancel': 'studio_cancel_plan', 'plan-step': 'studio_submit_plan_step'}[command]
        arguments = {'plan': args.id}
        if command == 'plan-step':
            arguments['step'] = args.step
            if args.assets is not None:
                arguments['assets'] = read_json(args.assets)
    else:
        name={'quote-status':'studio_get_quote','job':'studio_get_job','cancel':'studio_cancel_job','retry':'studio_retry_job'}[command]
        arguments={'quote' if command=='quote-status' else 'job':args.id}
        if command=='retry': arguments['idempotency_key']=args.key
    token=os.environ.get('DOBE_CLOUD_TOKEN' if product=='dobe' else 'STUDIO_CLOUD_TOKEN')
    result, failed=call(args.url,args.workspace,token,name,arguments,allow_loopback_http=args.allow_loopback_http)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 1 if failed else 0
