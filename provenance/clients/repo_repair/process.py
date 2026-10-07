"""Bounded process capture; subprocesses never use a shell."""
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_ms: int
    timed_out: bool
    output_exceeded: bool


def _stop(process):
    if os.name == 'nt':
        subprocess.run(('taskkill', '/PID', str(process.pid), '/T', '/F'), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    if process.poll() is None:
        process.kill()


def run_process(argv, cwd, stdin=None, timeout=30, max_output=1048576):
    start = time.monotonic()
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(tuple(argv), cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=False, **options)
    buffers = [bytearray(), bytearray()]
    lock = threading.Lock()
    exceeded = threading.Event()

    def read(stream, index):
        while data := stream.read(4096):
            with lock:
                remaining = max_output - sum(map(len, buffers))
                buffers[index].extend(data[:max(remaining, 0)])
                if len(data) > remaining: exceeded.set()
        stream.close()

    def write():
        try:
            if stdin: process.stdin.write(stdin)
            process.stdin.close()
        except (BrokenPipeError, OSError): pass

    threads = [threading.Thread(target=read, args=(process.stdout, 0), daemon=True),
               threading.Thread(target=read, args=(process.stderr, 1), daemon=True),
               threading.Thread(target=write, daemon=True)]
    for thread in threads: thread.start()
    timed_out = False
    try:
        while process.poll() is None:
            if exceeded.is_set() or time.monotonic() - start >= timeout:
                timed_out = not exceeded.is_set()
                _stop(process)
                break
            time.sleep(0.01)
        process.wait(timeout=10)
    except BaseException:
        _stop(process)
        raise
    finally:
        for thread in threads: thread.join(timeout=10)
    return ProcessResult(process.returncode, bytes(buffers[0]), bytes(buffers[1]),
                         int((time.monotonic() - start) * 1000), timed_out, exceeded.is_set())
