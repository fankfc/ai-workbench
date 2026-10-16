"""ZCode protocol fixture coverage, kept separate from live capabilities."""
import json
from app.contracts.providers import AgentRequest, ProviderIdentity
from app.providers.gpt import CapturedRun
from app.providers.zcode import ZCodeAdapter, decode_capture


def request():
    return AgentRequest("t", "a", "B", ProviderIdentity("zcode", "glm-fixture", "glm", "local"), "prompt.txt", "workspace", "1")


def capture(events=None, **kwargs):
    if events is None:
        events = [{"type": "session.created", "sessionId": "sess-fixture", "seq": 1, "payload": {}},
                  {"type": "tool.updated", "sessionId": "sess-fixture", "seq": 2, "payload": {"kind": "started", "name": "Write", "toolCallId": "tool"}},
                  {"type": "turn.completed", "sessionId": "sess-fixture", "seq": 3, "payload": {"response": "Done"}},
                  {"type": "result", "sessionId": "sess-fixture", "traceId": "trace-fixture", "response": "Done", "projection": {"status": "idle"}}]
    metadata = kwargs.pop("metadata", {"model_id": "glm-fixture", "source": "provider_response_metadata", "request_id": "turn-fixture"})
    return CapturedRun(b"\n".join(json.dumps(x).encode() for x in events) + b"\n", kwargs.pop("exit_code", 0), kwargs.pop("artifacts", {"result.txt": b"PROVIDER_BOUNDARY_OK\n"}), metadata=metadata, **kwargs)


def test_zcode_protocol_requires_completion_and_artifact_proof():
    value = decode_capture(request(), capture())
    assert value.success
    assert value.identity.family == "glm"
    assert value.external_execution_id == "sess-fixture"


def test_zcode_result_summary_without_metadata_is_unverified():
    value = decode_capture(request(), capture(metadata=None))
    assert value.reason_code == "MODEL_IDENTITY_UNVERIFIED"
    assert not value.success


def test_zcode_actual_configuration_error_is_structured_failure():
    value = decode_capture(request(), capture([{"type": "turn.failed", "sessionId": "sess-fixture", "seq": 1, "payload": {"error": {"code": "CONFIGURATION_ERROR", "message": "Select a model before continuing"}, "turnPhase": "model_creation"}}], exit_code=1, artifacts={}, metadata=None))
    assert value.reason_code == "MODEL_SELECTION_REQUIRED"
    assert not value.success


def test_zcode_empty_summary_cannot_succeed():
    value = decode_capture(request(), capture([{"type": "result", "sessionId": "sess-fixture", "response": "", "projection": {"status": "idle"}}]))
    assert value.reason_code == "EMPTY_RESULT"
    assert not value.success


def test_zcode_live_unverified_connection_has_no_resume():
    assert ZCodeAdapter().resume_supported is False


def test_zcode_error_projection_cannot_override_completed_event():
    value = decode_capture(request(), capture([{"type": "turn.completed", "sessionId": "s", "seq": 1, "payload": {"response": "Done"}}, {"type": "result", "sessionId": "s", "response": "Done", "projection": {"status": "error"}}]))
    assert value.reason_code == "PROVIDER_REPORTED_ERROR"
    assert not value.success


def test_zcode_event_sequences_must_increase():
    value = decode_capture(request(), capture([{"type": "session.created", "sessionId": "s", "seq": 2, "payload": {}}, {"type": "turn.completed", "sessionId": "s", "seq": 1, "payload": {"response": "Done"}}, {"type": "result", "sessionId": "s", "response": "Done", "projection": {"status": "idle"}}]))
    assert value.reason_code == "PROVIDER_EVENT_SEQUENCE_INVALID"
    assert not value.success


def test_zcode_model_request_is_not_actual_response_identity():
    value = decode_capture(request(), capture([{"type": "session.updated", "sessionId": "s", "seq": 1, "payload": {"modelId": "glm-fixture", "providerId": "zai"}}, {"type": "turn.completed", "sessionId": "s", "seq": 2, "payload": {"response": "Done"}}, {"type": "result", "sessionId": "s", "response": "Done", "projection": {"status": "idle"}}], metadata=None))
    assert value.identity_status == "unknown"
    assert not value.success
