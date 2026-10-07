"""Deterministic inputs for the example-client contract, not live model output."""
from datetime import datetime, timezone
from provenance import Policy, Runtime
from provenance.clients.repo_repair.case import GOOD_SOURCE, BAD_SOURCE

CORRECT_PATCH = GOOD_SOURCE.decode()
WRONG_PATCH = BAD_SOURCE.decode()


def policy():
    return Policy("repair-client-v1", "repair-client", ("collector", "human"),
                  {"tester": ("targeted_tests", "full_suite")}, ("issuer",), ("controller",),
                  {"repo.repair.simulated": ("targeted_tests", "full_suite")})


def runtime(store):
    return Runtime(store, policy(), lambda: datetime(2026, 10, 7, 12, tzinfo=timezone.utc))


def decision_dict(patch=CORRECT_PATCH, evidence=("source",)):
    return {"claim_statement": "The upper bound is not enforced.", "evidence_aliases": list(evidence),
            "patch_content": patch, "summary": "Clamp both bounds."}
