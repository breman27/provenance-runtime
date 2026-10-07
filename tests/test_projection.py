import tempfile
import unittest
from pathlib import Path
from provenance.errors import ProvenanceError
from provenance.model import Parent
from provenance.store import Store
from tests.support import observation, claim, node, insert, repair_records, alter_payload

try:
    from provenance.projection import status, impacted_by, evidence_for, why, check_supersession
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(API_AVAILABLE, "status/query API is not implemented")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "graph.db")
        self.addCleanup(self.store.close)

    def invalidate(self, target, trusted=True):
        control = node("Invalidation", {"reason": "collector was wrong"},
                       [Parent("target", target.id)], "fixture:control")
        insert(self.store, control, "control" if trusted else None)
        return control

    def test_invalidation_preserves_history(self):
        r = repair_records(self.store)
        unrelated = observation(self.store, "unrelated")
        original = r["effect"].canonical_body
        self.assertEqual(status(self.store, r["effect"].id), "VALID")
        control = self.invalidate(r["code"])
        expected = {"code": "INVALID", "failure": "VALID", "claim": "STALE", "action": "STALE",
                    "targeted_tests": "STALE", "full_suite": "STALE", "authority": "STALE", "effect": "STALE"}
        for name, wanted in expected.items():
            self.assertEqual(status(self.store, r[name].id), wanted, name)
        self.assertEqual(status(self.store, unrelated.id), "VALID")
        self.assertEqual(status(self.store, control.id), "VALID")
        self.assertEqual(self.store.get(r["effect"].id).canonical_body, original)

    def test_supersession_and_invalidation_precedence(self):
        old, replacement = observation(self.store), observation(self.store, "corrected")
        original = old.canonical_body
        control = node("Supersession", {"reason": "new measurement"},
                       [Parent("target", old.id), Parent("replacement", replacement.id)], "fixture:control")
        insert(self.store, control, "control")
        self.assertEqual(status(self.store, old.id), "SUPERSEDED")
        self.assertEqual(status(self.store, replacement.id), "VALID")
        self.invalidate(old)
        self.assertEqual(status(self.store, old.id), "INVALID")
        self.assertEqual(self.store.get(old.id).canonical_body, original)

    def test_supersession_rejects_dependent_or_wrong_kind_replacement(self):
        o = observation(self.store)
        old = claim(self.store, o)
        dependent = claim(self.store, old, statement="still depends on old")
        for replacement in (dependent, o):
            with self.subTest(kind=replacement.kind), self.assertRaises(ProvenanceError):
                check_supersession(self.store, old.id, replacement.id)
        bad = node("Supersession", {"reason": "bad replacement"},
                   [Parent("target", old.id), Parent("replacement", dependent.id)], "fixture:control")
        with self.assertRaises(ProvenanceError):
            insert(self.store, bad, "control")

    def test_query_sets_order_and_shared_ancestry(self):
        r = repair_records(self.store)
        trace = why(self.store, r["effect"].id)
        self.assertEqual({n.id for n in trace.nodes}, {n.id for n in r.values()})
        positions = {n.id: i for i, n in enumerate(trace.nodes)}
        for record in trace.nodes:
            for parent in record.parents:
                self.assertLess(positions[parent.node_id], positions[record.id])
        self.assertEqual({n.id for n in evidence_for(self.store, r["claim"].id)},
                         {r["failure"].id, r["code"].id})
        expected = tuple(sorted(n.id for k, n in r.items() if k not in {"failure", "code"}))
        self.assertEqual(impacted_by(self.store, r["code"].id), expected)
        control = self.invalidate(r["code"])
        updated = why(self.store, r["effect"].id)
        self.assertEqual(updated.nodes, trace.nodes)
        self.assertEqual(updated.controls, (control,))
        self.assertEqual(updated.statuses[r["effect"].id], "STALE")

    def test_tampered_external_control_fails_projection(self):
        r = repair_records(self.store)
        control = self.invalidate(r["code"])
        alter_payload(self.store, control, reason="tampered")
        with self.assertRaises(ProvenanceError) as caught:
            status(self.store, r["action"].id, "execution")
        self.assertEqual(caught.exception.problem.code, "HASH_MISMATCH")

    def test_imported_control_is_inspection_only(self):
        o = observation(self.store)
        self.invalidate(o, trusted=False)
        self.assertEqual(status(self.store, o.id, "inspection"), "INVALID")
        self.assertEqual(status(self.store, o.id, "execution"), "VALID")

    def test_tampered_target_cannot_hide_control(self):
        import json
        from provenance.format import canonical_json
        original = observation(self.store)
        other = observation(self.store, "other")
        control = self.invalidate(original)
        body = json.loads(control.canonical_body)
        body["parents"][0]["id"] = other.id
        with self.store.write_transaction():
            self.store._db.execute("UPDATE nodes SET body=? WHERE id=?", (canonical_json(body), control.id))
        with self.assertRaises(ProvenanceError):
            status(self.store, original.id, "execution")

    def test_impacted_by_rejects_removed_reference(self):
        import json
        from provenance.format import canonical_json
        r = repair_records(self.store)
        self.assertIn(r["effect"].id, impacted_by(self.store, r["code"].id))
        body = json.loads(r["claim"].canonical_body)
        body["parents"] = [p for p in body["parents"] if p["id"] != r["code"].id]
        with self.store.write_transaction():
            self.store._db.execute("UPDATE nodes SET body=? WHERE id=?", (canonical_json(body), r["claim"].id))
        with self.assertRaises(ProvenanceError) as caught:
            impacted_by(self.store, r["code"].id)
        self.assertEqual(caught.exception.problem.code, "HASH_MISMATCH")

    def test_wrong_query_kind_and_mode_are_rejected(self):
        o = observation(self.store)
        for query in (why, evidence_for):
            with self.assertRaises(ProvenanceError):
                query(self.store, o.id)
        with self.assertRaises(ProvenanceError):
            status(self.store, o.id, "unknown")


if __name__ == "__main__":
    unittest.main()
