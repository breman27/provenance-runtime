# Agent integration verification — October 7, 2026

Implementation tasks 1–6 are complete on the local `codex/agent-investigation` branch. Task 7 is incomplete: the live Codex normal and stale-source runs have not passed preflight. This is not a completed live-agent milestone.

## Executed checks

| Command/check | Observed result |
| --- | --- |
| `python -m unittest discover -s tests` | 121 tests, `OK`, exit 0; original 78 core tests included. |
| `python -m unittest discover -s integration_tests -v` | 5 actual Docker tests, `OK`, exit 0; no skips. |
| Independent review | Four Important findings; corrected in one test-first pass. No Critical or Minor findings. |
| Review regressions | Nested function/shadowing rejection; inherited-child deadline; failed-removal diagnostics; real Windows junction and injected leaf-link metadata; safe partial report error. Failures were observed before fixes. |
| `git diff --check` | Clean. |
| Saved replay normal/stale reports | Both ACCEPTED with `live_agent: false`; reopened graphs validated one receipt each and complete VALID ancestry. |
| Live normal-mode CLI attempt | `AGENT_UNAVAILABLE`, preflight stage, exit 1; no case or model response created. |

Verification ran with Python 3.12.14 on Windows and Docker Linux containers. The pinned Python image was `sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`. The actual container suite covers baseline regression, correct/wrong candidates, replay receipt/retry, stale refusal/fresh acceptance, zero/malformed checker results, and timeout removal. Candidate source never ran on the host.

Windows processes are created suspended, assigned to an owned kill-on-close job, and resumed only after ownership is established. The deadline covers inherited pipes after the parent exits. POSIX uses a dedicated process group; this verification run did not execute on a POSIX host. Docker removal gets two bounded, uniquely named attempts; unconfirmed removal yields `CONTAINER_CLEANUP` with a saved owned name and diagnostics. Actual daemon-outage recovery was not induced on the user's system; its failure/retry paths are covered by deterministic process results.

File symlink creation requires an unavailable Windows privilege here. The ordinary tests therefore use a real directory junction for ancestor redirect protection and inject dangling-file-link metadata for leaf checks. No mandatory checks were skipped and no privilege change was made.

## Remaining live prerequisite

Installed Codex `0.162.0-alpha.2` recognizes all requested feature switches, but effective metadata keeps `unified_exec` true even after `--disable unified_exec` and `features.unified_exec=false`. Current [official source](https://github.com/openai/codex/blob/main/codex-rs/core/src/config/managed_features.rs) forces that backend on absent a managed requirement. The application fails closed. No global managed requirements, account credentials, or user config were changed. A compatible CLI/configuration route needs evaluation before actual live normal/stale acceptance.

Docker Desktop initially failed on inaccessible Windows AF_UNIX runtime sockets. The `Docker/run` and `docker-secrets-engine` directories, containing only inspected runtime socket endpoints, were preserved as sibling `.provenance-backup-20261007` folders. Images, containers, and volumes were not reset. Startup retries stopped when the user reported errors. The engine later responded and all container tests passed without further startup changes. The backups were retained.

## Rulings and their costs

1. Define `Evidence` in `case.py` during Task 1 and re-export through the contract to resolve the plan's collector/type dependency. Cost if wrong: adjust internal imports; core API is unaffected.
2. Check Verification subjects by parent role instead of array position because canonicalization sorts parents. Cost if wrong: revise role assumptions across the core.
3. Use explicit disables in read-only `features list` without exec-only configuration flags; inference still requires both `--ignore-user-config` and `--strict-config`. Cost if wrong: preflight may reject a safe exec invocation.
4. Keep the strict preflight and Task 7 incomplete instead of changing global managed requirements or weakening the approved restriction. Cost if wrong: a safe current-CLI proposal mode remains unnecessarily unavailable.
5. Leave successful live behavior unverified, as the reviewer did, until actual responses and Docker results exist. Cost if wrong: live protocol incompatibilities remain undiscovered until that run.
6. Do not induce a Docker daemon outage to test recovery on the user's machine; use deterministic failure regressions plus actual timeout/removal evidence. Cost if wrong: daemon-outage recovery may differ from the simulated failures.

Deferred minors: none. Branch integration is deferred while live acceptance is pending. Private replay case artifacts remain ignored under `work/`; readable/JSON reports are saved separately under the chat's `outputs/`. No new implementation was pushed or published.
