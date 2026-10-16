"""Strict Claude Code stream-json normalization without launching a CLI."""
import json
import re
from typing import Mapping
from app.contracts.providers import AgentRequest
from .gpt import CapturedRun, DecodedRun, FIXTURE_ARTIFACTS, GptAdapter, _Facts, _finish, _read_events


def decode_capture(request: AgentRequest, capture: CapturedRun, expected_artifacts: Mapping[str, bytes] | None = None) -> DecodedRun:
    facts = _Facts(adapter="claude_code")
    try:
        events = _read_events(capture)
    except ValueError as error:
        facts.error = str(error)
        return _finish(request, capture, facts, FIXTURE_ARTIFACTS if expected_artifacts is None else expected_artifacts)
    for event in events:
        if isinstance(event.get("session_id"), str):
            facts.sessions.append(event["session_id"])
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init" and isinstance(event.get("model"), str):
            facts.configured_models.append(event["model"])
        elif kind == "assistant" and isinstance(event.get("message"), dict):
            message = event["message"]
            if isinstance(message.get("model"), str):
                facts.models.append(message["model"])
            for block in message.get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    facts.text += block["text"]
                    facts.normalized.append(("model.delta", {"text": block["text"]}))
                elif block.get("type") == "tool_use":
                    facts.normalized.append(("tool.started", {"tool_id": block.get("id"), "name": block.get("name"), "input": block.get("input")}))
        elif kind == "user" and isinstance(event.get("message"), dict):
            for block in event["message"].get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    facts.normalized.append(("tool.completed", {"tool_id": block.get("tool_use_id"), "is_error": block.get("is_error", False)}))
                    if block.get("is_error") is True:
                        facts.error = "TOOL_EXECUTION_FAILED"
        elif kind == "result":
            if event.get("is_error") is not False or event.get("subtype") != "success":
                diagnostic = json.dumps(event.get("errors", []))
                if re.search(r"(?i)not logged in|authentication|invalid (?:api )?key|unauthorized|\b401\b", diagnostic):
                    facts.error = "AUTHENTICATION_REQUIRED"
                elif re.search(r"(?i)rate.?limit|\b429\b", diagnostic):
                    facts.error = "RATE_LIMITED"
                else:
                    facts.error = "PROVIDER_REPORTED_ERROR"
            else:
                facts.finished = True
            if isinstance(event.get("result"), str):
                facts.text = event["result"]
            if isinstance(event.get("modelUsage"), dict):
                facts.models.extend(key for key in event["modelUsage"] if isinstance(key, str))
            facts.usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
            if event.get("permission_denials"):
                facts.error = "PERMISSION_REQUIRED"
        elif kind in {"permission_denied", "permission_request"}:
            facts.error = "PERMISSION_REQUIRED"
    return _finish(request, capture, facts, FIXTURE_ARTIFACTS if expected_artifacts is None else expected_artifacts)


class ClaudeCodeAdapter(GptAdapter):
    adapter_id = "claude_code"
    decoder = staticmethod(decode_capture)
