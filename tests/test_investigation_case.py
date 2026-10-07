import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from provenance import Policy, Runtime, Store

try:
    from provenance.clients.repo_repair.case import prepare_case, capture_snapshot, collect_source, collect_diff, safe_path
    from provenance.clients.repo_repair.errors import InvestigationError
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(AVAILABLE, "real source collectors are not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "case"

    def test_fixture_revisions_and_snapshot_integrity(self):
        case = prepare_case(self.root)
        good = capture_snapshot(case, case.good_revision)
        bad = capture_snapshot(case, case.baseline_revision)
        self.assertNotEqual(good.file_hashes["src/clamp.py"], bad.file_hashes["src/clamp.py"])
        self.assertEqual(bad.file_hashes["src/clamp.py"], "sha256:" + hashlib.sha256(bad.files["src/clamp.py"]).hexdigest())
        self.assertNotEqual(good.snapshot_hash, bad.snapshot_hash)
        self.assertEqual(good.files["tests/test_clamp.py"], bad.files["tests/test_clamp.py"])
        self.assertFalse((case.agent_view / ".git").exists())

    def test_case_refuses_existing_directory(self):
        self.root.mkdir()
        sentinel = self.root / "important.txt"
        sentinel.write_text("preserve")
        with self.assertRaises(InvestigationError):
            prepare_case(self.root)
        self.assertEqual(sentinel.read_text(), "preserve")
        self.assertEqual(list(self.root.iterdir()), [sentinel])

    def test_case_paths_cannot_escape(self):
        case = prepare_case(self.root)
        for value in ("../outside", "src/../../outside", str(Path(self.temp.name) / "outside")):
            with self.subTest(value=value), self.assertRaises(InvestigationError):
                safe_path(case.root, value)

    def test_snapshot_preserves_source_bytes(self):
        case = prepare_case(self.root)
        snapshot = capture_snapshot(case, case.baseline_revision)
        original = snapshot.files["src/clamp.py"]
        snapshot.files["src/clamp.py"] = b"changed caller copy"
        self.assertEqual(snapshot.files["src/clamp.py"], original)
        self.assertEqual(capture_snapshot(case, case.baseline_revision).snapshot_hash, snapshot.snapshot_hash)

    def test_collectors_record_actual_revision_and_diff(self):
        case = prepare_case(self.root)
        with Store(case.database) as store:
            policy = Policy("case-v1", "client", ("collector",), {"tester": ("targeted_tests", "full_suite")},
                            ("issuer",), ("controller",), {"repo.repair.simulated": ("targeted_tests", "full_suite")})
            runtime = Runtime(store, policy, lambda: datetime(2026, 10, 7, 12, tzinfo=timezone.utc))
            source = collect_source(runtime, runtime.observer("collector"), case, case.good_revision, "old_source")
            diff = collect_diff(runtime, runtime.observer("collector"), case, case.good_revision, case.baseline_revision, "diff")
            self.assertEqual(source.payload["revision"], case.good_revision)
            self.assertNotEqual(source.payload["revision"], case.baseline_revision)
            self.assertIn("source_time", source.payload)
            self.assertIn("diff --git", diff.payload["diff"])
            self.assertEqual(store.get(source.node_id).kind, "Observation")
            self.assertTrue(store.validate(source.node_id).ok)
            source.payload["revision"] = "fake"
            self.assertEqual(source.payload["revision"], case.good_revision)


if __name__ == "__main__":
    unittest.main()
