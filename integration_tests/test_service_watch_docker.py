"""Real persistent collector with manual external edits, in an isolated test repo."""
import tempfile
import unittest
from pathlib import Path
from provenance import status
from provenance.clients.repo_repair.case import GOOD_SOURCE, BAD_SOURCE, TARGET, _git, digest
from provenance.clients.observed_service.experiment import ServiceVerifier
from provenance.clients.observed_service.watch import ServiceWatcher
from tests.test_service_watch import WatchAgent


class WatchDockerTests(unittest.TestCase):
    def test_live_working_tree_batches_good_edit_and_bad_edit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            repo=root/'repo'
            (repo/'src').mkdir(parents=True)
            (repo/TARGET).write_bytes(GOOD_SOURCE)
            _git(repo,'init','--initial-branch=service')
            _git(repo,'config','user.name','Test fixture')
            _git(repo,'config','user.email','fixture@example.invalid')
            _git(repo,'add','.')
            _git(repo,'commit','-m','working')
            original_head=_git(repo,'rev-parse','HEAD')
            watcher=ServiceWatcher(repo,root/'session',ServiceVerifier(),output=lambda *args,**kwargs:None)
            watcher.start()
            try:
                self.assertEqual(watcher.tick()['health'],'OK')
                old_source=watcher.source.node_id
                old_log=watcher.last_log.node_id
                good=b'def clamp(value: int, lower: int, upper: int) -> int:\n    """Bound sensor readings."""\n    return min(upper, max(lower, value))\n'
                (repo/TARGET).write_bytes(good)
                self.assertEqual(watcher.tick()['health'],'OK')
                self.assertEqual(status(watcher.store,old_source,'execution'),'SUPERSEDED')
                self.assertEqual(status(watcher.store,old_log,'execution'),'VALID')
                (repo/TARGET).write_bytes(BAD_SOURCE)
                self.assertEqual(watcher.tick()['health'],'ANOMALY')
                observed=watcher.store.get(watcher.last_log.node_id).payload
                self.assertTrue(any(e['output']>100 for e in observed['entries']))
                self.assertEqual(digest(Path(observed['artifact']).read_bytes()),observed['stdout_hash'])
                self.assertEqual(_git(repo,'rev-parse','HEAD'),original_head)
                crash=b'def clamp(value: int, lower: int, upper: int) -> int:\n    return 1 // 0\n'
                (repo/TARGET).write_bytes(crash)
                self.assertEqual(watcher.tick()['health'],'ERROR')
                observed=watcher.store.get(watcher.last_log.node_id).payload
                self.assertIn('ZeroDivisionError',observed['stderr'])
                self.assertTrue(all(watcher.store.validate(i).ok for i in watcher.store.all_ids()))
            finally:
                watcher.close()
