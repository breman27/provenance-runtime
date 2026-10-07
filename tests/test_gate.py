import multiprocessing
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from provenance.errors import ProvenanceError
from provenance.model import Parent
from provenance.runtime import Policy, Runtime
from provenance.store import Store
from tests.support import node, insert, admitted_repair, policy_snapshot, alter_payload, repair_records, crash_worker

try:
    from provenance.gate import CommitResult
    API_AVAILABLE = hasattr(Runtime, "commit")
except ImportError:
    API_AVAILABLE = False


class GateTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(API_AVAILABLE, "effect gate is not implemented")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "graph.db"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.runtime = Runtime(self.store, Policy(**policy_snapshot()), lambda: self.now)
        self.r = admitted_repair(self.runtime)
        self.action = self.r["action"].id
        self.verifications = tuple(self.r[k].id for k in ("targeted_tests", "full_suite"))
        self.authority = self.r["authority"].id

    def commit(self, action=None, verifications=None, authority="default"):
        return self.runtime.commit(action or self.action,
                                   self.verifications if verifications is None else verifications,
                                   self.authority if authority == "default" else authority)

    def denied(self, expected, **kwargs):
        with self.assertRaises(ProvenanceError) as caught:
            self.commit(**kwargs)
        self.assertEqual(caught.exception.problem.code, expected)
        self.assertEqual(sum(self.store.get(i).kind == "Effect" for i in self.store.all_ids()), 0)
        self.assertIsNone(self.store._local_effect(self.action))

    def changed_verification(self, trusted=True, subject=None, **updates):
        payload = self.r["targeted_tests"].payload
        payload.update(updates)
        record = node("Verification", payload, [Parent("subject", subject or self.action)], "fixture:tester",
                      "2026-10-07T00:00:00.000001Z")
        insert(self.store, record, "verify" if trusted else None)
        return (record.id, self.r["full_suite"].id)

    def changed_authority(self, trusted=True, **updates):
        payload = self.r["authority"].payload
        payload.update(updates)
        record = node("Authority", payload, [Parent("subject", payload["action_id"])], "fixture:authority",
                      "2026-10-07T00:00:00.000001Z")
        insert(self.store, record, "authorize" if trusted else None)
        return record.id

    def test_commit_is_idempotent(self):
        first, retry = self.commit(), self.commit()
        self.assertTrue(first.integrity.ok)
        self.assertFalse(first.reused)
        self.assertTrue(retry.reused)
        self.assertEqual(first.effect_id, retry.effect_id)
        self.assertEqual(first.justification_status, "VALID")
        self.assertEqual(sum(self.store.get(i).kind == "Effect" for i in self.store.all_ids()), 1)
        effect = self.store.get(first.effect_id)
        self.assertEqual(effect.payload["policy"], self.runtime.policy.snapshot())
        self.assertEqual(effect.payload["policy_hash"], self.runtime.policy.content_hash())

    def test_missing_and_incomplete_verification_denied(self):
        for verifications in ((), self.verifications[:1]):
            with self.subTest(verifications=verifications):
                self.denied("VERIFICATION_REQUIRED", verifications=verifications)

    def test_failed_verification_denied(self):
        self.denied("VERIFICATION_FAILED", verifications=self.changed_verification(passed=False))

    def test_untrusted_verification_denied(self):
        self.denied("UNTRUSTED", verifications=self.changed_verification(trusted=False))

    def test_wrong_action_verification_denied(self):
        self.denied("WRONG_ACTION", verifications=self.changed_verification(subject=self.r["claim"].id))

    def test_missing_and_denied_authority(self):
        self.denied("AUTHORITY_REQUIRED", authority=None)
        self.denied("AUTHORITY_DENIED", authority=self.changed_authority(allowed=False))

    def test_untrusted_authority_denied(self):
        self.denied("UNTRUSTED", authority=self.changed_authority(trusted=False))

    def test_wrong_subject_resource_or_action_type_denied(self):
        for updates in ({"subject": "other:runtime"}, {"resource": "other:repo"}, {"action_type": "other.action"}):
            with self.subTest(updates=updates):
                self.denied("AUTHORITY_SCOPE", authority=self.changed_authority(**updates))

    def test_expired_authority_denied_at_exact_boundary(self):
        self.now = datetime(2026, 10, 7, 1, tzinfo=timezone.utc)
        self.denied("AUTHORITY_EXPIRED")

    def test_revoked_authority_denied(self):
        self.runtime.invalidate(self.runtime.controller("fixture:control"), self.authority, "revoked")
        self.denied("AUTHORITY_REVOKED")

    def test_stale_evidence_denied(self):
        self.runtime.invalidate(self.runtime.controller("fixture:control"), self.r["code"].id, "bad collector")
        self.denied("STALE")

    def test_changed_patch_requires_its_own_verification(self):
        action = node("ProposedAction", {"action_type": "repo.repair.simulated", "resource": "fixture:repo",
                                        "arguments": {"patch": "different"}},
                      [Parent("justification", self.r["claim"].id)], "reasoner")
        self.runtime.submit(action)
        self.denied("WRONG_ACTION", action=action.id)

    def test_unknown_action_policy_denied(self):
        action = node("ProposedAction", {"action_type": "repository.merge", "resource": "fixture:repo", "arguments": {}},
                      [Parent("justification", self.r["claim"].id)], "reasoner")
        self.runtime.submit(action)
        self.denied("POLICY_UNKNOWN", action=action.id)

    def test_retry_after_expiry_preserves_original_receipt(self):
        first = self.commit()
        self.now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        retry = self.commit(authority=None, verifications=())
        self.assertTrue(retry.reused)
        self.assertEqual(first.effect_id, retry.effect_id)

    def test_retry_after_invalidation_reports_stale_history(self):
        first = self.commit()
        self.runtime.invalidate(self.runtime.controller("fixture:control"), self.r["code"].id, "bad evidence")
        retry = self.commit()
        self.assertEqual(first.effect_id, retry.effect_id)
        self.assertEqual(retry.justification_status, "STALE")
        self.assertTrue(retry.integrity.ok)

    def test_corrupt_existing_ancestry_is_reported_without_new_write(self):
        first = self.commit()
        before = self.store.all_ids()
        alter_payload(self.store, self.r["code"], message="tampered")
        retry = self.commit()
        self.assertFalse(retry.integrity.ok)
        self.assertIsNone(retry.justification_status)
        self.assertEqual(first.effect_id, retry.effect_id)
        self.assertEqual(self.store.all_ids(), before)

    def test_imported_effect_does_not_count_as_local_commit(self):
        # A historical Effect can coexist with locally admitted supporting records.
        records = repair_records(self.store)
        with self.store.write_transaction():
            self.store._db.execute("DELETE FROM admissions WHERE node_id=?", (records["effect"].id,))
        self.assertIsNone(self.store._local_effect(self.action))
        result = self.commit()
        self.assertFalse(result.reused)
        self.assertEqual(self.store._local_effect(self.action), result.effect_id)

    def test_untrusted_observation_ancestry_denied(self):
        untrusted = node("Observation", {"message": "imported failure"})
        insert(self.store, untrusted)
        c = node("Claim", {"statement": "cause"}, [Parent("evidence", untrusted.id)], "reasoner")
        self.runtime.submit(c)
        a = node("ProposedAction", self.r["action"].payload, [Parent("justification", c.id)], "reasoner")
        self.runtime.submit(a)
        vs = tuple(self.runtime.verify(self.runtime.verifier("fixture:tester"), a.id, check, True)
                   for check in ("targeted_tests", "full_suite"))
        authority = self.runtime.authorize(self.runtime.issuer("fixture:authority"), a.id, True,
                                           datetime(2026, 10, 7, 1, tzinfo=timezone.utc))
        self.denied("UNTRUSTED", action=a.id, verifications=vs, authority=authority)

    def test_competing_commits_have_one_receipt(self):
        barrier = threading.Barrier(2)
        def worker():
            with Store(self.path) as store:
                runtime = Runtime(store, Policy(**policy_snapshot()), lambda: self.now)
                barrier.wait(timeout=10)
                return runtime.commit(self.action, self.verifications, self.authority)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker), pool.submit(worker)]
            results = [f.result(timeout=15) for f in futures]
        self.assertEqual(results[0].effect_id, results[1].effect_id)
        self.assertEqual(sorted(r.reused for r in results), [False, True])
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM local_effects").fetchone()[0], 1)
        self.assertEqual(sum(self.store.get(i).kind == "Effect" for i in self.store.all_ids()), 1)

    def crash_at(self, stage, expected):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=crash_worker, args=(self.path, stage, self.action,
                                                           self.verifications, self.authority, child))
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(20), "child did not reach the requested boundary")
            self.assertEqual(parent.recv(), stage)
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=10)
            parent.close()
        self.assertFalse(process.is_alive())
        with Store(self.path) as restarted:
            self.assertEqual(sum(restarted.get(i).kind == "Effect" for i in restarted.all_ids()), expected)
            self.assertEqual(restarted._db.execute("SELECT count(*) FROM local_effects").fetchone()[0], expected)
            if expected:
                runtime = Runtime(restarted, Policy(**policy_snapshot()), lambda: self.now)
                self.assertTrue(runtime.commit(self.action, (), None).reused)

    def test_crash_before_mapping_rolls_back_both_writes(self):
        self.crash_at("before_mapping", 0)

    def test_crash_after_commit_preserves_one_receipt(self):
        self.crash_at("after_commit", 1)


if __name__ == "__main__":
    unittest.main()
