"""A bounded example application using the unchanged provenance runtime."""
import difflib
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ... import Store, Runtime, Policy, ProvenanceError, status, why
from ...format import canonical_json
from .case import (Evidence, TARGET, TEST_PATH, prepare_case, capture_snapshot, collect_source,
                   collect_diff, candidate_snapshot, digest, safe_path, _git)
from .contract import AgentRequest, admit_decision, validate_patch
from .errors import InvestigationError, fail
from .verifier import record_test


@dataclass(frozen=True)
class InvestigationOptions:
    case_dir: Path
    scenario: str = 'normal'
    hint: str | None = None
    max_rounds: int = 3


@dataclass
class InvestigationReport:
    outcome: str
    backend: str
    live_agent: bool
    case_dir: str
    scenario: str
    rounds: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    tests: list = field(default_factory=list)
    claim_id: str | None = None
    action_id: str | None = None
    effect_id: str | None = None
    authority_id: str | None = None
    old_action: dict | None = None
    human_hint: str | None = None
    sources: list = field(default_factory=list)
    error: dict | None = None
    reason: str = ''
    trace: dict | None = None

    def as_dict(self): return asdict(self)


def fixture_policy():
    return Policy('repair-client-v1', 'repair-client', ('collector', 'human'),
                  {'tester': ('targeted_tests', 'full_suite')}, ('issuer',), ('controller',),
                  {'repo.repair.simulated': ('targeted_tests', 'full_suite')})


def _validate_options(options):
    if (options.scenario not in ('normal', 'stale-source') or type(options.max_rounds) is not int
            or not 1 <= options.max_rounds <= 3):
        fail('OPTIONS', 'options', 'known scenario and one to three rounds are required')
    if options.hint is not None and (type(options.hint) is not str or not options.hint.strip() or len(options.hint) > 4000):
        fail('OPTIONS', 'options', 'human hint must be nonempty text of at most 4,000 characters')
    if options.scenario == 'stale-source' and options.hint is None:
        fail('OPTIONS', 'options', 'stale-source requires a human revision-check hint')
    if options.hint is not None and options.max_rounds < 2:
        fail('OPTIONS', 'options', 'a human contribution requires at least two rounds')
    path = Path(options.case_dir).absolute()
    safe_path(path.parent, path.name)
    if path.exists(): fail('CASE_EXISTS', 'options', 'case directory must be new; existing data was preserved')


def _baseline_unchanged(case, baseline):
    revision = _git(case.repository, 'rev-parse', 'HEAD').decode().strip()
    current = capture_snapshot(case, revision)
    if current.snapshot_hash != baseline.snapshot_hash or any(safe_path(case.repository, name).read_bytes() != data for name, data in baseline.files.items()):
        fail('BASELINE_CHANGED', 'verify', 'the captured baseline or current fixture files changed')


def run_investigation(options, agent, verifier):
    report = InvestigationReport('UNRESOLVED', agent.backend, agent.live, str(Path(options.case_dir).absolute()), options.scenario)
    case, store = None, None
    try:
        _validate_options(options)
        verifier.preflight()
        agent.preflight()
        case = prepare_case(Path(options.case_dir))
        store = Store(case.database)
        runtime = Runtime(store, fixture_policy(), lambda: datetime.now(timezone.utc))
        observer, human = runtime.observer('collector'), runtime.observer('human')
        tester, issuer, controller = runtime.verifier('tester'), runtime.issuer('issuer'), runtime.controller('controller')
        baseline = capture_snapshot(case, case.baseline_revision)
        evidence = []

        def add(item):
            evidence.append(item)
            report.evidence[item.alias] = item.node_id
            if 'revision' in item.payload and 'source_text' in item.payload:
                report.sources.append({'alias': item.alias, 'revision': item.payload['revision'], 'snapshot_hash': item.payload['snapshot_hash']})
            return item

        source = add(collect_source(runtime, observer, case,
                                   case.good_revision if options.scenario == 'stale-source' else case.baseline_revision, 'source'))
        add(collect_diff(runtime, observer, case, case.good_revision, case.baseline_revision, 'change'))
        baseline_result = verifier.test(baseline, case, 'targeted_tests')
        baseline_payload = baseline_result.payload()
        baseline_payload.update(case_id=case.case_id, revision=case.baseline_revision, phase='baseline')
        baseline_id = runtime.observe(observer, baseline_payload)
        add(Evidence('baseline_failure', baseline_id, store.get(baseline_id).payload))
        report.tests.append(dict(baseline_payload))
        if (baseline_result.outcome != 'fail' or baseline_result.returncode != 1 or baseline_result.tests_run != 1
                or baseline_result.failures != 1 or baseline_result.errors != 0
                or baseline_result.snapshot_hash != baseline.snapshot_hash
                or baseline_result.candidate_hash != baseline.file_hashes[TARGET]):
            fail('BASELINE_RESULT', 'baseline', 'trusted baseline regression did not produce the expected real test failure')
        history = []
        previous_claim = None

        def verify_action(action_id, round_index):
            _baseline_unchanged(case, baseline)
            action = store.get(action_id)
            args = action.payload['arguments']
            candidate = candidate_snapshot(baseline, validate_patch(args['patch_content']))
            if (args['baseline_snapshot'] != baseline.snapshot_hash or args['candidate_snapshot'] != candidate.snapshot_hash
                    or args['original_file_hash'] != baseline.file_hashes[TARGET] or args['target_path'] != TARGET):
                fail('ACTION_BINDING', 'verify', 'action does not name the immutable baseline and exact candidate')
            verification_ids, passed = [], True
            for suite in ('targeted_tests', 'full_suite'):
                result = verifier.test(candidate, case, suite)
                artifact = f'artifacts/round-{round_index}-{suite}.json'
                safe_path(case.root, artifact).write_bytes(canonical_json(result.payload()))
                observation_id, verification_id = record_test(runtime, observer, tester, action_id, result, {'result': artifact})
                add(Evidence(f'round_{round_index}_{suite}', observation_id, store.get(observation_id).payload))
                report.tests.append(dict(phase=f'round-{round_index}', action_id=action_id,
                                         observation_id=observation_id, verification_id=verification_id, **result.payload()))
                verification_ids.append(verification_id)
                passed = passed and result.passed
                if result.outcome == 'infrastructure_error':
                    fail('TEST_INFRASTRUCTURE', 'verify', 'restricted container did not produce a usable test result')
            _baseline_unchanged(case, baseline)
            authority_id = runtime.authorize(issuer, action_id, True, runtime.clock() + timedelta(minutes=15)) if passed else None
            return tuple(verification_ids), authority_id

        for index in range(1, options.max_rounds + 1):
            usable = tuple(e for e in evidence if status(store, e.node_id, 'execution') == 'VALID')
            request = AgentRequest('Investigate the clamp regression and propose a justified repair.',
                                   'For ordinary integers with lower <= upper, clamp returns an int between the bounds, preserving values already within them.',
                                   usable, tuple(history), index)
            run = agent.propose(request, case.agent_view / f'round-{index}')
            if run.backend != agent.backend or run.live is not agent.live:
                fail('AGENT_PROTOCOL', 'agent', 'provider identity is assigned by the host adapter')
            claim_id, action_id = admit_decision(runtime, case, baseline, request, run)
            report.claim_id, report.action_id = claim_id, action_id
            row = {'round': index, 'claim_id': claim_id, 'action_id': action_id, **run.decision.as_dict()}
            report.rounds.append(row)
            if previous_claim is not None:
                runtime.supersede(controller, previous_claim, claim_id, 'Later reasoning round uses its own current observations')
            previous_claim = claim_id
            history.append(dict(round=index, summary=run.decision.summary, claim_statement=run.decision.claim_statement,
                                proposal_status=store.get(claim_id).payload['proposal_status']))
            if action_id:
                candidate_text = store.get(action_id).payload['arguments']['patch_content']
                diff = ''.join(difflib.unified_diff(baseline.files[TARGET].decode().splitlines(True), candidate_text.splitlines(True),
                                                   fromfile='a/' + TARGET, tofile='b/' + TARGET))
                patch_path = f'artifacts/round-{index}.patch'
                safe_path(case.root, patch_path).write_text(diff, encoding='utf-8', newline='\n')
                row['diff'], row['patch_artifact'] = diff, patch_path

            if index == 1 and options.hint is not None:
                report.human_hint = options.hint
                hint_id = runtime.observe(human, {'case_id': case.case_id, 'reported_statement': options.hint,
                                                 'source': 'human-report', 'verified_cause': False})
                add(Evidence('human_hint', hint_id, store.get(hint_id).payload))
                _baseline_unchanged(case, baseline)
                current = add(collect_source(runtime, observer, case, case.baseline_revision, 'source_current'))
                add(collect_diff(runtime, observer, case, case.good_revision, case.baseline_revision, 'change_refreshed'))
                mismatch = source.payload['revision'] != current.payload['revision'] or source.payload['snapshot_hash'] != current.payload['snapshot_hash']
                if mismatch:
                    mismatch_id = runtime.observe(observer, {'case_id': case.case_id, 'source': 'measured-revision-comparison',
                        'earlier_revision': source.payload['revision'], 'current_revision': current.payload['revision'],
                        'earlier_hash': source.payload['snapshot_hash'], 'current_hash': current.payload['snapshot_hash'], 'mismatch': True})
                    add(Evidence('source_mismatch', mismatch_id, store.get(mismatch_id).payload))
                    runtime.invalidate(controller, source.node_id, 'Measured source revision/hash differs from the failing baseline')
                report.old_action = {'action_id': action_id, 'status': status(store, action_id, 'execution') if action_id else None,
                                     'gate_outcome': 'HELD' if action_id else 'NO_PROPOSAL', 'used_old_source': 'source' in run.decision.evidence_aliases}
                if action_id and mismatch and report.old_action['status'] == 'STALE':
                    verification_ids, authority_id = verify_action(action_id, index)
                    try:
                        runtime.commit(action_id, verification_ids, authority_id)
                        fail('STALE_ACCEPTED', 'gate', 'stale action unexpectedly reached an effect')
                    except ProvenanceError as error:
                        report.old_action.update(gate_outcome='REFUSED', code=error.problem.code, reason=error.problem.detail)
                        if error.problem.code != 'STALE': raise
                continue
            if action_id is None:
                report.outcome = 'UNRESOLVED'
                report.reason = 'The agent supplied no changed candidate to verify.'
                break
            verification_ids, authority_id = verify_action(action_id, index)
            report.authority_id = authority_id
            try:
                result = runtime.commit(action_id, verification_ids, authority_id)
            except ProvenanceError as error:
                report.outcome, report.reason = 'REFUSED', error.problem.detail
                row['gate_code'] = error.problem.code
                history[-1]['test_feedback'] = [{'suite': test['suite'], 'outcome': test['outcome'],
                                                 'failures': test['failures'], 'errors': test['errors']}
                                                for test in report.tests if test.get('action_id') == action_id]
                continue
            report.effect_id, report.outcome = result.effect_id, 'ACCEPTED'
            report.reason = 'Both trusted test suites passed for this exact candidate; matching local authority admitted one simulated repair receipt.'
            trace = why(store, result.effect_id, 'execution')
            report.trace = {'status': trace.statuses[result.effect_id], 'records': [n.id for n in trace.nodes], 'statuses': trace.statuses}
            break
    except (InvestigationError, ProvenanceError, OSError, sqlite3.Error) as error:
        if isinstance(error, InvestigationError): detail = dict(code=error.code, stage=error.stage, detail=error.detail)
        elif isinstance(error, ProvenanceError): detail = dict(code=error.problem.code, stage='records', detail=error.problem.detail)
        else: detail = dict(code='IO_ERROR', stage='io', detail=str(error)[:2000])
        report.outcome, report.error, report.reason = 'ERROR', detail, detail['detail']
        if case: (case.root / 'error.json').write_bytes(canonical_json(detail))
    finally:
        if store: store.close()
        if case: (case.root / 'report.json').write_bytes(canonical_json(report.as_dict()))
    return report
