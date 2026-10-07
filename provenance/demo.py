"""Deterministic, manually populated fixture proving the effect boundary."""
from datetime import datetime, timezone

from .errors import ProvenanceError, fail
from .format import parse_json
from .model import Parent, make_node
from .projection import status, why
from .runtime import Policy, Runtime
from .store import Store


def run_demo(store: Store) -> dict:
    if store.all_ids():
        fail("DEMO_NOT_EMPTY", "demo requires a fresh database; existing history was preserved")
    instant = datetime(2026, 10, 7, tzinfo=timezone.utc)
    expiry = datetime(2026, 10, 7, 1, tzinfo=timezone.utc)
    policy = Policy("demo-v1", "fixture:runtime", ("fixture:runner",),
                    {"fixture:tester": ("targeted_tests", "full_suite")}, ("fixture:authority",),
                    ("fixture:control",), {"repo.repair.simulated": ("targeted_tests", "full_suite")})
    runtime = Runtime(store, policy, lambda: instant)
    ids = {}
    ids["failure"] = runtime.observe(runtime.observer("fixture:runner"),
                                     {"message": "auth_refresh_test failed", "fixture": True})
    ids["code_change"] = runtime.observe(runtime.observer("fixture:runner"),
                                         {"message": "code changed in abc123", "fixture": True})
    ids["root_cause"] = runtime.submit(make_node("Claim", {"statement": "abc123 introduced the regression"},
                                               [Parent("evidence", ids[k]) for k in ("failure", "code_change")],
                                               "fixture:reasoner", instant))
    action_payload = {"action_type": "repo.repair.simulated", "resource": "fixture:repo",
                      "arguments": {"patch": "replace expired auth state"}}
    ids["action"] = runtime.submit(make_node("ProposedAction", action_payload,
                                            [Parent("justification", ids["root_cause"])], "fixture:reasoner", instant))
    for check in ("targeted_tests", "full_suite"):
        ids[check] = runtime.verify(runtime.verifier("fixture:tester"), ids["action"], check, True)
    ids["authority"] = runtime.authorize(runtime.issuer("fixture:authority"), ids["action"], True, expiry)
    verification_ids = tuple(ids[k] for k in ("targeted_tests", "full_suite"))
    first = runtime.commit(ids["action"], verification_ids, ids["authority"])
    retry = runtime.commit(ids["action"], verification_ids, ids["authority"])
    before = status(store, ids["action"], "execution")
    ids["effect"] = first.effect_id
    ids["invalidation"] = runtime.invalidate(runtime.controller("fixture:control"), ids["code_change"],
                                              "code-change observation came from a faulty collector")
    next_payload = {**action_payload, "arguments": {"patch": "another repair based on the same evidence"}}
    ids["denied_action"] = runtime.submit(make_node("ProposedAction", next_payload,
                                                   [Parent("justification", ids["root_cause"])], "fixture:reasoner", instant))
    next_verifications = tuple(runtime.verify(runtime.verifier("fixture:tester"), ids["denied_action"], check, True)
                               for check in ("targeted_tests", "full_suite"))
    next_authority = runtime.authorize(runtime.issuer("fixture:authority"), ids["denied_action"], True, expiry)
    try:
        runtime.commit(ids["denied_action"], next_verifications, next_authority)
    except ProvenanceError as error:
        denial = error.problem.code
    else:
        fail("DEMO_INVARIANT", "runtime allowed an action with stale evidence")
    trace = why(store, first.effect_id, "execution")
    serialize = lambda record: {"id": record.id, "body": parse_json(record.canonical_body)}
    return {
        "mode": "simulation", "fixture_note": "Verification results are handwritten inputs; no repo tests were run.",
        "effect_id": first.effect_id, "retry_effect_id": retry.effect_id,
        "effect_count": sum(store.get(i).kind == "Effect" for i in store.all_ids()),
        "original_effect_still_exists": store.get(first.effect_id).kind == "Effect",
        "action_status_before": before, "action_status_after": status(store, ids["action"], "execution"),
        "historical_justification_status": trace.statuses[first.effect_id], "denial_code": denial,
        "node_ids": ids,
        "why": {"effect_id": trace.effect_id, "nodes": [serialize(n) for n in trace.nodes],
                "statuses": trace.statuses, "controls": [serialize(n) for n in trace.controls]},
    }
