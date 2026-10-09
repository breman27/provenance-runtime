# Human authority verification — October 9, 2026

The approved [design](superpowers/specs/2026-10-09-human-authority-workflow-design.md) and [plan](superpowers/plans/2026-10-09-human-authority-workflow-plan.md) were implemented natively in an isolated branch from `main` at `30d5380`. The workflow uses no new dependency, core kind, required payload or parent role. The compatible optional decision field and receipt inspection remain canonical format 0.1. Effects remain `repo.repair.simulated` receipts.

## Verification evidence

Windows, Python 3.12.14, ordinary default text encoding, Linux Docker engine:

| Check | Observed result |
| --- | --- |
| Fresh preimplementation unit baseline | 174 passed. |
| Core metadata/receipt + runtime/gate/format compatibility | 48 passed; old omitted-metadata bodies and golden vectors remain compatible. |
| Session/real Windows junction/OS-lock checks | 12 passed; foreign/missing/empty DBs preserved; contention and killed-process release proved. |
| Context/resource/service checks | 38 passed, including exact source/candidate/proof binding and cold direct freshness. |
| Decision/context/core/gate checks | 54 passed, including expiry equality, explicit renewal, rollback, denial/revocation and interrupted controls. |
| Manual/auto clients and existing watch/report/CLI checks | 50 passed. |
| Operator CLI and existing reports/service checks | 44 passed. |
| Fresh-process recovery/concurrent operator checks | 5 passed; four concurrent approvals/admissions yielded one grant and one Effect. |
| Full unit suite after mapping-integrity repair | 232 passed in 167.045 seconds. |
| Full actual Docker suite after mapping-integrity repair | 12 passed in 150.052 seconds; no skips. |
| Additional source-refusal report regression and CLI checks | 7 passed in 11.569 seconds. |
| Final full unit suite including report refresh | 233 passed in 233.921 seconds. |

Run the suites with:

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s integration_tests -v
```

Candidate checks in Docker use the existing pinned image, restricted UID, no network, read-only mounts/root, dropped capabilities and bounded resource/process execution. The new Docker cases prove manual waiting without Authority/Effect, later scoped approval/admission/retry, denial, source-change refusal despite passing original checks, continued watcher collection/queue recovery after stop, and explicit auto compatibility. Existing eight integration checks remain present.

Cold processes disable provider modules and remove the process key variable. Separate processes approve and admit, validate every graph record and the complete receipt ancestry, and retry the same receipt. Test-only process termination occurs after denial before invalidation, after invalidation before supersession, and during renewal; reconciliation creates no recovery Effect. Production code contains no crash hook.

Negative checks cover altered/imported/conflicting contexts, missing/redirected artifacts, invalid source bytes, wrong resources/subjects/hash/count/image proofs, imported supporting evidence/grants/Effects, invalid TTL/reason, changed active-approval inputs, conflicting decision sequences, corruption and lost retry mappings. Receipt integrity repair was driven by two failing regressions before implementation; source-refusal report refresh likewise failed first. Operator/model boundaries are tested separately from canonical integrity and justification status.

## Limits and trust

This milestone performs no paid/live model run: the provider contract is unchanged and the new behavior is the local decision lifecycle. Actual candidate/service execution was proved with recorded bounded decisions and Docker. Ordinary tests use verifier doubles for deterministic graph/resource tests; they are not claimed as Docker execution.

Windows OS locking and real junction rejection were exercised. The POSIX `fcntl`/symlink branches were implemented but were not run on a POSIX host during this milestone. Clock rollback cannot reorder decisions; expiry still follows the configured host wall clock. Physical probes observe source freshness and do not atomically freeze an external resource.

The bounded API model has no approval/control/DB tools. The operator role is an audit label, not authenticated human identity. Same-user shell code and DB writers remain trusted; a general shell agent requires OS/service isolation and an authenticated operator channel. Real source mutation and its credential/recovery integration remain future work. Private cases and API credentials are excluded from publication.
