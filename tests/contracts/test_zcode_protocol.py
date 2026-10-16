"""ZCode metadata policy fixtures; no installed provider or account operations."""
from copy import deepcopy
from types import SimpleNamespace
import json
import sys
import pytest
from app.providers.zcode_protocol import ZCodeProtocolClient, ZCodeProtocolError
from app.providers.native_rpc import NativeRpcClient, NativeRpcError


def snapshot(models=None, current=None):
    value = {"session": {"sessionId": "sess-metadata"}, "runtime": {"stateRevision": 0},
             "settings": {"model": {"available": [] if models is None else models}}}
    if current is not None:
        value["settings"]["model"]["current"] = current
    return value


def cleanup(**changes):
    return SimpleNamespace(**({"local_state": "exited", "remote_state": "not_applicable",
        "cleanup_complete": True, "forced": False, "output_limited": False,
        "running": 0, "open_handles": 0, "temp_dirs": 0} | changes))


class FixtureClient:
    def __init__(self, responses=None, *, clean=None, failure=None):
        self.responses = responses or {"runtime/capabilities": {"independentPlanState": True},
                                      "session/create": snapshot(), "session/close": {"closed": True}}
        self.cleaned = cleanup() if clean is None else clean
        self.failure = failure
        self.calls = []
        self.started = self.closed = 0
        self.diagnostics = {"server_starts": 0, "model_turn_starts": 0,
                            "raw_payload": "credential must remain private"}

    def start(self):
        self.started += 1
        self.diagnostics["server_starts"] += 1
        return self

    def request(self, method, params=None, *, timeout=None):
        self.calls.append((method, deepcopy(params)))
        if self.failure and method == "session/create":
            raise self.failure
        return deepcopy(self.responses[method])

    def close(self):
        self.closed += 1
        return self.cleaned


def make_probe(tmp_path, **options):
    fixture = FixtureClient(**options)
    observed = {}
    def factory(command, cwd, **kwargs):
        observed.update(command=command, cwd=cwd, **kwargs)
        return fixture
    probe = ZCodeProtocolClient(["fixture-native.exe", "metadata-server"], tmp_path,
        client_factory=factory, timeout_seconds=5, max_output_bytes=32000)
    return probe, fixture, observed


def test_fixed_metadata_request_has_no_model_prompt_or_authorization(tmp_path):
    probe, fixture, observed = make_probe(tmp_path)
    result = probe.probe()
    assert [method for method, _ in fixture.calls] == ["runtime/capabilities", "session/create", "session/close"]
    assert fixture.calls[1][1] == {
        "workspace": {"workspacePath": str(tmp_path.resolve()), "workspaceKey": str(tmp_path.resolve())},
        "mode": "guarded", "persistence": "deferred", "titleGenerationEnabled": False,
        "toolAllowlist": [], "dynamicWorkflowEnabled": False, "offPeakToolEnabled": False}
    assert observed["protocol_envelope"] == "plain"
    assert set(observed["metadata_methods"]) == {"runtime/capabilities", "session/create", "session/read", "session/close"}
    assert fixture.started == fixture.closed == 1
    assert result["model_turn_starts"] == 0 and result["production_enabled"] is False


def test_empty_catalog_is_host_context_required_with_unknown_identity(tmp_path):
    result = make_probe(tmp_path)[0].probe()
    assert result["reason_code"] == "HOST_ACCOUNT_CONTEXT_REQUIRED"
    assert result["metadata_status"] == "observed"
    assert result["identity_status"] == "unknown" and result["actual_model_id"] is None
    assert result["available_models"] == [] and result["current_model"] is None
    assert result["scope_enforced"] is False


def test_catalog_is_only_configuration_and_nested_secrets_are_not_projected(tmp_path):
    selection = {"providerId": "account:bigmodel-start-plan", "modelId": "GLM-5.3",
                 "options": {"reasoningLevel": "low", "credential": "never-store-this"}}
    model = {"ref": selection, "apiKey": "never-store-this", "label": "public label",
             "reasoning": {"levels": [{"value": "low"}, {"value": "high"}], "defaultLevel": "low"}}
    responses = {"runtime/capabilities": {"independentPlanState": True},
                 "session/create": snapshot([model], selection), "session/close": {"closed": True}}
    result = make_probe(tmp_path, responses=responses)[0].probe()
    assert result["reason_code"] == "MODEL_CATALOG_OBSERVED"
    assert result["available_models"][0] == {"provider_id": "account:bigmodel-start-plan", "model_id": "GLM-5.3",
        "reasoning_levels": ["low", "high"], "default_reasoning_level": "low"}
    assert result["current_model"] == {"provider_id": "account:bigmodel-start-plan", "model_id": "GLM-5.3", "reasoning_level": "low"}
    assert result["identity_status"] == "unknown" and result["production_enabled"] is False
    assert "never-store-this" not in json.dumps(result) and "raw_payload" not in json.dumps(result)


@pytest.mark.parametrize("method", ["session/send", "turn/start", "workspace/generateText",
    "provider/testModelConnectivity", "provider/updateAccountConfig", "session/setModel", "session/list", "initialize"])
def test_forbidden_method_is_rejected_before_any_client_start(tmp_path, method):
    probe, fixture, _ = make_probe(tmp_path)
    with pytest.raises(ZCodeProtocolError, match="METADATA_METHOD_FORBIDDEN"):
        probe.request(method, {})
    assert fixture.started == 0 and fixture.calls == []


@pytest.mark.parametrize("bad", [None, {}, {"independentPlanState": "true"}, {"independentPlanState": 1}])
def test_bad_capabilities_fail_without_creating_a_session(tmp_path, bad):
    probe, fixture, _ = make_probe(tmp_path, responses={"runtime/capabilities": bad})
    result = probe.probe()
    assert result["reason_code"] == "CAPABILITIES_RESPONSE_INVALID"
    assert [method for method, _ in fixture.calls] == ["runtime/capabilities"]
    assert fixture.closed == 1


@pytest.mark.parametrize("damage", ["missing-session", "bad-revision", "bad-catalog", "bad-reference", "too-many-models"])
def test_malformed_metadata_cannot_be_reported_as_observed(tmp_path, damage):
    value = snapshot()
    if damage == "missing-session":
        value["session"] = {}
    elif damage == "bad-revision":
        value["runtime"]["stateRevision"] = True
    elif damage == "bad-catalog":
        value["settings"]["model"]["available"] = "GLM-5.3"
    elif damage == "bad-reference":
        value["settings"]["model"]["available"] = [{"ref": {"modelId": "GLM-5.3"}}]
    else:
        value["settings"]["model"]["available"] = [{"ref": {"providerId": "p", "modelId": "m"}}] * 513
    probe, fixture, _ = make_probe(tmp_path, responses={"runtime/capabilities": {"independentPlanState": True},
        "session/create": value, "session/close": {"closed": True}})
    result = probe.probe()
    assert result["reason_code"] == "METADATA_RESPONSE_INVALID"
    assert result["metadata_status"] == "failed" and fixture.closed == 1


@pytest.mark.parametrize("reason", ["RPC_TIMEOUT", "RPC_OUTPUT_LIMIT", "RPC_PROCESS_EXITED", "RPC_PROTOCOL_INVALID"])
def test_bounded_transport_failures_stay_explicit_and_close(tmp_path, reason):
    probe, fixture, _ = make_probe(tmp_path, failure=NativeRpcError(reason))
    result = probe.probe()
    assert result["reason_code"] == reason and result["metadata_status"] == "failed"
    assert result["identity_status"] == "unknown" and fixture.closed == 1


def test_old_callback_timeout_is_not_silently_treated_as_empty_catalog(tmp_path):
    error = NativeRpcError("RPC_SERVER_ERROR")
    error.error_code = -32022
    result = make_probe(tmp_path, failure=error)[0].probe()
    assert result["reason_code"] == "RUNTIME_PREFERENCES_CALLBACK_TIMEOUT"
    assert result["metadata_status"] == "failed" and result["available_models"] == []


@pytest.mark.parametrize("changes", [{"cleanup_complete": False}, {"running": 1}, {"open_handles": 1},
    {"temp_dirs": 1}, {"output_limited": True}])
def test_incomplete_or_limited_cleanup_blocks_the_metadata_result(tmp_path, changes):
    result = make_probe(tmp_path, clean=cleanup(**changes))[0].probe()
    expected = "RPC_OUTPUT_LIMIT" if changes.get("output_limited") else "RPC_CLEANUP_INCOMPLETE"
    assert result["reason_code"] == expected and result["metadata_status"] == "failed"


def test_foreign_session_request_is_rejected_before_transport(tmp_path):
    probe, fixture, _ = make_probe(tmp_path)
    with pytest.raises(ZCodeProtocolError, match="OWNED_METADATA_SESSION_REQUIRED"):
        probe.request("session/read", {"sessionId": "someone-else"})
    assert fixture.calls == []


def test_tool_enabling_create_options_are_rejected_before_transport(tmp_path):
    probe, fixture, _ = make_probe(tmp_path)
    with pytest.raises(ZCodeProtocolError, match="FIXED_METADATA_PARAMS_REQUIRED"):
        probe.request("session/create", {"mode": "yolo", "model": {"providerId": "p", "modelId": "m"}})
    assert fixture.calls == []


def test_unexpected_model_activity_cannot_pass_metadata_probe(tmp_path):
    probe, fixture, _ = make_probe(tmp_path)
    fixture.diagnostics["model_turn_starts"] = 1
    result = probe.probe()
    assert result["reason_code"] == "UNEXPECTED_MODEL_ACTIVITY" and result["metadata_status"] == "failed"
    assert result["model_turn_starts"] == 1 and result["production_enabled"] is False


@pytest.mark.parametrize("response", [None, {}, {"closed": False}, {"closed": 1}])
def test_close_response_requires_actual_confirmation(tmp_path, response):
    probe, fixture, _ = make_probe(tmp_path, responses={"runtime/capabilities": {"independentPlanState": True},
        "session/create": snapshot(), "session/close": response})
    result = probe.probe()
    assert result["session_close_confirmed"] is False
    assert result["metadata_status"] == "failed" and result["reason_code"] == "OWNED_SESSION_CLOSE_UNCONFIRMED"
    assert fixture.closed == 1


def test_sensitive_identifier_is_rejected_and_never_reused_as_session_binding(tmp_path):
    value = snapshot()
    value["session"]["sessionId"] = "person@example.com"
    probe, fixture, _ = make_probe(tmp_path, responses={"runtime/capabilities": {"independentPlanState": True},
        "session/create": value})
    result = probe.probe()
    assert result["reason_code"] == "METADATA_RESPONSE_INVALID"
    assert result["session_id"] is None
    assert "person@example.com" not in json.dumps(result)
    assert [method for method, _ in fixture.calls] == ["runtime/capabilities", "session/create"]


def test_probe_cannot_be_repeated_or_reopen_a_closed_session(tmp_path):
    probe, fixture, _ = make_probe(tmp_path)
    result = probe.probe()
    with pytest.raises(ZCodeProtocolError, match="METADATA_PROBE_ALREADY_USED"):
        probe.probe()
    with pytest.raises(ZCodeProtocolError, match="OWNED_METADATA_SESSION_REQUIRED"):
        probe.request("session/read", {"sessionId": result["session_id"]})
    assert fixture.started == fixture.closed == 1


@pytest.mark.parametrize("flag", ["--prompt", "--prompt=task", "-p", "--target", "--resume", "--continue"])
def test_metadata_invocation_cannot_start_inference_through_cli_flags(tmp_path, flag):
    with pytest.raises(ZCodeProtocolError, match="METADATA_INVOCATION_REQUIRED"):
        ZCodeProtocolClient(["fixture.exe", flag], tmp_path)


@pytest.mark.parametrize("seconds", [61, 120])
def test_timeout_limit_matches_the_shared_sixty_second_client(tmp_path, seconds):
    with pytest.raises(ZCodeProtocolError, match="RPC_BOUNDS_REQUIRED"):
        ZCodeProtocolClient(["fixture.exe"], tmp_path, timeout_seconds=seconds)


@pytest.mark.parametrize("limit", [1, 1023])
def test_output_floor_matches_the_shared_client(tmp_path, limit):
    with pytest.raises(ZCodeProtocolError, match="RPC_BOUNDS_REQUIRED"):
        ZCodeProtocolClient(["fixture.exe"], tmp_path, max_output_bytes=limit)


@pytest.mark.parametrize("command", [
    ["arbitrary-native.exe", "metadata-server"],
    ["C:/Program Files/nodejs/node.exe", "D:/zcode/resources/glm/zcode.cjs",
     "app-server", "--cwd", "<wrong-path>", "--no-color", "--verbose"],
])
def test_default_transport_requires_the_pinned_official_app_server_entry(tmp_path, command):
    with pytest.raises(ZCodeProtocolError, match="SUPPORTED_PROTOCOL_ENTRY_REQUIRED"):
        ZCodeProtocolClient(command, tmp_path)


RPC_FIXTURE = r"""
import json, sys
mode = sys.argv[1]
def emit(message):
    print(json.dumps(message), flush=True)
def receive():
    return json.loads(sys.stdin.readline())
while True:
    line = sys.stdin.readline()
    if not line:
        break
    request = json.loads(line)
    if request["method"] == "runtime/capabilities":
        emit({"id":request["id"], "result":{"independentPlanState":True}})
    elif request["method"] == "session/create":
        methods = {"preferences":"session/requestRuntimePreferences",
                   "headers":"interaction/requestProviderRuntimeHeaders",
                   "permission":"interaction/requestPermission",
                   "browser":"interaction/browserExecute"}
        emit({"id":"server-callback", "method":methods[mode],
              "params":{"sessionId":"sess-actual-fixture","scope":"runtime-materialization"}})
        reply = receive()
        if reply != {"id":"server-callback","error":{"code":-32601,"message":"Unsupported client request"}}:
            # The supported contract requires honest method-not-found; no
            # actual authentication or authorization operation exists here.
            if (reply.get("id") != "server-callback" or reply.get("error",{}).get("code") != -32601
                    or "result" in reply):
                sys.exit(4)
        if mode != "preferences":
            emit({"id":request["id"],"error":{"code":-32031,"message":"Unsupported host callback"}})
        else:
            emit({"id":request["id"],"result":{
                "session":{"sessionId":"sess-actual-fixture"},
                "runtime":{"stateRevision":0},"settings":{"model":{"available":[]}}}})
    elif request["method"] == "session/close":
        if request["params"] != {"sessionId":"sess-actual-fixture","expectedPersistence":"deferred"}:
            sys.exit(5)
        emit({"id":request["id"],"result":{"closed":True}})
    else:
        sys.exit(6)
"""


def native_fixture_factory(command, cwd, **options):
    # Explicit test injection still runs the common native managed transport.
    return NativeRpcClient(command, cwd, **options)


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Native managed transport is Windows-only")
def test_real_local_ndjson_callback_uses_honest_fallback_without_model_call(tmp_path):
    fixture = tmp_path / "rpc_fixture.py"
    fixture.write_text(RPC_FIXTURE, encoding="utf-8")
    result = ZCodeProtocolClient([sys.executable, str(fixture), "preferences"], tmp_path,
        client_factory=native_fixture_factory, timeout_seconds=5, max_output_bytes=32000).probe()
    assert result["metadata_status"] == "observed" and result["reason_code"] == "HOST_ACCOUNT_CONTEXT_REQUIRED"
    assert result["session_close_confirmed"] is True and result["model_turn_starts"] == 0
    assert result["cleanup"]["cleanup_complete"] is True
    assert all(result["cleanup"][key] == 0 for key in ("running", "open_handles", "temp_dirs"))
    assert result["identity_status"] == "unknown" and result["production_enabled"] is False


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Native managed transport is Windows-only")
@pytest.mark.parametrize("callback", ["headers", "permission", "browser"])
def test_real_local_ndjson_rejects_auth_permission_and_browser_callbacks(tmp_path, callback):
    fixture = tmp_path / "rpc_fixture.py"
    fixture.write_text(RPC_FIXTURE, encoding="utf-8")
    result = ZCodeProtocolClient([sys.executable, str(fixture), callback], tmp_path,
        client_factory=native_fixture_factory, timeout_seconds=5, max_output_bytes=32000).probe()
    assert result["metadata_status"] == "failed"
    assert result["server_error_code"] == -32031
    assert result["credential_headers_applied_by_client"] is False
    assert result["model_turn_starts"] == 0 and result["identity_status"] == "unknown"
    assert result["cleanup"]["cleanup_complete"] is True
