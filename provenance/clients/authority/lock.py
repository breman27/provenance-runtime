"""Bounded OS-backed locks. Kernel handle ownership provides crash release."""
import os
import time
from contextlib import contextmanager

from ...errors import fail
from ..repo_repair.case import safe_path


@contextmanager
def session_lock(session, timeout=5.0):
    path = safe_path(session.root, 'approval.lock')
    handle = path.open('a+b')
    acquired = False
    try:
        if path.stat().st_size == 0:
            handle.write(b'\0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    fail('LOCK_TIMEOUT', 'another operator holds the session lock')
                time.sleep(min(.05, max(0, deadline-time.monotonic())))
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
