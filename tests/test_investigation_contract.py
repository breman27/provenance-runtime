import json
import tempfile
import unittest
from pathlib import Path
from provenance import Store, ProvenanceError
from provenance.clients.repo_repair.case import prepare_case, capture_snapshot, collect_source
from provenance.clients.repo_repair.errors import InvestigationError
from tests.investigation_support import runtime, decision_dict, CORRECT_PATCH, WRONG_PATCH

try:
    from provenance.clients.repo_repair.contract import AgentRequest, AgentRun, decode_decision, validate_patch, admit_decision, response_schema
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(AVAILABLE, "agent proposal contract is not implemented")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.case = prepare_case(Path(temp.name) / "case")
        self.store = Store(self.case.database)
        self.addCleanup(self.store.close)
        self.runtime = runtime(self.store)
        self.baseline = capture_snapshot(self.case, self.case.baseline_revision)
        self.source = collect_source(self.runtime, self.runtime.observer("collector"), self.case,
                                     self.case.baseline_revision, "source")
        self.request = AgentRequest("Repair clamp", "Plain integers; lower <= upper.", (self.source,), (), 1)

    def decode(self, value):
        return decode_decision(json.dumps(value).encode(), self.request.evidence)

    def test_exact_response_and_null_proposal(self):
        decision = self.decode(decision_dict(patch=None))
        claim, action = admit_decision(self.runtime, self.case, self.baseline, self.request,
                                      AgentRun(decision, "recorded", False, {}))
        self.assertEqual(self.store.get(claim).kind, "Claim")
        self.assertIsNone(action)
        self.assertNotIn(str(self.case.database), json.dumps(self.request.packet()))
        self.assertNotIn(self.source.node_id, json.dumps(self.request.packet()))

    def test_missing_extra_and_privileged_fields_rejected(self):
        before = self.store.all_ids()
        for field in ("passed", "authority_id", "id", "target_path"):
            bad = decision_dict()
            bad[field] = "forged"
            with self.subTest(field=field), self.assertRaises(InvestigationError):
                self.decode(bad)
        for field in decision_dict():
            bad = decision_dict()
            del bad[field]
            with self.subTest(field=field), self.assertRaises(InvestigationError):
                self.decode(bad)
        self.assertEqual(self.store.all_ids(), before)

    def test_aliases_must_be_distinct_and_offered(self):
        for aliases in ((), ("unknown",), ("source", "source")):
            with self.subTest(aliases=aliases), self.assertRaises(InvestigationError):
                self.decode(decision_dict(evidence=aliases))

    def test_limits_duplicate_keys_and_invalid_utf8(self):
        for field, value in (("claim_statement", "x" * 4001), ("summary", "x" * 4001),
                             ("patch_content", "é" * 4001), ("claim_statement", " ")):
            data = decision_dict()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(InvestigationError):
                self.decode(data)
        for data in (b'{"x":1,"x":2}', b'\xff', b'[]'):
            with self.subTest(data=data), self.assertRaises(InvestigationError):
                decode_decision(data, self.request.evidence)

    def test_valid_patch_and_crlf_normalization(self):
        self.assertEqual(validate_patch(CORRECT_PATCH.replace("\n", "\r\n")), CORRECT_PATCH.encode())
        branches = "def clamp(value, lower, upper):\n    if value < lower:\n        return lower\n    if value > upper:\n        return upper\n    return value\n"
        self.assertEqual(validate_patch(branches), branches.encode())

    def test_forbidden_ast_shapes_rejected(self):
        values = [
            "import os\n" + CORRECT_PATCH,
            "print('executed')\n" + CORRECT_PATCH,
            CORRECT_PATCH + "def extra():\n    return 0\n",
            "@print\n" + CORRECT_PATCH,
            "def clamp(value, lower, upper):\n    while True:\n        return value\n",
            "def clamp(value, lower, upper):\n    return eval('value')\n",
            "def clamp(value, lower, upper):\n    return value.__class__\n",
            "def clamp(value, lower, upper):\n    return value ** 100\n",
            "def clamp(value, lower, upper):\n    upper = value\n    return upper\n",
            "def clamp(value, lower, upper=10):\n    return value\n",
            "def clamp(value, lower, upper):\n    return [value][0]\n",
            "def clamp(value, lower, upper):\n    return 1000001\n",
        ]
        for content in values:
            with self.subTest(content=content[:60]), self.assertRaises(InvestigationError):
                validate_patch(content)

    def test_noop_proposal_does_not_create_action(self):
        claim, action = admit_decision(self.runtime, self.case, self.baseline, self.request,
                                      AgentRun(self.decode(decision_dict(WRONG_PATCH)), "recorded", False, {}))
        self.assertIsNone(action)
        self.assertEqual(self.store.get(claim).kind, "Claim")

    def test_action_binds_exact_candidate_and_evidence(self):
        claim_id, action_id = admit_decision(self.runtime, self.case, self.baseline, self.request,
                                            AgentRun(self.decode(decision_dict()), "recorded", False, {}))
        claim, action = self.store.get(claim_id), self.store.get(action_id)
        self.assertEqual([p.node_id for p in claim.parents], [self.source.node_id])
        self.assertEqual(action.payload["arguments"]["patch_content"], CORRECT_PATCH)
        self.assertEqual(action.payload["arguments"]["baseline_snapshot"], self.baseline.snapshot_hash)
        self.assertEqual(action.payload["arguments"]["target_path"], "src/clamp.py")
        self.assertNotEqual(action.payload["arguments"]["candidate_snapshot"], self.baseline.snapshot_hash)
        self.assertEqual(action.payload["resource"], "fixture:clamp:" + self.case.case_id)
        self.assertTrue(self.store.validate(action.id).ok)

    def test_invalidated_evidence_cannot_be_readmitted(self):
        decision = self.decode(decision_dict())
        self.runtime.invalidate(self.runtime.controller("controller"), self.source.node_id, "wrong source")
        before = self.store.all_ids()
        with self.assertRaises(InvestigationError):
            admit_decision(self.runtime, self.case, self.baseline, self.request, AgentRun(decision, "recorded", False, {}))
        self.assertEqual(self.store.all_ids(), before)


if __name__ == "__main__":
    unittest.main()
