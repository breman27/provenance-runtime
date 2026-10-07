"""Regressions for the independent review's four boundary findings."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from provenance.clients.repo_repair.agent import RecordedAgent
from provenance.clients.repo_repair.case import prepare_case, capture_snapshot, save_snapshot
from provenance.clients.repo_repair.contract import validate_patch, AgentRequest
from provenance.clients.repo_repair.coordinator import InvestigationOptions, run_investigation
from provenance.clients.repo_repair.errors import InvestigationError
from provenance.clients.repo_repair.process import run_process, ProcessResult
from provenance.clients.repo_repair.verifier import DockerVerifier
from tests.test_investigation_flow import DeterministicVerifier
from tests.investigation_support import decision_dict


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_nested_functions_and_builtin_shadowing_are_rejected(self):
        candidates = ['def clamp(value, lower, upper):\n    def min(value, lower):\n        return value\n    return min(value, upper)\n',
                      'def clamp(value, lower, upper):\n    def max(value, lower):\n        return max(value, lower)\n    return max(value, lower)\n']
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(InvestigationError): validate_patch(candidate)

    def test_deadline_covers_child_pipes_after_parent_exit(self):
        code = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time; time.sleep(2)"])'
        result = run_process((sys.executable, '-c', code), self.root, timeout=0.1)
        self.assertTrue(result.timed_out)
        self.assertLess(result.elapsed_ms, 1000)

    def test_failed_container_removal_is_reported_with_owned_name(self):
        case = prepare_case(self.root / 'case')
        snapshot = capture_snapshot(case, case.baseline_revision)
        verifier = DockerVerifier(); verifier.image_id = 'sha256:' + 'a' * 64
        timeout = ProcessResult(1, b'', b'timeout', 30, True, False)
        failed_remove = ProcessResult(1, b'', b'daemon unavailable', 10, False, False)
        with patch('provenance.clients.repo_repair.verifier.run_process', side_effect=[timeout, failed_remove, failed_remove]):
            with self.assertRaises(InvestigationError) as raised: verifier.test(snapshot, case, 'targeted_tests')
        self.assertEqual(raised.exception.code, 'CONTAINER_CLEANUP')
        self.assertIn('provenance-' + case.case_id, raised.exception.detail)
        self.assertIn('daemon unavailable', raised.exception.detail)

    def test_already_removed_container_is_distinguished_from_failure(self):
        case = prepare_case(self.root / 'case')
        snapshot = capture_snapshot(case, case.baseline_revision)
        verifier = DockerVerifier(); verifier.image_id = 'sha256:' + 'a' * 64
        timeout = ProcessResult(1, b'', b'timeout', 30, True, False)
        gone = ProcessResult(1, b'', b'Error response from daemon: No such container: owned', 1, False, False)
        with patch('provenance.clients.repo_repair.verifier.run_process', side_effect=[timeout, gone]):
            self.assertFalse(verifier.test(snapshot, case, 'targeted_tests').passed)

    def test_redirected_round_directory_preserves_external_folder(self):
        outside = self.root / 'outside'; outside.mkdir()
        redirect = self.root / 'redirect'
        if os.name == 'nt':
            result = subprocess.run(('cmd', '/c', 'mklink', '/J', str(redirect), str(outside)), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else: redirect.symlink_to(outside, target_is_directory=True)
        request = AgentRequest('repair', '', (), (), 1)
        with self.assertRaises(InvestigationError):
            RecordedAgent((json.dumps(decision_dict()).encode(),)).propose(request, redirect / 'round')
        self.assertEqual(list(outside.iterdir()), [])

    def test_trusted_runner_leaf_and_snapshot_manifest_redirects_are_rejected(self):
        # Windows requires extra privilege for file symlinks; inject the exact dangling
        # link metadata at the leaf. The ancestor junction test above uses a real redirect.
        case = prepare_case(self.root / 'case')
        snapshot = capture_snapshot(case, case.good_revision)
        verifier = DockerVerifier(); verifier.image_id = 'sha256:' + 'a' * 64
        original = Path.is_symlink
        for name in ('runner.py', 'snapshot.json'):
            def redirected(path): return path.name == name or original(path)
            with patch.object(Path, 'is_symlink', redirected), patch('provenance.clients.repo_repair.verifier.run_process', return_value=ProcessResult(0, b'', b'', 1, False, False)):
                with self.assertRaises(InvestigationError) as raised:
                    if name == 'runner.py': verifier.test(snapshot, case, 'targeted_tests')
                    else: save_snapshot(case, snapshot)
                self.assertEqual(raised.exception.code, 'CASE_PATH')

    def test_redirected_report_leaf_returns_error_without_overwrite(self):
        original = Path.is_symlink
        def redirected(path): return path.name == 'report.json' or original(path)
        with patch.object(Path, 'is_symlink', redirected):
            report = run_investigation(InvestigationOptions(self.root / 'case'),
                                      RecordedAgent((json.dumps(decision_dict()).encode(),)), DeterministicVerifier())
        self.assertEqual(report.outcome, 'ERROR')
        self.assertEqual(report.error['stage'], 'report')
        self.assertFalse((self.root / 'case' / 'report.json').exists())
