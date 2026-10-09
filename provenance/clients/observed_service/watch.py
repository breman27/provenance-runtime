"""Watch real working-tree edits, collect observations, and investigate asynchronously."""
import random
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from ... import Store, Runtime, ProvenanceError
from ...format import canonical_json
from ..repo_repair.case import (CasePaths, Evidence, TEST_SOURCE, TARGET, TEST_PATH,
                               _git, safe_path, capture_snapshot, digest, save_snapshot)
from ..repo_repair.errors import InvestigationError, fail
from .experiment import SERVICE_CONTRACT, ServiceVerifier, service_policy, run_experiment
from ..authority.context import create_session


@dataclass(frozen=True)
class WorkingVersion:
    content: bytes
    head: str
    fingerprint: str


def read_working_version(repository):
    repository = Path(repository).absolute()
    target = safe_path(repository, TARGET)
    if target.stat().st_size > 8000:
        fail('SOURCE_LIMIT', 'watch', 'Demo source must be at most 8,000 bytes')
    content = target.read_bytes()
    content.decode('utf-8')
    head = _git(repository, 'rev-parse', 'HEAD').decode().strip()
    fingerprint = digest(canonical_json({'source_hash': digest(content), 'upstream_head': head}))
    return WorkingVersion(content, head, fingerprint)


def initialize_session(repository, directory):
    repository, directory = Path(repository).absolute(), Path(directory).absolute()
    safe_path(repository.parent, repository.name)
    safe_path(directory.parent, directory.name)
    if directory.exists():
        fail('CASE_EXISTS', 'options', 'Watch session directory must be new')
    read_working_version(repository)
    for name in ('repository/src', 'repository/tests', 'versions', 'investigations'):
        safe_path(directory, name).mkdir(parents=True, exist_ok=True)
    mirror = directory/'repository'
    safe_path(mirror, TEST_PATH).write_bytes(TEST_SOURCE)
    safe_path(mirror, 'README.md').write_text(SERVICE_CONTRACT, encoding='utf-8', newline='\n')
    safe_path(mirror, 'service.py').write_bytes(Path(__file__).with_name('service.py').read_bytes())
    _git(mirror, 'init', '--initial-branch=observed')
    _git(mirror, 'config', 'core.autocrlf', 'false')
    _git(mirror, 'config', 'user.name', 'Provenance live collector')
    _git(mirror, 'config', 'user.email', 'collector@example.invalid')
    return CasePaths(directory, mirror, directory/'artifacts', directory/'agent-view',
                     directory/'history.db', uuid.uuid4().hex, '', '')


def capture_version(session, version, index):
    previous = session.baseline_revision
    safe_path(session.repository, TARGET).write_bytes(version.content)
    _git(session.repository, 'add', '.')
    _git(session.repository, 'commit', '--allow-empty', '-m', 'Capture working tree ' + version.fingerprint)
    revision = _git(session.repository, 'rev-parse', 'HEAD').decode().strip()
    root = safe_path(session.root, f'versions/version-{index:04d}')
    root.mkdir()
    case = replace(session, root=root, artifacts=root/'artifacts', agent_view=root/'agent-view',
                   good_revision=previous or revision, baseline_revision=revision)
    snapshot = capture_snapshot(case, revision)
    directory = save_snapshot(case, snapshot)
    return case, snapshot, directory


def reading_batch(random_source):
    # Ordinary incoming readings vary while covering values around both operating bounds.
    return (random_source.randint(-40, -1), random_source.randint(1, 99),
            random_source.randint(1, 99), random_source.randint(101, 240), 0, 100)


def health_of(payload):
    if payload.get('outcome') == 'error':
        return 'ERROR'
    return 'ANOMALY' if any(e['output'] != max(e['lower'], min(e['input'], e['upper']))
                            for e in payload['entries']) else 'OK'


def console_line(event):
    stamp = event['time'][11:19]
    kind = event['event']
    if kind == 'OBSERVATION':
        pairs = ', '.join(f"{value}->{output}" for value,output in zip(event['inputs'],event['outputs']))
        return f"[{stamp}] OBS #{event['batch']} v{event['version']} {event['health']} | {pairs or 'service failed'} | {event['observation_id'][:19]}"
    if kind in ('SOURCE_CHANGED', 'SOURCE_CAPTURED'):
        return f"[{stamp}] {kind} v{event['version']} | {event['source_hash'][:19]}"
    if kind == 'AGENT_TOOL':
        return f"[{stamp}] AGENT #{event['investigation']} step {event['step']}: {event['tool']}"
    if kind == 'AGENT_RESULT':
        return f"[{stamp}] AGENT #{event['investigation']} {event['outcome']}: {event['summary']}\n  Report: {event['report']}"
    return f"[{stamp}] {kind} " + ' '.join(f"{key}={value}" for key,value in event.items() if key not in ('time','event'))


class ServiceWatcher:
    def __init__(self, repository, directory, verifier, agent=None, interval=5, max_steps=8,
                 random_source=None, output=print, *, approval_mode='auto'):
        if not 1 <= interval <= 3600 or not 1 <= max_steps <= 12:
            fail('OPTIONS', 'options', 'Interval must be 1–3,600 seconds and steps 1–12')
        self.repository, self.directory = Path(repository).absolute(), Path(directory).absolute()
        self.verifier, self.agent, self.interval, self.max_steps = verifier, agent, interval, max_steps
        service_policy(approval_mode)
        self.approval_mode = approval_mode
        self.random = random_source or random.SystemRandom()
        self.output = output
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.pending = None
        self.sequence, self.version_index, self.investigation_index = 0, 0, 0
        self.session = self.case = self.snapshot = self.version = self.source = self.last_log = None
        self.last_health = None

    def event(self, kind, **values):
        event = {'time': datetime.now(timezone.utc).isoformat(), 'event': kind, **values}
        with self.lock:
            with safe_path(self.directory, 'events.jsonl').open('ab') as stream:
                stream.write(canonical_json(event)+b'\n')
            self.output(console_line(event), flush=True)
        return event

    def start(self):
        self.verifier.preflight()
        if self.agent:
            self.agent.preflight()
        self.session = initialize_session(self.repository, self.directory)
        self.store = Store(self.session.database)
        self.runtime = Runtime(self.store, service_policy(self.approval_mode), lambda: datetime.now(timezone.utc))
        self.observer, self.controller = self.runtime.observer('collector'), self.runtime.controller('controller')
        if self.approval_mode == 'manual':
            create_session(self.runtime, self.directory, self.session.case_id, 'manual', 'watch-service', self.repository)
        self.event('WATCHING', repo=str(self.repository), session=str(self.directory),
                   interval_seconds=self.interval, live_agent=bool(self.agent and self.agent.live))

    def tick(self):
        version = read_working_version(self.repository)
        changed = self.version is None or version.fingerprint != self.version.fingerprint
        if changed:
            old_source = self.source
            previous_case = self.case
            self.version_index += 1
            self.case, self.snapshot, artifact = capture_version(self.session, version, self.version_index)
            self.session = replace(self.session, baseline_revision=self.case.baseline_revision)
            payload = {'source': 'git-working-tree', 'scope': 'current_working_tree', 'live_source': True,
                       'upstream_repo': str(self.repository), 'upstream_head': version.head,
                       'working_tree_hash': version.fingerprint, 'revision': self.snapshot.revision,
                       'snapshot_hash': self.snapshot.snapshot_hash, 'file_hashes': self.snapshot.file_hashes,
                       'source_text': version.content.decode(), 'artifact': str(artifact)}
            node_id = self.runtime.observe(self.observer, payload)
            self.source = Evidence('source_current', node_id, self.store.get(node_id).payload)
            if old_source:
                self.runtime.supersede(self.controller, old_source.node_id, node_id,
                                       'Measured working tree changed; the earlier current-source view has been replaced')
            self.version = version
            self.event('SOURCE_CHANGED' if previous_case else 'SOURCE_CAPTURED', version=self.version_index,
                       source_hash=digest(version.content), observation_id=node_id, upstream_head=version.head)
        self.sequence += 1
        readings = reading_batch(self.random)
        payload = self.verifier.run_service(self.snapshot, self.case, readings=readings, allow_failure=True)
        stdout = payload['stdout'].encode()
        if digest(stdout) != payload['stdout_hash']:
            fail('SERVICE_LOG', 'watch', 'Saved stdout does not match captured digest')
        log_path = safe_path(self.directory, f'versions/version-{self.version_index:04d}/batch-{self.sequence:06d}.jsonl')
        log_path.write_bytes(stdout)
        payload.update(sequence=self.sequence, observed_at=datetime.now(timezone.utc).isoformat(),
                       upstream_repo=str(self.repository), working_tree_hash=self.version.fingerprint,
                       artifact=str(log_path))
        node_id = self.runtime.observe(self.observer, payload)
        current_log = Evidence('logs_current', node_id, self.store.get(node_id).payload)
        health = health_of(payload)
        self.event('OBSERVATION', batch=self.sequence, version=self.version_index, health=health,
                   inputs=list(readings), outputs=[entry['output'] for entry in payload['entries']],
                   observation_id=node_id, source_hash=payload['source_hash'])
        with self.lock:
            state = {'repo': str(self.repository), 'session': str(self.directory), 'batch': self.sequence,
                     'version': self.version_index, 'health': health, 'source_observation': self.source.node_id,
                     'log_observation': node_id, 'source_hash': payload['source_hash']}
            safe_path(self.directory, 'latest.json').write_bytes(canonical_json(state))
        if self.agent and (changed or (health != 'OK' and self.last_health == 'OK')):
            self.investigation_index += 1
            root = safe_path(self.directory, f'investigations/investigation-{self.investigation_index:04d}')
            root.mkdir()
            job_case = replace(self.case, root=root, artifacts=root/'artifacts', agent_view=root/'agent-view',
                               case_id=uuid.uuid4().hex)
            logs = []
            if self.last_log:
                logs.append(Evidence('logs_before', self.last_log.node_id, self.last_log.payload))
            logs.append(current_log)
            job = {'case': job_case, 'snapshot': self.snapshot, 'source': self.source, 'logs': logs,
                   'fingerprint': self.version.fingerprint, 'number': self.investigation_index,
                   'approval_session_root': self.directory, 'approval_mode': self.approval_mode}
            with self.lock:
                displaced = self.pending
                self.pending = job
            if displaced:
                self.event('INVESTIGATION_COALESCED', skipped=displaced['number'], latest=job['number'])
            self.event('INVESTIGATION_QUEUED', investigation=job['number'], version=self.version_index)
        self.last_log, self.last_health = current_log, health
        self.start_pending()
        return state

    def start_pending(self):
        if self.stop.is_set() or (self.thread and self.thread.is_alive()):
            return
        with self.lock:
            job, self.pending = self.pending, None
        if job:
            self.thread = threading.Thread(target=self.investigate, args=(job,), name='service-investigation')
            self.thread.start()

    def investigate(self, job):
        def guard():
            if self.stop.is_set():
                fail('WATCH_STOPPED', 'watch', 'Watcher stopped before this investigation completed')
            if read_working_version(self.repository).fingerprint != job['fingerprint']:
                fail('BASELINE_CHANGED', 'watch', 'Working tree changed while the agent was investigating')
        def on_step(step):
            self.event('AGENT_TOOL', investigation=job['number'], step=step['step'], tool=step['tool'])
        self.event('INVESTIGATION_STARTED', investigation=job['number'])
        try:
            report = run_experiment(job['case'].root, self.agent, self.verifier, 'live', self.max_steps,
                                    prepared=job, guard=guard, on_step=on_step, approval_mode=self.approval_mode)
            outcome = 'STALE' if (report.get('error') or {}).get('code') == 'BASELINE_CHANGED' else report['outcome']
            self.event('AGENT_RESULT', investigation=job['number'], outcome=outcome,
                       assessment=report['decision']['assessment'] if report['decision'] else None,
                       summary=report['decision']['summary'] if report['decision'] else report['reason'],
                       claim_id=report['claim_id'], effect_id=report['effect_id'],
                       report=str(job['case'].root/'report.md'))
            if report['outcome'] == 'AWAITING_APPROVAL':
                self.event('APPROVAL_PENDING', investigation=job['number'], action_id=report['action_id'],
                           session_dir=str(self.directory), report=str(job['case'].root/'report.md'))
        except Exception:
            # Preserve a public failure marker without printing transport exceptions/credentials.
            self.event('AGENT_ERROR', investigation=job['number'], detail='Investigation stopped unexpectedly; inspect saved case artifacts')

    def close(self):
        self.stop.set()
        if self.thread and self.thread.is_alive():
            self.event('STOPPING', detail='Waiting for the in-flight bounded request to finish')
            self.thread.join()
        if self.session:
            self.event('STOPPED', observations=self.sequence, versions=self.version_index)
            self.store.close()

    def run(self, max_ticks=None):
        self.start()
        try:
            while not self.stop.is_set() and not safe_path(self.directory, 'STOP').exists():
                try:
                    self.tick()
                except (InvestigationError, ProvenanceError, OSError, UnicodeError) as error:
                    self.event('COLLECTOR_ERROR', code=getattr(error, 'code', 'CAPTURE_FAILED'), detail=str(error)[:1000])
                if max_ticks is not None and self.sequence >= max_ticks:
                    break
                self.stop.wait(self.interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.close()
