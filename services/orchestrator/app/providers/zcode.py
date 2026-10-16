"""ZCode session-event stream and result summary; no direct GLM API route."""
from typing import Mapping
from app.contracts.providers import AgentRequest
from .gpt import CapturedRun, DecodedRun, FIXTURE_ARTIFACTS, GptAdapter, _Facts, _finish, _read_events


def decode_capture(request: AgentRequest, capture: CapturedRun, expected_artifacts: Mapping[str, bytes] | None = None) -> DecodedRun:
    facts = _Facts(adapter="zcode")
    try:
        events = _read_events(capture)
    except ValueError as error:
        facts.error = str(error)
        return _finish(request, capture, facts, FIXTURE_ARTIFACTS if expected_artifacts is None else expected_artifacts)
    previous_sequence = 0
    for event in events:
        if event.get("type") != "result" and "seq" in event:
            sequence = event["seq"]
            if type(sequence) is not int or sequence <= previous_sequence:
                facts.error = "PROVIDER_EVENT_SEQUENCE_INVALID"
            else:
                previous_sequence = sequence
        if isinstance(event.get("sessionId"), str):
            facts.sessions.append(event["sessionId"])
        kind = event.get("type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if kind == "model.streaming" and payload.get("kind") == "text_delta" and isinstance(payload.get("delta"), str):
            facts.text += payload["delta"]
            facts.normalized.append(("model.delta", {"text": payload["delta"]}))
        elif kind == "tool.updated":
            facts.normalized.append(("tool.started" if payload.get("kind") == "started" else "tool.completed", {"provider_payload": payload}))
            if payload.get("kind") == "error":
                facts.error = "TOOL_EXECUTION_FAILED"
        elif kind == "turn.completed":
            facts.finished = True
            if isinstance(payload.get("response"), str):
                facts.text = payload["response"]
        elif kind == "result":
            if isinstance(event.get("response"), str):
                facts.text = event["response"]
            facts.usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
            if isinstance(event.get("projection"), dict) and event["projection"].get("status") in {"error", "failed", "cancelled"}:
                facts.error = "PROVIDER_REPORTED_ERROR"
        elif kind == "turn.failed":
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            facts.error = "MODEL_SELECTION_REQUIRED" if error.get("code") == "CONFIGURATION_ERROR" and payload.get("turnPhase") == "model_creation" else "PROVIDER_REPORTED_ERROR"
        elif kind == "permission.requested" or (kind == "permission.resolved" and payload.get("decision") == "deny"):
            facts.error = "PERMISSION_REQUIRED"
    return _finish(request, capture, facts, FIXTURE_ARTIFACTS if expected_artifacts is None else expected_artifacts)


class ZCodeAdapter(GptAdapter):
    adapter_id = "zcode"
    decoder = staticmethod(decode_capture)
