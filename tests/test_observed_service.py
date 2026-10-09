import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from provenance import Store, Runtime, why, status
from provenance.clients.repo_repair.case import GOOD_SOURCE, BAD_SOURCE, TARGET, TEST_PATH, digest
from provenance.clients.repo_repair.errors import InvestigationError
from provenance.clients.repo_repair.process import ProcessResult
from provenance.clients.repo_repair.verifier import TestResult
from provenance.clients.repo_repair import openai_worker
from provenance.clients.observed_service.agent import RecordedServiceAgent, OpenAIServiceAgent, tools
from provenance.clients.observed_service.experiment import run_experiment, service_policy, prepare_service, ServiceVerifier
from provenance.clients.observed_service.service import READINGS
from tests.test_investigation_openai import FakeResponse, api_response


def steps(assessment='regression', patch_content=GOOD_SOURCE.decode()):
    return [{'tool': name, 'arguments': {}} for name in ('read_logs', 'read_source', 'read_diff', 'run_tests')] + [
        {'tool': 'finish', 'arguments': {'assessment': assessment, 'claim_statement': 'Assessment of the current deployed sensor behavior.',
         'evidence_aliases': ['logs_current', 'source_current', 'deployment_diff', 'current_full_suite'],
         'patch_content': patch_content, 'summary': 'Conclusion grounded in operational logs and current source.'}}]


class FakeServiceVerifier:
    def __init__(self):
        self.image_id = 'sha256:'+'1'*64
        self.events = []
    def preflight(self):
        return self.image_id
    def test(self, snapshot, case, suite):
        passed = snapshot.files[TARGET] == GOOD_SOURCE
        self.events.append(('test', snapshot.revision, passed))
        return TestResult(suite, self.image_id, snapshot.snapshot_hash, snapshot.file_hashes[TARGET],
                          1 if suite == 'targeted_tests' else 8, 0 if passed else 1, 0,
                          0 if passed else 1, 1, 'pass' if passed else 'fail', '', '')
    def run_service(self, snapshot, case):
        current_head = __import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], cwd=case.repository).decode().strip()
        assert current_head == snapshot.revision
        good = snapshot.files[TARGET] == GOOD_SOURCE
        self.events.append(('service', snapshot.revision, good))
        entries = [{'event': 'reading_processed', 'sequence': i, 'timestamp': '2026-10-07T00:00:00+00:00',
                    'revision': snapshot.revision, 'source_hash': snapshot.file_hashes[TARGET], 'input': value,
                    'lower': 0, 'upper': 100, 'output': max(0, min(value, 100)) if good else max(0, value)}
                   for i, value in enumerate(READINGS)]
        stdout = ''.join(json.dumps(entry)+'\n' for entry in entries)
        return {'revision': snapshot.revision, 'snapshot_hash': snapshot.snapshot_hash,
                'source_hash': snapshot.file_hashes[TARGET], 'image_id': self.image_id,
                'runner_hash': digest(Path('provenance/clients/observed_service/service.py').read_bytes()),
                'stdout_hash': digest(stdout.encode()), 'stdout': stdout, 'entries': entries, 'executor': 'unit-test-double'}


class ObservedServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/private/tmp' if Path('/private/tmp').is_dir() else None)
        self.root = Path(self.temporary.name).resolve() / 'case'
        self.verifier = FakeServiceVerifier()
    def tearDown(self):
        self.temporary.cleanup()
    def run_case(self, responses=None, scenario='regression', budget=8):
        return run_experiment(self.root, RecordedServiceAgent(steps() if responses is None else responses), self.verifier, scenario, budget)
    def test_report_is_utf8_under_an_ascii_default_text_encoding(self):
        original_open = Path.open
        def restrictive_open(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
            if path.name == 'report.md' and 'w' in mode and encoding in (None, 'locale'):
                encoding = 'ascii'
            return original_open(path, mode, buffering, encoding, errors, newline)
        with patch.object(Path, 'open', restrictive_open):
            try:
                report = self.run_case()
            except UnicodeError as error:
                self.fail('Report writing depends on the default text encoding: ' + str(error))
        self.assertEqual(report['outcome'], 'ACCEPTED', report['reason'])
        saved = (self.root / 'report.md').read_bytes().decode('utf-8')
        self.assertIn('Evidence → Claim → ProposedAction', saved)
        self.assertIn('Effects', saved)
    def test_patch_artifact_preserves_utf8_candidate_text(self):
        candidate = GOOD_SOURCE.decode().replace('    return', '    """Réparation → bornes."""\n    return')
        report = self.run_case(steps(patch_content=candidate))
        self.assertEqual(report['outcome'], 'REFUSED')  # The byte-matching test double rejects this variant.
        saved = (self.root / 'artifacts/repair.patch').read_bytes().decode('utf-8')
        self.assertIn('Réparation → bornes.', saved)
    def test_invalid_contract_bytes_return_structured_baseline_error(self):
        contract = self.root / 'repository/README.md'
        class EditingAgent(RecordedServiceAgent):
            def step(self, *args, **kwargs):
                result = super().step(*args, **kwargs)
                contract.write_bytes(b'\xff')
                return result
        try:
            report = run_experiment(self.root, EditingAgent(steps()), self.verifier)
        except UnicodeError as error:
            self.fail('Malformed contract bytes escaped the baseline guard: ' + str(error))
        self.assertEqual(report['outcome'], 'ERROR')
        self.assertEqual(report['error']['code'], 'BASELINE_CHANGED')
        saved = json.loads((self.root / 'report.json').read_bytes())
        self.assertEqual(saved['error']['code'], 'BASELINE_CHANGED')
        self.assertIsNone(saved['effect_id'])
    def test_working_run_precedes_change_and_current_logs_expose_regression(self):
        report = self.run_case()
        self.assertEqual(report['outcome'], 'ACCEPTED', report['reason'])
        service_events = [e for e in self.verifier.events if e[0] == 'service']
        self.assertEqual([e[2] for e in service_events], [True, False])
        self.assertNotEqual(service_events[0][1], service_events[1][1])
        self.assertEqual(report['service_runs'][0]['outputs'], [12, 0, 50, 100, 100, 100])
        self.assertEqual(report['service_runs'][1]['outputs'], [12, 0, 50, 100, 125, 200])
        self.assertEqual((self.root/'repository'/TARGET).read_bytes(), BAD_SOURCE)
        with Store(self.root/'history.db') as store:
            self.assertEqual(status(store, report['evidence']['logs_before'], 'execution'), 'VALID')
            self.assertTrue(all(store.validate(i).ok for i in store.all_ids()))
            claim = store.get(report['claim_id'])
            self.assertEqual(claim.payload['input_hash'], digest((self.root/'agent-view/step-5/input.json').read_bytes()))
            trace = why(store, report['effect_id'], 'execution')
            self.assertTrue(all(value == 'VALID' for value in trace.statuses.values()))
            self.assertEqual(sum(store.get(i).kind == 'Effect' for i in store.all_ids()), 1)
            effect = store.get(report['effect_id'])
            checks = tuple(p.node_id for p in effect.parents if p.role == 'verification')
            retry = Runtime(store, service_policy(), lambda: datetime.now(timezone.utc)).commit(report['action_id'], checks, report['authority_id'])
            self.assertTrue(retry.reused)
            self.assertEqual(retry.effect_id, report['effect_id'])
    def test_initial_question_does_not_reveal_fault_or_scenario(self):
        self.run_case()
        initial = json.loads((self.root/'agent-view/step-1/input.json').read_text())
        self.assertEqual(len(initial), 1)
        for word in ('regression', 'upper', 'broken', 'human_hint', '125', '200'):
            self.assertNotIn(word, initial[0]['content'])
        source_result = json.loads((self.root/'agent-view/step-2/result.json').read_text())
        self.assertEqual({e['alias'] for e in source_result}, {'source_current', 'service_contract'})
    def test_healthy_control_has_no_action_or_effect(self):
        report = self.run_case(steps('healthy', None), 'healthy')
        self.assertEqual(report['outcome'], 'HEALTHY', report['reason'])
        self.assertIsNone(report['action_id'])
        self.assertIsNone(report['effect_id'])
        self.assertEqual(report['service_runs'][0]['revision'], report['service_runs'][1]['revision'])
    def test_false_alarm_and_missed_regression_are_visible_failures(self):
        report = self.run_case(steps('healthy', None))
        self.assertEqual(report['outcome'], 'MISSED')
        self.assertIsNone(report['effect_id'])
        self.root = self.root.parent / 'second'
        report = self.run_case(steps(), 'healthy')
        self.assertEqual(report['outcome'], 'FALSE_ALARM')
        self.assertIsNone(report['effect_id'])
    def test_detection_without_patch_is_reported_without_receipt(self):
        report = self.run_case(steps('regression', None))
        self.assertEqual(report['outcome'], 'DETECTED')
        self.assertIsNone(report['effect_id'])
    def test_wrong_changed_patch_fails_verification_and_receipt_gate(self):
        report = self.run_case(steps('regression', 'def clamp(value, lower, upper):\n    return lower\n'))
        self.assertEqual(report['outcome'], 'REFUSED')
        self.assertIsNone(report['authority_id'])
        self.assertIsNone(report['effect_id'])
    def test_step_budget_and_unknown_tool_cannot_execute_arbitrary_commands(self):
        report = self.run_case([{'tool': 'read_logs', 'arguments': {}}], budget=1)
        self.assertEqual(report['outcome'], 'UNRESOLVED')
        self.root = self.root.parent / 'unknown'
        report = self.run_case([{'tool': 'shell', 'arguments': {'command': 'touch forbidden'}}])
        self.assertEqual(report['error']['code'], 'TOOL_REQUEST')
        self.assertFalse((self.root/'forbidden').exists())
    def test_tool_arguments_and_finish_aliases_are_validated(self):
        report = self.run_case([{'tool': 'read_source', 'arguments': {'path': '/etc/passwd'}}])
        self.assertEqual(report['error']['code'], 'TOOL_ARGUMENTS')
        self.root = self.root.parent / 'forged'
        responses = steps()
        responses[-1]['arguments']['authority_id'] = 'forged'
        report = self.run_case(responses)
        self.assertEqual(report['error']['code'], 'AGENT_PROTOCOL')
        self.assertIsNone(report['effect_id'])
    def test_finish_requires_collected_current_source_and_logs(self):
        responses = steps()
        responses[-1]['arguments']['evidence_aliases'] = ['deployment_diff']
        report = self.run_case(responses, budget=5)
        self.assertEqual(report['outcome'], 'UNRESOLVED')
        self.assertIsNone(report['claim_id'])
        result = json.loads((self.root/'agent-view/step-5/result.json').read_text())
        self.assertIn('logs_current', result['error'])
    def test_existing_case_preserved_before_preflight(self):
        self.root.mkdir()
        sentinel = self.root/'keep'
        sentinel.write_text('keep')
        report = self.run_case()
        self.assertEqual(report['error']['code'], 'CASE_EXISTS')
        self.assertEqual(sentinel.read_text(), 'keep')
        self.assertEqual(self.verifier.events, [])
    def test_revision_change_during_agent_call_refuses_stale_assessment(self):
        class ChangingAgent(RecordedServiceAgent):
            def step(self, transcript, aliases, output_dir):
                result = super().step(transcript, aliases, output_dir)
                (output_dir.parents[1]/'repository'/TARGET).write_bytes(GOOD_SOURCE)
                return result
        report = run_experiment(self.root, ChangingAgent(steps()), self.verifier)
        self.assertEqual(report['error']['code'], 'BASELINE_CHANGED')
        self.assertIsNone(report['effect_id'])
    def test_malformed_service_logs_cannot_become_observations(self):
        case = prepare_service(self.root)
        from provenance.clients.repo_repair.case import capture_snapshot
        verifier = ServiceVerifier()
        verifier.image_id = 'sha256:'+'1'*64
        with patch('provenance.clients.observed_service.experiment.run_process', return_value=ProcessResult(0,b'{}\n',b'',1,False,False)), patch.object(verifier, '_cleanup'):
            with self.assertRaises(InvestigationError) as raised:
                verifier.run_service(capture_snapshot(case, case.good_revision), case)
        self.assertEqual(raised.exception.code, 'SERVICE_LOG')


class ServiceApiTests(unittest.TestCase):
    def invoke(self, output, **changes):
        envelope = api_response(output=output, **changes)
        with patch.object(openai_worker, 'load_key', return_value='unit-test-key'), patch.object(openai_worker.http.client, 'HTTPSConnection') as factory:
            factory.return_value.getresponse.return_value = FakeResponse(json.dumps(envelope).encode())
            result = openai_worker.invoke({'mode': 'tool_step', 'model': 'gpt-4.1-mini', 'instructions': 'investigate', 'input': [{'role': 'user', 'content': 'check'}], 'tools': tools()})
            return result, json.loads(factory.return_value.request.call_args.kwargs['body'])
    def test_native_strict_function_request_returns_one_named_call(self):
        call = {'type': 'function_call', 'name': 'read_logs', 'call_id': 'call-test', 'arguments': '{}', 'status': 'completed'}
        result, body = self.invoke([call])
        self.assertEqual(result['tool_call']['name'], 'read_logs')
        self.assertEqual(body['tool_choice'], 'required')
        self.assertFalse(body['parallel_tool_calls'])
        self.assertFalse(body['store'])
        self.assertTrue(all(t['strict'] for t in body['tools']))
        self.assertEqual({t['name'] for t in body['tools']}, {'read_logs', 'read_source', 'read_diff', 'run_tests', 'finish'})
    def test_unexpected_multiple_incomplete_or_unknown_tools_fail_closed(self):
        call = {'type': 'function_call', 'name': 'read_logs', 'call_id': 'call-test', 'arguments': '{}'}
        for output in ([dict(call, name='shell')], [call, call], [dict(call, status='incomplete')], [{'type': 'web_search_call'}], []):
            with self.subTest(output=output), self.assertRaises(openai_worker.ApiFailure):
                self.invoke(output)
    def test_original_proposal_only_mode_still_rejects_function_calls(self):
        from tests.test_investigation_openai import OpenAIWorkerTests
        with self.assertRaises(openai_worker.ApiFailure):
            OpenAIWorkerTests().invoke(json.dumps(api_response(output=[{'type':'function_call', 'name':'read_logs', 'call_id':'call-test', 'arguments':'{}'}])).encode())

    def test_reasoning_continuation_is_rejected_without_persisting_reasoning(self):
        with self.assertRaises(openai_worker.ApiFailure) as raised:
            self.invoke([{'type': 'reasoning', 'summary': [{'text': 'private reasoning'}]}])
        self.assertEqual(raised.exception.code, 'API_MODEL')
        self.assertNotIn('private reasoning', str(raised.exception))

    def test_api_adapter_sends_collected_transcript_and_saves_bounded_call(self):
        transcript = [{'role': 'user', 'content': 'check service'}]
        call = {'type': 'function_call', 'name': 'read_logs', 'call_id': 'call-test', 'arguments': '{}'}
        with tempfile.TemporaryDirectory() as directory:
            agent = OpenAIServiceAgent()
            agent.ready = True
            with patch.object(agent, '_request', return_value=({'tool_call': call, 'metadata': {'model': 'gpt-4.1-mini', 'response_id': 'resp-test', 'unexpected': 'ignored'}}, 12)) as request:
                actual, arguments, metadata = agent.step(transcript, (), Path(directory)/'step')
            self.assertEqual(actual, call)
            self.assertEqual(arguments, {})
            self.assertTrue(metadata['tools_exposed'])
            self.assertNotIn('unexpected', metadata)
            self.assertEqual(request.call_args.args[0]['input'], transcript)
            self.assertEqual(request.call_args.args[0]['mode'], 'tool_step')

    def test_api_adapter_rejects_duplicate_function_argument_keys(self):
        call = {'type': 'function_call', 'name': 'read_logs', 'call_id': 'call-test', 'arguments': '{"x":1,"x":2}'}
        with tempfile.TemporaryDirectory() as directory:
            agent = OpenAIServiceAgent()
            agent.ready = True
            with patch.object(agent, '_request', return_value=({'tool_call': call, 'metadata': {}}, 1)):
                from provenance import ProvenanceError
                with self.assertRaises(ProvenanceError):
                    agent.step([], (), Path(directory)/'step')
