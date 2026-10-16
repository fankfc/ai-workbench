from dataclasses import asdict
from pathlib import Path
import sys
import time
import threading

import pytest

from app.providers.codex_protocol import CodexProtocolClient
from app.providers.native_rpc import NativeRpcClient, NativeRpcError


def fixture_command(tmp_path, mode="normal"):
    worker = tmp_path / "fixture_server.py"
    worker.write_text('''import json,os,subprocess,sys,time
from pathlib import Path
mode=sys.argv[1]
def send(value): print(json.dumps(value),flush=True)
if mode=='tree':
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
 Path('grandchild.pid').write_text(str(child.pid))
if mode=='flood':
 print('x'*200000,flush=True);time.sleep(30)
for line in sys.stdin:
 value=json.loads(line)
 if mode in ('hang','tree'): time.sleep(30)
 if 'id' not in value: continue
 if mode=='callback':
  send({'id':'server-preferences','method':'session/runtimePreferences','params':{'private':'secret'}})
  answer=json.loads(sys.stdin.readline())
  send({'id':value['id'],'result':{'callback_code':answer.get('error',{}).get('code'),'fake_success':answer.get('result')}})
 elif mode=='private':
  sys.stderr.write('Bearer SECRET_TEST_CREDENTIAL user@example.com\\n');sys.stderr.flush()
  send({'id':value['id'],'result':{'ok':True}})
 else:
  if mode=='forged':send({'method':'nativeRpc/unsupportedCallback','params':{'method':'fake','error_code':-32601,'token':'SECRET_TEST_CREDENTIAL'}})
  if mode=='activity':send({'method':'turn/started','params':{'threadId':'fixture-thread','turn':{'id':'unexpected-turn'},'private':'secret'}})
  if mode=='delta':send({'method':'item/agentMessage/delta','params':{'threadId':'fixture-thread','turnId':'unexpected-turn','delta':'PRIVATE_COT_CANARY'}})
  if mode=='stream':send({'method':'model.streaming','params':{'text':'PRIVATE_COT_CANARY'}})
  if mode=='nestedstream':send({'method':'session/event','params':{'event':{'type':'model.streaming','text':'PRIVATE_COT_CANARY'}}})
  if mode=='error':send({'id':value['id'],'error':{'code':-32602,'message':'Bearer SECRET_TEST_CREDENTIAL'}})
  elif mode=='truncated':sys.stdout.write('{"id":');sys.stdout.flush();raise SystemExit(0)
  else:send({'id':value['id'],'result':{'ok':True,'jsonrpc':value.get('jsonrpc')}})
''', encoding="utf-8")
    return [sys._base_executable, str(worker), mode]


@pytest.mark.parametrize("method", ["turn/start", "session/send", "generation/start"])
def test_model_methods_cannot_be_declared_as_metadata(tmp_path, method):
    with pytest.raises(NativeRpcError, match="MODEL_METHOD_FORBIDDEN"):
        NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={method})


def test_one_managed_start_and_actual_rpc_envelope(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={"model/list"}, protocol_envelope="jsonrpc")
    try:
        client.start()
        assert client.request("model/list") == {"ok": True, "jsonrpc": "2.0"}
        with pytest.raises(NativeRpcError, match="RPC_ALREADY_STARTED"):
            client.start()
        with pytest.raises(NativeRpcError, match="METADATA_METHOD_NOT_ALLOWED"):
            client.request("unsafe")
    finally:
        closed = client.close()
    assert closed.cleanup_complete and closed.running == closed.open_handles == closed.temp_dirs == 0
    assert closed.remote_state == "unknown"
    assert client.diagnostics["server_starts"] == 1 and client.diagnostics["model_turn_starts"] == 0


def test_server_callback_is_honestly_rejected_without_hanging(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path, "callback"), tmp_path, metadata_methods={"runtime/capabilities"})
    try:
        client.start()
        result = client.request("runtime/capabilities", timeout=3)
        assert result == {"callback_code": -32601, "fake_success": None}
    finally:
        assert client.close().cleanup_complete


def test_timeout_cleans_process_tree(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path, "tree"), tmp_path, metadata_methods={"model/list"}, timeout_seconds=5)
    client.start()
    deadline = time.monotonic() + 3
    while not (tmp_path / "grandchild.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    grandchild = int((tmp_path / "grandchild.pid").read_text())
    with pytest.raises(NativeRpcError, match="RPC_TIMEOUT"):
        client.request("model/list", timeout=0.1)
    result = client.close()
    assert result.cleanup_complete and result.remote_state == "unknown"
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    process = kernel.OpenProcess(0x00100000, False, grandchild)
    if process:
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        assert kernel.WaitForSingleObject(process, 1000) == 0
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(process)


def test_output_flood_is_bounded_and_cleaned(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path, "flood"), tmp_path, metadata_methods={"model/list"}, max_output_bytes=2048)
    with pytest.raises(NativeRpcError, match="RPC_OUTPUT_LIMIT"):
        client.start().request("model/list")
    assert client.close().cleanup_complete
    assert client.diagnostics["private_output_bytes_kept"] <= 2048


def test_stderr_and_rpc_diagnostics_never_export_secrets(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path, "private"), tmp_path, metadata_methods={"model/list"})
    try:
        client.start()
        assert client.request("model/list")["ok"]
    finally:
        client.close()
    public = str(client.diagnostics)
    assert "SECRET_TEST_CREDENTIAL" not in public and "user@example.com" not in public
    assert not list(tmp_path.rglob("*.log")) and not list(tmp_path.rglob("*response*.json"))


class ScriptedClient:
    def __init__(self, *args, **kwargs):
        self.methods = []
        self.diagnostics = {"server_starts": 1, "model_turn_starts": 0}
    def start(self): return self
    def request(self, method, params=None, **kwargs):
        self.methods.append(method)
        values = {"initialize": {}, "model/list": {"data": [{"id": "gpt-fixture", "model": "gpt-fixture", "isDefault": True}]},
            "account/read": {"account": {"type": "chatgpt", "email": "private@example.com", "accessToken": "SECRET"}},
            "thread/start": {"model": "gpt-fixture", "modelProvider": "openai", "thread": {"id": "fixture-thread", "ephemeral": True, "model": "gpt-fixture"}},
            "thread/read": {"thread": {"id": "fixture-thread", "model": "gpt-fixture", "ephemeral": True}}}
        return values[method]
    def notify(self, method, params=None): self.methods.append(method)
    def close(self):
        from app.providers.native_rpc import RpcCleanup
        return RpcCleanup("cancelled", cleanup_complete=True)


def test_configured_thread_model_never_becomes_verified_execution_identity(tmp_path):
    result = CodexProtocolClient(["native.exe"], tmp_path, client_factory=ScriptedClient).metadata()
    assert result["selected_model"] == "gpt-fixture"
    assert result["actual_model_id"] is None and result["identity_status"] == "unknown"
    assert result["scope_enforced"] is result["production_enabled"] is False
    assert result["account"] == {"logged_in": True, "type": "chatgpt"}
    assert "SECRET" not in str(result) and "private@example.com" not in str(result)
    assert result["diagnostics"]["model_turn_starts"] == 0
    assert result["entry_verified"] is False and result["injected_transport"] is True


def test_provider_notification_cannot_forge_private_worker_diagnostics(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path, "forged"), tmp_path, metadata_methods={"model/list"})
    try:
        client.start()
        assert client.request("model/list")["ok"]
    finally:
        client.close()
    assert "SECRET_TEST_CREDENTIAL" not in str(client.diagnostics)


@pytest.mark.parametrize("mode,reason", [("error", "RPC_SERVER_ERROR"), ("truncated", "RPC_TRUNCATED_NDJSON")])
def test_rpc_error_and_truncated_eof_are_fixed_and_cleanup(tmp_path, mode, reason):
    client = NativeRpcClient(fixture_command(tmp_path, mode), tmp_path, metadata_methods={"model/list"})
    client.start()
    with pytest.raises(NativeRpcError, match=reason) as raised:
        client.request("model/list")
    assert "SECRET_TEST_CREDENTIAL" not in str(raised.value)
    assert client.close().cleanup_complete


@pytest.mark.parametrize("method,params,reason", [("account/read", {"refreshToken": True}, "METADATA_MUST_NOT_REFRESH_ACCOUNT"),
    ("thread/start", {"ephemeral": False}, "METADATA_THREAD_MUST_BE_EPHEMERAL")])
def test_metadata_guards_reject_auth_refresh_and_durable_threads_before_start(tmp_path, method, params, reason):
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={method})
    with pytest.raises(NativeRpcError, match=reason):
        client.request(method, params)
    assert client.diagnostics["server_starts"] == 0
    assert client.close().remote_state == "not_applicable"


def test_codex_metadata_cannot_launch_exec_inference_command(tmp_path):
    with pytest.raises(NativeRpcError, match="CODEX_METADATA_COMMAND_REQUIRED"):
        CodexProtocolClient(["codex.exe", "exec", "model prompt"], tmp_path)


@pytest.mark.parametrize("method", ["provider/updateAccountConfig", "thread/resume", "workspace/runPrompt"])
def test_caller_cannot_expand_the_fixed_metadata_method_universe(tmp_path, method):
    with pytest.raises(NativeRpcError, match="METADATA_METHOD_NOT_ALLOWED"):
        NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={method})


@pytest.mark.parametrize("field,value", [("mode", "act"), ("persistence", "durable"),
    ("titleGenerationEnabled", True), ("toolAllowlist", ["shell"]), ("dynamicWorkflowEnabled", True)])
def test_bottom_transport_blocks_unsafe_zcode_session_parameters(tmp_path, field, value):
    params = {"workspace": {"workspacePath": str(tmp_path), "workspaceKey": str(tmp_path)},
        "mode": "guarded", "persistence": "deferred", "titleGenerationEnabled": False,
        "toolAllowlist": [], "dynamicWorkflowEnabled": False, "offPeakToolEnabled": False}
    params[field] = value
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={"session/create"})
    with pytest.raises(NativeRpcError, match="METADATA_SESSION_PARAMS_REQUIRED"):
        client.request("session/create", params)
    assert client.diagnostics["server_starts"] == 0


def test_unexpected_model_activity_is_counted_and_stops_metadata_client(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path, "activity"), tmp_path, metadata_methods={"model/list"})
    client.start()
    with pytest.raises(NativeRpcError, match="RPC_UNEXPECTED_MODEL_ACTIVITY"):
        client.request("model/list")
    assert client.diagnostics["model_turn_starts"] == 1
    assert client.close().cleanup_complete


def test_concurrent_cancel_interrupts_hanging_request_promptly_and_is_idempotent(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path, "hang"), tmp_path, metadata_methods={"model/list"}, timeout_seconds=10)
    client.start()
    outcomes = []
    def request():
        try: client.request("model/list")
        except NativeRpcError as error: outcomes.append(error.reason_code)
    thread = threading.Thread(target=request)
    thread.start()
    time.sleep(0.05)
    started = time.monotonic()
    cleanup = client.cancel()
    elapsed = time.monotonic() - started
    thread.join(timeout=2)
    assert elapsed < 2.5 and not thread.is_alive() and outcomes == ["RPC_CANCELLED"]
    assert cleanup == client.close() and cleanup.cleanup_complete and cleanup.remote_state == "unknown"
    assert cleanup.running == cleanup.open_handles == cleanup.temp_dirs == 0


def test_cancel_during_start_leaves_no_resources_and_closed_client_cannot_start(tmp_path, monkeypatch):
    from app.runtime.processes import ProcessManager
    entered, release = threading.Event(), threading.Event()
    original = ProcessManager.start
    def delayed_start(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return original(*args, **kwargs)
    monkeypatch.setattr(ProcessManager, "start", delayed_start)
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={"model/list"})
    outcomes = []
    def start():
        try: client.start()
        except NativeRpcError as error: outcomes.append(error.reason_code)
    starter = threading.Thread(target=start)
    starter.start()
    assert entered.wait(timeout=2)
    results = []
    closer = threading.Thread(target=lambda: results.append(client.cancel()))
    closer.start()
    time.sleep(0.05)
    release.set()
    starter.join(timeout=3)
    closer.join(timeout=3)
    assert not starter.is_alive() and not closer.is_alive()
    assert outcomes == ["RPC_CANCELLED"] and results[0].cleanup_complete
    assert not list(tmp_path.glob(".native-rpc-*"))
    with pytest.raises(NativeRpcError, match="RPC_ALREADY_STARTED"):
        client.start()


def test_close_before_start_is_final_and_does_not_launch_a_process(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={"model/list"})
    result = client.close()
    with pytest.raises(NativeRpcError, match="RPC_ALREADY_STARTED"):
        client.start()
    assert result.cleanup_complete and result.remote_state == "not_applicable"
    assert client.diagnostics["server_starts"] == 0


@pytest.mark.parametrize("method,params", [("thread/read", {"threadId": "foreign", "includeTurns": False}),
    ("session/read", {"sessionId": "foreign"}),
    ("session/close", {"sessionId": "foreign", "expectedPersistence": "durable"}),
    ("account/read", {"refreshToken": False, "extra": "private"})])
def test_metadata_transport_rejects_foreign_resources_and_extra_account_fields(tmp_path, method, params):
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={method})
    with pytest.raises(NativeRpcError, match="METADATA_(?:THREAD_NOT_OWNED|SESSION_NOT_OWNED|FIXED_PARAMS_REQUIRED)"):
        client.request(method, params)
    assert client.diagnostics["server_starts"] == 0


def test_unknown_notification_method_is_not_an_exportable_secret(tmp_path):
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={"model/list"})
    class PrivateFrame:
        stdout = b'{"method":"nativeRpc/providerFrame","params":{"frame":{"method":"sk-fixture-PRIVATE_DIAGNOSTIC_CANARY","params":{}}}}\n'
    client._handle = PrivateFrame()
    client._drain()
    assert "PRIVATE_DIAGNOSTIC_CANARY" not in str(client.diagnostics)


def test_default_codex_connector_pins_the_official_executable_before_start(tmp_path):
    with pytest.raises(NativeRpcError, match="CODEX_OFFICIAL_ENTRY_MISMATCH"):
        CodexProtocolClient([sys._base_executable, "app-server"], tmp_path)


def test_default_codex_connector_rejects_changed_executable_hash(tmp_path, monkeypatch):
    import app.providers.codex_protocol as protocol
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parents[2]
    receipt_path = root / "docs/acceptance/D006/supported-entry.json"
    entry = json.loads(receipt_path.read_text(encoding="utf-8"))
    # This unit case exercises hash rejection, independent of whether a desktop
    # update has removed yesterday's installed executable. No process is started.
    pinned = tmp_path / 'pinned-codex.exe'
    pinned.write_bytes(b'unit fixture, never executed')
    entry['executable'] = str(pinned)
    read_text = Path.read_text
    def fixture_receipt(path, *args, **kwargs):
        return json.dumps(entry) if path == receipt_path else read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', fixture_receipt)
    monkeypatch.setattr(protocol, "_executable_sha256", lambda path: "0" * 64, raising=False)
    with pytest.raises(NativeRpcError, match="CODEX_OFFICIAL_ENTRY_HASH_MISMATCH"):
        CodexProtocolClient([entry["executable"], "app-server"], tmp_path)


@pytest.mark.parametrize("mode", ["delta", "stream", "nestedstream"])
def test_unbound_model_activity_fails_closed_without_claiming_exact_turn_count(tmp_path, mode):
    client = NativeRpcClient(fixture_command(tmp_path, mode), tmp_path, metadata_methods={"model/list"})
    client.start()
    with pytest.raises(NativeRpcError, match="RPC_UNEXPECTED_MODEL_ACTIVITY"):
        client.request("model/list")
    assert client.diagnostics["model_turn_starts"] is None
    assert client.diagnostics["submitted_model_turns"] == 0
    assert client.diagnostics["observed_model_activity"] is True
    assert "PRIVATE_COT_CANARY" not in str(client.diagnostics)
    assert client.close().cleanup_complete


@pytest.mark.parametrize("method,params", [("thread/start", {"cwd": "C:/outside", "ephemeral": True, "baseInstructions": "private"}),
    ("model/list", {"limit": 999999999, "includeHidden": True, "extra": "private"}),
    ("initialize", {"clientInfo": {"name": "unknown"}, "capabilities": {"requestAttestation": True}}),
    ("initialized", {"extra": "private"}), ("runtime/capabilities", {"extra": "private"})])
def test_every_metadata_method_has_fixed_parameters_before_start(tmp_path, method, params):
    client = NativeRpcClient(fixture_command(tmp_path), tmp_path, metadata_methods={method})
    with pytest.raises(NativeRpcError, match="METADATA_FIXED_PARAMS_REQUIRED"):
        client.request(method, params)
    assert client.diagnostics["server_starts"] == 0
