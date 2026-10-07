# Agent integration verification — October 7, 2026

The user amended the provider choice to OpenAI Responses API. Implementation and live acceptance for tasks 1–7 now pass on the local `codex/agent-investigation` branch. The separate original Codex CLI route remains unavailable under its unchanged restriction; this is no longer the selected live prerequisite. The API amendment received a separate focused independent review after the original branch review.

## Executed checks

| Command/check | Observed result |
| --- | --- |
| `python -m unittest discover -s tests` | 135 tests, `OK`, exit 0; original 78 core tests included. |
| `python -m unittest discover -s integration_tests -v` | 5 actual Docker tests, `OK`, exit 0; no skips. |
| Independent review | Four Important findings; corrected in one test-first pass. No Critical or Minor findings. |
| Independent API amendment review | No Critical or Important findings. One Minor provider-envelope check deferred. |
| Review regressions | Nested function/shadowing rejection; inherited-child deadline; failed-removal diagnostics; real Windows junction and injected leaf-link metadata; safe partial report error. Failures were observed before fixes. |
| `git diff --check` | Clean. |
| Saved replay normal/stale reports | Both ACCEPTED with `live_agent: false`; reopened graphs validated one receipt each and complete VALID ancestry. |
| Original Codex-mode attempt | `AGENT_UNAVAILABLE`, preflight stage, exit 1; no case or model response created. |
| Live OpenAI normal case | ACCEPTED, actual model proposal, one targeted/eight full tests, one receipt. |
| Live OpenAI stale-source case | Two actual model rounds. First selected old source and passed checks, but was REFUSED STALE. Fresh second proposal ACCEPTED. |
| Live API receipt inspection | Reopened both graphs: complete VALID ancestry, one Effect each, exact-action retry reused each receipt. |

Verification ran with Python 3.12.14 on Windows and Docker Linux containers. The pinned Python image was `sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`. The actual container suite covers baseline regression, correct/wrong candidates, replay receipt/retry, stale refusal/fresh acceptance, zero/malformed checker results, and timeout removal. Candidate source never ran on the host.

Windows processes are created suspended, assigned to an owned kill-on-close job, and resumed only after ownership is established. The deadline covers inherited pipes after the parent exits. POSIX uses a dedicated process group; this verification run did not execute on a POSIX host. Docker removal gets two bounded, uniquely named attempts; unconfirmed removal yields `CONTAINER_CLEANUP` with a saved owned name and diagnostics. Actual daemon-outage recovery was not induced on the user's system; its failure/retry paths are covered by deterministic process results.

File symlink creation requires an unavailable Windows privilege here. The ordinary tests therefore use a real directory junction for ancestor redirect protection and inject dangling-file-link metadata for leaf checks. No mandatory checks were skipped and no privilege change was made.

## Actual API evidence and original CLI limitation

Both live cases returned model `gpt-4.1-mini-2025-04-14`. Across three actual model calls, selected usage metadata recorded 6,624 input tokens and 452 output tokens (zero cached input tokens). The host exposed no tools and sent strict-schema foreground requests with `store: false`, no automatic retry, and 4,096 maximum output tokens. Raw provider reasoning/error bodies and the API key were not persisted.

Normal receipt: `sha256:cf76ed68fd549e8634fc46337f1d82d0774f64ed5ae5261681d603c61523d1f3`.
Correction receipt: `sha256:89aa0842248f2192adaf763eaf1ea5800c36966e12d2852bad76dc9b22991815`.
The first correction action `sha256:b6657ac673b4265b23929374d2bc09c650e977eebbebb0762cacf167c6f83a11` selected the old source and was refused with `STALE`. The second packet contained the supplied human hint and current source, excluded the invalid source, and the replacement Claim had no old-Claim parent. Its candidate earned the only Effect in that case.

Two issues exposed by actual model output were reproduced and fixed: missing-final-newline patches now carry Git's marker without modifying candidate bytes; CLI output uses UTF-8 even when the Windows text stream uses another encoding. Corrected display patches were saved separately from the first live artifacts and checked with `git apply --check`. Model calls were not repeated for these display corrections.

Installed Codex `0.162.0-alpha.2` recognizes all requested feature switches, but effective metadata keeps `unified_exec` true even after `--disable unified_exec` and `features.unified_exec=false`. Current [official source](https://github.com/openai/codex/blob/main/codex-rs/core/src/config/managed_features.rs) forces that backend on absent a managed requirement. That adapter still fails closed. No global managed requirements or Codex credentials were changed. The user configured an API key through the Windows user environment and explicitly selected the API route.

Docker Desktop initially failed on inaccessible Windows AF_UNIX runtime sockets. The `Docker/run` and `docker-secrets-engine` directories, containing only inspected runtime socket endpoints, were preserved as sibling `.provenance-backup-20261007` folders. Images, containers, and volumes were not reset. Startup retries stopped when the user reported errors. The engine later responded and all container tests passed without further startup changes. The backups were retained.

## Rulings and their costs

1. Define `Evidence` in `case.py` during Task 1 and re-export through the contract to resolve the plan's collector/type dependency. Cost if wrong: adjust internal imports; core API is unaffected.
2. Check Verification subjects by parent role instead of array position because canonicalization sorts parents. Cost if wrong: revise role assumptions across the core.
3. Use explicit disables in read-only `features list` without exec-only configuration flags; inference still requires both `--ignore-user-config` and `--strict-config`. Cost if wrong: preflight may reject a safe exec invocation.
4. Keep the strict Codex preflight instead of changing global managed requirements or weakening the approved restriction. Cost if wrong: a safe current-CLI proposal mode remains unnecessarily unavailable. The later user-selected API route fulfilled live acceptance.
5. Leave successful live behavior unverified, as the original reviewer did, until actual responses and Docker results exist. Cost if wrong: live protocol incompatibilities remain undiscovered until that run. Both API live cases subsequently passed.
6. Do not induce a Docker daemon outage to test recovery on the user's machine; use deterministic failure regressions plus actual timeout/removal evidence. Cost if wrong: daemon-outage recovery may differ from the simulated failures.
7. Verify client request settings rather than claim control over OpenAI's server retention/billing implementation. Cost if wrong: server behavior may differ from the client's requested settings.
8. Prove the default model live without making paid calls to every optional model ID. Unsupported model settings fail without a provider fallback. Cost if wrong: a selected alternative model may be incompatible until its first run.
9. Carry forward the original process/AST/Docker/gate review and test their new interactions instead of commissioning another review of unchanged code. Cost if wrong: an undiscovered interaction may remain despite the regression and live checks.

Deferred minor: the raw API envelope parser accepts duplicate top-level keys and does not reject an explicitly incomplete message when the response's overall status says completed. The independently validated decision, candidate tests, authority, and gate still apply; no conforming API response was found that triggers this contradiction. Additional envelope validation can tighten that edge without changing the contract. The review grades it Minor; no execution/authority bypass was found.

Private case artifacts remain ignored under `work/`; readable/JSON reports are saved separately under the original chat's `outputs/`. The user subsequently authorized committing and publishing the finished implementation to continue on another computer. The [continuation handoff](continue-on-another-computer.md) records setup, verified behavior, and the deferred minor; credentials and private cases remain excluded from Git.
