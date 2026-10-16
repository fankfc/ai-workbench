"""Private Job-inherited broker. No model method or raw stderr/response files."""
from contextlib import suppress
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

METADATA_METHODS = frozenset({"initialize", "initialized", "model/list", "account/read", "thread/start", "thread/read",
    "runtime/capabilities", "session/create", "session/read", "session/close"})
CALLBACK_METHODS = frozenset({"session/runtimePreferences", "session/createRuntimePreferences", "session/httpHeaders",
    "session/requestPermission", "session/openBrowser", "account/chatgptAuthTokens/refresh",
    "item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/tool/requestUserInput"})


def exact_params(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(exact_params(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(exact_params(a, e) for a, e in zip(actual, expected))
    return actual == expected


def run():
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    inbox, max_bytes = Path(config["inbox"]), config["max_output_bytes"]
    outgoing, lock = queue.Queue(), threading.Lock()
    counts, exceeded = {"stdout": 0, "stderr": 0}, threading.Event()
    stdout_done = threading.Event()
    methods, owned_threads, owned_sessions = {}, set(), set()
    process = None
    def emit(value):
        print(json.dumps(value, ensure_ascii=True, separators=(",", ":")), flush=True)
    def read(stream, kind):
        pending = b""
        while True:
            data = stream.read1(4096)
            if not data:
                if kind == "stdout" and pending:
                    outgoing.put(("truncated", None))
                if kind == "stdout":
                    stdout_done.set()
                return
            with lock:
                counts[kind] += len(data)
                if sum(counts.values()) > max_bytes:
                    exceeded.set()
                    return
            if kind == "stderr":
                continue
            pending += data
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if line.strip():
                    outgoing.put(("frame", line))
    def send(message):
        if config["envelope"] == "jsonrpc":
            message = {"jsonrpc": "2.0", **message}
        process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        process.stdin.flush()
    try:
        environment = dict(os.environ)
        permitted = config.get("environment", {})
        if set(permitted) - {"ZCODE_BUILTIN_PROVIDER_CONFIG_FILE"}:
            raise ValueError("METADATA_ENVIRONMENT_REQUIRED")
        environment.update(permitted)
        process = subprocess.Popen(config["command"], cwd=config["cwd"], env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        emit({"method": "nativeRpc/started", "params": {"pid": process.pid}})
        for kind in ("stdout", "stderr"):
            threading.Thread(target=read, args=(getattr(process, kind), kind), daemon=True).start()
        deadline = time.monotonic() + config["timeout_seconds"]
        while time.monotonic() < deadline:
            if exceeded.is_set():
                emit({"method": "nativeRpc/outputLimit", "params": {}})
                return
            if (inbox.parent / "close-requested").exists():
                return
            for path in sorted(inbox.glob("*.json")):
                message = json.loads(path.read_text(encoding="utf-8"))
                path.unlink()
                method = message.get("method", "")
                lowered = method.lower().replace("_", "/").replace(".", "/")
                if method not in config["metadata_methods"] or method not in METADATA_METHODS or lowered.startswith("turn/") or "generat" in lowered or "completion" in lowered or lowered == "session/send":
                    raise ValueError("METADATA_METHOD_REQUIRED")
                params = message.get("params", {})
                fixed = {"initialize": {"clientInfo": {"name": "workbench_metadata", "title": "Workbench metadata connector", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True}}, "initialized": {},
                    "model/list": {"limit": 50, "includeHidden": False}, "account/read": {"refreshToken": False},
                    "thread/start": {"cwd": config["cwd"], "ephemeral": True}, "runtime/capabilities": {}}.get(method)
                if fixed is not None and not exact_params(params, fixed):
                    raise ValueError("METADATA_FIXED_PARAMS_REQUIRED")
                if method == "session/create":
                    expected = {"workspace": {"workspacePath": config["cwd"], "workspaceKey": config["cwd"]},
                        "mode": "guarded", "persistence": "deferred", "titleGenerationEnabled": False,
                        "toolAllowlist": [], "dynamicWorkflowEnabled": False, "offPeakToolEnabled": False}
                    if not exact_params(params, expected) or any(params.get(key) is not False for key in
                            ("titleGenerationEnabled", "dynamicWorkflowEnabled", "offPeakToolEnabled")):
                        raise ValueError("METADATA_SESSION_PARAMS_REQUIRED")
                if method == "thread/start" and params.get("ephemeral") is not True:
                    raise ValueError("METADATA_THREAD_MUST_BE_EPHEMERAL")
                if method == "account/read" and params.get("refreshToken") is not False:
                    raise ValueError("METADATA_MUST_NOT_REFRESH_ACCOUNT")
                if method == "account/read" and set(params) != {"refreshToken"}:
                    raise ValueError("METADATA_FIXED_PARAMS_REQUIRED")
                if method == "thread/read" and params.get("includeTurns") is not False:
                    raise ValueError("METADATA_HISTORY_MUST_BE_EXCLUDED")
                if method == "thread/read" and (params.get("threadId") not in owned_threads or set(params) != {"threadId", "includeTurns"}):
                    raise ValueError("METADATA_THREAD_NOT_OWNED")
                if method in {"session/read", "session/close"}:
                    keys = {"sessionId"} if method == "session/read" else {"sessionId", "expectedPersistence"}
                    if params.get("sessionId") not in owned_sessions or set(params) != keys or method == "session/close" and params.get("expectedPersistence") != "deferred":
                        raise ValueError("METADATA_SESSION_NOT_OWNED")
                if "id" not in message and method != "initialized":
                    raise ValueError("METADATA_NOTIFICATION_NOT_ALLOWED")
                if "id" in message:
                    methods[message["id"]] = (method, params)
                send(message)
            while not outgoing.empty():
                kind, line = outgoing.get_nowait()
                if kind == "truncated":
                    emit({"method": "nativeRpc/truncated", "params": {}})
                    return
                value = json.loads(line)
                if isinstance(value, dict) and "method" in value and "id" in value:
                    send({"id": value["id"], "error": {"code": -32601, "message": "Unsupported client request in metadata connector"}})
                    method = value.get("method", "")
                    safe = method if isinstance(method, str) and method in CALLBACK_METHODS else "unclassified"
                    emit({"method": "nativeRpc/unsupportedCallback", "params": {"method": safe, "error_code": -32601}})
                else:
                    request_method, request_params = methods.pop(value.get("id"), (None, {})) if isinstance(value, dict) and "id" in value else (None, {})
                    result = value.get("result") if isinstance(value, dict) else None
                    if isinstance(result, dict):
                        if request_method == "thread/start":
                            thread = result.get("thread", {})
                            if isinstance(thread, dict) and thread.get("ephemeral") is True and isinstance(thread.get("id"), str):
                                owned_threads.add(thread["id"])
                        elif request_method == "session/create":
                            session = result.get("session", {})
                            if isinstance(session, dict) and isinstance(session.get("sessionId"), str):
                                owned_sessions.add(session["sessionId"])
                        elif request_method == "session/close" and result.get("closed") is True:
                            owned_sessions.discard(request_params["sessionId"])
                    emit({"method": "nativeRpc/providerFrame", "params": {"frame": value}})
            if process.poll() is not None and stdout_done.is_set() and outgoing.empty():
                return
            time.sleep(0.005)
    except Exception:
        emit({"method": "nativeRpc/workerError", "params": {}})
    finally:
        emit({"method": "nativeRpc/stderrSummary", "params": {"bytes": counts["stderr"]}})
        if process is not None:
            with suppress(Exception):
                process.stdin.close()
                process.wait(timeout=0.1)
            if process.poll() is None:
                process.terminate()
                with suppress(Exception):
                    process.wait(timeout=0.1)
        # Root exit closes the owning Job and reclaims every descendant.


if __name__ == "__main__":
    run()
