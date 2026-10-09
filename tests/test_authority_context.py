import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from provenance import Store, Runtime
from provenance.errors import ProvenanceError
from provenance.format import canonical_json, parse_json
from provenance.model import Parent, make_node
from tests.authority_support import pending

try:
    from provenance.clients.authority.profiles import authority_policy
    from provenance.clients.authority.context import create_session, open_session
except ImportError:
    authority_policy = None

try:
    from provenance.clients.authority.context import record_context, load_context
except ImportError:
    record_context = None


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(authority_policy, 'approval sessions are not implemented')
        directory = tempfile.TemporaryDirectory(prefix='approval-é-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = Store(self.root / 'history.db')
        self.addCleanup(self.store.close)
        self.runtime = Runtime(self.store, authority_policy('manual'),
                               lambda: datetime(2026, 10, 9, tzinfo=timezone.utc))

    def create(self, **updates):
        args = dict(runtime=self.runtime, root=self.root, case_id='a'*32, mode='manual',
                    client='observed-service', source_repository=self.root/'repository')
        args.update(updates)
        return create_session(**args)

    def test_fixed_policy_and_unicode_roundtrip(self):
        self.assertEqual(authority_policy('manual').issuers, ('human-operator',))
        self.assertEqual(authority_policy('auto').issuers, ('issuer',))
        created = self.create()
        self.assertEqual(created, open_session(self.root))
        self.assertEqual(created, self.create())
        self.assertEqual(self.store.admission(created.observation_id).principal_id, 'collector')
        with self.assertRaises(ProvenanceError):
            self.create(mode='auto')
        with self.assertRaises(ProvenanceError):
            authority_policy('arbitrary')

    def test_missing_db_does_not_create_it(self):
        self.create()
        other = self.root/'missing'
        other.mkdir()
        (other/'approval-session.json').write_bytes((self.root/'approval-session.json').read_bytes())
        with self.assertRaises(ProvenanceError):
            open_session(other)
        self.assertFalse((other/'history.db').exists())

    def test_empty_database_is_not_initialized_and_bad_field_types_are_structured(self):
        self.create()
        other = self.root/'empty'
        other.mkdir()
        (other/'approval-session.json').write_bytes((self.root/'approval-session.json').read_bytes())
        database = other/'history.db'
        database.write_bytes(b'')
        with self.assertRaises(ProvenanceError):
            open_session(other)
        self.assertEqual(database.read_bytes(), b'')
        path = self.root/'approval-session.json'
        data = parse_json(path.read_bytes())
        data['observation_id'] = []
        path.write_bytes(canonical_json(data))
        with self.assertRaises(ProvenanceError):
            open_session(self.root)

    def test_mutated_foreign_or_duplicate_descriptor_refused(self):
        created = self.create()
        path = self.root/'approval-session.json'
        original = path.read_bytes()
        for field, value in [('profile', 'observed-service-auto-v1'), ('session_id', 'b'*32),
                             ('database', '../history.db'), ('source_repository', 'relative')]:
            data = parse_json(original)
            data['descriptor'][field] = value
            path.write_bytes(canonical_json(data))
            with self.subTest(field=field), self.assertRaises(ProvenanceError):
                open_session(self.root)
        path.write_bytes(original)
        with self.store.write_transaction():
            self.store._db.execute('DELETE FROM admissions WHERE node_id=?', (created.observation_id,))
        with self.assertRaises(ProvenanceError):
            open_session(self.root)

    def test_real_redirect_is_rejected_without_changing_target(self):
        external = self.root/'external'
        external.mkdir()
        target = self.root/'redirect'
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(target), str(external)],
                                    capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            target.symlink_to(external, target_is_directory=True)
        self.addCleanup(lambda: target.rmdir() if os.name == 'nt' else target.unlink())
        with self.assertRaises(Exception) as caught:
            open_session(target)
        self.assertIn('CASE_PATH', str(caught.exception))
        self.assertEqual(list(external.iterdir()), [])


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(record_context, 'proposal binding is not implemented')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        (self.case, self.store, self.runtime, self.session, self.baseline, self.action,
         self.source, self.checks, self.logs) = pending(Path(temp.name)/'case')
        self.addCleanup(self.store.close)

    def record(self, **updates):
        args = dict(session=self.session, runtime=self.runtime, case=self.case, baseline=self.baseline,
                    action_id=self.action, source_observation_id=self.source, verification_ids=self.checks)
        args.update(updates)
        return record_context(**args)

    def test_exact_binding_roundtrip_and_defensive_copy(self):
        ctx = self.record()
        self.assertEqual(ctx.context_hash, load_context(self.session, self.store, self.action).context_hash)
        self.assertEqual(ctx.context_hash, self.record().context_hash)
        copy = ctx.data
        copy['verification_ids'].clear()
        self.assertEqual(ctx.data['verification_ids'], list(self.checks))
        self.assertEqual(ctx.data['original_file_hash'], self.baseline.file_hashes['src/clamp.py'])

    def test_wrong_resource_source_or_check_cannot_be_bound(self):
        with self.assertRaises(ProvenanceError):
            self.record(source_observation_id=self.logs)
        with self.assertRaises(ProvenanceError):
            self.record(verification_ids=self.checks[:1])
        claim_id = self.store.get(self.action).parents[0].node_id
        wrong = self.runtime.verify(self.runtime.verifier('tester'), claim_id, 'targeted_tests', True)
        with self.assertRaises(ProvenanceError):
            self.record(verification_ids=(wrong, self.checks[1]))
        payload = self.store.get(self.action).payload
        payload['resource'] = 'fixture:clamp:foreign'
        node = make_node('ProposedAction', payload, self.store.get(self.action).parents, 'agent:test', self.runtime.clock())
        wrong_action = self.runtime.submit(node)
        with self.assertRaises(ProvenanceError):
            self.record(action_id=wrong_action)

    def test_altered_context_artifact_and_imported_proof_fail_closed(self):
        ctx = self.record()
        path = self.session.root/'approvals'/ (self.action.split(':')[1]+'.json')
        original = path.read_bytes()
        data = parse_json(original)
        data['context']['candidate_file_hash'] = 'sha256:'+'0'*64
        path.write_bytes(canonical_json(data))
        with self.assertRaises(ProvenanceError):
            load_context(self.session, self.store, self.action)
        path.write_bytes(original)
        artifact = next(iter(ctx.data['artifacts']))
        (self.session.root/artifact).write_bytes(b'changed')
        with self.assertRaises(ProvenanceError):
            load_context(self.session, self.store, self.action)
        self.assertEqual(load_context(self.session, self.store, self.action, artifacts=False).context_hash, ctx.context_hash)
        with self.store.write_transaction():
            self.store._db.execute('DELETE FROM admissions WHERE node_id=?', (self.checks[0],))
        with self.assertRaises(ProvenanceError):
            load_context(self.session, self.store, self.action, artifacts=False)

    def test_conflicting_locally_admitted_context_is_not_silently_selected(self):
        ctx = self.record()
        data = ctx.data
        data['case_id'] = 'f'*32
        from provenance.clients.repo_repair.case import digest
        self.runtime.observe(self.runtime.observer('collector'), {'source': 'approval-context',
            'context': data, 'context_hash': digest(canonical_json(data))})
        with self.assertRaises(ProvenanceError):
            load_context(self.session, self.store, self.action)

    def test_imported_supporting_log_cannot_earn_permission_context(self):
        with self.store.write_transaction():
            self.store._db.execute('DELETE FROM admissions WHERE node_id=?', (self.logs,))
        with self.assertRaises(ProvenanceError):
            self.record()

    def test_wrong_counts_hashes_and_images_cannot_supply_required_checks(self):
        original = self.store.get(self.checks[0])
        evidence_id = next(p.node_id for p in original.parents if p.role == 'evidence')
        proof = self.store.get(evidence_id).payload
        for updates in ({'tests_run': 0}, {'candidate_hash': 'sha256:'+'0'*64}, {'image_id': 'sha256:'+'e'*64}):
            evidence = self.runtime.observe(self.runtime.observer('collector'), dict(proof, **updates))
            check = self.runtime.verify(self.runtime.verifier('tester'), self.action, 'targeted_tests', True, (evidence,))
            with self.subTest(updates=updates), self.assertRaises(ProvenanceError):
                self.record(verification_ids=(check, self.checks[1]))
