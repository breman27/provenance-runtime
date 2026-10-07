"""Transfer inspectable history, never credentials or local execution rights."""
from .errors import ProvenanceError, fail
from .format import canonical_json, parse_json
from .model import Node
from .rules import check_record
from .store import Store
from .validation import validate_graph


def export_graph(store: Store) -> bytes:
    with store.read_snapshot():
        rows = []
        for node_id in store.all_ids():
            report = store.validate(node_id)
            if not report.ok:
                raise ProvenanceError(report.errors[0])
            rows.append({"id": node_id, "body": parse_json(store.get(node_id).canonical_body)})
        return canonical_json({"format": "provenance-runtime-export", "version": "0.1", "nodes": rows})


def _topology(roots, lookup):
    """Check availability/cycles before examining hashes; also produce insert order."""
    active, done, ordered = set(), set(), []
    for root in sorted(roots):
        stack = [(root, False)]
        while stack:
            node_id, exiting = stack.pop()
            if exiting:
                active.discard(node_id)
                done.add(node_id)
                ordered.append(node_id)
                continue
            if node_id in active:
                fail("CYCLE", "imported references contain a cycle", node_id)
            if node_id in done:
                continue
            try:
                record = lookup(node_id)
            except ProvenanceError:
                fail("MISSING_PARENT", "import parent is unavailable", node_id)
            errors = check_record(record)
            if errors:
                raise ProvenanceError(errors[0])
            active.add(node_id)
            stack.append((node_id, True))
            stack.extend((p.node_id, False) for p in reversed(record.parents))
    return tuple(ordered)


def import_graph(store: Store, data: bytes) -> tuple[str, ...]:
    envelope = parse_json(data)
    if (type(envelope) is not dict or set(envelope) != {"format", "version", "nodes"}
            or envelope["format"] != "provenance-runtime-export" or type(envelope["nodes"]) is not list):
        fail("SCHEMA", "invalid graph export envelope")
    if envelope["version"] != "0.1":
        fail("UNKNOWN_VERSION", "unsupported graph export version")
    staged = {}
    for item in envelope["nodes"]:
        if (type(item) is not dict or set(item) != {"id", "body"}
                or type(item["id"]) is not str or type(item["body"]) is not dict):
            fail("SCHEMA", "export nodes require a content ID and object body")
        record = Node(item["id"], canonical_json(item["body"]))
        if record.id in staged:
            fail("IMPORT_CONFLICT", "duplicate content ID in graph export", record.id)
        staged[record.id] = record
    with store.write_transaction():
        existing_ids = set(store.all_ids())
        for node_id, record in staged.items():
            if node_id in existing_ids and store.get(node_id).canonical_body != record.canonical_body:
                fail("IMPORT_CONFLICT", "existing content ID has different bytes", node_id)
        cache = dict(staged)
        def lookup(node_id):
            if node_id not in cache:
                cache[node_id] = store.get(node_id)
            return cache[node_id]
        order = _topology(staged, lookup)
        indices = lambda i: store._indexed_parents(i) if i in existing_ids else None
        for node_id in sorted(staged):
            report = validate_graph(node_id, lookup, indices)
            if not report.ok:
                raise ProvenanceError(report.errors[0])
        for node_id in order:
            if node_id in staged:
                store._insert(staged[node_id], None)
    return tuple(sorted(staged))
