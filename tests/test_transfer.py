import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from provenance.errors import ProvenanceError
from provenance.format import canonical_json
from provenance.model import Parent
from provenance.projection import status, why
from provenance.runtime import Runtime, Policy
from provenance.store import Store
from tests.support import admitted_repair, policy_snapshot, node, alter_payload

try:
    from provenance.transfer import export_graph, import_graph
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(API_AVAILABLE, "historical graph transfer is not implemented")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.original = Store(self.root / "source.db")
        self.restored = Store(self.root / "restored.db")
        self.addCleanup(self.original.close)
        self.addCleanup(self.restored.close)
        self.clock = lambda: datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.runtime = Runtime(self.original, Policy(**policy_snapshot()), self.clock)
        self.r = admitted_repair(self.runtime)
        self.action = self.r["action"].id
        self.vs = tuple(self.r[k].id for k in ("targeted_tests", "full_suite"))
        self.authority = self.r["authority"].id
        self.effect = self.runtime.commit(self.action, self.vs, self.authority).effect_id

    def test_round_trip_preserves_history_without_trust(self):
        self.runtime.invalidate(self.runtime.controller("fixture:control"), self.r["code"].id, "bad collector")
        data = export_graph(self.original)
        # Input record ordering is irrelevant; store IDs and output ordering remain fixed.
        envelope = json.loads(data)
        envelope["nodes"].reverse()
        imported = import_graph(self.restored, json.dumps(envelope).encode())
        self.assertEqual(imported, self.original.all_ids())
        self.assertEqual(export_graph(self.restored), data)
        self.assertEqual(export_graph(self.original), data)
        self.assertEqual(status(self.restored, self.effect, "inspection"), "STALE")
        self.assertIsNone(self.restored.admission(self.authority))
        self.assertIsNone(self.restored._local_effect(self.action))
        for node_id in self.original.all_ids():
            self.assertEqual(self.original.get(node_id).canonical_body, self.restored.get(node_id).canonical_body)
            self.assertEqual(self.original.parent_ids(node_id), self.restored.parent_ids(node_id))
            self.assertTrue(self.restored.validate(node_id).ok)

    def test_imported_effect_never_satisfies_local_commit_or_grants_trust(self):
        import_graph(self.restored, export_graph(self.original))
        runtime = Runtime(self.restored, Policy(**policy_snapshot()), self.clock)
        with self.assertRaises(ProvenanceError) as caught:
            runtime.commit(self.action, self.vs, self.authority)
        self.assertEqual(caught.exception.problem.code, "UNTRUSTED")
        self.assertIsNone(self.restored._local_effect(self.action))
        self.assertIsNone(self.restored.admission(self.effect))

    def test_idempotent_reimport_does_not_change_existing_local_trust(self):
        data = export_graph(self.original)
        before = self.original.admission(self.authority)
        import_graph(self.original, data)
        import_graph(self.original, data)
        self.assertEqual(export_graph(self.original), data)
        self.assertEqual(self.original.admission(self.authority), before)
        self.assertEqual(self.original._local_effect(self.action), self.effect)

    def test_imported_control_affects_inspection_only(self):
        r = admitted_repair(Runtime(self.restored, Policy(**policy_snapshot()), self.clock))
        self.runtime.invalidate(self.runtime.controller("fixture:control"), self.r["code"].id, "imported correction")
        import_graph(self.restored, export_graph(self.original))
        self.assertEqual(status(self.restored, r["code"].id, "inspection"), "INVALID")
        self.assertEqual(status(self.restored, r["code"].id, "execution"), "VALID")

    def test_invalid_final_record_rolls_back_entire_import(self):
        envelope = json.loads(export_graph(self.original))
        envelope["nodes"][-1]["body"]["payload"]["tampered"] = True
        with self.assertRaises(ProvenanceError):
            import_graph(self.restored, canonical_json(envelope))
        self.assertEqual(self.restored.all_ids(), ())

    def test_missing_parent_fails_without_partial_import(self):
        envelope = json.loads(export_graph(self.original))
        envelope["nodes"] = [n for n in envelope["nodes"] if n["id"] != self.r["failure"].id]
        with self.assertRaises(ProvenanceError) as caught:
            import_graph(self.restored, canonical_json(envelope))
        self.assertEqual(caught.exception.problem.code, "MISSING_PARENT")
        self.assertEqual(self.restored.all_ids(), ())

    def test_forged_cycle_is_rejected_before_hash_validation(self):
        a_id, b_id = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        a = node("Claim", {"statement": "a"}, [Parent("evidence", b_id)])
        b = node("Claim", {"statement": "b"}, [Parent("evidence", a_id)])
        data = canonical_json({"format": "provenance-runtime-export", "version": "0.1", "nodes": [
            {"id": a_id, "body": json.loads(a.canonical_body)}, {"id": b_id, "body": json.loads(b.canonical_body)}]})
        with self.assertRaises(ProvenanceError) as caught:
            import_graph(self.restored, data)
        self.assertEqual(caught.exception.problem.code, "CYCLE")
        self.assertEqual(self.restored.all_ids(), ())

    def test_duplicate_id_conflicts_are_rejected(self):
        envelope = json.loads(export_graph(self.original))
        duplicate = dict(envelope["nodes"][0])
        duplicate["body"] = {**duplicate["body"], "producer": "changed"}
        envelope["nodes"].append(duplicate)
        with self.assertRaises(ProvenanceError):
            import_graph(self.restored, canonical_json(envelope))
        self.assertEqual(self.restored.all_ids(), ())

    def test_unknown_versions_and_noncanonical_body_representation_rejected(self):
        source = json.loads(export_graph(self.original))
        for kind in ("export", "node", "body_string"):
            envelope = json.loads(json.dumps(source))
            if kind == "export":
                envelope["version"] = "0.2"
            elif kind == "node":
                envelope["nodes"][0]["body"]["schema_version"] = "0.2"
            else:
                envelope["nodes"][0]["body"] = json.dumps(envelope["nodes"][0]["body"], indent=2)
            with self.subTest(kind=kind), self.assertRaises(ProvenanceError):
                import_graph(self.restored, canonical_json(envelope))
            self.assertEqual(self.restored.all_ids(), ())

    def test_export_rejects_corrupt_history(self):
        alter_payload(self.original, self.r["code"], message="tampered")
        with self.assertRaises(ProvenanceError):
            export_graph(self.original)

    def test_inspection_detects_disguised_imported_control(self):
        control_id = self.runtime.invalidate(self.runtime.controller("fixture:control"), self.r["code"].id, "invalid source")
        import_graph(self.restored, export_graph(self.original))
        self.assertEqual(status(self.restored, self.effect), "STALE")
        body = json.loads(self.restored.get(control_id).canonical_body)
        body["kind"] = "Observation"
        with self.restored.write_transaction():
            self.restored._db.execute("UPDATE nodes SET body=? WHERE id=?", (canonical_json(body), control_id))
        for query in (status, why):
            with self.subTest(query=query.__name__):
                with self.assertRaises(ProvenanceError) as caught:
                    query(self.restored, self.effect)
                self.assertEqual(caught.exception.problem.code, "HASH_MISMATCH")


if __name__ == "__main__":
    unittest.main()
