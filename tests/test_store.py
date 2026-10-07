import json
import tempfile
import unittest
from pathlib import Path

from provenance.errors import ProvenanceError
from provenance.format import canonical_json
from provenance.model import Node, Parent
from tests.support import observation, claim, node, insert, raw_seed, alter_payload

try:
    from provenance.store import Store
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(API_AVAILABLE, "SQLite store is not implemented")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "graph.db"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)

    def test_persistence_and_idempotent_insertion(self):
        o = observation(self.store)
        c = claim(self.store, o)
        self.assertEqual(self.store.put(c), c.id)
        with Store(self.path) as reopened:
            self.assertEqual(reopened.all_ids(), tuple(sorted((o.id, c.id))))
            self.assertEqual(reopened.get(c.id).canonical_body, c.canonical_body)
            self.assertTrue(reopened.validate(c.id).ok)

    def test_branching_and_joining_visit_once(self):
        o = observation(self.store)
        c1 = claim(self.store, o, statement="first")
        c2 = claim(self.store, o, statement="second")
        joined = claim(self.store, c1, c2, statement="joined")
        report = self.store.validate(joined.id)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(len(report.visited), 4)
        self.assertEqual(self.store.child_ids(o.id), tuple(sorted((c1.id, c2.id))))
        self.assertEqual(self.store.parent_ids(joined.id), tuple(sorted((c1.id, c2.id))))

    def test_missing_parent_rejected_without_partial_insert(self):
        missing = node("Claim", {"statement": "missing"}, [Parent("evidence", "sha256:" + "0" * 64)])
        with self.assertRaises(ProvenanceError):
            self.store.put(missing)
        self.assertEqual(self.store.all_ids(), ())

    def test_ancestor_mutation_is_reported(self):
        o = observation(self.store)
        c = claim(self.store, o)
        alter_payload(self.store, o, message="edited")
        report = self.store.validate(c.id)
        self.assertFalse(report.ok)
        self.assertIn(("HASH_MISMATCH", o.id), {(p.code, p.node_id) for p in report.errors})
        with self.assertRaises(ProvenanceError):
            claim(self.store, c, statement="cannot append to corrupt history")

    def test_relationship_index_mutation_detected(self):
        o = observation(self.store)
        c = claim(self.store, o)
        with self.store.write_transaction():
            self.store._db.execute("DELETE FROM edges WHERE child_id=?", (c.id,))
        self.assertIn("INDEX_MISMATCH", {p.code for p in self.store.validate(c.id).errors})

    def test_illegal_type_edge_and_direct_trusted_insert_rejected(self):
        o = observation(self.store)
        bad = node("Claim", {"statement": "bad"}, [Parent("evidence", o.id)], "reasoner")
        v = node("Verification", {"verifier_id": "v", "check": "test", "passed": True},
                 [Parent("subject", bad.id)], "v")
        self.store.put(bad)
        insert(self.store, v, "verify")
        illegal = node("Claim", {"statement": "cannot derive from verification"}, [Parent("evidence", v.id)])
        with self.assertRaises(ProvenanceError):
            self.store.put(illegal)
        for record in (o, v, node("Effect", {}, [Parent("action", bad.id)])):
            with self.subTest(kind=record.kind), self.assertRaises(ProvenanceError):
                self.store.put(record)

    def test_unknown_version_reports_offending_node(self):
        o = observation(self.store)
        body = json.loads(o.canonical_body)
        body["schema_version"] = "0.2"
        with self.store.write_transaction():
            self.store._db.execute("UPDATE nodes SET body=? WHERE id=?", (canonical_json(body), o.id))
        self.assertIn(("UNKNOWN_VERSION", o.id), {(p.code, p.node_id) for p in self.store.validate(o.id).errors})

    def test_cycle_rejection(self):
        a_id, b_id = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        a = node("Claim", {"statement": "a"}, [Parent("evidence", b_id)])
        b = node("Claim", {"statement": "b"}, [Parent("evidence", a_id)])
        raw_seed(self.store, [Node(a_id, a.canonical_body), Node(b_id, b.canonical_body)])
        self.assertIn("CYCLE", {p.code for p in self.store.validate(a_id).errors})
        downstream = node("Claim", {"statement": "downstream"}, [Parent("evidence", a_id)])
        with self.assertRaises(ProvenanceError):
            self.store.put(downstream)

    def test_deep_chain_does_not_use_python_recursion(self):
        # Seed a valid deep history once; validate it and append using the real public API.
        o = node("Observation", {"message": "deep"})
        records = [o]
        for i in range(1500):
            records.append(node("Claim", {"statement": str(i)}, [Parent("evidence", records[-1].id)]))
        raw_seed(self.store, records)
        tail = claim(self.store, records[-1], statement="final")
        report = self.store.validate(tail.id)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(len(report.visited), 1502)

    def test_transaction_rolls_back_and_missing_root_is_structured(self):
        o = node("Observation", {"message": "rolled back"})
        with self.assertRaises(RuntimeError):
            with self.store.write_transaction():
                self.store._insert(o, None)
                raise RuntimeError("interrupt")
        self.assertEqual(self.store.all_ids(), ())
        self.assertEqual(self.store.validate(o.id).errors[0].code, "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
