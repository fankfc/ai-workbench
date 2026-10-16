"""D011 fixture: native Python workers touch only their supplied temp workspace."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("worker", "service"), default="worker")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--tree", action="store_true")
    parser.add_argument("--ignore-cancel", action="store_true")
    parser.add_argument("--flood", action="store_true")
    parser.add_argument("--spawn-many", type=int, default=0)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--exit-parent", action="store_true")
    parser.add_argument("--crash-after-create", action="store_true")
    parser.add_argument("--remote-id")
    parser.add_argument("--exit-on-trigger", action="store_true")
    parser.add_argument("--literal", default="")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if Path.cwd().resolve() != root:
        raise RuntimeError("fixture must run in its supplied temp workspace")
    if args.mode == "service":
        from app.runtime.processes import ProcessManager
        manager = ProcessManager(root / "leases.sqlite3")
        if args.crash_after_create:
            original_create = manager._windows.api.CreateProcessW
            def crash_at_return(*parameters):
                created = original_create(*parameters)
                if created:
                    from app.runtime.processes import _ProcessInfo
                    info = ctypes.cast(parameters[-1], ctypes.POINTER(_ProcessInfo)).contents
                    (root / "created-pid.json").write_text(json.dumps({"pid": info.dwProcessId}), encoding="utf-8")
                    os._exit(73)
                return created
            manager._windows.api.CreateProcessW = crash_at_return
        handle = manager.start("parent-exit", "a1", [sys.executable, str(Path(__file__).resolve()),
            "--root", str(root), "--tree", "--ignore-cancel"], root, remote_id=args.remote_id)
        (root / "service.json").write_text(json.dumps({"pid": os.getpid(), "worker_pid": handle.pid}), encoding="utf-8")
        while True:
            time.sleep(0.05)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    event_name = os.environ.get("APP_RUNTIME_CANCEL_EVENT")
    event = kernel.OpenEventW(0x00100000, False, event_name) if event_name else None
    info = {"pid": os.getpid(), "parent_pid": os.getppid(), "level": args.level,
            "cwd": str(Path.cwd()), "literal": args.literal,
            "secret_inherited": "D011_SECRET_CANARY" in os.environ,
            "temp": os.environ.get("TEMP"), "event": bool(event)}
    (root / f"worker-{os.getpid()}.json").write_text(json.dumps(info), encoding="utf-8")
    print(json.dumps(info), flush=True)
    children = []
    if args.tree and args.level < 2:
        command = [sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                   "--tree", "--level", str(args.level + 1)]
        if args.ignore_cancel:
            command.append("--ignore-cancel")
        children.append(subprocess.Popen(command, shell=False, creationflags=subprocess.CREATE_NO_WINDOW))
    if args.spawn_many:
        attempts = []
        for index in range(args.spawn_many):
            try:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                    "--ignore-cancel", "--level", str(index + 10)], shell=False,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                children.append(child)
                attempts.append({"pid": child.pid, "accepted": True})
            except OSError as exc:
                attempts.append({"accepted": False, "winerror": exc.winerror})
        (root / "spawn-attempts.json").write_text(json.dumps(attempts), encoding="utf-8")
    if args.exit_code is not None:
        return args.exit_code
    if args.exit_parent:
        time.sleep(0.3)
        return 0
    try:
        while True:
            if args.exit_on_trigger and (root / "exit-trigger.txt").exists():
                return 0
            if not args.ignore_cancel and event and kernel.WaitForSingleObject(event, 0) == 0:
                (root / f"cooperative-{os.getpid()}.json").write_text("true", encoding="utf-8")
                return 0
            if args.flood:
                os.write(sys.stdout.fileno(), b"x" * 8192)
                os.write(sys.stderr.fileno(), b"y" * 8192)
            (root / f"heartbeat-{os.getpid()}.txt").write_text(str(time.monotonic()), encoding="utf-8")
            time.sleep(0.01 if args.flood else 0.03)
    finally:
        if event:
            kernel.CloseHandle(event)


if __name__ == "__main__":
    raise SystemExit(main())
