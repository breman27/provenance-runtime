"""Handwritten fixtures and intentional storage corruption, used only by tests."""
import sqlite3
from provenance.format import canonical_json
from provenance.model import Parent, make_node

NOW = "2026-10-07T00:00:00.000000Z"


def node(kind, payload, parents=(), producer="fixture:runner", time=NOW):
    return make_node(kind, payload, parents, producer, time)


def insert(store, record, operation=None):
    from provenance.store import Admission
    with store.write_transaction():
        return store._insert(record, Admission(record.producer, operation) if operation else None)


def observation(store, message="failed", trusted=True):
    record = node("Observation", {"message": message})
    insert(store, record, "observe" if trusted else None)
    return record


def claim(store, *parents, statement="root cause"):
    record = node("Claim", {"statement": statement}, [Parent("evidence", p.id) for p in parents], "reasoner")
    store.put(record)
    return record


def raw_seed(store, records):
    """Bypass validation to simulate disk corruption and adversarial imports."""
    with store.write_transaction():
        for record in records:
            store._db.execute("INSERT INTO nodes(id,body) VALUES (?,?)", (record.id, record.canonical_body))
        for record in records:
            for ref in record.parents:
                store._db.execute("INSERT INTO edges(child_id,role,parent_id) VALUES (?,?,?)",
                                  (record.id, ref.role, ref.node_id))


def alter_payload(store, record, **fields):
    import json
    body = json.loads(record.canonical_body)
    body["payload"].update(fields)
    with store.write_transaction():
        store._db.execute("UPDATE nodes SET body=? WHERE id=?", (canonical_json(body), record.id))


def policy_snapshot():
    return {"version": "fixture-v1", "subject": "fixture:runtime", "observers": ["fixture:runner"],
            "verifiers": {"fixture:tester": ["targeted_tests", "full_suite"]},
            "issuers": ["fixture:authority"], "controllers": ["fixture:control"],
            "requirements": {"repo.repair.simulated": ["targeted_tests", "full_suite"]}}


def repair_records(store, include_effect=True):
    import hashlib
    records = {}
    records["failure"] = observation(store)
    records["code"] = observation(store, "code changed")
    records["claim"] = claim(store, records["failure"], records["code"])
    action = node("ProposedAction", {"action_type": "repo.repair.simulated", "resource": "fixture:repo",
                                     "arguments": {"patch": "fixed"}},
                  [Parent("justification", records["claim"].id)], "reasoner")
    records["action"] = action
    store.put(action)
    for name in ("targeted_tests", "full_suite"):
        v = node("Verification", {"verifier_id": "fixture:tester", "check": name, "passed": True},
                 [Parent("subject", action.id)], "fixture:tester")
        insert(store, v, "verify")
        records[name] = v
    authority = node("Authority", {"issuer_id": "fixture:authority", "subject": "fixture:runtime",
                                  "action_id": action.id, "action_type": "repo.repair.simulated",
                                  "resource": "fixture:repo", "allowed": True,
                                  "expires_at": "2026-10-07T01:00:00.000000Z"},
                     [Parent("subject", action.id)], "fixture:authority")
    insert(store, authority, "authorize")
    records["authority"] = authority
    if include_effect:
        policy = policy_snapshot()
        effect = node("Effect", {"receipt": {"action_id": action.id, "kind": "simulated-repo-repair"},
                                 "policy": policy,
                                 "policy_hash": "sha256:" + hashlib.sha256(canonical_json(policy)).hexdigest()},
                      [Parent("action", action.id), Parent("authority", authority.id)] +
                      [Parent("verification", records[k].id) for k in ("targeted_tests", "full_suite")],
                      "fixture:runtime")
        insert(store, effect, "effect")
        records["effect"] = effect
    return records


def admitted_repair(runtime):
    from datetime import datetime, timezone
    store = runtime.store
    ids = {}
    for name, message in (("failure", "failed"), ("code", "code changed")):
        ids[name] = runtime.observe(runtime.observer("fixture:runner"), {"message": message})
    ids["claim"] = runtime.submit(node("Claim", {"statement": "root cause"},
                                     [Parent("evidence", ids[k]) for k in ("failure", "code")], "reasoner"))
    ids["action"] = runtime.submit(node("ProposedAction", {"action_type": "repo.repair.simulated", "resource": "fixture:repo",
                                                          "arguments": {"patch": "fixed"}},
                                      [Parent("justification", ids["claim"])], "reasoner"))
    for check in ("targeted_tests", "full_suite"):
        ids[check] = runtime.verify(runtime.verifier("fixture:tester"), ids["action"], check, True)
    ids["authority"] = runtime.authorize(runtime.issuer("fixture:authority"), ids["action"], True,
                                         datetime(2026, 10, 7, 1, tzinfo=timezone.utc))
    return {k: store.get(v) for k, v in ids.items()}


def crash_worker(path, stage, action_id, verification_ids, authority_id, pipe):
    """Signal exact transaction boundaries to the parent; no production test hook."""
    from datetime import datetime, timezone
    from provenance.store import Store
    from provenance.runtime import Policy, Runtime
    with Store(path) as store:
        runtime = Runtime(store, Policy(**policy_snapshot()), lambda: datetime(2026, 10, 7, tzinfo=timezone.utc))
        if stage == "before_mapping":
            def pause_before_mapping(action, effect):
                pipe.send(stage)
                pipe.recv()
            store._bind_local_effect = pause_before_mapping
        runtime.commit(action_id, verification_ids, authority_id)
        pipe.send("after_commit")
        pipe.recv()
