"""Managed metadata-only RPC; private frames are bounded in memory, never logs."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from uuid import uuid4
from app.runtime.processes import ProcessManager
from app.runtime.resources import ResourceLimits

METADATA_METHODS = frozenset({"initialize", "initialized", "model/list", "account/read", "thread/start", "thread/read",
    "runtime/capabilities", "session/create", "session/read", "session/close"})
NOTIFICATION_METHODS = frozenset({"account/updated", "mcpServer/startupStatus/updated", "remoteControl/status/changed",
    "thread/started", "thread/closed", "thread/status/changed", "session/updated", "session/runtimeUpdated"})
CALLBACK_METHODS = frozenset({"session/runtimePreferences", "session/createRuntimePreferences", "session/httpHeaders",
    "session/requestPermission", "session/openBrowser", "account/chatgptAuthTokens/refresh",
    "item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/tool/requestUserInput"})


def fixed_params(method, cwd):
    return {"initialize": {"clientInfo": {"name": "workbench_metadata", "title": "Workbench metadata connector", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True}}, "initialized": {},
        "model/list": {"limit": 50, "includeHidden": False}, "account/read": {"refreshToken": False},
        "thread/start": {"cwd": str(cwd), "ephemeral": True}, "runtime/capabilities": {}}.get(method)


def exact_params(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(exact_params(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(exact_params(a, e) for a, e in zip(actual, expected))
    return actual == expected


def forbidden_method(method):
    value = method.lower().replace("_", "/").replace(".", "/")
    return (value.startswith("turn/") or "generat" in value or "completion" in value
        or value in {"session/send", "review/start", "responses/create", "chat/send", "chat/create",
            "account/login/start", "account/logout", "config/write", "config/batchwrite"})


class NativeRpcError(RuntimeError):
    def __init__(self, reason_code, *, error_code=None):
        self.reason_code, self.error_code = reason_code, error_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class RpcCleanup:
    local_state: str
    remote_state: str = "unknown"
    cleanup_complete: bool = False
    forced: bool = False
    output_limited: bool = False
    running: int = 0
    open_handles: int = 0
    temp_dirs: int = 0


class NativeRpcClient:
    def __init__(self, command, cwd, *, metadata_methods, protocol_envelope="plain",
                 timeout_seconds=60, max_output_bytes=65536):
        if not isinstance(command, list) or not command or any(not isinstance(v, str) or not v or "\x00" in v for v in command):
            raise NativeRpcError("RPC_COMMAND_INVALID")
        self.command, self.cwd = list(command), Path(cwd).resolve(strict=True)
        if not self.cwd.is_dir() or Path(command[0]).suffix.lower() != ".exe":
            raise NativeRpcError("RPC_NATIVE_EXECUTABLE_REQUIRED")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
            raise NativeRpcError("RPC_TIME_LIMIT_INVALID")
        if type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 2_000_000:
            raise NativeRpcError("RPC_OUTPUT_LIMIT_INVALID")
        if protocol_envelope not in {"plain", "jsonrpc"}:
            raise NativeRpcError("RPC_ENVELOPE_INVALID")
        self.metadata_methods = frozenset(metadata_methods)
        if not self.metadata_methods or any(not isinstance(m, str) or not m.strip() for m in self.metadata_methods):
            raise NativeRpcError("RPC_METADATA_ALLOWLIST_REQUIRED")
        if any(forbidden_method(m) for m in self.metadata_methods):
            raise NativeRpcError("MODEL_METHOD_FORBIDDEN")
        if not self.metadata_methods <= METADATA_METHODS:
            raise NativeRpcError("METADATA_METHOD_NOT_ALLOWED")
        self.protocol_envelope = protocol_envelope
        self.timeout_seconds, self.max_output_bytes = timeout_seconds, max_output_bytes
        self.diagnostics = {"server_starts": 0, "model_turn_starts": 0, "submitted_model_turns": 0,
            "observed_model_activity": False, "private_output_bytes_kept": 0,
            "private_stderr": "[omitted: private provider stderr]", "unsupported_callbacks": [], "notification_methods": []}
        self._manager = self._handle = self._directory = self._cleanup = None
        self._started = self._closed = self._ready = self._limited = False
        self._offset, self._pending, self._counter, self._packet_counter = 0, b"", 0, 0
        self._replies = {}
        self._lock = threading.RLock()
        self._closing = threading.Event()
        self._owned_threads, self._owned_sessions = set(), set()
        self._observed_turn_starts = set()

    def start(self):
        with self._lock:
            if self._started or self._closed or self._closing.is_set():
                raise NativeRpcError("RPC_ALREADY_STARTED")
            self._started = True
            active_seconds = self.timeout_seconds - min(5, self.timeout_seconds * 0.2)
            self._deadline = time.monotonic() + active_seconds
            self._directory = Path(tempfile.mkdtemp(prefix=".native-rpc-", dir=self.cwd))
            (self._directory / "inbox").mkdir()
            config = {"command": self.command, "cwd": str(self.cwd), "inbox": str(self._directory / "inbox"),
                "metadata_methods": sorted(self.metadata_methods), "envelope": self.protocol_envelope,
                "timeout_seconds": active_seconds, "max_output_bytes": self.max_output_bytes}
            # Only the packaged ZCode catalog reference is authorized for this
            # metadata lane. Credential environment variables stay excluded.
            builtin = os.environ.get("ZCODE_BUILTIN_PROVIDER_CONFIG_FILE")
            if builtin:
                candidate = Path(builtin)
                if not candidate.is_absolute() or candidate.name != "zcode-builtin.json" or not candidate.is_file():
                    self.close()
                    raise NativeRpcError("RPC_BUILTIN_CONFIG_REFERENCE_INVALID")
                config["environment"] = {"ZCODE_BUILTIN_PROVIDER_CONFIG_FILE": str(candidate)}
            path = self._directory / "worker-config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            self._manager = ProcessManager(self._directory / "leases.sqlite3", ResourceLimits(
                max_running=1, max_output_bytes=self.max_output_bytes, cancel_grace_seconds=0.1, kill_wait_seconds=4))
            try:
                self._handle = self._manager.start("native-metadata", uuid4().hex,
                    [sys._base_executable, str(Path(__file__).with_name("native_rpc_worker.py")), str(path)], self._directory)
                while not self._ready:
                    self._drain()
                    self._check_lifetime()
                    time.sleep(0.005)
                self.diagnostics["server_starts"] = 1
                return self
            except Exception:
                self.close()
                raise

    def _validate_method(self, method, params):
        if not isinstance(method, str) or forbidden_method(method):
            raise NativeRpcError("MODEL_METHOD_FORBIDDEN")
        if method not in self.metadata_methods:
            raise NativeRpcError("METADATA_METHOD_NOT_ALLOWED")
        if not isinstance(params, dict):
            raise NativeRpcError("RPC_PARAMS_INVALID")
        if method == "thread/start" and params.get("ephemeral") is not True:
            raise NativeRpcError("METADATA_THREAD_MUST_BE_EPHEMERAL")
        if method == "account/read" and params.get("refreshToken") is not False:
            raise NativeRpcError("METADATA_MUST_NOT_REFRESH_ACCOUNT")
        if method == "account/read" and set(params) != {"refreshToken"}:
            raise NativeRpcError("METADATA_FIXED_PARAMS_REQUIRED")
        expected_fixed = fixed_params(method, self.cwd)
        if expected_fixed is not None and not exact_params(params, expected_fixed):
            raise NativeRpcError("METADATA_FIXED_PARAMS_REQUIRED")
        if method == "thread/read" and params.get("includeTurns") is not False:
            raise NativeRpcError("METADATA_HISTORY_MUST_BE_EXCLUDED")
        if method == "thread/read" and params.get("threadId") not in self._owned_threads:
            raise NativeRpcError("METADATA_THREAD_NOT_OWNED")
        if method == "thread/read" and set(params) != {"threadId", "includeTurns"}:
            raise NativeRpcError("METADATA_FIXED_PARAMS_REQUIRED")
        if method in {"session/read", "session/close"}:
            if params.get("sessionId") not in self._owned_sessions:
                raise NativeRpcError("METADATA_SESSION_NOT_OWNED")
            expected = {"sessionId"} if method == "session/read" else {"sessionId", "expectedPersistence"}
            if set(params) != expected or method == "session/close" and params.get("expectedPersistence") != "deferred":
                raise NativeRpcError("METADATA_FIXED_PARAMS_REQUIRED")
        if method == "session/create":
            expected = {"workspace": {"workspacePath": str(self.cwd), "workspaceKey": str(self.cwd)},
                "mode": "guarded", "persistence": "deferred", "titleGenerationEnabled": False,
                "toolAllowlist": [], "dynamicWorkflowEnabled": False, "offPeakToolEnabled": False}
            if (not exact_params(params, expected) or any(params.get(key) is not False for key in
                    ("titleGenerationEnabled", "dynamicWorkflowEnabled", "offPeakToolEnabled"))):
                raise NativeRpcError("METADATA_SESSION_PARAMS_REQUIRED")

    def _send(self, method, params, request_id=None):
        self._validate_method(method, params)
        if not self._started or self._closed:
            raise NativeRpcError("RPC_NOT_RUNNING")
        if self._closing.is_set():
            raise NativeRpcError("RPC_CANCELLED")
        if request_id is None and method != "initialized":
            raise NativeRpcError("METADATA_NOTIFICATION_NOT_ALLOWED")
        message = {"method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        self._packet_counter += 1
        path = self._directory / "inbox" / f"{self._packet_counter:08}.json"
        data = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(data) > self.max_output_bytes:
            raise NativeRpcError("RPC_REQUEST_LIMIT")
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def _drain(self):
        if self._closing.is_set():
            raise NativeRpcError("RPC_CANCELLED")
        current = self._handle.stdout
        self.diagnostics["private_output_bytes_kept"] = len(current)
        self._pending += current[self._offset:]
        self._offset = len(current)
        while b"\n" in self._pending:
            line, self._pending = self._pending.split(b"\n", 1)
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                raise NativeRpcError("RPC_INVALID_NDJSON") from None
            if not isinstance(value, dict):
                raise NativeRpcError("RPC_INVALID_ENVELOPE")
            method = value.get("method")
            internal = method != "nativeRpc/providerFrame"
            if not internal:
                value = value.get("params", {}).get("frame")
                if not isinstance(value, dict):
                    raise NativeRpcError("RPC_INVALID_ENVELOPE")
                method = value.get("method")
                normalized = method.lower().replace(".", "/") if isinstance(method, str) else ""
                payload = value.get("params", {})
                nested = payload.get("event", {}) if isinstance(payload, dict) else {}
                event_type = nested.get("type", "").lower().replace(".", "/") if isinstance(nested, dict) and isinstance(nested.get("type"), str) else ""
                active = (normalized.startswith(("turn/", "item/agentmessage/", "item/reasoning/", "model/stream"))
                    or normalized in {"model/rerouted", "session/modelcallstarted"} or "generat" in normalized
                    or event_type.startswith(("model/", "turn/", "generation/", "agentmessage/")))
                if active:
                    self.diagnostics["observed_model_activity"] = True
                    if normalized == "turn/started" and isinstance(payload, dict):
                        thread = payload.get("threadId")
                        turn = payload.get("turn", {}).get("id") if isinstance(payload.get("turn"), dict) else None
                        if isinstance(thread, str) and thread and isinstance(turn, str) and turn:
                            self._observed_turn_starts.add((thread, turn))
                            self.diagnostics["model_turn_starts"] = len(self._observed_turn_starts)
                        else:
                            self.diagnostics["model_turn_starts"] = None
                    else:
                        self.diagnostics["model_turn_starts"] = None
                    self.diagnostics["unexpected_model_activity"] = True
                    raise NativeRpcError("RPC_UNEXPECTED_MODEL_ACTIVITY")
            if internal and method == "nativeRpc/started":
                self._ready = True
                self.diagnostics["server_pid"] = value["params"]["pid"]
            elif internal and method == "nativeRpc/outputLimit":
                self._limited = True
                raise NativeRpcError("RPC_OUTPUT_LIMIT")
            elif internal and method == "nativeRpc/truncated":
                raise NativeRpcError("RPC_TRUNCATED_NDJSON")
            elif internal and method == "nativeRpc/workerError":
                raise NativeRpcError("RPC_WORKER_FAILED")
            elif internal and method == "nativeRpc/unsupportedCallback":
                name = value.get("params", {}).get("method")
                self.diagnostics["unsupported_callbacks"].append({"method": name if name in CALLBACK_METHODS else "unclassified",
                    "error_code": -32601})
            elif internal and method == "nativeRpc/stderrSummary":
                self.diagnostics["stderr_bytes"] = value["params"]["bytes"]
            elif method:
                self.diagnostics["notification_methods"].append(method if method in NOTIFICATION_METHODS else "unclassified")
            elif "id" in value:
                self._replies[value["id"]] = value

    def _check_lifetime(self, deadline=None):
        if self._closing.is_set():
            raise NativeRpcError("RPC_CANCELLED")
        if time.monotonic() >= min(self._deadline, deadline or self._deadline):
            raise NativeRpcError("RPC_TIMEOUT")
        result = self._manager.poll(self._handle)
        if result is not None:
            if result.output_truncated or self._limited:
                raise NativeRpcError("RPC_OUTPUT_LIMIT")
            if self._pending:
                raise NativeRpcError("RPC_TRUNCATED_NDJSON")
            raise NativeRpcError("RPC_PROCESS_EXITED")

    def request(self, method, params=None, *, timeout=None):
        with self._lock:
            params = (fixed_params(method, self.cwd) or {}) if params is None else params
            self._validate_method(method, params)
            if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
                raise NativeRpcError("RPC_TIMEOUT_INVALID")
            self._counter += 1
            deadline = min(self._deadline, time.monotonic() + (timeout or self.timeout_seconds)) if self._started else 0
            try:
                self._send(method, params, self._counter)
                while True:
                    self._drain()
                    if self._counter in self._replies:
                        reply = self._replies.pop(self._counter)
                        if "error" in reply:
                            raise NativeRpcError("RPC_SERVER_ERROR", error_code=reply["error"].get("code"))
                        result = reply.get("result")
                        if isinstance(result, dict):
                            if method == "thread/start":
                                thread = result.get("thread", {})
                                if isinstance(thread, dict) and thread.get("ephemeral") is True and isinstance(thread.get("id"), str):
                                    self._owned_threads.add(thread["id"])
                            elif method == "session/create":
                                session = result.get("session", {})
                                if isinstance(session, dict) and isinstance(session.get("sessionId"), str):
                                    self._owned_sessions.add(session["sessionId"])
                            elif method == "session/close" and result.get("closed") is True:
                                self._owned_sessions.discard(params["sessionId"])
                        return result
                    self._check_lifetime(deadline)
                    time.sleep(0.005)
            except NativeRpcError:
                self.close()
                raise

    def notify(self, method, params=None):
        with self._lock:
            self._send(method, {} if params is None else params)

    def close(self):
        # Publish the local stop signal before waiting for the request lock.
        self._closing.set()
        if self._directory is not None:
            try:
                (self._directory / "close-requested").write_bytes(b"close")
            except OSError:
                pass
        with self._lock:
            if self._cleanup is not None:
                return self._cleanup
            self._closed = True
            result = None
            if self._handle is not None:
                try:
                    (self._directory / "close-requested").write_bytes(b"close")
                    result = self._manager.wait(self._handle, timeout=0.3)
                except TimeoutError:
                    result = self._manager.cancel(self._handle)
                except (OSError, RuntimeError):
                    pass
            cleanup_error = False
            if self._manager is not None:
                try:
                    self._manager.close()
                except RuntimeError:
                    cleanup_error = True
            snapshot = self._manager.resource_snapshot() if self._manager else {"running": 0, "open_handles": 0, "temp_dirs": 0}
            if self._directory is not None:
                try:
                    resolved = self._directory.resolve(strict=False)
                    if not resolved.is_relative_to(self.cwd) or not resolved.name.startswith(".native-rpc-") or self._directory.is_symlink() or self._directory.is_junction():
                        raise OSError("UNSAFE_RPC_CLEANUP_PATH")
                    shutil.rmtree(self._directory)
                except OSError:
                    cleanup_error = True
            self.diagnostics["private_output_bytes_kept"] = len(self._handle.stdout) if self._handle else 0
            self._cleanup = RpcCleanup(result.local_state if result else "not_started" if self._handle is None else "cleanup_failed",
                "unknown" if self._handle is not None else "not_applicable",
                not cleanup_error and not any(snapshot[k] for k in ("running", "open_handles", "temp_dirs")),
                bool(result and result.forced), self._limited or bool(result and result.output_truncated),
                snapshot["running"], snapshot["open_handles"], snapshot["temp_dirs"])
            self._replies.clear()
            self._pending = b""
            return self._cleanup

    cancel = close
