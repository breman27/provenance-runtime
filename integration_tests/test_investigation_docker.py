"""Explicit Docker acceptance. Missing prerequisites are errors, never skips."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from provenance import Store, Runtime, why
from provenance.clients.repo_repair.agent import RecordedAgent
from provenance.clients.repo_repair.case import (prepare_case, capture_snapshot, candidate_snapshot,
                                                 GOOD_SOURCE, BAD_SOURCE, TARGET, TEST_PATH, TEST_SOURCE)
from provenance.clients.repo_repair.coordinator import InvestigationOptions, run_investigation, fixture_policy
from provenance.clients.repo_repair.verifier import DockerVerifier
from provenance.clients.repo_repair.process import run_process
from tests.investigation_support import decision_dict


class DockerAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = DockerVerifier()
        cls.image_id = cls.verifier.preflight()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_real_baseline_correct_and_wrong_candidates(self):
        case = prepare_case(self.root / 'case')
        baseline = capture_snapshot(case, case.baseline_revision)
        failed = self.verifier.test(baseline, case, 'targeted_tests')
        self.assertEqual(failed.outcome, 'fail')
        self.assertFalse(failed.passed)
        candidate = candidate_snapshot(baseline, GOOD_SOURCE)
        targeted = self.verifier.test(candidate, case, 'targeted_tests')
        full = self.verifier.test(candidate, case, 'full_suite')
        self.assertTrue(targeted.passed, targeted.stderr)
        self.assertTrue(full.passed, full.stderr)
        self.assertEqual(full.tests_run, 8)
        self.assertEqual(full.image_id, self.image_id)
        wrong = candidate_snapshot(baseline, b'def clamp(value, lower, upper):\n    return lower\n')
        self.assertFalse(self.verifier.test(wrong, case, 'full_suite').passed)
        self.assertEqual((case.repository / TARGET).read_bytes(), BAD_SOURCE)
        self.assertEqual((case.repository / TEST_PATH).read_bytes(), TEST_SOURCE)
        self.assertEqual(capture_snapshot(case, case.baseline_revision).snapshot_hash, baseline.snapshot_hash)

    def test_recorded_normal_receipt_ancestry_and_retry(self):
        agent = RecordedAgent((json.dumps(decision_dict()).encode(),))
        report = run_investigation(InvestigationOptions(self.root / 'normal'), agent, self.verifier)
        self.assertEqual(report.outcome, 'ACCEPTED', report.reason)
        self.assertFalse(report.live_agent)
        with Store(self.root / 'normal' / 'history.db') as store:
            self.assertTrue(store.validate(report.effect_id).ok)
            trace = why(store, report.effect_id, 'execution')
            self.assertEqual(trace.statuses[report.effect_id], 'VALID')
            effect = store.get(report.effect_id)
            verifications = tuple(p.node_id for p in effect.parents if p.role == 'verification')
            runtime = Runtime(store, fixture_policy(), lambda: datetime.now(timezone.utc))
            retry = runtime.commit(report.action_id, verifications, report.authority_id)
            self.assertTrue(retry.reused)
            self.assertEqual(retry.effect_id, report.effect_id)
            self.assertEqual(sum(store.get(i).kind == 'Effect' for i in store.all_ids()), 1)

    def test_recorded_wrong_candidate_creates_no_effect(self):
        wrong = 'def clamp(value, lower, upper):\n    return lower\n'
        report = run_investigation(InvestigationOptions(self.root / 'wrong', max_rounds=1),
                                  RecordedAgent((json.dumps(decision_dict(wrong)).encode(),)), self.verifier)
        self.assertEqual(report.outcome, 'REFUSED', report.reason)
        self.assertIsNone(report.effect_id)
        with Store(self.root / 'wrong' / 'history.db') as store:
            self.assertFalse(any(store.get(i).kind == 'Effect' for i in store.all_ids()))

    def test_recorded_stale_action_refused_and_fresh_action_accepted(self):
        responses = (json.dumps(decision_dict()).encode(),
                     json.dumps(decision_dict(evidence=('source_current', 'human_hint'))).encode())
        report = run_investigation(InvestigationOptions(self.root / 'stale', scenario='stale-source',
                                  hint='Check whether the source snapshot is from the current revision.'),
                                  RecordedAgent(responses), self.verifier)
        self.assertEqual(report.outcome, 'ACCEPTED', report.reason)
        self.assertEqual(report.old_action['status'], 'STALE')
        self.assertEqual(report.old_action['gate_outcome'], 'REFUSED')
        self.assertEqual(report.old_action['code'], 'STALE')
        with Store(self.root / 'stale' / 'history.db') as store:
            self.assertEqual(sum(store.get(i).kind == 'Effect' for i in store.all_ids()), 1)
            receipt_action = [p.node_id for p in store.get(report.effect_id).parents if p.role == 'action']
            self.assertEqual(receipt_action, [report.action_id])
            self.assertNotEqual(receipt_action, [report.old_action['action_id']])

    def test_real_runner_faults_cannot_pass_and_timeout_container_is_removed(self):
        # Host checker faults, injected only by test code; candidate constraints stay intact.
        faults = ('print(\'{"suite":"targeted_tests","tests_run":0}\')\n',
                  'print("malformed checker output")\n', 'import time\ntime.sleep(60)\n')
        original_read = Path.read_bytes
        for index, source in enumerate(faults):
            with self.subTest(fault=index):
                case = prepare_case(self.root / f'fault-{index}')
                snapshot = capture_snapshot(case, case.good_revision)
                names = []
                def read(path):
                    if path.name == 'runner.py' and 'provenance' in path.parts: return source.encode()
                    return original_read(path)
                def execute(argv, *args, **kwargs):
                    if '--name' in argv: names.append(argv[argv.index('--name') + 1])
                    return run_process(argv, *args, **kwargs)
                with patch.object(Path, 'read_bytes', read), patch('provenance.clients.repo_repair.verifier.run_process', side_effect=execute):
                    result = self.verifier.test(snapshot, case, 'targeted_tests')
                self.assertFalse(result.passed)
                self.assertEqual(result.outcome, 'infrastructure_error')
                self.assertEqual(len(names), 1)
                absent = run_process(('docker', 'inspect', names[0]), case.root, timeout=10)
                self.assertNotEqual(absent.returncode, 0)
                self.assertIn(b'no such', absent.stderr.lower())
