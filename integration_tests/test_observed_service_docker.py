"""Real service runs and agent-tool replays; missing Docker is an error."""
import json
import tempfile
import unittest
from pathlib import Path
from provenance import Store, why
from provenance.clients.repo_repair.case import digest
from provenance.clients.observed_service.agent import RecordedServiceAgent
from provenance.clients.observed_service.experiment import ServiceVerifier, run_experiment


class ObservedServiceDockerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = ServiceVerifier()
        cls.verifier.preflight()
    def test_real_deployments_logs_tools_candidate_and_receipt(self):
        responses = json.loads(Path('examples/recorded-service-regression.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'regression'
            report = run_experiment(root, RecordedServiceAgent(responses), self.verifier)
            self.assertEqual(report['outcome'], 'ACCEPTED', report['reason'])
            self.assertEqual(report['service_runs'][0]['outputs'], [12,0,50,100,100,100])
            self.assertEqual(report['service_runs'][1]['outputs'], [12,0,50,100,125,200])
            with Store(root/'history.db') as store:
                for alias in ('logs_before', 'logs_current'):
                    observation = store.get(report['evidence'][alias])
                    self.assertEqual(observation.payload['executor'], 'docker-linux-restricted')
                    self.assertEqual(observation.payload['image_id'], self.verifier.image_id)
                    saved = [json.loads(line) for line in (root/observation.payload['artifact']).read_text().splitlines()]
                    self.assertEqual(saved, observation.payload['entries'])
                    self.assertEqual(digest((root/observation.payload['artifact']).read_bytes()), observation.payload['stdout_hash'])
                self.assertTrue(store.validate(report['effect_id']).ok)
                trace = why(store, report['effect_id'], 'execution')
                self.assertTrue(all(s == 'VALID' for s in trace.statuses.values()))
                self.assertEqual(sum(store.get(i).kind == 'Effect' for i in store.all_ids()), 1)
            current_tests = [t for t in report['tests'] if t['phase']=='agent-step-4']
            self.assertTrue(all(t['outcome']=='fail' for t in current_tests))
            candidate_tests = [t for t in report['tests'] if t['phase']=='candidate']
            self.assertEqual([t['tests_run'] for t in candidate_tests], [1,8])
            self.assertTrue(all(t['outcome']=='pass' for t in candidate_tests))
    def test_real_healthy_control_has_no_effect(self):
        responses = json.loads(Path('examples/recorded-service-healthy.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'healthy'
            report = run_experiment(root, RecordedServiceAgent(responses), self.verifier, scenario='healthy')
            self.assertEqual(report['outcome'], 'HEALTHY', report['reason'])
            self.assertIsNone(report['effect_id'])
            self.assertTrue(all(t['outcome']=='pass' for t in report['tests']))
