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
from provenance.clients.repo_repair.openai_agent import DEFAULT_MODEL
from provenance.clients.repo_repair.process import ProcessResult


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
        self.assertIn('## Claims', out)
        self.assertIn('## Verifications', out)
        self.assertIn('ACCEPTED', out)
        self.assertIn('Proposed replacement for `src/clamp.py`', out)
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

    def test_openai_mode_uses_same_gate_and_labels_api_provider(self):
        def result(value): return ProcessResult(0, json.dumps(value).encode(), b'', 1, False, False)
        responses = [result({'status': 'ok', 'model': DEFAULT_MODEL}),
                     result({'status': 'ok', 'output_text': json.dumps(decision_dict()), 'metadata': {'model': DEFAULT_MODEL, 'tokens': {}}})]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
             patch('provenance.clients.repo_repair.report.DockerVerifier', DeterministicVerifier), \
             patch('provenance.clients.repo_repair.openai_agent.run_process', side_effect=responses):
            code = main(['investigate', '--agent', 'openai', '--case-dir', str(self.root / 'api'), '--json'])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report['backend'], 'openai')
        self.assertTrue(report['live_agent'])
        self.assertEqual(report['outcome'], 'ACCEPTED')
        self.assertIn('API', err.getvalue())
        self.assertIn('Live OpenAI API reasoning', (self.root / 'api' / 'report.md').read_text(encoding='utf-8'))

    def test_live_preflight_failure_does_not_claim_completed_reasoning(self):
        report = InvestigationReport('ERROR', 'openai', True, 'case', 'normal', error={'code':'API_KEY_MISSING', 'stage':'preflight', 'detail':'missing'})
        text = render_report(report)
        self.assertIn('OpenAI API mode', text)
        self.assertIn('no completed model response', text)
        self.assertNotIn('Live Codex reasoning', text)

    def test_json_is_utf8_even_when_stdout_text_encoding_is_ascii(self):
        self.responses.write_text(json.dumps([dict(decision_dict(), summary='Réparation — correct')]), encoding='utf-8')
        raw = io.BytesIO()
        output = io.TextIOWrapper(raw, encoding='ascii', write_through=True)
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()), \
             patch('provenance.clients.repo_repair.report.DockerVerifier', DeterministicVerifier):
            code = main(['investigate', '--agent', 'recorded', '--responses', str(self.responses), '--case-dir', str(self.root / 'utf8'), '--json'])
        self.assertEqual(code, 0)
        value = json.loads(raw.getvalue().decode('utf-8'))
        self.assertEqual(value['rounds'][0]['summary'], 'Réparation — correct')
