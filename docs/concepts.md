# Concepts and terminology

## The general model

The runtime records how information supports an action and checks the boundary where that proposal becomes an effect. The model can describe contributions from a person, a reasoning model, a test tool, or another program. Their outputs have explicit types and dependency links.

The included repo-repair fixture is one example. The first milestone establishes immutable records, ancestry validation, current justification status, and a local effect gate. A repo-maintainer agent that diagnoses bugs and proposes real patches is a future client of this runtime.

Think of the normal flow as:

```text
Capture observations
        ↓
State a claim supported by those observations
        ↓
Propose a concrete action justified by that claim
        ↓
Collect the required verification and matching permission
        ↓
Finalize the action through the runtime's gate
        ↓
Retain an effect receipt with its justification
```

Verification and authority can be collected separately. The diagram is a reading order; the graph permits branching and shared inputs.

## Glossary

| Term | Meaning | Repo-repair example |
| --- | --- | --- |
| Node / record | One immutable object in the graph. | A test-failure observation. |
| Observation | Captured input, admitted through a trusted observer API. | A tool reports a failing test. The fixture supplies this report manually. |
| Claim | An interpretation with explicit supporting evidence. | “Revision abc123 caused the failure.” |
| ProposedAction | The exact action being requested, its resource, and its arguments. | Request the simulated repair described by a patch string. |
| Verification | A named check's pass/fail result for a particular Claim or ProposedAction. | `targeted_tests` reports a pass for the exact proposed action. |
| Authority | A permission receipt bound to an action, runtime subject, type, resource, and expiration. It can allow or deny. | The registered issuer permits this action on `fixture:repo`. |
| Effect | A runtime-admitted consequence, recorded with its supporting action, verification, authority, and policy. | A simulated receipt stored in SQLite. |
| Invalidation | An appended declaration that a target record is unusable. | Discover that the code-change observation came from a faulty collector. |
| Supersession | An appended record naming an old record and its replacement of the same kind. | Replace an earlier observation with a corrected observation. |
| Parent | A record this node references; the role says why it is referenced. | A Claim points to the observations used as evidence. |
| Ancestry | The records reached by walking backward through parents. | An Effect reaches its action, checks, authority, claim, and observations. |
| Provenance | The recorded origins and dependency relationships behind a result. | The structured answer to “why was this effect admitted?” |
| Policy | Trusted runtime configuration defining eligible principals and required checks. | Both `targeted_tests` and `full_suite` must pass. |
| Admission | Local metadata recording which trusted runtime API and principal admitted a node. | A Verification has a local `verify` admission. |
| Handle | A runtime-issued object that trusted host code uses to call a particular admission API. | A registered verifier handle issues results for its allowed check names. |
| Projection | A current view derived from immutable history. | The status of a Claim after one of its observations is invalidated. |
| Idempotent retry | Retrying the exact committed action retrieves its original receipt. | Calling `commit` twice creates one local effect. |

Observation records identify captured inputs; their factual reliability is a separate concern. Claims remain interpretations. Hashes establish content integrity relative to retained IDs. Trusted admission records who the local application permitted to issue a record.

## What `commit` means

```python
receipt = runtime.commit(action_id, verification_ids, authority_id)
```

Read this as: **“Finalize this proposed action if the runtime's requirements are satisfied.”** It is not the Git command `git commit`. The name reflects committing the local effect and its receipt within a database transaction.

For a new action, the gate checks ancestry integrity, current justification, trusted required passing verification for the exact action, and matching trusted permission. Then it writes an Effect and an action-to-receipt mapping atomically.

For an action already committed locally, it returns the existing receipt with current integrity and justification information. The retry does not cause another effect. Authority expiring afterward does not erase the historical receipt.

`CommitResult` contains:

| Field | Meaning |
| --- | --- |
| `effect_id` | Content ID of the effect receipt. |
| `reused` | `True` when the action already had a local receipt. |
| `integrity` | A ValidationReport for the receipt and reachable ancestry. |
| `justification_status` | Current derived status. This is `None` when integrity errors prevent a reliable status report. |

The current handler admits only `repo.repair.simulated` and writes a local receipt. A future effect such as creating a real PR needs a handler with durable intent, adapter idempotency, and recovery. Those integrations are outside this prototype.

## Three meanings that must stay separate

| Mechanism | Question answered | Successful result means |
| --- | --- | --- |
| `store.validate(id)` | Do retained hashes, schemas, parent availability, and relationships match this history? | The reachable stored graph passes integrity and structural checks. |
| `status(store, id, mode)` | Is the recorded justification currently usable under this projection? | `VALID`: no applicable invalidation/supersession or unusable causal dependency makes it stale. |
| `Verification.payload.passed` | What result did the registered checker report for its named check and subject? | That particular check reported a pass. The gate also checks its trust, subject, freshness, and required check name. |
| Authority plus local policy/admission | May the runtime admit this particular effect? | The grant matches its action, subject, resource, and type and remains allowed, current, and unrevoked. |

An intact Claim can have an incorrect interpretation. A Verification can report `passed: true` while its justification later becomes STALE. A currently usable proposal still needs verification and authority before an effect is admitted.

## Record fields

In the JSON report, a serialized record has two outer fields: `id` and `body`. The body contains exactly the six fields below.

| Field | Meaning |
| --- | --- |
| `id` | `sha256:` followed by the content hash of the canonical body. The ID is outside its own hash input. |
| `body.schema_version` | The record format/semantics version. Currently the string `"0.1"`. |
| `body.kind` | One of the eight record kinds in the glossary. |
| `body.payload` | Kind-specific data. It is an object, with required fields listed below. |
| `body.parents` | An array of `{ "role": ..., "id": ... }` references. Each `id` names an input record. |
| `body.producer` | A descriptive producer name, such as `fixture:tester`. This string alone grants no trust. |
| `body.created_at` | Creation instant normalized to UTC, including six fractional-second digits. |

The content ID includes payload, parents, producer, timestamp, kind, and schema version. Creating another record with the same patch but a different timestamp or justification produces a different action ID. Idempotent retry means reusing the exact existing action ID.

### Required payload fields

| Kind | Required payload fields |
| --- | --- |
| Observation | Any object in the supported JSON domain. The fixture uses `message` and `fixture`; these names are example fields. |
| Claim | `statement`: nonempty text describing the interpretation. |
| ProposedAction | `action_type`: operation name; `resource`: target identifier; `arguments`: object with the exact proposed inputs. |
| Verification | `verifier_id`: checker name; `check`: check name; `passed`: boolean result. |
| Authority | `issuer_id`: grant issuer; `subject`: permitted runtime identity; `action_id`: exact proposal ID; `action_type`; `resource`; `allowed`: boolean permission; `expires_at`: canonical UTC expiration. |
| Effect | `receipt`: consequence details; `policy`: complete serializable configuration snapshot; `policy_hash`: hash of that snapshot. |
| Invalidation | `reason`: nonempty text explaining the declaration. The target is a parent reference. |
| Supersession | `reason`: nonempty text explaining the replacement. Target and replacement are parent references. |

Additional payload fields may carry supported JSON data. Unknown outer body fields are rejected. A proposed action's `resource` is an application-defined identifier, not automatically a filesystem path or remote repository URL. The current simulated receipt contains `kind: "simulated-repo-repair"` and `action_id`.

### Parent relationship roles

| Child record | Parent role | Parent meaning |
| --- | --- | --- |
| Claim | `evidence` | An Observation or another Claim supporting it; at least one required. |
| ProposedAction | `justification` | A Claim or Verification supporting the request; at least one required. |
| Verification | `subject` | Exactly one Claim or ProposedAction being checked. |
| Verification | `evidence` | Optional Observation records containing supporting checker output. |
| Authority | `subject` | Exactly one ProposedAction being permitted or denied. |
| Effect | `action` | Exactly one ProposedAction admitted by the runtime. |
| Effect | `verification` | Required passing checks bound to that proposal. |
| Effect | `authority` | Exactly one matching Authority receipt. |
| Invalidation | `target` | The record declared unusable. |
| Supersession | `target` | The old record. |
| Supersession | `replacement` | The new record of the same kind. |

Observation has no parents in V0. Control targets are primary records, including Authority and Effect; controls do not target other controls. Supersession cannot use a replacement whose causal ancestry depends on its target.

The word **subject** appears in two places with different meanings: a parent role `subject` names the record being checked or permitted; `Authority.payload.subject` names the runtime identity receiving permission.

Control links commit to the referenced history, but they are not causal support. An Invalidation therefore does not become stale merely because it points to the record it invalidates.

## Status values

| Value | Meaning |
| --- | --- |
| `VALID` | No applicable control or unusable causal parent makes this record's justification stale. This does not by itself grant permission or prove a Claim true. |
| `INVALID` | An applicable Invalidation directly targets this record. |
| `SUPERSEDED` | An applicable Supersession identifies this record as the old representation. |
| `STALE` | At least one causal dependency is INVALID, SUPERSEDED, or STALE. The record itself remains unchanged. |

Direct INVALID takes precedence over SUPERSEDED, followed by inherited STALE. Historical Effects remain present regardless of current justification status. An authority's expiration is checked by the gate's clock; expiration alone does not append an Invalidation or alter the history's status.

Integrity errors, such as `HASH_MISMATCH`, are structured failures rather than another status value. The runtime cannot reliably derive a clean status from corrupted records.

## Inspection, execution, and imports

`inspection` is the default query mode. It interprets declared control records, including imported history, for auditing. `execution` applies locally admitted controls. The gate uses execution mode and also requires trusted local admissions.

The portable JSON contains producer labels and permission/check declarations. The local admission registry is deliberately separate. Import preserves historical bodies, hashes, links, inspection statuses, and receipts; it does not grant local observer/verifier/issuer privileges or restore the local action-to-receipt mapping.

Consequently, a record can display VALID in an imported history and still fail the gate with `UNTRUSTED`. Existing local admissions survive an idempotent re-import. Deliberately reissuing a record through an approved local API is a separate operation from import.

## Common gate failures

| Code | Meaning |
| --- | --- |
| `STALE` | A proposal, verification, or authority has unusable supporting justification. |
| `UNTRUSTED` | A required trusted record lacks an approved local admission. |
| `VERIFICATION_REQUIRED` | The gate lacks every required passing check. |
| `VERIFICATION_FAILED` | A supplied check reported failure. |
| `WRONG_ACTION` | The request or verification subject does not bind the requested proposal. |
| `AUTHORITY_REQUIRED` | No authority receipt was supplied, or the supplied record is not Authority. |
| `AUTHORITY_SCOPE` | Permission names a different action, subject, resource, or type. |
| `AUTHORITY_DENIED` | The grant explicitly denies the action. |
| `AUTHORITY_EXPIRED` | The gate's current time has reached or passed the expiry. |
| `AUTHORITY_REVOKED` | Authority was invalidated or superseded. |
| `POLICY_UNKNOWN` | There is no configured policy and supported local handler for the action type. |

See [the demo walkthrough](demo-walkthrough.md) for these concepts in one complete scenario, and [the README](../README.md#format-01) for canonical encoding rules.
