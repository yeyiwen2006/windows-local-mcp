"""Explicit, bounded current-user command execution; not a filesystem sandbox.

No shell is implicitly inserted. Children enter a Windows Job Object before their
first instruction, and ordinary descendants are terminated on exit/cancel/pause.
Output is memory-only, capped per stream, and never copied into audit records.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import threading
import time
from uuid import uuid4

from .files import Files
from .guard import Guard

MAX_RUNNING = 4
MAX_RETAINED = 32
MAX_OUTPUT_CHARS = 262144
ENCODINGS = ("utf-8", "gb18030", "utf-16-le", "cp1252")
_SECRET_ENV = {"CONTROL_PLANE_API_KEY", "OPENAI_API_KEY", "OPENAI_ADMIN_KEY"}


def _integer(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} through {high}")
    return value


class Output:
    def __init__(self, limit: int):
        self.limit = limit
        self.text = ""
        self.total = 0
        self.lock = threading.Lock()

    def add(self, text: str) -> None:
        with self.lock:
            self.total += len(text)
            room = self.limit - len(self.text)
            if room > 0:
                self.text += text[:room]

    def read(self, offset: int, maximum: int) -> dict:
        with self.lock:
            if offset > len(self.text):
                raise ValueError("Output offset exceeds captured character count")
            end = min(len(self.text), offset + maximum)
            return {"text": self.text[offset:end], "next_offset": end,
                    "captured_chars": len(self.text), "total_chars": self.total,
                    "truncated": self.total > len(self.text)}


@dataclass
class Job:
    identifier: str
    timeout_seconds: int
    stdout: Output
    stderr: Output
    started: float = field(default_factory=time.monotonic)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    state: str = "running"
    exit_code: int | None = None
    pid: int | None = None
    error_type: str | None = None
    cancel_reason: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    worker: threading.Thread | None = None

    def request_stop(self, reason: str) -> None:
        with self.lock:
            if not self.done.is_set() and self.cancel_reason is None:
                self.cancel_reason = reason
                self.stop.set()

    def snapshot(self, stdout_offset: int = 0, stderr_offset: int = 0,
                 maximum: int = 65536) -> dict:
        with self.lock:
            return {"job_id": self.identifier, "pid": self.pid, "state": self.state,
                    "exit_code": self.exit_code,
                    "success": self.state == "completed" and self.exit_code == 0,
                    "started_at": self.started_at, "finished_at": self.finished_at,
                    "elapsed_seconds": self.elapsed_seconds if self.done.is_set()
                    else time.monotonic() - self.started,
                    "timeout_seconds": self.timeout_seconds, "error_type": self.error_type,
                    "stdout": self.stdout.read(stdout_offset, maximum),
                    "stderr": self.stderr.read(stderr_offset, maximum)}


class WindowsProcess:
    """Create suspended, restrict inherited handles, assign job, then resume."""
    def __init__(self, executable: str, arguments: list[str], cwd: str, env: dict):
        import _winapi
        import ctypes
        from ctypes import wintypes
        import msvcrt
        import win32job
        import win32process

        self.api = _winapi
        self.job_api = win32job
        self.process_api = win32process
        self.process = None
        self.thread = None
        self.job = None
        self.stdout_fd = self.stderr_fd = None
        parent_fds: list[int] = []
        child_fds: list[int] = []
        try:
            # pywin32 312 rejects None for the name. Use the native NULL-name API
            # so another process cannot accidentally open a shared named job.
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create_job = kernel.CreateJobObjectW
            create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            create_job.restype = wintypes.HANDLE
            self.job = create_job(None, None)
            if not self.job:
                self.job = None
                raise ctypes.WinError(ctypes.get_last_error())
            limits = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, limits)
            out_r, out_w = os.pipe()
            parent_fds.append(out_r); child_fds.append(out_w)
            err_r, err_w = os.pipe()
            parent_fds.append(err_r); child_fds.append(err_w)
            null_fd = os.open(os.devnull, os.O_RDONLY | os.O_BINARY)
            child_fds.append(null_fd)
            handles = [msvcrt.get_osfhandle(fd) for fd in (null_fd, out_w, err_w)]
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = handles
            startup.lpAttributeList = {"handle_list": handles}
            command_line = subprocess.list2cmdline([executable, *arguments])
            if len(command_line.encode("utf-16-le")) // 2 >= 32767:
                raise ValueError("Command line exceeds the Windows limit")
            # Error boxes must not turn a non-interactive launch into a desktop wait.
            # Change this thread only and restore its previous mode immediately.
            kernel.GetThreadErrorMode.argtypes = []
            kernel.GetThreadErrorMode.restype = wintypes.DWORD
            kernel.SetThreadErrorMode.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
            kernel.SetThreadErrorMode.restype = wintypes.BOOL
            old_mode = wintypes.DWORD()
            if not kernel.SetThreadErrorMode(kernel.GetThreadErrorMode() | 0x8003, ctypes.byref(old_mode)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                self.process, self.thread, self.pid, _ = _winapi.CreateProcess(
                    executable, command_line, None, None, True,
                    0x00000004 | 0x08000000,  # CREATE_SUSPENDED | CREATE_NO_WINDOW
                    env, cwd, startup)
            finally:
                if not kernel.SetThreadErrorMode(old_mode.value, None):
                    raise ctypes.WinError(ctypes.get_last_error())
            win32job.AssignProcessToJobObject(self.job, self.process)
            self.stdout_fd, self.stderr_fd = out_r, err_r
            parent_fds.clear()  # Ownership transfers to reader threads.
        except BaseException:
            if self.process is not None:
                _winapi.TerminateProcess(self.process, 1)
                _winapi.WaitForSingleObject(self.process, 5000)
            self.close()
            raise
        finally:
            for fd in parent_fds + child_fds:
                os.close(fd)

    def resume(self) -> None:
        self.process_api.ResumeThread(self.thread)
        self.api.CloseHandle(self.thread)
        self.thread = None

    def poll(self) -> int | None:
        if self.api.WaitForSingleObject(self.process, 0) == 0:
            return self.api.GetExitCodeProcess(self.process)
        return None

    def terminate(self) -> None:
        self.job_api.TerminateJobObject(self.job, 1)
        self.api.WaitForSingleObject(self.process, 5000)

    def close(self) -> None:
        if self.job is not None:
            self.api.CloseHandle(self.job)  # KILL_ON_JOB_CLOSE covers abnormal server shutdown.
            self.job = None
        for name in ("thread", "process"):
            handle = getattr(self, name, None)
            if handle is not None:
                self.api.CloseHandle(handle)
                setattr(self, name, None)


class Commands:
    def __init__(self, guard: Guard):
        self.guard = guard
        self.files = Files(guard)
        self.enable_file = guard.state / "COMMANDS_ENABLED"
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.closed = False

    @property
    def enabled(self) -> bool:
        return self.enable_file.is_file() and not self.enable_file.is_symlink()

    def status(self) -> dict:
        with self.lock:
            return {"enabled": self.enabled, "requires_local_opt_in": True,
                    "running": sum(not job.done.is_set() for job in self.jobs.values()),
                    "retained": len(self.jobs), "max_running": MAX_RUNNING,
                    "max_retained": MAX_RETAINED, "desktop_focus_required": False}

    def _lookup(self, identifier: str) -> Job:
        with self.lock:
            if identifier not in self.jobs:
                raise ValueError("Unknown or expired command job_id")
            return self.jobs[identifier]

    def start(self, executable: str, arguments: list[str], cwd: str,
              timeout_seconds: int = 600, output_limit_chars: int = MAX_OUTPUT_CHARS,
              encoding: str = "utf-8", environment: dict[str, str] | None = None) -> dict:
        _integer(timeout_seconds, "timeout_seconds", 1, 86400)
        _integer(output_limit_chars, "output_limit_chars", 1024, MAX_OUTPUT_CHARS)
        if encoding not in ENCODINGS:
            raise ValueError("Unsupported output encoding")
        if not isinstance(arguments, list) or len(arguments) > 256 or any(
            not isinstance(arg, str) or "\0" in arg for arg in arguments):
            raise ValueError("arguments must contain at most 256 NUL-free strings")
        overrides = {} if environment is None else environment
        if not isinstance(overrides, dict) or len(overrides) > 64 or any(
            not isinstance(k, str) or not isinstance(v, str) or not k or "=" in k or
            "\0" in k + v or len(k) > 256 or len(v) > 32767 or
            k.upper() in _SECRET_ENV or k.upper().startswith("WINDOWS_LOCAL_MCP_")
            for k, v in overrides.items()):
            raise ValueError("Invalid or service-private environment override")
        with self.guard.action("command_start", {"executable": executable, "cwd": cwd,
                                                "argument_count": len(arguments),
                                                "timeout_seconds": timeout_seconds}):
            if not self.enabled:
                raise PermissionError("Commands are disabled. Enable locally with Enable-Commands.ps1")
            if os.name != "nt":
                raise OSError("Command execution requires Windows")
            exe = self.files.path(executable)
            directory = self.files.path(cwd, mutation=True)
            if not exe.is_file() or exe.suffix.casefold() != ".exe":
                raise ValueError("executable must be an existing absolute .exe path")
            # Reject DOS/16-bit and obviously malformed images before CreateProcess:
            # otherwise Windows may display an unsupported-application dialog.
            with exe.open("rb") as image:
                header = image.read(64)
                if len(header) != 64 or header[:2] != b"MZ":
                    raise OSError("executable is not a Windows PE image")
                pe_offset = int.from_bytes(header[60:64], "little")
                if pe_offset < 64 or pe_offset > os.fstat(image.fileno()).st_size - 4:
                    raise OSError("executable has an invalid PE offset")
                image.seek(pe_offset)
                if image.read(4) != b"PE\0\0":
                    raise OSError("16-bit and non-PE executables are unsupported")
            if not directory.is_dir():
                raise ValueError("cwd must be an existing local directory outside service-protected paths")
            env = {k: v for k, v in os.environ.items()
                   if k.upper() not in _SECRET_ENV and not k.upper().startswith("WINDOWS_LOCAL_MCP_")}
            env.update(overrides)
            with self.lock:
                if self.closed:
                    raise RuntimeError("Command executor is closed")
                if sum(not j.done.is_set() for j in self.jobs.values()) >= MAX_RUNNING:
                    raise RuntimeError("Command concurrency limit reached; wait or cancel an existing job")
                while len(self.jobs) >= MAX_RETAINED:
                    oldest = next((key for key, j in self.jobs.items() if j.done.is_set()), None)
                    if oldest is None:
                        raise RuntimeError("Command job capacity reached")
                    del self.jobs[oldest]
                job = Job(uuid4().hex, timeout_seconds, Output(output_limit_chars), Output(output_limit_chars))
                self.guard.audit({"tool": "command_job", "job_id": job.identifier, "result": "starting"})
                process = WindowsProcess(str(exe), arguments, str(directory), env)
                job.pid = process.pid
                self.jobs[job.identifier] = job
                job.worker = threading.Thread(target=self._watch, args=(job, process, encoding),
                                              name=f"command-{job.identifier[:8]}", daemon=True)
                try:
                    self.guard.check()
                    if not self.enabled:
                        raise PermissionError("Command permission was revoked")
                    # The watchdog alone owns process handles, including resume/cleanup.
                    job.worker.start()
                except BaseException:
                    job.request_stop("cancelled")
                    if job.worker.ident is None:
                        process.close()
                        for fd in (process.stdout_fd, process.stderr_fd):
                            os.close(fd)
                        del self.jobs[job.identifier]
                    raise
                return job.snapshot(maximum=0)

    def _watch(self, job: Job, process: WindowsProcess, encoding: str) -> None:
        readers: list[threading.Thread] = []
        reader_errors: list[str] = []
        unowned_fds = {process.stdout_fd, process.stderr_fd}
        resumed = False
        state, code, error_type = "failed", None, None
        def drain(fd: int, output: Output) -> None:
            decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
            try:
                while block := os.read(fd, 16384):
                    output.add(decoder.decode(block))
                output.add(decoder.decode(b"", final=True))
            except Exception as exc:
                reader_errors.append(type(exc).__name__)
            finally:
                os.close(fd)
        try:
            for fd, output in ((process.stdout_fd, job.stdout), (process.stderr_fd, job.stderr)):
                thread = threading.Thread(target=drain, args=(fd, output), daemon=True)
                thread.start()
                unowned_fds.remove(fd)
                readers.append(thread)
            while True:
                try:
                    self.guard.check()
                except PermissionError:
                    job.request_stop("paused")
                if not self.enabled:
                    job.request_stop("permission_revoked")
                if job.stop.is_set():
                    state = job.cancel_reason or "cancelled"
                    break
                if not resumed:
                    if time.monotonic() - job.started >= job.timeout_seconds:
                        state = "timed_out"
                        break
                    process.resume()
                    resumed = True
                code = process.poll()
                if code is not None:
                    state = "completed"
                    break
                if time.monotonic() - job.started >= job.timeout_seconds:
                    state = "timed_out"
                    break
                job.stop.wait(0.05)
        except BaseException as exc:
            error_type = type(exc).__name__
        finally:
            try:
                process.terminate()  # Even a successful root must not leave detached descendants.
                if code is None:
                    code = process.poll()
            except Exception as exc:
                state, error_type = "failed", type(exc).__name__
            finally:
                process.close()
            for fd in unowned_fds:
                os.close(fd)
            for reader in readers:
                reader.join(5)
            if reader_errors or any(reader.is_alive() for reader in readers):
                state, error_type = "failed", "OutputDrainError"
            try:
                with self.guard.lock:
                    self.guard.audit({"tool": "command_job", "job_id": job.identifier,
                                      "result": state, "exit_code": code, "error_type": error_type})
            except OSError:
                state, error_type = "failed", "AuditWriteError"
            with job.lock:
                job.state, job.exit_code, job.error_type = state, code, error_type
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.elapsed_seconds = time.monotonic() - job.started
                job.done.set()

    def poll(self, job_id: str, stdout_offset: int = 0, stderr_offset: int = 0,
             max_chars: int = 65536, wait_seconds: int = 0) -> dict:
        _integer(stdout_offset, "stdout_offset", 0, MAX_OUTPUT_CHARS)
        _integer(stderr_offset, "stderr_offset", 0, MAX_OUTPUT_CHARS)
        _integer(max_chars, "max_chars", 1, 65536)
        _integer(wait_seconds, "wait_seconds", 0, 10)
        with self.guard.action("command_poll", {"job_id": job_id}):
            job = self._lookup(job_id)
        job.done.wait(wait_seconds)  # Never hold the global guard while waiting.
        self.guard.check()
        return job.snapshot(stdout_offset, stderr_offset, max_chars)

    def cancel(self, job_id: str) -> dict:
        job = self._lookup(job_id)
        job.request_stop("cancelled")  # Cancellation remains available while paused.
        try:
            with self.guard.lock:
                self.guard.audit({"tool": "command_cancel", "job_id": job_id, "result": "requested"})
        except OSError:
            pass  # Audit failure must never prevent emergency termination.
        return {"job_id": job_id, "cancellation_requested": not job.done.is_set(),
                "finished": job.done.is_set()}

    def cancel_all(self, reason: str) -> None:
        with self.lock:
            for job in self.jobs.values():
                job.request_stop(reason)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self.cancel_all("service_stopped")
            jobs = list(self.jobs.values())
        for job in jobs:
            job.done.wait(6)
