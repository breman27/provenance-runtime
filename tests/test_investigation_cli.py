import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from provenance.__main__ import main
from provenance.clients.repo_repair.coordinator import InvestigationReport
from provenance.clients.repo_repair.report import render_report
from tests.test_investigation_flow import DeterministicVerifier
from tests.investigation_support import decision_dict


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.responses = self.root / 'responses.json'
        self.responses.write_text(json.dumps([decision_dict()]), encoding='utf-8')
    def tearDown(self): self.tmp.cleanup()
    def invoke(self, extra=(), responses=None):
        out, err = io.StringIO(), io.StringIO()
        arguments = ['investigate', '--agent', 'recorded', '--responses', str(responses or self.responses),
                     '--case-dir', str(self.root / 'case'), *extra]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch('provenance.clients.repo_repair.report.DockerVerifier', DeterministicVerifier):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_default_readable_and_json_output(self):
        code, out, err = self.invoke()
        self.assertEqual(code, 0)
        self.assertIn('Recorded reasoning', out)
        self.assertIn('CLAIMED', out)
        self.assertIn('TESTED', out)
        self.assertIn('ACCEPTED', out)
        self.assertIn('--- a/src/clamp.py', out)
        self.assertIn('Checking prerequisites', err)
        self.assertTrue((self.root / 'case' / 'report.md').exists())
        self.root = self.root / 'json'; self.root.mkdir()
        code, out, _ = self.invoke(('--json',))
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)['live_agent'])

    def test_unresolved_refused_and_error_exit_codes(self):
        self.responses.write_text(json.dumps([decision_dict(None)]), encoding='utf-8')
        code, out, _ = self.invoke()
        self.assertEqual(code, 4)
        self.assertIn('UNRESOLVED', out)
        self.root = self.root / 'wrong'; self.root.mkdir()
        self.responses.write_text(json.dumps([decision_dict('def clamp(value, lower, upper):\n    return lower\n')]), encoding='utf-8')
        code, out, _ = self.invoke(('--max-rounds', '1'))
        self.assertEqual(code, 3)
        self.assertIn('REFUSED', out)
        self.root = self.root / 'error'; self.root.mkdir()
        self.responses.write_text('invalid', encoding='utf-8')
        code, out, _ = self.invoke(('--json',))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['outcome'], 'ERROR')
        self.assertFalse((self.root / 'case').exists())

    def test_invalid_cli_combinations_before_case_write(self):
        for args in [['investigate', '--agent', 'recorded', '--case-dir', str(self.root / 'case')],
                     ['investigate', '--agent', 'recorded', '--case-dir', str(self.root / 'case'), '--responses', str(self.responses), '--model', 'x']]:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(raised.exception.code, 2)
        self.assertFalse((self.root / 'case').exists())

    def test_existing_case_preserved(self):
        (self.root / 'case').mkdir()
        sentinel = self.root / 'case' / 'keep'; sentinel.write_text('keep')
        code, out, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('CASE_EXISTS', out)
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_redirected_markdown_report_preserves_error_in_safe_json(self):
        original = Path.is_symlink
        def redirected(path): return path.name == 'report.md' or original(path)
        with patch.object(Path, 'is_symlink', redirected):
            code, out, _ = self.invoke(('--json',))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)['error']['stage'], 'report')
        persisted = json.loads((self.root / 'case' / 'report.json').read_bytes())
        self.assertEqual(persisted['outcome'], 'ERROR')
        self.assertEqual(persisted['error']['stage'], 'report')
        self.assertFalse((self.root / 'case' / 'report.md').exists())

    def test_readable_hint_later_interpretation_and_backend(self):
        report = InvestigationReport('REFUSED', 'codex', True, 'case', 'stale-source',
             rounds=[dict(round=1, claim_statement='First claim', summary='First summary', claim_id='a', action_id='b'),
                     dict(round=2, claim_statement='Later claim', summary='Later summary', claim_id='c', action_id=None)],
             human_hint='Check the revision', reason='Stale evidence')
        text = render_report(report)
        for value in ('Live Codex reasoning', 'First claim', 'Later claim', 'Check the revision', 'REFUSED', 'Stale evidence'):
            self.assertIn(value, text)
