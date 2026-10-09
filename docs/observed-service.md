# An agent investigates an observed service

For the interactive, continuously running experiment, use the [live service watcher](live-service-watch.md). The benchmark below is retained as a bounded replay/acceptance harness.

As of October 9, new CLI runs default to [manual authority](human-authority.md). Passing candidates wait at `AWAITING_APPROVAL`; use separate `authority inspect`, `approve` and `admit` commands. Add `--approval auto` to reproduce the historical automatic receipt results described below. Existing programmatic calls keep their automatic default.

This benchmark starts with a working sensor-processing repository, captures real operational logs, deploys a code change, and asks an API agent to investigate. No human hint is supplied. The agent chooses its evidence-gathering tools through native OpenAI Responses function calls.

The service processes a batch of readings for a dashboard. Its documented contract requires outputs in 0–100, preserving inputs already in range. The working batch returns `12, 0, 50, 100, 100, 100`. The changed implementation returns `12, 0, 50, 100, 125, 200`. It still starts and emits ordinary `reading_processed` logs: the model must identify the behavioral violation from the data and contract.

## Run both live cases

Python 3.12+, Git, and a running Linux Docker engine are required. No third-party Python packages are needed.

```sh
cd /Users/brett/workspace/provenance-runtime
python3.12 scripts/test_observed_service.py
```

The script uses an existing `OPENAI_API_KEY` or prompts for one locally with hidden input. The key is held only in the process environment and is not written to disk. It runs a healthy control and a regression case, saving each under a fresh `work/service-...` path. Each case contains a small independent Git repository with `README.md`, `service.py`, `src/clamp.py`, and tests, plus logs and the runtime's SQLite graph.

Individual cases:

```sh
python -m provenance observe-service --agent openai --scenario healthy --case-dir ./work/service-healthy
python -m provenance observe-service --agent openai --scenario regression --case-dir ./work/service-regression
```

The default model is `gpt-4.1-mini`; `--model` chooses another compatible non-reasoning model. Reasoning-model tool continuations are rejected because this client does not carry their required reasoning items across turns. Each case permits eight model calls by default, adjustable with `--max-steps` from 1 to 12. Calls have a 180-second deadline and 4,096 output-token cap, with no automatic retries. Native function requests use strict schemas, one call at a time, and `store: false`. API usage is billed to the configured API project. Running both cases can use up to sixteen calls at the default budget.

## Sequence and agent visibility

1. Create a Git repo with the working implementation. Independently run its targeted and full suites before proceeding.
2. Run the service in a restricted Linux container. Capture its stdout logs, executed source hash, snapshot, revision, runner hash, and image ID as a trusted `logs_before` Observation.
3. In the regression scenario, commit the change after the first run. In the healthy control, retain the working revision.
4. Run the deployed service again and admit `logs_current`. Earlier logs remain valid historical facts: they do not assert that the current deployment is healthy.
5. Start the model with the same neutral question in both scenarios: “Check whether the latest sensor-service deployment behaves according to its README. Use available tools to gather evidence and report your assessment.” Neither the scenario label, injected bug, expected diagnosis, nor a human hint is in this question.
6. Dispatch the model's selected tools. Offer only evidence aliases actually returned by tools. Check that the deployed revision and working files remain unchanged before and after each step.
7. Record the final interpretation as a Claim. A changed repair proposal is independently tested before authority and the existing effect gate can admit a simulated receipt.

The available tools are `read_logs`, `read_source`, `read_diff`, `run_tests`, and `finish`. The first four have no arguments. They cannot request arbitrary paths or commands. `finish` carries an assessment, claim, evidence aliases, optional complete file replacement, and summary. A final assessment must use the current logs and current source. Missing current evidence returns feedback within the step budget. Tools cannot create Verification, Authority, or Effect records.

`read_logs` returns the captured earlier/current runs; `read_source` obtains the currently deployed immutable source and README; `read_diff` captures the deployment diff; `run_tests` runs the deployed source in fresh containers. Each tool result is an Observation with a friendly alias. The transcript preserves tool calls and their result packets, never private reasoning streams. Selected API IDs, model, elapsed time and token counts are retained per step. The final Claim hashes the actual saved request packet that produced the function call.

The original `investigate` client still has its proposal-only, zero-tool API contract. This new command intentionally exposes the five bounded application tools. The runtime core and record format are unchanged.

## Outcomes and limits

- `HEALTHY`: the model found the control consistent with the contract; no repair receipt.
- `DETECTED`: it identified the actual regression but supplied no changed repair.
- `ACCEPTED`: it identified the regression and a tested candidate earned one simulated receipt.
- `MISSED` / `FALSE_ALARM`: its assessment disagrees with the observed behavior; exit 3.
- `REFUSED`: a proposal failed verification or admission; exit 3.
- `UNRESOLVED`: inconclusive assessment or exhausted budget; exit 4.
- `ERROR`: a prerequisite, provider, collector, or infrastructure failure; exit 1. Invalid CLI/replay usage exits 2.

An evaluation-only host check compares the actual current outputs with the README's contract to distinguish detection, misses and false alarms. That classification is not sent to the model or used as evidence for its Claim. Evidence and gate admission are separately validated.

Service and candidate code execute only in Linux Docker containers with the existing network, filesystem, privilege, user and resource restrictions. Credentials and the runtime DB are not mounted. The only proposed edit is the bounded pure `clamp` function; candidate verification runs one targeted and eight full-suite tests. A receipt is simulated acceptance, with no automatic application to the deployed repo.

This is a bounded batch/deployment experiment. It does not yet implement a continuous log watcher, arbitrary repository tooling, or an agent already investigating while a deployment moves. The revision guards refuse a deployment change during this run. The experiment measures autonomous tool selection and behavioral regression detection across two real deployments.

## Replay and verification

```sh
python -m provenance observe-service --agent recorded --responses ./examples/recorded-service-regression.json --case-dir ./work/service-replay
python -m provenance observe-service --agent recorded --scenario healthy --responses ./examples/recorded-service-healthy.json --case-dir ./work/service-control-replay
TMPDIR=/private/tmp python -m unittest discover -s tests
TMPDIR=/private/tmp python -m unittest discover -s integration_tests -v
```

Replay performs actual service and test-container runs but supplies recorded tool choices and conclusions. Reports label it as replay. Unit tests use doubles and cannot establish live-model detection. The explicit Docker suite checks real healthy/broken operational logs, failing deployed tests, passing repair tests, one valid receipt, and a healthy control with no effect. On macOS, `/private/tmp` avoids symlinked temporary ancestors without weakening the case-path boundary.

Live-model success must be established by inspecting the new live cases' tool calls, Claims, test results, and receipt ancestry. Replay success is not a claim about how a live model behaves.

The [verification record](observed-service-verification.md) distinguishes the executed unit/container/replay checks from pending live-model acceptance.
