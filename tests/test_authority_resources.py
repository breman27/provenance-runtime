import tempfile
import unittest
from pathlib import Path

from provenance.errors import ProvenanceError
from provenance.projection import status
from provenance.clients.repo_repair.case import TARGET, TEST_PATH, _git
from tests.authority_support import pending

try:
    from provenance.clients.authority.context import record_context
    from provenance.clients.authority.resources import check_current
except ImportError:
    check_current = None


class ResourceTests(unittest.TestCase):
    client = 'observed-service'
    def setUp(self):
        self.assertIsNotNone(check_current, 'direct freshness checks are not implemented')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        (self.case, self.store, self.runtime, self.session, self.baseline, self.action,
         self.source, self.checks, self.logs) = pending(Path(temp.name)/'case', client=self.client)
        self.addCleanup(self.store.close)
        self.context = record_context(self.session, self.runtime, self.case, self.baseline,
                                      self.action, self.source, self.checks)

    def test_current_is_read_only_but_each_measured_change_stales_only_source(self):
        before = self.store.all_ids()
        check_current(self.session, self.runtime, self.context)
        self.assertEqual(before, self.store.all_ids())
        for name in (TARGET, TEST_PATH, 'README.md', 'service.py'):
            path = self.case.repository/name
            original = path.read_bytes()
            path.write_bytes(b'\xffchanged')
            with self.subTest(name=name), self.assertRaises(ProvenanceError) as caught:
                check_current(self.session, self.runtime, self.context)
            self.assertEqual(caught.exception.problem.code, 'STALE')
            path.write_bytes(original)
        self.assertEqual(status(self.store, self.source, 'execution'), 'INVALID')
        self.assertEqual(status(self.store, self.action, 'execution'), 'STALE')
        self.assertEqual(status(self.store, self.logs, 'execution'), 'VALID')

    def test_head_change_is_detected_without_polling(self):
        _git(self.case.repository, 'commit', '--allow-empty', '-m', 'new deployment identity')
        with self.assertRaises(ProvenanceError) as caught:
            check_current(self.session, self.runtime, self.context)
        self.assertEqual(caught.exception.problem.code, 'STALE')

    def test_offline_source_is_unavailable_without_false_invalidation(self):
        moved = self.case.repository.with_name('offline')
        self.case.repository.rename(moved)
        with self.assertRaises(ProvenanceError) as caught:
            check_current(self.session, self.runtime, self.context)
        self.assertEqual(caught.exception.problem.code, 'SOURCE_UNAVAILABLE')
        self.assertEqual(status(self.store, self.source, 'execution'), 'VALID')


class WatchResourceTests(unittest.TestCase):
    client = 'watch-service'
    setUp = ResourceTests.setUp
    test_head_change_is_detected_without_polling = ResourceTests.test_head_change_is_detected_without_polling
    test_offline_source_is_unavailable_without_false_invalidation = ResourceTests.test_offline_source_is_unavailable_without_false_invalidation

    def test_uncommitted_external_source_edit_is_detected_without_watcher(self):
        (self.session.source_repository/TARGET).write_bytes(b'\xff')
        with self.assertRaises(ProvenanceError) as caught:
            check_current(self.session, self.runtime, self.context)
        self.assertEqual(caught.exception.problem.code, 'STALE')
        self.assertEqual(status(self.store, self.logs, 'execution'), 'VALID')
