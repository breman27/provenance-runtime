# Provenance Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a local provenance runtime that validates immutable evidence ancestry, derives current status, and gates a simulated effect on trusted verification and authority.

**Architecture:** Canonical JSON records form a content-addressed DAG in SQLite. Small modules implement record rules, persistence and integrity validation, status and queries, trusted admission, and the transactional effect gate. A deterministic repo-repair fixture proves the boundary without model integration or external writes.

**Tech Stack:** Python 3.12 or later; standard-library `json`, `hashlib`, `datetime`, `sqlite3`, `unittest`, and `argparse`. No third-party runtime or test dependencies.

**Spec:** [Approved design](C:/Users/bsema/Documents/Codex/2026-10-07/alr/outputs/2026-10-07-provenance-runtime-design.md), approved in this chat on October 7, 2026.

## Global constraints

- “The model-facing interface accepts only Claim and ProposedAction.”
- “Unknown schema versions fail closed.” V0 supports exactly `schema_version = "0.1"`.
- “Status is a derived view.” Do not persist current truth or a status cache.
- “Parent references are sorted by role and ID; duplicate references are rejected. Array order inside payloads remains meaningful.”
- “Timestamp format is UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`.”
- JSON integers are limited to `-(2^53 - 1)` through `2^53 - 1`; reject floats, duplicate input keys, and unpaired surrogates.
- Node hash input is ASCII `provenance-runtime:node:0.1`, one LF byte (`0x0A`), and canonical body bytes.
- “Imported historical Effects are queryable but do not populate the local commit mapping.”
- “Imported control records cannot invalidate or authorize locally executable history.”
- The only executable action type in this milestone is `repo.repair.simulated`; its required checks are exactly `targeted_tests` and `full_suite`.
- “No actual repository writes or network calls occur.” This applies to the runtime's effects; normal development commits record the implementation.
- Historical records remain immutable. Local trusted admission is execution metadata, never inferred from a producer label or restored from an export.

## Review focus

1. Mutating a caller's payload after record creation must not mutate a record or its ID — Task 1.
2. Two timestamps denoting the same instant must hash alike; a naive datetime must be rejected — Task 1.
3. A tampered Invalidation outside an effect's original ancestry must prevent using a misleading execution-status projection — Task 3.
4. An imported Effect with a matching action hash must not suppress or masquerade as a locally committed effect — Tasks 5 and 6.
5. A process dying after writing an Effect but before writing its action mapping must leave neither write committed — Task 5.

## Workspace and commands

Create the deliverable project at:

`C:/Users/bsema/workspace/provenance-runtime`

This directory will be a new Git repository at execution time. Do not create it until the plan review and execution-method selection are complete. Use `work/` in the chat workspace for scratch scripts and transient test results. No separate worktree is needed for a new, dedicated repository with no existing checkout to isolate.

Verified runtime: Python 3.12.14 with SQLite 3.53.1. In PowerShell, set:

```powershell
$provenancePython = 'C:\Users\bsema\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
```

All commands below run with the project directory as their working directory. Use `& $provenancePython -m unittest tests.test_format -v` for a targeted module, substituting the task's test module. Final suite command: `& $provenancePython -m unittest discover -s tests -v`. Success means exit code 0 and the unittest summary `OK`; skipped acceptance tests do not satisfy this plan.

## Files and responsibilities

| Path, relative to the project | Responsibility |
| --- | --- |
| `provenance/__init__.py` | Small public API surface. |
| `provenance/errors.py` | Structured errors shared by modules. |
| `provenance/format.py` | Restricted JSON parsing/encoding and timestamps. |
| `provenance/model.py` | Immutable Node/Parent values, hashes, and version dispatch. |
| `provenance/rules.py` | Payload schemas, typed relationships, causal-role classification. |
| `provenance/store.py` | SQLite transactions, rows, indexes, and admission metadata. |
| `provenance/validation.py` | Iterative ancestry and integrity validation. |
| `provenance/projection.py` | Invalidation, supersession, status, and causal queries. |
| `provenance/runtime.py` | Registered trusted handles and model-facing submission. |
| `provenance/gate.py` | Policy checks and local atomic effect commit. |
| `provenance/transfer.py` | Deterministic export and atomic historical import. |
| `provenance/demo.py`, `provenance/__main__.py` | Repo-repair fixture and CLI. |
| `tests/support.py` | Shared deterministic fixtures; deliberate corruption helpers stay here. |
| `tests/test_format.py`, `tests/test_store.py`, `tests/test_projection.py`, `tests/test_runtime.py`, `tests/test_gate.py`, `tests/test_transfer.py`, `tests/test_demo.py` | Acceptance tests owned by their corresponding task. |
| `tests/fixtures/v01-golden.json` | Fixed canonical bytes and node hashes, not generated by the implementation under test. |
| `README.md`, `.gitignore`, `pyproject.toml`, `docs/superpowers/specs/2026-10-07-provenance-runtime-design.md`, `docs/superpowers/plans/2026-10-07-provenance-runtime-plan.md` | Usage, packaging metadata, and copies of approved project documents. |

## Shared interface decisions

Types below belong to the first task that produces them. Later tasks reuse these names without renaming them.

- `Parent(role: str, node_id: str)` is immutable. JSON representation: `{"role": role, "id": node_id}`.
- `Node(id: str, canonical_body: bytes)` is immutable. Properties `kind`, `payload`, `parents`, `producer`, `created_at`, and `schema_version` decode the body; `payload` returns a defensive copy and `parents` a tuple of Parent values.
- `Problem(code: str, node_id: str | None, detail: str)` and `ProvenanceError(problem: Problem)` live in `errors.py`.
- `ValidationReport(ok: bool, visited: tuple[str, ...], errors: tuple[Problem, ...])` belongs to `validation.py`.
- `Admission(principal_id: str, operation: str)` belongs to `store.py`. Operations are `observe`, `verify`, `authorize`, `control`, and `effect`; imported records have no Admission.
- Modes are exactly `inspection` and `execution`. Inspection includes declared imported controls. Execution includes only locally admitted controls; it does not confer trust on imported observations or verification.
- Query node sequences use parent-before-child topological order, with lexical node ID order to break ties; sets of IDs are returned as sorted tuples. Deduplicate shared ancestry.
- `CommitResult(effect_id: str, reused: bool, integrity: ValidationReport, justification_status: str | None)` belongs to `gate.py`. A corrupt existing receipt returns integrity errors and status `None`; a fresh commit with invalid ancestry raises ProvenanceError.

### Task 1: Canonical records and typed grammar

**Files:** Create `provenance/__init__.py`, `errors.py`, `format.py`, `model.py`, `rules.py`, `tests/__init__.py`, `tests/test_format.py`, `tests/fixtures/v01-golden.json`, `.gitignore`, and `pyproject.toml`. Copy the approved spec and plan into their mapped `docs/` locations. Initialize the dedicated Git repository as part of this task.

**Interfaces produced:**
- `canonical_json(value: object) -> bytes`, `parse_json(data: bytes) -> object`, `utc_timestamp(value: datetime | str) -> str`.
- `make_node(kind: str, payload: dict, parents: Iterable[Parent], producer: str, created_at: datetime | str, schema_version: str = "0.1") -> Node`.
- `decode_node(node_id: str, body: bytes) -> Node`; retain supplied ID for validation rather than silently recomputing it.
- `check_record(node: Node) -> tuple[Problem, ...]`, `check_relationships(node: Node, parents: Mapping[str, Node]) -> tuple[Problem, ...]`, `is_causal(kind: str, role: str) -> bool`.

- [x] Write `test_canonical_json_vector` with these exact assertions:
  ```python
  self.assertEqual(canonical_json({"z": 2, "a": 1}), b'{"a":1,"z":2}')
  self.assertEqual(hashlib.sha256(b'{"a":1,"z":2}').hexdigest(),
                   '99168216144c7fed5d4c54916cf98d9c66096280c04a499822a99b6658bd177a')
  ```
  Add named tests `test_payload_is_defensive`, `test_equivalent_instants_hash_equally`, `test_naive_datetime_rejected`, `test_parent_order_is_unordered`, `test_payload_array_order_is_meaningful`, `test_creation_time_changes_id`, `test_unicode_scalar_order`, `test_no_unicode_normalization`, `test_duplicate_json_keys_rejected`, `test_invalid_json_domain_rejected`, `test_unknown_version_rejected`, and `test_typed_parent_rules`. Use subtests for boolean/integer boundaries, floats, surrogate strings, duplicate roles/IDs, and each illegal relationship.
- [x] Run `& $provenancePython -m unittest tests.test_format -v`; confirm the new API is absent before implementation, then that tests expose behavior failures once minimal imports exist.
- [x] Implement the produced interfaces. Use strict `json` hooks before any lossy decoding, UTF-8 `json.dumps` with compact separators and sorted keys, and explicit recursive domain checks. Node canonical bodies contain exactly the six fields named by the spec. Pin full golden Observation and multi-parent Claim bodies and IDs in the fixture using an independently checked byte/hash calculation. Re-run those fixtures in a fresh interpreter as a portability check.
- [x] Define required payloads: Claim has `statement: str`; ProposedAction has `action_type: str`, `resource: str`, `arguments: dict`; Verification has `verifier_id: str`, `check: str`, `passed: bool`; Authority has `issuer_id`, `subject`, `action_id`, `action_type`, `resource`, `allowed: bool`, `expires_at`; controls have `reason: str`; Effect has `receipt`, `policy`, `policy_hash`. Observation accepts any supported JSON object. Required strings are nonempty; reject unknown envelope fields and unknown parent roles.
- [x] Encode relationships from the spec. Authority has exactly one `subject` ProposedAction; Invalidation has one `target`; Supersession has one `target` and one same-kind `replacement`. Control roles are noncausal. Effect roles are `action`, `authority`, and one or more `verification`; required named checks are enforced using its policy snapshot. All other causal roles follow the approved table. Reject Observation parents and duplicate references.
- [x] Run `tests.test_format`; require all tests to pass. Commit the task's files with message `feat: define canonical provenance records and grammar`.

### Task 2: SQLite store and deep integrity validation

**Files:** Create `store.py`, `validation.py`, `tests/support.py`, `tests/test_store.py`; modify public exports.

**Consumes:** Task 1 format, Node, Parent, and rules interfaces.
**Produces:** `Store(path: str | Path)` with context-manager support, `get(node_id: str) -> Node`, `all_ids() -> tuple[str, ...]`, `parent_ids(node_id: str, causal_only: bool = False) -> tuple[str, ...]`, `child_ids(node_id: str, causal_only: bool = False) -> tuple[str, ...]`, `put(node: Node) -> str`, `admission(node_id: str) -> Admission | None`, `validate(node_id: str) -> ValidationReport`, `write_transaction() -> ContextManager[None]`; internal `_insert(node: Node, admission: Admission | None) -> str` and `_local_effect(action_id: str) -> str | None`.

- [x] Write named tests for persistence after reopen, idempotent identical insertion, branching and joining, missing parent rejection, raw-SQL ancestor mutation, relationship-index mutation, illegal typed edges, unknown version, cycle rejection, and a chain of at least 1,500 Claims. Assert failures identify the offending ancestor; assert successful shared ancestry is visited once. `Store.put` must reject trusted kinds, including Effect; fixtures use internal `_insert` until Task 4 provides runtime APIs.
  Representative assertions in `test_ancestor_mutation_is_reported`, after building a Claim over an Observation and corrupting that Observation through the test's raw connection:
  ```python
  report = store.validate(claim_id)
  self.assertFalse(report.ok)
  self.assertIn(("HASH_MISMATCH", observation_id),
                {(p.code, p.node_id) for p in report.errors})
  ```
- [x] Run `& $provenancePython -m unittest tests.test_store -v`; confirm new behavior fails.
- [x] Implement append-only `nodes`, `edges`, `admissions`, and `local_effects` tables with primary/foreign keys and reverse-edge indexes. Enable foreign keys, a 5,000 ms busy timeout, and `synchronous=FULL`. Use explicit `BEGIN IMMEDIATE` for write transactions and rollback on exceptions. Internal insertion requires an active transaction; public `put` permits only Claim and ProposedAction and manages that transaction.
- [x] Implement iterative validation over canonical parent references, checking stored indexes in both directions. Validate hashes, payloads, schemas, required parents, and relationship types; report codes `HASH_MISMATCH`, `MISSING_PARENT`, `CYCLE`, `SCHEMA`, `UNKNOWN_VERSION`, `ILLEGAL_PARENT`, `INDEX_MISMATCH`, and `NOT_FOUND`. Reject partial inserts; decode failures become Problems rather than successful reports.
- [x] Run `tests.test_store` and the affected `tests.test_format`; require pass. Commit with message `feat: persist and validate provenance ancestry`.

### Task 3: Control records, status, and provenance queries

**Files:** Create `projection.py`, `tests/test_projection.py`; extend test support and public exports.

**Consumes:** Store and ValidationReport.
**Produces:** `status(store: Store, node_id: str, mode: str = "inspection") -> str`, `impacted_by(store: Store, node_id: str) -> tuple[str, ...]`, `evidence_for(store: Store, claim_id: str) -> tuple[Node, ...]`, `why(store: Store, effect_id: str, mode: str = "inspection") -> Trace`. `Trace` contains `effect_id`, `nodes: tuple[Node, ...]`, `statuses: dict[str, str]`, and `controls: tuple[Node, ...]`. Internal `check_supersession(store: Store, target_id: str, replacement_id: str) -> None` rejects kind mismatch or causal dependence on the target.

- [x] Write tests asserting exact statuses VALID, INVALID, SUPERSEDED, and STALE; invalidation wins over supersession; transitive descendants become stale while an unrelated branch stays valid. Assert original bytes and historical Effect remain unchanged. Check Supersession rejects a replacement dependent on the target. Invalidation does not become stale merely because its target is invalid. Assert exact deterministic query sets and ordering.
  In `test_invalidation_preserves_history`, construct the graph and append a trusted control through the internal fixture insertion API:
  ```python
  self.assertEqual(status(store, observation_id), "INVALID")
  self.assertEqual(status(store, claim_id), "STALE")
  self.assertEqual(status(store, effect_id), "STALE")
  self.assertEqual(store.get(effect_id).canonical_body, original_effect_bytes)
  self.assertEqual(status(store, unrelated_observation_id), "VALID")
  self.assertEqual(status(store, invalidation_id), "VALID")
  ```
- [x] Add `test_tampered_external_control_fails_projection`: append a locally admitted control referencing an ancestor, corrupt its stored body, and assert execution status raises a structured integrity error instead of accepting or silently ignoring it. Add `test_imported_control_is_inspection_only` with inspection INVALID and execution VALID for the same otherwise-valid locally admitted Observation.
- [x] Run `& $provenancePython -m unittest tests.test_projection -v`; confirm failures.
- [x] Implement status from validated causal ancestry and relevant control records, using a single consistent read snapshot per public query. Validate relevant control records and their ancestry before applying them. Treat invalidation/supersession target links as noncausal. Raise ProvenanceError on malformed projections or an inappropriate query kind. Derive status on demand; do not materialize a truth table.
- [x] Run `tests.test_projection` and affected store tests; require pass. Commit with message `feat: derive stale evidence and provenance queries`.

### Task 4: Trusted runtime admission and policy

**Files:** Create `runtime.py`, `tests/test_runtime.py`; extend public exports and test support.

**Consumes:** Canonical records, Store, supersession check, and projection interfaces.
**Produces:** `Policy(version: str, subject: str, observers: tuple[str, ...], verifiers: dict[str, tuple[str, ...]], issuers: tuple[str, ...], controllers: tuple[str, ...], requirements: dict[str, tuple[str, ...]])`, with `snapshot() -> dict` and `content_hash() -> str`. `Runtime(store: Store, policy: Policy, clock: Callable[[], datetime])` produces registry-bound ObserverHandle, VerifierHandle, AuthorityHandle, and ControlHandle through `observer(id)`, `verifier(id)`, `issuer(id)`, and `controller(id)`.

Runtime methods:
- `submit(node: Node) -> str`: Claim or ProposedAction only, no admission attached.
- `observe(handle: ObserverHandle, payload: dict) -> str`.
- `verify(handle: VerifierHandle, subject_id: str, check: str, passed: bool, evidence_ids: tuple[str, ...] = ()) -> str`.
- `authorize(handle: AuthorityHandle, action_id: str, allowed: bool, expires_at: datetime) -> str`.
- `invalidate(handle: ControlHandle, target_id: str, reason: str) -> str`.
- `supersede(handle: ControlHandle, target_id: str, replacement_id: str, reason: str) -> str`.

- [x] Write tests: spoofed producer labels never create admissions; handles from another Runtime are rejected; unknown principal IDs are rejected; model submission rejects Observation, Verification, Authority, Effect, and controls; approved verifier handles can issue only their registered check names. Assert every trusted record's admission matches the operation/principal, timestamps use the injected clock, and complete policy snapshots/hash values are deterministic.
  In `test_model_cannot_upgrade_producer_label`, use an Observation node labeled with the approved observer ID and an ordinary Claim node:
  ```python
  with self.assertRaises(ProvenanceError):
      runtime.submit(spoofed_observation)
  claim_id = runtime.submit(claim)
  self.assertIsNone(store.admission(claim_id))
  observation_id = runtime.observe(runtime.observer("fixture:runner"), {"message": "failed"})
  self.assertEqual(store.admission(observation_id), Admission("fixture:runner", "observe"))
  ```
- [x] Run `& $provenancePython -m unittest tests.test_runtime -v`; confirm failures.
- [x] Implement opaque handles authenticated by registry object identity, not caller-supplied serialized fields. Runtime methods use internal store insertion in a transaction and copy the action's immutable scope into authority records. Verify subjects and supporting evidence roles. Handle capability checks and admission metadata remain outside model input. Keep simulated action names in policy configuration and the demo, not record-kind names.
- [x] Run `tests.test_runtime` and affected projection tests; require pass. Commit with message `feat: separate model proposals from trusted admission`.

### Task 5: Transactional effect gate and crash recovery

**Files:** Create `gate.py`, `tests/test_gate.py`; extend Runtime with `commit(action_id: str, verification_ids: tuple[str, ...], authority_id: str | None) -> CommitResult`; extend Store with internal `_bind_local_effect(action_id: str, effect_id: str) -> None`.

**Consumes:** Policy, trusted admissions, Store transactions/validation, and execution-mode status.
**Produces:** `commit_effect(runtime: Runtime, action_id: str, verification_ids: tuple[str, ...], authority_id: str | None) -> CommitResult` and the shared CommitResult value.

- [x] Write the allowed fixture test and subtests for missing/failed/incomplete/untrusted/wrong-action verification; denied/missing/untrusted/wrong-subject/wrong-resource/expired/revoked authority; stale evidence; modified patch; unknown action policy. Use test support to construct deliberately malformed but locally admitted scope records where the ordinary authority API would otherwise prevent them. Assert every denial adds zero Effect rows and zero mappings.
  In `test_commit_is_idempotent`, build the approved repair fixture through Runtime APIs:
  ```python
  first = runtime.commit(action_id, verification_ids, authority_id)
  retry = runtime.commit(action_id, verification_ids, authority_id)
  self.assertTrue(first.integrity.ok)
  self.assertFalse(first.reused)
  self.assertTrue(retry.reused)
  self.assertEqual(first.effect_id, retry.effect_id)
  self.assertEqual(first.justification_status, "VALID")
  self.assertEqual(sum(store.get(i).kind == "Effect" for i in store.all_ids()), 1)
  ```
- [x] Write retry tests: same action returns the original ID with `reused=True`; authority expiration after commit does not create a second Effect; invalidation after commit preserves history and reports STALE; corrupt existing ancestry yields an invalid integrity report and no new writes. Add `test_imported_effect_does_not_count_as_local_commit`.
- [x] Write a competing-commit test with two separate Store connections and synchronized workers; assert one Effect and one mapping. Use an injected clock, not sleeps, for expiry tests. Write subprocess crash tests with database writes paused immediately before `_bind_local_effect` and immediately after transaction commit; terminate the child, reopen the DB, and assert respectively zero or one complete receipts/mappings. Synchronize via a pipe; any test hook belongs to tests, not a production crash feature.
- [x] Run `& $provenancePython -m unittest tests.test_gate -v`; confirm failures.
- [x] Implement the spec's five-step commit in one `BEGIN IMMEDIATE` transaction. Check an existing local receipt before evaluating today's authority expiry. Fresh effects require trusted observation ancestry, approved and locally admitted verifications for every named check on the exact action, execution-valid dependencies, and matching locally admitted authority. Reject expiry when `now >= expires_at`. Include a complete policy snapshot and its content hash in the Effect. Policy hash is `sha256:` plus SHA-256 of `canonical_json(snapshot)`.
- [x] Persist runtime-created Effect and unique action mapping together; never execute imported Effects. Fresh denials use structured error codes `UNTRUSTED`, `STALE`, `VERIFICATION_REQUIRED`, `VERIFICATION_FAILED`, `WRONG_ACTION`, `AUTHORITY_REQUIRED`, `AUTHORITY_SCOPE`, `AUTHORITY_DENIED`, `AUTHORITY_EXPIRED`, `AUTHORITY_REVOKED`, or `POLICY_UNKNOWN`. Corrupted fresh ancestry retains the validator's exact Problem.
- [x] Run `tests.test_gate` and affected runtime/projection tests; require pass, including actual reopen/crash assertions. Commit with message `feat: gate simulated effects with atomic retry recovery`.

### Task 6: Portable export and atomic historical import

**Files:** Create `transfer.py`, `tests/test_transfer.py`; extend Store only as needed for staging/import and public exports.

**Consumes:** Format, rules, Store validation, and queries.
**Produces:** `export_graph(store: Store) -> bytes`, `import_graph(store: Store, data: bytes) -> tuple[str, ...]`.

- [x] Write round-trip tests into a fresh DB: identical canonical bodies, IDs, relationships, inspection statuses, and historical receipts; identical repeated export bytes. Assert no trusted admission or local action mapping is recreated. Test invalid final record rollback, missing parent, forged cycle, duplicate ID conflict, noncanonical body, unknown schema/export version, and idempotent re-import. Importing controls against existing local records changes only inspection status. Assert a valid imported Effect cannot satisfy the local retry lookup or create authorization.
  In `test_round_trip_preserves_history_without_trust`, export a committed fixture with a later invalidation and import into a new Store:
  ```python
  self.assertEqual(export_graph(restored), export_graph(original))
  self.assertEqual(status(restored, effect_id, "inspection"), "STALE")
  self.assertIsNone(restored.admission(authority_id))
  self.assertIsNone(restored._local_effect(action_id))
  self.assertEqual(restored.get(effect_id).canonical_body,
                   original.get(effect_id).canonical_body)
  ```
- [x] Run `& $provenancePython -m unittest tests.test_transfer -v`; confirm failures.
- [x] Define export envelope `{"format":"provenance-runtime-export","version":"0.1","nodes":[{"id":...,"body":...}]}`. Emit nodes in lexical ID order from one read snapshot. Export every record, including controls and historical Effects, but omit local admission registry and local commit mapping. Decode strictly, stage all records, check cycles/missing parents before hash validation, then validate against the union of staged and existing records. Commit imported rows atomically with no admissions. Reject same-ID/different-body conflicts. Never call runtime effect commit during import.
- [x] Run `tests.test_transfer` and affected gate tests; require pass. Commit with message `feat: transfer historical graphs without execution trust`.

### Task 7: Repo-repair demo, public API, and final validation

**Files:** Create `demo.py`, `__main__.py`, `tests/test_demo.py`, `README.md`; finalize `__init__.py` and packaging metadata.

**Consumes:** Runtime, queries, gate, and transfer.
**Produces:** `run_demo(store: Store) -> dict`; `python -m provenance demo --db PATH` emits deterministic structured JSON. The report contains `effect_id`, `retry_effect_id`, `effect_count`, `original_effect_still_exists`, `action_status_before`, `action_status_after`, `historical_justification_status`, `denial_code`, and `why` (serialized Trace). Add `node_ids` mapping semantic fixture names to their hashes for inspection.

- [x] Write `test_demo_proves_effect_boundary`: assert one historical Effect; successful retry reuses its ID; two Observations support the root-cause Claim; both named verifications and authority appear in the why-trace; invalidating the code-change Observation leaves the other Observation VALID, makes derived nodes STALE, preserves the receipt, and denies a new dependent action. Add a CLI subprocess test checking exit code 0 and valid JSON; an invalid CLI command exits nonzero without database writes.
  Pin these report assertions:
  ```python
  report = run_demo(store)
  self.assertEqual(report["effect_count"], 1)
  self.assertEqual(report["effect_id"], report["retry_effect_id"])
  self.assertTrue(report["original_effect_still_exists"])
  self.assertEqual(report["action_status_before"], "VALID")
  self.assertEqual(report["action_status_after"], "STALE")
  self.assertEqual(report["historical_justification_status"], "STALE")
  self.assertEqual(report["denial_code"], "STALE")
  ```
- [x] Run `& $provenancePython -m unittest tests.test_demo -v`; confirm failures.
- [x] Implement the fixture using fixed UTC instants, registered fixture principals, handwritten Claim/ProposedAction nodes, and manual passing verifier results. Label the results as fixture inputs rather than suggesting actual repo tests ran. The runtime has no model or GitHub dependency. Handle a nonempty demo DB by declining rerun with a clear message and no writes, so the demo cannot silently reuse an unrelated history.
- [x] Document the exact commands, trust boundary, format rules, status/query APIs, and acceptance milestone. Explain that export preserves inspectable history but does not restore execution privileges; explain that simulated local retry guarantees do not promise exactly-once external effects. Include one runnable library example using the registered handles.
- [x] Run the full command `& $provenancePython -m unittest discover -s tests -v`; require zero failures/errors/skips. Run the CLI once against a fresh DB under the chat's `work/` directory, inspect its JSON, and compare the output to the Task 7 assertions. Scan Git changes for accidental DB files, cache files, private data, or network integrations.
- [x] Commit with message `feat: demonstrate verified provenance and stale-action denial`.

## Review and completion handoff

Before implementation, the human reviews this plan and selects an execution method. Recommended: **Native**, because these seven tasks share a small set of evolving interfaces and the first milestone performs only local simulated effects. The worker can preserve context while an independent whole-project review checks the final boundary.

After implementation, complete the review workflow for the selected method. Record fresh test results, demonstrate the fixture, and report any remaining limitations. Do not create a remote repository, open a PR, publish, or connect model providers as part of this milestone.
