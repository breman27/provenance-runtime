# Reports use the runtime's record vocabulary

All generated agent investigation reports share one renderer. The repo-repair client, observed-service benchmark, and live watcher use the same sections and identity/relationship presentation:

1. **Evidence — Observations:** captured inputs and tool outputs, with a compact evidence table and expandable record details.
2. **Claims:** interpretations, with direct links to the Observation records selected as evidence.
3. **ProposedActions:** exact requested changes, linked to their justifying Claims.
4. **Verifications:** actual check records bound to a subject, including pass/fail separately from justification status.
5. **Authorities:** permission records, their issuer, scope/subject, expiration, and local admission.
6. **Effects:** admitted receipts and their action, verification, and authority parents.
7. **Invalidations / Supersessions:** included when applicable controls explain changed justification.
8. **Outcome:** the recorded investigation/gate result, separate from a Claim.

Empty sections explicitly say that no record of that kind is present. Error, healthy, unresolved, refused, and accepted reports use the same vocabulary. Tool/check activity appears separately; it is not relabeled as a provenance record.

Records receive readable report-local labels such as `Observation O1`, `Claim C1`, and `ProposedAction P1`. Their full content IDs remain visible in their details. Parent links use the actual stored roles: evidence, justification, subject, verification, authority, action, target, and replacement. A tool called `run_tests` is an operation. Its output can be an Observation, and a separately admitted Verification can cite that output. A raw result with `passed: true` never becomes a Verification merely because it passed.

## A reusable library API

```python
from provenance import snapshot_records, render_record_report

snapshot = snapshot_records(store, (effect_id,), aliases={"current_logs": observation_id})
text = render_record_report(
    snapshot,
    title="Provenance report",
    outcome="ACCEPTED",
    reason="The exact proposal passed the gate.",
)
```

The renderer has no dependency on a provider or on the clamp/sensor scenario. `snapshot_records` reads and validates the real graph in one SQLite read snapshot. It retains requested roots and ancestry, matching check/grant/effect descendants of proposals, and applicable later controls. It captures actual record kinds, immutable bodies, aliases, local admission metadata, and derived execution statuses.

Both agent clients retain that information in the JSON report's additive `record_snapshot` field. Legacy report envelopes without bodies show clearly labeled summaries and unavailable-record details; they cannot invent check or permission receipts.

## Time and history

`record_snapshot.captured_at` identifies when displayed statuses were derived. Outcome remains the run's recorded result. A historical HEALTHY result can coexist with a now-STALE Claim after a source replacement. Permission decisions and test pass/fail are shown separately from justification status. Regenerating a report refreshes the view without changing immutable records, model requests, or database receipts.

The saved local case reports were regenerated from read-only SQLite backups to display this vocabulary. The already-running Python watcher has its earlier formatter in memory; restart it to load the new report renderer for subsequent investigations:

```sh
cd /Users/brett/workspace/provenance-runtime
python3.12 scripts/watch_observed_service.py
```

Stop the earlier watcher with Ctrl+C first. Existing sessions remain available. A new helper run prints a new session directory and may prompt for the API key again.

## Verification

The full 169-test unit suite passed, including eight new checks for record classification, shared headings, graph parent links, failed Verification retention, stale controls, absent records, local admission, and safe payload formatting. The final evidence-table layout and CLI integrations passed their focused 17-test check. All ten saved local reports were regenerated and checked for the required sections and full record IDs. No model calls or container reruns were needed for this reporting change.
