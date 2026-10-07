"""Iterative validation follows canonical references, never trusting indexes."""
from dataclasses import dataclass
from typing import Callable

from .errors import Problem, ProvenanceError
from .model import Node, content_id
from .rules import check_record, check_relationships


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    visited: tuple[str, ...]
    errors: tuple[Problem, ...]


def validate_graph(root_id: str, lookup: Callable[[str], Node],
                   indexed_parents: Callable[[str], tuple] | None = None) -> ValidationReport:
    nodes, active, done, errors = {}, set(), set(), []
    stack = [(root_id, False)]
    while stack:
        node_id, exiting = stack.pop()
        if exiting:
            record = nodes[node_id]
            if all(p.node_id in nodes for p in record.parents):
                errors.extend(check_relationships(record, nodes))
            active.discard(node_id)
            done.add(node_id)
            continue
        if node_id in active:
            errors.append(Problem("CYCLE", node_id, "ancestor reference creates a cycle"))
            continue
        if node_id in done:
            continue
        try:
            record = lookup(node_id)
        except ProvenanceError as error:
            code = "NOT_FOUND" if node_id == root_id else "MISSING_PARENT"
            errors.append(Problem(code, node_id, error.problem.detail))
            done.add(node_id)
            continue
        if content_id(record.canonical_body) != node_id:
            errors.append(Problem("HASH_MISMATCH", node_id, "record bytes do not match retained content ID"))
        schema_errors = check_record(record)
        errors.extend(schema_errors)
        if schema_errors:
            done.add(node_id)
            continue
        nodes[node_id] = record
        refs = tuple((p.role, p.node_id) for p in record.parents)
        if indexed_parents is not None:
            actual = indexed_parents(node_id)
            if actual is not None and actual != refs:
                errors.append(Problem("INDEX_MISMATCH", node_id, "relationship rows differ from canonical parents"))
        active.add(node_id)
        stack.append((node_id, True))
        stack.extend((p.node_id, False) for p in reversed(record.parents))
    unique = tuple(dict.fromkeys(errors))
    return ValidationReport(not unique, tuple(sorted(nodes)), unique)
