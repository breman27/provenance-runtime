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
