# A real-agent investigation client

This example connects an agent's interpretation to captured evidence and independently checked work. It investigates a small bundled Python repository where `clamp` stopped enforcing its upper bound. The host collects source and a failing test, asks for a claim and candidate fix, tests that exact candidate, and requests a simulated acceptance receipt from the existing runtime.

The core library remains the system of record. This client supplies the collectors, reasoning adapter, test runner, and fixture policy. It is a first integration benchmark, not an agent framework for arbitrary repositories.

## Prerequisites and starting a case

Use Python 3.12+, Git, a running Linux Docker engine, and the Docker CLI. The host resolves `python:3.12-slim` to an image ID at preflight and uses that ID throughout the case. Obtaining the image can require network access; candidate containers have no network.

Live mode also requires a logged-in Codex CLI supporting the restriction flags checked by `CodexAgent.preflight()`. The application invokes `codex login status`; it does not read or copy authentication files. It ignores optional user configuration during inference and disables shell execution, apps, plugins, hooks, browsing, computer use, and subagents. An unsupported or ineffective restriction fails preflight.

```sh
python -m provenance investigate --agent codex --case-dir ./work/live-normal
python -m provenance investigate --agent codex --scenario stale-source --case-dir ./work/live-correction --hint "Check whether the source snapshot is from the current revision."
```

Each `--case-dir` must be new. Existing paths are preserved. Add `--json` for a machine-readable report or `--model MODEL` to select the Codex model explicitly. Without `--model`, the CLI chooses its default. Reports record the requested model and any available provider metadata rather than guessing the model used.

Live mode consumes normal account model usage. There are at most three agent invocations, each bounded to 180 seconds, and each test container is bounded to 30 seconds. `--max-rounds` can reduce the round budget. A human hint requires at least two rounds. These bounds limit invocations and time, not exact token cost. Ordinary unit tests do not invoke a live model or Docker.

## What happens

1. Preflight validates options, a Linux Docker engine and pinned image, then the selected agent backend. No model call occurs if a prerequisite fails.
2. A private Git fixture receives a working revision and an actual upper-bound regression revision. Collectors read revision IDs, source bytes, hashes, and the Git diff. A trusted targeted test must fail on the current baseline.
3. The agent receives evidence under friendly aliases such as `source`, `change`, and `baseline_failure`. It returns a Claim statement, selected aliases, an optional full file replacement, and a short conclusion. The host constructs records and hashes.
4. With a hint, the first proposal stays uncommitted. The host records what the human reported, refreshes source and diff, and asks for a second interpretation. A report is neither proven causation nor authorization.
5. A changed candidate receives one targeted test and all eight full-suite cases. Both checks bind to its complete ProposedAction ID and exact candidate/snapshot hashes. Failed checks become feedback for another round within the budget.
6. Only a candidate passing both suites gets local Authority, scoped to the exact action and fixture for 15 minutes. The existing gate checks evidence, verification, and authority before creating an Effect receipt.

`commit` here means finalize the runtime's simulated local receipt. It does not create a Git commit, modify the source repository, or publish a pull request. Passing tests establish behavior for these test cases; they do not make the agent's root-cause hypothesis universally true. The saved summary is a stated conclusion, not private model chain of thought.

## The reasoning contract

Every response contains exactly four fields:

| Field | Meaning |
| --- | --- |
| `claim_statement` | The interpretation or uncertainty to record, up to 4,000 characters. |
| `evidence_aliases` | Distinct aliases of Observations actually offered in this round. |
| `patch_content` | The complete replacement for `src/clamp.py`, up to 8,000 UTF-8 bytes, or `null`. |
| `summary` | A short user-facing conclusion, up to 4,000 characters. |

The host rejects additional fields, invented IDs, verification or authority declarations, unknown aliases, duplicate JSON keys, and oversize values. Input packets are limited to 128 KiB and process output to 1 MiB. A null or unchanged patch is `UNRESOLVED`, with no action or receipt.

Only the pure `clamp(value, lower, upper)` file can be proposed. Its AST allows optional docstrings and `int` annotations, returns, `if` statements, bounded integer expressions/comparisons, and positional `min`/`max` calls. It rejects imports, assignment, loops, attributes, indexing, arbitrary calls, decorators, conditional expressions, and other functions/classes. Trees are limited to 200 nodes and integer constants to ±1,000,000. This deliberately small profile is separate from the general provenance primitives.

## Independent checking

Candidate Python runs only in fresh Linux containers. The source directory and trusted runner/tests are mounted read-only. The root filesystem is read-only; network is disabled; capabilities are dropped; no-new-privileges is set; the user is `65534:65534`; limits are one CPU, 256 MiB memory, 64 processes, and a 16 MiB temporary filesystem. Runtime DBs, credentials, host home directories, and the Docker socket are not mounted.

The runner requires positive, expected test counts: one targeted regression and eight full-suite tests. A timeout, nonzero unexpected exit, malformed output, zero tests, mismatched hash, or sandbox failure cannot pass. The host records image, runner, test, candidate and snapshot hashes plus actual output and elapsed time. Timeout cleanup names only the uniquely owned case container. There is no host-execution fallback.

## Human correction and stale evidence

The `stale-source` scenario honestly captures an earlier working revision as `source`, while the failing test belongs to the current regression revision. After the human revision-check hint, the collector measures the source revision/hash mismatch and the controller invalidates the earlier case-specific Observation.

A Claim or ProposedAction that actually selected that Observation becomes stale. The host checks the old candidate and attempts the gate before superseding the earlier Claim; the gate must refuse its stale justification even if its tests pass. If the model did not propose work or did not use the old source, the report says so. It does not invent an old action or stale dependency.

The next round excludes the invalid source and offers `source_current`, the human report, and measured mismatch. A replacement Claim has its own Observation parents. Supersession preserves both interpretations without making the replacement depend on the earlier Claim. A human hypothesis alone does not invalidate an Observation.

## Replay mode and another provider

Replay uses a JSON array of one to three response objects with the four fields above:

```sh
python -m provenance investigate --agent recorded --responses ./examples/recorded-repair.json --case-dir ./work/replay
```

Replay still uses real Docker verification, but reports **Recorded reasoning** and `live_agent: false`. Unit-test doubles for verification exist only in test code and are unavailable from the CLI.

A new provider implements `AgentBackend`: host-owned `backend`/`live` attributes, a non-inference `preflight()`, and `propose(AgentRequest, output_dir) -> AgentRun`. The request carries the question, fixture contract, evidence aliases/data, prior summaries, and round index. Use the same `decode_decision` validation; never let provider JSON assign identity, trusted handles, IDs, or permission. The runtime core does not import a provider.

## Artifacts and outcomes

The case retains its Git fixture, SQLite `history.db`, source snapshots, trusted runner, bounded input/validated decision packets, proposed `.patch` files, test result JSON, and `report.json`/`report.md`. Selected CLI metadata can include version, requested model, token counts, and elapsed time. CLI reasoning-event streams are not persisted. Keep cases private: they can contain human reports and application evidence.

Reports distinguish `CLAIMED`, `TESTED`, and the final result:

| Outcome | Exit | Meaning |
| --- | --- | --- |
| `ACCEPTED` | 0 | A verified, authorized exact proposal earned a local receipt. |
| `REFUSED` | 3 | The gate refused a proposal; reason/code remain recorded. |
| `UNRESOLVED` | 4 | No changed candidate was available. |
| `ERROR` | 1 | A prerequisite, adapter, verifier, or I/O failure stopped the investigation. |
| Invalid usage | 2 | Options/response input were invalid; existing cases are preserved. |

Partial created cases retain their evidence and precise error stage. Preflight failures occur before case creation. Friendly names and full provenance references let a human inspect why work was proposed and why a receipt was accepted or refused.

## Verification evidence on October 7, 2026

Unit checks cover real Git captures, strict proposals, process bounds, restricted Docker arguments, action/hash binding, human ordering, stale cascade/refusal, and CLI output. Their verifier/provider doubles do not prove actual container or live-model acceptance.

Actual acceptance remains pending on this machine. Docker Desktop 4.73.0 errors during startup on inaccessible Windows AF_UNIX sockets before a container can run. Two runtime socket folders were preserved as backups during diagnosis; images, containers, and volumes were not reset. Startup retries stopped after the user reported the error. The installed Codex CLI (`0.162.0-alpha.2`) also reports `unified_exec` enabled despite explicit disable settings, so the adapter rejects preflight. No live inference has been consumed or acceptance receipt claimed.

Run actual container acceptance separately with `python -m unittest discover -s integration_tests -v`. Missing prerequisites are failures, never skipped successes. Run the two live commands above only after both preflights pass, and inspect their saved reports/receipt ancestry before claiming the integration milestone complete.
