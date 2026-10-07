"""Capture real fixture revisions into immutable, private case artifacts."""
import hashlib
import os
import re
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from ...format import canonical_json, parse_json
from .errors import fail

TARGET = "src/clamp.py"
TEST_PATH = "tests/test_clamp.py"
GOOD_SOURCE = b"def clamp(value: int, lower: int, upper: int) -> int:\n    return max(lower, min(value, upper))\n"
BAD_SOURCE = b"def clamp(value: int, lower: int, upper: int) -> int:\n    if value < lower:\n        return lower\n    return value\n"
TEST_SOURCE = b'''import unittest
from clamp import clamp

class ClampTests(unittest.TestCase):
    def check(self, value, lower, upper, expected):
        result = clamp(value, lower, upper)
        self.assertIs(type(result), int)
        self.assertEqual(result, expected)
    def test_above_upper(self): self.check(15, 0, 10, 10)
    def test_below_lower(self): self.check(-5, 0, 10, 0)
    def test_within_bounds(self): self.check(5, 0, 10, 5)
    def test_exact_lower(self): self.check(0, 0, 10, 0)
    def test_exact_upper(self): self.check(10, 0, 10, 10)
    def test_equal_bounds(self): self.check(7, 4, 4, 4)
    def test_negative_interval(self): self.check(-3, -10, -5, -5)
    def test_large_bounded_input(self): self.check(1000, -100, 100, 100)
'''


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _no_redirect(path):
    current = Path(os.path.abspath(path))
    for component in (current, *current.parents):
        if component.is_symlink():
            fail("CASE_PATH", "case", "case paths cannot contain symlinks")
        try:
            attrs = getattr(component.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            continue
        if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            fail("CASE_PATH", "case", "case paths cannot contain redirected directories")


def safe_path(root: Path, relative: str) -> Path:
    part = Path(relative)
    if part.is_absolute() or part.drive or part.root or ".." in part.parts:
        fail("CASE_PATH", "case", "artifact path must stay beneath its case")
    candidate = root / part
    _no_redirect(candidate)
    if not candidate.resolve().is_relative_to(root.resolve()):
        fail("CASE_PATH", "case", "artifact path escaped its case")
    return candidate


@dataclass(frozen=True)
class CasePaths:
    root: Path
    repository: Path
    artifacts: Path
    agent_view: Path
    database: Path
    case_id: str
    good_revision: str
    baseline_revision: str


@dataclass(frozen=True, init=False)
class Snapshot:
    revision: str
    _files: tuple
    _hashes: tuple
    snapshot_hash: str

    def __init__(self, revision: str, files: dict[str, bytes], file_hashes: dict[str, str], snapshot_hash: str):
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "_files", tuple(sorted(files.items())))
        object.__setattr__(self, "_hashes", tuple(sorted(file_hashes.items())))
        object.__setattr__(self, "snapshot_hash", snapshot_hash)

    @property
    def files(self):
        return dict(self._files)

    @property
    def file_hashes(self):
        return dict(self._hashes)


@dataclass(frozen=True, init=False)
class Evidence:
    alias: str
    node_id: str
    _payload: bytes

    def __init__(self, alias: str, node_id: str, payload: dict):
        object.__setattr__(self, "alias", alias)
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "_payload", canonical_json(payload))

    @property
    def payload(self):
        return parse_json(self._payload)


def _git(repository, *args, env=None):
    result = subprocess.run(["git", "-C", str(repository), *args], capture_output=True, env=env, timeout=30)
    if result.returncode:
        fail("GIT_FAILED", "collect", result.stderr.decode("utf-8", errors="replace")[:2000])
    return result.stdout


def snapshot_value(revision, files):
    hashes = {name: digest(data) for name, data in files.items()}
    manifest_hash = digest(canonical_json({"revision": revision, "files": hashes}))
    return Snapshot(revision, files, hashes, manifest_hash)


def save_snapshot(case, snapshot):
    directory = safe_path(case.root, "artifacts/snapshots/" + snapshot.snapshot_hash.split(":", 1)[1])
    for name, data in snapshot.files.items():
        target = safe_path(directory, name)
        if target.exists() and target.read_bytes() != data:
            fail("SNAPSHOT_MISMATCH", "collect", "stored snapshot artifact was changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
    manifest = canonical_json({"revision": snapshot.revision, "files": snapshot.file_hashes,
                               "snapshot_hash": snapshot.snapshot_hash})
    metadata = safe_path(directory, 'snapshot.json')
    if metadata.exists() and metadata.read_bytes() != manifest:
        fail("SNAPSHOT_MISMATCH", "collect", "snapshot manifest was changed")
    if not metadata.exists():
        metadata.write_bytes(manifest)
    return directory


def prepare_case(root: Path) -> CasePaths:
    root = Path(os.path.abspath(root))
    _no_redirect(root)
    if root.exists():
        fail("CASE_EXISTS", "case", "case directory already exists; earlier data was preserved")
    root.mkdir(parents=True, exist_ok=False)
    repository, artifacts, agent_view = root / "repository", root / "artifacts", root / "agent-view"
    for relative in ('repository/src', 'repository/tests', 'artifacts', 'agent-view'):
        safe_path(root, relative).mkdir(parents=True, exist_ok=True)
    safe_path(repository, TARGET).write_bytes(GOOD_SOURCE)
    safe_path(repository, TEST_PATH).write_bytes(TEST_SOURCE)
    _git(repository, "init", "--initial-branch=fixture")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "config", "user.name", "Provenance fixture")
    _git(repository, "config", "user.email", "fixture@example.invalid")
    env = dict(os.environ, GIT_AUTHOR_DATE="2026-10-07T00:00:00Z", GIT_COMMITTER_DATE="2026-10-07T00:00:00Z")
    _git(repository, "add", "src", "tests")
    _git(repository, "commit", "-m", "working clamp", env=env)
    good = _git(repository, "rev-parse", "HEAD").decode().strip()
    safe_path(repository, TARGET).write_bytes(BAD_SOURCE)
    env.update(GIT_AUTHOR_DATE="2026-10-07T00:01:00Z", GIT_COMMITTER_DATE="2026-10-07T00:01:00Z")
    _git(repository, "add", TARGET)
    _git(repository, "commit", "-m", "introduce upper-bound regression", env=env)
    baseline = _git(repository, "rev-parse", "HEAD").decode().strip()
    case = CasePaths(root, repository, artifacts, agent_view, root / "history.db", uuid.uuid4().hex, good, baseline)
    safe_path(root, 'case.json').write_bytes(canonical_json({"case_id": case.case_id, "good_revision": good,
                                                    "baseline_revision": baseline}))
    save_snapshot(case, capture_snapshot(case, baseline))
    return case


def capture_snapshot(case: CasePaths, revision: str) -> Snapshot:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        fail("REVISION", "collect", "source capture requires an immutable Git revision")
    files = {name: _git(case.repository, "show", f"{revision}:{name}") for name in (TARGET, TEST_PATH)}
    return snapshot_value(revision, files)


def collect_source(runtime, observer, case, revision, alias):
    snapshot = capture_snapshot(case, revision)
    directory = save_snapshot(case, snapshot)
    source_time = _git(case.repository, "show", "-s", "--format=%cI", revision).decode().strip()
    payload = {"case_id": case.case_id, "source": "git", "revision": revision, "source_time": source_time,
               "snapshot_hash": snapshot.snapshot_hash, "file_hashes": snapshot.file_hashes,
               "source_text": snapshot.files[TARGET].decode("utf-8"),
               "artifact": directory.relative_to(case.root).as_posix()}
    node_id = runtime.observe(observer, payload)
    return Evidence(alias, node_id, runtime.store.get(node_id).payload)


def collect_diff(runtime, observer, case, before, after, alias):
    capture_snapshot(case, before)
    capture_snapshot(case, after)
    data = _git(case.repository, "diff", before, after, "--", TARGET)
    payload = {"case_id": case.case_id, "source": "git", "before_revision": before, "after_revision": after,
               "diff": data.decode("utf-8"), "diff_hash": digest(data)}
    node_id = runtime.observe(observer, payload)
    return Evidence(alias, node_id, runtime.store.get(node_id).payload)


def candidate_snapshot(baseline: Snapshot, patch: bytes) -> Snapshot:
    files = baseline.files
    files[TARGET] = patch
    return snapshot_value(baseline.revision, files)
