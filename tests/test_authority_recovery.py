import json
import os
import subprocess
import sys
import unittest

from provenance import Store, why, status
from provenance.clients.authority.manager import ApprovalManager
from tests import test_authority_manager as lifecycle


class RecoveryTests(unittest.TestCase):
    setUp = lifecycle.ManagerTests.setUp
    count = lifecycle.ManagerTests.count

    def command(self, name):
        return [sys.executable, '-m', 'tests.authority_process', str(self.session.root), name, self.action]

    def run_cold(self, name, expected=0):
        proc = subprocess.run(self.command(name), capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, expected, proc.stderr)
        return json.loads(proc.stdout) if expected == 0 else None

    def test_cold_approval_admission_and_cli_need_no_provider(self):
        # These fresh processes use current UTC, not this test's deterministic clock.
        grant = self.run_cold('approve')
        self.assertEqual(grant['state'], 'APPROVED')
        self.assertIsNone(grant['effect_id'])
        receipt = self.run_cold('admit')
        self.assertEqual(receipt['state'], 'COMMITTED')
        self.assertTrue(self.run_cold('admit')['reused'])
        with Store(self.session.database) as store:
            self.assertTrue(all(store.validate(i).ok for i in store.all_ids()))
            trace = why(store, receipt['effect_id'], 'execution')
            self.assertTrue(all(value == 'VALID' for value in trace.statuses.values()))
        code = ('import sys;sys.modules["provenance.clients.observed_service.agent"]=None;'
                'sys.modules["provenance.clients.repo_repair.openai_worker"]=None;'
                'from provenance.__main__ import main;raise SystemExit(main(sys.argv[1:]))')
        env = {k: v for k,v in os.environ.items() if k != 'OPENAI_API_KEY'}
        result = subprocess.run([sys.executable, '-c', code, 'authority', 'inspect', '--session-dir',
                                 str(self.session.root), '--action', self.action, '--json'], env=env,
                                 capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_concurrent_approvals_and_admissions_yield_one_grant_one_effect(self):
        for command, kind in (('approve', 'Authority'), ('admit', 'Effect')):
            processes = [subprocess.Popen(self.command(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
            results = []
            try:
                for proc in processes:
                    out, err = proc.communicate(timeout=25)
                    self.assertEqual(proc.returncode, 0, err)
                    results.append(json.loads(out))
            finally:
                for proc in processes:
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()
            self.assertEqual(self.count(kind), 1)
            ids = {r['authority_id'] if kind == 'Authority' else r['effect_id'] for r in results}
            self.assertEqual(len(ids), 1)
            self.assertEqual(sum(not r['reused'] for r in results), 1)

    def test_process_exit_between_denial_and_invalidation_cannot_rescue_old_grant(self):
        old = self.run_cold('approve')['authority_id']
        self.run_cold('deny-before-invalidate', expected=91)
        result = self.run_cold('admit')
        self.assertEqual(result['state'], 'DENIED')
        self.assertEqual(self.count('Effect'), 0)
        self.assertEqual(status(self.store, old, 'execution'), 'INVALID')

    def test_process_exit_after_invalidation_reconciles_supersession(self):
        old = self.run_cold('approve')['authority_id']
        self.run_cold('deny-before-supersede', expected=91)
        self.assertEqual(self.run_cold('admit')['state'], 'DENIED')
        self.assertEqual(self.count('Effect'), 0)
        self.assertTrue(any(self.store.get(i).kind == 'Supersession' for i in self.store.child_ids(old)))

    def test_process_exit_during_renewal_reconciles_without_recovery_effect(self):
        old = self.run_cold('approve')['authority_id']
        self.run_cold('renew-before-supersede', expected=91)
        current = self.run_cold('approve')
        self.assertNotEqual(current['authority_id'], old)
        self.assertTrue(current['reused'])
        self.assertEqual(status(self.store, old, 'execution'), 'SUPERSEDED')
        self.assertEqual(self.count('Effect'), 0)
