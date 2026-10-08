"""Working deployment -> real logs -> changed deployment -> autonomous tool loop."""
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ... import Store, Runtime, Policy, why, ProvenanceError
from ...format import canonical_json, parse_json
from ..repo_repair.case import (CasePaths, Evidence, GOOD_SOURCE, BAD_SOURCE, TEST_SOURCE,
    TARGET, TEST_PATH, _git, safe_path, capture_snapshot, collect_source, collect_diff,
    candidate_snapshot, digest, save_snapshot)
from ..repo_repair.contract import AgentRequest, AgentRun, decode_decision, admit_decision, validate_patch
from ..repo_repair.coordinator import unified_patch
from ..repo_repair.errors import InvestigationError, fail
from ..repo_repair.process import run_process
from ..repo_repair.verifier import DockerVerifier, record_test
from .agent import tools
from ..reporting import report_record_snapshot, render_investigation_report
from .service import READINGS

SERVICE_CONTRACT = '''# Sensor service

The service processes batches of integer sensor readings for a dashboard.
Outputs must stay between 0 and 100 inclusive. Inputs already in that interval
must be preserved. Values below 0 map to 0, and values above 100 map to 100.

Run `python service.py` to process one batch and emit one JSON log per reading.
The deployed implementation is `src/clamp.py`. Each collected run identifies
its immutable Git revision and the SHA-256 of the source actually executed.
'''


def service_policy():
    return Policy('observed-service-v1', 'observed-service', ('collector',),
                  {'tester': ('targeted_tests', 'full_suite')}, ('issuer',), ('controller',),
                  {'repo.repair.simulated': ('targeted_tests', 'full_suite')})


def prepare_service(root):
    root = Path(root).absolute()
    safe_path(root.parent, root.name)
    if root.exists():
        fail('CASE_EXISTS', 'options', 'Case must be new; existing data was preserved')
    for name in ('repository/src', 'repository/tests', 'artifacts', 'agent-view', 'logs'):
        safe_path(root, name).mkdir(parents=True, exist_ok=True)
    repo = root/'repository'
    safe_path(repo, TARGET).write_bytes(GOOD_SOURCE)
    safe_path(repo, TEST_PATH).write_bytes(TEST_SOURCE)
    safe_path(repo, 'service.py').write_bytes(Path(__file__).with_name('service.py').read_bytes())
    safe_path(repo, 'README.md').write_text(SERVICE_CONTRACT)
    _git(repo, 'init', '--initial-branch=service')
    _git(repo, 'config', 'core.autocrlf', 'false')
    _git(repo, 'config', 'user.name', 'Provenance service fixture')
    _git(repo, 'config', 'user.email', 'fixture@example.invalid')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'Deploy working sensor service')
    revision = _git(repo, 'rev-parse', 'HEAD').decode().strip()
    return CasePaths(root, repo, root/'artifacts', root/'agent-view', root/'history.db',
                     uuid.uuid4().hex, revision, revision)


def deploy_change(case):
    safe_path(case.repository, TARGET).write_bytes(BAD_SOURCE)
    _git(case.repository, 'add', TARGET)
    _git(case.repository, 'commit', '-m', 'Simplify sensor processing')
    revision = _git(case.repository, 'rev-parse', 'HEAD').decode().strip()
    return replace(case, baseline_revision=revision)


def baseline_unchanged(case, snapshot):
    current = _git(case.repository, 'rev-parse', 'HEAD').decode().strip()
    if current != snapshot.revision or capture_snapshot(case, current).snapshot_hash != snapshot.snapshot_hash:
        fail('BASELINE_CHANGED', 'verify', 'Deployment revision changed during investigation')
    for name, data in snapshot.files.items():
        if safe_path(case.repository, name).read_bytes() != data:
            fail('BASELINE_CHANGED', 'verify', 'Deployed source or tests changed during investigation')
    if safe_path(case.repository, 'service.py').read_bytes() != Path(__file__).with_name('service.py').read_bytes():
        fail('BASELINE_CHANGED', 'verify', 'Service entry point changed during investigation')
    if safe_path(case.repository, 'README.md').read_text() != SERVICE_CONTRACT:
        fail('BASELINE_CHANGED', 'verify', 'Service contract changed during investigation')


class ServiceVerifier(DockerVerifier):
    def run_service(self, snapshot, case, readings=READINGS, allow_failure=False):
        if not allow_failure:
            validate_patch(snapshot.files[TARGET].decode())
        if not 1 <= len(readings) <= 64 or any(type(v) is not int or abs(v) > 1000000 for v in readings):
            fail('SERVICE_INPUT', 'observe', 'Invalid service reading batch')
        if not self.image_id:
            fail('VERIFIER_CONFIG', 'observe', 'Docker preflight required')
        directory = save_snapshot(case, snapshot)
        trusted = safe_path(case.root, 'artifacts/service-runner')
        trusted.mkdir(exist_ok=True)
        runner = Path(__file__).with_name('service.py').read_bytes()
        safe_path(trusted, 'service.py').write_bytes(runner)
        name = 'provenance-' + case.case_id + '-' + uuid.uuid4().hex[:12]
        argv = (self.command, 'run', '--rm', '--name', name, '--network', 'none', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '65534:65534',
                '--cpus', '1', '--memory', '256m', '--pids-limit', '64', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                '--mount', f'type=bind,source={directory / "src"},target=/candidate,readonly',
                '--mount', f'type=bind,source={trusted},target=/trusted,readonly',
                self.image_id, 'python', '-I', '-B', '/trusted/service.py', '/candidate', snapshot.revision, canonical_json(list(readings)).decode())
        try:
            result = run_process(argv, case.root, timeout=30)
        finally:
            self._cleanup(case, name)
        if result.returncode or result.timed_out or result.output_exceeded:
            if allow_failure:
                return {'revision': snapshot.revision, 'snapshot_hash': snapshot.snapshot_hash,
                        'source_hash': snapshot.file_hashes[TARGET], 'image_id': self.image_id,
                        'runner_hash': digest(runner), 'entries': [], 'stdout_hash': digest(result.stdout),
                        'stdout': result.stdout.decode('utf-8', errors='replace'),
                        'stderr': result.stderr.decode('utf-8', errors='replace'), 'returncode': result.returncode,
                        'timed_out': result.timed_out, 'output_exceeded': result.output_exceeded,
                        'outcome': 'error', 'elapsed_ms': result.elapsed_ms, 'executor': 'docker-linux-restricted'}
            fail('SERVICE_RUN', 'observe', 'Restricted service run did not complete')
        entries = []
        for line in result.stdout.splitlines():
            entry = parse_json(line)
            fields = {'event', 'sequence', 'timestamp', 'revision', 'source_hash', 'input', 'lower', 'upper', 'output'}
            if (type(entry) is not dict or set(entry) != fields or entry['event'] != 'reading_processed'
                    or entry['revision'] != snapshot.revision or entry['source_hash'] != snapshot.file_hashes[TARGET]
                    or any(type(entry[k]) is not int for k in ('sequence', 'input', 'lower', 'upper', 'output'))
                    or type(entry['timestamp']) is not str):
                fail('SERVICE_LOG', 'observe', 'Service log failed revision/content validation')
            entries.append(entry)
        if (len(entries) != len(readings) or [e['sequence'] for e in entries] != list(range(len(readings)))
                or tuple(e['input'] for e in entries) != tuple(readings)
                or any((e['lower'], e['upper']) != (0, 100) for e in entries)):
            fail('SERVICE_LOG', 'observe', 'Service log is incomplete or has unexpected inputs')
        return {'revision': snapshot.revision, 'snapshot_hash': snapshot.snapshot_hash,
                'source_hash': snapshot.file_hashes[TARGET], 'image_id': self.image_id,
                'runner_hash': digest(runner), 'entries': entries, 'stdout_hash': digest(result.stdout),
                'outcome': 'ok', 'stdout': result.stdout.decode('utf-8'), 'elapsed_ms': result.elapsed_ms, 'executor': 'docker-linux-restricted'}


def render_report(report):
    mode = 'Live OpenAI function calls' if report['live_agent'] else 'Recorded tool replay; no live model call'
    return render_investigation_report(report, title='Observed service: '+report['outcome'], mode=mode)


def run_experiment(case_dir, agent, verifier, scenario='regression', max_steps=8, *, prepared=None, guard=None, on_step=None):
    root = Path(case_dir).absolute()
    report = {'outcome': 'UNRESOLVED', 'backend': agent.backend, 'live_agent': agent.live,
              'case_dir': str(root), 'scenario': scenario, 'service_runs': [], 'steps': [], 'tests': [],
              'evidence': {}, 'claim_id': None, 'action_id': None, 'authority_id': None,
              'effect_id': None, 'decision': None, 'reason': 'Step budget exhausted.', 'error': None}
    case, store = None, None
    try:
        if (scenario not in ('regression', 'healthy') and not (scenario == 'live' and prepared)) or type(max_steps) is not int or not 1 <= max_steps <= 12:
            fail('OPTIONS', 'options', 'Known scenario and one to twelve steps required')
        safe_path(root.parent, root.name)
        if prepared is None:
            if root.exists():
                fail('CASE_EXISTS', 'options', 'Case must be new; existing data was preserved')
            verifier.preflight()
            agent.preflight()
            case = prepare_service(root)
        else:
            case = prepared['case']
            if case.root != root:
                fail('CASE_PATH', 'options', 'Prepared case root differs from report root')
        store = Store(case.database)
        runtime = Runtime(store, service_policy(), lambda: datetime.now(timezone.utc))
        observer, tester, issuer = runtime.observer('collector'), runtime.verifier('tester'), runtime.issuer('issuer')
        offered = {}
        logs = []

        def observe(alias, payload, expose=True):
            node_id = runtime.observe(observer, payload)
            evidence = Evidence(alias, node_id, store.get(node_id).payload)
            report['evidence'][alias] = node_id
            if expose:
                offered[alias] = evidence
            return evidence

        def test_snapshot(snapshot, phase):
            results = []
            for suite in ('targeted_tests', 'full_suite'):
                result = verifier.test(snapshot, case, suite)
                if result.outcome not in ('pass', 'fail'):
                    fail('TEST_INFRASTRUCTURE', 'verify', 'Restricted tests returned no usable result')
                payload = dict(phase=phase, **result.payload())
                report['tests'].append(payload)
                results.append(result)
            return results

        def collect_logs(alias, snapshot):
            payload = verifier.run_service(snapshot, case)
            artifact = f'logs/{alias}.jsonl'
            log_bytes = payload['stdout'].encode('utf-8')
            if digest(log_bytes) != payload['stdout_hash']:
                fail('SERVICE_LOG', 'observe', 'Captured stdout does not match its digest')
            safe_path(case.root, artifact).write_bytes(log_bytes)
            payload['artifact'] = artifact
            logs.append(observe(alias, payload, expose=False))
            report['service_runs'].append({'alias': alias, 'revision': snapshot.revision,
                                          'outputs': [e['output'] for e in payload['entries']]})
            return payload

        if prepared is None:
            healthy = capture_snapshot(case, case.good_revision)
            if not all(r.passed for r in test_snapshot(healthy, 'before-deployment')):
                fail('HEALTHY_BASELINE', 'baseline', 'Initial service did not pass the trusted suites')
            collect_logs('logs_before', healthy)
            if scenario == 'regression':
                case = deploy_change(case)
            current = capture_snapshot(case, case.baseline_revision)
            current_logs = collect_logs('logs_current', current)
        else:
            current = prepared['snapshot']
            logs = prepared['logs']
            for evidence in logs:
                report['evidence'][evidence.alias] = evidence.node_id
                report['service_runs'].append({'alias': evidence.alias, 'revision': evidence.payload['revision'],
                    'outputs': [entry['output'] for entry in evidence.payload['entries']]})
            current_logs = logs[-1].payload
        # Evaluation-only oracle: never included in the initial question or tool output.
        changed_behavior = current_logs.get('outcome') == 'error' or any(e['output'] != max(0, min(e['input'], 100)) for e in current_logs['entries'])
        safe_path(case.root, 'case.json').write_bytes(canonical_json({'case_id': case.case_id,
            'earlier_revision': case.good_revision, 'current_revision': case.baseline_revision}))
        transcript = [{'role': 'user', 'content': 'Check whether the latest sensor-service deployment behaves according to its README. Use available tools to gather evidence and report your assessment.'}]
        def check_current():
            baseline_unchanged(case, current)
            if guard:
                guard()

        seen_calls = set()
        for index in range(1, max_steps + 1):
            check_current()
            directory = safe_path(case.root, f'agent-view/step-{index}')
            call, arguments, metadata = agent.step(transcript, tuple(offered), directory)
            check_current()
            name = call.get('name')
            if (name not in {t['name'] for t in tools()} or type(arguments) is not dict
                    or type(call.get('call_id')) is not str or call['call_id'] in seen_calls):
                fail('TOOL_REQUEST', 'agent', 'Invalid or duplicate bounded tool request')
            seen_calls.add(call['call_id'])
            step = {'step': index, 'tool': name, 'metadata': metadata}
            report['steps'].append(step)
            if on_step:
                on_step(step)
            if name != 'finish' and arguments:
                fail('TOOL_ARGUMENTS', 'agent', 'Read/test tools take no arguments')
            result = []
            if name == 'read_logs':
                for evidence in logs:
                    offered[evidence.alias] = evidence
                    result.append({'alias': evidence.alias, 'data': evidence.payload})
            elif name == 'read_source':
                evidence = prepared['source'] if prepared else collect_source(runtime, observer, case, case.baseline_revision, 'source_current')
                offered[evidence.alias] = evidence
                report['evidence'][evidence.alias] = evidence.node_id
                result.append({'alias': evidence.alias, 'data': evidence.payload})
                contract = observe('service_contract', {'readme': SERVICE_CONTRACT, 'revision': case.baseline_revision})
                result.append({'alias': contract.alias, 'data': contract.payload})
            elif name == 'read_diff':
                evidence = collect_diff(runtime, observer, case, case.good_revision, case.baseline_revision, 'deployment_diff')
                offered[evidence.alias] = evidence
                report['evidence'][evidence.alias] = evidence.node_id
                result.append({'alias': evidence.alias, 'data': evidence.payload})
            elif name == 'run_tests':
                try:
                    current_tests = test_snapshot(current, f'agent-step-{index}')
                except InvestigationError as error:
                    if error.code not in ('PATCH_SHAPE', 'PATCH_LIMIT'):
                        raise
                    current_tests = []
                    evidence = observe('current_test_error', {'revision': current.revision, 'code': error.code, 'detail': error.detail})
                    result.append({'alias': evidence.alias, 'data': evidence.payload})
                for test in current_tests:
                    evidence = observe(f'current_{test.suite}', dict(revision=current.revision, **test.payload()))
                    result.append({'alias': evidence.alias, 'data': evidence.payload})
            else:
                if set(arguments) != {'assessment', 'claim_statement', 'evidence_aliases', 'patch_content', 'summary'}:
                    fail('AGENT_PROTOCOL', 'proposal', 'Unexpected finish fields')
                assessment = arguments['assessment']
                if assessment not in ('healthy', 'regression', 'inconclusive'):
                    fail('AGENT_PROTOCOL', 'proposal', 'Unknown assessment')
                decision = decode_decision(canonical_json({k: v for k, v in arguments.items() if k != 'assessment'}), tuple(offered.values()))
                if not {'logs_current', 'source_current'} <= set(decision.evidence_aliases):
                    result = {'error': 'Final assessment must cite logs_current and source_current. Request their tools if needed.'}
                else:
                    request = AgentRequest(transcript[0]['content'], SERVICE_CONTRACT, tuple(offered.values()), (), index)
                    run = AgentRun(decision, agent.backend, agent.live, metadata)
                    claim_id, action_id = admit_decision(runtime, case, current, request, run,
                                                        input_bytes=safe_path(directory, 'input.json').read_bytes())
                    report.update(claim_id=claim_id, action_id=action_id, decision=arguments)
                    if assessment == 'inconclusive':
                        report['reason'] = 'Agent gathered evidence but did not reach a conclusion.'
                    elif assessment == 'healthy':
                        report['outcome'] = 'MISSED' if changed_behavior else 'HEALTHY'
                        report['reason'] = 'Agent missed the observed behavior change.' if changed_behavior else 'Agent found the healthy deployment consistent with its contract.'
                        if action_id:
                            report['outcome'], report['reason'] = 'REFUSED', 'A healthy assessment cannot request a changed repair.'
                    elif not changed_behavior:
                        report['outcome'], report['reason'] = 'FALSE_ALARM', 'Agent reported a regression in the healthy control.'
                    elif action_id is None:
                        report['outcome'], report['reason'] = 'DETECTED', 'Agent detected the observed regression without proposing a changed repair.'
                    else:
                        candidate = candidate_snapshot(current, validate_patch(decision.patch_content))
                        verification_ids = []
                        results = test_snapshot(candidate, 'candidate')
                        for test in results:
                            _, verification_id = record_test(runtime, observer, tester, action_id, test, {})
                            verification_ids.append(verification_id)
                        check_current()
                        authority_id = runtime.authorize(issuer, action_id, True, runtime.clock()+timedelta(minutes=15)) if all(t.passed for t in results) else None
                        report['authority_id'] = authority_id
                        try:
                            receipt = runtime.commit(action_id, tuple(verification_ids), authority_id)
                            report['outcome'], report['effect_id'] = 'ACCEPTED', receipt.effect_id
                            report['reason'] = 'Agent detected the regression; its independently tested repair earned one simulated receipt.'
                            trace = why(store, receipt.effect_id, 'execution')
                            report['trace'] = {'status': trace.statuses[receipt.effect_id], 'records': [n.id for n in trace.nodes]}
                        except ProvenanceError as error:
                            report['outcome'], report['reason'] = 'REFUSED', error.problem.detail
                        safe_path(case.root, 'artifacts/repair.patch').write_text(unified_patch(current.files[TARGET].decode(), decision.patch_content))
                    break
            check_current()
            safe_path(directory, 'result.json').write_bytes(canonical_json(result))
            transcript.extend([call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': canonical_json(result).decode()}])
    except (InvestigationError, ProvenanceError, OSError, sqlite3.Error) as error:
        if isinstance(error, InvestigationError):
            detail = {'code': error.code, 'stage': error.stage, 'detail': error.detail}
        elif isinstance(error, ProvenanceError):
            detail = {'code': error.problem.code, 'stage': 'records', 'detail': error.problem.detail}
        else:
            detail = {'code': 'IO_ERROR', 'stage': 'io', 'detail': str(error)[:2000]}
        report.update(outcome='ERROR', error=detail, reason=detail['detail'])
    finally:
        if store:
            try:
                report['record_snapshot'] = report_record_snapshot(store, report)
            except (ProvenanceError, sqlite3.Error):
                report['record_snapshot_error'] = {'code': 'RECORD_SNAPSHOT', 'detail': 'Could not validate the report records'}
            finally:
                store.close()
        if case:
            try:
                safe_path(case.root, 'report.json').write_bytes(canonical_json(report))
                safe_path(case.root, 'report.md').write_text(render_report(report))
            except (InvestigationError, OSError) as error:
                report.update(outcome='ERROR', error={'code': 'REPORT_WRITE', 'stage': 'report', 'detail': str(error)[:2000]}, reason='Could not save report safely.')
    return report
