import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from provenance.__main__ import main
from provenance import import_graph, make_node, Parent
from provenance.format import canonical_json, parse_json
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

    def test_source_refusal_refreshes_recorded_state_in_operator_report(self):
        self.run_command('approve')
        (self.case.repository/'src/clamp.py').write_bytes(b'changed')
        code, data = self.run_command('admit')
        self.assertEqual(code, 3)
        self.assertEqual(data['error']['code'], 'STALE')
        self.assertEqual(data['result']['state'], 'STALE')
        saved = json.loads((self.case.root/'authority-report.json').read_bytes())
        self.assertEqual(saved['state'], 'STALE')

    def test_imported_decision_metadata_stays_untrusted_and_cannot_crash_reports(self):
        from datetime import timedelta
        action = self.store.get(self.action)
        for index, metadata in enumerate(({'reason': 'imported note'}, 'imported annotation',
                {'sequence': 'imported string', 'reason': 'untrusted'},
                {'sequence': 999, 'reason': 'imported complete-looking history'})):
            node = make_node('Authority', {'issuer_id': 'human-operator', 'subject': 'observed-service',
                'action_id': self.action, 'action_type': action.payload['action_type'], 'resource': action.payload['resource'],
                'allowed': True, 'expires_at': '2026-10-10T00:00:00.000000Z', 'decision': metadata},
                [Parent('subject', self.action)], 'human-operator', self.runtime.clock()+timedelta(seconds=index))
            import_graph(self.store, canonical_json({'format': 'provenance-runtime-export', 'version': '0.1',
                'nodes': [{'id': node.id, 'body': parse_json(node.canonical_body)}]}))
        code, result = self.run_command('inspect')
        self.assertEqual(code, 0)
        self.assertEqual(result['state'], 'AWAITING_APPROVAL')
        code, readable = self.run_command('inspect', json_output=False)
        self.assertEqual(code, 0)
        self.assertIn('imported note', readable)
        history = readable.split('## Operator decision history')[1]
        self.assertIn('No operator decision has been recorded', history)
        self.assertNotIn('imported', history)
        self.assertEqual(self.run_command('approve')[1]['state'], 'APPROVED')
        code, result = self.run_command('admit')
        self.assertEqual(code, 0)
        self.assertEqual(result['state'], 'COMMITTED')

    def test_json_inspection_and_persisted_results_survive_markdown_failure(self):
        with patch('provenance.clients.authority.cli.render_authority_report', side_effect=ValueError('render failure')):
            self.assertEqual(self.run_command('inspect')[0], 0)
            code, result = self.run_command('approve')
            self.assertEqual(code, 1)
            self.assertEqual(result['error']['code'], 'REPORT_WRITE')
            self.assertEqual(result['result']['state'], 'APPROVED')
            code, result = self.run_command('admit')
            self.assertEqual(code, 1)
            self.assertEqual(result['result']['state'], 'COMMITTED')
            self.assertTrue(result['result']['effect_id'])

    def test_cli_manual_default_and_explicit_auto(self):
        with patch('provenance.clients.observed_service.cli.run_cli', return_value=0) as run:
            main(['observe-service', '--agent', 'recorded', '--responses', 'unused.json', '--case-dir', 'unused'])
            self.assertEqual(run.call_args.args[0].approval, 'manual')
            main(['observe-service', '--agent', 'recorded', '--responses', 'unused.json', '--case-dir', 'unused', '--approval', 'auto'])
            self.assertEqual(run.call_args.args[0].approval, 'auto')
