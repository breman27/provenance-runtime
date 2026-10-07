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


def _stop(process, job=None):
    if os.name == 'nt':
        job.terminate()
    else:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    if process.poll() is None:
        process.kill()


def run_process(argv, cwd, stdin=None, timeout=30, max_output=1048576):
    start = time.monotonic()
    job = None
    if os.name == 'nt':
        from .windows_job import WindowsJob
        job = WindowsJob()
    options = {'creationflags': subprocess.CREATE_NO_WINDOW | 0x00000004} if job else {'start_new_session': True}  # CREATE_SUSPENDED
    try:
        process = subprocess.Popen(tuple(argv), cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False, **options)
        if job:
            try: job.attach_and_resume(process)
            except BaseException:
                process.kill(); process.wait(timeout=10)
                raise
    except BaseException:
        if job: job.close()
        raise
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
        while process.poll() is None or any(thread.is_alive() for thread in threads):
            if exceeded.is_set() or time.monotonic() - start >= timeout:
                timed_out = not exceeded.is_set()
                _stop(process, job)
                break
            time.sleep(0.01)
        process.wait(timeout=10)
    except BaseException:
        _stop(process, job)
        raise
    finally:
        if job: job.close()
        for thread in threads: thread.join(timeout=10)
    return ProcessResult(process.returncode, bytes(buffers[0]), bytes(buffers[1]),
                         int((time.monotonic() - start) * 1000), timed_out, exceeded.is_set())
