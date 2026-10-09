# Human Authority Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Preserve the user's Native execution preference: one implementer here and one independent whole-branch reviewer at the end.

**Goal:** Persist verified proposals until a separate local operator grants permission, and admit one simulated receipt only while the exact proposal, checks and current grant remain usable.

**Architecture:** Keep the existing graph/gate and add a provider-independent approval client. Its host-recorded session/context binds the resource and exact proofs; local commands serialize decisions, reconcile interrupted controls and reuse existing receipts. The observed-service clients publish eligible manual proposals while the watcher continues collecting.

**Tech Stack:** Python 3.12+, standard library, existing SQLite store, Git, existing restricted Linux Docker verifier; no new dependency or model request.

**Spec:** `docs/superpowers/specs/2026-10-09-human-authority-workflow-design.md`.

## Global Constraints

- Keep canonical version 0.1, required payload fields, record kinds and parent roles unchanged. Effects remain `repo.repair.simulated` SQLite receipts.
- Local host code, database access and runtime handles remain trusted. The bounded API model has no approval tools/issuer handle. This work does not isolate an unrestricted same-user shell agent or authenticate a remote human.
- All operator actions use fixed compiled client profiles/roles. No arbitrary issuer, policy, path/command, historical-grant override or provider fallback is exposed.
- TTL is type `int` (not bool), 1–60 minutes, default 15; reason is null/empty or at most 4,000 characters. Expiry refuses at equality. No command silently renews permission.
- All new text/artifacts use UTF-8/LF, bounded strict JSON, and existing `safe_path` redirect/traversal guards. Opening an operator session must not create a missing DB.
- Decision sequences are positive safe JSON integers, allocated per Action under the session lock. They determine permission order independently of timestamps.
- Operator commands perform no inference. Existing model/tool/time bounds and independent candidate checks remain unchanged.
- CLI/convenience helpers default new observed-service runs to manual; existing programmatic calls default to auto. Legacy sessions retain their original behavior and are not silently migrated.
- Physical source probes occur before approval and admission. Existing receipts are inspected/reused without source re-execution. Later real effects require a separate atomic resource-version/mutation integration.
- Do not hold SQLite read/write transactions across Git/filesystem probes. The operator lock does not participate in ordinary collection.

## Review Focus

1. A missing/foreign/mutated session/context, redirected artifact or guessed resource must not create a DB, grant or new receipt — Tasks 2/3.
2. An expired/revoked/denied grant must not be replaced implicitly by admission or rescued by selecting an older grant after crash/clock rollback — Tasks 4/7.
3. Source changes without a running watcher, or during review/admission, must refuse the old exact action; a newly issued permission can become stale and must never admit an effect — Tasks 3/5/7.
4. Reopening a committed case with unavailable source or corrupt mapping must return its valid existing receipt or an integrity error, never interpret corruption as absence and duplicate it — Tasks 1/4/7.
5. Waiting proposals must not stop collection, expose approval tools to the model, or make local actor labels look like authenticated identity — Tasks 5/6/7.

## Workspace and interfaces

Execute in the existing isolated `codex/authority-workflow` checkout, currently `C:/Users/bsema/Documents/Codex/2026-10-07/alr/outputs/provenance-runtime-agent`. Preserve its ignored earlier private cases. Create this plan's ledger with the executing-plans workspace script; baseline is `main` at `30d5380` plus approved design/plan commits. The previously verified baseline has 174 ordinary tests and three affected Docker checks passing. Run fresh baseline verification at execution start, then record actual counts/commands.

| Unit/file | Responsibility |
| --- | --- |
| `provenance/runtime.py` | Optional Authority decision metadata and read-only local receipt lookup. |
| `provenance/clients/authority/profiles.py` | Fixed service profiles and role/check constants; no provider imports. |
| `provenance/clients/authority/lock.py` | Bounded OS-backed local session lock. |
| `provenance/clients/authority/context.py` | Host-recorded session/proposal DTOs, persistence, ownership/proof/artifact validation. |
| `provenance/clients/authority/resources.py` | Service-specific physical freshness probes and measured mismatch controls. |
| `provenance/clients/authority/manager.py` | Derived states, decisions/reconciliation/revocation/admission. |
| `provenance/clients/authority/cli.py`, `report.py` | Local operator commands and record-based UTF-8 reports. |
| `provenance/clients/observed_service/contract.py` | Existing unchanged service-contract text, moved to avoid circular imports. |
| Existing observed-service experiment/watch/CLI and scripts | Manual queue publication and explicit auto compatibility. |
| `tests/authority_support.py`, `tests/authority_process.py` | Deterministic verified cases and subprocess lock/decision helpers; no production fault hooks. |
| `tests/test_authority_*.py`, `integration_tests/test_authority_docker.py` | Regression, concurrency, cold-process and actual Docker acceptance. |

Fixed profile IDs: `observed-service-auto-v1` maps to existing policy version `observed-service-v1`; `observed-service-manual-v1` maps to that policy version/name. Both keep subject `observed-service`, observer `collector`, verifier `tester` for `targeted_tests`/`full_suite`, controller `controller`, and existing action requirement. Auto issuer is `issuer`; manual issuer is `human-operator`. Client tags are `observed-service` and `watch-service`.

Session file: `approval-session.json`, max 64 KiB, strict object `{descriptor, observation_id}`. Descriptor fields are format `provenance-approval-session`, version `0.1`, session_id (32 hex chars), mode, client, profile, source_repository (host-selected absolute path), database `history.db`. A locally admitted collector Observation retains the descriptor/hash. Do not deserialize arbitrary policy lists from the file.

Proposal file: `approvals/<action hex>.json`, max 128 KiB, strict `{context, observation_id}`. The context binds session_id, case_id, client, action_id, case_dir/repository relative to session, source_observation_id, baseline_revision/snapshot, candidate_snapshot, target_path, original/candidate file hashes, required verification_ids, image_id, and artifact paths/hashes. Snapshot manifests and proof JSON are owned relative paths. A trusted collector Observation stores source `approval-context`, the canonical context and its hash. Only one eligible context per action is permitted; conflicting trusted contexts are an error. Withdrawals/receipt inspection can recover ownership from the intact recorded context when files/source are unavailable; grants/new admission require the matching physical context/artifacts.

Manual decision metadata fields: method `local-cli`, actor `human-operator`, context_hash, sequence, reason, ttl_minutes. Fixed top-level grant fields always come from the runtime/action. Identical active-grant approval reuses its ID; altered reason/TTL requires `--renew`; expired/revoked/denied state permits a new explicit approval. Conflicting same-sequence trusted decisions are an integrity error.

### Task 1: Compatible core authority metadata and receipt lookup

**Files:** Modify `provenance/runtime.py`; create `tests/test_authority_core.py`; reuse existing gate/format tests.
**Consumes:** Existing Policy/Store/CommitResult and core mapping/retry semantics.
**Produces:** `Runtime.authorize(handle, action_id, allowed, expires_at, *, decision: dict | None = None) -> str`; `Runtime.local_receipt(action_id: str) -> CommitResult | None`.

- [ ] Write regressions for omitted metadata preserving old canonical body, detached metadata copies, non-object/invalid JSON metadata, forged handles, no receipt, locally committed receipt, imported Effect, corrupt mapping/ancestry and no record writes from lookup.
  ```python
  self.assertEqual(runtime.store.get(old_grant).payload, expected_legacy_payload)
  self.assertIsNone(runtime.local_receipt(uncommitted_action))
  self.assertTrue(runtime.local_receipt(committed_action).reused)
  self.assertFalse(runtime.local_receipt(corrupt_action).integrity.ok)
  ```
- [ ] Run `python -m unittest tests.test_authority_core -v`; Expected RED on absent keyword/method.
- [ ] Add the optional decision field only when supplied, through canonical JSON validation/copy. Implement lookup inside a short read snapshot using the existing mapping and `_existing` retry validator; no admission/policy/effect behavior changes.
- [ ] Run `python -m unittest tests.test_authority_core tests.test_runtime tests.test_gate tests.test_format -v`; Expected `OK` and unchanged golden vectors.
- [ ] Commit `feat: retain authority decisions and inspect local receipts`.

### Task 2: Session profiles, descriptor binding and portable coordination

**Files:** Create authority package marker, `profiles.py`, `lock.py`, descriptor portion of `context.py`; create `tests/test_authority_context.py`, `test_authority_lock.py`, helpers.
**Consumes:** Task 1, Runtime/Policy, canonical_json/parse_json, safe_path and existing CasePaths.
**Produces:** frozen `ApprovalSession(root: Path, database: Path, session_id: str, mode: str, client: str, profile: str, source_repository: Path, observation_id: str)`; `authority_policy(mode: str) -> Policy`; `create_session(runtime: Runtime, root: Path, case_id: str, mode: str, client: str, source_repository: Path) -> ApprovalSession`; `open_session(root: Path) -> ApprovalSession`; `session_lock(session: ApprovalSession, timeout: float = 5.0)` context manager.

- [ ] Test fixed profiles/roles, descriptor roundtrip/local collector admission, wrong profile/session/hash, missing DB without creation, existing descriptor mode-change refusal, Unicode paths, traversal and real Windows junction/POSIX symlink rejection. Test a second process timing out on the lock, release after exit/crash, acquisition failure cleanup and no unrelated path modification.
  ```python
  self.assertEqual(authority_policy('manual').issuers, ('human-operator',))
  self.assertFalse(missing_database.exists())
  self.assertEqual(open_session(root).session_id, created.session_id)
  ```
- [ ] Run descriptor/lock tests; Expected RED before the modules exist.
- [ ] Implement strict bounded descriptor persistence with a host Observation binding, allowlisted profiles and database existence checks. Use standard `msvcrt`/`fcntl` OS locks on guarded `approval.lock`, monotonic acquisition deadline, automatic handle release; no PID-file deletion/stale-lock heuristic.
- [ ] Run `python -m unittest tests.test_authority_context tests.test_authority_lock tests.test_authority_core -v`; Expected `OK`, no skipped redirect/lock proof.
- [ ] Commit `feat: persist trusted approval sessions and coordinate operators`.

### Task 3: Exact proposal context, proof validation and physical freshness

**Files:** Complete `context.py`, create `resources.py`, extract unchanged `observed_service/contract.py`; extend helpers/tests with `tests/test_authority_resources.py`.
**Consumes:** Session/profile/lock interfaces; Snapshot/save_snapshot/validate_patch; actual Action/Verification/Observation/admission APIs.
**Produces:** frozen `ProposalContext(action_id: str, observation_id: str, context_hash: str, data: dict)` with defensive copies; `record_context(session: ApprovalSession, runtime: Runtime, case: CasePaths, baseline: Snapshot, action_id: str, source_observation_id: str, verification_ids: tuple[str, ...]) -> ProposalContext`; `load_context(session: ApprovalSession, store: Store, action_id: str, *, artifacts: bool = True) -> ProposalContext`; `check_current(session: ApprovalSession, runtime: Runtime, context: ProposalContext) -> None`.

- [ ] Test exact source/candidate/snapshot/action binding, required positive-count named checks and local admissions, wrong subject/hash/check/image/artifact, unknown target/resource, imported contexts, conflicting contexts, missing/redirected/altered files and context. Test recorded ownership lookup with unavailable source for withdrawal/receipt inspection.
- [ ] Add direct freshness tests: upstream working-tree edit without collector polling, Git HEAD change, owned fixture source/tests/README/service tampering including invalid UTF-8, missing/offline repo and redirected path. Assert measured change preserves historical logs, invalidates only the case-specific source view, and stales its action.
- [ ] Run context/resource tests; Expected RED on missing proof/context/freshness behavior.
- [ ] Persist baseline/candidate snapshots and proof JSON under the proposal's owned paths. Validate context hash against the locally admitted Observation, exact resource `fixture:clamp:<case_id>`, target `src/clamp.py`, normalized candidate and the supplied `targeted_tests`/`full_suite` subject/evidence bindings. Fail closed rather than scan for convenient older passing checks.
- [ ] Locate the unique trusted recorded context in the graph; require its matching file/artifacts for a grant or new admission. With `artifacts=False`, intact graph/session ownership supports withdrawal or existing-receipt inspection even when source/context files are unavailable. A conflicting trusted context for one action fails closed.
- [ ] Use raw byte/hash checks plus immutable revisions for owned service, and source-byte/upstream-HEAD fingerprint for the live repo. Resolve source location from host session data only. Record a measured mismatch then invalidate the scoped source before refusing; missing/unreadable source is `SOURCE_UNAVAILABLE`, not evidence that it changed. Release DB snapshots before physical I/O.
- [ ] Run `python -m unittest tests.test_authority_context tests.test_authority_resources tests.test_observed_service -v`; Expected `OK`, no model/Docker invocation.
- [ ] Commit `feat: bind pending approvals to exact verified resource contexts`.

### Task 4: Permission lifecycle, recovery and one-receipt admission

**Files:** Create `manager.py`, `tests/test_authority_manager.py`; extend deterministic helpers.
**Consumes:** Tasks 1–3 and existing Runtime authorize/invalidate/supersede/commit.
**Produces:** `ApprovalResult(action_id: str, state: str, authority_id: str | None, effect_id: str | None, reused: bool, reason: str, integrity_ok: bool, record_snapshot: dict)` plus `as_dict()`; `ApprovalManager(session_dir: Path, *, clock: Callable[[], datetime] = utc_now)` with `list(include_all: bool = False) -> tuple[ApprovalResult, ...]`, `inspect(action_id: str) -> ApprovalResult`, `approve(action_id: str, ttl_minutes: int = 15, reason: str | None = None, renew: bool = False) -> ApprovalResult`, `deny(action_id: str, reason: str | None = None) -> ApprovalResult`, `revoke(authority_id: str, reason: str | None = None) -> ApprovalResult`, `admit(action_id: str) -> ApprovalResult`. Errors use InvestigationError code/stage/detail.

- [ ] Write lifecycle tests for waiting/approve-without-effect/denial/admit, exact expiry equality, renewal/active retry/reason or TTL conflict without `--renew`, revocation before/after effect, denial after approval, reapproval after denial, already-committed denial refusal, invalid TTL/bool/reason, untrusted/imported/wrong-scope grants, clock rollback and conflicting sequences.
  ```python
  self.assertEqual(manager.inspect(action).state, 'AWAITING_APPROVAL')
  self.assertIsNone(manager.approve(action).effect_id)
  self.assertEqual(manager.deny(action).state, 'DENIED')
  self.assertEqual(manager.admit(approved_action).state, 'COMMITTED')
  self.assertTrue(manager.admit(approved_action).reused)
  ```
- [ ] Add interrupted denial/renewal regressions by raising from ordinary runtime control calls in tests after the new Authority is persisted. Reopen the manager; older grants cannot be selected, required controls reconcile, and recovery creates no Effect. Deny/revoke still work offline; expired/revoked/denied admission never renews.
- [ ] Run manager tests; Expected RED on missing methods/states/recovery.
- [ ] Open a validated session/own Store per operation. Under the operator lock, allocate per-action sequence from locally admitted human decisions and reconcile all earlier decisions. Supersede earlier decisions on renewal; invalidate previous allowed grants on denial. Recover missing controls before mutation/admission. Never order permission by timestamp/hash or accept a user-selected historical grant.
- [ ] Default list includes `AWAITING_APPROVAL`, `APPROVED`, `EXPIRED` and `REVOKED`; `--all` includes every owned proposal/history state. Normalize empty reason to null before active-grant comparison. A busy lock returns `LOCK_TIMEOUT` without a decision or effect.
- [ ] Validate current proof/context before approval; probe before grant and admission. Derive result again after issuance: a grant becoming stale concurrently is reported unusable. Core transactional gate remains the final effect check. Existing receipt lookup runs before source re-execution and refuses corrupt mapping/integrity; retries never mint new Authority.
- [ ] Run manager/context/core/gate tests; Expected `OK`. Commit `feat: enforce durable manual authority decisions`.

### Task 5: Manual observed-service and continuing watcher integration

**Files:** Modify experiment/watch/CLI, `provenance/__main__.py`, `scripts/watch_observed_service.py`, `scripts/test_observed_service.py`; create `tests/test_authority_clients.py`, extend watcher/service tests.
**Consumes:** Session/context/manager and current verifier/agent contracts.
**Produces:** `service_policy(approval_mode: str = 'auto') -> Policy`; keyword `approval_mode: str = 'auto'` on run_experiment and ServiceWatcher; prepared jobs include `approval_session_root`, `approval_mode`. New CLI/helper `--approval manual|auto` defaults manual, passed explicitly. Programmatic omitted mode and auto tests retain legacy behavior.

- [ ] Test eligible manual finish stores exact required Verifications/context and returns `AWAITING_APPROVAL` with no Authority/Effect; failed/wrong/healthy/inconclusive/no-op proposals do not become eligible. Confirm explicit auto path and old programmatic calls still produce existing results. Model tool catalogue/finish fields never expose approval controls.
- [ ] Test continuous collection while a verified action waits, multiple source versions staling old proposals, shared DB with independent worker/operator connections, descriptor reopen after stop and direct stale-source detection without further ticks. Pending events include full Action ID and session root.
- [ ] Run client/watcher tests; Expected RED on absent mode/queue publication.
- [ ] Persist manual session identity after preflight/owned setup. Watcher persists its stable root identity while each investigation keeps its own case/resource UUID. Write explicit candidate proof artifacts and record context after successful checks; add context/session records to report roots without offering them as model-selected evidence. Manual branch stops before authorize/commit; auto branch keeps its existing records/fixture semantics rather than implicitly creating a manual queue.
- [ ] Add `APPROVAL_PENDING` output/events and preserve investigation coalescing/stop behavior. Do not hold an operator lock across agent calls or make collection wait for a human. Treat `AWAITING_APPROVAL` as successful completed investigation (CLI exit 0), distinct from permission/receipt.
- [ ] Run new clients plus existing observed-service/watch/report/CLI tests; Expected `OK`. Commit `feat: queue verified service proposals for human approval`.

### Task 6: Operator commands and typed review reports

**Files:** Create authority `cli.py`, `report.py`, `tests/test_authority_cli.py`; modify `provenance/__main__.py` and shared report integration.
**Consumes:** ApprovalManager/ApprovalResult and existing snapshot_records/render_record_report.
**Produces:** `run_cli(args) -> int`; `render_authority_report(result: ApprovalResult) -> str`; `authority list|inspect|approve|deny|revoke|admit` exact spec flags and JSON output.

- [ ] Test parser requirements/full content IDs, invalid reason/TTL/unsupported issuer or grant override before writes, missing DB without creation, default/manual vs explicit auto, list filtering/--all, grant-only output, denial/expiry/revocation/stale/refused outcomes, receipt retry, UTF-8 under ASCII stdout, preserved unrelated files and report-write failure after persisted mutation.
- [ ] Run authority CLI tests; Expected RED before command group exists.
- [ ] Lazily dispatch commands without importing agent/API-key setup. Use fixed operator/profile only; present context/diff/evidence/verification/grant roles and application state separately from runtime status. Save guarded UTF-8 `authority-report.json`/`.md` in the proposal case; preserve original model input packets. Errors retain partial record facts.
- [ ] Exit 2 invalid usage, 1 operational/integrity error, 3 refused admission, 0 successful inspection/decision/admission. No arbitrary execution, issuer, resource paths or historical-grant choice flags.
- [ ] Run authority CLI plus existing demo/observed-service/investigation CLI/report tests; Expected `OK`. Commit `feat: expose local authority review and admission commands`.

### Task 7: Cold-process, concurrency and actual Docker acceptance

**Files:** Create `tests/test_authority_recovery.py`, subprocess test helper, `integration_tests/test_authority_docker.py`; extend manager tests only for failures exposed by acceptance.
**Consumes:** Complete workflow and existing actual Docker verifier/recorded service tools.

- [ ] Add cold-process tests opening saved cases with model constructors set to fail if invoked, key variables absent, and recorded owned proofs. Approve then admit in separate processes; concurrent approvals allocate one ordered history, identical retries reuse active grant, concurrent admission yields exactly one receipt. Test lock contention/release and crash at each control-reconciliation phase.
- [ ] Add Docker cases for real manual verified waiting followed by local approval/admission; denial and source-edit refusal even with passing original candidate checks; watcher continues collecting/pending report after stop; explicit auto fixture remains accepted. Require actual candidate checks and receipt ancestry/retry validation, no skipped mandatory checks or host candidate execution.
- [ ] Run ordinary full suite and `python -m unittest discover -s integration_tests -v`. Expected both `OK`, exit 0. Missing Docker is an environment blocker, not a successful skip. Tests expose only ordinary interfaces/mocks; no production failure hooks.
- [ ] Fix only reproduced failures under TDD. Reopen accepted graphs, validate every record/mapping and the complete why trace; ensure no duplicate local Effect and no authority for unapproved manual proposals. Record default Windows results; retain explicit POSIX-unverified limitation if no POSIX host run is available.
- [ ] Commit `test: prove manual authority across restarts and concurrent operators` after checks pass.

### Task 8: Documentation, final independent review and handoff

**Files:** Create `docs/human-authority.md`, `docs/human-authority-verification.md`; update README, service/watch guides and continuation handoff; preserve execution ledger/rulings.
**Consumes:** Actual verified commands/results and complete workflow.

- [ ] Document the human flow with a minimal recorded/Docker example: queue → inspect → approve → admit, plus deny/revoke/renew/expiry/stale cases. State SDK auto compatibility, new CLI manual default, private context files, local trust limits and infrastructure needed for a general shell agent. Permission is for the simulated consequence; investigation tools retain existing preapproval.
- [ ] Document selected roles/TTL/sequence/context binding, loss/corruption/offline behavior, no model calls by operators, immutable historical receipts, and how another client supplies a trusted resource adapter. Report verification counts and actual limitations without claiming live-model or POSIX runs not performed.
- [ ] Self-check spec coverage, source diff, metadata/no secret/case DB publication and `git diff --check`; full tests from Task 7 remain the required evidence unless code changes.
- [ ] Dispatch one fresh independent whole-branch reviewer on the most capable model per Native workflow, with spec/plan/ledger and all five Review Focus items. Fix consequential findings through reproduced regressions and a green full suite; defer/report minor items and rule explicitly on declined judgments. No re-review of covered fixes.
- [ ] Commit verification/docs, preserve the record before removing only this plan's verified scratch workspace. Follow the user's repository publication preference after successful review; private cases stay ignored and real source effects remain deferred.

## Plan self-review and handoff

Spec coverage: core additions (1), scoped persistence/locking (2), bindings/direct physical freshness (3), states/decisions/recovery/idempotency (4), manual/auto collection integration (5), CLI/report vocabulary (6), process/Docker proof (7), trust documentation/review (8). Interfaces introduced earlier are consumed by the exact later names above; constant service contract extraction avoids context/resource/experiment import cycles. Each Review Focus owns explicit tests.

Native execution is already selected and is preserved. Review this written plan before implementation; after approval execution proceeds continuously task-by-task, with no per-task permission prompts.
