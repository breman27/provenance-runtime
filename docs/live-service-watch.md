# Live service watcher

New command-line/helper sessions default to [manual authority](human-authority.md). Verified repairs emit `APPROVAL_PENDING` with a full Action ID and session path, while collection continues. Use that session path for `authority list`, `inspect`, `approve` and `admit`. Stopping collection preserves pending proposals. `--approval auto` explicitly selects the historical automatic receipt behavior in the October 7 run described below; programmatic defaults remain automatic.

This is the interactive experiment: leave one process running, edit a real repository from the chat, and observe what the collector and API agent do. The watcher never changes the watched repository. It has no injected failure scenario or predetermined edit sequence.

## Start

```sh
cd /Users/brett/workspace/provenance-runtime
python3.12 scripts/watch_observed_service.py
```

The helper prompts locally for an API key when needed. Leave the terminal open. The default watched Git repo is `/Users/brett/workspace/provenance-observed-service`. The editable implementation is `src/clamp.py`. Uncommitted edits are detected; committing is optional. The service maps incoming integer readings into the inclusive 0–100 display range. Its incoming batches vary.

The script prints the session directory. Each five-second tick runs the current captured implementation on a fresh batch in a restricted Linux container, writes actual stdout logs, admits an Observation, and displays the inputs, outputs, source version and Observation ID. Source execution is container-only. The collector runs until Ctrl+C or a `STOP` file appears inside the session directory.

Typical console activity:

```text
SOURCE_CAPTURED v1
OBS #1 v1 OK | -14->0, 32->32, 81->81, 176->100, 0->0, 100->100
AGENT #1 step 1: read_logs
AGENT #1 step 2: read_source
AGENT #1 HEALTHY: ...
OBS #2 v1 OK | ...
```

The displayed order and model-selected tools depend on the actual run. These lines illustrate the interface, not predetermined agent output.

## Make changes from the chat

After startup, share the session path printed in the terminal. We can inspect `latest.json`, the event stream, logs and agent reports while editing the watched repo. Make a behavior-preserving change first and wait for the agent's assessment. Then introduce a change that violates the contract or crashes the service and inspect whether the live agent detects it.

Source changes and newly observed failure transitions queue a neutral investigation. The model chooses logs, current source, diff and test tools; it receives no injected diagnosis or human hint. Collection continues in the main thread during bounded model calls in a separate worker thread. Repeated unchanged batches add Observations without repeat API investigations. Only one investigation runs at a time, with one latest pending version; rapid edits coalesce.

Each investigation has the existing eight-call budget, 180-second per-call deadline, 4,096 output-token cap and no automatic retries. The running watcher has no total model-call budget: new edits can trigger new bounded investigations. Defaults use `gpt-4.1-mini`; the existing non-reasoning model restriction applies. API usage uses the configured API project. The key stays in process memory/environment and is not written to session files.

The host displays its mechanical `OK`, `ANOMALY`, or `ERROR` check separately from the model's actual assessment and Claim. A host-detected anomaly alone is not live-model success. `AGENT_RESULT` must show what the model concluded, with its saved evidence references and report. An agent may miss a regression, invent one, stay inconclusive, fail, or propose a repair; those outcomes remain visible.

## Evidence and changing versions

One SQLite graph spans the whole session. Every captured source view and run has content hashes and actual timestamps. A private Git mirror retains the exact working-tree bytes collected at each version, plus the upstream HEAD. The watcher only reads the external source repo; it creates capture commits in its owned session mirror. Model tools use those immutable captured revisions.

A changed working tree supersedes the earlier `current_working_tree` source Observation. Prior Claims about that current-source view become stale, while historical run logs remain valid facts. If another edit occurs during an investigation, its guards refuse the old version and display `STALE`; the latest captured version gets its own queued investigation. Candidate repairs are independently tested and can earn simulated receipts in the shared graph. They remain proposals; apply code changes from this chat.

Session files:

- `events.jsonl`: collection, source changes, selected tools and final results.
- `latest.json`: latest source/log Observation IDs and mechanical health.
- `history.db`: continuous provenance records, controls, Claims and any receipts.
- `versions/version-*/batch-*.jsonl`: exact service stdout for each batch.
- `repository/`: private Git capture history.
- `investigations/investigation-*/report.md`: model assessment and exact evidence/test/receipt details.

A service crash is captured as an error Observation with stdout, stderr, source hash and exit metadata. Syntax/runtime failures remain visible to the agent. The proposed replacement still obeys the existing pure-function profile and independent candidate gate. The active watched file is `src/clamp.py`; the runner, operating contract, and verifier are host-owned for this small demo.

Ctrl+C stops collection and waits for an in-flight bounded request to return before final shutdown. On return from an in-flight request, the stop guard refuses further investigation work. Session directories must be new and cannot contain redirected paths. On macOS, use real temporary paths such as `/private/tmp` for smoke checks.

## Other options

```sh
python3.12 scripts/watch_observed_service.py --interval 2
python3.12 scripts/watch_observed_service.py --agent none
python3.12 -m provenance watch-service --repo /Users/brett/workspace/provenance-observed-service --session-dir ./work/watch-smoke --agent none --interval 1 --max-ticks 3
```

`--agent none` still collects real observations continuously but performs no inference. `--max-ticks` is an optional finite smoke-check setting; the normal helper has no tick limit.

## Verification on October 7, 2026

All 161 ordinary tests and eight real Docker acceptance tests passed after adding the watcher. New checks cover continued collection during a blocked model turn, source supersession and stale Claims, unsaved good/bad edits, coalescing rapid edits, one shared graph, crash/error capture, and no repeated model calls for unchanged healthy batches. Mock agent choices establish lifecycle behavior, not actual live-model assessment.

A separate collector smoke run used the clean permanent `/Users/brett/workspace/provenance-observed-service` repo for three actual varying-input batches. All outputs satisfied the operating contract. The session retained four intact records (one source view and three run Observations); every saved stdout artifact matched its Observation hash. That run used `--agent none`, exited cleanly, and left the watched repo's Git working tree unchanged. Its artifacts are under `work/watch-collector-check-20261007` in provenance-runtime.

The interactive API watch was subsequently verified in session `work/watch-20261007-201054-95956`. The clean baseline and two behavior-preserving edits were each reported HEALTHY by the live model. A third chat-driven edit removed the upper-bound check; the agent detected the regression without a hint, requested source/log/diff/test tools, and proposed the missing check. The independently tested candidate earned one simulated receipt. Details follow.

## Actual interactive API run — October 7, 2026, Eastern time

The user started the keyed watcher at approximately 8:10 p.m. We inspected its running baseline, then made two good edits and one breaking edit from the chat. The watched repo's upstream HEAD stayed unchanged; all edits were uncommitted working-tree changes. No failure scenario or human hint was sent to the model.

| Captured version | Actual chat change | Live result | Selected model calls |
| --- | --- | --- | --- |
| 1 | Original `max(lower, min(value, upper))` | HEALTHY | logs, source, finish |
| 2 | Equivalent `min(upper, max(lower, value))`, plus a docstring | HEALTHY | source, logs, tests, finish |
| 3 | Explicit lower- and upper-bound checks | HEALTHY | logs, source, finish |
| 4 | Removed the upper-bound check | Regression detected; repair ACCEPTED | source, logs, diff, tests, finish |

The first failing batch contained input 223 and output 223. The model cited that exact operational violation alongside the current source, actual deployment diff, and failing targeted/full test observations. Its proposed replacement restored the upper-bound branch. The independent candidate passed one targeted test and eight full-suite tests. Its simulated receipt was admitted 8.343 seconds after the first failing batch was recorded. This used 15 actual API calls across four investigations; the model selected different tool sequences for them.

At graph inspection, all 69 stored records validated. The three earlier healthy Claims were STALE because their current-source Observations had been superseded. The latest receipt's complete ancestry was VALID, exactly one Effect existed, and exact-action retry reused it in a copied database. Each final Claim's input hash matched its actual saved final request packet, evidence parents matched the model's selected aliases, and saved operational stdout hashes matched the corresponding Observations. Original live databases were inspected through read-only backups.

The collector was still running at the end of inspection. The demo source was deliberately left in the failing version for review; the model's repair remains a proposal and was not applied automatically. The regression report is `work/watch-20261007-201054-95956/investigations/investigation-0004/report.md`. No provenance-runtime changes were committed or pushed.
