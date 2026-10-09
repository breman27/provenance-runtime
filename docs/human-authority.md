# Human authority workflow

A passing candidate can now wait durably for a separate operator decision. The agent investigates and proposes; trusted tests check the exact candidate; a local operator grants permission; the existing gate admits one simulated receipt. Approval alone creates no Effect and applies no patch.

## Try it without a model or API key

Use Python 3.12+, Git and a running Linux Docker engine. This replay runs actual restricted candidate tests. Choose a fresh private directory:

```sh
python -m provenance observe-service --agent recorded --responses examples/recorded-service-regression.json --case-dir ./work/manual-example
python -m provenance authority list --session-dir ./work/manual-example
```

The investigation returns `AWAITING_APPROVAL`. Copy its full `sha256:…` Action ID into the commands below, replacing `ACTION_ID`:

```sh
python -m provenance authority inspect --session-dir ./work/manual-example --action ACTION_ID
python -m provenance authority approve --session-dir ./work/manual-example --action ACTION_ID --reason "Reviewed the diff and both checks"
python -m provenance authority admit --session-dir ./work/manual-example --action ACTION_ID
```

Inspection shows the exact diff, source revision, selected Observations, Claim, required Verifications and permission history. Approval creates a scoped Authority with a 15-minute lifetime. Admission probes the source again and asks the gate to admit a receipt. An exact retry returns the same receipt. All operator commands run without inference or an API key, including after the investigating process exits.

New `observe-service`, `watch-service` and convenience-script runs default to `--approval manual`. Explicit `--approval auto` retains the preapproved simulated benchmark. Existing calls to `run_experiment(...)` and `ServiceWatcher(...)` default to `approval_mode='auto'` for compatibility; pass `'manual'` explicitly to use this workflow. Original `investigate` and `demo` fixtures retain their existing automatic authority behavior. Existing private sessions are not converted.

## Other decisions

```sh
python -m provenance authority deny --session-dir ./work/manual-example --action ACTION_ID --reason "Need a different investigation"
python -m provenance authority approve --session-dir ./work/manual-example --action ACTION_ID --ttl-minutes 5 --renew
python -m provenance authority revoke --session-dir ./work/manual-example --authority AUTHORITY_ID --reason "Withdraw permission"
python -m provenance authority list --session-dir ./work/manual-example --all --json
```

Use full content IDs, not report labels such as `P1` or `A1`. TTL must be an integer from 1 to 60 minutes, default 15. Permission expires at equality with its expiry timestamp. Reasons are optional Unicode text of at most 4,000 characters; empty text and null mean no reason.

An unchanged repeated approval reuses its active grant. Changing the reason or lifetime of an active grant requires `--renew`; input is never silently discarded. Expired, denied or revoked permission requires a new explicit approval. Admission never issues or renews a grant. A denial remains the current decision after its expiry timestamp. A later explicit approval can replace it if the proposal is still eligible.

Denial after a receipt returns `ALREADY_COMMITTED` without appending a denial. Revoke the receipt's grant to record withdrawal. Revocation preserves the historical Effect and changes its current justification status. Source changes require a fresh investigation; renewing permission does not repair stale evidence.

| Application state | Meaning |
| --- | --- |
| AWAITING_APPROVAL | Verified proposal with no current permission decision. |
| APPROVED | Active permission; admission is still separate. |
| DENIED | Latest trusted decision denies permission. |
| EXPIRED | Current allowed grant reached its expiry. |
| REVOKED | Current allowed grant was invalidated or superseded. |
| STALE | Proposal or supporting justification is unusable. |
| VERIFICATION_FAILED | Required recorded verification is unusable. |
| COMMITTED | A historical local receipt exists; current integrity/status are separate. |

Default listing includes waiting, approved, expired and revoked proposals. `--all` includes denied, stale, failed-check and completed history. Runtime `VALID` describes justification, independently of permission or check results. Inspection/listing show recorded status; approval and new admission perform physical freshness probes.

Every subcommand supports `--json`. Exit codes are 0 for successful inspection/decisions/admission, 2 for invalid usage, 3 for refused admission, and 1 for operational/integrity failure. Mutating commands save `authority-report.json` and `.md` beside the proposal's investigation report. A report-write error includes the persisted result; it does not undo a decision. Source refusal refreshes the recorded state where intact context permits it.

## Continuous investigations

```sh
python scripts/watch_observed_service.py --repo /absolute/path/to/service --approval manual
```

The watcher keeps collecting while proposals wait. `APPROVAL_PENDING` events include the full Action ID and the session directory. Use that stable session directory for every operator command; individual investigations have distinct action/resource identities in the shared database. Stopping the watcher preserves its approval queue. Approval of an old source version is refused even if the watcher has not polled again.

The owned benchmark checks source/tests/README/service bytes and Git HEAD. The watcher checks the actual external source bytes and upstream HEAD rather than relying on its last poll or mirror HEAD. A measured change records a new Observation and invalidates the scoped source view; historical logs remain facts. Missing or unreadable source is `SOURCE_UNAVAILABLE`, without pretending it was measured to change. These probes do not freeze the repository. A future real executor needs an atomic version check with its resource mutation.

## Persistence and recovery

Private sessions contain `approval-session.json`, `approvals/<action hex>.json`, immutable baseline/candidate snapshots, exact proof JSON and `history.db`. Collector-admitted Observations bind the descriptor/context hashes to the graph. Grants bind the exact Action, subject, resource, checks and context. Missing, altered, imported or conflicting bindings refuse permission/new admission; a missing DB is never initialized by an operator command.

The fixed manual profile uses policy version `observed-service-manual-v1`, subject `observed-service`, observer `collector`, verifier `tester`, issuer `human-operator` and controller `controller`. Required checks remain `targeted_tests` and `full_suite` for `repo.repair.simulated`. Model output and CLI arguments cannot choose an issuer, arbitrary policy, resource path or historical grant.

Decisions carry method `local-cli`, fixed actor label, context hash, reason, lifetime and a positive per-action sequence. The sequence determines order even after clock rollback. A bounded OS-backed session lock serializes operators, releases on process death and is independent of collection. Each operation opens its own SQLite connection. Interrupted renewal/denial controls reconcile before mutation/admission; recovery alone creates no Effect and cannot resurrect an older grant.

Withdrawal and existing-receipt inspection use intact recorded ownership even when source or context files are unavailable. New grants/admission require their matching files and proofs. Receipt retries skip external execution; corrupt ancestry, an inconsistent mapping, or a lost mapping for a locally admitted Effect is an integrity failure, never absence. Imported Effects have no local effect admission and do not establish local execution.

Historical inspection, withdrawal and receipt retries also survive changes to the installed verifier runner. New grants/admission require its compatibility with the recorded proof. Imported Authority metadata remains untrusted graph history and is excluded from operator decision history. JSON inspection is independent of Markdown rendering; a failed readable-report write still returns the persisted permission/receipt result.

Session paths bind to the host on which they were created. Relocation/rebinding is outside this version. Clone the code on another computer and create a fresh session there; use core graph inspection for historical records transferred separately.

## What prevents an agent approving itself

The bounded API model receives only logs/source/diff/tests/finish tools. It receives no issuer/control handles, approval commands or database access. Privileged text or operator labels in its output remain data. Trusted host code decides which Observations and Verifications to admit.

`human-operator` is an audit role, not proof that a physical human called the command. An unrestricted shell agent sharing the operator's OS identity could invoke the CLI or modify SQLite. Such deployments need separate OS/service identities, protected issuer/database access and an authenticated operator channel. Future real effect credentials belong to a trusted executor requiring gate admission. This local library does not provide an OS sandbox, remote authentication, signatures or general IAM.

## Another application

`ApprovalManager` is independent of model providers and report layout. This first client has compiled service profiles and a service-specific freshness adapter. To support another resource, supply a trusted host profile and capture adapter that binds exact Action/proof/artifact ownership, then a direct freshness probe analogous to `check_current`. Extend the allowlisted client routing and its tests; do not accept executable probes or policies from model output or session JSON. Real resource mutation needs an executor/recovery design beyond the current simulated receipt.

See [verification](human-authority-verification.md), the approved [design](superpowers/specs/2026-10-09-human-authority-workflow-design.md) and [plan](superpowers/plans/2026-10-09-human-authority-workflow-plan.md).
