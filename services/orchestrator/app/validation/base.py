"""Trusted snapshot/runner inputs; mechanical results never replace A review."""
from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Callable, Mapping, Sequence
import uuid


@dataclass(frozen=True)
class ArtifactSnapshot:
    revision_id: str
    byte_sha256: str
    path: Path

    def __post_init__(self):
        if not isinstance(self.revision_id,str) or not self.revision_id.strip() or not isinstance(self.byte_sha256,str) or re.fullmatch(r"[a-f0-9]{64}",self.byte_sha256) is None:
            raise ValueError("ARTIFACT_SNAPSHOT_BINDING_REQUIRED")


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    truncated: bool = False
    executed: bool = True


@dataclass
class ValidationContext:
    task_id: str
    attempt_id: str
    artifact: ArtifactSnapshot
    criteria: Sequence
    workspace: Path
    source: ArtifactSnapshot | None = None
    runner: Callable | None = None
    commands: Mapping[str,list[str]] = field(default_factory=dict)
    data_inputs: Mapping[str,ArtifactSnapshot] = field(default_factory=dict)
    connection: sqlite3.Connection | None = None
    environment: dict = field(default_factory=dict)
    execution_authorized: bool = False
    store: object | None = None
    protected_names: Sequence[str] = field(default_factory=tuple)
    timeout_seconds: float = 15
    rendered_paths: Mapping[str,Path] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    criterion_id: str
    revision_id: str
    artifact_sha256: str
    validator_id: str
    validator_version: str
    status: str
    reason_code: str
    evidence_ref: str | None
    evidence_sha256: str | None
    method: str
    environment: dict
    duration_ms: float
    pending_A_review: tuple[str,...] = ()

    @property
    def passed(self):
        return self.status == "pass"

    def to_dict(self):
        return {**asdict(self),"passed":self.passed}


@dataclass(frozen=True)
class Observation:
    status: str
    reason_code: str
    method: str
    details: dict = field(default_factory=dict)
    pending_A_review: tuple[str,...] = ()


class NativeMechanicalRunner:
    """D011 owns the native process tree; this wrapper supplies no OS sandbox."""
    def __init__(self, manager, task_id: str, attempt_id: str, step_prefix="validator"):
        self.manager, self.task_id, self.attempt_id, self.step_prefix = manager,task_id,attempt_id,step_prefix

    def __call__(self, argv, cwd, timeout):
        handle = self.manager.start(self.task_id,self.attempt_id,list(argv),Path(cwd),step_id=self.step_prefix+"-"+uuid.uuid4().hex)
        timed_out = False
        try:
            result = self.manager.wait(handle,timeout=timeout)
        except TimeoutError:
            timed_out = True
            result = self.manager.cancel(handle)
        return CommandResult(result.returncode,handle.stdout,handle.stderr,timed_out=timed_out,truncated=result.output_truncated,executed=True)


def snapshot_bytes(context: ValidationContext, snapshot: ArtifactSnapshot) -> bytes:
    root = Path(context.workspace).resolve()
    path = Path(snapshot.path)
    resolved = path.resolve()
    authorized_blob = context.store is not None and context.connection is not None and resolved == context.store.path_for(snapshot.byte_sha256).resolve()
    if not resolved.is_relative_to(root) and not authorized_blob:
        raise ValueError("ARTIFACT_OUTSIDE_AUTHORIZED_SCOPE")
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
        raise ValueError("ARTIFACT_SYMLINK_FORBIDDEN")
    if not path.is_file() or path.stat().st_size > 16_000_000:
        raise ValueError("ARTIFACT_MISSING_OR_TOO_LARGE")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != snapshot.byte_sha256:
        raise ValueError("ARTIFACT_HASH_MISMATCH")
    if authorized_blob:
        row = context.connection.execute("SELECT byte_sha256 FROM artifact_revisions WHERE id=? AND task_id=? AND attempt_id=?", (snapshot.revision_id,context.task_id,context.attempt_id)).fetchone()
        if row is None or row[0] != snapshot.byte_sha256:
            raise ValueError("ARTIFACT_REVISION_BINDING_MISMATCH")
    return data


def run_command(context: ValidationContext, criterion, method: str) -> Observation:
    command = context.commands.get(criterion.id)
    if context.runner is None or not isinstance(command,list) or not command or any(not isinstance(arg,str) or not arg or "\0" in arg for arg in command):
        return Observation("blocked","TOOL_UNAVAILABLE",method)
    if context.execution_authorized is not True:
        return Observation("blocked","OS_SANDBOX_UNVERIFIED",method)
    try:
        result = context.runner(command,Path(context.workspace),context.timeout_seconds)
    except (OSError,ValueError,RuntimeError):
        return Observation("blocked","TOOL_EXECUTION_UNAVAILABLE",method)
    if not isinstance(result,CommandResult) or result.executed is not True:
        return Observation("not_verified","COMMAND_NOT_EXECUTED",method)
    details = {"command":command,"exit_code":result.exit_code,"stdout":result.stdout.decode("utf-8",errors="replace"),"stderr":result.stderr.decode("utf-8",errors="replace"),"executed":True,"timed_out":result.timed_out,"truncated":result.truncated}
    if result.timed_out:
        return Observation("blocked","VALIDATOR_TIMEOUT",method,details)
    if result.truncated:
        return Observation("not_verified","VALIDATOR_OUTPUT_TRUNCATED",method,details)
    if type(result.exit_code) is not int:
        return Observation("not_verified","COMMAND_EXIT_STATUS_UNKNOWN",method,details)
    if result.exit_code != 0:
        return Observation("fail","VALIDATOR_COMMAND_FAILED",method,details)
    return Observation("pass","COMMAND_EXECUTED_SUCCESSFULLY",method,details)
