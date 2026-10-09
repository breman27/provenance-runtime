import json
import random
import tempfile
import unittest
from pathlib import Path

from provenance import Store
from provenance.clients.authority.manager import ApprovalManager
from provenance.clients.observed_service.agent import RecordedServiceAgent, tools
from provenance.clients.observed_service.experiment import run_experiment
from provenance.clients.observed_service.watch import ServiceWatcher
from provenance.clients.repo_repair.case import GOOD_SOURCE, BAD_SOURCE, TARGET, digest
from provenance.clients.repo_repair.errors import InvestigationError
from tests.test_observed_service import steps, FakeServiceVerifier
from tests import test_service_watch as watch_tests


class ClientApprovalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)/'case'

    def test_manual_checks_wait_then_cold_operator_can_approve_and_admit(self):
        report = run_experiment(self.root, RecordedServiceAgent(steps()), FakeServiceVerifier(), approval_mode='manual')
        self.assertEqual(report['outcome'], 'AWAITING_APPROVAL', report['reason'])
        self.assertIsNone(report['authority_id'])
        self.assertIsNone(report['effect_id'])
        self.assertTrue(report['approval_context_observation_id'])
        manager = ApprovalManager(self.root)
        self.assertEqual(manager.approve(report['action_id']).state, 'APPROVED')
        self.assertEqual(manager.admit(report['action_id']).state, 'COMMITTED')
        for packet in self.root.glob('agent-view/*/input.json'):
            self.assertNotIn('approval-context', packet.read_text(encoding='utf-8'))
        self.assertEqual({t['name'] for t in tools()}, {'read_logs', 'read_source', 'read_diff', 'run_tests', 'finish'})

    def test_explicit_and_sdk_default_auto_remain_accepted(self):
        for index, kwargs in enumerate(({}, {'approval_mode': 'auto'})):
            report = run_experiment(self.root.with_name('auto'+str(index)), RecordedServiceAgent(steps()), FakeServiceVerifier(), **kwargs)
            self.assertEqual(report['outcome'], 'ACCEPTED', report['reason'])

    def test_healthy_inconclusive_and_failed_candidates_do_not_enter_queue(self):
        for index, (responses, scenario) in enumerate(((steps('healthy', None), 'healthy'),
                (steps('inconclusive', None), 'regression'), (steps(patch_content=BAD_SOURCE.decode()+'\n'), 'regression'))):
            root = self.root.with_name('case'+str(index))
            report = run_experiment(root, RecordedServiceAgent(responses), FakeServiceVerifier(), scenario, approval_mode='manual')
            self.assertNotEqual(report['outcome'], 'AWAITING_APPROVAL')
            self.assertEqual(ApprovalManager(root).list(include_all=True), ())


class RepairAgent(watch_tests.WatchAgent):
    def step(self, *args, **kwargs):
        call, arguments, metadata = super().step(*args, **kwargs)
        if call['name'] == 'finish':
            arguments.update(assessment='regression', patch_content=GOOD_SOURCE.decode())
        return call, arguments, metadata


class PendingVerifier(watch_tests.WatchVerifier):
    def run_service(self, snapshot, case, readings, allow_failure):
        payload = super().run_service(snapshot, case, readings, allow_failure)
        if snapshot.files[TARGET] != GOOD_SOURCE:
            for entry in payload['entries']:
                entry['output'] = max(0, entry['input'])
            payload['stdout'] = ''.join(json.dumps(e)+'\n' for e in payload['entries'])
            payload['stdout_hash'] = digest(payload['stdout'].encode('utf-8'))
        return payload


class WatchApprovalTests(unittest.TestCase):
    setUp = watch_tests.ServiceWatchTests.setUp
    tearDown = watch_tests.ServiceWatchTests.tearDown
    events = watch_tests.ServiceWatchTests.events
    wait_agent = watch_tests.ServiceWatchTests.wait_agent

    def test_queue_survives_stop_and_collection_continues_with_multiple_proposals(self):
        (self.repo/TARGET).write_bytes(BAD_SOURCE)
        self.watcher = ServiceWatcher(self.repo, self.root/'session', PendingVerifier(), RepairAgent(),
            random_source=random.Random(5), output=lambda *a, **k: None, approval_mode='manual')
        self.watcher.start()
        self.watcher.tick()
        self.wait_agent()
        manager = ApprovalManager(self.root/'session')
        first = manager.list()[0]
        self.assertEqual(first.state, 'AWAITING_APPROVAL')
        self.watcher.tick()
        self.assertEqual(self.watcher.sequence, 2)
        (self.repo/TARGET).write_bytes(BAD_SOURCE+b'# second captured version\n')
        self.watcher.tick()
        self.wait_agent()
        all_rows = manager.list(include_all=True)
        self.assertEqual(len(all_rows), 2)
        self.assertEqual({r.state for r in all_rows}, {'STALE', 'AWAITING_APPROVAL'})
        self.assertTrue(any(e['event'] == 'APPROVAL_PENDING' and e['action_id'] == first.action_id for e in self.events()))
        self.watcher.close()
        self.watcher = None
        self.assertEqual(len(ApprovalManager(self.root/'session').list()), 1)
        current = manager.list()[0]
        (self.repo/TARGET).write_bytes(GOOD_SOURCE)
        with self.assertRaises(InvestigationError) as caught:
            manager.approve(current.action_id)
        self.assertEqual(caught.exception.code, 'STALE')
