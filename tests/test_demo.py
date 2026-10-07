import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from provenance.errors import ProvenanceError
from provenance.projection import status
from provenance.store import Store

try:
    from provenance.demo import run_demo
    from provenance import Runtime, Policy, Parent, make_node
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(API_AVAILABLE, "repo-repair demo is not implemented")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "demo.db"

    def test_demo_proves_effect_boundary(self):
        with Store(self.path) as store:
            report = run_demo(store)
            self.assertEqual(report["effect_count"], 1)
            self.assertEqual(report["effect_id"], report["retry_effect_id"])
            self.assertTrue(report["original_effect_still_exists"])
            self.assertEqual(report["action_status_before"], "VALID")
            self.assertEqual(report["action_status_after"], "STALE")
            self.assertEqual(report["historical_justification_status"], "STALE")
            self.assertEqual(report["denial_code"], "STALE")
            self.assertEqual(status(store, report["node_ids"]["failure"]), "VALID")
            self.assertEqual(status(store, report["node_ids"]["code_change"]), "INVALID")
            ancestry = {n["body"]["kind"] for n in report["why"]["nodes"]}
            self.assertEqual(ancestry, {"Observation", "Claim", "ProposedAction", "Verification", "Authority", "Effect"})
            checks = {n["body"]["payload"]["check"] for n in report["why"]["nodes"] if n["body"]["kind"] == "Verification"}
            self.assertEqual(checks, {"targeted_tests", "full_suite"})
            self.assertEqual(len(report["why"]["nodes"]), 8)
            self.assertEqual(len(report["why"]["controls"]), 1)

    def test_cli_emits_valid_json(self):
        result = subprocess.run([sys.executable, "-m", "provenance", "demo", "--db", str(self.path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["denial_code"], "STALE")
        self.assertEqual(report["effect_count"], 1)

    def test_invalid_cli_command_does_not_create_database(self):
        result = subprocess.run([sys.executable, "-m", "provenance", "invalid", "--db", str(self.path)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.path.exists())

    def test_nonempty_database_refuses_rerun_without_writes(self):
        with Store(self.path) as store:
            run_demo(store)
            before = store.all_ids()
            with self.assertRaises(ProvenanceError) as caught:
                run_demo(store)
            self.assertEqual(caught.exception.problem.code, "DEMO_NOT_EMPTY")
            self.assertEqual(store.all_ids(), before)

    def test_fixture_output_is_deterministic_across_databases(self):
        with Store(":memory:") as first, Store(":memory:") as second:
            self.assertEqual(run_demo(first), run_demo(second))


if __name__ == "__main__":
    unittest.main()
