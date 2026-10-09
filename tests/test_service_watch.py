import json
import os
import random
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from provenance import Store, Parent, make_node, status, why
from provenance.format import canonical_json
from provenance.clients.repo_repair.case import GOOD_SOURCE, BAD_SOURCE, TEST_SOURCE, TARGET, digest, _git
from provenance.clients.observed_service.watch import ServiceWatcher, read_working_version
from provenance.clients.observed_service.experiment import SERVICE_CONTRACT
from tests.test_observed_service import FakeServiceVerifier


class WatchVerifier(FakeServiceVerifier):
    def run_service(self, snapshot, case, readings, allow_failure):
        payload = super().run_service(snapshot, case)
        good = snapshot.files[TARGET] != BAD_SOURCE
        entries = [{'input': value, 'output': max(0,min(value,100)) if good else max(0,value),
                    'lower': 0, 'upper': 100, 'event': 'reading_processed', 'sequence': index,
                    'timestamp': '2026-10-07T00:00:00+00:00', 'revision': snapshot.revision,
                    'source_hash': snapshot.file_hashes[TARGET]} for index,value in enumerate(readings)]
        stdout = ''.join(json.dumps(e)+'\n' for e in entries)
        payload.update(entries=entries, stdout=stdout, stdout_hash=digest(stdout.encode()), outcome='ok')
        return payload


class WatchAgent:
    backend, live = 'recorded', False
    def __init__(self, block=None):
        self.index = 0
        self.assessment = 'healthy'
        self.block = block
        self.entered = threading.Event()
    def preflight(self):
        pass
    def step(self, transcript, aliases, output_dir):
        self.index += 1
        self.entered.set()
        if self.block is not None:
            self.block.wait(5)
        names = ('read_logs', 'read_source', 'finish')
        name = names[(self.index-1)%3]
        arguments = {} if name != 'finish' else {'assessment': self.assessment,
            'claim_statement': 'Interpretation of the live service.', 'evidence_aliases': ['logs_current','source_current'],
            'patch_content': None, 'summary': 'Evidence-backed service assessment.'}
        call = {'type':'function_call','name':name,'call_id':f'call-{self.index}','arguments':canonical_json(arguments).decode()}
        output_dir.mkdir(parents=True)
        (output_dir/'input.json').write_bytes(canonical_json(transcript))
        return call,arguments,{}


class ServiceWatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root/'service'
        (self.repo/'src').mkdir(parents=True)
        (self.repo/'src/clamp.py').write_bytes(GOOD_SOURCE)
        (self.repo/'README.md').write_text(SERVICE_CONTRACT, encoding='utf-8')
        _git(self.repo,'init','--initial-branch=service')
        _git(self.repo,'config','user.name','Test fixture')
        _git(self.repo,'config','user.email','fixture@example.invalid')
        _git(self.repo,'add','.')
        _git(self.repo,'commit','-m','working service')
        self.watcher = None
    def tearDown(self):
        if self.watcher:
            if self.watcher.agent and getattr(self.watcher.agent,'block',None):
                self.watcher.agent.block.set()
            self.watcher.close()
        self.temporary.cleanup()
    def start(self,agent=None):
        self.watcher=ServiceWatcher(self.repo,self.root/'session',WatchVerifier(),agent,
                                   random_source=random.Random(5),output=lambda *args,**kwargs:None)
        self.watcher.start()
        return self.watcher
    def events(self):
        return [json.loads(line) for line in (self.root/'session/events.jsonl').read_text(encoding='utf-8').splitlines()]
    def wait_agent(self):
        self.watcher.thread.join(5)
        self.assertFalse(self.watcher.thread.is_alive())
    def test_unchanged_tree_collects_distinct_observations_and_variable_readings(self):
        watcher=self.start()
        first=watcher.tick()
        first_source=watcher.source.node_id
        second=watcher.tick()
        self.assertEqual(first['health'],'OK')
        self.assertEqual(second['health'],'OK')
        self.assertEqual(watcher.version_index,1)
        self.assertEqual(first_source,watcher.source.node_id)
        self.assertNotEqual(first['log_observation'],second['log_observation'])
        observations=[e for e in self.events() if e['event']=='OBSERVATION']
        self.assertNotEqual(observations[0]['inputs'],observations[1]['inputs'])
        self.assertEqual((self.repo/TARGET).read_bytes(),GOOD_SOURCE)
    def test_unsaved_good_then_bad_changes_are_captured_without_changing_external_repo(self):
        watcher=self.start()
        original_head=_git(self.repo,'rev-parse','HEAD')
        watcher.tick()
        old_source=watcher.source.node_id
        old_log=watcher.last_log.node_id
        claim=watcher.runtime.submit(make_node('Claim',{'statement':'The current working tree is healthy'},
                    [Parent('evidence',old_source)],'test-agent',watcher.runtime.clock()))
        good=b'def clamp(value: int, lower: int, upper: int) -> int:\n    """Keep sensor output within the display range."""\n    return min(upper, max(lower, value))\n'
        (self.repo/TARGET).write_bytes(good)
        self.assertEqual(watcher.tick()['health'],'OK')
        self.assertEqual(status(watcher.store,old_source,'execution'),'SUPERSEDED')
        self.assertEqual(status(watcher.store,claim,'execution'),'STALE')
        self.assertEqual(status(watcher.store,old_log,'execution'),'VALID')
        (self.repo/TARGET).write_bytes(BAD_SOURCE)
        self.assertEqual(watcher.tick()['health'],'ANOMALY')
        self.assertEqual(watcher.version_index,3)
        self.assertEqual(_git(self.repo,'rev-parse','HEAD'),original_head)
        self.assertEqual((self.repo/TARGET).read_bytes(),BAD_SOURCE)
        self.assertTrue(all(watcher.store.validate(i).ok for i in watcher.store.all_ids()))
    def test_agent_records_claim_in_the_continuous_graph_and_no_repeat_call_when_unchanged(self):
        agent=WatchAgent()
        watcher=self.start(agent)
        watcher.tick(); self.wait_agent()
        result=next(e for e in self.events() if e['event']=='AGENT_RESULT')
        self.assertEqual(result['outcome'],'HEALTHY')
        self.assertEqual(watcher.store.get(result['claim_id']).kind,'Claim')
        watcher.tick()
        self.assertEqual(agent.index,3)
        self.assertEqual(sum(e['event']=='INVESTIGATION_QUEUED' for e in self.events()),1)
    def test_collector_continues_while_model_turn_is_blocked(self):
        release=threading.Event()
        agent=WatchAgent(release)
        watcher=self.start(agent)
        watcher.tick()
        self.assertTrue(agent.entered.wait(1))
        watcher.tick()
        self.assertEqual(watcher.sequence,2)
        self.assertTrue(watcher.thread.is_alive())
        self.assertEqual(sum(e['event']=='OBSERVATION' for e in self.events()),2)
        release.set(); self.wait_agent()
    def test_change_during_agent_turn_marks_old_investigation_stale_and_queues_latest(self):
        release=threading.Event()
        agent=WatchAgent(release)
        watcher=self.start(agent)
        watcher.tick(); self.assertTrue(agent.entered.wait(1))
        (self.repo/TARGET).write_bytes(BAD_SOURCE)
        watcher.tick()
        release.set(); self.wait_agent()
        result=next(e for e in self.events() if e['event']=='AGENT_RESULT')
        self.assertEqual(result['outcome'],'STALE')
        self.assertIsNone(result['effect_id'])
        self.assertEqual(watcher.pending['number'],2)
    def test_queued_changes_coalesce_to_latest_source(self):
        release=threading.Event()
        watcher=self.start(WatchAgent(release))
        watcher.tick(); self.assertTrue(watcher.agent.entered.wait(1))
        (self.repo/TARGET).write_bytes(GOOD_SOURCE+b'\n')
        watcher.tick()
        (self.repo/TARGET).write_bytes(BAD_SOURCE)
        watcher.tick()
        self.assertEqual(watcher.pending['number'],3)
        self.assertTrue(any(e['event']=='INVESTIGATION_COALESCED' and e['skipped']==2 for e in self.events()))
        release.set(); self.wait_agent()
    def test_failed_service_run_is_recorded_with_diagnostics(self):
        watcher=self.start()
        original=watcher.verifier.run_service
        def failure(*args,**kwargs):
            payload=original(*args,**kwargs)
            payload.update(outcome='error',entries=[],stdout='',stdout_hash=digest(b''),stderr='ZeroDivisionError',returncode=1)
            return payload
        watcher.verifier.run_service=failure
        state=watcher.tick()
        self.assertEqual(state['health'],'ERROR')
        observation=watcher.store.get(state['log_observation'])
        self.assertEqual(observation.payload['stderr'],'ZeroDivisionError')
    def test_source_symlink_and_existing_session_are_rejected(self):
        from provenance.clients.repo_repair.errors import InvestigationError
        from provenance.clients.observed_service.watch import initialize_session
        source_bytes = (self.repo/TARGET).read_bytes()
        external = self.root/'external-source'
        external.mkdir()
        (external/'clamp.py').write_bytes(source_bytes)
        (self.repo/TARGET).unlink()
        if os.name == 'nt':
            (self.repo/'src').rmdir()
            created = subprocess.run(('cmd', '/c', 'mklink', '/J', str(self.repo/'src'), str(external)),
                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(created.returncode, 0, created.stderr)
        else:
            (self.repo/TARGET).symlink_to(external/'clamp.py')
        with self.assertRaises(InvestigationError):
            read_working_version(self.repo)
        self.assertEqual((external/'clamp.py').read_bytes(), source_bytes)
        session = self.root/'existing-session'
        session.mkdir()
        sentinel = session/'keep.txt'
        sentinel.write_bytes(b'preserved')
        with self.assertRaises(InvestigationError) as raised:
            initialize_session(self.repo, session)
        self.assertEqual(raised.exception.code, 'CASE_EXISTS')
        self.assertEqual(sentinel.read_bytes(), b'preserved')
