"""Bounded, non-retrying OpenAI Responses transport; no credentials in journals."""
import json
import os
import re
from pathlib import Path
import stat
import urllib.request
import urllib.error

MODEL = 'gpt-6-astra'
MAX_OUTPUT = 8192
MAX_INPUT = 64000
# USD per million = micro-USD per token. Snapshot: 2026-11-19 standard pricing.
INPUT_RATE, CACHED_RATE, OUTPUT_RATE = 10, 1, 50


class ProviderError(RuntimeError):
    def __init__(self,status,request_id,message):
        super().__init__(message)
        self.status=status;self.request_id=request_id


def credential_value(value):
    value=value.strip() if isinstance(value,str) else ''
    if not value or len(value)>16384 or any(not 33<=ord(character)<=126 for character in value):
        # HTTP libraries can include an invalid header's value in exceptions.
        # Reject it before constructing the Authorization header or any journal.
        raise ValueError('API credential must contain printable non-whitespace ASCII')
    return value


def key():
    value=os.environ.get('OPENAI_API_KEY')
    if value: return credential_value(value)
    path=Path.home()/'.config/adopecli-benchmark/openai-api-key'
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
            raise ValueError('API key file must be owned by this user with owner-only access')
        value=stream.read(16385).strip()
    return credential_value(value)


def cost(usage):
    input_tokens=usage['input_tokens'];output_tokens=usage['output_tokens']
    cached=usage.get('input_tokens_details',{}).get('cached_tokens',0)
    if any(type(n) is not int or n<0 for n in (input_tokens,output_tokens,cached)) or cached>input_tokens:
        raise ValueError('Invalid provider usage')
    details=usage.get('input_tokens_details',{})
    writes=details.get('cache_write_tokens',0)
    lifetimes=details.get('cache_write_tokens_details',{})
    short=lifetimes.get('ttl_30m_tokens',0);long=lifetimes.get('ttl_12h_tokens',0)
    if any(type(n) is not int or n<0 for n in (writes,short,long)) or short+long!=writes or cached+writes>input_tokens:
        raise ValueError('Invalid or unpriced cache write usage')
    # Standard GPT-6 Astra cache writes: $12.50 / $25 per million.
    # Calculate half-micro-USD units exactly, rounding up only the final charge.
    half_units=2*((input_tokens-cached-writes)*INPUT_RATE+cached*CACHED_RATE+output_tokens*OUTPUT_RATE)+short*25+long*50
    return (half_units+1)//2


class Provider:
    def __init__(self, credential=None):
        self.credential=credential_value(credential) if credential is not None else key()

    def post(self, endpoint, payload):
        request=urllib.request.Request('https://api.openai.com/v1/'+endpoint,
            data=json.dumps(payload,allow_nan=False).encode(),method='POST',
            headers={'Authorization':'Bearer '+self.credential,'Content-Type':'application/json'})
        # No automatic retries or configurable destination that could receive credentials.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError('Provider redirects are not permitted')
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=180) as response:
                raw=response.read(32*1024*1024+1)
                if len(raw)>32*1024*1024: raise ValueError('Provider response exceeds local evidence limit')
                return json.loads(raw),response.headers.get('x-request-id')
        except urllib.error.HTTPError as exc:
            raw=exc.read(8192)
            try:message=json.loads(raw).get('error',{}).get('message','Provider rejected request')
            except (ValueError,AttributeError):message='Provider rejected request'
            message=str(message).replace(self.credential,'[redacted]')
            message=re.sub(r'sk-[A-Za-z0-9_-]+','[redacted]',message)
            raise ProviderError(exc.code,exc.headers.get('x-request-id'),message[:1000]) from None

    def count(self, request):
        payload={k:v for k,v in request.items() if k in ('model','input','instructions','reasoning','text','tools','tool_choice','parallel_tool_calls','truncation')}
        response,request_id=self.post('responses/input_tokens',payload)
        tokens=response['input_tokens']
        if type(tokens) is not int or not 0<=tokens<=MAX_INPUT:
            raise ValueError('Selected context exceeds the 64000 input-token limit')
        return tokens,request_id

    def generate(self, request):
        return self.post('responses',request)


def decision(response):
    if response.get('status')!='completed':
        raise ValueError('Provider did not complete its decision')
    texts=[part['text'] for item in response.get('output',[]) if item.get('type')=='message'
           for part in item.get('content',[]) if part.get('type')=='output_text']
    if len(texts)!=1: raise ValueError('Expected one structured decision')
    value=json.loads(texts[0])
    if not isinstance(value,dict) or value.get('action') not in ('submit','inspect','accept','reject'):
        raise ValueError('Invalid coordinator decision')
    return value
