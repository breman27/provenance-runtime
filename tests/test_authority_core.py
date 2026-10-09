import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from provenance.errors import ProvenanceError
from provenance.runtime import Runtime, Policy, AuthorityHandle
from provenance.store import Store
from tests.support import admitted_repair, policy_snapshot, alter_payload


class AuthorityCoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / 'history.db')
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.runtime = Runtime(self.store, Policy(**policy_snapshot()), lambda: self.now)
        self.records = admitted_repair(self.runtime)
        self.action = self.records['action'].id

    def grant(self, **kwargs):
        return self.runtime.authorize(self.runtime.issuer('fixture:authority'), self.action, True,
                                      self.now + timedelta(minutes=15), **kwargs)

    def commit(self):
        return self.runtime.commit(self.action, tuple(self.records[k].id for k in
                                   ('targeted_tests', 'full_suite')), self.records['authority'].id)

    def test_optional_metadata_is_detached_and_legacy_body_unchanged(self):
        old = self.grant()
        self.assertNotIn('decision', self.store.get(old).payload)
        self.assertEqual(old, self.grant(decision=None))
        metadata = {'reason': 'révision', 'nested': [1]}
        new = self.grant(decision=metadata)
        metadata['nested'].append(2)
        self.assertEqual(self.store.get(new).payload['decision'], {'reason': 'révision', 'nested': [1]})
        self.assertEqual({k: v for k, v in self.store.get(new).payload.items() if k != 'decision'},
                         self.store.get(old).payload)

    def test_metadata_cannot_bypass_handle_or_json_validation(self):
        before = self.store.all_ids()
        for bad in ([], 'issuer', {'value': 1.5}, {'value': object()}, {'value': '\ud800'}):
            with self.subTest(bad=repr(bad)), self.assertRaises(ProvenanceError):
                self.grant(decision=bad)
        with self.assertRaises(ProvenanceError):
            self.runtime.authorize(AuthorityHandle('fixture:authority'), self.action, True,
                                   self.now, decision={'issuer_id': 'fixture:authority'})
        self.assertEqual(before, self.store.all_ids())

    def test_lookup_is_read_only_and_preserves_history_after_expiry(self):
        self.assertIsNone(self.runtime.local_receipt(self.action))
        result = self.commit()
        before = self.store.all_ids()
        self.now += timedelta(days=2)
        receipt = self.runtime.local_receipt(self.action)
        self.assertTrue(receipt.reused)
        self.assertTrue(receipt.integrity.ok)
        self.assertEqual(receipt.effect_id, result.effect_id)
        self.assertEqual(before, self.store.all_ids())

    def test_corrupt_mapping_and_ancestry_are_errors_not_absence(self):
        result = self.commit()
        with self.store.write_transaction():
            self.store._db.execute('UPDATE local_effects SET effect_id=? WHERE action_id=?',
                                   (self.records['claim'].id, self.action))
        self.assertFalse(self.runtime.local_receipt(self.action).integrity.ok)
        with self.store.write_transaction():
            self.store._db.execute('UPDATE local_effects SET effect_id=? WHERE action_id=?',
                                   (result.effect_id, self.action))
        before = self.store.all_ids()
        alter_payload(self.store, self.records['code'], message='tampered')
        self.assertFalse(self.runtime.local_receipt(self.action).integrity.ok)
        self.assertEqual(before, self.store.all_ids())

    def test_unmapped_historical_effect_is_not_local_receipt(self):
        receipt = self.commit()
        with self.store.write_transaction():
            self.store._db.execute('DELETE FROM local_effects WHERE action_id=?', (self.action,))
            self.store._db.execute('DELETE FROM admissions WHERE node_id=?', (receipt.effect_id,))
        self.assertIsNone(self.runtime.local_receipt(self.action))

    def test_missing_mapping_for_locally_admitted_effect_is_integrity_failure(self):
        receipt = self.commit()
        with self.store.write_transaction():
            self.store._db.execute('DELETE FROM local_effects WHERE action_id=?', (self.action,))
        result = self.runtime.local_receipt(self.action)
        self.assertIsNotNone(result)
        self.assertFalse(result.integrity.ok)
        self.assertEqual(result.effect_id, receipt.effect_id)

    def test_mapping_to_imported_effect_is_integrity_failure(self):
        receipt = self.commit()
        with self.store.write_transaction():
            self.store._db.execute('DELETE FROM admissions WHERE node_id=?', (receipt.effect_id,))
        result = self.runtime.local_receipt(self.action)
        self.assertFalse(result.integrity.ok)
