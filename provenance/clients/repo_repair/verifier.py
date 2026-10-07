"""Host-controlled verification, bound to exact candidate content."""
import re
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

from ...format import parse_json, canonical_json
from .case import TARGET, TEST_PATH, TEST_SOURCE, digest, save_snapshot, snapshot_value, safe_path
from .contract import validate_patch
from .errors import fail
from .process import run_process

SUITES = {'targeted_tests': 1, 'full_suite': 8}


@dataclass(frozen=True)
class TestResult:
    suite: str
    image_id: str
    snapshot_hash: str
    candidate_hash: str
    tests_run: int
    failures: int
    errors: int
    returncode: int
    elapsed_ms: int
    outcome: str
    stdout: str
    stderr: str

    @property
    def passed(self):
        return (self.outcome == 'pass' and self.returncode == 0 and
                self.tests_run == SUITES.get(self.suite) and self.tests_run > 0 and self.failures == self.errors == 0)

    def payload(self):
        value = asdict(self)
        value['stdout_hash'] = digest(self.stdout.encode())
        value['stderr_hash'] = digest(self.stderr.encode())
        value['runner_hash'] = digest(Path(__file__).with_name('runner.py').read_bytes())
        value['tests_hash'] = digest(TEST_SOURCE)
        value['executor'] = 'docker-linux-restricted'
        return value


class DockerVerifier:
    def __init__(self, command='docker'):
        self.command, self.image_id = command, None

    def preflight(self):
        cwd = Path.cwd()
        try:
            result = run_process((self.command, 'version', '--format', '{{json .Server}}'), cwd, timeout=20)
            if result.returncode or result.timed_out or result.output_exceeded:
                fail('DOCKER_UNAVAILABLE', 'preflight', 'a running Linux Docker engine is required')
            if parse_json(result.stdout).get('Os') != 'linux':
                fail('DOCKER_UNAVAILABLE', 'preflight', 'the Docker engine must use Linux containers')
            result = run_process((self.command, 'image', 'inspect', '--format', '{{.Id}}', 'python:3.12-slim'), cwd)
            if result.returncode:
                pull = run_process((self.command, 'pull', 'python:3.12-slim'), cwd, timeout=180)
                if pull.returncode or pull.timed_out or pull.output_exceeded:
                    fail('IMAGE_UNAVAILABLE', 'preflight', 'could not obtain python:3.12-slim')
                result = run_process((self.command, 'image', 'inspect', '--format', '{{.Id}}', 'python:3.12-slim'), cwd)
            image_id = result.stdout.decode('ascii').strip()
            if result.returncode or result.timed_out or result.output_exceeded or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
                fail('IMAGE_UNAVAILABLE', 'preflight', 'could not pin the container image')
        except (OSError, ValueError, UnicodeError) as error:
            fail('DOCKER_UNAVAILABLE', 'preflight', str(error)[:500])
        self.image_id = image_id
        return image_id

    def test(self, snapshot, case, suite):
        if suite not in SUITES or not self.image_id:
            fail('VERIFIER_CONFIG', 'verify', 'preflight and a known suite are required')
        expected = snapshot_value(snapshot.revision, snapshot.files)
        if expected.snapshot_hash != snapshot.snapshot_hash or expected.file_hashes != snapshot.file_hashes or set(snapshot.files) != {TARGET, TEST_PATH}:
            fail('SNAPSHOT_MISMATCH', 'verify', 'snapshot content does not match its manifest')
        validate_patch(snapshot.files[TARGET].decode('utf-8'))
        directory = save_snapshot(case, snapshot)
        trusted = safe_path(case.root, 'artifacts/trusted')
        trusted.mkdir(exist_ok=True)
        runner = Path(__file__).with_name('runner.py').read_bytes()
        for name, data in [('runner.py', runner), ('test_clamp.py', TEST_SOURCE)]:
            target = safe_path(trusted, name)
            if target.exists() and target.read_bytes() != data:
                fail('TRUSTED_ARTIFACT', 'verify', 'trusted runner artifact changed')
            target.write_bytes(data)
        name = 'provenance-' + case.case_id + '-' + uuid.uuid4().hex[:12]
        argv = (self.command, 'run', '--rm', '--name', name, '--network', 'none', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '65534:65534',
                '--cpus', '1', '--memory', '256m', '--pids-limit', '64', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                '--mount', f'type=bind,source={directory / "src"},target=/candidate,readonly',
                '--mount', f'type=bind,source={trusted},target=/trusted,readonly',
                self.image_id, 'python', '-I', '-B', '/trusted/runner.py', suite)
        try:
            result = run_process(argv, case.root, timeout=30)
        finally:
            # A killed Docker client may leave its container running. Scope cleanup to this unique name.
            self._cleanup(case, name)
        outcome, count, failures, errors = 'infrastructure_error', 0, 0, 0
        if not result.timed_out and not result.output_exceeded:
            try:
                data = parse_json(result.stdout)
                counts = [data[k] for k in ('tests_run', 'failures', 'errors')]
                valid = (set(data) == {'suite', 'tests_run', 'failures', 'errors', 'successful', 'candidate_hash', 'tests_hash'}
                         and all(type(n) is int and n >= 0 for n in counts)
                         and data['suite'] == suite and data['tests_run'] == SUITES[suite]
                         and data['candidate_hash'] == snapshot.file_hashes[TARGET]
                         and data['tests_hash'] == digest(TEST_SOURCE) and type(data['successful']) is bool
                         and data['successful'] == (data['failures'] == data['errors'] == 0)
                         and result.returncode == (0 if data['successful'] else 1))
                if valid:
                    count, failures, errors = counts
                    outcome = 'pass' if data['successful'] else 'fail'
            except (ValueError, KeyError, TypeError): pass
        return TestResult(suite, self.image_id, snapshot.snapshot_hash, snapshot.file_hashes[TARGET], count,
                          failures, errors, result.returncode, result.elapsed_ms, outcome,
                          result.stdout.decode('utf-8', errors='replace'), result.stderr.decode('utf-8', errors='replace'))

    def _cleanup(self, case, name):
        def absent(result):
            return (not result.timed_out and not result.output_exceeded and result.returncode != 0
                    and b'no such container' in result.stderr.lower())
        diagnostics = []
        for attempt in range(2):
            try:
                result = run_process((self.command, 'rm', '--force', name), case.root, timeout=10)
            except OSError as error:
                diagnostics.append(str(error)[:500])
                continue
            if (result.returncode == 0 and not result.timed_out and not result.output_exceeded) or absent(result):
                return
            diagnostics.append(result.stderr.decode('utf-8', errors='replace')[:500] or 'cleanup timeout/output failure')
        payload = {'container_name': name, 'cleanup': 'unconfirmed', 'diagnostics': diagnostics}
        safe_path(case.root, 'artifacts/cleanup-' + name + '.json').write_bytes(canonical_json(payload))
        fail('CONTAINER_CLEANUP', 'verify', 'Could not confirm removal of owned container ' + name + ': ' + '; '.join(diagnostics))


def record_test(runtime, observer, verifier_handle, action_id, result, artifact_refs):
    action = runtime.store.get(action_id)
    if (result.suite not in SUITES or action.kind != 'ProposedAction'
            or result.snapshot_hash != action.payload['arguments']['candidate_snapshot']
            or result.candidate_hash != digest(action.payload['arguments']['patch_content'].encode())):
        fail('VERIFICATION_BINDING', 'verify', 'test result does not bind this exact action and candidate')
    payload = result.payload()
    payload.update(action_id=action_id, artifacts=artifact_refs)
    observation = runtime.observe(observer, payload)
    verification = runtime.verify(verifier_handle, action_id, result.suite, result.passed, (observation,))
    return observation, verification
