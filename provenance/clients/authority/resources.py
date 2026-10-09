"""Physical freshness adapters. No model, Docker execution or held DB snapshot."""
from pathlib import Path

from ...errors import fail, ProvenanceError
from ...format import canonical_json
from ...projection import status
from ..repo_repair.case import TARGET, TEST_PATH, TEST_SOURCE, safe_path, digest, _git
from ..repo_repair.errors import InvestigationError
from ..observed_service.contract import SERVICE_CONTRACT


def check_current(session, runtime, context):
    data = context.data
    source = runtime.store.get(data['source_observation_id'])
    try:
        repository = safe_path(session.source_repository.parent, session.source_repository.name)
        content = safe_path(repository, TARGET).read_bytes()
        head = _git(repository, 'rev-parse', 'HEAD').decode('ascii').strip()
        if session.client == 'watch-service':
            fingerprint = digest(canonical_json({'source_hash': digest(content), 'upstream_head': head}))
            if (source.payload.get('source') != 'git-working-tree'
                    or source.payload.get('upstream_repo') != str(repository)):
                fail('APPROVAL_CONTEXT', 'live source view differs from the session resource')
            changed = fingerprint != source.payload.get('working_tree_hash')
            measured = {'upstream_head': head, 'source_hash': digest(content), 'working_tree_hash': fingerprint}
        else:
            expected = {TARGET: source.payload['source_text'].encode('utf-8'), TEST_PATH: TEST_SOURCE,
                        'README.md': SERVICE_CONTRACT.encode('utf-8'),
                        'service.py': Path(__file__).parents[1].joinpath('observed_service/service.py').read_bytes()}
            observed = {name: digest(safe_path(repository, name).read_bytes()) for name in expected}
            changed = head != data['baseline_revision'] or any(observed[name] != digest(value) for name, value in expected.items())
            measured = {'revision': head, 'file_hashes': observed}
    except (OSError, UnicodeError, InvestigationError) as error:
        fail('SOURCE_UNAVAILABLE', 'recorded source cannot be safely read: ' + str(error)[:500])
    if changed:
        runtime.observe(runtime.observer('collector'), {'source': 'approval-freshness',
            'action_id': context.action_id, 'source_observation_id': source.id, 'measured': measured})
        if status(runtime.store, source.id, 'execution') == 'VALID':
            runtime.invalidate(runtime.controller('controller'), source.id, 'source changed before approval/admission')
        fail('STALE', 'source changed; a fresh investigation is required', context.action_id)
