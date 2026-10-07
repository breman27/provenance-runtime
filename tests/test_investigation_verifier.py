import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from provenance import Store
from provenance.clients.repo_repair.case import prepare_case, capture_snapshot, collect_source, candidate_snapshot, TARGET, digest, TEST_SOURCE
from provenance.clients.repo_repair.contract import AgentRequest, AgentRun, decode_decision, admit_decision
from provenance.clients.repo_repair.errors import InvestigationError
from provenance.clients.repo_repair.process import ProcessResult, run_process
from provenance.clients.repo_repair.verifier import DockerVerifier, record_test
from tests.investigation_support import runtime, decision_dict, CORRECT_PATCH


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.case = prepare_case(Path(self.tmp.name) / 'case')
        self.snapshot = candidate_snapshot(capture_snapshot(self.case, self.case.baseline_revision), CORRECT_PATCH.encode())
        self.store = Store(self.case.database)
        self.runtime = runtime(self.store)
        self.verifier = DockerVerifier()
        self.verifier.image_id = 'sha256:' + 'a' * 64

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def output(self, **updates):
        data = dict(suite='targeted_tests', tests_run=1, failures=0, errors=0, successful=True,
                    candidate_hash=self.snapshot.file_hashes[TARGET], tests_hash=digest(TEST_SOURCE))
        data.update(updates)
        return json.dumps(data).encode()

    def process(self, output=None, code=0, timeout=False, overflow=False):
        return ProcessResult(code, self.output() if output is None else output, b'', 10, timeout, overflow)

    def test_pass_fail_and_unusable_results(self):
        for process, expected in [(self.process(), True), (self.process(self.output(failures=1, successful=False), 1), False),
                                  (self.process(self.output(tests_run=0)), False), (self.process(b'garbage'), False),
                                  (self.process(code=1), False), (self.process(timeout=True), False),
                                  (self.process(overflow=True), False), (self.process(self.output(suite='full_suite')), False),
                                  (self.process(self.output(candidate_hash='wrong')), False)]:
            with self.subTest(process=process), patch('provenance.clients.repo_repair.verifier.run_process', return_value=process):
                result = self.verifier.test(self.snapshot, self.case, 'targeted_tests')
                self.assertEqual(result.passed, expected)

    def test_docker_boundaries_and_owned_cleanup(self):
        with patch('provenance.clients.repo_repair.verifier.run_process', return_value=self.process(timeout=True)) as call:
            self.verifier.test(self.snapshot, self.case, 'targeted_tests')
        argv = call.call_args_list[0].args[0]
        for option, value in [('--network', 'none'), ('--user', '65534:65534'), ('--cpus', '1'),
                              ('--memory', '256m'), ('--pids-limit', '64'), ('--cap-drop', 'ALL')]:
            self.assertEqual(argv[argv.index(option) + 1], value)
        self.assertIn('--read-only', argv)
        self.assertIn('no-new-privileges', argv)
        mounts = [argv[i+1] for i, arg in enumerate(argv) if arg == '--mount']
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all('readonly' in mount for mount in mounts))
        name = argv[argv.index('--name') + 1]
        self.assertTrue(name.startswith('provenance-' + self.case.case_id))
        self.assertEqual(call.call_args_list[-1].args[0], ('docker', 'rm', '--force', name))
        self.assertEqual(argv[argv.index(self.verifier.image_id) + 1], 'python')

    def test_preflight_requires_linux_engine_and_image(self):
        bad = self.process(b'', code=1)
        with patch('provenance.clients.repo_repair.verifier.run_process', return_value=bad):
            with self.assertRaises(InvestigationError): DockerVerifier().preflight()
        windows = self.process(b'{"Os":"windows"}')
        with patch('provenance.clients.repo_repair.verifier.run_process', return_value=windows):
            with self.assertRaises(InvestigationError): DockerVerifier().preflight()
        linux = self.process(b'{"Os":"linux"}')
        with patch('provenance.clients.repo_repair.verifier.run_process', side_effect=[linux, bad, bad]):
            with self.assertRaises(InvestigationError): DockerVerifier().preflight()

    def test_record_binds_exact_action_and_hashes(self):
        evidence = collect_source(self.runtime, self.runtime.observer('collector'), self.case, self.case.baseline_revision, 'source')
        request = AgentRequest('repair', {}, (evidence,), (), 1)
        run = AgentRun(decode_decision(json.dumps(decision_dict()).encode(), (evidence,)), 'recorded', False, {})
        _, action = admit_decision(self.runtime, self.case, capture_snapshot(self.case, self.case.baseline_revision), request, run)
        with patch('provenance.clients.repo_repair.verifier.run_process', return_value=self.process()):
            result = self.verifier.test(self.snapshot, self.case, 'targeted_tests')
        for wrong in [replace(result, candidate_hash='wrong'), replace(result, snapshot_hash='wrong'), replace(result, suite='bad')]:
            with self.assertRaises(InvestigationError):
                record_test(self.runtime, self.runtime.observer('collector'), self.runtime.verifier('tester'), action, wrong, {})
        observation, verification = record_test(self.runtime, self.runtime.observer('collector'), self.runtime.verifier('tester'), action, result, {})
        self.assertEqual([p.node_id for p in self.store.get(verification).parents if p.role == 'subject'], [action])
        self.assertEqual(self.store.get(observation).payload['candidate_hash'], self.snapshot.file_hashes[TARGET])
        self.assertTrue(self.store.get(verification).payload['passed'])


class ProcessTests(unittest.TestCase):
    def test_output_timeout_and_overflow(self):
        cwd = Path(tempfile.gettempdir())
        normal = run_process((sys.executable, '-c', 'import sys; print("ok"); print("err", file=sys.stderr)'), cwd)
        self.assertEqual(normal.returncode, 0)
        self.assertIn(b'ok', normal.stdout)
        self.assertIn(b'err', normal.stderr)
        timeout = run_process((sys.executable, '-c', 'import time; time.sleep(10)'), cwd, timeout=0.1)
        self.assertTrue(timeout.timed_out)
        overflow = run_process((sys.executable, '-c', 'print("x" * 10000)'), cwd, max_output=100)
        self.assertTrue(overflow.output_exceeded)
        self.assertLessEqual(len(overflow.stdout) + len(overflow.stderr), 100)
