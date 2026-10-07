# First Real Agent Investigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user selected Native execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect one actual Codex reasoning client to real source/test observations, human feedback, independent verification, and the existing provenance gate.

**Architecture:** Add an example client under `provenance/clients/repo_repair/`, independent of the core runtime. The client prepares a known-bug repository, captures evidence, requests structured claims/proposals from a provider adapter, and tests candidate code in Docker. The existing runtime retains the graph and admits the simulated acceptance receipt.

**Tech Stack:** Python 3.12+ and its standard library, Git, Docker with Linux containers, and the installed Codex CLI using normal saved authentication. No new Python package dependencies.

**Spec:** [Approved agent-investigation design](../specs/2026-10-07-agent-investigation-design.md), approved October 7, 2026.

## Global Constraints

- “The model receives evidence aliases and data, not trusted handles or the database path.”
- “Every selected alias must resolve to an Observation actually supplied in that reasoning round.”
- “The first round contains no later human hint.”
- Preserve canonical schema `0.1`, existing core public APIs, and the action type `repo.repair.simulated`. Core format/rules/store/runtime/gate modules do not import the client or its dependencies.
- Editable target: exactly `src/clamp.py`; exact function parameters: `value`, `lower`, `upper`.
- Response keys: exactly `claim_statement`, `evidence_aliases`, `patch_content`, `summary`. Claim/summary limit: 4,000 characters each; patch limit: 8,000 UTF-8 bytes; adapter output limit: 1 MiB.
- AST limit: 200 nodes; integer constant range: -1,000,000 through 1,000,000. Apply the spec's pure-function restrictions before execution.
- “Default maximum: three agent invocations, 180 seconds per invocation, 30 seconds per container test run.” Invocation/time limits are not promises of an exact token or monetary budget.
- Docker verification: no network; read-only root and mounts; unprivileged user; dropped capabilities; no-new-privileges; one CPU; 256 MiB; 64 processes; private temporary storage.
- Resolve `python:3.12-slim` once to an exact image ID and use that ID throughout a case. Never run candidate Python on the host as a fallback.
- Required checks: `targeted_tests` and `full_suite`. Authority expires 15 minutes after issuance and binds the exact action and fixture resource.
- “A later claim may confirm the same diagnosis or change it; do not require a model to change its conclusion merely because a human spoke.”
- Recorded-response mode is visibly labeled; ordinary unit tests make no live model calls. Explicit Docker/live tests supply separate evidence.
- The effect remains a local receipt. Background monitoring, chat UI, arbitrary repositories, general tool selection, and real PR/deployment effects remain deferred.

## Review Focus

1. Existing case paths, symlinks/junctions, and path traversal must never overwrite an earlier case or escape the selected case root — Tasks 1 and 2.
2. No-op/unchanged proposals and null proposals must be reported honestly; they must not silently become successful repair receipts — Tasks 2 and 5.
3. A Docker timeout must terminate the case's container, not merely the CLI process, and an infrastructure failure must not become a passing verification — Task 3.
4. Model output attempting to cite an invalidated/not-offered observation or supply privileged fields must fail before record admission — Tasks 2, 4, and 5.
5. A human hint arriving after an initial interpretation must remain new evidence; revisions must not mutate or causally depend on the claim they supersede — Task 5.

## Workspace and verification

The design and plan live on `codex/agent-investigation`. At execution, use the workspace-isolation skill to verify/create an appropriate isolated feature workspace and record its absolute path in this plan's ledger. Start from the approved design/plan commits, not an uncommitted copy.

Use the existing bundled Python interpreter or another Python 3.12+ interpreter. Commands below assume `python` is that interpreter and run from the repository root. Keep transient implementation artifacts under the plan's ignored workspace and live case artifacts under the chat's `work/` directory. Do not publish live case data automatically.

Ordinary suite: `python -m unittest discover -s tests -v`. Explicit container suite: `python -m unittest discover -s integration_tests -v`. Live smoke commands are in Task 7. Success means exit code 0 and `OK`; mandatory container/live checks cannot be replaced by skipped tests or recorded responses.

Docker's engine was stopped during design. Start/check it during authorized execution, resolve the selected image, and verify sandbox availability before an agent call. If a prerequisite needs user setup, continue independent unit work and report that prerequisite precisely; do not weaken the execution profile.

## File structure

| File | Responsibility |
| --- | --- |
| `provenance/clients/__init__.py`, `provenance/clients/repo_repair/__init__.py` | Example-client package; no provider imports in the core package. |
| `provenance/clients/repo_repair/errors.py` | Client errors with code, stage, and detail. |
| `provenance/clients/repo_repair/case.py` | New private case, fixture assets, Git revisions, snapshots, and artifact paths. |
| `provenance/clients/repo_repair/contract.py` | Evidence packets, strict response decoding, pure patch validation, and canonical records. |
| `provenance/clients/repo_repair/process.py` | Bounded subprocess execution and process-tree cleanup. |
| `provenance/clients/repo_repair/verifier.py` | Docker preflight, immutable candidate preparation, trusted execution, and verification evidence. |
| `provenance/clients/repo_repair/runner.py` | Trusted in-container unittest runner; never accepts test code from the model. |
| `provenance/clients/repo_repair/agent.py` | Provider protocol, explicit recorded backend, and restricted Codex adapter. |
| `provenance/clients/repo_repair/coordinator.py` | Bounded investigation rounds, human contribution, supersession/invalidation, and gate admission. |
| `provenance/clients/repo_repair/report.py` | Plain-English and JSON reports. |
| `examples/repair-fixture/src/clamp.py`, `examples/repair-fixture/tests/test_clamp.py`, `examples/repair-fixture/README.md` | Known-bug source, trusted tests, and the stated behavior contract. |
| `tests/test_investigation_case.py`, `tests/test_investigation_contract.py`, `tests/test_investigation_verifier.py`, `tests/test_investigation_agent.py`, `tests/test_investigation_flow.py`, `tests/test_investigation_cli.py`, `tests/investigation_support.py` | Unit and deterministic coordinator tests. |
| `integration_tests/test_investigation_docker.py` | Opt-in actual container execution, separate from ordinary discovery. |
| `provenance/__main__.py`, `README.md`, `docs/agent-investigation.md` | CLI delegation and user documentation. |

## Shared interfaces

These definitions belong to the task that produces them. Later tasks reuse the names and signatures.

- `InvestigationError(code: str, stage: str, detail: str)` is a ValueError with those properties. Core ProvenanceError remains unchanged and its code/detail are preserved in reports.
- `CasePaths(root: Path, repository: Path, artifacts: Path, agent_view: Path, database: Path, case_id: str, good_revision: str, baseline_revision: str)` is immutable. Generated resource: `fixture:clamp:<case_id>`.
- `Snapshot(revision: str, files: dict[str, bytes], file_hashes: dict[str, str], snapshot_hash: str)` is a captured value; expose defensive copies. Its manifest hashes the revision and sorted file hashes using canonical JSON. Preserve source bytes.
- `Evidence(alias: str, node_id: str, payload: dict)` is host-owned. Only alias and payload are serialized to the agent; node ID resolution stays with the host.
- `AgentRequest(question: str, contract: str, evidence: tuple[Evidence, ...], history: tuple[dict, ...], round_index: int)` has `packet() -> dict`. The packet uses JSON-compatible values and no private paths/handles.
- `AgentDecision(claim_statement: str, evidence_aliases: tuple[str, ...], patch_content: str | None, summary: str)` is validated output. `AgentRun(decision: AgentDecision, backend: str, live: bool, metadata: dict)` adds host-derived attribution.
- `ProcessResult(returncode: int, stdout: bytes, stderr: bytes, elapsed_ms: int, timed_out: bool, output_exceeded: bool)` is immutable. Callers decide whether a captured process outcome is acceptable.
- `TestResult(suite: str, image_id: str, snapshot_hash: str, candidate_hash: str, tests_run: int, failures: int, errors: int, returncode: int, elapsed_ms: int, outcome: str, stdout: bytes, stderr: bytes)` has `passed: bool`. PASS requires exit 0, positive count, zero failures/errors, complete valid output, and no timeout/infrastructure error.
- `InvestigationOptions(case_dir: Path, scenario: str = "normal", hint: str | None = None, model: str | None = None, max_rounds: int = 3)` validates scenarios `normal`/`stale-source`, positive budget at most 3, and a 4,000-character hint limit.
- `InvestigationReport(case_id: str, backend: str, live_agent: bool, outcome: str, stage: str, rounds: tuple[dict, ...], observations: dict[str, str], final_action_id: str | None, effect_id: str | None, error: dict | None)` has `as_dict() -> dict`. Outcomes are ACCEPTED, REFUSED, UNRESOLVED, or ERROR. Round entries carry CLAIMED/TESTED/ACCEPTED/REFUSED stage events, summaries, IDs, and artifact references.

### Task 1: Private case and real source observations

**Files:** Create package markers, `errors.py`, `case.py`, fixture files, `tests/test_investigation_case.py`, and test support.

**Produces:** CasePaths, Snapshot, InvestigationError; `prepare_case(root: Path) -> CasePaths`; `capture_snapshot(case: CasePaths, revision: str) -> Snapshot`; `collect_source(runtime: Runtime, observer: ObserverHandle, case: CasePaths, revision: str, alias: str) -> Evidence`; `collect_diff(runtime, observer, case, before: str, after: str, alias: str) -> Evidence`.

- [ ] Write `test_fixture_revisions_and_snapshot_integrity`, `test_case_refuses_existing_directory`, `test_case_paths_cannot_escape`, `test_snapshot_preserves_source_bytes`, and `test_collectors_record_actual_revision_and_diff`. Assert the known-bug source differs from the good revision and captured hash matches independently hashed source bytes. A source Observation records the actual revision and source time, not a fabricated current revision.
  ```python
  good = capture_snapshot(case, case.good_revision)
  bad = capture_snapshot(case, case.baseline_revision)
  self.assertNotEqual(good.file_hashes["src/clamp.py"], bad.file_hashes["src/clamp.py"])
  self.assertIn(b"upper", bad.files["src/clamp.py"])
  self.assertEqual(evidence.payload["revision"], case.baseline_revision)
  ```
- [ ] Run `python -m unittest tests.test_investigation_case -v`; Expected: new behavior fails before implementation.
- [ ] Implement new-case validation before writes, with resolved root/subpath containment, no reparse/symlink destinations, and no overwrite. Create synthetic fixture Git history with stable fixture author metadata and no remote. The good implementation clamps both bounds; the changed implementation clamps only the lower bound. Trusted tests use 8 named cases: above upper, below lower, within bounds, exact lower, exact upper, equal bounds, negative interval, and large bounded input. Targeted suite selects the above-upper regression.
- [ ] Capture source/test bytes with `git show <revision>:<path>` and a real revision diff using argument arrays, not shell strings. Copy the baseline into private immutable artifact directories. Keep `.git`, DB, output files, and handles out of agent-visible material. Use canonical hash manifests and register real source/diff observations through Runtime.observe.
- [ ] Run the targeted tests; Expected: exit 0, `OK`. Commit with message `feat: capture real fixture evidence in private cases`.

### Task 2: Structured proposal contract and pure patch profile

**Files:** Create `contract.py`, `tests/test_investigation_contract.py`; extend `case.py` and test support.

**Consumes:** CasePaths/Snapshot, existing canonical format and Runtime APIs.
**Produces:** Evidence, AgentRequest, AgentDecision, AgentRun; `decode_decision(data: bytes, offered: tuple[Evidence, ...]) -> AgentDecision`; `validate_patch(content: str) -> bytes`; `admit_decision(runtime, case, baseline: Snapshot, request: AgentRequest, run: AgentRun) -> tuple[str, str | None]`; `response_schema(aliases: tuple[str, ...]) -> dict`; `candidate_snapshot(baseline: Snapshot, patch: bytes) -> Snapshot` in `case.py`.

- [ ] Write named tests for exact fields/limits, missing/extra fields, duplicate JSON keys, unknown/stale aliases, empty alias list, invalid UTF-8, null proposal, CRLF normalization, no-op proposal, forbidden path/privileged fields, and allowed/forbidden AST shapes. Forge `passed`, `authority_id`, or `id` in the response and assert rejection without new graph records. Offered evidence is validated against the store and execution status before admission.
  ```python
  with self.assertRaises(InvestigationError):
      decode_decision(forged_response, offered)
  self.assertEqual(validate_patch(valid_crlf_patch), valid_lf_patch.encode("utf-8"))
  claim_id, action_id = admit_decision(runtime, case, baseline, request, null_patch_run)
  self.assertEqual(store.get(claim_id).kind, "Claim")
  self.assertIsNone(action_id)
  ```
- [ ] Run `python -m unittest tests.test_investigation_contract -v`; Expected: failing new contract behavior.
- [ ] Implement strict decoding with the existing restricted JSON parser. All four response fields are required. Enforce the spec's byte/character limits and distinct offered aliases. Normalize candidate text to LF before hashing. No-op text yields a recorded Claim with no action and an honest unresolved summary, never a receipt.
- [ ] Validate AST without evaluating/importing candidate code. Permit only the exact `clamp` signature, docstrings, If/Return, integer Constants, allowed argument/builtin Names, comparisons, Boolean expressions, unary +/-/not, and integer arithmetic +, -, *, //, %. Calls may target only built-in `min`/`max`, with 1–3 positional expressions and no keywords/starred arguments. Annotations may be absent or the bare name `int`. Reject every other node/name, assignment, extra definition, default, decorator, or type parameter. Check 200-node and constant-range limits.
- [ ] Construct Claim/ProposedAction through the existing APIs. Resolve only Observation evidence. Host sets producer/timestamp/resource/IDs. Action arguments are `baseline_snapshot`, `candidate_snapshot`, `target_path`, `original_file_hash`, and normalized `patch_content`; target path is host-filled `src/clamp.py`. Compute the candidate manifest from the captured baseline plus the one normalized replacement. Attach backend/live attribution and summary to the Claim payload. Do not expose privileged handles in either DTO.
- [ ] Run targeted contract/case tests; Expected: `OK`. Commit with message `feat: validate agent claims and bounded patch proposals`.

### Task 3: Bounded processes and trusted Docker verification

**Files:** Create `process.py`, `verifier.py`, `runner.py`, `tests/test_investigation_verifier.py`; extend test support.

**Consumes:** CasePaths/Snapshot, candidate_snapshot, patch validator, InvestigationError.
**Produces:** ProcessResult, TestResult; `run_process(argv: tuple[str, ...], cwd: Path, stdin: bytes | None = None, timeout: int = 30, max_output: int = 1048576) -> ProcessResult`; `DockerVerifier(command: str = "docker")` with `preflight() -> str`, `test(snapshot: Snapshot, case: CasePaths, suite: str) -> TestResult`; `record_test(runtime, observer, verifier_handle, action_id: str, result: TestResult, artifact_refs: dict) -> tuple[str, str]` returning Observation/Verification IDs. TestResult.snapshot_hash identifies the tested whole candidate manifest; candidate_hash identifies the tested `src/clamp.py` bytes. record_test checks both against the action arguments before admitting trusted output.

- [ ] Write tests for positive-count PASS, actual FAIL-shaped result, zero tests, malformed result, nonzero status, timeout, output overflow, wrong suite/hash, missing engine/image, and container-only cleanup. The process fake lives in test utilities; production code keeps only its ordinary lifecycle methods. Assert the Docker invocation's privilege/mount boundaries and that no host Python candidate execution is invoked.
  ```python
  self.assertFalse(zero_test_result.passed)
  self.assertFalse(timeout_result.passed)
  self.assertTrue(valid_positive_count_result.passed)
  self.assertEqual(store.get(verification_id).parents[0].node_id, action_id)
  self.assertEqual(store.get(observation_id).payload["candidate_hash"], expected_candidate_hash)
  ```
- [ ] Run `python -m unittest tests.test_investigation_verifier -v`; Expected: failing new verifier behavior.
- [ ] Implement subprocess invocation with shell disabled, bounded simultaneous stdout/stderr capture, elapsed integer milliseconds, and timeout cleanup of the owned process tree. On Windows use hidden subprocess creation and terminate only the launched PID/tree; on POSIX own the process group. Do not dump environment variables or authentication material.
- [ ] Preflight a Linux Docker engine and resolve/pull `python:3.12-slim` only during authorized execution, then pin its local image ID. Prepare the candidate by replacing the one allowed file in a new snapshot. Use `--network none`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--user 65534:65534`, `--cpus 1`, `--memory 256m`, `--pids-limit 64`, and a 16 MiB `/tmp` tmpfs. Mount only snapshot and trusted runner/tests, read-only. Generate a unique case-owned container name.
- [ ] The trusted runner selects the fixed targeted/full test suite, requires positive count, and emits one structured result with counts. Candidate pure-code validation precedes container execution. Preserve output/artifact digests and image/runner/test/source hashes. Timeout/interruption removes only the owned container; infrastructure/parse/overflow failure returns an unusable result and can never report PASS. Verification records must bind the supplied exact action and supporting test Observation.
- [ ] Run verifier/contract/case tests; Expected: `OK`. Commit with message `feat: independently verify candidates in restricted containers`.

### Task 4: Recorded provider and restricted live Codex adapter

**Files:** Create `agent.py`, `tests/test_investigation_agent.py`; extend test support.

**Consumes:** AgentRequest/Decision/Run, schema and strict decoder, run_process.
**Produces:** `AgentBackend` protocol with `backend: str`, `live: bool`, `preflight() -> None`, `propose(request: AgentRequest, output_dir: Path) -> AgentRun`; `RecordedAgent(responses: tuple[bytes, ...])`; `CodexAgent(command: str = "codex", model: str | None = None)`.

- [ ] Write tests for recorded-response sequencing/exhaustion, explicit `live=False`, schema-output parsing, null response, timeout/output limits, process failure/missing output, unsupported restriction switches, login failure, and forbidden response fields. Assert the input packet for round 1 excludes the later hint. Verify backend output cannot assign its own `live` status or trusted producer.
  ```python
  run = recorded.propose(request, output_dir)
  self.assertFalse(run.live)
  self.assertEqual(run.backend, "recorded")
  with self.assertRaises(InvestigationError):
      decode_decision(forged_privileged_response, request.evidence)
  ```
- [ ] Run `python -m unittest tests.test_investigation_agent -v`; Expected: failing new adapter behavior.
- [ ] Implement RecordedAgent through the same strict decoder as live responses. Store only the bounded input packet, validated output, and selected metadata; no CLI JSONL reasoning events are persisted. Limit the serialized input packet to 128 KiB and reject overflow before invocation rather than silently truncating evidence. A successful recorded response remains recorded mode even when its patch later passes real Docker tests.
- [ ] Implement Codex preflight using version/help, `login status`, and supported feature switches, without inference or manually reading credentials. Invoke `codex exec` with `--ignore-user-config`, `--strict-config`, `--ephemeral`, `--sandbox read-only`, `--skip-git-repo-check`, `--json`, `--output-schema`, and `--output-last-message`; supply the packet on stdin and a generated proposal workspace as cwd. Set `approval_policy="never"`, `web_search="disabled"`, and `mcp_servers={}` per invocation. Omit model unless explicitly supplied.
- [ ] Disable supported effect-capable features: `shell_tool`, `unified_exec`, `apps`, `plugins`, `hooks`, `multi_agent`, `browser_use`, `browser_use_external`, `browser_use_full_cdp_access`, `computer_use`, `in_app_browser`, `image_generation`, `code_mode_host`, `remote_plugin`; also disable `daemon_auto_start` and `unbounded_connection_retries`. Verify these switches are recognized and effective through CLI metadata. Unsupported restrictions yield `AGENT_UNAVAILABLE` before inference; never add a permissive fallback. The generated view has only supplied case material, never runtime DB or handles.
- [ ] Parse only the final schema output. Attribute backend/live/CLI version/model/elapsed/token counts from host or documented CLI metadata. Ignore reasoning events and reject unexpected effect-capable tool events. Apply 180-second and 1 MiB bounds. Adapter failure records its stage without admitting a Claim/Action from malformed output.
- [ ] Run agent and affected contract/verifier tests; Expected: `OK`. Commit with message `feat: connect structured reasoning through a restricted Codex adapter`.

### Task 5: Bounded investigation and human correction

**Files:** Create `coordinator.py`, `tests/test_investigation_flow.py`; extend test support.

**Consumes:** All earlier client interfaces and existing Runtime, status, Supersession/Invalidation, and commit APIs.
**Produces:** InvestigationOptions/Report; `run_investigation(options: InvestigationOptions, agent: AgentBackend, verifier: DockerVerifier) -> InvestigationReport`. Tests may supply protocol-compatible deterministic verifier results; that test implementation is not a CLI backend.

- [ ] Write deterministic flow tests for correct/incorrect candidates, null/no-op proposal, missing prerequisites before agent use, exhausted round budget, exact action binding, human hint ordering, supersession without old-Claim dependency, and partial-error preservation. Use a backend that raises on use to prove prerequisite failure does not consume inference.
  ```python
  self.assertEqual(correct_report.outcome, "ACCEPTED")
  self.assertIsNotNone(correct_report.effect_id)
  self.assertEqual(wrong_report.outcome, "REFUSED")
  self.assertIsNone(wrong_report.effect_id)
  self.assertEqual(no_proposal_report.outcome, "UNRESOLVED")
  self.assertFalse(recorded_report.live_agent)
  ```
- [ ] Add `test_stale_source_refuses_old_action_and_accepts_fresh_evidence` and `test_human_hint_is_not_automatic_invalidation`. Assert the case-specific old snapshot becomes INVALID only after measured revision/hash mismatch, an old dependent action becomes STALE, and a new claim excludes the invalid source. A human hypothesis alone changes no old status.
- [ ] Run `python -m unittest tests.test_investigation_flow -v`; Expected: failing new coordinator behavior.
- [ ] Implement option validation and preflight before creating a case or invoking a model. Register host-owned collector/human/verifier/issuer/controller handles with fixture policy requiring both check names. Capture baseline targeted failure through the real verifier interface; a baseline that passes or has infrastructure failure cannot proceed as the intended known-bug case.
- [ ] Build each request from execution-usable Observation aliases and explicit prior summaries. Round 1 excludes the hint; if supplied, keep its proposal uncommitted, capture the human report afterward, refresh source/diff, and run the next round. Treat the hint as a report, not verified causation or permission. Record every validated model response/Claim even when no proposal is available; malformed output is retained only as a bounded error artifact. Failed tests produce real feedback for the next call until the three-invocation budget is spent; no fabricated success on exhaustion.
- [ ] In `stale-source`, initially capture the good revision as the honestly labeled old source while failure comes from the baseline revision. On the hint/refreshed read, record the mismatch and invalidate the earlier case-specific source. If an old proposal actually depends on that source, test it and attempt the gate with available verification records; issue Authority only if both checks pass. Assert the gate refuses it as stale before adding later supersession. If the model did not use that source, report the proposal's actual dependency/status rather than inventing an invalidation effect; keep it uncommitted while choosing the later proposal. With no old proposal, preserve the Claim and report that fact. The next request excludes the invalid source. A superseding Claim references its own observations, not the old Claim. Deterministic regression responses deliberately select the old source to prove cascade/refusal.
- [ ] For the selected candidate, check immutable baseline/current source and exact candidate/action hashes, run both suites, and record their real output. Issue exact-action Authority only when both checks pass, with a 15-minute expiry, then call the existing gate. Preserve any core failure code. Return ACCEPTED, REFUSED, UNRESOLVED, or ERROR honestly, with partial artifacts retained. Retrying a committed exact action uses existing runtime semantics and creates no duplicate receipt.
- [ ] Run flow and affected client tests; Expected: `OK`. Commit with message `feat: record bounded collaborative repair investigations`.

### Task 6: Readable reports, CLI, and documentation

**Files:** Create `report.py`, `tests/test_investigation_cli.py`, `docs/agent-investigation.md`; modify `provenance/__main__.py` and README.

**Consumes:** InvestigationOptions/Report and provider/coordinator factories.
**Produces:** `render_report(report: InvestigationReport) -> str`; `run_cli(args) -> int`; CLI `investigate --agent codex|recorded --case-dir PATH --scenario normal|stale-source --hint TEXT --model MODEL --json`. Recorded mode requires an explicit recorded-response file and is labeled throughout.

- [ ] Write tests for readable record names, first/later interpretation, hint, proposed diff, test results, admission/refusal, JSON validity, recorded/live attribution, unresolved/infrastructure outcomes, invalid arguments without case writes, and nonempty-case refusal. Existing `demo` CLI output must remain compatible.
  ```python
  self.assertIn("Recorded reasoning", render_report(recorded_report))
  self.assertIn("REFUSED", render_report(refused_report))
  self.assertEqual(json.loads(json_output)["live_agent"], False)
  self.assertFalse(invalid_case_path.exists())
  ```
- [ ] Run `python -m unittest tests.test_investigation_cli tests.test_demo -v`; Expected: new CLI/report tests fail; original demo tests remain green.
- [ ] Add lazy CLI delegation to the client without new imports in core `__init__`. Preserve demo options. Human output is default; `--json` is machine output. Progress goes to stderr. Exit codes: 0 ACCEPTED, 3 REFUSED, 4 UNRESOLVED, 1 infrastructure/adapter ERROR, 2 invalid CLI usage. Save a final report and stage/error information when a created case has partial progress; preflight failures before case creation are reported without overwriting paths.
- [ ] Document prerequisites, model-usage boundaries, restricted fixture profile, actual versus recorded runs, source collection, hint interpretation, patch/testing/authority stages, stale-source behavior, artifacts, and how another provider could implement AgentBackend. State that final effects remain receipts and tests do not universally prove a root-cause hypothesis.
- [ ] Run targeted CLI and affected client tests; Expected: `OK`. Commit with message `feat: expose readable agent investigation CLI`.

### Task 7: Actual container and live-agent acceptance

**Files:** Create `integration_tests/test_investigation_docker.py`; update `docs/agent-investigation.md` with observed verification evidence. Test helpers remain under tests/integration_tests, not production classes.

**Consumes:** Complete client and existing provenance queries.

- [ ] Write explicit container tests before the integration glue: real baseline regression fails; the independently supplied correct pure patch passes targeted and all 8 full-suite cases; unchanged/wrong candidate fails; zero/malformed/timeout results do not pass; fixture tests and base source remain unchanged. Include recorded-agent end-to-end cases for normal acceptance and stale-source refusal/fresh acceptance, using the actual Docker verifier.
  ```python
  self.assertFalse(baseline_result.passed)
  self.assertTrue(correct_targeted.passed)
  self.assertEqual(correct_full.tests_run, 8)
  self.assertTrue(correct_full.passed)
  self.assertIsNone(stale_attempt_effect_id)
  ```
- [ ] Run `python -m unittest discover -s integration_tests -v`; Expected: expose missing integration glue or pass existing implemented behavior. For behavior already covered/implemented by earlier task tests, add no duplicate production code; record that the explicit integration test confirms it. A missing Docker prerequisite is a reported environment condition, not a skipped acceptance success.
- [ ] Complete only the integration wiring those failures reveal, under TDD. Run the ordinary full suite and explicit container suite; Expected: both exit 0 with `OK`, no skipped mandatory checks.
- [ ] Run one explicit live normal case with `python -m provenance investigate --agent codex --case-dir <fresh-live-normal-path> --json`. Require actual Codex output, real Docker checks, an admitted receipt, and validated ancestry. Reopen its DB and verify the receipt's complete explanation. Record actual model/CLI/image identifiers when available, with credentials/internal reasoning omitted.
- [ ] Run one explicit live stale-source case with `--scenario stale-source --hint "Check whether the source snapshot is from the current revision."` in another fresh case directory. Require a second actual agent round consuming the hint and fresh source evidence. Report what it actually did, including confirmation/no-proposal outcomes. The deterministic container test independently proves stale dependent-action refusal; do not pretend the live model generated a proposal it did not produce.
- [ ] Preserve user-facing readable/JSON reports under outputs after checking them. Keep raw transient artifacts under work and do not publish live case data or push the implementation without the applicable final integration decision. Review changed files for accidental credentials, case DBs, `.git` fixture directories, or model transcripts.
- [ ] Commit with message `test: prove real verifier and live agent integration` after required checks pass. Perform the Native workflow's fresh independent whole-project review; fix consequential findings through failing regressions and a green suite. Record remaining limitations and any actual unavailable prerequisite.

## Plan self-review and handoff

Every approved design section maps to a task: fixture/capture (1), data contract/patch constraints (2), independent verification/resource bounds (3), provider interface/restrictions (4), collaboration/status/gate (5), CLI/artifacts/docs (6), actual integration evidence (7). Review Focus conditions each have an owning regression. Shared interfaces are defined above and consumed without changing names.

The preserved execution method is Native: implement task-by-task here, then one independent final reviewer. The human reviews this written plan before implementation, as required by the planning workflow.
