import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from provenance import Store, Runtime
from provenance.errors import ProvenanceError
from provenance.format import canonical_json, parse_json

try:
    from provenance.clients.authority.profiles import authority_policy
    from provenance.clients.authority.context import create_session, open_session
except ImportError:
    authority_policy = None


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
