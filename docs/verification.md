# Prototype verification

Completed October 7, 2026. All seven approved implementation tasks are complete.

Code revision: `02a3b164736b4e57f4a2bc34c8e337a8437293f6` (the following documentation commit does not change executable code).

## Evidence

- Python 3.12.14, SQLite 3.53.1.
- Full suite: `python -m unittest discover -s tests -v` — **78 tests passed, zero failures/errors/skips**. Final run: 8.424 seconds.
- Canonical JSON and record hashes checked against fixed vectors independently generated with Node.js SHA-256; a fresh Python interpreter reproduces the record ID.
- Persistence after reopen, branching/joins, 1,500-node deep ancestry, malformed parents, cycles, ancestor tampering, and index corruption tested.
- Invalidation, supersession, deterministic provenance queries, and preservation of historical receipts tested.
- Trusted handles, exact action verification, missing/failed verification, authority scope/expiry/revocation, untrusted imports, and stale-action denial tested.
- Concurrent commits through separate SQLite connections produce exactly one receipt. Actual child-process termination before the action mapping rolls back both writes; termination after commit preserves one complete receipt after restart.
- Export/import preserves canonical bodies, IDs, relationships, inspection status, and historical receipts. Failed import is atomic; import recreates neither trusted admission nor the local execution mapping.
- CLI demo against a fresh persisted database and the README's library example both passed after the review fixes. Reopened demo records all validate. Demo output has one historical Effect, eight justification ancestors including the Effect, one later control, and a new action denied with `STALE`.
- Source-only working tree is clean. No databases, bytecode caches, task scratch files, or external provider/network integrations are tracked.

## Independent review and fixes

A fresh-context reviewer using `gpt-6-astra` reviewed the complete implementation, approved spec, plan, and task ledger. It independently ran the original 76-test suite. No Critical or Minor issues were reported; two Important audit-query issues were reproduced.

1. `impacted_by` could miss corrupted records if a removed parent link hid them from discovery. `test_impacted_by_rejects_removed_reference` failed before the fix and passes afterward.
2. Inspection status could miss an imported control if corruption changed its kind. `test_inspection_detects_disguised_imported_control` failed for both `status` and `why` before the fix and passes afterward.

Both now validate record integrity before fields participate in discovery. The complete 78-test suite and delivery checks pass. Fixes were validated with regression tests and the full suite; the reviewer was not dispatched for a second review.

## Rulings I made

These resolve the reviewer's explicitly deferred judgments, in their original order:

1. External effects, providers and network exactly-once remain deferred. The approved milestone has a simulated local effect. Cost if wrong: live use requires another adapter/recovery milestone.
2. Hostile in-process code and full replacement of the database, admission metadata, and retained roots remain outside V0. The approved threat boundary trusts the local host and storage. Cost if wrong: this prototype offers no protection from those actors.
3. Hashes establish integrity, not factual truth or producer authentication. The approved IR separates claims from trusted admission. Cost if wrong: truth and identity need separate verification mechanisms.
4. VALID status remains separate from execution trust. Inspection can replay imported history while commit requires local admission. Cost if wrong: consumers must use the gate rather than treating status alone as authorization.

No deferred Minor findings. The prototype was developed and verified locally on `codex/provenance-runtime` before its initial public publication.
