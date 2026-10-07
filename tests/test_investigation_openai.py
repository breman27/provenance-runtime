import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from provenance.clients.repo_repair.case import Evidence
from provenance.clients.repo_repair.contract import AgentRequest
from provenance.clients.repo_repair.errors import InvestigationError
from provenance.clients.repo_repair.openai_agent import OpenAIAgent, DEFAULT_MODEL
from provenance.clients.repo_repair import openai_worker
from provenance.clients.repo_repair.process import ProcessResult
from tests.investigation_support import decision_dict


class FakeResponse:
    def __init__(self, body, status=200):
        self.data = io.BytesIO(body)
        self.status = status
    def read(self, size): return self.data.read(size)
    def getheader(self, name): return 'req-unit-test' if name == 'x-request-id' else None


def api_response(**changes):
    value = {'id': 'resp-test', 'model': DEFAULT_MODEL, 'status': 'completed', 'error': None,
             'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': json.dumps(decision_dict())}]}],
             'usage': {'input_tokens': 50, 'output_tokens': 60, 'input_tokens_details': {'cached_tokens': 10}}}
    value.update(changes)
    return value


class OpenAIWorkerTests(unittest.TestCase):
    def invoke(self, response, status=200, mode='propose'):
        with patch.object(openai_worker, 'load_key', return_value='unit-test-only-key'), patch.object(openai_worker.http.client, 'HTTPSConnection') as factory:
            connection = factory.return_value
            connection.getresponse.return_value = FakeResponse(response, status)
            result = openai_worker.invoke({'mode': mode, 'model': DEFAULT_MODEL, 'input': '{}', 'instructions': 'reason only', 'schema': {'type': 'object'}})
            return result, factory

    def test_request_has_no_tools_strict_schema_and_no_stored_state(self):
        result, factory = self.invoke(json.dumps(api_response()).encode())
        self.assertEqual(factory.call_args.args[0], 'api.openai.com')
        arguments = factory.return_value.request.call_args
        self.assertEqual(arguments.args[:2], ('POST', '/v1/responses'))
        body = json.loads(arguments.kwargs['body'])
        self.assertEqual(body['tools'], [])
        self.assertEqual(body['tool_choice'], 'none')
        self.assertFalse(body['store'])
        self.assertFalse(body['stream'])
        self.assertFalse(body['background'])
        self.assertEqual(body['truncation'], 'disabled')
        self.assertTrue(body['text']['format']['strict'])
        self.assertEqual(body['max_output_tokens'], 4096)
        self.assertNotIn('previous_response_id', body)
        self.assertNotIn('unit-test-only-key', json.dumps(result))
        self.assertEqual(result['metadata']['tokens']['cached_input_tokens'], 10)

    def test_reasoning_is_discarded_and_tool_items_are_rejected(self):
        output = [{'type': 'reasoning', 'summary': [{'text': 'private internal reasoning'}]}, *api_response()['output']]
        result, _ = self.invoke(json.dumps(api_response(output=output)).encode())
        self.assertNotIn('private internal reasoning', json.dumps(result))
        for kind in ('function_call', 'web_search_call', 'computer_call', 'shell_call'):
            with self.subTest(kind=kind), self.assertRaises(openai_worker.ApiFailure) as raised:
                self.invoke(json.dumps(api_response(output=[{'type': kind}])).encode())
            self.assertEqual(raised.exception.code, 'API_TOOL_EVENT')

    def test_refusal_incomplete_malformed_and_limits_fail_closed(self):
        refusal = [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]
        for data in (json.dumps(api_response(status='incomplete')).encode(), json.dumps(api_response(output=refusal)).encode(),
                     b'invalid', b'[]', b'x' * 1048577, json.dumps(api_response(output=[])).encode()):
            with self.subTest(data=data[:60]), self.assertRaises(openai_worker.ApiFailure): self.invoke(data)

    def test_http_errors_do_not_echo_provider_body_or_key(self):
        for status, code in ((401, 'API_AUTH'), (403, 'API_AUTH'), (429, 'API_RATE_LIMIT'), (500, 'API_HTTP')):
            with self.subTest(status=status), self.assertRaises(openai_worker.ApiFailure) as raised:
                self.invoke(b'Incorrect API key: unit-test-only-key; private request data', status)
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn('unit-test-only-key', str(raised.exception))
            self.assertNotIn('private request data', str(raised.exception))

    def test_preflight_only_queries_model_and_does_not_infer(self):
        result, factory = self.invoke(json.dumps({'id': DEFAULT_MODEL}).encode(), mode='preflight')
        self.assertEqual(factory.return_value.request.call_args.args[:2], ('GET', '/v1/models/' + DEFAULT_MODEL))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(factory.return_value.request.call_count, 1)

    def test_key_missing_and_invalid_models_make_no_request(self):
        with patch.object(openai_worker, 'load_key', return_value=None), patch.object(openai_worker.http.client, 'HTTPSConnection') as connection:
            with self.assertRaises(openai_worker.ApiFailure) as raised:
                openai_worker.invoke({'mode': 'preflight', 'model': DEFAULT_MODEL})
            self.assertEqual(raised.exception.code, 'API_KEY_MISSING')
            connection.assert_not_called()
        with patch.object(openai_worker, 'load_key', return_value='unit-test-key'), patch.object(openai_worker.http.client, 'HTTPSConnection') as connection:
            with self.assertRaises(openai_worker.ApiFailure): openai_worker.invoke({'mode': 'preflight', 'model': '../wrong'})
            connection.assert_not_called()


class OpenAIAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.request = AgentRequest('repair', 'clamp', (Evidence('source', 'unused', {'source_text': 'source'}),), (), 1)
    def tearDown(self): self.tmp.cleanup()
    def process(self, value, **changes):
        return ProcessResult(changes.get('returncode', 0), json.dumps(value).encode(), b'', 12,
                             changes.get('timed_out', False), changes.get('output_exceeded', False))

    def test_live_decision_host_metadata_and_bounded_worker(self):
        agent = OpenAIAgent()
        preflight = self.process({'status': 'ok', 'model': DEFAULT_MODEL})
        response = self.process({'status': 'ok', 'output_text': json.dumps(decision_dict()),
                                 'metadata': {'model': DEFAULT_MODEL, 'response_id': 'resp-test', 'request_id': 'req-test',
                                              'tokens': {'input_tokens': 1, 'output_tokens': 2}}})
        with patch('provenance.clients.repo_repair.openai_agent.run_process', side_effect=[preflight, response]) as execute:
            agent.preflight()
            run = agent.propose(self.request, self.root / 'round')
        self.assertTrue(run.live)
        self.assertEqual(run.backend, 'openai')
        self.assertEqual(run.metadata['model'], DEFAULT_MODEL)
        self.assertEqual(run.metadata['elapsed_ms'], 12)
        self.assertEqual(execute.call_args.kwargs['timeout'], 180)
        self.assertEqual(execute.call_args.kwargs['max_output'], 1048576)
        self.assertNotIn('API_KEY', execute.call_args.args[0])
        self.assertEqual({p.name for p in (self.root / 'round').iterdir()}, {'input.json', 'decision.json', 'metadata.json'})

    def test_worker_failure_timeout_and_overflow_do_not_admit_decision(self):
        for index, process in enumerate((self.process({'status': 'error', 'code': 'API_AUTH', 'detail': 'HTTP 401'}),
                                        self.process({}, timed_out=True), self.process({}, output_exceeded=True),
                                        self.process({}, returncode=1), self.process({'status': 'ok'}))):
            agent = OpenAIAgent()
            with patch('provenance.clients.repo_repair.openai_agent.run_process', side_effect=[self.process({'status': 'ok', 'model': DEFAULT_MODEL}), process]):
                agent.preflight()
                with self.assertRaises(InvestigationError): agent.propose(self.request, self.root / str(index))
            self.assertFalse((self.root / str(index) / 'decision.json').exists())

    def test_provider_cannot_assign_privileged_fields_or_identity(self):
        forged = dict(decision_dict(), live=True, passed=True)
        agent = OpenAIAgent()
        with patch('provenance.clients.repo_repair.openai_agent.run_process', side_effect=[self.process({'status': 'ok', 'model': DEFAULT_MODEL}),
             self.process({'status': 'ok', 'output_text': json.dumps(forged), 'metadata': {}})]):
            agent.preflight()
            with self.assertRaises(InvestigationError): agent.propose(self.request, self.root / 'round')

    def test_preflight_failure_prevents_proposal(self):
        agent = OpenAIAgent()
        with patch('provenance.clients.repo_repair.openai_agent.run_process', return_value=self.process({'status': 'error', 'code': 'API_KEY_MISSING', 'detail': 'Configure OPENAI_API_KEY'})):
            with self.assertRaises(InvestigationError): agent.preflight()
        with self.assertRaises(InvestigationError): agent.propose(self.request, self.root / 'round')
        self.assertFalse((self.root / 'round').exists())
