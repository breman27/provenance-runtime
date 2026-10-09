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
from ..repo_repair.case import safe_path, digest
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
