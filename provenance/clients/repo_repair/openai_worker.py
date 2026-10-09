"""Standalone bounded HTTPS worker. Emits selected text/metadata, never raw API output."""
import http.client
import json
import os
import re
import ssl
import sys
from urllib.parse import quote

LIMIT = 1048576
MODEL_PATTERN = r'[A-Za-z0-9_.:-]{1,128}'


class ApiFailure(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(detail)


def load_key():
    key = os.environ.get('OPENAI_API_KEY')
    if key is None and os.name == 'nt':
        # Read the normal user environment so configuring a key does not require
        # restarting a long-running desktop process. No Codex auth files are read.
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as environment:
                key, kind = winreg.QueryValueEx(environment, 'OPENAI_API_KEY')
                if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ): return None
        except OSError: return None
    if type(key) is not str or not key.strip(): return None
    key = key.strip()
    if len(key) > 4096 or any(char.isspace() for char in key): return None
    return key


def _identifier(value):
    return value if type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) else None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ApiFailure('API_PROTOCOL', 'OpenAI returned duplicate JSON object keys')
        result[key] = value
    return result


def invoke(request):
    key = load_key()
    if not key: raise ApiFailure('API_KEY_MISSING', 'Configure OPENAI_API_KEY locally before using the OpenAI backend')
    model = request.get('model')
    if type(model) is not str or not re.fullmatch(MODEL_PATTERN, model):
        raise ApiFailure('API_MODEL', 'Model must be a nonempty model ID of at most 128 characters')
    mode = request.get('mode')
    if mode not in ('preflight', 'propose', 'tool_step'): raise ApiFailure('API_PROTOCOL', 'Unknown API worker operation')
    body = None
    method, path = 'GET', '/v1/models/' + quote(model, safe='')
    if mode == 'propose':
        payload = {'model': model, 'instructions': request['instructions'], 'input': request['input'],
                   'tools': [], 'tool_choice': 'none', 'parallel_tool_calls': False,
                   'store': False, 'stream': False, 'background': False, 'truncation': 'disabled',
                   'max_output_tokens': 4096,
                   'text': {'format': {'type': 'json_schema', 'name': 'repair_decision', 'strict': True, 'schema': request['schema']}}}
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        method, path = 'POST', '/v1/responses'
    elif mode == 'tool_step':
        payload = {'model': model, 'instructions': request['instructions'], 'input': request['input'],
                   'tools': request['tools'], 'tool_choice': 'required', 'parallel_tool_calls': False,
                   'store': False, 'stream': False, 'background': False, 'truncation': 'disabled',
                   'max_output_tokens': 4096}
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        method, path = 'POST', '/v1/responses'
    # Fixed official endpoint, standard TLS verification, no redirects/custom base URLs.
    connection = http.client.HTTPSConnection('api.openai.com', context=ssl.create_default_context(), timeout=20 if mode == 'preflight' else 180)
    try:
        connection.request(method, path, body=body, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            code = 'API_AUTH' if response.status in (401, 403) else 'API_RATE_LIMIT' if response.status == 429 else 'API_HTTP'
            # Provider error bodies can echo credentials/input. Do not read or persist them.
            raise ApiFailure(code, f'OpenAI returned HTTP {response.status}; no automatic retry was made')
        chunks, size = [], 0
        while chunk := response.read(min(65536, LIMIT + 1 - size)):
            chunks.append(chunk); size += len(chunk)
            if size > LIMIT: raise ApiFailure('API_OUTPUT_LIMIT', 'API response exceeds 1 MiB')
        try: data = json.loads(b''.join(chunks), object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError): raise ApiFailure('API_PROTOCOL', 'OpenAI returned malformed JSON') from None
        if type(data) is not dict: raise ApiFailure('API_PROTOCOL', 'OpenAI returned an unexpected response shape')
        if mode == 'preflight':
            if data.get('id') != model: raise ApiFailure('API_MODEL', 'Model-access check returned a different model ID')
            return {'status': 'ok', 'model': model}
        if data.get('status') != 'completed' or data.get('error') is not None:
            raise ApiFailure('API_INCOMPLETE', 'OpenAI did not complete the structured response')
        output = data.get('output')
        if type(output) is not list: raise ApiFailure('API_PROTOCOL', 'OpenAI returned no output list')
        texts, calls = [], []
        for item in output:
            if type(item) is not dict: raise ApiFailure('API_PROTOCOL', 'OpenAI returned an invalid output item')
            kind = item.get('type')
            if kind == 'reasoning':
                if mode == 'tool_step':
                    raise ApiFailure('API_MODEL', 'Reasoning-model tool continuations are unsupported; select gpt-4.1-mini')
                continue
            if mode == 'tool_step' and kind == 'function_call':
                if (item.get('status') not in (None, 'completed') or not _identifier(item.get('call_id'))
                        or item.get('name') not in {tool['name'] for tool in request['tools']}
                        or type(item.get('arguments')) is not str):
                    raise ApiFailure('API_PROTOCOL', 'Invalid bounded function call')
                calls.append({k: item[k] for k in ('type', 'call_id', 'name', 'arguments')})
                continue
            if kind != 'message': raise ApiFailure('API_TOOL_EVENT', 'Unexpected tool/output item from proposal-only API')
            if item.get('status', 'completed') != 'completed':
                raise ApiFailure('API_INCOMPLETE', 'OpenAI returned a noncompleted assistant message')
            if item.get('role') != 'assistant' or type(item.get('content')) is not list:
                raise ApiFailure('API_PROTOCOL', 'OpenAI returned an invalid assistant message')
            for content in item['content']:
                if type(content) is not dict: raise ApiFailure('API_PROTOCOL', 'OpenAI returned invalid message content')
                if content.get('type') == 'refusal': raise ApiFailure('API_REFUSAL', 'OpenAI refused the proposal request')
                if content.get('type') != 'output_text' or type(content.get('text')) is not str:
                    raise ApiFailure('API_PROTOCOL', 'OpenAI returned non-text message content')
                texts.append(content['text'])
        if mode == 'tool_step':
            if len(calls) != 1 or texts: raise ApiFailure('API_PROTOCOL', 'Expected exactly one bounded function call')
        elif len(texts) != 1 or not texts[0].strip(): raise ApiFailure('API_PROTOCOL', 'Expected one final structured text response')
        actual_model = _identifier(data.get('model'))
        if not actual_model: raise ApiFailure('API_PROTOCOL', 'Response omitted a usable model identifier')
        usage = data.get('usage')
        usage = usage if type(usage) is dict else {}
        tokens = {k: v for k, v in usage.items() if k in ('input_tokens', 'output_tokens', 'total_tokens') and type(v) is int and 0 <= v <= 2**53-1}
        details = usage.get('input_tokens_details')
        cached = details.get('cached_tokens') if type(details) is dict else None
        if type(cached) is int and 0 <= cached <= 2**53-1: tokens['cached_input_tokens'] = cached
        return {'status': 'ok', **({'tool_call': calls[0]} if mode == 'tool_step' else {'output_text': texts[0]}), 'metadata': {'model': actual_model,
                'response_id': _identifier(data.get('id')), 'request_id': _identifier(response.getheader('x-request-id')), 'tokens': tokens}}
    finally: connection.close()


def main():
    try:
        raw = sys.stdin.buffer.read(1048577)
        if len(raw) > LIMIT: raise ApiFailure('API_INPUT_LIMIT', 'Worker input exceeds 1 MiB')
        request = json.loads(raw)
        if type(request) is not dict: raise ApiFailure('API_PROTOCOL', 'Invalid worker input')
        result = invoke(request)
    except ApiFailure as error:
        result = {'status': 'error', 'code': error.code, 'detail': error.detail}
    except (TimeoutError, OSError, http.client.HTTPException):
        result = {'status': 'error', 'code': 'API_NETWORK', 'detail': 'OpenAI HTTPS request failed or timed out; no automatic retry was made'}
    except Exception:
        # Unexpected transport/parse failures must not expose exception values or headers.
        result = {'status': 'error', 'code': 'API_PROTOCOL', 'detail': 'OpenAI worker could not process the response'}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8') + b'\n')
    return 0


if __name__ == '__main__': raise SystemExit(main())
