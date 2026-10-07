"""SQLite storage. Public insertion accepts proposals, not trusted receipts."""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .errors import ProvenanceError, fail
from .model import Node
from .rules import is_causal, check_record
from .validation import validate_graph, ValidationReport


@dataclass(frozen=True)
class Admission:
    principal_id: str
    operation: str


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, body BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS edges(
                child_id TEXT NOT NULL REFERENCES nodes(id), role TEXT NOT NULL,
                parent_id TEXT NOT NULL REFERENCES nodes(id),
                PRIMARY KEY(child_id,role,parent_id));
            CREATE INDEX IF NOT EXISTS edges_reverse ON edges(parent_id,child_id);
            CREATE TABLE IF NOT EXISTS admissions(
                node_id TEXT PRIMARY KEY REFERENCES nodes(id),
                principal_id TEXT NOT NULL, operation TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS local_effects(
                action_id TEXT PRIMARY KEY REFERENCES nodes(id),
                effect_id TEXT NOT NULL UNIQUE REFERENCES nodes(id));
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._db.close()

    @contextmanager
    def write_transaction(self):
        if self._db.in_transaction:
            fail("TRANSACTION", "nested write transaction is not supported")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    @contextmanager
    def read_snapshot(self):
        if self._db.in_transaction:
            yield
            return
        self._db.execute("BEGIN")
        try:
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def get(self, node_id: str) -> Node:
        row = self._db.execute("SELECT body FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row is None:
            fail("NOT_FOUND", "record is unavailable", node_id)
        return Node(node_id, bytes(row[0]))

    def all_ids(self) -> tuple[str, ...]:
        return tuple(row[0] for row in self._db.execute("SELECT id FROM nodes ORDER BY id"))

    def _indexed_parents(self, node_id):
        return tuple(self._db.execute("SELECT role,parent_id FROM edges WHERE child_id=? ORDER BY role,parent_id",
                                      (node_id,)))

    def parent_ids(self, node_id: str, causal_only: bool = False) -> tuple[str, ...]:
        record = self.get(node_id)
        return tuple(sorted({parent_id for role, parent_id in self._indexed_parents(node_id)
                             if not causal_only or is_causal(record.kind, role)}))

    def child_ids(self, node_id: str, causal_only: bool = False) -> tuple[str, ...]:
        self.get(node_id)
        rows = self._db.execute("SELECT child_id,role FROM edges WHERE parent_id=? ORDER BY child_id", (node_id,))
        return tuple(sorted({child_id for child_id, role in rows
                             if not causal_only or is_causal(self.get(child_id).kind, role)}))

    def admission(self, node_id: str) -> Admission | None:
        row = self._db.execute("SELECT principal_id,operation FROM admissions WHERE node_id=?", (node_id,)).fetchone()
        return Admission(*row) if row else None

    def validate(self, node_id: str) -> ValidationReport:
        with self.read_snapshot():
            return validate_graph(node_id, self.get, self._indexed_parents)

    def put(self, node: Node) -> str:
        errors = check_record(node)
        if errors:
            raise ProvenanceError(errors[0])
        if node.kind not in {"Claim", "ProposedAction"}:
            fail("UNTRUSTED", "trusted record kind requires a dedicated runtime API", node.id)
        with self.write_transaction():
            return self._insert(node, None)

    def _insert(self, node: Node, admission: Admission | None) -> str:
        if not self._db.in_transaction:
            fail("TRANSACTION", "internal insertion requires an active transaction")
        existing = self._db.execute("SELECT body FROM nodes WHERE id=?", (node.id,)).fetchone()
        if existing is not None and bytes(existing[0]) != node.canonical_body:
            fail("HASH_MISMATCH", "existing content ID has different bytes", node.id)
        lookup = lambda node_id: node if node_id == node.id else self.get(node_id)
        indices = lambda node_id: None if node_id == node.id and existing is None else self._indexed_parents(node_id)
        report = validate_graph(node.id, lookup, indices)
        if not report.ok:
            raise ProvenanceError(report.errors[0])
        if existing is None:
            self._db.execute("INSERT INTO nodes(id,body) VALUES (?,?)", (node.id, node.canonical_body))
            self._db.executemany("INSERT INTO edges(child_id,role,parent_id) VALUES (?,?,?)",
                                 [(node.id, p.role, p.node_id) for p in node.parents])
        if admission is not None:
            self._db.execute("INSERT OR IGNORE INTO admissions(node_id,principal_id,operation) VALUES (?,?,?)",
                             (node.id, admission.principal_id, admission.operation))
        return node.id

    def _local_effect(self, action_id: str) -> str | None:
        row = self._db.execute("SELECT effect_id FROM local_effects WHERE action_id=?", (action_id,)).fetchone()
        return row[0] if row else None

    def _bind_local_effect(self, action_id: str, effect_id: str) -> None:
        if not self._db.in_transaction:
            fail("TRANSACTION", "effect mapping requires an active transaction")
        self._db.execute("INSERT INTO local_effects(action_id,effect_id) VALUES (?,?)", (action_id, effect_id))
