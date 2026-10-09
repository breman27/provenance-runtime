# Human authority workflow

Draft for review — October 9, 2026. Based on `main` at `30d5380`.

## Purpose

Let a model investigate and propose work, let trusted tools verify the exact candidate, and let a human separately decide whether the proposed action is permitted. A successful test does not issue permission in manual mode.

Success means a verified proposal waits durably across process restarts; a local operator can inspect, approve, deny, renew or revoke its permission; and the gate admits one simulated receipt only when the proposal, required checks and current permission remain usable. Existing history stays immutable.

The selected starting approach is local human approval. Configurable automatic policy can follow this workflow later. A remote approval service would also require authentication and distributed coordination, which are outside this milestone.

## Scope and trust

The first integration covers the observed-service benchmark and continuous watcher. Its reusable approval helper is independent of the model provider and report layout. The original repo-repair benchmark remains a documented automatic fixture until wired into this helper separately.

Reading evidence and running bounded investigation tools retain their existing preapproved host policy. This milestone changes permission for the final simulated consequence, not permission for every read or model call.

The existing local trust boundary remains explicit: the host application and local processes with access to its runtime handles/database are trusted. This is not a Python sandbox or a multi-user identity system. The operator role is fixed by trusted application configuration; a name in model output or an arbitrary `--issuer` argument cannot confer permission. No remote approval endpoint is added.

The model keeps its existing bounded tools: logs, source, diff, tests and finish. It receives no issuer/control handles or approval tools. Its output cannot create Authority, Verification, Effect, Invalidation or Supersession records.

The effect remains `repo.repair.simulated`: a local SQLite receipt. Applying a patch, creating a Git commit/PR, deployment, standing grants, delegation, cryptographic signing, multiple approvers and general policy languages are deferred.

## User flow

1. The collector and model investigate as they do now. A proposed candidate runs the required independent suites.
2. If both checks pass and the proposal is current, manual mode returns `AWAITING_APPROVAL`. It records no Authority or Effect. Collection continues while proposals wait.
3. The operator lists pending proposals and inspects the exact diff, source version, selected evidence, named checks and current justification status.
4. Approval issues an Authority for the exact ProposedAction ID, existing policy subject, action type and resource. Its lifetime starts at issuance and defaults to 15 minutes.
5. Admission is a separate command. It selects the current permission, rechecks source and recorded proofs, and calls the existing gate. This separation makes expiry and revocation before use observable.
6. Denial records an Authority with `allowed: false` and blocks earlier grants. Revocation invalidates a selected grant. A later explicit approval can replace an earlier decision when the same proposal remains eligible.
7. Admission retries return the existing local receipt; they never reapply the consequence or mint another grant automatically.

Operator commands perform no inference. They reuse intact candidate checks while the captured source/test context is unchanged. If source changed, they refuse the old proposal and require a fresh investigation; they do not silently replace its patch or justification.

## CLI

The benchmark and watcher accept `--approval manual|auto`. Manual is the default for new observed-service runs and the convenience watcher. `auto` explicitly selects the existing preapproved simulated-fixture behavior. Healthy/inconclusive investigations do not enter the approval queue without an eligible changed proposal.

Existing programmatic entry points keep their automatic fixture default when the new optional mode is omitted; the CLI passes its selected mode explicitly. Existing sessions retain their original profile and are not silently converted to manual mode.

Add one command group:

| Command | Inputs | Result |
| --- | --- | --- |
| `authority list` | `--session-dir`, optional `--all`, `--json` | Current proposals; `--all` includes completed/denied/stale history. |
| `authority inspect` | `--session-dir`, `--action`, optional `--json` | Record-based review of one exact proposal and its permission/check history. |
| `authority approve` | `--session-dir`, `--action`, optional `--reason`, `--ttl-minutes`, `--renew` | New or reused scoped grant, with no Effect. |
| `authority deny` | `--session-dir`, `--action`, optional `--reason` | Explicit denial; prior usable grants stop being eligible. |
| `authority revoke` | `--session-dir`, `--authority`, optional `--reason` | Invalidation of that exact locally issued grant. |
| `authority admit` | `--session-dir`, `--action` | Existing receipt, newly admitted simulated receipt, or precise refusal. |

Action/Authority arguments are full content IDs copied from the report. Report-local labels remain presentation aids. The CLI offers no arbitrary commands, target paths, issuer IDs, or user-selected historical grant bypass.

TTL is an integer from 1 to 60 minutes, default 15, bounded by the local issuer configuration. A denial never automatically becomes approval when its expiry timestamp passes. An already completed action cannot be undone by denial; revoking its grant changes the recorded justification view while preserving its receipt.

`deny` on an already committed action returns `ALREADY_COMMITTED` without appending a denial. The operator can revoke its grant to record withdrawal of permission. Denial and revocation require intact in-scope records, but do not need the external repository to be online or its source to be current.

Default output is readable and UTF-8; `--json` is machine output. Mutations save refreshed reports. Invalid usage is exit 2, operational/integrity failures exit 1, refused admission exit 3, and successful inspection/permission decisions/admission exit 0.

## Records and state

Use existing kinds and parent roles. Pending state is an application projection over the graph and host context; it is not a new primitive. `VALID` still describes justification and is distinct from permission/check results.

| Application state | Meaning |
| --- | --- |
| `AWAITING_APPROVAL` | Eligible, current proposal with passing required checks and no active decision. |
| `APPROVED` | Current allowed Authority is usable and not expired; no receipt yet. |
| `DENIED` | The latest trusted decision denies permission. |
| `EXPIRED` | The current allowed grant has reached its expiry. |
| `REVOKED` | The current allowed grant has been invalidated. |
| `STALE` | Proposal or supporting justification is unusable. |
| `VERIFICATION_FAILED` | Required checks are absent, failed, mismatched or unusable. |
| `COMMITTED` | A local effect receipt exists; current integrity/justification are reported separately. |

Receipt existence takes precedence in the display and never implies that later evidence or permission is still current. Before a new admission, stale justification and unusable checks block progress regardless of an approval label.

Add a backwards-compatible, keyword-only `decision` metadata parameter to `Runtime.authorize`. When omitted, existing record bodies and callers are unchanged. When present, metadata lives under one optional payload field and cannot replace the host-generated issuer, subject, action, type, resource, allowed flag or expiry. The canonical format and required schema/roles remain version 0.1.

Manual decision metadata records the method, configured operator role, optional reason (at most 4,000 characters), approval-context hash, and a positive decision sequence. The sequence is allocated by the trusted approval helper under a session lock, so ordering does not depend on wall-clock rollback or hash order. Only locally admitted decisions from the configured issuer count. Imported/forged decisions never determine current permission.

The operator metadata is an audit label supplied by the trusted local host; it is not an authentication credential or a model-supplied identity proof.

A renewal creates a new Authority and supersedes prior decisions. A denial additionally invalidates previous live allowed grants, preventing an older grant from being reused. Revocation targets its exact Authority through the existing trusted control operation. No stored record is edited.

## Persistence and resource binding

New manual runs persist a host-owned session descriptor and per-proposal approval context beneath the existing private case/session directory. The watcher needs this descriptor because its root currently exists only as in-memory CasePaths and events.

The descriptor binds workflow version/mode, client type, case/resource identity, expected policy profile and trusted resource location. Each eligible proposal context binds its Action ID, source Observation ID, immutable baseline/candidate hashes, target, recorded Verification IDs, verifier image and supporting artifacts. Paths are host-generated and validated by the existing redirect/traversal guards. Context hashes are recorded through the collector and copied into decision metadata.

The helper checks context against the actual immutable Action and Verification records, local admissions and artifacts. A missing, altered, foreign or inconsistent context cannot yield a grant or a new receipt. Workflow mode and supported issuer policy come from trusted client profiles, not model data or arbitrary policy supplied in a file.

Each operation reopens SQLite independently. Pending proposals remain inspectable after the model/collector process exits, and approval requires neither an API key nor a model request. Private sessions are local; relocation/rebinding across hosts is outside this first version and missing resource paths refuse progress.

For the watcher, freshness checks read the actual external working-tree bytes and upstream HEAD against the trusted source fingerprint. For the standalone benchmark, they check its owned deployment, tests and contract bytes against the captured context. Measured mismatches enter the graph through existing collector/control operations before the proposal is refused. Manual mode cannot rely on the watcher having recently polled.

Probe immediately before issuing a grant and again immediately before admission. An offline, redirected or changed source is unavailable rather than assumed unchanged. These are observed freshness checks; a later real effect executor must add an atomic version check with its resource mutation. The current simulated receipt does not claim to freeze the external repository.

## Coordination, recovery and idempotency

Use a portable OS-backed session lock around permission mutations and admission. The lock is bounded, releases on process exit, and does not block ordinary log collection. Each process retains its own SQLite connection; existing gate writes remain transactional.

Before admission, reconcile the latest trusted decision and any unfinished supersession/revocation controls. A crash after a denial but before older grants are invalidated cannot make an old grant eligible on restart. A crash during renewal preserves its explicit decision and repairable control history. No Effect is created during this recovery.

Unchanged repeated approval while its grant is active returns that grant. Changing its reason or TTL requires `--renew`, so operator input is never silently discarded. Expired/revoked/denied permission requires a new explicit operator approval to create a new decision; `admit` never renews it. Renewing a grant requires the same freshness, scope and verification checks as initial approval.

Use a public read-only local-receipt lookup backed by the existing action-to-effect mapping to support already-committed retries without creating records. It validates mapping/ancestry and reports current status using the existing retry semantics. Imported Effects do not count as local receipts.

An existing receipt is returned without source/artifact re-execution. Corrupt mapping or ancestry is reported as an integrity failure and cannot be treated as absence to create another receipt.

Admission chooses the latest eligible trusted grant automatically and then passes exact check/authority IDs to `Runtime.commit`. Earlier grants, wrong-action grants, denied/expired/revoked grants, stale evidence and forged local labels remain unusable. SQLite gates concurrent new commits to one receipt.

## Components

- Core: optional Authority decision metadata and read-only local-receipt lookup; no new kinds, required payloads, parent roles or effect handler.
- Approval helper: context validation, derived proposal state, serialized operator decisions, reconciliation and gate invocation. It depends on Runtime/Store and a trusted client freshness adapter, not an agent provider.
- Observed-service adapter: persist context after real candidate checks; manual mode stops before authorization/admission; automatic mode keeps the fixture path.
- Watcher adapter: persist its session/resource identity, keep collecting while proposals wait, and expose pending proposal IDs in events/reports.
- CLI/reporter: operator commands and existing typed record snapshots, with permission state displayed separately from verification and justification.

## Acceptance checks

1. Manual successful candidate creates Claim, ProposedAction and required Verifications, then waits with no Authority or Effect.
2. Reopen that case in another local process; inspect and approve without a key/model call. Approval creates one exact scoped Authority and no Effect.
3. Admission creates one validated local receipt; exact retry and concurrent admission reuse it.
4. Denial is retained and blocks admission, including after earlier approval and after restart.
5. Expiry refuses at the exact boundary; admission cannot auto-renew. Explicit renewal creates an auditable new grant and retires earlier decisions.
6. Revocation before use refuses admission; after use it preserves the historical receipt and reports changed justification.
7. Source changes while pending, during review, or before admission refuse the old proposal, even with passing tests. Watcher source supersession and cold-process direct reads both establish this.
8. Missing/failed/mismatched/invalidated checks, wrong resources, altered artifacts/context, imported Authority/Effects and privileged model fields cannot grant or admit.
9. Crash/restart at each multi-record permission step cannot recover an obsolete grant as usable; no recovery creates an Effect.
10. The collector continues while decisions wait, and stop/restart preserves the queue. No operator command invokes a model.
11. Existing golden format vectors, old authorize callers, automatic fixture results, UTF-8 output and default Windows tests stay compatible.
12. Ordinary tests use recorded decisions and verifier doubles; explicit Docker checks prove manual waiting and later approval/admission against actual candidate tests. No extra live-model proof is needed for this permission lifecycle because the provider contract is unchanged.

## Review and implementation handoff

The written spec is the next reviewable artifact. After its approval, write a test-first implementation plan and preserve the user's Native execution preference: implement here, then one independent final review. Real source effects remain a separate subsequent milestone.
