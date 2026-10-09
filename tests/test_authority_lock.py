import subprocess
import sys
import unittest

from provenance.errors import ProvenanceError
from tests import test_authority_context as session_tests

try:
    from provenance.clients.authority.lock import session_lock
except ImportError:
    session_lock = None


class LockTests(unittest.TestCase):
    setUp = session_tests.SessionTests.setUp
    create = session_tests.SessionTests.create

    def test_other_process_times_out_then_acquires_after_release(self):
        self.assertIsNotNone(session_lock, 'operator lock is not implemented')
        session = self.create()
        code = ('from provenance.clients.authority.context import open_session; '
                'from provenance.clients.authority.lock import session_lock; import sys; '
                's=open_session(sys.argv[1]); '\
                '\nwith session_lock(s, timeout=.1): print("acquired")')
        with session_lock(session):
            result = subprocess.run([sys.executable, '-c', code, str(self.root)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'LOCK_TIMEOUT', result.stderr)
        result = subprocess.run([sys.executable, '-c', code, str(self.root)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'acquired', result.stdout)

    def test_process_death_releases_lock(self):
        session = self.create()
        code = ('from provenance.clients.authority.context import open_session; '
                'from provenance.clients.authority.lock import session_lock; import sys, time; '
                's=open_session(sys.argv[1]); '\
                '\nwith session_lock(s):\n print("locked", flush=True)\n time.sleep(30)')
        proc = subprocess.Popen([sys.executable, '-c', code, str(self.root)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        try:
            self.assertEqual(proc.stdout.readline().strip(), b'locked')
            proc.kill()
            proc.wait(timeout=5)
            with session_lock(session, timeout=.2):
                pass
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()
