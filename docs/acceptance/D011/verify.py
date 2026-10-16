"""Reproduce D011 acceptance with local heartbeat workers, never model calls."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from app.runtime.processes import ProcessManager
from app.runtime.resources import ResourceLimits

REPOSITORY = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("d011_fixtures", REPOSITORY / "tests/integration/test_process_lifecycle.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def facts() -> dict:
    return {"at_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "python": sys.version, "provider_calls": 0, "mode": "real_windows_local_fixture",
        "command": "services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D011/verify.py",
        "source_sha256": {str(path.relative_to(REPOSITORY)).replace("\\", "/"):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in [
                REPOSITORY / "services/orchestrator/app/runtime/processes.py",
                REPOSITORY / "services/orchestrator/app/runtime/resources.py",
                REPOSITORY / "services/orchestrator/app/runtime/leases.py",
                REPOSITORY / "tests/fixtures/process_worker.py",
                REPOSITORY / "tests/integration/test_process_lifecycle.py"]}}


def run() -> None:
    process_report = {**facts(), "scenarios": []}
    resource_report = {**facts(), "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="D011-acceptance-") as directory:
        base = Path(directory)
        for name, options, remote_id in [
            ("cooperative", ["--tree"], None),
            ("ignore_cooperative", ["--tree", "--ignore-cancel"], "remote-unknown-fixture"),
            ("parent_normal_exit", ["--tree", "--ignore-cancel", "--exit-on-trigger"], None),
        ]:
            root = base / name
            root.mkdir()
            manager = ProcessManager(root / "leases.sqlite3")
            try:
                handle = manager.start(name, "a1", helpers.command(root, *options), root, remote_id=remote_id)
                workers = helpers.until(lambda: helpers.tree(root) if len(helpers.tree(root)) == 3 else None)
                if name == "parent_normal_exit":
                    (root / "exit-trigger.txt").write_text("exit normally", encoding="utf-8")
                started = time.monotonic()
                result = manager.wait(handle, timeout=8) if name == "parent_normal_exit" else manager.cancel(handle)
                helpers.until(lambda: all(not helpers.alive(worker["pid"]) for worker in workers))
                process_report["scenarios"].append({"name": name, "root_pid": handle.pid,
                    "workers": workers, "duration_seconds": time.monotonic() - started,
                    "result": asdict(result), "alive_after": [worker["pid"] for worker in workers if helpers.alive(worker["pid"])],
                    "temp_removed": not handle.temp_dir.exists(), "resources_after": manager.resource_snapshot(),
                    "lease": manager.leases.records()[0]})
            finally:
                manager.close()
        root = base / "service_exit"
        root.mkdir()
        environment = {key: value for key, value in os.environ.items() if key.upper() in ProcessManager.ENVIRONMENT_KEYS}
        environment["PYTHONPATH"] = str(REPOSITORY / "services/orchestrator")
        service = subprocess.Popen(helpers.command(root, "--mode", "service"), cwd=root, env=environment,
            shell=False, creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            workers = helpers.until(lambda: helpers.tree(root) if len(helpers.tree(root)) == 3 else None)
            service.kill()
            service.wait(timeout=5)
            helpers.until(lambda: all(not helpers.alive(worker["pid"]) for worker in workers))
            process_report["scenarios"].append({"name": "service_forced_exit", "service_pid": service.pid,
                "service_returncode": service.returncode, "workers": workers, "alive_after": [],
                "mechanism": "KILL_ON_JOB_CLOSE; Job handle never inherited",
                "temporary_directory_recovery": "owner crashed; retained lease identifies temp dir for D012 recovery"})
        finally:
            if service.poll() is None:
                service.kill()
                service.wait(timeout=5)
            service.stderr.close()
        root = base / "service_create_race"
        root.mkdir()
        helpers.test_owner_death_after_create_does_not_leave_suspended_orphan(root)
        created_pid = json.loads((root / "created-pid.json").read_text())["pid"]
        process_report["scenarios"].append({"name": "owner_death_after_CreateProcess_return",
            "created_pid": created_pid, "alive_after": [], "worker_entrypoint_executed": bool(helpers.tree(root)),
            "mechanism": "PROC_THREAD_ATTRIBUTE_JOB_LIST + CREATE_SUSPENDED + KILL_ON_JOB_CLOSE"})
        for name, limits, arguments in [
            ("output_flood", ResourceLimits(max_output_bytes=2048), ["--flood", "--ignore-cancel"]),
            ("active_process_limit", ResourceLimits(max_processes_per_job=3), ["--spawn-many", "8", "--ignore-cancel"]),
        ]:
            root = base / name
            root.mkdir()
            manager = ProcessManager(root / "leases.sqlite3", limits)
            try:
                handle = manager.start(name, "a1", helpers.command(root, *arguments), root)
                scenario = {"name": name, "limits": asdict(limits)}
                if name == "active_process_limit":
                    attempts = helpers.until(lambda: json.loads((root / "spawn-attempts.json").read_text()) if (root / "spawn-attempts.json").exists() else None)
                    helpers.until(lambda: len(helpers.tree(root)) == 3)
                    scenario.update(attempts=attempts, admitted_worker_count=len(helpers.tree(root)),
                                    resource_snapshot=manager.resource_snapshot())
                    assert sum(item["accepted"] for item in attempts) == 2
                    assert len(helpers.tree(root)) == limits.max_processes_per_job
                    result = manager.cancel(handle)
                else:
                    result = manager.wait(handle, timeout=8)
                    assert result.output_bytes_kept <= limits.max_output_bytes and result.output_truncated
                scenario.update(result=asdict(result), resources_after=manager.resource_snapshot(),
                                temp_removed=not handle.temp_dir.exists())
                resource_report["scenarios"].append(scenario)
            finally:
                manager.close()
        for index, limits in enumerate([ResourceLimits(max_running=1), ResourceLimits(max_temp_dirs=1), ResourceLimits(max_open_handles=9)]):
            root = base / f"budget-{index}"
            root.mkdir()
            second = root / "second"
            second.mkdir()
            manager = ProcessManager(root / "leases.sqlite3", limits)
            try:
                handle = manager.start("budget", "a1", helpers.command(root), root)
                helpers.until(lambda: helpers.tree(root))
                try:
                    manager.start("budget", "a2", helpers.command(second), second)
                    raise AssertionError("budget did not reject second start")
                except RuntimeError as exc:
                    rejection = str(exc)
                    assert "RESOURCE_LIMIT" in rejection
                before = manager.resource_snapshot()
                manager.cancel(handle)
                resource_report["scenarios"].append({"name": f"launch-budget-{index}",
                    "limits": asdict(limits), "rejection": rejection,
                    "before_cleanup": before, "resources_after": manager.resource_snapshot()})
            finally:
                manager.close()
    process_report["exit_code"] = resource_report["exit_code"] = 0
    for filename, value in [("process-tree.json", process_report), ("resource-report.json", resource_report)]:
        (OUTPUT / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"process_scenarios": len(process_report["scenarios"]),
        "resource_scenarios": len(resource_report["scenarios"]), "exit_code": 0}))


if __name__ == "__main__":
    run()
