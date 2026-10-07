import json
import tempfile
import unittest
from pathlib import Path
from provenance import Store
from provenance.projection import status
from provenance.clients.repo_repair.agent import RecordedAgent
from provenance.clients.repo_repair.case import TARGET
from provenance.clients.repo_repair.coordinator import InvestigationOptions, run_investigation
from provenance.clients.repo_repair.errors import InvestigationError
from provenance.clients.repo_repair.verifier import TestResult, SUITES
from tests.investigation_support import decision_dict, CORRECT_PATCH, WRONG_PATCH


class DeterministicVerifier:
    """A unit-test double only. Never offered by the application CLI."""
    def preflight(self): return 'sha256:' + 'a' * 64
    def test(self, snapshot, case, suite):
        passed = snapshot.files[TARGET] == CORRECT_PATCH.encode()
        return TestResult(suite, self.preflight(), snapshot.snapshot_hash, snapshot.file_hashes[TARGET],
                          SUITES[suite], 0 if passed else 1, 0, 0 if passed else 1, 1, 'pass' if passed else 'fail', '{}', '')


class TrackingAgent(RecordedAgent):
    def __init__(self, responses):
        super().__init__(tuple(json.dumps(d).encode() for d in responses))
        self.requests = []
    def propose(self, request, output_dir):
        self.requests.append(request)
        return super().propose(request, output_dir)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.case_dir = Path(self.tmp.name) / 'case'
    def tearDown(self): self.tmp.cleanup()
    def run_case(self, responses, **kwargs):
        agent = TrackingAgent(responses)
        report = run_investigation(InvestigationOptions(self.case_dir, **kwargs), agent, DeterministicVerifier())
        return report, agent

    def test_correct_wrong_and_no_proposal_outcomes(self):
        report, _ = self.run_case([decision_dict()])
        self.assertEqual(report.outcome, 'ACCEPTED')
        self.assertIsNotNone(report.effect_id)
        self.assertFalse(report.live_agent)
        self.assertEqual(len(report.rounds), 1)
        self.assertTrue((self.case_dir / 'report.json').exists())
        self.case_dir = Path(self.tmp.name) / 'wrong'
        wrong = 'def clamp(value, lower, upper):\n    return lower\n'
        report, agent = self.run_case([decision_dict(wrong)] * 3)
        self.assertEqual(report.outcome, 'REFUSED')
        self.assertIsNone(report.effect_id)
        self.assertEqual(len(agent.requests), 3)
        self.case_dir = Path(self.tmp.name) / 'null'
        report, _ = self.run_case([decision_dict(None)])
        self.assertEqual(report.outcome, 'UNRESOLVED')
        self.assertIsNone(report.action_id)
        self.case_dir = Path(self.tmp.name) / 'noop'
        report, _ = self.run_case([decision_dict(WRONG_PATCH)])
        self.assertEqual(report.outcome, 'UNRESOLVED')

    def test_prerequisites_fail_before_case_or_inference(self):
        class MissingVerifier(DeterministicVerifier):
            def preflight(self): raise InvestigationError('DOCKER_UNAVAILABLE', 'preflight', 'missing')
        agent = TrackingAgent([decision_dict()])
        report = run_investigation(InvestigationOptions(self.case_dir), agent, MissingVerifier())
        self.assertEqual(report.outcome, 'ERROR')
        self.assertEqual(report.error['stage'], 'preflight')
        self.assertFalse(self.case_dir.exists())
        self.assertFalse(agent.requests)

    def test_stale_source_refuses_old_action_and_accepts_fresh_evidence(self):
        report, agent = self.run_case([decision_dict(), decision_dict(evidence=('source_current', 'human_hint'))],
                                      scenario='stale-source', hint='Check the source revision')
        self.assertEqual(report.outcome, 'ACCEPTED')
        self.assertEqual(report.old_action['status'], 'STALE')
        self.assertEqual(report.old_action['gate_outcome'], 'REFUSED')
        self.assertNotIn('human_hint', [e.alias for e in agent.requests[0].evidence])
        self.assertNotIn('source', [e.alias for e in agent.requests[1].evidence])
        with Store(self.case_dir / 'history.db') as store:
            old_source = report.evidence['source']
            self.assertEqual(status(store, old_source, 'execution'), 'INVALID')
            new_claim = store.get(report.claim_id)
            self.assertNotIn(report.rounds[0]['claim_id'], [p.node_id for p in new_claim.parents])
            self.assertNotIn(old_source, [p.node_id for p in new_claim.parents])
            self.assertEqual(len([i for i in store.all_ids() if store.get(i).kind == 'Effect']), 1)

    def test_human_hint_is_not_automatic_invalidation(self):
        report, _ = self.run_case([decision_dict(), decision_dict(evidence=('source_current', 'human_hint'))], hint='I suspect something else')
        self.assertEqual(report.outcome, 'ACCEPTED')
        with Store(self.case_dir / 'history.db') as store:
            self.assertEqual(status(store, report.evidence['source'], 'execution'), 'VALID')
            self.assertFalse(any(store.get(i).kind == 'Invalidation' for i in store.all_ids()))
            human = store.get(report.evidence['human_hint'])
            self.assertEqual(human.payload['reported_statement'], 'I suspect something else')

    def test_partial_error_retains_first_claim_and_evidence(self):
        report, _ = self.run_case([decision_dict()], hint='Check the source')
        self.assertEqual(report.outcome, 'ERROR')
        self.assertEqual(report.error['code'], 'RESPONSE_EXHAUSTED')
        self.assertEqual(len(report.rounds), 1)
        self.assertTrue((self.case_dir / 'history.db').exists())
        self.assertTrue((self.case_dir / 'error.json').exists())

    def test_invalid_options_and_passing_baseline_do_not_use_agent(self):
        agent = TrackingAgent([decision_dict()])
        report = run_investigation(InvestigationOptions(self.case_dir, max_rounds=4), agent, DeterministicVerifier())
        self.assertEqual(report.error['stage'], 'options')
        self.assertFalse(agent.requests)
        class PassingBaseline(DeterministicVerifier):
            def test(self, snapshot, case, suite):
                original = super().test(snapshot, case, suite)
                from dataclasses import replace
                return replace(original, returncode=0, failures=0, outcome='pass')
        report = run_investigation(InvestigationOptions(self.case_dir), agent, PassingBaseline())
        self.assertEqual(report.error['code'], 'BASELINE_RESULT')
        self.assertFalse(agent.requests)
