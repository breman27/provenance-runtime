# Human authority execution record

Approved Native execution: one implementer, one independent final reviewer, and one test-first review fix pass. Final code fixes are committed at `ee7a26e`. The final unit suite passed 237 tests and the actual Docker suite passed 12 tests, with no skips. Private cases and model credentials remain excluded from Git.

| Task | Delivered commit |
| --- | --- |
| 1: compatible metadata/receipt inspection | d7352b2 |
| 2: sessions/profiles/portable operator lock | 66dc4ad |
| 3: exact context/proofs/direct resource freshness | 8c2fbe3 |
| 4: decision lifecycle/reconciliation/admission | 4c519a8 |
| 5: manual service/watcher queue | 3a7c31b |
| 6: operator CLI/review reports | c5570a0 |
| 7: process/concurrency/Docker and receipt corruption checks | 9040307 |
| 8: source-refusal report, docs and final review fixes | bffef51, 6a0d82a, ee7a26e |

The original scratch ledgers follow. Some automated task-completion ranges were recorded before their subsequent commits; the delivery table above identifies the actual implementations. Test commands/results and every execution/review ruling are retained. Final review raised no deferred minors.

## Preflight ledger

# SDD ledger — plan: docs/superpowers/plans/2026-10-09-human-authority-workflow-plan.md

Approved Native execution. Base a4bf60b. No implementation delegates; one independent final reviewer.

## Preflight shared interfaces
| Producer | Consumers | Interface |
| --- | --- | --- |
| Task 1 | 4, 6, 7 | Runtime.authorize decision keyword; Runtime.local_receipt |
| Task 2 | 3–7 | ApprovalSession, fixed authority_policy, create/open_session, session_lock |
| Task 3 | 4–7 | ProposalContext, record/load_context, check_current |
| Task 4 | 5–7 | ApprovalManager operations; ApprovalResult.as_dict |
| Task 5 | 6, 7 | Manual queue persistence and explicit CLI defaults |
| Task 6 | 7, 8 | Authority CLI exit codes, typed permission reports |

Ruling: Native sequential implementation follows the approved plan — user selected Native — cost if wrong: slower execution without implementation parallelism.

Task 1 started at a4bf60b. Baseline suite in baseline.log.

## Completion and review ledger

# SDD ledger — plan: docs/superpowers/plans/2026-10-09-human-authority-workflow-plan.md
Preflight interface rows and initial Native ruling are in ledger.md beside this canonical completion ledger.
Baseline: 174 tests passed in 110.651s on Windows without forced UTF-8 mode.
Committed implementations: Task 1 d7352b2; Task 2 66dc4ad; Task 3 8c2fbe3; Task 4 4c519a8. Some completion-script ranges precede their subsequent commits; these explicit IDs identify the delivered ranges.
Ruling: Manual profile uses policy version observed-service-manual-v1 and fixed human-operator issuer — the plan's profile/version wording is ambiguous; separate policy snapshots make selected permission mode explicit — cost if wrong: consumers expecting the old policy version string must use the documented profile.
Ruling: Denial metadata uses ttl_minutes null and expiry at issuance — a denial remains the current decision regardless of its expiry — cost if wrong: clients must interpret permission by decision sequence and allowed flag, not expiry alone.
Task 7: Mapping-loss/imported-mapping regressions failed first, then core/gate 28 tests passed. Full suites rerun because gate changed.
Task 8: Documentation drafted while final Task 7 verification runs; no completion claim or review dispatch until results are read. Source-refusal report regression failed on absent partial state, then CLI 7 tests passed.
Final review: one fresh GPT-6 Astra reviewer of 30d5380..6a0d82a. Two Important defects reproduced, no Critical or Minor defects. Reviewer independently ran 42 targeted tests (69.912s), all passed; inspected Docker evidence without rerunning it.
Final fix pass: imported metadata/report failure regressions and historical-runner-update regression reproduced RED; fixes and 46 targeted tests GREEN (64.252s). Full post-fix unit suite 237/237 passed (179.900s); full actual Docker suite 12/12 passed (155.366s), no skips.
Final: fixed imported decision metadata/report crashes — test_imported_decision_metadata_stays_untrusted_and_cannot_crash_reports and test_json_inspection_and_persisted_results_survive_markdown_failure RED→GREEN, suite 237/237, Docker 12/12.
Final: fixed current verifier coupling of historical receipt/withdrawal — test_historical_receipt_and_withdrawal_survive_installed_verifier_update RED→GREEN, suite 237/237, Docker 12/12; new-permission compatibility regression remains green.
Committed delivery correction: Task 5 3a7c31b, Task 6 c5570a0, Task 7 9040307; source-refusal report correction bffef51; walkthrough/review evidence 6a0d82a; final independent-review fix pass ee7a26e. Completion-script ranges preceding subsequent commits are supplemented by these exact delivery IDs.
Final: Ruling: unrestricted same-user shell/DB writers remain trusted — the bounded API tool boundary prevents model self-approval; general execution needs separate identities — cost if wrong: a shell agent with operator privileges can grant itself permission.
Final: Ruling: source mutation after the last physical probe remains an observed-freshness limitation — only simulated receipts are executed; atomic version/mutation belongs to a real executor — cost if wrong: a late edit may escape that probe and a future real executor could act on outdated source.
Final: Ruling: latest-grant expiry follows configured wall time — decision sequences protect precedence, not elapsed time after clock rollback — cost if wrong: rollback can extend the apparent lifetime of the latest grant.
Final: Ruling: simultaneous loss of retry mapping and effect admission cannot establish former local execution — unadmitted graph history is indistinguishable from imports — cost if wrong: double metadata loss can defeat historical deduplication.
Final: Ruling: POSIX locking/symlink behavior remains unverified on a POSIX host — this run proved Windows locks/junctions and inspected the portable branch — cost if wrong: platform-specific behavior may fail until tested there.
Final: Ruling: real patches/deployment credentials/authenticated human identity remain deferred — this milestone delivers local audited permission for a simulated receipt — cost if wrong: a deployment expecting real execution/authentication still needs those integrations.
Final: Deferred minors: none raised.
Ruling: Inspect/list project recorded status; physical probes occur before approve/new admission — required probes stay explicit and receipt/history inspection works offline — cost if wrong: a displayed recorded APPROVED state can become unusable before the next physical probe; this is stated in each report.
Ruling: Preserve the user's standing commit/push preference after successful review instead of reasking the finishing-branch menu — approval already exists — cost if wrong: tested implementation is published under that existing authorization.
Task 1: complete (commits a4bf60b..a4bf60b, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_authority_core tests.test_runtime tests.test_gate tests.test_format -v → OK)
Task 2: complete (commits d7352b2..66dc4ad, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_authority_context tests.test_authority_lock tests.test_authority_core -v → OK)
Task 3: complete (commits 66dc4ad..66dc4ad, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_authority_context tests.test_authority_resources tests.test_observed_service -v → OK)
Task 4: complete (commits 8c2fbe3..8c2fbe3, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_authority_manager tests.test_authority_context tests.test_authority_core tests.test_gate -v → OK)
Task 5: complete (commits 4c519a8..4c519a8, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_authority_clients tests.test_observed_service tests.test_service_watch tests.test_reporting tests.test_investigation_cli -v → OK)
Task 6: complete (commits 3a7c31b..3a7c31b, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest tests.test_authority_cli tests.test_reporting tests.test_investigation_cli tests.test_observed_service -v → OK)
Task 7: complete (commits c5570a0..c5570a0, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest discover -s tests -v → OK)
Task 8: complete (commits c5570a0..6a0d82a, tests: C:/Users/bsema/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe -m unittest discover -s tests -v → OK)
