import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from provenance.__main__ import main
from provenance.clients.authority.context import record_context
from tests.authority_support import pending


class AuthorityCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        (self.case, self.store, self.runtime, self.session, self.baseline, self.action,
         self.source, self.checks, self.logs) = pending(Path(temp.name)/'case')
        self.addCleanup(self.store.close)
        record_context(self.session, self.runtime, self.case, self.baseline, self.action, self.source, self.checks)

    def run_command(self, command, *extra, json_output=True):
        argv = ['authority', command, '--session-dir', str(self.session.root)]
        if command not in ('list', 'revoke'):
            argv += ['--action', self.action]
        argv += list(extra)
        if json_output:
            argv += ['--json']
        stream = io.BytesIO()
        stdout = io.TextIOWrapper(stream, encoding='ascii')
        with patch('sys.stdout', stdout), patch('sys.stderr', io.StringIO()):
            code = main(argv)
        stdout.flush()
        data = stream.getvalue().decode('utf-8')
        stdout.detach()
        return code, json.loads(data) if json_output else data

    def test_list_inspect_unicode_grant_and_admit_use_no_agent(self):
        code, rows = self.run_command('list')
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]['state'], 'AWAITING_APPROVAL')
        code, report = self.run_command('inspect', json_output=False)
        self.assertEqual(code, 0)
        self.assertIn('Application permission state: AWAITING_APPROVAL', report)
        self.assertIn('Exact proposed diff', report)
        code, grant = self.run_command('approve', '--reason', 'Révision → accord')
        self.assertEqual(code, 0)
        self.assertIsNone(grant['effect_id'])
        self.assertTrue(grant['authority_id'])
        self.assertIn('Révision', (self.case.root/'authority-report.md').read_text(encoding='utf-8'))
        code, receipt = self.run_command('admit')
        self.assertEqual(code, 0)
        self.assertEqual(receipt['state'], 'COMMITTED')
        self.assertEqual(self.run_command('admit')[1]['effect_id'], receipt['effect_id'])
        self.assertEqual(self.run_command('revoke', '--authority', grant['authority_id'])[0], 0)

    def test_usage_errors_before_writes(self):
        before = self.store.all_ids()
        for extra in (['--issuer', 'human-operator'], ['--ttl-minutes', '0'], ['--ttl-minutes', '61']):
            with self.subTest(extra=extra), self.assertRaises(SystemExit) as caught:
                self.run_command('approve', *extra)
            self.assertEqual(caught.exception.code, 2)
        with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(['authority', 'inspect', '--session-dir', str(self.session.root), '--action', 'P1'])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(before, self.store.all_ids())

    def test_refused_admission_denial_and_list_filtering(self):
        self.assertEqual(self.run_command('admit')[0], 3)
        self.assertEqual(self.run_command('deny')[1]['state'], 'DENIED')
        self.assertEqual(self.run_command('admit')[0], 3)
        self.assertEqual(self.run_command('list')[1], [])
        self.assertEqual(len(self.run_command('list', '--all')[1]), 1)

    def test_missing_db_does_not_create_it(self):
        root = self.session.root/'missing'
        with patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()):
            self.assertEqual(main(['authority', 'list', '--session-dir', str(root)]), 1)
        self.assertFalse((root/'history.db').exists())

    def test_report_failure_reports_persisted_decision(self):
        target = self.case.root/'authority-report.md'
        target.mkdir()
        code, data = self.run_command('approve')
        self.assertEqual(code, 1)
        self.assertEqual(data['error']['code'], 'REPORT_WRITE')
        self.assertTrue(data['result']['authority_id'])
        self.assertEqual(sum(self.store.get(i).kind == 'Authority' for i in self.store.all_ids()), 1)

    def test_cli_manual_default_and_explicit_auto(self):
        with patch('provenance.clients.observed_service.cli.run_cli', return_value=0) as run:
            main(['observe-service', '--agent', 'recorded', '--responses', 'unused.json', '--case-dir', 'unused'])
            self.assertEqual(run.call_args.args[0].approval, 'manual')
            main(['observe-service', '--agent', 'recorded', '--responses', 'unused.json', '--case-dir', 'unused', '--approval', 'auto'])
            self.assertEqual(run.call_args.args[0].approval, 'auto')
