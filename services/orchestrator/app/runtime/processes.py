"""Windows process ownership with suspended creation and bounded tree cleanup.

The manager owns the only Job handle. Children inherit only standard I/O
handles, so an abrupt service exit releases the Job and kills descendants.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from app.runtime.leases import LeaseStore
from app.runtime.resources import BoundedOutput, ResourceLimits


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
                ("bInheritHandle", wintypes.BOOL)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD), ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", wintypes.LPVOID)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class _BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


class _Windows:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("WINDOWS_JOB_OBJECTS_REQUIRED")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID], wintypes.BOOL),
            "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CreateEventW": ([wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetEvent": ([wintypes.HANDLE], wintypes.BOOL),
            "CreatePipe": ([ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(_SecurityAttributes), wintypes.DWORD], wintypes.BOOL),
            "SetHandleInformation": ([wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD], wintypes.BOOL),
            "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
            "InitializeProcThreadAttributeList": ([wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
            "UpdateProcThreadAttribute": ([wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID], wintypes.BOOL),
            "DeleteProcThreadAttributeList": ([wintypes.LPVOID], None),
            "CreateProcessW": ([wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
                wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
                ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInfo)], wintypes.BOOL),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "ReadFile": ([wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes = arguments
            function.restype = result

    @staticmethod
    def checked(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def active_processes(self, job) -> int:
        info = _Accounting()
        self.checked(self.api.QueryInformationJobObject(job, 1, ctypes.byref(info), ctypes.sizeof(info), None))
        return info.ActiveProcesses


@dataclass(frozen=True)
class ProcessResult:
    local_state: str
    remote_state: str
    status: str
    returncode: int
    pid: int
    cooperative_requested: bool
    forced: bool
    output_bytes_seen: int
    output_bytes_kept: int
    output_truncated: bool
    resource_limit: str | None = None


@dataclass(eq=False)
class ProcessHandle:
    task_id: str
    attempt_id: str
    pid: int
    remote_id: str | None
    cwd: Path
    temp_dir: Path
    _owner: object = field(repr=False)
    _output: BoundedOutput = field(repr=False)
    step_id: str = "default"
    _native: dict = field(default_factory=dict, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)
    _cancel_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _native_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _resource_hit: threading.Event = field(default_factory=threading.Event, repr=False)
    _cancel_requested: bool = field(default=False, repr=False)
    _cancel_deadline: float = field(default=0, repr=False)
    _remote_confirmed: bool = field(default=False, repr=False)
    _forced: bool = field(default=False, repr=False)
    _result: ProcessResult | None = field(default=None, repr=False)
    _error: BaseException | None = field(default=None, repr=False)
    _readers: list = field(default_factory=list, repr=False)

    @property
    def stdout(self) -> bytes:
        return self._output.read("stdout")

    @property
    def stderr(self) -> bytes:
        return self._output.read("stderr")

    @property
    def returncode(self) -> int | None:
        return self._result.returncode if self._result else None

    @property
    def local_state(self) -> str:
        if self._done.is_set() and self._error:
            return "cleanup_failed"
        return self._result.local_state if self._result else "running"


class ProcessManager:
    # Peak: job/event/NUL, two pipe pairs, suspended process and primary thread.
    START_HANDLE_BUDGET = 9
    LIVE_HANDLE_BUDGET = 5
    ENVIRONMENT_KEYS = frozenset({"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT",
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"})

    def __init__(self, ledger_path: Path, limits: ResourceLimits | None = None) -> None:
        self.limits = limits or ResourceLimits()
        self.leases = LeaseStore(ledger_path)
        self._windows = _Windows()
        self._lock = threading.RLock()
        self._active: dict[tuple[str, str, str], ProcessHandle] = {}
        self._failed: dict[tuple[str, str, str], ProcessHandle] = {}
        self._closed = False
        self._peak_handles = 0

    def _validate(self, command: list[str], cwd: Path) -> tuple[list[str], Path]:
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) or "\0" in arg for arg in command):
            raise TypeError("NATIVE_ARGUMENT_ARRAY_REQUIRED")
        executable = command[0]
        if not executable or Path(executable).suffix.lower() != ".exe":
            raise ValueError("NATIVE_EXE_REQUIRED")
        resolved = shutil.which(executable)
        if not resolved:
            raise FileNotFoundError(executable)
        resolved_path = Path(resolved).resolve(strict=True)
        if resolved_path.suffix.lower() != ".exe" or not resolved_path.is_file():
            raise ValueError("NATIVE_EXE_REQUIRED")
        cwd = Path(cwd).resolve(strict=True)
        if not cwd.is_dir():
            raise NotADirectoryError(cwd)
        return [str(resolved_path), *command[1:]], cwd

    def start(self, task_id: str, attempt_id: str, command: list[str], cwd: Path,
              remote_id: str | None = None, *, step_id: str = "default") -> ProcessHandle:
        if any(not isinstance(value, str) or not value.strip() for value in (task_id, attempt_id)):
            raise ValueError("TASK_ATTEMPT_REQUIRED")
        if remote_id is not None and (not isinstance(remote_id, str) or not remote_id.strip()):
            raise ValueError("REMOTE_ID_REQUIRED")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("STEP_ID_REQUIRED")
        command, cwd = self._validate(command, cwd)
        with self._lock:
            if self._closed:
                raise RuntimeError("MANAGER_CLOSED")
            if any(handle.cwd == cwd for handle in self._active.values()):
                raise RuntimeError("WORKSPACE_IN_USE")
            if self.leases.contains(task_id, attempt_id, step_id):
                raise RuntimeError("ATTEMPT_ALREADY_STARTED")
            if self.leases.unresolved_cancel(task_id, attempt_id):
                raise RuntimeError("REMOTE_EXECUTION_UNCONFIRMED")
            count = len(self._active)
            reserved = count * self.LIVE_HANDLE_BUDGET + self.START_HANDLE_BUDGET
            if (count >= self.limits.max_running or count >= self.limits.max_temp_dirs
                    or reserved > self.limits.max_open_handles):
                raise RuntimeError("RESOURCE_LIMIT:launch")
            self._peak_handles = max(self._peak_handles, reserved)
            temp_dir = Path(tempfile.mkdtemp(prefix=".runtime-", dir=cwd))
            handle = ProcessHandle(task_id, attempt_id, 0, remote_id, cwd, temp_dir,
                                   self, BoundedOutput(self.limits.max_output_bytes), step_id=step_id)
            try:
                self._launch(handle, command)
                self._active[(task_id, attempt_id, step_id)] = handle
                monitor = threading.Thread(target=self._monitor, args=(handle,), daemon=True,
                                           name=f"runtime-monitor-{handle.pid}")
                monitor.start()
                return handle
            except BaseException:
                self._cleanup_start(handle)
                raise

    def _close_native(self, handle: ProcessHandle, name: str) -> None:
        with handle._native_lock:
            value = handle._native.get(name)
            if value:
                self._windows.checked(self._windows.api.CloseHandle(value))
                handle._native.pop(name, None)

    @staticmethod
    def _remove_temp(handle: ProcessHandle) -> None:
        if not handle.temp_dir.exists():
            return
        resolved = handle.temp_dir.resolve()
        if (not resolved.is_relative_to(handle.cwd) or not handle.temp_dir.name.startswith(".runtime-")
                or handle.temp_dir.is_symlink() or handle.temp_dir.is_junction()):
            raise RuntimeError("TEMP_CLEANUP_SCOPE_UNCONFIRMED")
        shutil.rmtree(handle.temp_dir)

    def _launch(self, handle: ProcessHandle, command: list[str]) -> None:
        win = self._windows
        api = win.api
        handle._native["job"] = win.checked(api.CreateJobObjectW(None, None))
        limit = _ExtendedLimit()
        limit.BasicLimitInformation.LimitFlags = 0x2000 | 0x0008  # kill-on-close + active-process limit
        limit.BasicLimitInformation.ActiveProcessLimit = self.limits.max_processes_per_job
        win.checked(api.SetInformationJobObject(handle._native["job"], 9, ctypes.byref(limit), ctypes.sizeof(limit)))
        event_name = "Local\\AIWorkbenchCancel-" + uuid.uuid4().hex
        handle._native["event"] = win.checked(api.CreateEventW(None, True, False, event_name))
        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        null = api.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(security), 3, 0, None)
        if null == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        handle._native["stdin"] = null
        for stream in ("stdout", "stderr"):
            read, write = wintypes.HANDLE(), wintypes.HANDLE()
            win.checked(api.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 4096))
            handle._native[stream] = read.value
            handle._native[stream + "_write"] = write.value
            win.checked(api.SetHandleInformation(read, 1, 0))
        size = ctypes.c_size_t()
        api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        win.checked(api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)))
        try:
            inherited = (wintypes.HANDLE * 3)(handle._native["stdin"],
                handle._native["stdout_write"], handle._native["stderr_write"])
            win.checked(api.UpdateProcThreadAttribute(attributes, 0, 0x20002, inherited,
                ctypes.sizeof(inherited), None, None))
            jobs = (wintypes.HANDLE * 1)(handle._native["job"])
            # Windows 10+: Job membership is established by process creation,
            # removing a separate post-create assignment window.
            win.checked(api.UpdateProcThreadAttribute(attributes, 0, 0x2000D, jobs,
                ctypes.sizeof(jobs), None, None))
            startup = _StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100 | 0x1  # standard handles + SW_HIDE
            startup.StartupInfo.wShowWindow = 0
            startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = inherited
            startup.lpAttributeList = ctypes.cast(attributes, wintypes.LPVOID)
            environment = {key: value for key, value in os.environ.items()
                           if key.upper() in self.ENVIRONMENT_KEYS}
            environment.update(TEMP=str(handle.temp_dir), TMP=str(handle.temp_dir),
                APP_RUNTIME_CANCEL_EVENT=event_name, PYTHONUTF8="1")
            environment_block = ctypes.create_unicode_buffer("\0".join(
                f"{key}={value}" for key, value in sorted(environment.items(), key=lambda item: item[0].upper())) + "\0\0")
            # list2cmdline is Windows argv quoting, never a shell invocation.
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            process = _ProcessInfo()
            flags = 0x4 | 0x08000000 | 0x400 | 0x80000  # suspended/no-window/Unicode/extended startup
            win.checked(api.CreateProcessW(command[0], command_line, None, None, True,
                flags, environment_block, str(handle.cwd), ctypes.byref(startup), ctypes.byref(process)))
            handle.pid = process.dwProcessId
            handle._native.update(process=process.hProcess, thread=process.hThread)
            in_job = wintypes.BOOL()
            win.checked(api.IsProcessInJob(process.hProcess, handle._native["job"], ctypes.byref(in_job)))
            if not in_job.value:
                raise RuntimeError("PROCESS_JOB_OWNERSHIP_UNCONFIRMED")
            self.leases.start(task_id=handle.task_id, attempt_id=handle.attempt_id,
                pid=handle.pid, owner_pid=os.getpid(), remote_id=handle.remote_id,
                cwd=handle.cwd, temp_dir=handle.temp_dir, step_id=handle.step_id)
            if api.ResumeThread(process.hThread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            api.DeleteProcThreadAttributeList(attributes)
        for name in ("thread", "stdin", "stdout_write", "stderr_write"):
            self._close_native(handle, name)

    def _cleanup_start(self, handle: ProcessHandle) -> None:
        api = self._windows.api
        if "process" in handle._native:
            # Also covers a suspended child when Job assignment was rejected.
            self._windows.checked(api.TerminateProcess(handle._native["process"], 1))
            api.WaitForSingleObject(handle._native["process"], int(self.limits.kill_wait_seconds * 1000))
        for name in list(handle._native):
            self._close_native(handle, name)
        self._remove_temp(handle)

    def _cleanup_failed(self, handle: ProcessHandle) -> dict:
        """Job close is an independent kernel fallback when query fails."""
        errors = []
        try:
            self._close_native(handle, "job")
        except OSError as exc:
            errors.append(type(exc).__name__)
        deadline = time.monotonic() + self.limits.kill_wait_seconds
        if "job" not in handle._native:
            for reader in handle._readers:
                if reader is not threading.current_thread():
                    reader.join(timeout=max(0, deadline - time.monotonic()))
            for name in list(handle._native):
                if name in {"stdout", "stderr"} and any(reader.is_alive() for reader in handle._readers):
                    continue
                try:
                    self._close_native(handle, name)
                except OSError as exc:
                    errors.append(type(exc).__name__)
            if not any(reader.is_alive() for reader in handle._readers):
                try:
                    self._remove_temp(handle)
                except (OSError, RuntimeError) as exc:
                    errors.append(type(exc).__name__)
        audit = {"error_type": type(handle._error).__name__, "job_closed": "job" not in handle._native,
            "open_handles": len(handle._native), "temp_removed": not handle.temp_dir.exists(),
            "reader_threads_alive": sum(reader.is_alive() for reader in handle._readers), "cleanup_errors": errors}
        self.leases.failure(handle.task_id, handle.attempt_id, handle.step_id, audit)
        return audit

    def _read(self, handle: ProcessHandle, stream: str) -> None:
        api = self._windows.api
        buffer = ctypes.create_string_buffer(4096)
        count = wintypes.DWORD()
        native = handle._native[stream]
        try:
            while api.ReadFile(native, buffer, len(buffer), ctypes.byref(count), None):
                if not count.value:
                    break
                if handle._output.append(stream, buffer.raw[:count.value]):
                    handle._resource_hit.set()
            error = ctypes.get_last_error()
            if error not in (0, 109):  # broken pipe is normal after complete tree exit
                raise ctypes.WinError(error)
        except BaseException as exc:
            handle._error = exc
            handle._resource_hit.set()
        finally:
            self._close_native(handle, stream)

    def _kill(self, handle: ProcessHandle) -> None:
        with handle._native_lock:
            job = handle._native.get("job")
            if job:
                self._windows.checked(self._windows.api.TerminateJobObject(job, 1))
                handle._forced = True

    def _monitor(self, handle: ProcessHandle) -> None:
        readers = [threading.Thread(target=self._read, args=(handle, stream), daemon=True,
                    name=f"runtime-{stream}-{handle.pid}") for stream in ("stdout", "stderr")]
        handle._readers = readers
        for reader in readers:
            reader.start()
        try:
            api = self._windows.api
            while api.WaitForSingleObject(handle._native["process"], 20) == 0x102:
                if handle._resource_hit.is_set():
                    self._kill(handle)
            code = wintypes.DWORD()
            self._windows.checked(api.GetExitCodeProcess(handle._native["process"], ctypes.byref(code)))
            job = handle._native["job"]
            # Cooperating descendants may finish shortly after their parent.
            while (handle._cancel_requested and not handle._resource_hit.is_set()
                   and time.monotonic() < handle._cancel_deadline
                   and self._windows.active_processes(job)):
                time.sleep(0.01)
            # A finished root never transfers ownership of its descendants.
            if self._windows.active_processes(job):
                self._kill(handle)
            deadline = time.monotonic() + self.limits.kill_wait_seconds
            while self._windows.active_processes(job):
                if time.monotonic() >= deadline:
                    raise TimeoutError("LOCAL_TREE_STOP_UNCONFIRMED")
                time.sleep(0.01)
            for reader in readers:
                reader.join(timeout=max(0.01, deadline - time.monotonic()))
                if reader.is_alive():
                    raise TimeoutError("OUTPUT_DRAIN_UNCONFIRMED")
            if handle._error:
                raise handle._error
            local_state = ("resource_limit" if handle._resource_hit.is_set() else
                "cancelled" if handle._cancel_requested else "exited" if code.value == 0 else "failed")
            for name in list(handle._native):
                self._close_native(handle, name)
            self._remove_temp(handle)
            seen, kept, truncated = handle._output.snapshot()
            remote_state = "stopped" if handle._remote_confirmed else "unknown" if handle.remote_id else "not_applicable"
            result = ProcessResult(local_state, remote_state,
                "cancel_pending_remote" if handle._cancel_requested and remote_state == "unknown" else local_state,
                code.value, handle.pid, handle._cancel_requested, handle._forced,
                seen, kept, truncated, "output_bytes" if handle._resource_hit.is_set() else None)
            self.leases.finish(handle.task_id, handle.attempt_id, asdict(result), handle.step_id)
            handle._result = result
        except BaseException as exc:
            handle._error = exc
            try:
                self._cleanup_failed(handle)
            finally:
                with self._lock:
                    self._failed[(handle.task_id, handle.attempt_id, handle.step_id)] = handle
                    self._closed = True
        finally:
            with self._lock:
                self._active.pop((handle.task_id, handle.attempt_id, handle.step_id), None)
            handle._done.set()

    def _require_owned(self, handle: ProcessHandle) -> None:
        if not isinstance(handle, ProcessHandle) or handle._owner is not self:
            raise ValueError("FOREIGN_PROCESS_HANDLE")

    def poll(self, handle: ProcessHandle) -> ProcessResult | None:
        self._require_owned(handle)
        if handle._done.is_set():
            if handle._error:
                raise RuntimeError("PROCESS_CLEANUP_FAILED") from handle._error
            return handle._result
        return None

    def wait(self, handle: ProcessHandle, timeout: float | None = None) -> ProcessResult:
        self._require_owned(handle)
        if not handle._done.wait(timeout):
            raise TimeoutError("PROCESS_WAIT_TIMEOUT")
        result = self.poll(handle)
        assert result is not None
        return result

    def cancel(self, handle: ProcessHandle, remote_stop_confirmed: bool = False) -> ProcessResult:
        self._require_owned(handle)
        if not isinstance(remote_stop_confirmed, bool):
            raise TypeError("REMOTE_CONFIRMATION_BOOLEAN_REQUIRED")
        with handle._cancel_lock:
            if remote_stop_confirmed and handle.remote_id is not None:
                handle._remote_confirmed = True
            if not handle._done.is_set():
                handle._cancel_requested = True
                handle._cancel_deadline = time.monotonic() + self.limits.cancel_grace_seconds
                with handle._native_lock:
                    event = handle._native.get("event")
                    if event:
                        self._windows.checked(self._windows.api.SetEvent(event))
                if not handle._done.wait(self.limits.cancel_grace_seconds):
                    self._kill(handle)
            result = self.wait(handle, timeout=self.limits.kill_wait_seconds)
            if handle._remote_confirmed and result.remote_state != "stopped":
                result = ProcessResult(**{**asdict(result), "remote_state": "stopped", "status": result.local_state})
                self.leases.finish(handle.task_id, handle.attempt_id, asdict(result), handle.step_id)
                handle._result = result
            return result

    def resource_snapshot(self) -> dict:
        with self._lock:
            active_processes = 0
            owned_handles = 0
            owned = {**self._failed, **self._active}
            query_errors = []
            for handle in owned.values():
                with handle._native_lock:
                    owned_handles += len(handle._native)
                    if "job" in handle._native:
                        try:
                            active_processes += self._windows.active_processes(handle._native["job"])
                        except OSError as exc:
                            query_errors.append(type(exc).__name__)
            return {"running": len(self._active), "temp_dirs": sum(handle.temp_dir.exists() for handle in owned.values()),
                "open_handles": owned_handles, "peak_reserved_handles": self._peak_handles,
                "active_processes": None if query_errors else active_processes,
                "failed_cleanups": len(self._failed), "query_errors": query_errors}

    def confirm_remote_stop(self, task_id: str, attempt_id: str, step_id: str = "default", *,
                            remote_stop_confirmed: bool) -> dict:
        if remote_stop_confirmed is not True:
            raise TypeError("EXPLICIT_REMOTE_STOP_CONFIRMATION_REQUIRED")
        return self.leases.confirm_remote_stop(task_id, attempt_id, step_id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            handles = list(self._active.values())
            failures = list(self._failed.values())
        errors = []
        for handle in handles:
            try:
                self.cancel(handle)
            except BaseException as exc:
                errors.append(exc)
        for handle in failures:
            audit = self._cleanup_failed(handle)
            if audit["open_handles"] or not audit["temp_removed"] or audit["reader_threads_alive"]:
                errors.append(RuntimeError("FAILED_CLEANUP_STILL_PENDING"))
        if errors:
            raise RuntimeError("PROCESS_MANAGER_CLEANUP_FAILED") from errors[0]

    def __enter__(self) -> ProcessManager:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
