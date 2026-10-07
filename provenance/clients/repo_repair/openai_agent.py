"""OpenAI Responses adapter: structured text only; no model-accessible tools."""
import re
import sys
from pathlib import Path
from ...errors import ProvenanceError
from ...format import canonical_json, parse_json
from .agent import PROMPT, _prepare, _save
from .contract import AgentRun, decode_decision, response_schema
from .errors import fail
from .process import run_process

DEFAULT_MODEL = 'gpt-4.1-mini'


class OpenAIAgent:
    backend, live = 'openai', True

    def __init__(self, model=None):
        self.model, self.ready = model or DEFAULT_MODEL, False

    def _request(self, value, cwd, stage):
        worker = Path(__file__).with_name('openai_worker.py').absolute()
        try:
            result = run_process((sys.executable, '-I', str(worker)), cwd, stdin=canonical_json(value),
                                 timeout=20 if stage == 'preflight' else 180, max_output=1048576)
        except OSError: fail('API_WORKER', stage, 'Could not start the bounded OpenAI request worker')
        if result.returncode or result.timed_out or result.output_exceeded:
            fail('API_WORKER', stage, 'OpenAI request timed out, exceeded output limits, or failed; no automatic retry was made')
        try: data = parse_json(result.stdout)
        except ProvenanceError: fail('API_PROTOCOL', stage, 'OpenAI worker returned malformed output')
        if type(data) is not dict or data.get('status') not in ('ok', 'error'):
            fail('API_PROTOCOL', stage, 'OpenAI worker returned an unexpected response shape')
        if data['status'] == 'error':
            code, detail = data.get('code'), data.get('detail')
            if type(code) is not str or not re.fullmatch(r'API_[A-Z_]{1,40}', code) or type(detail) is not str or len(detail) > 2000:
                fail('API_PROTOCOL', stage, 'OpenAI worker returned invalid error metadata')
            fail(code, stage, detail)
        return data, result.elapsed_ms

    def preflight(self):
        if type(self.model) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', self.model):
            fail('API_MODEL', 'options', 'Model must be a nonempty model ID of at most 128 characters')
        self.ready = False
        data, _ = self._request({'mode': 'preflight', 'model': self.model}, Path.cwd(), 'preflight')
        if data.get('model') != self.model: fail('API_MODEL', 'preflight', 'Model-access check did not match the requested model')
        self.ready = True

    def propose(self, request, output_dir):
        if not self.ready: fail('AGENT_UNAVAILABLE', 'agent', 'OpenAI preflight has not succeeded')
        packet = _prepare(request, output_dir)
        data, elapsed = self._request({'mode': 'propose', 'model': self.model,
             'instructions': PROMPT.decode('utf-8'), 'input': packet.decode('utf-8'),
             'schema': response_schema(tuple(e.alias for e in request.evidence))}, output_dir, 'agent')
        text = data.get('output_text')
        if type(text) is not str: fail('API_PROTOCOL', 'agent', 'OpenAI worker returned no structured text')
        decision = decode_decision(text.encode('utf-8'), request.evidence)
        provider = data.get('metadata')
        if type(provider) is not dict: fail('API_PROTOCOL', 'agent', 'OpenAI worker returned no provider metadata')
        allowed = {'model', 'response_id', 'request_id', 'tokens'}
        metadata = {name: value for name, value in provider.items() if name in allowed}
        metadata.update(requested_model=self.model, elapsed_ms=elapsed, tools_exposed=False)
        return _save(output_dir, AgentRun(decision, self.backend, self.live, metadata))
