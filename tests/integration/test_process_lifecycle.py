"""Only temp-directory fixtures; no real model or provider calls."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.runtime.processes import ProcessManager
from app.runtime.resources import ResourceLimits

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects")]
WORKER = Path(__file__).parents[1] / "fixtures" / "process_worker.py"
PYTHON = str(Path(sys._base_executable).resolve())


def until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    raise AssertionError("condition did not become true before deadline")


def alive(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.OpenProcess(0x00100000, False, pid)
    if not process:
        return False
    try:
        return kernel.WaitForSingleObject(process, 0) == 0x102
    finally:
        kernel.CloseHandle(process)


def command(root, *arguments):
    return [PYTHON, str(WORKER.resolve()), "--root", str(root), *arguments]


def tree(root):
    return [json.loads(path.read_text(encoding="utf-8")) for path in root.glob("worker-*.json")]


@pytest.fixture
def manager(tmp_path):
    value = ProcessManager(tmp_path / "leases.sqlite3")
    try:
        yield value
    finally:
        value.close()


def test_native_argv_workspace_and_credentials_are_isolated(manager, tmp_path, monkeypatch):
    monkeypatch.setenv("D011_SECRET_CANARY", "fixture-secret")
    root = tmp_path / "workspace with spaces"
    root.mkdir()
    malicious = 'two words "quote" & echo forbidden > unexpected.txt | ; $(bad)'
    handle = manager.start("t1", "a1", command(root, "--literal", malicious, "--exit-code", "0"), root)
    result = manager.wait(handle, timeout=8)
    info = tree(root)[0]
    assert result.local_state == "exited" and result.returncode == 0
    assert info["literal"] == malicious
    assert info["cwd"] == str(root.resolve()) and not info["secret_inherited"]
    assert info["temp"] == str(handle.temp_dir)
    assert not (root / "unexpected.txt").exists()
    assert not handle.temp_dir.exists()
    lease = manager.leases.records()[0]
    assert (lease["task_id"], lease["attempt_id"], lease["pid"]) == ("t1", "a1", handle.pid)
    assert lease["local_state"] == "exited"


def test_cooperative_cancel_reaches_child_and_grandchild(manager, tmp_path):
    handle = manager.start("t2", "a1", command(tmp_path, "--tree"), tmp_path)
    workers = until(lambda: tree(tmp_path) if len(tree(tmp_path)) == 3 else None)
    result = manager.cancel(handle)
    assert result.local_state == "cancelled" and result.cooperative_requested
    assert not result.forced
    assert len(list(tmp_path.glob("cooperative-*.json"))) == 3
    until(lambda: all(not alive(item["pid"]) for item in workers))


def test_ignored_cancel_kills_complete_job_tree_and_preserves_remote_unknown(manager, tmp_path):
    handle = manager.start("t3", "a1", command(tmp_path, "--tree", "--ignore-cancel"), tmp_path, remote_id="remote-session-3")
    workers = until(lambda: tree(tmp_path) if len(tree(tmp_path)) == 3 else None)
    started = time.monotonic()
    result = manager.cancel(handle)
    assert result.local_state == "cancelled" and result.forced
    assert result.status == "cancel_pending_remote" and result.remote_state == "unknown"
    assert time.monotonic() - started < 7
    until(lambda: all(not alive(item["pid"]) for item in workers))
    lease = manager.leases.records()[0]
    assert lease["remote_id"] == "remote-session-3" and lease["remote_state"] == "unknown"
    confirmed = manager.cancel(handle, remote_stop_confirmed=True)
    assert confirmed.remote_state == "stopped" and confirmed.status == "cancelled"


def test_output_flood_hits_shared_byte_budget_while_streaming(tmp_path):
    manager = ProcessManager(tmp_path / "leases.sqlite3", ResourceLimits(max_output_bytes=2048))
    try:
        handle = manager.start("flood", "a1", command(tmp_path, "--flood", "--ignore-cancel"), tmp_path)
        result = manager.wait(handle, timeout=8)
        assert result.local_state == "resource_limit"
        assert result.output_bytes_seen > 2048
        assert result.output_bytes_kept == len(handle.stdout) + len(handle.stderr) <= 2048
        assert result.output_truncated and not alive(handle.pid)
        assert manager.resource_snapshot()["open_handles"] == 0
    finally:
        manager.close()


def test_job_active_process_limit_rejects_child_starts(tmp_path):
    manager = ProcessManager(tmp_path / "leases.sqlite3", ResourceLimits(max_processes_per_job=3))
    try:
        handle = manager.start("limit", "a1", command(tmp_path, "--spawn-many", "8", "--ignore-cancel"), tmp_path)
        attempts = until(lambda: json.loads((tmp_path / "spawn-attempts.json").read_text()) if (tmp_path / "spawn-attempts.json").exists() else None)
        assert sum(item["accepted"] for item in attempts) == 2
        assert sum(not item["accepted"] for item in attempts) == 6
        pids = [handle.pid] + [item["pid"] for item in attempts if item["accepted"]]
        until(lambda: len(tree(tmp_path)) == 3)
        assert sum(alive(pid) for pid in pids) == 3
        # Job accounting can retain rejected, already terminated process refs.
        # The actual workers that reached their entry point are the live budget.
        assert len(tree(tmp_path)) == 3
        manager.cancel(handle)
        until(lambda: all(not alive(pid) for pid in pids))
    finally:
        manager.close()


def test_running_temp_directory_and_handle_budgets_reject_before_start(tmp_path):
    for index, limits in enumerate((ResourceLimits(max_running=1), ResourceLimits(max_temp_dirs=1), ResourceLimits(max_open_handles=9))):
        root = tmp_path / f"budget-{index}"
        root.mkdir()
        second = root / "second"
        second.mkdir()
        manager = ProcessManager(root / "leases.sqlite3", limits)
        try:
            handle = manager.start("limit", "a1", command(root), root)
            until(lambda: tree(root))
            with pytest.raises(RuntimeError, match="RESOURCE_LIMIT"):
                manager.start("limit", "a2", command(second), second)
            assert len(manager.leases.records()) == 1
            manager.cancel(handle)
            assert manager.resource_snapshot()["open_handles"] == 0
        finally:
            manager.close()


def test_non_native_and_invalid_arguments_are_rejected(manager, tmp_path):
    for invalid in (["cmd.cmd"], ["powershell.ps1"], [], [sys.executable, "bad\0arg"], "echo bad"):
        with pytest.raises((TypeError, ValueError, FileNotFoundError)):
            manager.start("invalid", "a1", invalid, tmp_path)
    assert manager.leases.records() == []


def test_workspace_reuse_and_closed_manager_are_rejected(manager, tmp_path):
    handle = manager.start("t", "a", command(tmp_path), tmp_path)
    with pytest.raises(RuntimeError, match="WORKSPACE_IN_USE"):
        manager.start("t2", "a2", command(tmp_path), tmp_path)
    manager.cancel(handle)
    manager.close()
    with pytest.raises(RuntimeError, match="MANAGER_CLOSED"):
        manager.start("t3", "a3", command(tmp_path), tmp_path)


@pytest.mark.parametrize("exit_code,state", [(0, "exited"), (9, "failed")])
def test_normal_and_abnormal_exit_cleanup(manager, tmp_path, exit_code, state):
    handle = manager.start("exit", "a1", command(tmp_path, "--exit-code", str(exit_code)), tmp_path)
    result = manager.wait(handle, timeout=8)
    assert result.returncode == exit_code and result.local_state == state
    assert manager.resource_snapshot()["open_handles"] == 0
    assert not handle.temp_dir.exists()


def test_parent_exit_also_reclaims_living_descendants(manager, tmp_path):
    handle = manager.start("exit-parent", "a1", command(tmp_path, "--tree", "--ignore-cancel", "--exit-on-trigger"), tmp_path)
    workers = until(lambda: tree(tmp_path) if len(tree(tmp_path)) == 3 else None)
    (tmp_path / "exit-trigger.txt").write_text("exit normally", encoding="utf-8")
    manager.wait(handle, timeout=8)
    until(lambda: all(not alive(item["pid"]) for item in workers))


def test_service_forced_exit_closes_job_and_reclaims_tree(tmp_path):
    env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT"}}
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "services" / "orchestrator")
    service = subprocess.Popen(command(tmp_path, "--mode", "service"), cwd=tmp_path, env=env,
        shell=False, creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        workers = until(lambda: tree(tmp_path) if len(tree(tmp_path)) == 3 else None)
        service.kill()
        service.wait(timeout=5)
        until(lambda: all(not alive(item["pid"]) for item in workers))
    finally:
        if service.poll() is None:
            service.kill()
            service.wait(timeout=5)
        if service.stderr:
            service.stderr.close()


def test_limits_require_positive_finite_budgets():
    for invalid in ({"max_running": 0}, {"max_output_bytes": -1}, {"max_processes_per_job": True}, {"cancel_grace_seconds": -1}, {"kill_wait_seconds": float("inf")}):
        with pytest.raises(ValueError, match="INVALID_RESOURCE_LIMIT"):
            ResourceLimits(**invalid)


def test_lease_survives_reopen_and_attempt_cannot_be_reused(tmp_path):
    path = tmp_path / "leases.sqlite3"
    manager = ProcessManager(path)
    handle = manager.start("persist", "a1", command(tmp_path, "--exit-code", "0"), tmp_path, remote_id="session-kept")
    manager.wait(handle, timeout=8)
    manager.close()
    reopened = ProcessManager(path)
    try:
        lease = reopened.leases.records()[0]
        assert lease["remote_id"] == "session-kept" and lease["remote_state"] == "unknown"
        with pytest.raises(RuntimeError, match="ATTEMPT_ALREADY_STARTED"):
            reopened.start("persist", "a1", command(tmp_path), tmp_path)
    finally:
        reopened.close()


def test_remote_confirmation_requires_an_explicit_boolean(manager, tmp_path):
    handle = manager.start("confirm", "a1", command(tmp_path), tmp_path, remote_id="unknown-session")
    with pytest.raises(TypeError, match="REMOTE_CONFIRMATION_BOOLEAN_REQUIRED"):
        manager.cancel(handle, remote_stop_confirmed="false")
    assert manager.cancel(handle).remote_state == "unknown"


def test_failed_native_launch_removes_owned_temp_and_handles(manager, tmp_path):
    invalid_exe = tmp_path / "invalid native.exe"
    invalid_exe.write_bytes(b"this is not a PE executable")
    with pytest.raises(OSError):
        manager.start("bad-pe", "a1", [str(invalid_exe)], tmp_path)
    assert not list(tmp_path.glob(".runtime-*"))
    assert manager.resource_snapshot()["open_handles"] == 0
    assert manager.leases.records() == []


def test_repeated_launches_do_not_leak_os_handles(manager, tmp_path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessHandleCount.restype = wintypes.BOOL
    def handle_count():
        count = wintypes.DWORD()
        assert kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(count))
        return count.value
    warmup = manager.start("handles", "warmup", command(tmp_path, "--exit-code", "0"), tmp_path)
    manager.wait(warmup, timeout=8)
    baseline = handle_count()
    for index in range(10):
        handle = manager.start("handles", f"a{index}", command(tmp_path, "--exit-code", "0"), tmp_path)
        manager.wait(handle, timeout=8)
    assert handle_count() <= baseline + 2
    assert manager.resource_snapshot()["open_handles"] == 0


def test_owner_death_after_create_does_not_leave_suspended_orphan(tmp_path):
    env = {key: value for key, value in os.environ.items() if key.upper() in ProcessManager.ENVIRONMENT_KEYS}
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "services" / "orchestrator")
    service = subprocess.Popen(command(tmp_path, "--mode", "service", "--crash-after-create"),
        cwd=tmp_path, env=env, shell=False, creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = None
    try:
        pid = until(lambda: json.loads((tmp_path / "created-pid.json").read_text())["pid"] if (tmp_path / "created-pid.json").exists() else None)
        service.wait(timeout=5)
        assert service.returncode == 73
        until(lambda: not alive(pid), timeout=2)
        assert not tree(tmp_path), "suspended worker must never execute"
    finally:
        if service.poll() is None:
            service.kill()
            service.wait(timeout=5)
        # The RED implementation leaves only the deliberately suspended fixture.
        # Clean that exact owned test PID; no production success depends on this.
        if pid is not None and alive(pid):
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            native = kernel.OpenProcess(1, False, pid)
            if native:
                kernel.TerminateProcess(native, 1)
                kernel.CloseHandle(native)


def test_same_attempt_can_run_two_distinct_steps_and_records_both(manager, tmp_path):
    first = manager.start("multi", "a1", command(tmp_path, "--exit-code", "0"), tmp_path, step_id="B.execute")
    manager.wait(first, timeout=8)
    second = manager.start("multi", "a1", command(tmp_path, "--exit-code", "0"), tmp_path, step_id="A.review")
    manager.wait(second, timeout=8)
    records = manager.leases.records()
    assert [(row["task_id"], row["attempt_id"], row["step_id"]) for row in records] == [
        ("multi", "a1", "B.execute"), ("multi", "a1", "A.review")]
    assert first.pid != second.pid
    with pytest.raises(RuntimeError, match="ATTEMPT_ALREADY_STARTED"):
        manager.start("multi", "a1", command(tmp_path), tmp_path, step_id="B.execute")


def test_remote_unknown_cancel_blocks_new_step_until_confirmation(manager, tmp_path):
    first = manager.start("remote", "a1", command(tmp_path), tmp_path, remote_id="remote-pending", step_id="B.execute")
    manager.cancel(first)
    with pytest.raises(RuntimeError, match="REMOTE_EXECUTION_UNCONFIRMED"):
        manager.start("remote", "a1", command(tmp_path), tmp_path, step_id="B.retry")
    manager.cancel(first, remote_stop_confirmed=True)
    second = manager.start("remote", "a1", command(tmp_path, "--exit-code", "0"), tmp_path, step_id="A.review")
    manager.wait(second, timeout=8)


def test_local_exit_with_unknown_remote_also_blocks_distinct_step(manager, tmp_path):
    handle = manager.start("remote-exit", "a1", command(tmp_path, "--exit-code", "0"), tmp_path,
                           remote_id="unknown-after-exit", step_id="B.execute")
    assert manager.wait(handle, timeout=8).remote_state == "unknown"
    with pytest.raises(RuntimeError, match="REMOTE_EXECUTION_UNCONFIRMED"):
        manager.start("remote-exit", "a1", command(tmp_path), tmp_path, step_id="A.review")


def test_crashed_owner_remote_lease_blocks_new_manager_restart(tmp_path):
    env = {key: value for key, value in os.environ.items() if key.upper() in ProcessManager.ENVIRONMENT_KEYS}
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "services" / "orchestrator")
    service = subprocess.Popen(command(tmp_path, "--mode", "service", "--remote-id", "unreconciled-remote"),
        cwd=tmp_path, env=env, shell=False, creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    manager = None
    try:
        workers = until(lambda: tree(tmp_path) if len(tree(tmp_path)) == 3 else None)
        service.kill()
        service.wait(timeout=5)
        until(lambda: all(not alive(item["pid"]) for item in workers))
        manager = ProcessManager(tmp_path / "leases.sqlite3")
        lease = manager.leases.records()[0]
        assert lease["local_state"] == "running" and lease["remote_state"] == "unknown"
        with pytest.raises(RuntimeError, match="REMOTE_EXECUTION_UNCONFIRMED"):
            manager.start("parent-exit", "a1", command(tmp_path), tmp_path, step_id="restart")
    finally:
        if service.poll() is None:
            service.kill()
            service.wait(timeout=5)
        if manager is not None:
            manager.close()


def test_monitor_failure_cleans_temp_and_records_failed_accounting(tmp_path, monkeypatch):
    manager = ProcessManager(tmp_path / "leases.sqlite3")
    original = manager._windows.active_processes
    try:
        handle = manager.start("query-failure", "a1", command(tmp_path, "--tree", "--ignore-cancel", "--exit-on-trigger"), tmp_path)
        workers = until(lambda: tree(tmp_path) if len(tree(tmp_path)) == 3 else None)
        def failure(job):
            raise OSError("D011 injected QueryInformation failure")
        monkeypatch.setattr(manager._windows, "active_processes", failure)
        (tmp_path / "exit-trigger.txt").write_text("exit", encoding="utf-8")
        with pytest.raises(RuntimeError, match="PROCESS_CLEANUP_FAILED"):
            manager.wait(handle, timeout=8)
        until(lambda: all(not alive(item["pid"]) for item in workers))
        assert not handle.temp_dir.exists()
        snapshot = manager.resource_snapshot()
        assert snapshot["failed_cleanups"] == 1 and snapshot["open_handles"] == snapshot["temp_dirs"] == 0
        assert manager.leases.records()[0]["local_state"] == "cleanup_failed"
        assert handle.local_state == "cleanup_failed"
        with pytest.raises(RuntimeError, match="MANAGER_CLOSED"):
            manager.start("new", "a1", command(tmp_path), tmp_path)
    finally:
        monkeypatch.setattr(manager._windows, "active_processes", original)
        manager.close()
