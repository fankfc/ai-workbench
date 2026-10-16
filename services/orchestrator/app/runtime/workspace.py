"""Service-enforced task scopes and persistent exclusive write leases.

These checks protect operations through this gateway. A normal same-user CLI
can bypass it; execution_directory requires an explicit acknowledgement of that
limitation and never labels an ordinary directory as an OS sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import threading
import time
import uuid


class ScopeError(PermissionError):
    pass


@dataclass(frozen=True)
class WriteLease:
    area: str
    role: str
    token: str
    epoch: int
    workspace: str


class WorkspaceManager:
    def __init__(self, data_root: Path):
        path = Path(data_root).absolute()
        _reject_reparse(path)
        self.data_root = path.resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._workspaces = {}
        self._lock = threading.RLock()

    def create(self, task_id: str, attempt_id: str) -> TaskWorkspace:
        if any(not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None
               for value in (task_id, attempt_id)):
            raise ScopeError("TASK_SCOPE_ID_INVALID")
        with self._lock:
            key = task_id, attempt_id
            if key not in self._workspaces:
                self._workspaces[key] = TaskWorkspace(self.data_root / "tasks" / task_id / attempt_id)
            return self._workspaces[key]


def _reject_reparse(path: Path) -> None:
    for ancestor in reversed((path, *path.parents)):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ScopeError("REPARSE_POINT_DENIED")


class TaskWorkspace:
    AREAS = frozenset({"input", "a", "b", "translation", "evidence", "artifacts"})
    WRITABLE = {"A": frozenset({"a", "b"}), "B": frozenset({"b"}),
                "service": frozenset({"a", "b", "translation", "evidence", "artifacts"})}
    RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})

    def __init__(self, root: Path) -> None:
        _reject_reparse(root)
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        for name in self.AREAS:
            area = self.root / name
            _reject_reparse(area)
            area.mkdir(exist_ok=True)

    def area(self, name: str) -> Path:
        if name not in self.AREAS:
            raise ScopeError("WORKSPACE_AREA_INVALID")
        path = self.root / name
        _reject_reparse(path)
        return path

    def _path(self, relative_path: str | Path) -> Path:
        text = str(relative_path)
        windows = PureWindowsPath(text)
        if (not text or "\0" in text or "%" in text or ":" in text
                or windows.drive or windows.root or text.startswith(("/", "\\"))):
            raise ScopeError("PATH_SCOPE_INVALID")
        parts = text.replace("\\", "/").split("/")
        if any(not part or part in (".", "..") or part.rstrip(" .") != part
               or part.split(".")[0].upper() in self.RESERVED for part in parts):
            raise ScopeError("PATH_SCOPE_INVALID")
        if len(parts) < 2 or parts[0] not in self.AREAS:
            raise ScopeError("WORKSPACE_AREA_INVALID")
        candidate = self.root.joinpath(*parts)
        _reject_reparse(candidate)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root):
            raise ScopeError("PATH_SCOPE_ESCAPE")
        if resolved.exists() and resolved.is_file() and resolved.stat().st_nlink > 1:
            raise ScopeError("HARDLINK_DENIED")
        return resolved

    def resolve(self, relative_path: str | Path, role: str = "service", write: bool = False) -> Path:
        if role not in self.WRITABLE:
            raise ScopeError("ROLE_INVALID")
        path = self._path(relative_path)
        if write and path.relative_to(self.root).parts[0] not in self.WRITABLE[role]:
            raise ScopeError("ROLE_WRITE_DENIED")
        return path

    @contextmanager
    def _state_lock(self):
        with self._lock:
            lock_path = self.root / ".lease-lock"
            _reject_reparse(lock_path)
            with lock_path.open("a+b") as stream:
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise ScopeError("WRITE_LEASE_LOCK_TIMEOUT")
                            time.sleep(0.01)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream, fcntl.LOCK_UN)

    def _json(self, filename: str) -> dict:
        path = self.root / filename
        _reject_reparse(path)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save_json(self, filename: str, value: dict) -> None:
        self._replace(self.root / filename, json.dumps(value, sort_keys=True).encode("utf-8"))

    def _replace(self, path: Path, content: bytes) -> None:
        _reject_reparse(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse(path.parent)
        temporary = path.parent / (".write-" + uuid.uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            _reject_reparse(path)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def ingest_source(self, relative_name: str, content: bytes) -> Path:
        if not isinstance(content, bytes):
            raise TypeError("WORKSPACE_BYTES_REQUIRED")
        with self._state_lock():
            path = self._path("input/" + relative_name)
            manifest = self._json(".source-manifest.json")
            key = path.relative_to(self.root).as_posix()
            if path.exists() or key in manifest:
                raise ScopeError("SOURCE_IMMUTABLE")
            self._replace(path, content)
            os.chmod(path, stat.S_IREAD)
            manifest[key] = hashlib.sha256(content).hexdigest()
            self._save_json(".source-manifest.json", manifest)
            return path

    def read(self, role: str, relative_path: str | Path) -> bytes:
        with self._state_lock():
            path = self.resolve(relative_path, role)
            content = path.read_bytes()
            if path.relative_to(self.root).parts[0] == "input":
                expected = self._json(".source-manifest.json").get(path.relative_to(self.root).as_posix())
                if expected is None or hashlib.sha256(content).hexdigest() != expected:
                    raise ScopeError("SOURCE_INTEGRITY_FAILED")
            return content

    def _check_role_area(self, role: str, area: str) -> None:
        if role not in self.WRITABLE or area not in self.WRITABLE[role]:
            raise ScopeError("ROLE_WRITE_DENIED")

    def acquire_write_lease(self, role: str, area: str) -> WriteLease:
        self._check_role_area(role, area)
        with self._state_lock():
            state = self._json(".write-leases.json")
            previous = state.get(area, {})
            if previous.get("token"):
                raise ScopeError("WRITE_LEASE_HELD")
            lease = WriteLease(area, role, uuid.uuid4().hex, previous.get("epoch", 0) + 1, str(self.root))
            state[area] = {"role": role, "token": lease.token, "epoch": lease.epoch}
            self._save_json(".write-leases.json", state)
            return lease

    def _check_lease(self, lease: WriteLease, state: dict, role: str, area: str) -> None:
        if (not isinstance(lease, WriteLease) or lease.workspace != str(self.root)
                or lease.area != area or lease.role != role
                or state.get(area) != {"role": role, "token": lease.token, "epoch": lease.epoch}):
            raise ScopeError("WRITE_LEASE_STALE")

    def handoff(self, lease: WriteLease, to_role: str) -> WriteLease:
        self._check_role_area(to_role, lease.area)
        with self._state_lock():
            state = self._json(".write-leases.json")
            self._check_lease(lease, state, lease.role, lease.area)
            replacement = WriteLease(lease.area, to_role, uuid.uuid4().hex, lease.epoch + 1, str(self.root))
            state[lease.area] = {"role": to_role, "token": replacement.token, "epoch": replacement.epoch}
            self._save_json(".write-leases.json", state)
            return replacement

    def release(self, lease: WriteLease) -> None:
        with self._state_lock():
            state = self._json(".write-leases.json")
            self._check_lease(lease, state, lease.role, lease.area)
            state[lease.area] = {"role": lease.role, "token": None, "epoch": lease.epoch}
            self._save_json(".write-leases.json", state)

    def lease_snapshot(self) -> dict:
        with self._state_lock():
            return self._json(".write-leases.json")

    def write(self, role: str, relative_path: str | Path, content: bytes,
              lease: WriteLease | None = None) -> Path:
        if not isinstance(content, bytes):
            raise TypeError("WORKSPACE_BYTES_REQUIRED")
        with self._state_lock():
            path = self.resolve(relative_path, role, write=True)
            area = path.relative_to(self.root).parts[0]
            if area in {"a", "b"}:
                self._check_lease(lease, self._json(".write-leases.json"), role, area)
            self._replace(path, content)
            return path

    def execution_directory(self, role: str, require_os_sandbox: bool = True) -> Path:
        if require_os_sandbox:
            raise ScopeError("OS_SANDBOX_UNVERIFIED")
        if role not in {"A", "B"}:
            raise ScopeError("ROLE_INVALID")
        return self.area(role.lower())
