# Continue on another computer

The project is in [breman27/provenance-runtime](https://github.com/breman27/provenance-runtime). The October 9 milestone adds a durable [human authority workflow](human-authority.md); its [verification record](human-authority-verification.md) records final checks and review. The October 7 integration results below remain historical evidence.

## Get the code

```sh
git clone https://github.com/breman27/provenance-runtime.git
cd provenance-runtime
```

For an existing clone, switch to `main` and run `git pull --ff-only` after preserving any local changes.

## Set up and check

Use Python 3.12 or later, Git, and a running Linux Docker engine with its CLI. No Python packages need installing. Configure `OPENAI_API_KEY` locally using the [OpenAI quickstart](https://developers.openai.com/api/docs/quickstart). On Windows the client can read the key from your user environment; on other systems export it in the process environment. The key must allow model lookup and Responses creation. API calls use API billing.

```sh
python -m unittest discover -s tests
python -m unittest discover -s integration_tests -v
python -m provenance investigate --agent openai --case-dir ./work/new-normal
python -m provenance investigate --agent openai --scenario stale-source --case-dir ./work/new-correction --hint "Check whether the source snapshot is from the current revision."
```

Ordinary unit tests do not invoke Docker or a model. The integration suite runs real Docker containers. The last two commands make paid model calls and require fresh case paths. OpenAI defaults to `gpt-4.1-mini`; `--model` can select a model supporting Responses and strict structured output. No tools are exposed to the model.

The API key and private `work/` case databases/reports are excluded from Git and will not appear in the new clone. The committed verification record preserves the results of the original live runs. Create new cases to reproduce them; transfer old private case folders separately if you need their original graphs.

## Historical October 7 integration state

- All 135 unit tests and five real Docker integration tests passed.
- Two actual OpenAI scenarios passed, using `gpt-4.1-mini-2025-04-14` across three model calls.
- The normal case received one verified, authorized simulated receipt.
- In the correction case, the first candidate passed its tests but was refused with `STALE` because its Claim depended on an invalid source Observation. A supplied human hint and fresh source supported a later Claim; that independently tested proposal received the only receipt in the case.
- Both graphs were reopened: receipt ancestry validated and exact-action retries reused the original receipts.
- The runtime core and canonical format remain unchanged. Real source edits, Git commits, remote PR creation, background monitoring, and a chat UI are outside this example client's effects. `Runtime.commit` records a simulated SQLite receipt.
- The optional Codex CLI backend stays fail-closed because the installed CLI did not honor one execution restriction. The OpenAI API backend completed the live milestone.

## Current authority milestone and next work

The [October 9 cleanup](portable-service-cleanup.md) fixes Windows service-report encoding, makes redirected-source checks portable, and closes the previously deferred duplicate/contradictory API-envelope validation issue.

New observed-service/watcher CLI sessions default to manual approval. Verified proposals wait without Authority/Effect; separate operator commands list, inspect, approve, deny, renew, revoke and admit. The queue survives stopping the watcher, operators make no model calls, and collection continues while decisions wait. Original fixture clients and omitted programmatic modes retain automatic behavior. Private approval sessions bind host paths; create fresh cases on another computer rather than assuming that transferred sessions can be rebound.

The next substantial milestone is a trusted executor for a real bounded effect, with an atomic source-version check and recovery/idempotency around that mutation. First try the recorded/Docker manual walkthrough, assess the operator reports, and choose the exact real consequence to permit. A shell-capable agent needs separate OS/service identity and protected issuer/database/effect credentials; the bounded API model currently has only investigation tools. No general IAM, remote approval service or real source write has been added.

Start a new coding chat in this repository with: “Read `docs/continue-on-another-computer.md` and continue provenance-runtime from that handoff.”

Useful context: [client walkthrough](agent-investigation.md), [verification and review record](agent-investigation-verification.md), [concepts](concepts.md), and the approved [design](superpowers/specs/2026-10-07-agent-investigation-design.md)/[plan](superpowers/plans/2026-10-07-agent-investigation-plan.md).
