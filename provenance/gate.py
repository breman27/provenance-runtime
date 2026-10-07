"""One transaction admits a simulated local effect and its retry receipt."""
from dataclasses import dataclass

from .errors import Problem, ProvenanceError, fail
from .format import utc_timestamp
from .model import Parent, make_node
from .projection import status
from .store import Admission
from .validation import ValidationReport


@dataclass(frozen=True)
class CommitResult:
    effect_id: str
    reused: bool
    integrity: ValidationReport
    justification_status: str | None


def _validate(store, node_id):
    report = store.validate(node_id)
    if not report.ok:
        raise ProvenanceError(report.errors[0])
    return report


def _admitted(runtime, record, operation, approved, principal=None):
    admission = runtime.store.admission(record.id)
    expected = principal or record.producer
    if (admission is None or admission.operation != operation or admission.principal_id != expected
            or record.producer != expected or expected not in approved):
        fail("UNTRUSTED", f"{record.kind} lacks an approved local {operation} admission", record.id)


def _trusted_ancestry(runtime, report):
    for node_id in report.visited:
        record = runtime.store.get(node_id)
        if record.kind == "Observation":
            _admitted(runtime, record, "observe", runtime.policy.observers)
        elif record.kind == "Verification":
            verifier, check = record.payload["verifier_id"], record.payload["check"]
            _admitted(runtime, record, "verify", runtime.policy.verifiers, verifier)
            if check not in runtime.policy.verifiers[verifier]:
                fail("UNTRUSTED", "verifier is not approved for its check", node_id)


def _existing(runtime, action_id, effect_id):
    store = runtime.store
    report, state = store.validate(effect_id), None
    if report.ok:
        effect = store.get(effect_id)
        action_refs = [p.node_id for p in effect.parents if p.role == "action"]
        if effect.kind != "Effect" or action_refs != [action_id] or effect.payload["receipt"].get("action_id") != action_id:
            report = ValidationReport(False, report.visited,
                                      (Problem("MAPPING_MISMATCH", effect_id, "local receipt does not bind requested action"),))
        else:
            try:
                state = status(store, effect_id, "execution")
            except ProvenanceError as error:
                report = ValidationReport(False, report.visited, (error.problem,))
    return CommitResult(effect_id, True, report, state)


def commit_effect(runtime, action_id: str, verification_ids: tuple[str, ...],
                  authority_id: str | None) -> CommitResult:
    store, policy = runtime.store, runtime.policy
    with store.write_transaction():
        existing = store._local_effect(action_id)
        if existing is not None:
            return _existing(runtime, action_id, existing)
        action_report = _validate(store, action_id)
        action = store.get(action_id)
        if action.kind != "ProposedAction":
            fail("WRONG_ACTION", "commit requires a ProposedAction", action_id)
        action_type = action.payload["action_type"]
        if action_type != "repo.repair.simulated" or action_type not in policy.requirements:
            fail("POLICY_UNKNOWN", "no local effect handler and policy for action type", action_id)
        _trusted_ancestry(runtime, action_report)
        if status(store, action_id, "execution") != "VALID":
            fail("STALE", "action has unusable justification", action_id)
        checks = set()
        for verification_id in verification_ids:
            report = _validate(store, verification_id)
            verification = store.get(verification_id)
            if verification.kind != "Verification":
                fail("VERIFICATION_REQUIRED", "record is not a verification", verification_id)
            _trusted_ancestry(runtime, report)
            subject = [p.node_id for p in verification.parents if p.role == "subject"]
            if subject != [action_id]:
                fail("WRONG_ACTION", "verification binds a different action", verification_id)
            if not verification.payload["passed"]:
                fail("VERIFICATION_FAILED", "verification did not pass", verification_id)
            if status(store, verification_id, "execution") != "VALID":
                fail("STALE", "verification has unusable justification", verification_id)
            checks.add(verification.payload["check"])
        if not set(policy.requirements[action_type]).issubset(checks):
            fail("VERIFICATION_REQUIRED", "not every policy-required check has passed", action_id)
        if authority_id is None:
            fail("AUTHORITY_REQUIRED", "action has no authority receipt", action_id)
        _validate(store, authority_id)
        authority = store.get(authority_id)
        if authority.kind != "Authority":
            fail("AUTHORITY_REQUIRED", "record is not authority", authority_id)
        grant = authority.payload
        _admitted(runtime, authority, "authorize", policy.issuers, grant["issuer_id"])
        if (grant["action_id"] != action_id or grant["subject"] != policy.subject
                or grant["action_type"] != action_type or grant["resource"] != action.payload["resource"]):
            fail("AUTHORITY_SCOPE", "authority does not match action, subject and resource", authority_id)
        if not grant["allowed"]:
            fail("AUTHORITY_DENIED", "authority explicitly denies the action", authority_id)
        authority_state = status(store, authority_id, "execution")
        if authority_state in {"INVALID", "SUPERSEDED"}:
            fail("AUTHORITY_REVOKED", "authority has been revoked or superseded", authority_id)
        if authority_state != "VALID":
            fail("STALE", "authority has unusable justification", authority_id)
        now = utc_timestamp(runtime.clock())
        if now >= grant["expires_at"]:
            fail("AUTHORITY_EXPIRED", "authority has expired", authority_id)
        effect = make_node("Effect", {
            "receipt": {"kind": "simulated-repo-repair", "action_id": action_id},
            "policy": policy.snapshot(), "policy_hash": policy.content_hash(),
        }, [Parent("action", action_id), Parent("authority", authority_id)]
            + [Parent("verification", i) for i in verification_ids], policy.subject, now)
        store._insert(effect, Admission(policy.subject, "effect"))
        store._bind_local_effect(action_id, effect.id)
        return CommitResult(effect.id, False, store.validate(effect.id), "VALID")
