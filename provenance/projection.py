"""On-demand current status over immutable history and later controls."""
import heapq
from dataclasses import dataclass

from .errors import ProvenanceError, fail
from .model import Node
from .rules import is_causal
from .store import Store


@dataclass(frozen=True)
class Trace:
    effect_id: str
    nodes: tuple[Node, ...]
    statuses: dict[str, str]
    controls: tuple[Node, ...]


def _validated(store, node_id):
    report = store.validate(node_id)
    if not report.ok:
        raise ProvenanceError(report.errors[0])
    return {i: store.get(i) for i in report.visited}


def _ordered(nodes):
    remaining, children = {}, {i: set() for i in nodes}
    for node_id, record in nodes.items():
        deps = {p.node_id for p in record.parents if p.node_id in nodes}
        remaining[node_id] = len(deps)
        for parent_id in deps:
            children[parent_id].add(node_id)
    ready = [i for i, count in remaining.items() if not count]
    heapq.heapify(ready)
    result = []
    while ready:
        node_id = heapq.heappop(ready)
        result.append(nodes[node_id])
        for child in sorted(children[node_id]):
            remaining[child] -= 1
            if not remaining[child]:
                heapq.heappush(ready, child)
    if len(result) != len(nodes):
        fail("CYCLE", "cannot order cyclic ancestry")
    return tuple(result)


def _controls(store, ancestry, mode):
    if mode not in {"inspection", "execution"}:
        fail("MODE", "projection mode must be inspection or execution")
    controls = []
    for node_id in store.all_ids():
        record, admission = store.get(node_id), store.admission(node_id)
        if mode == "execution" and (admission is None or admission.operation != "control"):
            continue
        try:
            candidate = (record.kind in {"Invalidation", "Supersession"}
                         or (admission is not None and admission.operation == "control"))
            if not candidate:
                continue
            # Validate before consulting the target: tampering must not hide a control.
            _validated(store, node_id)
            # Canonical target links identify controls even when an index was altered.
            targets = [p.node_id for p in record.parents if p.role == "target"]
        except (KeyError, TypeError) as error:
            fail("SCHEMA", str(error), node_id)
        if any(target in ancestry for target in targets) or node_id in ancestry:
            controls.append(record)
    return tuple(sorted(controls, key=lambda n: n.id))


def _projection(store, node_id, mode):
    nodes = _validated(store, node_id)
    ordered = _ordered(nodes)
    controls = _controls(store, nodes, mode)
    invalid, superseded = set(), set()
    for record in controls:
        targets = {p.node_id for p in record.parents if p.role == "target"}
        if record.kind == "Invalidation":
            invalid.update(targets)
        elif record.kind == "Supersession":
            superseded.update(targets)
    states = {}
    for record in ordered:
        if record.id in invalid:
            value = "INVALID"
        elif record.id in superseded:
            value = "SUPERSEDED"
        elif any(states[p.node_id] != "VALID" for p in record.parents if is_causal(record.kind, p.role)):
            value = "STALE"
        else:
            value = "VALID"
        states[record.id] = value
    return ordered, states, controls


def status(store: Store, node_id: str, mode: str = "inspection") -> str:
    with store.read_snapshot():
        return _projection(store, node_id, mode)[1][node_id]


def why(store: Store, effect_id: str, mode: str = "inspection") -> Trace:
    with store.read_snapshot():
        nodes, states, controls = _projection(store, effect_id, mode)
        if store.get(effect_id).kind != "Effect":
            fail("QUERY_KIND", "why requires an Effect", effect_id)
        return Trace(effect_id, nodes, dict(sorted(states.items())), controls)


def evidence_for(store: Store, claim_id: str) -> tuple[Node, ...]:
    with store.read_snapshot():
        nodes = _validated(store, claim_id)
        if nodes[claim_id].kind != "Claim":
            fail("QUERY_KIND", "evidence_for requires a Claim", claim_id)
        return tuple(n for n in _ordered(nodes) if n.id != claim_id and n.kind in {"Claim", "Observation"})


def impacted_by(store: Store, node_id: str) -> tuple[str, ...]:
    with store.read_snapshot():
        _validated(store, node_id)
        reverse = {}
        for child_id in store.all_ids():
            record = store.get(child_id)
            for ref in record.parents:
                if is_causal(record.kind, ref.role):
                    reverse.setdefault(ref.node_id, set()).add(child_id)
        seen, pending = set(), [node_id]
        while pending:
            current = pending.pop()
            for child in sorted(reverse.get(current, ())):
                if child not in seen:
                    _validated(store, child)
                    seen.add(child)
                    pending.append(child)
        return tuple(sorted(seen))


def check_supersession(store: Store, target_id: str, replacement_id: str) -> None:
    with store.read_snapshot():
        target = _validated(store, target_id)[target_id]
        replacement = _validated(store, replacement_id)[replacement_id]
        if target.kind != replacement.kind:
            fail("ILLEGAL_PARENT", "replacement must have the target's kind", replacement_id)
        pending, seen = [replacement_id], set()
        while pending:
            current = pending.pop()
            if current == target_id:
                fail("ILLEGAL_PARENT", "replacement depends on the target", replacement_id)
            if current not in seen:
                seen.add(current)
                record = store.get(current)
                pending.extend(p.node_id for p in record.parents if is_causal(record.kind, p.role))
