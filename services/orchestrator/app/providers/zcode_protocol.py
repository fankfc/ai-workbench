"""Public ZCode metadata over the common bounded native NDJSON transport.

This is not an inference adapter. Neither configured model references nor a
successful catalog query qualify identity, account authorization or OS scope.
The transport owns process bounds and honestly rejects client callbacks.
"""
from pathlib import Path
import hashlib
import math
import os
import re
import time

from .native_rpc import NativeRpcClient, NativeRpcError
from .gpt import redact_text


METADATA_METHODS = frozenset({"runtime/capabilities", "session/create", "session/read", "session/close"})
NODE_ENTRY = Path("C:/Program Files/nodejs/node.exe")
ZCODE_ENTRY = Path("D:/zcode/resources/glm/zcode.cjs")
ENTRY_HASHES = {
    "node": "3602f2bb1a10f2cbab4c36886218a33c1ab3db87290e73b033c46c77147d0237",
    "zcode": "b816e38656e70fb585fe2ab1ea010da89cda928dac1ccb5d83255fd18796da6e",
}


class ZCodeProtocolError(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
    # Never bind an RPC handle to a modified/redacted identifier.
    if redact_text(value) != value:
        raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
    return value


def _selection(value):
    if not isinstance(value, dict):
        raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
    result = {"provider_id": _identifier(value.get("providerId")), "model_id": _identifier(value.get("modelId"))}
    options = value.get("options")
    if options is not None:
        if not isinstance(options, dict):
            raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
        if "reasoningLevel" in options:
            result["reasoning_level"] = _identifier(options["reasoningLevel"])
    return result


def _catalog(value):
    if not isinstance(value, list) or len(value) > 512:
        raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
    output = []
    for model in value:
        if not isinstance(model, dict):
            raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
        selected = _selection(model.get("ref"))
        selected.pop("reasoning_level", None)
        reasoning = model.get("reasoning")
        if reasoning is not None:
            if not isinstance(reasoning, dict):
                raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
            levels = reasoning.get("levels", [])
            if not isinstance(levels, list) or len(levels) > 32:
                raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
            selected["reasoning_levels"] = [_identifier(item.get("value")) if isinstance(item, dict)
                else _identifier(None) for item in levels]
            default = reasoning.get("defaultLevel")
            if default is not None:
                selected["default_reasoning_level"] = _identifier(default)
        output.append(selected)
    return output


def _cleanup(value):
    names = ("local_state", "remote_state", "cleanup_complete", "forced", "output_limited",
             "running", "open_handles", "temp_dirs")
    output = {key: (value.get(key) if isinstance(value, dict) else getattr(value, key, None)) for key in names}
    if output["local_state"] not in {"exited", "cancelled", "failed", "resource_limit", "cleanup_failed", "unknown"}:
        output["local_state"] = "unknown"
    if output["remote_state"] not in {"not_applicable", "unknown", "stopped"}:
        output["remote_state"] = "unknown"
    if any(type(output[key]) is not bool for key in ("cleanup_complete", "forced", "output_limited")):
        raise ZCodeProtocolError("RPC_CLEANUP_INCOMPLETE")
    if any(type(output[key]) is not int or output[key] < 0 for key in ("running", "open_handles", "temp_dirs")):
        raise ZCodeProtocolError("RPC_CLEANUP_INCOMPLETE")
    return output


class ZCodeProtocolClient:
    """One metadata probe; supports no prompt, model selection or account writes."""
    scope_enforced = False
    supports_generation = False

    @staticmethod
    def fixed_command(cwd):
        return [str(NODE_ENTRY.resolve()), str(ZCODE_ENTRY.resolve()), "app-server",
                "--cwd", str(Path(cwd).resolve()), "--no-color"]

    @staticmethod
    def _verify_entry(command, cwd):
        expected = ZCodeProtocolClient.fixed_command(cwd)
        if len(command) != len(expected):
            raise ZCodeProtocolError("SUPPORTED_PROTOCOL_ENTRY_REQUIRED")
        for index, (actual, required) in enumerate(zip(command, expected)):
            if index in {0, 1, 4}:
                actual = os.path.normcase(str(Path(actual).resolve()))
                required = os.path.normcase(required)
            if actual != required:
                raise ZCodeProtocolError("SUPPORTED_PROTOCOL_ENTRY_REQUIRED")
        try:
            for key, path in (("node", NODE_ENTRY), ("zcode", ZCODE_ENTRY)):
                with path.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                if digest != ENTRY_HASHES[key]:
                    raise ZCodeProtocolError("SUPPORTED_PROTOCOL_ENTRY_CHANGED")
        except OSError:
            raise ZCodeProtocolError("SUPPORTED_PROTOCOL_ENTRY_UNAVAILABLE") from None

    def __init__(self, command, cwd, *, client_factory=None, timeout_seconds=40, max_output_bytes=65536):
        if (not isinstance(command, (list, tuple)) or not command
                or any(not isinstance(item, str) or not item or "\0" in item for item in command)):
            raise ZCodeProtocolError("NATIVE_ARGV_REQUIRED")
        forbidden = {"-p", "--prompt", "--target", "--target-replace", "--resume", "--continue", "-c"}
        if any(item.split("=", 1)[0] in forbidden for item in command[1:]):
            raise ZCodeProtocolError("METADATA_INVOCATION_REQUIRED")
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 60 or type(max_output_bytes) is not int
                or not 1024 <= max_output_bytes <= 2_000_000):
            raise ZCodeProtocolError("RPC_BOUNDS_REQUIRED")
        self.command = list(command)
        self.cwd = Path(cwd).resolve()
        self.entry_verified = client_factory is None
        if self.entry_verified:
            self._verify_entry(self.command, self.cwd)
        self.client_factory = NativeRpcClient if client_factory is None else client_factory
        self.timeout_seconds, self.max_output_bytes = timeout_seconds, max_output_bytes
        self._client = None
        self._session_id = None
        self._deadline = None
        self._used = False

    def _create_params(self):
        return {"workspace": {"workspacePath": str(self.cwd), "workspaceKey": str(self.cwd)},
                "mode": "guarded", "persistence": "deferred", "titleGenerationEnabled": False,
                "toolAllowlist": [], "dynamicWorkflowEnabled": False, "offPeakToolEnabled": False}

    def request(self, method, params=None):
        if method not in METADATA_METHODS:
            raise ZCodeProtocolError("METADATA_METHOD_FORBIDDEN")
        value = {} if params is None else params
        if method == "runtime/capabilities" and value != {}:
            raise ZCodeProtocolError("FIXED_METADATA_PARAMS_REQUIRED")
        if method == "session/create" and (self._session_id is not None or value != self._create_params()):
            raise ZCodeProtocolError("FIXED_METADATA_PARAMS_REQUIRED")
        if method in {"session/read", "session/close"}:
            if (not isinstance(value, dict) or self._session_id is None
                    or value.get("sessionId") != self._session_id):
                raise ZCodeProtocolError("OWNED_METADATA_SESSION_REQUIRED")
            allowed = {"sessionId"} if method == "session/read" else {"sessionId", "expectedPersistence"}
            if set(value) != allowed or method == "session/close" and value["expectedPersistence"] != "deferred":
                raise ZCodeProtocolError("FIXED_METADATA_PARAMS_REQUIRED")
        if self._client is None or self._deadline is None:
            raise ZCodeProtocolError("RPC_CLIENT_NOT_STARTED")
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise ZCodeProtocolError("RPC_TIMEOUT")
        return self._client.request(method, value, timeout=remaining)

    def probe(self):
        if self._used:
            raise ZCodeProtocolError("METADATA_PROBE_ALREADY_USED")
        self._used = True
        self._deadline = time.monotonic() + self.timeout_seconds
        report = {"metadata_status": "failed", "reason_code": "RPC_TRANSPORT_FAILED",
                  "identity_status": "unknown", "actual_model_id": None, "actual_model_family": "unknown",
                  "available_models": [], "current_model": None, "session_id": None, "state_revision": None,
                  "model_turn_starts": 0, "production_enabled": False, "scope_enforced": False,
                  "credential_headers_applied_by_client": False,
                  "entry_verified": self.entry_verified, "injected_transport": not self.entry_verified}
        try:
            self._client = self.client_factory(self.command, self.cwd, metadata_methods=METADATA_METHODS,
                protocol_envelope="plain", timeout_seconds=self.timeout_seconds, max_output_bytes=self.max_output_bytes)
            self._client.start()
            capabilities = self.request("runtime/capabilities", {})
            if not isinstance(capabilities, dict) or type(capabilities.get("independentPlanState")) is not bool:
                raise ZCodeProtocolError("CAPABILITIES_RESPONSE_INVALID")
            report["capabilities"] = {"independent_plan_state": capabilities["independentPlanState"]}
            value = self.request("session/create", self._create_params())
            if not isinstance(value, dict):
                raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
            session, runtime, settings = value.get("session"), value.get("runtime"), value.get("settings")
            if not isinstance(session, dict) or not isinstance(runtime, dict) or not isinstance(settings, dict):
                raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
            self._session_id = _identifier(session.get("sessionId"))
            report["session_id"] = self._session_id
            revision = runtime.get("stateRevision")
            model = settings.get("model")
            if type(revision) is not int or revision < 0 or not isinstance(model, dict):
                raise ZCodeProtocolError("METADATA_RESPONSE_INVALID")
            report["state_revision"] = revision
            available = _catalog(model.get("available"))
            current = None if model.get("current") is None else _selection(model["current"])
            report.update(available_models=available, current_model=current, metadata_status="observed",
                reason_code="MODEL_CATALOG_OBSERVED" if available else "HOST_ACCOUNT_CONTEXT_REQUIRED")
        except Exception as error:
            if isinstance(error, ZCodeProtocolError):
                report["reason_code"] = error.reason_code
            elif isinstance(error, NativeRpcError):
                reason = error.reason_code
                report["reason_code"] = reason if isinstance(reason, str) and re.fullmatch(r"[A-Z_]{1,64}", reason) else "RPC_TRANSPORT_FAILED"
                code = getattr(error, "error_code", None)
                if type(code) is int:
                    report["server_error_code"] = code
                    if code == -32022:
                        report["reason_code"] = "RUNTIME_PREFERENCES_CALLBACK_TIMEOUT"
            # Never copy exception text, stderr or original responses to reports.
        finally:
            if self._client is not None:
                if self._session_id is not None:
                    try:
                        closed = self.request("session/close", {"sessionId": self._session_id, "expectedPersistence": "deferred"})
                    except Exception:
                        report["session_close_confirmed"] = False
                    else:
                        report["session_close_confirmed"] = isinstance(closed, dict) and closed.get("closed") is True
                    if report["session_close_confirmed"] is False and report["metadata_status"] == "observed":
                        report.update(reason_code="OWNED_SESSION_CLOSE_UNCONFIRMED", metadata_status="failed")
                try:
                    cleaned = _cleanup(self._client.close())
                    report["cleanup"] = cleaned
                    if cleaned["output_limited"]:
                        report.update(reason_code="RPC_OUTPUT_LIMIT", metadata_status="failed")
                    elif (not cleaned["cleanup_complete"] or cleaned["local_state"] not in {"exited", "cancelled"}
                          or any(cleaned[key] != 0 for key in ("running", "open_handles", "temp_dirs"))):
                        report.update(reason_code="RPC_CLEANUP_INCOMPLETE", metadata_status="failed")
                except Exception:
                    report.update(reason_code="RPC_CLEANUP_INCOMPLETE", metadata_status="failed")
                diagnostics = getattr(self._client, "diagnostics", {})
                count = diagnostics.get("model_turn_starts") if isinstance(diagnostics, dict) else None
                report["model_turn_starts"] = count if type(count) is int and count >= 0 else None
                if report["model_turn_starts"] != 0:
                    report.update(reason_code="UNEXPECTED_MODEL_ACTIVITY", metadata_status="failed")
            self._client, self._session_id, self._deadline = None, None, None
        return report
