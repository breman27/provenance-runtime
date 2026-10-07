# Provenance runtime: first prototype

Approved — October 7, 2026

## What we are proving

A runtime can track the information that justified an action, check its integrity, and prevent further actions when that justification becomes stale. Reasoning providers supply claims and proposals; the runtime owns observations, verification, authorization, and effects.

This carries forward the scope in **Branch · Revisit Jev idea**, especially the final implementation and test outline. The broader destination is a provider-neutral execution model for uncertain reasoning. This prototype establishes its provenance and action boundary.

Success: given an effect, return its complete recorded ancestry; detect altered or missing ancestors; invalidate an observation and identify affected descendants; deny a new effect with stale evidence, missing verification, or missing authority; preserve historical effects.

Hashes establish content integrity relative to a retained hash. They do not establish that a claim is true, authenticate a producer name, or prevent a database owner from replacing the whole history and its roots. V0 assumes a trusted local runtime and local storage. Cross-machine issuer authentication and independently anchored history are later work.

## Implementation choice

**Proposed default: Python and SQLite, with standard-library runtime dependencies.** Python keeps the prototype small and SQLite gives us a persistent transactional store. The IR is specified as data, so subsequent implementations can use other languages.

TypeScript would make sense if immediate integration with a JavaScript application is the priority; it adds packaging and a SQLite runtime choice. A format-only prototype would be smaller, but would leave persistence, invalidation, and the effect boundary untested. The Python runtime is the proposed compromise.

The workspace is currently empty and has no Git repository. This document is a design deliverable; no product scaffolding or dependencies have been created.

## Records and relationships

Every immutable record has `schema_version`, `kind`, `payload`, typed `parents`, `producer`, and `created_at`. Its ID is `sha256:<digest>` of the canonical body; the ID itself is excluded from that body. Parent IDs are already content hashes.

| Record | Required relationships and meaning |
| --- | --- |
| Observation | No parents in V0; captures a tool result or explicit human input through the runtime. |
| Claim | One or more `evidence` parents, each an Observation or Claim. |
| ProposedAction | One or more `justification` parents, each a Claim or Verification; payload fixes the action type, resource, and complete arguments. |
| Verification | Exactly one `subject` parent, a Claim or ProposedAction; optional Observation parents contain verifier output. Payload includes verifier ID, check name, and pass/fail result. |
| Effect | Exactly one action, one authority receipt, and the policy-required passing verification records for that exact action. Only the runtime's commit operation creates it. |

Three supporting record kinds complete the original outline: Authority, Invalidation, and Supersession. Authority binds a trusted issuer, subject, action hash, action type, resource, and expiration. Invalidation references its target and reason. Supersession references the old record and its replacement of the same kind. Revoking authority uses Invalidation.

Relationship roles distinguish causal dependencies from control references. An Invalidation's target is included in its hash ancestry, but target invalidity does not make the invalidation itself stale. Supersession cannot name a replacement whose causal ancestry depends on the old record.

Ordinary insertion accepts only Observation, Claim, ProposedAction, and Verification through the appropriate API. Authority, control records, and Effect use dedicated runtime methods. The model-facing interface accepts only Claim and ProposedAction. Supplying a `producer` string cannot confer trusted issuer status.

## Canonical format and storage

V0 defines a deliberately restricted JSON format rather than claiming conformance to a general canonical JSON standard:

- UTF-8, no BOM; compact JSON; object keys sorted by Unicode scalar value; no Unicode normalization.
- Values are null, booleans, valid Unicode strings, arrays, objects with string keys, and integers from `-(2^53 - 1)` through `2^53 - 1`. Reject floats, duplicate input keys, and unpaired surrogates.
- Parent references are sorted by role and ID; duplicate references are rejected. Array order inside payloads remains meaningful.
- Timestamp format is UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Normalize an input instant before hashing; retain the resulting timestamp in export and replay.
- SHA-256 input is the ASCII prefix `provenance-runtime:node:0.1` followed by one LF byte (`0x0A`), then canonical body bytes. Identical complete bodies produce identical IDs; different creation times are different records.
- Unknown schema versions fail closed. Freeze the 0.1 encoding with golden test vectors. A future version adds its own decoder and encoder without rewriting existing records.

SQLite stores canonical node bodies, an indexed parent/child relationship table, a local trusted-admission registry, and a unique action-to-effect mapping for locally committed effects. The admission registry records which dedicated runtime API admitted a trusted record; it is local execution metadata and is not inferred from exported producer strings. Imported historical Effects are queryable but do not populate the local commit mapping. Nodes and relationships are append-only; application APIs expose no update or delete. Status is a derived view. Relationship indexes are checked against the canonical bodies during validation and can be rebuilt from those bodies.

Insertion validates the entire new record and its reachable parents in one transaction. Graph traversal uses an iterative algorithm with visited and active sets, so shared ancestry is processed once and deep graphs do not rely on Python's recursion limit. Imports are staged, checked for missing parents and cycles, validated, then committed atomically.

## Integrity and current status

`validate(id)` checks hashes, schemas, typed relationships, parent availability, and cycle freedom throughout the reachable ancestry. It reports structured errors, including the offending ancestor. This is separate from whether the evidence is currently usable.

`status(id)` derives one of VALID, INVALID, SUPERSEDED, or STALE. Direct invalidation takes precedence over supersession; otherwise an unusable causal dependency makes the record stale. Status propagates along causal relationships, including an Effect's verification and authority dependencies. Historical effects remain stored even when their current justification is stale.

`why(effect)` returns the immutable justification ancestry and a separate current-status report, including later control records. `impacted_by(id)` returns transitive causal dependents. `evidence_for(claim)` returns its supporting Claim and Observation ancestry. Results are deterministic structured data, with no generated explanation required.

For V0, derive status on demand instead of maintaining a second source of truth in a cache.

## Effect boundary

V0 has one effect: **record a simulated repo-repair receipt in SQLite**. It exercises the same graph shape as creating a PR, while keeping the first prototype's transaction boundary within one database. No actual repository writes or network calls occur.

Trusted runtime configuration names permitted authority issuers and verifiers and defines required checks for each action type. The repair fixture requires both `targeted_tests` and `full_suite`. This configuration is outside model-controlled payloads. Issuer and verifier identities come from registered runtime handles, rather than caller-supplied labels. Include the complete serializable policy snapshot, its version, and its content hash in the Effect payload for audit.

Within an explicit SQLite write transaction, `commit(action_id, verification_ids, authority_id)`:

1. Returns an existing local receipt if this exact action was already committed. Validate that receipt's integrity; report any integrity errors and its current justification status, and create no new effect.
2. Validates ancestry and current status; rejects corrupted or stale dependencies.
3. Requires every configured check to pass, from an approved verifier, with a subject equal to the exact proposed-action hash. A changed patch produces a new hash and requires new verification.
4. Requires authority from an approved issuer for the configured runtime subject, exact action hash, action type, and resource; rejects denied, revoked, or expired authority using the injected runtime clock.
5. Writes the Effect and its unique action mapping atomically. Authority consumption is represented by the committed Effect.

Competing commits serialize and the unique action mapping provides a final duplicate guard. A crash before commit leaves no effect; a crash after commit leaves one retrievable receipt. SQLite's atomic transaction model supports this local boundary ([SQLite documentation](https://www.sqlite.org/atomiccommit.html)).

Imported records can be inspected and their declared statuses replayed, but importing a producer name never grants execution privileges. Imported Authority, Verification, Observation, and control records remain historical data; the executable gate requires trusted records admitted through the local runtime's dedicated APIs. The inspection status view includes imported control records, while the execution status view accepts control records only from local trusted admissions. Imported control records cannot invalidate or authorize locally executable history. Imported Effects are historical receipts, never instructions to execute.

Real external effects are a later milestone. They require a durable intent/outbox, adapter idempotency, and recovery or reconciliation. A database transaction alone cannot guarantee exactly-once creation of a PR across a network failure.

## Acceptance tests

| Area | Required evidence |
| --- | --- |
| Canonicalization | Key ordering and input formatting do not change IDs; parent order does not matter; payload array order and creation time do; unsupported values and duplicate keys fail. |
| Integrity | Alter any ancestor byte and descendant validation fails; missing parents, cycles, and illegal roles/types are rejected. Index corruption is detected. |
| Graph shape | Branches share evidence; joins require every parent; an unrelated branch remains valid after invalidation; a deep chain validates without recursion failure. |
| Current status | Invalidation makes the target INVALID and causal descendants STALE. Supersession preserves old bodies. Control records do not invalidate themselves through their target relationship. |
| Historical effects | Invalidating evidence preserves the receipt, changes its justification status, and denies a fresh dependent action. |
| Gate denial | Missing, failed, untrusted, incomplete, or wrong-action verification fails; missing, denied, untrusted, wrong-subject, wrong-resource, expired, or revoked authority fails. |
| Retry and recovery | Repeated and competing commits yield one receipt; a crash before commit yields none; restart after commit retrieves the original receipt even if its authority later expires. |
| Queries | `why`, `impacted_by`, and `evidence_for` return exact deterministic sets, including shared ancestry without duplicates. |
| Portability | Export and import into a fresh DB preserve bodies, hashes, relationships, declared statuses, and historical receipts. Failed import leaves no partial records. Execution trust is not inferred from an imported name. |
| Versioning | Golden 0.1 vectors stay unchanged; unknown versions fail. A later 0.2 reader must retain the original 0.1 validation path. |

The end-to-end fixture is: failing-test Observation plus code-change Observation -> root-cause Claim -> proposed repair -> two passing Verifications plus Authority -> simulated Effect. Then invalidate the code-change Observation and demonstrate that history persists while another dependent action is denied.

## Build order and deferred work

1. Restricted canonical encoding, golden vectors, immutable records, and legal relationships.
2. SQLite persistence, ancestry validation, and atomic import/export.
3. Control records, current-status derivation, and provenance queries.
4. Trusted local effect gate, transaction/retry tests, and the repo-repair fixture.

Keep the units small: format/model, store/validation, status/queries, gate, and demo. The next step after design approval is a written implementation plan with test-first tasks.

Model adapters, external PR creation, a new language, scheduling, vector memory, multi-agent execution, confidence scoring, distributed consensus, and an optimizer remain deferred. The first provider integration can submit Claim and ProposedAction records without changing the provenance model or gate.

Implementation references: [Python JSON](https://docs.python.org/3/library/json.html), [Python SQLite](https://docs.python.org/3/library/sqlite3.html). These are library references; the protocol rules above are our proposed design.
