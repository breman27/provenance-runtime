# The demo, explained

## What this example tests

The general runtime takes records describing evidence, interpretations, requested actions, check results, and permission. This fixture uses a fictional software repair because those concepts are easy to name in that setting.

It proves that the graph and gate can admit one justified effect, reuse its receipt on retry, preserve that effect after its evidence is invalidated, and deny a fresh action based on the same stale claim.

All input observations, claims, patch descriptions, and passing verification results are handwritten. `fixture:reasoner` is a producer label for those example records, not a connected reasoning model. The patch argument is a description string. The effect is a simulated SQLite receipt. A repo-maintainer agent and real repository/test integrations are later clients of the runtime.

The project's automated regression tests exercise the library itself. They are separate from the fixture's named `targeted_tests` and `full_suite` Verification records.

Use the [plain-English report](../examples/demo-report.md) first. Its [raw JSON](../examples/demo-report.json) contains the same report data.

## Read the story in this order

1. **Observe a failure and a code change.** `failure` says “auth_refresh_test failed”; `code_change` says “code changed in abc123.” Here, abc123 is a fictional revision mentioned in the input text. The long `sha256:` IDs identify provenance records.
2. **State a cause.** `root_cause` claims “abc123 introduced the regression,” referencing both observations with `evidence` roles.
3. **Request a repair.** `action` requests `repo.repair.simulated` on `fixture:repo`, with patch description “replace expired auth state.” Its `justification` is the root-cause Claim.
4. **Supply checks and permission.** `targeted_tests` and `full_suite` each report a pass for that exact action. `authority` permits that action for `fixture:runtime` on `fixture:repo` until the fixture expiry.
5. **Finalize the action.** `runtime.commit(...)` runs the gate and records `effect`. Calling it again returns the same effect ID. This is the runtime's action-finalization operation, not a Git commit.
6. **Invalidate an input.** `invalidation` targets `code_change`, declaring its collector faulty. The original observation remains stored; its current status becomes INVALID. Its dependent claim, proposal, verification, authority, and effect justification become STALE.
7. **Try a fresh action.** `denied_action` proposes another repair using the same claim. The fixture supplies new passing checks and permission, but the gate returns `STALE`. Only the original effect exists.

The JSON is a final snapshot, so its statuses are from **after step 6**. A stale historical justification does not mean the first effect bypassed the gate: the controls were appended after that effect was admitted.

The fixture uses a fixed UTC clock for reproducible IDs, so every record has the same creation timestamp. JSON object keys are sorted for deterministic serialization. Nodes are ordered with parents before dependents and hash ordering to break sibling ties. Use the numbered story and dependency links to understand the flow; alphabetical field order and sibling order are not an execution timeline.

## The top-level report fields

| Field | Value / meaning in this run |
| --- | --- |
| `mode` | `"simulation"`: the effect is a local example receipt. |
| `fixture_note` | States that verification results were handwritten inputs and no repository tests were run. |
| `effect_count` | `1`: one Effect remains in the database. |
| `effect_id` | The original admitted effect's content ID. |
| `retry_effect_id` | The same ID returned when the exact action was retried. |
| `original_effect_still_exists` | `true`: invalidation preserved the historical receipt. |
| `action_status_before` | `"VALID"`: the original proposal had usable justification before invalidation. |
| `action_status_after` | `"STALE"`: that proposal now depends on invalidated evidence. |
| `historical_justification_status` | `"STALE"`: the existing effect's justification is currently stale. |
| `denial_code` | `"STALE"`: the fresh dependent action was refused. |
| `node_ids` | Human-readable aliases mapped to their full content IDs. |
| `why` | The explanation graph for the original successful effect, plus current status and applicable later controls. |

`node_ids` is a convenience index in this report, not part of a node's canonical hashed body. For example, find the hash assigned to `root_cause`, then find the node with that `id` inside `why.nodes`.

## The `why` object

| Field | Meaning |
| --- | --- |
| `why.effect_id` | The effect being explained; matches the top-level `effect_id`. |
| `why.nodes` | Eight immutable records: two Observations, one Claim, one ProposedAction, two Verifications, one Authority, and the Effect itself. |
| `why.statuses` | A map from each of those IDs to its current derived status. Status values are a view of history and are not fields written into the immutable record body. |
| `why.controls` | The later Invalidation affecting this explanation. It is separate from the original effect's immutable ancestry. |

This report is centered on the first effect. The later denied proposal and its new prerequisites live in the database, but they did not justify the first effect and therefore do not belong in `why.nodes`. `node_ids.denied_action` still gives you the proposal's ID. `export_graph(store)` produces a separate export containing every historical record.

## Decode one actual record

Here is the failure Observation from the report, with its complete ID:

```json
{
  "id": "sha256:391060d047bdf1df77e94faadd6cec93531e37f9448679772016ca186ed79241",
  "body": {
    "created_at": "2026-10-07T00:00:00.000000Z",
    "kind": "Observation",
    "parents": [],
    "payload": {
      "fixture": true,
      "message": "auth_refresh_test failed"
    },
    "producer": "fixture:runner",
    "schema_version": "0.1"
  }
}
```

Read it as: “The fixture runner recorded an observation containing this failure message, with no dependency parents, using schema 0.1 at the fixture's UTC instant. The full body determines this record's hash ID.”

For the Claim, `parents` contains two references. Their role `evidence` tells you these are supporting inputs. Each reference's `id` resolves to the relevant Observation. The ProposedAction uses role `justification`; the Verification uses role `subject` to name the exact proposal checked.

See [Record fields and relationship roles](concepts.md#record-fields) for the complete dictionary. `producer` names a source; trust comes from local runtime admission rather than from the string.

## Read the Effect's payload

The Effect has three payload fields:

- `receipt`: `kind` identifies the simulated consequence and `action_id` binds it to the proposal.
- `policy`: a snapshot of the trusted runtime configuration used for the effect.
- `policy_hash`: the hash of that policy snapshot.

Its policy fields mean:

| Field | Meaning |
| --- | --- |
| `version` | Application policy revision, `demo-v1`; distinct from the node schema version `0.1`. |
| `subject` | The runtime identity receiving permission, `fixture:runtime`. |
| `observers` | Principal IDs eligible to issue trusted observations. |
| `verifiers` | Checker IDs mapped to the check names each may issue. |
| `issuers` | Principal IDs eligible to issue authority. |
| `controllers` | Principal IDs eligible to append invalidation/supersession controls. |
| `requirements` | Action types mapped to required check names; this action needs both `targeted_tests` and `full_suite`. |

The snapshot records the conditions used for that historical effect. A policy object embedded in imported JSON does not configure a local runtime or grant permission.

## Inspect records with the library

These operations work on a Store containing the demonstration:

```python
from provenance import evidence_for, impacted_by, status, why

evidence = evidence_for(store, report["node_ids"]["root_cause"])
affected_ids = impacted_by(store, report["node_ids"]["code_change"])
current_status = status(store, report["node_ids"]["action"], "execution")
explanation = why(store, report["effect_id"], "execution")
```

`evidence_for` returns supporting records. `impacted_by` returns all causal dependent IDs, including the later proposal and its prerequisites. `why` is centered on one effect. Integrity failures raise structured errors rather than returning an apparently clean explanation.

Run commands and a complete setup example are in [the README](../README.md). [Concepts and terminology](concepts.md) explains the distinction among integrity validation, current status, verification, and authority.
