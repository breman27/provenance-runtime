import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from provenance.errors import ProvenanceError
from provenance.format import canonical_json
from provenance.model import Node, Parent
from provenance.store import Store, Admission
from tests.support import node, policy_snapshot

try:
    from provenance.runtime import Policy, Runtime, ObserverHandle
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False


def fixture_policy():
    return Policy(**policy_snapshot())


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(API_AVAILABLE, "trusted runtime is not implemented")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "graph.db")
        self.addCleanup(self.store.close)
        self.clock = lambda: datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.runtime = Runtime(self.store, fixture_policy(), self.clock)

    def test_model_cannot_upgrade_producer_label(self):
        r = self.runtime
        spoofed = node("Observation", {"message": "fake"}, producer="fixture:runner")
        with self.assertRaises(ProvenanceError):
            r.submit(spoofed)
        o_id = r.observe(r.observer("fixture:runner"), {"message": "failed"})
        c_id = r.submit(node("Claim", {"statement": "cause"}, [Parent("evidence", o_id)]))
        self.assertIsNone(self.store.admission(c_id))
        self.assertEqual(self.store.admission(o_id), Admission("fixture:runner", "observe"))
        self.assertEqual(self.store.get(o_id).created_at, "2026-10-07T00:00:00.000000Z")

    def test_foreign_and_forged_handles_rejected(self):
        other = Runtime(self.store, fixture_policy(), self.clock)
        for handle in (other.observer("fixture:runner"), ObserverHandle("fixture:runner"), "fixture:runner"):
            with self.subTest(handle=repr(handle)), self.assertRaises(ProvenanceError):
                self.runtime.observe(handle, {"message": "not admitted"})
        self.assertEqual(self.store.all_ids(), ())

    def test_unknown_principals_and_verifier_checks_rejected(self):
        r = self.runtime
        for getter in (r.observer, r.verifier, r.issuer, r.controller):
            with self.assertRaises(ProvenanceError):
                getter("unknown")
        o_id = r.observe(r.observer("fixture:runner"), {})
        c_id = r.submit(node("Claim", {"statement": "cause"}, [Parent("evidence", o_id)]))
        with self.assertRaises(ProvenanceError):
            r.verify(r.verifier("fixture:tester"), c_id, "model_confidence", True)
        verification = r.verify(r.verifier("fixture:tester"), c_id, "targeted_tests", True, (o_id,))
        self.assertEqual(self.store.admission(verification), Admission("fixture:tester", "verify"))

    def test_model_submission_rejects_every_trusted_kind(self):
        for kind in ("Observation", "Verification", "Authority", "Effect", "Invalidation", "Supersession"):
            with self.subTest(kind=kind), self.assertRaises(ProvenanceError):
                self.runtime.submit(node(kind, {}))

    def test_malformed_model_input_is_structured(self):
        for body in (b'{}', b'not json', b'[]'):
            with self.subTest(body=body), self.assertRaises(ProvenanceError):
                self.runtime.submit(Node("sha256:" + "0" * 64, body))

    def test_authority_and_controls_bind_admitted_action(self):
        r = self.runtime
        o_id = r.observe(r.observer("fixture:runner"), {"message": "source"})
        c_id = r.submit(node("Claim", {"statement": "cause"}, [Parent("evidence", o_id)]))
        a_id = r.submit(node("ProposedAction", {"action_type": "repo.repair.simulated", "resource": "fixture:repo",
                                               "arguments": {"patch": "fixed"}}, [Parent("justification", c_id)]))
        authority = r.authorize(r.issuer("fixture:authority"), a_id, True,
                                datetime(2026, 10, 7, 1, tzinfo=timezone.utc))
        payload = self.store.get(authority).payload
        self.assertEqual(payload["action_id"], a_id)
        self.assertEqual(payload["resource"], "fixture:repo")
        self.assertEqual(payload["subject"], "fixture:runtime")
        self.assertEqual(self.store.admission(authority), Admission("fixture:authority", "authorize"))
        invalidation = r.invalidate(r.controller("fixture:control"), o_id, "bad evidence")
        self.assertEqual(self.store.admission(invalidation), Admission("fixture:control", "control"))
        replacement = r.observe(r.observer("fixture:runner"), {"message": "corrected"})
        supersession = r.supersede(r.controller("fixture:control"), o_id, replacement, "new result")
        self.assertEqual(self.store.get(supersession).kind, "Supersession")

    def test_policy_snapshot_is_stable_and_defensive(self):
        source = policy_snapshot()
        policy = Policy(**source)
        before = policy.snapshot()
        source["requirements"]["repo.repair.simulated"].clear()
        policy.snapshot()["issuers"].clear()
        self.assertEqual(policy.snapshot(), before)
        self.assertEqual(policy.content_hash(), "sha256:" + hashlib.sha256(canonical_json(before)).hexdigest())


if __name__ == "__main__":
    unittest.main()
