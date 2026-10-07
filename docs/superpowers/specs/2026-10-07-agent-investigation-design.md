# First real agent investigation

Approved — October 7, 2026

## Purpose and success

Replace the original demo's handwritten reasoning and verification with one actual agent integration and real tool results. A human can contribute a hint after the initial analysis. The runtime must preserve the resulting evidence and claims and admit a local receipt only for a verified, authorized proposal with usable justification.

The accepted scope is a manually started investigation of a small bundled repository with a known bug. This is an application using the existing library. The agent provider stays behind an adapter; observation capture, testing, authority, and record construction belong to the trusted host application.

Success means: a live agent produces a proposed code change; trusted tools independently test the exact candidate; the gate accepts or refuses it for a mechanically explainable reason; a human contribution enters a later reasoning round; and an invalidated input blocks a dependent proposal while its history remains available.

## Approach

**Selected agent backend: existing Codex CLI.** The user selected this route. The installed CLI is `0.162.0-alpha.2` and reports a ChatGPT login. Its local help supports non-interactive execution, a read-only sandbox, ephemeral runs, and a schema-constrained final answer. Official documentation describes structured final responses and reuse of saved CLI authentication ([non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)).

The adapter supplies a bounded packet of captured evidence and accepts a structured reasoning response. It does not ask Codex to modify the actual repository. Use the CLI's default model unless a caller explicitly supplies `--model`; record the selected/reported model when available.

Alternative routes considered: a direct model API would need separate provider/key setup; an external-agent JSON interface would prove interchangeability but leave the first live connection to another application. Neither is required for this milestone. The adapter contract must permit a deterministic recorded-response backend for repeatable tests and a future second provider.

**Selected verifier backend: Docker Linux containers.** Docker Desktop is installed locally, but its Linux engine is currently stopped. A running engine and the selected Python image are preconditions for verification, not a reason to fall back to running proposed code directly on the host. Docker's run interface supports read-only filesystems/mounts and resource limits ([Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/)).

## Bundled repository

Ship a small Python repository containing `src/clamp.py` and trusted unittest files. `clamp(value, lower, upper)` must return an integer constrained to the supplied bounds. The known bug fails to enforce the upper bound; targeted tests cover that regression and the full suite also covers normal values and lower bounds.

The host prepares a private case copy and real Git revisions/diff describing the known change. Capture source bytes, file hashes, revision IDs, test-run results, and the selected baseline snapshot as Observations. Record event/source timestamps where relevant and the Observation's actual creation time separately. Do not substitute handwritten PASS values for execution results.

Only `src/clamp.py` is an editable proposal target. Tests, the trusted runner, case metadata, credentials, and the runtime's own source are outside that target. A proposal supplies replacement text for the function file; the host creates an actual unified diff for display. This first fixture supports a pure integer clamp function, with an AST shape allowing bounded expressions/conditionals and calls only to `min`/`max`. Reject imports, executable top-level code, additional functions/classes, decorators, loops, arbitrary calls, and edits to other paths before execution. This is a constrained integration benchmark, not an arbitrary-repository runner.

## Components and boundaries

| Component | Responsibility |
| --- | --- |
| Fixture/case manager | Prepare source snapshots, revisions, immutable baseline, and private workspace paths. |
| Trusted collectors | Capture source/diff/test output and human reports through registered observer handles. |
| Agent adapter | Convert evidence and feedback into a Claim statement and an optional patch proposal. |
| Proposal validator | Resolve evidence aliases, construct canonical records, enforce target/patch limits, and bind the exact baseline. |
| Docker verifier | Test exact candidate bytes with trusted tests and produce trusted results. |
| Investigation coordinator | Run bounded rounds, accept a human hint, record feedback, and select the final proposal. |
| Existing runtime | Store provenance, derive status, enforce verification and authority, and record the local effect. |
| Reporter | Present friendly record names, reasoning summaries, test outcomes, and why an action was accepted/refused. |

The model receives evidence aliases and data, not trusted handles or the database path. Producer IDs, timestamps, canonical hashes, Authority, Verification, and control records are created by the host. Evidence selection is model-proposed, but every selected alias must resolve to an Observation actually supplied in that reasoning round.

Keep the coordinator, provider adapter, fixture, collectors, verifier, and reporter in a distinct example-client package. The CLI delegates to that client; the core format, graph rules, store, and runtime do not import an agent provider or the Docker runner.

Codex runs in a generated proposal workspace containing only supplied case material. Configure proposal-only operation: disable model-accessible shell execution, apps/connectors, plugins/hooks, browsing/computer use, and subagent creation, and do not load the user's optional tool configuration. Retain normal login handling through the CLI itself. The installed feature switches must be checked during adapter preflight; an unsupported or ineffective restriction is an adapter-unavailable error. Structured text is sufficient because collectors supply the inputs.

No authentication file is read or copied by the application. The CLI uses its normal authentication mechanism. Its schema constrains the final response shape, and the host independently validates that response before constructing records ([developer command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)).

## Agent input and output

An input packet contains the investigation question, fixture contract, observation aliases with payloads/source references, currently usable evidence, prior claim/proposal summaries, and new human/checker feedback. The first round contains no later human hint.

The response has exactly these fields:

- `claim_statement`: nonempty text containing the interpretation or current uncertainty.
- `evidence_aliases`: a nonempty list of distinct supplied Observation aliases.
- `patch_content`: full replacement UTF-8 text for `src/clamp.py`, or null when there is insufficient evidence to propose work.
- `summary`: a short user-facing explanation of what changed or remains unresolved. This is a supplied reasoning summary, not a capture of internal model chain of thought.

Use a strict JSON schema with all fields required and no additional properties. Reject model-created IDs, verification results, authority declarations, unknown aliases, unsupported values, and oversize responses. Limit claim/summary fields to 4,000 characters each, patch content to 8,000 UTF-8 bytes, and captured adapter output to 1 MiB.

Create a Claim from `claim_statement` and the resolved evidence. If a patch is supplied, create a ProposedAction of the existing `repo.repair.simulated` type, with a fixture-specific resource and arguments containing the immutable baseline snapshot hash, target path, original file hash, and exact normalized candidate content. Normalize candidate text to UTF-8/LF before hashing and testing; retain the original source byte hash. Every verification binds to this complete action ID.

## Investigation flow

1. Preflight the CLI/login, Docker engine/image, and private case paths before consuming model usage.
2. Collect real baseline source, revision/diff, and failing-test Observations. A baseline expected to fail must actually fail the trusted regression test.
3. Call the agent and record its Claim and optional ProposedAction. With no proposal, report the unresolved result rather than manufacture a patch.
4. If a human hint is provided, capture it as an Observation of what the person reported, refresh the fixed source/diff collectors, and call the agent again with that new evidence. A hint is neither an automatic factual verdict nor authorization.
5. Test the selected exact candidate in fresh container runs for `targeted_tests` and `full_suite`. Failed results become Observations and Verification records; they can inform another reasoning round within the budget.
6. For a passing proposal, issue scoped local Authority through the trusted issuer for that exact action and fixture resource, expiring 15 minutes after issuance. The host's policy permits only the controlled fixture's simulated acceptance.
7. Call the existing gate and emit the receipt or refusal reason. The accepted consequence remains a SQLite receipt plus reconstructible patch data; no live repository or remote PR is changed.

Default maximum: three agent invocations, 180 seconds per invocation, 30 seconds per container test run. This bounds invocations and time, not exact token spending. Explicitly invoking the live backend consumes the existing account's normal model usage. No live model call occurs in the ordinary unit suite.

A later claim may confirm the same diagnosis or change it; do not require a model to change its conclusion merely because a human spoke. When a revised claim replaces an earlier one, construct it from its own Observation evidence and append Supersession. Do not make the replacement causally depend on the old Claim, which the existing grammar forbids for supersession.

## Collaborative correction scenario

Provide an additional controlled `stale-source` scenario. Its first source collector captures real code from an earlier fixture revision, while the failing test is from the current revision. Label the captured revision/hash honestly. The scenario represents a collector using an unsuitable source snapshot for the investigation.

A human hint asks the investigator to check the source revision. The host obtains the current source and captures the revision/hash mismatch as new evidence. Its trusted controller declares the earlier case-specific snapshot unusable. A claim/proposal that selected that snapshot becomes STALE and the gate must refuse it, even if a candidate happens to pass tests.

The second reasoning round receives the hint and fresh source data with the old snapshot excluded from usable evidence. It creates a new claim/proposal without the invalidated dependency. Both interpretations remain recorded. If the first model supplies no proposal, retain its Claim and demonstrate the dependent-action denial through a deterministic adapter regression; do not claim the live model proposed an action it did not produce.

This separates two assertions: deterministic tests prove the stale-action contract; the live run proves that the model can consume actual evidence, contribute a proposal, and receive human feedback. Report each independently.

## Verification execution

Mount only the candidate case snapshot and trusted runner/tests into the container, read-only. Use a read-only root filesystem, no network, an unprivileged user, dropped capabilities, no-new-privileges, one CPU, 256 MiB memory, a 64-process limit, and a small private temporary filesystem. Do not mount the Docker socket, user's home, repository credentials, runtime DB, or authority metadata.

The static pure-function profile prevents the candidate from modifying or impersonating the in-process checker. Docker additionally bounds where code can run. The trusted runner requires a positive test count and records exit status, counts, stdout/stderr digests, and timeout/infrastructure failures. A timeout, malformed result, zero tests, or sandbox error cannot become a passing Verification.

The allowed file contains only an optional module docstring and one `clamp` function with the exact three named parameters, optional `int` annotations, and no defaults/decorators. Its body uses returns and conditionals over those integer parameters, bounded integer constants, comparisons, Boolean expressions, and `min`/`max` calls. Local/global assignment, attribute access, indexing, comprehensions, power operations, and references to other names are rejected. Limit the parsed tree to 200 nodes and constants to the range -1,000,000 through 1,000,000. The trusted tests supply ordinary bounded integers.

Resolve `python:3.12-slim` to a local image ID during setup and use that exact ID for every baseline/candidate run in the case. Record it so a changing image tag cannot silently alter the verifier environment.

Record the actual resolved image ID, runner/test hashes, original/candidate snapshot hashes, selected suite, integer elapsed milliseconds, and result in supporting Observations. Recheck that the candidate tested is the same bytes named by the ProposedAction and that the baseline is still the captured immutable baseline before authority/commit.

Give each container a case-owned unique name. On timeout/interruption, stop and remove only that container and preserve recorded history. Never execute candidate Python on the host as a fallback.

## CLI and outputs

Proposed command:

```shell
python -m provenance investigate --agent codex --case-dir ./work/case-1
python -m provenance investigate --agent codex --scenario stale-source --case-dir ./work/case-2 --hint "Check whether the source snapshot is from the current revision."
```

`--case-dir` must be new; refuse overwriting a prior case. `--model` optionally selects the CLI model. A recorded-response backend is available only as an explicitly labeled testing/replay mode and must never be reported as a live model run.

Default output is readable text/Markdown: sources captured, first interpretation, human contribution, later interpretation, proposed diff, test results, admission/refusal, and friendly provenance references. `--json` exposes the machine-readable report. Save the SQLite graph, input/output evidence packets, source snapshots, proposed diffs, test artifacts, and reports beneath the case directory. Credentials and internal model reasoning are excluded.

Reports distinguish CLAIMED, TESTED, ACCEPTED, and REFUSED. A passing patch test demonstrates behavior under the supplied tests; it does not establish a causal claim as universally true. On failure, retain partial evidence and a precise error stage rather than describing the investigation as successful.

## Acceptance evidence

- Real baseline test failure and unchanged fixture tests/source outside the allowed candidate file.
- Live Codex returns an admissible structured Claim/proposal; a correct candidate is independently tested and receives one local receipt.
- Deterministic wrong candidate fails actual tests and creates no Effect.
- Wrong source/action hash, forged verification/authority fields, unknown aliases, forbidden edits/syntax, empty tests, timeout, and missing sandbox deny progress or admission.
- Human input is recorded after the first round and supplied to the next; prior records are retained.
- Stale-source detection invalidates the case-specific input; a dependent proposal is refused; a fresh independent proposal can be tested and admitted.
- Retry of an accepted exact action still returns the existing receipt; the original 0.1 golden vectors and existing suite remain valid.
- Ordinary tests use recorded adapter responses; explicit container integration tests run actual candidate code, and an explicit live smoke run supplies separate evidence of the real agent connection.

## Deferred work and review handoff

Background polling, chat UI, arbitrary repository support, deployment/PR effects, scheduling, vector retrieval, general tool selection, and provider optimization remain deferred. No new record kind, canonical schema version, or existing effect-gate contract is needed for this integration.

After written-spec approval, create the test-first implementation plan and preserve the user's previous Native execution preference unless changed. Implement on an isolated feature workspace, then perform one independent whole-project review. This draft itself has not run a live agent or any proposed code.
