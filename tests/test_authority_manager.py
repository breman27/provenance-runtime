import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from provenance.runtime import Runtime
from provenance.projection import status
from provenance.clients.repo_repair.errors import InvestigationError
from provenance.clients.authority.context import record_context
from tests.authority_support import pending, NOW

try:
    from provenance.clients.authority.manager import ApprovalManager
except ImportError:
    ApprovalManager = None


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ApprovalManager, 'approval lifecycle is not implemented')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.now = NOW
        (self.case, self.store, self.runtime, self.session, self.baseline, self.action,
         self.source, self.checks, self.logs) = pending(Path(temp.name)/'case', lambda: self.now)
        self.addCleanup(self.store.close)
        self.context = record_context(self.session, self.runtime, self.case, self.baseline,
                                      self.action, self.source, self.checks)
        self.manager = ApprovalManager(self.session.root, clock=lambda: self.now)

    def count(self, kind):
        return sum(self.store.get(i).kind == kind for i in self.store.all_ids())

    def test_manual_lifecycle_grant_only_then_one_receipt(self):
        self.assertEqual(self.manager.inspect(self.action).state, 'AWAITING_APPROVAL')
        self.assertEqual(self.manager.admit(self.action).state, 'AWAITING_APPROVAL')
        grant = self.manager.approve(self.action, reason='Reviewed source and checks')
        self.assertEqual(grant.state, 'APPROVED')
        self.assertIsNone(grant.effect_id)
        self.assertEqual(self.count('Effect'), 0)
        self.assertTrue(self.manager.approve(self.action, reason='Reviewed source and checks').reused)
        result = self.manager.admit(self.action)
        self.assertEqual(result.state, 'COMMITTED')
        self.assertTrue(result.integrity_ok)
        self.assertTrue(self.manager.admit(self.action).reused)
        self.assertEqual(self.count('Effect'), 1)
        self.assertEqual(self.count('Authority'), 1)
        self.assertEqual(self.manager.deny(self.action).state, 'ALREADY_COMMITTED')
        self.assertEqual(self.count('Authority'), 1)

    def test_expiry_at_equality_and_explicit_renewal(self):
        first = self.manager.approve(self.action, ttl_minutes=1)
        self.now += timedelta(minutes=1)
        self.assertEqual(self.manager.admit(self.action).state, 'EXPIRED')
        self.assertEqual(self.count('Authority'), 1)
        second = self.manager.approve(self.action, ttl_minutes=1)
        self.assertNotEqual(first.authority_id, second.authority_id)
        self.assertEqual(status(self.store, first.authority_id, 'execution'), 'SUPERSEDED')
        self.assertEqual(self.manager.admit(self.action).state, 'COMMITTED')

    def test_active_retry_requires_renew_for_changed_inputs(self):
        first = self.manager.approve(self.action, reason='')
        self.assertEqual(self.manager.approve(self.action, reason=None).authority_id, first.authority_id)
        for updates in ({'reason': 'new reason'}, {'ttl_minutes': 20}):
            with self.subTest(updates=updates), self.assertRaises(InvestigationError) as caught:
                self.manager.approve(self.action, **updates)
            self.assertEqual(caught.exception.code, 'RENEW_REQUIRED')
        self.assertEqual(self.count('Authority'), 1)
        renewed = self.manager.approve(self.action, reason='new reason', renew=True)
        self.assertNotEqual(renewed.authority_id, first.authority_id)

    def test_denial_blocks_old_grant_and_later_explicit_approval_can_replace_it(self):
        old = self.manager.approve(self.action)
        denial = self.manager.deny(self.action, reason='not now')
        self.assertEqual(denial.state, 'DENIED')
        self.assertEqual(self.manager.admit(self.action).state, 'DENIED')
        self.assertEqual(status(self.store, old.authority_id, 'execution'), 'INVALID')
        self.now += timedelta(days=1)
        self.assertEqual(self.manager.admit(self.action).state, 'DENIED')
        self.assertEqual(self.manager.approve(self.action).state, 'APPROVED')
        self.assertEqual(self.manager.admit(self.action).state, 'COMMITTED')

    def test_revoke_before_and_after_receipt_preserves_history(self):
        first = self.manager.approve(self.action)
        self.assertEqual(self.manager.revoke(first.authority_id, reason='withdraw').state, 'REVOKED')
        self.assertEqual(self.manager.admit(self.action).state, 'REVOKED')
        second = self.manager.approve(self.action)
        receipt = self.manager.admit(self.action)
        self.manager.revoke(second.authority_id)
        retry = self.manager.admit(self.action)
        self.assertEqual(retry.effect_id, receipt.effect_id)
        self.assertEqual(retry.state, 'COMMITTED')
        self.assertEqual(status(self.store, retry.effect_id, 'execution'), 'STALE')

    def test_invalid_options_do_not_write(self):
        before = self.store.all_ids()
        for ttl in (True, False, 0, 61, '15', 1.5):
            with self.subTest(ttl=ttl), self.assertRaises(InvestigationError):
                self.manager.approve(self.action, ttl_minutes=ttl)
        for reason in (123, 'x'*4001, '\ud800'):
            with self.subTest(reason=repr(reason)), self.assertRaises(InvestigationError):
                self.manager.approve(self.action, reason=reason)
        self.assertEqual(before, self.store.all_ids())

    def test_withdrawal_and_receipt_retry_work_without_files_or_source(self):
        grant = self.manager.approve(self.action)
        receipt = self.manager.admit(self.action)
        self.case.repository.rename(self.case.repository.with_name('offline'))
        (self.session.root/'approvals'/(self.action.split(':')[1]+'.json')).unlink()
        self.manager.revoke(grant.authority_id)
        self.assertEqual(self.manager.admit(self.action).effect_id, receipt.effect_id)

    def test_offline_denial_and_no_grant_for_changed_source(self):
        self.case.repository.rename(self.case.repository.with_name('offline'))
        self.assertEqual(self.manager.deny(self.action).state, 'DENIED')
        with self.assertRaises(InvestigationError) as caught:
            self.manager.approve(self.action)
        self.assertEqual(caught.exception.code, 'SOURCE_UNAVAILABLE')
        self.assertEqual(self.count('Authority'), 1)

    def test_clock_rollback_cannot_rescue_superseded_grant(self):
        old = self.manager.approve(self.action)
        self.now -= timedelta(days=2)
        denied = self.manager.deny(self.action)
        self.assertEqual(self.manager.admit(self.action).authority_id, denied.authority_id)
        self.assertEqual(self.manager.admit(self.action).state, 'DENIED')
        seq = self.store.get(denied.authority_id).payload['decision']['sequence']
        self.assertEqual(seq, self.store.get(old.authority_id).payload['decision']['sequence']+1)

    def test_interrupted_denial_reconciles_controls_without_effect(self):
        old = self.manager.approve(self.action)
        with patch.object(Runtime, 'invalidate', side_effect=RuntimeError('operator crash')):
            with self.assertRaises(RuntimeError):
                self.manager.deny(self.action)
        self.assertEqual(self.count('Authority'), 2)
        reopened = ApprovalManager(self.session.root, clock=lambda: self.now)
        self.assertEqual(reopened.admit(self.action).state, 'DENIED')
        self.assertEqual(status(self.store, old.authority_id, 'execution'), 'INVALID')
        self.assertEqual(self.count('Effect'), 0)

    def test_interrupted_renewal_retires_old_grant_and_no_recovery_effect(self):
        old = self.manager.approve(self.action)
        with patch.object(Runtime, 'supersede', side_effect=RuntimeError('operator crash')):
            with self.assertRaises(RuntimeError):
                self.manager.approve(self.action, renew=True)
        current = self.manager.approve(self.action)
        self.assertTrue(current.reused)
        self.assertNotEqual(current.authority_id, old.authority_id)
        self.assertEqual(status(self.store, old.authority_id, 'execution'), 'SUPERSEDED')
        self.assertEqual(self.count('Effect'), 0)

    def test_conflicting_trusted_sequences_are_integrity_failure(self):
        result = self.manager.approve(self.action)
        grant = self.store.get(result.authority_id)
        metadata = dict(grant.payload['decision'], reason='conflicting')
        self.runtime.authorize(self.runtime.issuer('human-operator'), self.action, True,
                               self.now+timedelta(minutes=15), decision=metadata)
        with self.assertRaises(InvestigationError) as caught:
            self.manager.admit(self.action)
        self.assertEqual(caught.exception.code, 'DECISION_INTEGRITY')
        self.assertEqual(self.count('Effect'), 0)

    def test_corrupt_receipt_is_integrity_error_never_duplicate(self):
        self.manager.approve(self.action)
        self.manager.admit(self.action)
        with self.store.write_transaction():
            self.store._db.execute('UPDATE local_effects SET effect_id=? WHERE action_id=?', (self.source, self.action))
        with self.assertRaises(InvestigationError) as caught:
            self.manager.admit(self.action)
        self.assertEqual(caught.exception.code, 'RECEIPT_INTEGRITY')
        self.assertEqual(self.count('Effect'), 1)

    def test_list_filters_history_and_retains_expired_and_revoked(self):
        self.assertEqual(len(self.manager.list()), 1)
        self.manager.deny(self.action)
        self.assertEqual(len(self.manager.list()), 0)
        self.assertEqual(len(self.manager.list(include_all=True)), 1)
        grant = self.manager.approve(self.action)
        self.manager.revoke(grant.authority_id)
        self.assertEqual(self.manager.list()[0].state, 'REVOKED')

    def test_source_and_required_check_changes_block_new_permission(self):
        self.runtime.invalidate(self.runtime.controller('controller'), self.checks[0], 'test withdrawn')
        self.assertEqual(self.manager.inspect(self.action).state, 'VERIFICATION_FAILED')
        with self.assertRaises(InvestigationError):
            self.manager.approve(self.action)
        self.assertEqual(self.count('Authority'), 0)

    def test_forged_imported_operator_decision_cannot_supply_permission(self):
        from provenance.model import make_node, Parent
        from tests.support import insert
        action = self.store.get(self.action)
        forged = make_node('Authority', {'issuer_id': 'human-operator', 'subject': 'observed-service',
            'action_id': self.action, 'action_type': action.payload['action_type'], 'resource': action.payload['resource'],
            'allowed': True, 'expires_at': '2026-10-10T00:00:00.000000Z',
            'decision': {'method': 'local-cli', 'actor': 'human-operator', 'context_hash': self.context.context_hash,
                         'sequence': 999, 'reason': None, 'ttl_minutes': 15}},
            [Parent('subject', self.action)], 'human-operator', self.now)
        insert(self.store, forged)
        self.assertEqual(self.manager.admit(self.action).state, 'AWAITING_APPROVAL')
        real = self.manager.approve(self.action)
        self.assertEqual(self.store.get(real.authority_id).payload['decision']['sequence'], 1)

    def test_grant_concurrently_staled_by_collector_is_reported_unusable(self):
        original = Runtime.authorize
        def issue_then_invalidate(runtime, *args, **kwargs):
            grant = original(runtime, *args, **kwargs)
            runtime.invalidate(runtime.controller('controller'), self.source, 'collector correction')
            return grant
        with patch.object(Runtime, 'authorize', issue_then_invalidate):
            grant = self.manager.approve(self.action)
        self.assertEqual(grant.state, 'STALE')
        self.assertEqual(self.manager.admit(self.action).state, 'STALE')
        self.assertEqual(self.count('Effect'), 0)
