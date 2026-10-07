"""Small typed grammar. Integrity and execution trust are separate checks."""
import hashlib
import re
from collections import Counter
from typing import Mapping

from .errors import Problem, ProvenanceError
from .format import canonical_json, parse_json, utc_timestamp
from .model import Node

KINDS = {"Observation", "Claim", "Verification", "ProposedAction", "Authority",
         "Effect", "Invalidation", "Supersession"}
PRIMARY = KINDS - {"Invalidation", "Supersession"}
ROLES = {
    "Observation": {},
    "Claim": {"evidence": {"Observation", "Claim"}},
    "ProposedAction": {"justification": {"Claim", "Verification"}},
    "Verification": {"subject": {"Claim", "ProposedAction"}, "evidence": {"Observation"}},
    "Authority": {"subject": {"ProposedAction"}},
    "Effect": {"action": {"ProposedAction"}, "verification": {"Verification"}, "authority": {"Authority"}},
    "Invalidation": {"target": PRIMARY},
    "Supersession": {"target": PRIMARY, "replacement": PRIMARY},
}
ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
FIELDS = {"schema_version", "kind", "payload", "parents", "producer", "created_at"}
PAYLOADS = {
    "Claim": {"statement": str},
    "ProposedAction": {"action_type": str, "resource": str, "arguments": dict},
    "Verification": {"verifier_id": str, "check": str, "passed": bool},
    "Authority": {"issuer_id": str, "subject": str, "action_id": str, "action_type": str,
                  "resource": str, "allowed": bool, "expires_at": str},
    "Invalidation": {"reason": str}, "Supersession": {"reason": str},
    "Effect": {"receipt": dict, "policy": dict, "policy_hash": str},
}


def is_causal(kind: str, role: str) -> bool:
    return kind not in {"Invalidation", "Supersession"} and role in ROLES.get(kind, {})


def check_record(node: Node) -> tuple[Problem, ...]:
    def problem(code, detail):
        return (Problem(code, node.id, detail),)
    try:
        body = parse_json(node.canonical_body)
        if type(body) is not dict or set(body) != FIELDS:
            return problem("SCHEMA", "node envelope fields do not match version 0.1")
        if body["schema_version"] != "0.1":
            return problem("UNKNOWN_VERSION", "unsupported node schema")
        kind, payload = body["kind"], body["payload"]
        if type(kind) is not str or kind not in KINDS or type(payload) is not dict:
            return problem("SCHEMA", "unknown kind or non-object payload")
        if not ID_PATTERN.fullmatch(node.id) or canonical_json(body) != node.canonical_body:
            return problem("SCHEMA", "invalid content ID or noncanonical bytes")
        if type(body["producer"]) is not str or not body["producer"].strip():
            return problem("SCHEMA", "producer must be nonempty text")
        if type(body["created_at"]) is not str or utc_timestamp(body["created_at"]) != body["created_at"]:
            return problem("SCHEMA", "timestamp is not canonical UTC")
        refs = body["parents"]
        if type(refs) is not list or any(type(p) is not dict or set(p) != {"role", "id"}
                                       or type(p["role"]) is not str or p["role"] not in ROLES[kind]
                                       or type(p["id"]) is not str or not ID_PATTERN.fullmatch(p["id"]) for p in refs):
            return problem("ILLEGAL_PARENT", "invalid parent reference or role")
        keys = [(p["role"], p["id"]) for p in refs]
        if keys != sorted(set(keys)):
            return problem("SCHEMA", "parents are not sorted and unique")
        counts = Counter(p["role"] for p in refs)
        exact = {"Verification": {"subject": 1}, "Authority": {"subject": 1},
                 "Effect": {"action": 1, "authority": 1},
                 "Invalidation": {"target": 1}, "Supersession": {"target": 1, "replacement": 1}}
        minimum = {"Claim": "evidence", "ProposedAction": "justification", "Effect": "verification"}
        if any(counts[r] != n for r, n in exact.get(kind, {}).items()) or (kind in minimum and not counts[minimum[kind]]):
            return problem("SCHEMA", "required parent cardinality is not satisfied")
        for field, expected in PAYLOADS.get(kind, {}).items():
            if type(payload.get(field)) is not expected or (expected is str and not payload[field].strip()):
                return problem("SCHEMA", f"invalid required payload field: {field}")
        if kind == "Authority":
            if utc_timestamp(payload["expires_at"]) != payload["expires_at"]:
                return problem("SCHEMA", "authority expiry is not canonical UTC")
            if payload["action_id"] != refs[0]["id"]:
                return problem("SCHEMA", "authority payload does not bind its subject")
        if kind == "Effect":
            snapshot = payload["policy"]
            if type(snapshot.get("requirements")) is not dict:
                return problem("SCHEMA", "effect lacks policy requirements")
            digest = "sha256:" + hashlib.sha256(canonical_json(snapshot)).hexdigest()
            if payload["policy_hash"] != digest:
                return problem("SCHEMA", "policy snapshot hash mismatch")
        return ()
    except (ProvenanceError, KeyError, TypeError, AttributeError) as error:
        return problem("SCHEMA", str(error))


def check_relationships(node: Node, parents: Mapping[str, Node]) -> tuple[Problem, ...]:
    errors = []
    for ref in node.parents:
        parent = parents.get(ref.node_id)
        if parent is None:
            errors.append(Problem("MISSING_PARENT", ref.node_id, "required parent is unavailable"))
        elif parent.kind not in ROLES[node.kind].get(ref.role, set()):
            errors.append(Problem("ILLEGAL_PARENT", node.id, f"{ref.role} cannot reference {parent.kind}"))
    if errors:
        return tuple(errors)
    if node.kind == "Supersession":
        by_role = {p.role: parents[p.node_id] for p in node.parents}
        if by_role["target"].kind != by_role["replacement"].kind:
            errors.append(Problem("ILLEGAL_PARENT", node.id, "replacement must have target's kind"))
    if node.kind == "Effect":
        action = next(parents[p.node_id] for p in node.parents if p.role == "action")
        authority = next(parents[p.node_id] for p in node.parents if p.role == "authority")
        verifications = [parents[p.node_id] for p in node.parents if p.role == "verification"]
        required = node.payload["policy"]["requirements"].get(action.payload["action_type"])
        checks = {v.payload["check"] for v in verifications if v.payload["passed"]}
        if (type(required) is not list or not required or any(type(c) is not str for c in required)
                or not set(required).issubset(checks)
                or authority.payload["action_id"] != action.id
                or any(not v.payload["passed"] or [p.node_id for p in v.parents if p.role == "subject"] != [action.id]
                       for v in verifications)):
            errors.append(Problem("ILLEGAL_PARENT", node.id, "effect verification or authority does not bind action"))
    return tuple(errors)
