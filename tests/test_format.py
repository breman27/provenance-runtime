import hashlib
import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    from provenance.errors import ProvenanceError
    from provenance.format import canonical_json, parse_json, utc_timestamp
    from provenance.model import Parent, make_node, decode_node
    from provenance.rules import check_record, check_relationships
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False

NOW = "2026-10-07T00:00:00.000000Z"


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(API_AVAILABLE, "canonical record API is not implemented")

    def observation(self, **kwargs):
        args = dict(kind="Observation", payload={"message": "failed"}, parents=(),
                    producer="fixture:runner", created_at=NOW)
        args.update(kwargs)
        return make_node(**args)

    def test_canonical_json_vector(self):
        self.assertEqual(canonical_json({"z": 2, "a": 1}), b'{"a":1,"z":2}')
        self.assertEqual(hashlib.sha256(b'{"a":1,"z":2}').hexdigest(),
                         "99168216144c7fed5d4c54916cf98d9c66096280c04a499822a99b6658bd177a")

    def test_payload_is_defensive(self):
        payload = {"nested": ["original"]}
        node = self.observation(payload=payload)
        original = node.canonical_body
        payload["nested"].append("changed")
        node.payload["nested"].append("also changed")
        self.assertEqual(node.payload, {"nested": ["original"]})
        self.assertEqual(node.canonical_body, original)
        with self.assertRaises(AttributeError):
            node.id = "edited"

    def test_equivalent_instants_hash_equally(self):
        self.assertEqual(self.observation().id,
                         self.observation(created_at="2026-10-06T20:00:00-04:00").id)
        self.assertEqual(utc_timestamp(datetime(2026, 10, 7, tzinfo=timezone.utc)), NOW)

    def test_naive_datetime_rejected(self):
        for value in (datetime(2026, 10, 7), "2026-10-07T00:00:00"):
            with self.subTest(value=value), self.assertRaises(ProvenanceError):
                utc_timestamp(value)

    def test_parent_order_is_unordered(self):
        a, b = self.observation(), self.observation(payload={"different": True})
        make = lambda p: make_node("Claim", {"statement": "root cause"}, p, "reasoner", NOW)
        parents = (Parent("evidence", a.id), Parent("evidence", b.id))
        self.assertEqual(make(parents).id, make(reversed(parents)).id)
        with self.assertRaises(ProvenanceError):
            make(parents + (parents[0],))

    def test_payload_array_order_is_meaningful(self):
        self.assertNotEqual(self.observation(payload={"a": [1, 2]}).id,
                            self.observation(payload={"a": [2, 1]}).id)

    def test_creation_time_changes_id(self):
        self.assertNotEqual(self.observation().id,
                            self.observation(created_at="2026-10-07T00:00:01Z").id)

    def test_unicode_scalar_order(self):
        self.assertEqual(canonical_json({"\U00010000": 2, "\ue000": 1}),
                         '{"\ue000":1,"\U00010000":2}'.encode())
        self.assertEqual(canonical_json({"q": '"\\\n', "s": "é"}),
                         '{"q":"\\\"\\\\\\n","s":"é"}'.encode())

    def test_no_unicode_normalization(self):
        self.assertNotEqual(self.observation(payload={"s": "é"}).id,
                            self.observation(payload={"s": "e\u0301"}).id)

    def test_duplicate_json_keys_rejected(self):
        for data in (b'{"a":1,"a":2}', b'{"p":{"x":1,"x":2}}'):
            with self.subTest(data=data), self.assertRaises(ProvenanceError):
                parse_json(data)

    def test_invalid_json_domain_rejected(self):
        invalid = [1.0, float("nan"), float("inf"), 2**53, -(2**53), "\ud800", {1: "x"}, (1,)]
        for value in invalid:
            with self.subTest(value=repr(value)), self.assertRaises(ProvenanceError):
                canonical_json(value)
        for data in (b'NaN', b'Infinity', b'1.0', b'9007199254740992', b'"\\ud800"', b'\xef\xbb\xbf{}'):
            with self.subTest(data=data), self.assertRaises(ProvenanceError):
                parse_json(data)
        self.assertEqual(parse_json(b'[true,false,null,9007199254740991,-9007199254740991]'),
                         [True, False, None, 2**53 - 1, -(2**53 - 1)])

    def test_unknown_version_rejected(self):
        with self.assertRaises(ProvenanceError):
            self.observation(schema_version="0.2")

    def test_typed_parent_rules(self):
        observation = self.observation()
        claim = make_node("Claim", {"statement": "cause"},
                          [Parent("evidence", observation.id)], "reasoner", NOW)
        self.assertEqual(check_relationships(claim, {observation.id: observation}), ())
        bad_claim = make_node("Claim", {"statement": "cause"},
                              [Parent("justification", observation.id)], "reasoner", NOW)
        self.assertTrue(check_record(bad_claim) or check_relationships(bad_claim, {observation.id: observation}))
        self.assertTrue(check_record(make_node("Claim", {"statement": "cause"}, (), "reasoner", NOW)))
        self.assertTrue(check_record(self.observation(parents=[Parent("evidence", claim.id)])))
        self.assertTrue(check_record(make_node("Verification", {"verifier_id": "v", "check": "test", "passed": 1},
                                             [Parent("subject", claim.id)], "v", NOW)))

    def test_unknown_envelope_field_rejected(self):
        node = self.observation()
        body = json.loads(node.canonical_body)
        body["unexpected"] = True
        self.assertTrue(check_record(decode_node(node.id, canonical_json(body))))

    def test_golden_vectors_and_fresh_process(self):
        vectors = json.loads((Path(__file__).parent / "fixtures/v01-golden.json").read_text(encoding="utf-8"))
        for vector in vectors:
            with self.subTest(id=vector["id"]):
                body = vector["body"]
                node = make_node(body["kind"], body["payload"],
                                 [Parent(p["role"], p["id"]) for p in body["parents"]],
                                 body["producer"], body["created_at"])
                self.assertEqual(node.id, vector["id"])
                self.assertEqual(node.canonical_body.decode(), vector["canonical"])
        code = "from provenance.model import make_node; print(make_node('Observation', {'message':'failed'}, (), 'fixture:runner', '2026-10-07T00:00:00Z').id)"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), vectors[0]["id"])


if __name__ == "__main__":
    unittest.main()
