"""Host-owned session and proposal bindings. Local actor labels are audit data."""
import os
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from ...errors import fail
from ...format import canonical_json, parse_json
from ...store import Store, Admission
from ...projection import status
from ..repo_repair.case import (safe_path, digest, TARGET, TEST_PATH, TEST_SOURCE,
                               snapshot_value, candidate_snapshot, save_snapshot)
from ..repo_repair.contract import validate_patch
from ..repo_repair.verifier import SUITES
from .profiles import authority_policy, profile_name


@dataclass(frozen=True)
class ApprovalSession:
    root: Path
    database: Path
    session_id: str
    mode: str
    client: str
    profile: str
    source_repository: Path
    observation_id: str


def guarded_root(root):
    root = Path(root).absolute()
    return safe_path(root.parent, root.name)


def read_object(path, limit):
    if not path.is_file() or path.stat().st_size > limit:
        fail('APPROVAL_CONTEXT', 'missing or oversized approval file')
    data = path.read_bytes()
    if len(data) > limit:
        fail('APPROVAL_CONTEXT', 'approval file exceeds its byte limit')
    value = parse_json(data)
    if type(value) is not dict:
        fail('APPROVAL_CONTEXT', 'approval file must be a JSON object')
    return value


def write_object(root, relative, value):
    path = safe_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe_path(root, relative + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(canonical_json(value) + b'\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def existing_database(path):
    # Inspect read-only first: Store's normal constructor intentionally creates tables.
    if not path.is_file():
        fail('APPROVAL_SESSION', 'session history database is missing')
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'nodes', 'edges', 'admissions', 'local_effects'}.issubset(names):
                fail('APPROVAL_SESSION', 'session database has no runtime history schema')
    except sqlite3.Error:
        fail('APPROVAL_SESSION', 'session database cannot be read')


def trusted_observation(store, node_id, source):
    content_id(node_id)
    report = store.validate(node_id)
    if not report.ok:
        fail('APPROVAL_CONTEXT', 'approval observation has invalid ancestry', node_id)
    record = store.get(node_id)
    if (record.kind != 'Observation' or record.producer != 'collector'
            or store.admission(node_id) != Admission('collector', 'observe')
            or record.payload.get('source') != source):
        fail('APPROVAL_CONTEXT', 'approval context lacks a local collector admission', node_id)
    return record


def content_id(value):
    if type(value) is not str or not re.fullmatch('sha256:[0-9a-f]{64}', value):
        fail('APPROVAL_CONTEXT', 'a full SHA-256 content ID is required')
    return value


def open_session(root) -> ApprovalSession:
    root = guarded_root(root)
    data = read_object(safe_path(root, 'approval-session.json'), 65536)
    if set(data) != {'descriptor', 'observation_id'} or type(data['descriptor']) is not dict:
        fail('APPROVAL_SESSION', 'invalid session wrapper')
    descriptor = data['descriptor']
    fields = {'format', 'version', 'session_id', 'mode', 'client', 'profile', 'source_repository', 'database'}
    if (set(descriptor) != fields or descriptor['format'] != 'provenance-approval-session'
            or descriptor['version'] != '0.1' or type(descriptor['session_id']) is not str
            or not re.fullmatch('[0-9a-f]{32}', descriptor['session_id'])
            or descriptor['client'] not in ('observed-service', 'watch-service')
            or descriptor['database'] != 'history.db'
            or descriptor['profile'] != profile_name(descriptor['mode'])
            or type(descriptor['source_repository']) is not str
            or not Path(descriptor['source_repository']).is_absolute()):
        fail('APPROVAL_SESSION', 'unsupported or inconsistent session descriptor')
    database = safe_path(root, 'history.db')
    existing_database(database)
    with Store(database) as store:
        record = trusted_observation(store, data['observation_id'], 'approval-session')
        if (record.payload.get('descriptor') != descriptor
                or record.payload.get('descriptor_hash') != digest(canonical_json(descriptor))
                or record.payload.get('session_root') != str(root)):
            fail('APPROVAL_SESSION', 'session file does not match its recorded local binding')
    return ApprovalSession(root, database, descriptor['session_id'], descriptor['mode'],
                           descriptor['client'], descriptor['profile'],
                           Path(descriptor['source_repository']), data['observation_id'])


def create_session(runtime, root, case_id, mode, client, source_repository) -> ApprovalSession:
    root = guarded_root(root)
    source_repository = Path(source_repository).absolute()
    if (client not in ('observed-service', 'watch-service') or type(case_id) is not str
            or not re.fullmatch('[0-9a-f]{32}', case_id)
            or runtime.policy.snapshot() != authority_policy(mode).snapshot()
            or Path(runtime.store.path).absolute() != safe_path(root, 'history.db')):
        fail('APPROVAL_SESSION', 'client, identity or runtime profile is inconsistent')
    path = safe_path(root, 'approval-session.json')
    if path.exists():
        session = open_session(root)
        if (session.session_id, session.mode, session.client, session.source_repository) != (
                case_id, mode, client, source_repository):
            fail('APPROVAL_SESSION', 'existing sessions cannot change mode, identity or resource')
        return session
    safe_path(source_repository.parent, source_repository.name)
    descriptor = {'format': 'provenance-approval-session', 'version': '0.1', 'session_id': case_id,
                  'mode': mode, 'client': client, 'profile': profile_name(mode),
                  'source_repository': str(source_repository), 'database': 'history.db'}
    observation = runtime.observe(runtime.observer('collector'), {
        'source': 'approval-session', 'session_root': str(root), 'descriptor': descriptor,
        'descriptor_hash': digest(canonical_json(descriptor))})
    write_object(root, 'approval-session.json', {'descriptor': descriptor, 'observation_id': observation})
    return open_session(root)


@dataclass(frozen=True, init=False)
class ProposalContext:
    action_id: str
    observation_id: str
    context_hash: str
    _data: bytes

    def __init__(self, action_id, observation_id, context_hash, data):
        object.__setattr__(self, 'action_id', action_id)
        object.__setattr__(self, 'observation_id', observation_id)
        object.__setattr__(self, 'context_hash', context_hash)
        object.__setattr__(self, '_data', canonical_json(data))

    @property
    def data(self):
        return parse_json(self._data)


def _relative(session, path):
    path = guarded_root(path)
    if not path.is_relative_to(session.root):
        fail('APPROVAL_CONTEXT', 'proposal paths must belong to this session')
    value = path.relative_to(session.root).as_posix()
    safe_path(session.root, value)
    return value


def _installed_runner_hash():
    return digest(Path(__file__).parents[1].joinpath('repo_repair/runner.py').read_bytes())


def _proofs(store, action_id, ids, candidate_hash, candidate_snapshot_hash, *, current_runner_hash=None):
    if type(ids) not in (tuple, list) or len(ids) != 2 or len(set(ids)) != 2:
        fail('VERIFICATION_FAILED', 'exactly the two required checks must be recorded', action_id)
    proofs, images = {}, set()
    for node_id in ids:
        content_id(node_id)
        report = store.validate(node_id)
        if not report.ok:
            fail('APPROVAL_CONTEXT', 'verification ancestry is corrupt', node_id)
        node = store.get(node_id)
        subjects = [p.node_id for p in node.parents if p.role == 'subject']
        evidence = [p.node_id for p in node.parents if p.role == 'evidence']
        if (node.kind != 'Verification' or node.producer != 'tester'
                or store.admission(node_id) != Admission('tester', 'verify')
                or subjects != [action_id] or len(evidence) != 1 or node.payload['passed'] is not True
                or node.payload['verifier_id'] != 'tester' or node.payload['check'] not in SUITES
                or node.payload['check'] in proofs):
            fail('VERIFICATION_FAILED', 'required check lacks its exact local binding', node_id)
        check = node.payload['check']
        obs_id = evidence[0]
        obs_report = store.validate(obs_id)
        observation = store.get(obs_id)
        if (not obs_report.ok or observation.kind != 'Observation' or observation.producer != 'collector'
                or store.admission(obs_id) != Admission('collector', 'observe')):
            fail('VERIFICATION_FAILED', 'test evidence is not locally observed', obs_id)
        proof = observation.payload
        required = {'action_id': action_id, 'suite': check, 'candidate_hash': candidate_hash,
                    'snapshot_hash': candidate_snapshot_hash, 'tests_hash': digest(TEST_SOURCE),
                    'tests_run': SUITES[check], 'failures': 0, 'errors': 0, 'returncode': 0,
                    'outcome': 'pass', 'executor': 'docker-linux-restricted'}
        if (any(proof.get(k) != v or type(proof.get(k)) is not type(v) for k, v in required.items())
                or type(proof.get('stdout')) is not str or type(proof.get('stderr')) is not str
                or proof.get('stdout_hash') != digest(proof['stdout'].encode('utf-8'))
                or proof.get('stderr_hash') != digest(proof['stderr'].encode('utf-8'))
                or (current_runner_hash is not None and proof.get('runner_hash') != current_runner_hash)):
            fail('VERIFICATION_FAILED', 'test evidence does not prove the exact candidate', node_id)
        content_id(proof.get('runner_hash'))
        content_id(proof.get('image_id'))
        images.add(proof['image_id'])
        proofs[check] = proof
    if set(proofs) != set(SUITES) or len(images) != 1:
        fail('VERIFICATION_FAILED', 'checks must use the same pinned verifier image', action_id)
    return proofs, images.pop()


def _validate_binding(session, store, data, *, current_runner_hash=None):
    fields = {'session_id', 'case_id', 'client', 'action_id', 'case_dir', 'repository',
              'source_observation_id', 'baseline_revision', 'baseline_snapshot', 'candidate_snapshot',
              'target_path', 'original_file_hash', 'candidate_file_hash', 'verification_ids', 'image_id', 'artifacts'}
    if (type(data) is not dict or set(data) != fields or data['session_id'] != session.session_id
            or data['client'] != session.client or type(data['case_id']) is not str
            or not re.fullmatch('[0-9a-f]{32}', data['case_id'])
            or type(data['case_dir']) is not str or type(data['repository']) is not str
            or type(data['artifacts']) is not dict):
        fail('APPROVAL_CONTEXT', 'proposal context has inconsistent session ownership')
    content_id(data['action_id'])
    case_dir = safe_path(session.root, data['case_dir'])
    repository = safe_path(session.root, data['repository'])
    if session.client == 'observed-service' and repository != session.source_repository:
        fail('APPROVAL_CONTEXT', 'owned repository differs from recorded session resource')
    report = store.validate(data['action_id'])
    if not report.ok:
        fail('APPROVAL_CONTEXT', 'proposal ancestry is corrupt', data['action_id'])
    for node_id in report.visited:
        ancestor = store.get(node_id)
        if ancestor.kind == 'Observation' and (ancestor.producer != 'collector'
                or store.admission(node_id) != Admission('collector', 'observe')):
            fail('APPROVAL_CONTEXT', 'supporting evidence lacks a local collector admission', node_id)
    action = store.get(data['action_id'])
    if (action.kind != 'ProposedAction' or action.payload['action_type'] != 'repo.repair.simulated'
            or action.payload['resource'] != 'fixture:clamp:' + data['case_id'] or data['target_path'] != TARGET):
        fail('APPROVAL_CONTEXT', 'proposal target or resource is outside this client profile')
    args = action.payload['arguments']
    expected = {'baseline_snapshot': data['baseline_snapshot'], 'candidate_snapshot': data['candidate_snapshot'],
                'target_path': TARGET, 'original_file_hash': data['original_file_hash']}
    if set(args) != set(expected) | {'patch_content'} or any(args[k] != v for k, v in expected.items()):
        fail('APPROVAL_CONTEXT', 'proposal arguments differ from recorded context')
    patch = validate_patch(args['patch_content'])
    if args['patch_content'].encode('utf-8') != patch or digest(patch) != data['candidate_file_hash']:
        fail('APPROVAL_CONTEXT', 'candidate bytes differ from recorded context')
    source_id = content_id(data['source_observation_id'])
    source = store.get(source_id)
    if (source_id not in report.visited or source.kind != 'Observation' or source.producer != 'collector'
            or store.admission(source_id) != Admission('collector', 'observe')
            or source.payload.get('snapshot_hash') != data['baseline_snapshot']
            or source.payload.get('revision') != data['baseline_revision']
            or source.payload.get('file_hashes', {}).get(TARGET) != data['original_file_hash']
            or type(source.payload.get('source_text')) is not str):
        fail('APPROVAL_CONTEXT', 'source view does not bind the captured baseline')
    baseline = snapshot_value(data['baseline_revision'], {TARGET: source.payload['source_text'].encode('utf-8'), TEST_PATH: TEST_SOURCE})
    candidate = candidate_snapshot(baseline, patch)
    if (baseline.snapshot_hash != data['baseline_snapshot'] or candidate.snapshot_hash != data['candidate_snapshot']
            or baseline.file_hashes != source.payload['file_hashes'] or patch == baseline.files[TARGET]):
        fail('APPROVAL_CONTEXT', 'immutable baseline or candidate content differs')
    proofs, image = _proofs(store, data['action_id'], data['verification_ids'],
                           data['candidate_file_hash'], data['candidate_snapshot'], current_runner_hash=current_runner_hash)
    if image != data['image_id']:
        fail('VERIFICATION_FAILED', 'recorded verifier image differs')
    expected_artifacts = {}
    for snapshot in (baseline, candidate):
        directory = case_dir/'artifacts'/'snapshots'/snapshot.snapshot_hash.split(':')[1]
        for name, value in snapshot.files.items():
            expected_artifacts[_relative(session, directory/name)] = digest(value)
        manifest = canonical_json({'revision': snapshot.revision, 'files': snapshot.file_hashes,
                                   'snapshot_hash': snapshot.snapshot_hash})
        expected_artifacts[_relative(session, directory/'snapshot.json')] = digest(manifest)
    for check, proof in proofs.items():
        path = case_dir/'artifacts'/'approvals'/data['action_id'].split(':')[1]/(check+'.json')
        expected_artifacts[_relative(session, path)] = digest(canonical_json(proof)+b'\n')
    if data['artifacts'] != expected_artifacts:
        fail('APPROVAL_CONTEXT', 'artifact references differ from the exact recorded proofs')
    return baseline, candidate


def _recorded_context(session, store, action_id):
    matches = []
    for node_id in store.all_ids():
        node = store.get(node_id)
        if (node.kind == 'Observation' and node.payload.get('source') == 'approval-context'
                and type(node.payload.get('context')) is dict
                and node.payload['context'].get('action_id') == action_id
                and store.admission(node_id) == Admission('collector', 'observe')):
            trusted_observation(store, node_id, 'approval-context')
            data = node.payload['context']
            if node.payload.get('context_hash') != digest(canonical_json(data)):
                fail('APPROVAL_CONTEXT', 'recorded context hash differs', node_id)
            matches.append(ProposalContext(action_id, node_id, node.payload['context_hash'], data))
    if not matches:
        fail('APPROVAL_CONTEXT', 'proposal has no local approval context', action_id)
    if len({m.context_hash for m in matches}) != 1:
        fail('APPROVAL_CONTEXT', 'proposal has conflicting trusted contexts', action_id)
    return matches[0]


def load_context(session, store, action_id, *, artifacts=True) -> ProposalContext:
    content_id(action_id)
    with store.read_snapshot():
        ctx = _recorded_context(session, store, action_id)
    # Immutable recorded ownership remains inspectable across application updates.
    # Filesystem/current-code checks happen after the short graph snapshot.
    _validate_binding(session, store, ctx.data,
                      current_runner_hash=_installed_runner_hash() if artifacts else None)
    if artifacts:
        path = safe_path(session.root, 'approvals/'+action_id.split(':')[1]+'.json')
        wrapper = read_object(path, 131072)
        if wrapper != {'context': ctx.data, 'observation_id': ctx.observation_id}:
            fail('APPROVAL_CONTEXT', 'proposal file differs from recorded context')
        for relative, expected_hash in ctx.data['artifacts'].items():
            path = safe_path(session.root, relative)
            if not path.is_file() or path.stat().st_size > 1048576 or digest(path.read_bytes()) != expected_hash:
                fail('APPROVAL_CONTEXT', 'proposal artifact is missing or altered')
    return ctx


def record_context(session, runtime, case, baseline, action_id, source_observation_id, verification_ids):
    if (case.database.absolute() != session.database or runtime.policy.snapshot() != authority_policy(session.mode).snapshot()
            or baseline.revision != case.baseline_revision):
        fail('APPROVAL_CONTEXT', 'proposal runtime or captured case differs from session')
    action = runtime.store.get(content_id(action_id))
    patch = validate_patch(action.payload.get('arguments', {}).get('patch_content'))
    candidate = candidate_snapshot(baseline, patch)
    runner_hash = _installed_runner_hash()
    proofs, image_id = _proofs(runtime.store, action_id, verification_ids, digest(patch), candidate.snapshot_hash,
                              current_runner_hash=runner_hash)
    data = {'session_id': session.session_id, 'case_id': case.case_id, 'client': session.client,
            'action_id': action_id, 'case_dir': _relative(session, case.root), 'repository': _relative(session, case.repository),
            'source_observation_id': source_observation_id, 'baseline_revision': baseline.revision,
            'baseline_snapshot': baseline.snapshot_hash, 'candidate_snapshot': candidate.snapshot_hash,
            'target_path': TARGET, 'original_file_hash': baseline.file_hashes[TARGET], 'candidate_file_hash': digest(patch),
            'verification_ids': list(verification_ids), 'image_id': image_id, 'artifacts': {}}
    for snapshot in (baseline, candidate):
        # Paths/hashes are generated from trusted captures, never model-provided paths.
        directory = case.root/'artifacts'/'snapshots'/snapshot.snapshot_hash.split(':')[1]
        for name, value in snapshot.files.items():
            data['artifacts'][_relative(session, directory/name)] = digest(value)
        manifest = canonical_json({'revision': snapshot.revision, 'files': snapshot.file_hashes, 'snapshot_hash': snapshot.snapshot_hash})
        data['artifacts'][_relative(session, directory/'snapshot.json')] = digest(manifest)
    for check, proof in proofs.items():
        relative = _relative(session, case.root/'artifacts'/'approvals'/action_id.split(':')[1]/(check+'.json'))
        data['artifacts'][relative] = digest(canonical_json(proof)+b'\n')
    _validate_binding(session, runtime.store, data, current_runner_hash=runner_hash)
    path = safe_path(session.root, 'approvals/'+action_id.split(':')[1]+'.json')
    if path.exists():
        existing = load_context(session, runtime.store, action_id)
        if existing.data != data:
            fail('APPROVAL_CONTEXT', 'an existing proposal context cannot be replaced')
        return existing
    for snapshot in (baseline, candidate):
        save_snapshot(case, snapshot)
    for check, proof in proofs.items():
        relative = _relative(session, case.root/'artifacts'/'approvals'/action_id.split(':')[1]/(check+'.json'))
        write_object(session.root, relative, proof)
    context_hash = digest(canonical_json(data))
    observation_id = runtime.observe(runtime.observer('collector'), {
        'source': 'approval-context', 'context': data, 'context_hash': context_hash})
    write_object(session.root, 'approvals/'+action_id.split(':')[1]+'.json', {'context': data, 'observation_id': observation_id})
    return load_context(session, runtime.store, action_id)
