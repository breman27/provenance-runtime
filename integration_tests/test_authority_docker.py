"""Actual Docker proof of the manual queue; no host execution or live model."""
import json
import tempfile
import unittest
from pathlib import Path

from provenance import Store, why
from provenance.clients.authority.manager import ApprovalManager
from provenance.clients.observed_service.agent import RecordedServiceAgent
from provenance.clients.observed_service.experiment import ServiceVerifier, run_experiment
from provenance.clients.observed_service.watch import ServiceWatcher
from provenance.clients.repo_repair.case import GOOD_SOURCE, BAD_SOURCE, TARGET, _git
from provenance.clients.repo_repair.errors import InvestigationError
from tests.test_authority_clients import RepairAgent


class AuthorityDockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = ServiceVerifier()
        cls.verifier.preflight()

    def run_case(self, root, mode='manual'):
        steps = json.loads(Path('examples/recorded-service-regression.json').read_text(encoding='utf-8'))
        report = run_experiment(root, RecordedServiceAgent(steps), self.verifier, approval_mode=mode)
        self.assertEqual(report['outcome'], 'AWAITING_APPROVAL' if mode == 'manual' else 'ACCEPTED', report['reason'])
        return report

    def test_real_manual_wait_approve_admit_and_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()/'case'
            report = self.run_case(root)
            with Store(root/'history.db') as store:
                self.assertFalse(any(store.get(i).kind in ('Authority', 'Effect') for i in store.all_ids()))
            manager = ApprovalManager(root)
            self.assertIsNone(manager.approve(report['action_id']).effect_id)
            receipt = manager.admit(report['action_id'])
            self.assertEqual(receipt.state, 'COMMITTED')
            self.assertEqual(manager.admit(report['action_id']).effect_id, receipt.effect_id)
            with Store(root/'history.db') as store:
                self.assertTrue(all(store.validate(i).ok for i in store.all_ids()))
                self.assertTrue(all(s == 'VALID' for s in why(store, receipt.effect_id, 'execution').statuses.values()))
                checks = [r for r in report['tests'] if r['phase']=='candidate']
                self.assertEqual([r['tests_run'] for r in checks], [1, 8])
                self.assertTrue(all(r['image_id'] == self.verifier.image_id and r['executor'] == 'docker-linux-restricted' for r in checks))

    def test_real_denial_and_unpolled_source_edit_refuse_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()/'case'
            report = self.run_case(root)
            manager = ApprovalManager(root)
            manager.approve(report['action_id'])
            manager.deny(report['action_id'])
            self.assertEqual(manager.admit(report['action_id']).state, 'DENIED')
            manager.approve(report['action_id'])
            (root/'repository'/TARGET).write_bytes(GOOD_SOURCE)
            with self.assertRaises(InvestigationError) as caught:
                manager.admit(report['action_id'])
            self.assertEqual(caught.exception.code, 'STALE')
            with Store(root/'history.db') as store:
                self.assertFalse(any(store.get(i).kind == 'Effect' for i in store.all_ids()))

    def test_real_watcher_collects_while_waiting_and_queue_survives_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root/'source'
            (repo/'src').mkdir(parents=True)
            (repo/TARGET).write_bytes(BAD_SOURCE)
            _git(repo, 'init', '--initial-branch=service')
            _git(repo, 'config', 'user.name', 'Test fixture')
            _git(repo, 'config', 'user.email', 'fixture@example.invalid')
            _git(repo, 'add', '.')
            _git(repo, 'commit', '-m', 'source')
            watcher = ServiceWatcher(repo, root/'session', self.verifier, RepairAgent(),
                                     output=lambda *a, **k: None, approval_mode='manual')
            watcher.start()
            try:
                watcher.tick()
                watcher.thread.join(45)
                self.assertFalse(watcher.thread.is_alive())
                self.assertEqual(ApprovalManager(root/'session').list()[0].state, 'AWAITING_APPROVAL')
                watcher.tick()
                self.assertEqual(watcher.sequence, 2)
            finally:
                watcher.close()
            self.assertEqual(ApprovalManager(root/'session').list()[0].state, 'AWAITING_APPROVAL')

    def test_explicit_auto_still_earns_real_verified_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.run_case(Path(temporary).resolve()/'case', mode='auto')
