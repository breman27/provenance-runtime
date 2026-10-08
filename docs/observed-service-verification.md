# Observed service verification — October 7, 2026

Implemented the autonomous sensor-service benchmark on macOS with Python 3.12.10 and Docker Linux containers. The pinned image used in the saved replay was `sha256:ce9a404c2c0138e747a43e6ea022d2f7e670ed868df35d627a663ba7fb940ea9`.

- Full unit suite: 153 tests passed, including the existing 135 tests and 18 new checks.
- Docker acceptance suite: all seven tests passed. After the final raw-log/hash and request-binding changes, the two new Docker tests were rerun in the permanent repository and passed.
- Saved regression CLI replay: `work/service-replay-regression-20261007`, ACCEPTED, five recorded tool steps, 15 intact graph records, one Effect with complete VALID receipt ancestry.
- Saved healthy CLI replay: `work/service-replay-healthy-20261007`, HEALTHY, four recorded tool steps, seven intact graph records, no ProposedAction or Effect.
- Reopened both graphs from read-only database backups; every stored record validated. Saved stdout log bytes matched each Observation's stdout hash.
- Normal working outputs: `12, 0, 50, 100, 100, 100`. Changed deployment outputs: `12, 0, 50, 100, 125, 200`.
- The service ran successfully before the source change was committed. Current-deployment targeted/full tests failed. The proposed candidate subsequently passed one targeted test and eight full-suite tests in independent containers.
- Model transport tests confirm strict named function calls, no parallel tools, no stored API state, rejection of unknown/multiple/incomplete tool calls, duplicate function-argument rejection, and continued rejection of tools by the original proposal-only client.
- Admission tests cover missed regressions, false alarms, healthy controls, wrong candidates, required current observations, existing-case preservation, step exhaustion, changing deployed source during a model turn, and idempotent receipt retry.
- The Claim's input hash binds the actual saved final tool request, and model-selected evidence aliases bind its Observation parents.

## Live-model status

Both saved native-function benchmark cases passed with live API reasoning: `work/service-healthy-20261007-192638-80868` reported HEALTHY without an action/effect, and `work/service-regression-20261007-192638-80868` reported ACCEPTED with one verified repair receipt. Their graphs were validated while refreshing the record-based reports.

The subsequent [interactive watcher run](live-service-watch.md) proved chat-driven edits against a running collector and live API agent: baseline plus two good edits stayed healthy, and a real breaking edit was detected and independently repaired in a proposal. Its four investigations used different model-selected tool sequences. This is separate from the deterministic replay checks above.

All saved local reports now use the [shared record-based format](reporting.md). Their record snapshots were derived from read-only database backups; immutable graph records and original model input packets were preserved.
