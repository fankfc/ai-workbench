"""Claude stream-json fixtures; model prose is never identity evidence."""
import json
from app.contracts.providers import AgentRequest, ProviderIdentity
from app.providers.gpt import CapturedRun
from app.providers.claude_code import ClaudeCodeAdapter, decode_capture


def request():
    return AgentRequest("t", "a", "A", ProviderIdentity("claude_code", "claude-fixture", "claude", "local"), "prompt.txt", "workspace", "1")


def capture(events=None, **kwargs):
    if events is None:
        events = [{"type": "system", "subtype": "init", "session_id": "claude-session", "model": "claude-fixture", "tools": ["Read", "Write"]},
                  {"type": "assistant", "session_id": "claude-session", "message": {"model": "claude-fixture", "content": [{"type": "text", "text": "Done"}, {"type": "tool_use", "id": "tool", "name": "Write", "input": {"file_path": "result.txt"}}]}},
                  {"type": "result", "subtype": "success", "is_error": False, "session_id": "claude-session", "result": "Done", "usage": {"input_tokens": 8}, "modelUsage": {"claude-fixture": {"inputTokens": 8}}}]
    return CapturedRun(b"\n".join(json.dumps(x).encode() for x in events) + b"\n", kwargs.pop("exit_code", 0), kwargs.pop("artifacts", {"result.txt": b"PROVIDER_BOUNDARY_OK\n"}), **kwargs)


def test_claude_response_metadata_and_result_are_required():
    value = decode_capture(request(), capture())
    assert value.success
    assert value.identity.family == "claude"
    assert value.external_execution_id == "claude-session"
    assert any(x.kind == "tool.started" for x in value.events)


def test_claude_model_self_claim_does_not_verify_identity():
    value = decode_capture(request(), capture([{"type": "result", "subtype": "success", "is_error": False, "session_id": "claude-session", "result": "I am Claude"}]))
    assert value.identity_status == "unknown"
    assert not value.success


def test_claude_error_result_cannot_be_success():
    value = decode_capture(request(), capture([{"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "turn limit"}]))
    assert value.reason_code == "PROVIDER_REPORTED_ERROR"
    assert not value.success


def test_claude_artifact_bytes_must_match():
    value = decode_capture(request(), capture(artifacts={"result.txt": b"wrong\n"}))
    assert value.reason_code == "ARTIFACT_BYTES_MISMATCH"
    assert not value.success


def test_claude_requires_explicit_transport_and_no_implicit_resume():
    assert ClaudeCodeAdapter().resume_supported is False


def test_claude_model_change_during_response_is_not_hidden_by_final_model():
    value = decode_capture(request(), capture([
        {"type": "system", "subtype": "init", "session_id": "s", "model": "claude-other"},
        {"type": "assistant", "session_id": "s", "message": {"model": "claude-fixture", "content": [{"type": "text", "text": "Done"}]}},
        {"type": "result", "session_id": "s", "subtype": "success", "is_error": False, "result": "Done"}]))
    assert value.identity_status == "mismatch"
    assert value.reason_code == "MODEL_IDENTITY_CHANGED"
    assert not value.success


def test_claude_success_result_requires_explicit_false_error_flag():
    value = decode_capture(request(), capture([{"type": "assistant", "session_id": "s", "message": {"model": "claude-fixture", "content": [{"type": "text", "text": "Done"}]}}, {"type": "result", "session_id": "s", "subtype": "success", "result": "Done"}]))
    assert not value.success
    assert value.reason_code == "PROVIDER_REPORTED_ERROR"


def test_claude_permission_denial_in_result_is_a_block():
    value = decode_capture(request(), capture([{"type": "result", "session_id": "s", "subtype": "success", "is_error": False, "result": "Permission needed", "modelUsage": {"claude-fixture": {}}, "permission_denials": [{"tool_name": "Write"}]}]))
    assert value.reason_code == "PERMISSION_REQUIRED"
    assert not value.success


def test_claude_mixed_session_ids_are_rejected():
    value = decode_capture(request(), capture([{"type": "assistant", "session_id": "one", "message": {"model": "claude-fixture", "content": [{"type": "text", "text": "Done"}]}}, {"type": "result", "session_id": "two", "subtype": "success", "is_error": False, "result": "Done"}]))
    assert value.reason_code == "EXTERNAL_EXECUTION_CHANGED"
    assert not value.success


def test_claude_rate_limit_result_is_fixed_failure():
    value = decode_capture(request(), capture([{"type": "result", "session_id": "s", "subtype": "error_during_execution", "is_error": True, "errors": ["429 rate limit"]}], artifacts={}))
    assert value.reason_code == "RATE_LIMITED"
    assert not value.success


def test_claude_not_logged_in_result_is_fixed_failure():
    value = decode_capture(request(), capture([{"type": "result", "session_id": "s", "subtype": "error_during_execution", "is_error": True, "errors": ["Not logged in. Please run /login"]}], artifacts={}))
    assert value.reason_code == "AUTHENTICATION_REQUIRED"
    assert not value.success
