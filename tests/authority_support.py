"""Real local graph/resource setup; candidate execution doubles stay in tests."""
from datetime import datetime, timezone

from provenance import Store, Runtime
from provenance.model import make_node, Parent
from provenance.clients.observed_service.experiment import prepare_service, deploy_change
from provenance.clients.repo_repair.case import capture_snapshot, collect_source, candidate_snapshot, GOOD_SOURCE, Evidence, digest
from provenance.format import canonical_json
from provenance.clients.repo_repair.verifier import record_test, TestResult, SUITES
from provenance.clients.authority.profiles import authority_policy
from provenance.clients.authority.context import create_session

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
IMAGE = 'sha256:' + 'd'*64


def pending(root, clock=lambda: NOW, client='observed-service'):
    case = deploy_change(prepare_service(root))
    store = Store(case.database)
    runtime = Runtime(store, authority_policy('manual'), clock)
    session = create_session(runtime, case.root, case.case_id, 'manual', client, case.repository)
    baseline = capture_snapshot(case, case.baseline_revision)
    source = collect_source(runtime, runtime.observer('collector'), case, baseline.revision, 'source_current')
    if client == 'watch-service':
        payload = dict(source.payload, source='git-working-tree', upstream_repo=str(case.repository),
                       upstream_head=baseline.revision, working_tree_hash=digest(canonical_json({
                           'source_hash': baseline.file_hashes['src/clamp.py'], 'upstream_head': baseline.revision})))
        source_id = runtime.observe(runtime.observer('collector'), payload)
        source = Evidence('source_current', source_id, payload)
    logs = runtime.observe(runtime.observer('collector'), {'source': 'logs', 'message': 'out of range'})
    claim = runtime.submit(make_node('Claim', {'statement': 'upper bound regression'},
                                    [Parent('evidence', source.node_id), Parent('evidence', logs)], 'agent:test', clock()))
    candidate = candidate_snapshot(baseline, GOOD_SOURCE)
    action = runtime.submit(make_node('ProposedAction', {
        'action_type': 'repo.repair.simulated', 'resource': 'fixture:clamp:' + case.case_id,
        'arguments': {'baseline_snapshot': baseline.snapshot_hash, 'candidate_snapshot': candidate.snapshot_hash,
                      'target_path': 'src/clamp.py', 'original_file_hash': baseline.file_hashes['src/clamp.py'],
                      'patch_content': GOOD_SOURCE.decode('utf-8')}},
        [Parent('justification', claim)], 'agent:test', clock()))
    checks = tuple(record_test(runtime, runtime.observer('collector'), runtime.verifier('tester'), action,
                TestResult(suite, IMAGE, candidate.snapshot_hash, candidate.file_hashes['src/clamp.py'],
                           count, 0, 0, 0, 1, 'pass', '{}', ''), {})[1] for suite, count in SUITES.items())
    return case, store, runtime, session, baseline, action, source.node_id, checks, logs
