from __future__ import annotations

import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.runtime.workspace import ScopeError, WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    return WorkspaceManager(tmp_path / "data").create("task-1", "attempt-1")


def test_attempts_have_independent_six_areas(tmp_path):
    manager = WorkspaceManager(tmp_path / "data")
    first, second = manager.create("t1", "a1"), manager.create("t2", "a1")
    for name in ("input", "a", "b", "translation", "evidence", "artifacts"):
        assert first.area(name).is_dir() and second.area(name).is_dir()
        assert first.area(name) != second.area(name)
    first.ingest_source("same.txt", b"first")
    second.ingest_source("same.txt", b"second")
    assert first.read("A", "input/same.txt") == b"first"
    assert second.read("B", "input/same.txt") == b"second"


@pytest.mark.parametrize("path", ["../outside.txt", "input/../../outside.txt", "input/../a/pass.json",
    "input/%2e%2e/outside.txt", "input/%252e%252e/outside.txt", "input/file.txt:stream",
    "C:/outside.txt", "C:outside.txt", "//server/share/file", "\\\\server\\share\\file",
    "input/CON", "input/file. ", "input/bad\0name"])
def test_path_tricks_are_rejected(workspace, path):
    with pytest.raises(ScopeError):
        workspace.read("B", path)


def test_other_task_absolute_path_is_rejected(workspace, tmp_path):
    other = WorkspaceManager(tmp_path / "other").create("task-2", "attempt-1")
    path = other.ingest_source("private.txt", b"private")
    with pytest.raises(ScopeError):
        workspace.read("A", str(path))


def test_b_cannot_modify_source_a_or_evidence(workspace):
    workspace.ingest_source("source.txt", b"immutable source")
    for path in ("input/source.txt", "a/PASS.json", "evidence/proof.json", "artifacts/final.txt"):
        with pytest.raises(ScopeError, match="ROLE_WRITE_DENIED"):
            workspace.write("B", path, b"forged")
    assert workspace.read("A", "input/source.txt") == b"immutable source"
    with pytest.raises(ScopeError, match="SOURCE_IMMUTABLE"):
        workspace.ingest_source("source.txt", b"overwrite")


def test_explicit_handoff_revokes_old_owner_and_allows_b_to_resume(workspace):
    b_lease = workspace.acquire_write_lease("B", "b")
    workspace.write("B", "b/candidate.txt", b"draft", b_lease)
    with pytest.raises(ScopeError, match="WRITE_LEASE_HELD"):
        workspace.acquire_write_lease("A", "b")
    a_lease = workspace.handoff(b_lease, "A")
    with pytest.raises(ScopeError, match="WRITE_LEASE_STALE"):
        workspace.write("B", "b/candidate.txt", b"late B", b_lease)
    workspace.write("A", "b/candidate.txt", b"takeover", a_lease)
    resumed = workspace.handoff(a_lease, "B")
    workspace.write("B", "b/candidate.txt", b"resumed", resumed)
    assert workspace.read("A", "b/candidate.txt") == b"resumed"


def test_a_decision_lease_cannot_be_handed_to_b(workspace):
    lease = workspace.acquire_write_lease("A", "a")
    with pytest.raises(ScopeError, match="ROLE_WRITE_DENIED"):
        workspace.handoff(lease, "B")


def test_concurrent_lease_acquisition_has_one_owner(workspace):
    def acquire(role):
        try:
            return workspace.acquire_write_lease(role, "b")
        except ScopeError:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(executor.map(acquire, ["A", "B"]))
    assert sum(value is not None for value in leases) == 1


def test_lease_epoch_survives_workspace_reopen(tmp_path):
    manager = WorkspaceManager(tmp_path / "data")
    first = manager.create("t", "a")
    b = first.acquire_write_lease("B", "b")
    second = WorkspaceManager(tmp_path / "data").create("t", "a")
    a = second.handoff(b, "A")
    with pytest.raises(ScopeError, match="WRITE_LEASE_STALE"):
        first.write("B", "b/file.txt", b"stale", b)
    second.write("A", "b/file.txt", b"new owner", a)


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="real Windows junction")
def test_real_windows_junction_cannot_escape_scope(workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("private", encoding="utf-8")
    junction = workspace.area("b") / "escape"
    result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        shell=False, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    try:
        with pytest.raises(ScopeError, match="REPARSE_POINT_DENIED"):
            workspace.read("A", "b/escape/secret.txt")
        lease = workspace.acquire_write_lease("B", "b")
        with pytest.raises(ScopeError, match="REPARSE_POINT_DENIED"):
            workspace.write("B", "b/escape/inject.txt", b"bad", lease)
        assert not (outside / "inject.txt").exists()
    finally:
        os.rmdir(junction)


def test_directory_scope_does_not_claim_os_sandbox(workspace):
    with pytest.raises(ScopeError, match="OS_SANDBOX_UNVERIFIED"):
        workspace.execution_directory("B", require_os_sandbox=True)
    assert workspace.execution_directory("B", require_os_sandbox=False) == workspace.area("b")
