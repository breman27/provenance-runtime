import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from provenance.clients.repo_repair.agent import RecordedAgent, CodexAgent, DISABLED_FEATURES, REQUIRED_FLAGS
from provenance.clients.repo_repair.case import Evidence
from provenance.clients.repo_repair.contract import AgentRequest
from provenance.clients.repo_repair.errors import InvestigationError
from provenance.clients.repo_repair.process import ProcessResult
from tests.investigation_support import decision_dict


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.request = AgentRequest('repair the failure', {}, (Evidence('source', 'unused', {'source_text': 'source'}),), (), 1)

    def tearDown(self): self.tmp.cleanup()

    def result(self, stdout=b'', code=0, timeout=False, overflow=False):
        return ProcessResult(code, stdout, b'', 10, timeout, overflow)

    def test_recorded_sequence_and_explicit_status(self):
        agent = RecordedAgent((json.dumps(decision_dict()).encode(), json.dumps(decision_dict(None)).encode()))
        agent.preflight()
        first = agent.propose(self.request, self.root / 'one')
        second = agent.propose(self.request, self.root / 'two')
        self.assertEqual(first.backend, 'recorded')
        self.assertFalse(first.live)
        self.assertIsNone(second.decision.patch_content)
        self.assertNotIn('hint', (self.root / 'one' / 'input.json').read_text())
        with self.assertRaises(InvestigationError): agent.propose(self.request, self.root / 'three')

    def test_input_limit_and_forged_fields(self):
        forged = decision_dict(); forged['live'] = True
        with self.assertRaises(InvestigationError):
            RecordedAgent((json.dumps(forged).encode(),)).propose(self.request, self.root / 'forged')
        huge = AgentRequest('x' * 131073, {}, self.request.evidence, (), 1)
        with self.assertRaises(InvestigationError):
            RecordedAgent((b'{}',)).propose(huge, self.root / 'huge')
        self.assertFalse((self.root / 'huge').exists())

    def test_preflight_recognizes_effective_restrictions_and_login(self):
        features = '\n'.join(f'{name} stable false' for name in DISABLED_FEATURES).encode()
        for outputs, success in [([self.result(b'codex 1'), self.result(' '.join(REQUIRED_FLAGS).encode()), self.result(b'logged in'), self.result(features)], True),
                                 ([self.result(b'codex 1'), self.result(b'old help')], False),
                                 ([self.result(b'codex 1'), self.result(' '.join(REQUIRED_FLAGS).encode()), self.result(code=1)], False),
                                 ([self.result(b'codex 1'), self.result(' '.join(REQUIRED_FLAGS).encode()), self.result(), self.result(features.replace(b'false', b'true', 1))], False)]:
            with patch('provenance.clients.repo_repair.agent.run_process', side_effect=outputs):
                if success: CodexAgent().preflight()
                else:
                    with self.assertRaises(InvestigationError): CodexAgent().preflight()

    def test_live_schema_output_and_restriction_argv(self):
        agent = CodexAgent(); agent.cli_version = 'codex test'
        def launch(argv, cwd, **kwargs):
            Path(argv[argv.index('--output-last-message') + 1]).write_bytes(json.dumps(decision_dict()).encode())
            self.assertEqual(kwargs['timeout'], 180)
            self.assertEqual(kwargs['max_output'], 1048576)
            self.assertIn(b'repair the failure', kwargs['stdin'])
            self.assertIn('--ignore-user-config', argv)
            for feature in DISABLED_FEATURES: self.assertIn(feature, argv)
            for config in ('approval_policy="never"', 'web_search="disabled"', 'mcp_servers={}'): self.assertIn(config, argv)
            return self.result(b'{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":20}}\n')
        with patch('provenance.clients.repo_repair.agent.run_process', side_effect=launch):
            result = agent.propose(self.request, self.root / 'live')
        self.assertTrue(result.live)
        self.assertEqual(result.metadata['tokens']['output_tokens'], 20)
        self.assertFalse(any(p.suffix == '.jsonl' for p in (self.root / 'live').iterdir()))

    def test_live_failures_never_return_decision(self):
        for index, result in enumerate([self.result(code=1), self.result(timeout=True), self.result(overflow=True), self.result(),
                                       self.result(b'{"type":"item.completed","item":{"type":"command_execution"}}\n')]):
            agent = CodexAgent(); agent.cli_version = 'codex test'
            with patch('provenance.clients.repo_repair.agent.run_process', return_value=result):
                with self.assertRaises(InvestigationError): agent.propose(self.request, self.root / str(index))
