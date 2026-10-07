# Demo report, in plain English

This view comes from the [matching raw JSON](demo-report.json). Friendly names are display aliases; the underlying record IDs and bodies are unchanged.

The example manually supplies inputs for a fictional repo repair. Its effect is a SQLite receipt. The named verification results are fixture inputs, separate from the automated tests of the runtime.

## Recorded outcome

| Question | Result |
| --- | --- |
| Was the initial proposal usable? | `VALID` |
| How many effects were recorded? | `1` |
| Did retry return the original receipt? | `True` |
| What is the original proposal status afterward? | `STALE` |
| Does the historical effect still exist? | `True` |
| What is its current justification status? | `STALE` |
| Why was the new dependent action denied? | `STALE` |

## Original effect and the records supporting it

These statuses are from the end of the example, after the code-change observation was invalidated. The effect was admitted earlier, while its justification was usable.

| Name | Record kind | What it says | Parent names and roles | Current status |
| --- | --- | --- | --- | --- |
| `failure` | Observation | auth_refresh_test failed | None | `VALID` |
| `code_change` | Observation | code changed in abc123 | None | `INVALID` |
| `root_cause` | Claim | abc123 introduced the regression | evidence: failure, evidence: code_change | `STALE` |
| `action` | ProposedAction | Request repo.repair.simulated on fixture:repo: replace expired auth state | justification: root_cause | `STALE` |
| `authority` | Authority | Permit that action for fixture:runtime on fixture:repo | subject: action | `STALE` |
| `full_suite` | Verification | full_suite reported PASS for the original action | subject: action | `STALE` |
| `targeted_tests` | Verification | targeted_tests reported PASS for the original action | subject: action | `STALE` |
| `effect` | Effect | Runtime recorded one simulated repair receipt | action: action, authority: authority, verification: full_suite, verification: targeted_tests | `STALE` |

A Verification can retain its recorded PASS result while its supporting justification becomes STALE. The result and the current status answer different questions.

## The later change

An **Invalidation** targets `code_change`. Reason: “code-change observation came from a faulty collector.”

The original record and receipt stay stored. Their current statuses are derived from this appended declaration.

## The refused follow-up

The fixture proposes another repair using the same root-cause Claim, supplies new passing checks and authority, and calls the gate again. Its dependency on invalidated evidence causes the `STALE` denial. There is still one effect.

`why.nodes` explains the first effect. The later denied proposal and its new prerequisites are separate records in the database; they do not belong to that first effect’s justification.

For every report field and one complete record example, read [The demo, explained](../docs/demo-walkthrough.md). For the general model and complete field meanings, read [Concepts and terminology](../docs/concepts.md).
