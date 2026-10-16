"""Official Codex metadata connector; configuration never grants execution identity."""
from .native_rpc import NativeRpcClient, NativeRpcError
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", value):
        return None
    return None if value.lower().startswith(("sk-", "bearer", "eyj")) else value


def _executable_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CodexProtocolClient:
    scope_enforced = False
    supports_generation = False

    def __init__(self, command, cwd, *, client_factory=NativeRpcClient,
                 timeout_seconds=60, max_output_bytes=65536):
        if client_factory is NativeRpcClient and (not isinstance(command, list) or len(command) < 2 or
            command[1:] not in (["app-server"], ["app-server", "--stdio"], ["app-server", "--listen", "stdio://"])):
            raise NativeRpcError("CODEX_METADATA_COMMAND_REQUIRED")
        self.injected_transport = client_factory is not NativeRpcClient
        self.entry_verified = False
        if not self.injected_transport:
            try:
                root = Path(__file__).resolve().parents[4]
                entry = json.loads((root / "docs/acceptance/D006/supported-entry.json").read_text(encoding="utf-8"))
                expected = Path(entry["executable"]).resolve(strict=True)
                actual = Path(command[0]).resolve(strict=True)
                if actual != expected or entry.get("adapter") != "codex" or entry.get("source_kind") != "official_installed_runtime":
                    raise NativeRpcError("CODEX_OFFICIAL_ENTRY_MISMATCH")
                if _executable_sha256(actual) != entry.get("executable_sha256"):
                    raise NativeRpcError("CODEX_OFFICIAL_ENTRY_HASH_MISMATCH")
                self.entry_verified = True
            except NativeRpcError:
                raise
            except (OSError, ValueError, KeyError, TypeError):
                raise NativeRpcError("CODEX_OFFICIAL_ENTRY_MISMATCH") from None
        self.command, self.cwd, self.client_factory = command, Path(cwd).resolve(strict=True), client_factory
        self.timeout_seconds, self.max_output_bytes = timeout_seconds, max_output_bytes
        self._used = False

    def metadata(self):
        if self._used:
            raise NativeRpcError("RPC_ALREADY_STARTED")
        self._used = True
        client = self.client_factory(self.command, self.cwd, metadata_methods={"initialize", "initialized",
            "model/list", "account/read", "thread/start", "thread/read"}, protocol_envelope="plain",
            timeout_seconds=self.timeout_seconds, max_output_bytes=self.max_output_bytes)
        report = {"actual_model_id": None, "identity_status": "unknown", "scope_enforced": False,
            "production_enabled": False, "model_turn_starts": 0,
            "selection_source": "official thread/start configuration metadata; not per-turn execution telemetry",
            "entry_verified": self.entry_verified, "injected_transport": self.injected_transport}
        try:
            client.start()
            client.request("initialize", {"clientInfo": {"name": "workbench_metadata", "title": "Workbench metadata connector", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True}})
            client.notify("initialized", {})
            models = client.request("model/list", {"limit": 50, "includeHidden": False})
            report["model_catalog"] = [{"id": _name(m.get("id")), "model": _name(m.get("model")),
                "is_default": m.get("isDefault") is True} for m in models.get("data", []) if isinstance(m, dict)]
            account = client.request("account/read", {"refreshToken": False}).get("account")
            report["account"] = {"logged_in": isinstance(account, dict),
                "type": _name(account.get("type")) if isinstance(account, dict) else None}
            account = None
            started = client.request("thread/start", {"cwd": str(self.cwd), "ephemeral": True})
            thread = started.get("thread", {})
            if thread.get("ephemeral") is not True or not _name(thread.get("id")):
                raise NativeRpcError("RPC_METADATA_THREAD_BINDING_INVALID")
            read = client.request("thread/read", {"threadId": thread["id"], "includeTurns": False}).get("thread", {})
            if read.get("id") != thread["id"] or read.get("ephemeral") is not True:
                raise NativeRpcError("RPC_METADATA_THREAD_BINDING_INVALID")
            model = _name(started.get("model"))
            if read.get("model") not in (None, model) or thread.get("model") not in (None, model):
                raise NativeRpcError("RPC_CONFIGURED_MODEL_CHANGED")
            report.update(selected_model=model, model_provider=_name(started.get("modelProvider")),
                thread_id=thread["id"], ephemeral=True, model_access_verified=False)
        except Exception as error:
            # The partial record contains only this connector's field projections.
            error.metadata_report = report
            raise
        finally:
            report["cleanup"] = asdict(client.close())
            report["diagnostics"] = dict(client.diagnostics)
            report["model_turn_starts"] = client.diagnostics.get("model_turn_starts")
        return report
