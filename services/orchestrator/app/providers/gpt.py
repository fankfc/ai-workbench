"""Codex JSONL boundary and shared capture validation; no process launch here.

Metadata belongs to the trusted transport. Requested model IDs and model prose
are never copied into observed identity. CLI JSONL currently omits model IDs,
so a normal Codex CLI capture retains unknown identity unless a separate trusted
provider response supplies it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Awaitable, Callable, Mapping

from app.contracts.events import AgentEvent
from app.contracts.providers import AgentRequest, ModelFamily, ProviderIdentity


FIXTURE_ARTIFACTS = {"result.txt": b"PROVIDER_BOUNDARY_OK\n"}


@dataclass(frozen=True)
class CapturedRun:
    stdout: bytes
    exit_code: int | None
    artifacts: Mapping[str, bytes]
    stderr: bytes = b""
    timed_out: bool = False
    metadata: Mapping[str, str] | None = None


@dataclass(frozen=True)
class DecodedRun:
    identity: ProviderIdentity
    identity_status: str
    reason_code: str
    events: tuple[AgentEvent, ...]
    usage: dict | None
    external_execution_id: str | None
    success: bool


@dataclass
class _Facts:
    adapter: str = "codex"
    models: list[str] = field(default_factory=list)
    configured_models: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)
    normalized: list[tuple[str, dict]] = field(default_factory=list)
    text: str = ""
    finished: bool = False
    error: str | None = None
    usage: dict | None = None


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)\bsk-(?:proj-)?[\w-]+", "[REDACTED]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)
    value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED_JWT]", value)
    value = re.sub(r"(?i)(\b[\w-]*(?:key|token|secret|password|authorization)[\w-]*\s*[:=]\s*)[^\r\n]+", r"\1[REDACTED]", value)
    return re.sub(r"(?<![A-Za-z0-9_.+-])[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", value) if "@" in value else value


def _safe_payload(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: "[REDACTED]" if re.search(r"(?i)key|token|secret|password|authorization|email", key) and not ("token" in key.lower() and type(item) in (int, float)) else _safe_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    return value


def _read_events(capture: CapturedRun) -> list[dict]:
    if len(capture.stdout) > 2_000_000:
        raise ValueError("EVENT_STREAM_TOO_LARGE")
    try:
        values = [json.loads(line) for line in capture.stdout.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeError, ValueError):
        raise ValueError("EVENT_STREAM_TRUNCATED_OR_INVALID") from None
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("EVENT_STREAM_INVALID")
    return values


def _family(model: str) -> ModelFamily:
    for prefix, family in (("claude-", ModelFamily.CLAUDE), ("gpt-", ModelFamily.GPT), ("glm-", ModelFamily.GLM)):
        if model.lower().startswith(prefix):
            return family
    return ModelFamily.UNKNOWN


def _finish(request: AgentRequest, capture: CapturedRun, facts: _Facts, expected_artifacts: Mapping[str, bytes]) -> DecodedRun:
    metadata = capture.metadata or {}
    if metadata.get("source") == "provider_response_metadata" and metadata.get("request_id") and metadata.get("model_id"):
        facts.models.append(metadata["model_id"])
    model = facts.models[-1] if facts.models else "unknown"
    family = _family(model)
    status = "verified" if family != ModelFamily.UNKNOWN else "unknown"
    if len(set(facts.models + facts.configured_models)) > 1:
        status = "mismatch"
        facts.error = facts.error or "MODEL_IDENTITY_CHANGED"
    if status == "verified" and (model != request.identity.model_id or family != request.identity.family):
        status = "mismatch"
    identity = ProviderIdentity(request.identity.adapter, model, family, request.identity.connection_id)
    reason = facts.error
    if reason is None and request.identity.adapter != facts.adapter:
        reason = "ADAPTER_REQUEST_MISMATCH"
    if reason is None and len(set(facts.sessions)) > 1:
        reason = "EXTERNAL_EXECUTION_CHANGED"
    if reason is None and not facts.sessions:
        reason = "EXTERNAL_EXECUTION_ID_MISSING"
    if reason is None and metadata.get("external_execution_id") and metadata["external_execution_id"] != facts.sessions[0]:
        reason = "METADATA_EXECUTION_MISMATCH"
    if reason is None and capture.timed_out:
        reason = "PROVIDER_TIMEOUT"
    if reason is None and capture.exit_code != 0:
        reason = "PROVIDER_EXIT_FAILED"
    if reason is None and not facts.text.strip():
        reason = "EMPTY_RESULT"
    if reason is None and not facts.finished:
        reason = "FINISH_EVENT_MISSING"
    if reason is None and status != "verified":
        reason = "MODEL_IDENTITY_MISMATCH" if status == "mismatch" else "MODEL_IDENTITY_UNVERIFIED"
    if reason is None:
        for name, expected in expected_artifacts.items():
            if name not in capture.artifacts:
                reason = "ARTIFACT_MISSING"
                break
            if capture.artifacts[name] != expected:
                reason = "ARTIFACT_BYTES_MISMATCH"
                break
    success = reason is None
    external = facts.sessions[0] if facts.sessions else None
    safe_usage = _safe_payload(facts.usage)
    records = [("provider.started", {"external_execution_id": external}),
               ("provider.identity", {"model_id": model, "family": family.value, "status": status}),
               *facts.normalized,
               ("provider.usage", {"status": "observed" if safe_usage is not None else "unknown", "usage": safe_usage}),
               ("provider.completed" if success else "provider.error", {"reason_code": reason or "CAPTURE_VERIFIED", "exit_code": capture.exit_code})]
    events = tuple(AgentEvent(request.task_id, request.attempt_id, index, kind, _safe_payload(payload)) for index, (kind, payload) in enumerate(records, 1))
    return DecodedRun(identity, status, reason or "CAPTURE_VERIFIED", events, safe_usage, external, success)


def decode_capture(request: AgentRequest, capture: CapturedRun, expected_artifacts: Mapping[str, bytes] | None = None) -> DecodedRun:
    facts = _Facts()
    try:
        events = _read_events(capture)
    except ValueError as error:
        facts.error = str(error)
        return _finish(request, capture, facts, FIXTURE_ARTIFACTS if expected_artifacts is None else expected_artifacts)
    for event in events:
        kind = event.get("type")
        if kind == "thread.started" and isinstance(event.get("thread_id"), str):
            facts.sessions.append(event["thread_id"])
        elif kind == "item.completed" and isinstance(event.get("item"), dict):
            item = event["item"]
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                facts.text += item["text"]
                facts.normalized.append(("model.delta", {"text": item["text"]}))
            elif item.get("type") in {"command_execution", "file_change", "mcp_tool_call"}:
                facts.normalized.append(("tool.completed", {"provider_item": item}))
                if item.get("status") == "failed" or (item.get("exit_code") is not None and item.get("exit_code") != 0):
                    facts.error = "TOOL_EXECUTION_FAILED"
        elif kind == "item.started" and isinstance(event.get("item"), dict):
            facts.normalized.append(("tool.started", {"provider_item": event["item"]}))
        elif kind == "turn.completed":
            facts.finished = True
            facts.usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
        elif kind in {"turn.failed", "error"}:
            facts.error = "PROVIDER_REPORTED_ERROR"
    return _finish(request, capture, facts, FIXTURE_ARTIFACTS if expected_artifacts is None else expected_artifacts)


class GptAdapter:
    """Capture transport is explicit; fixture success does not enable a profile."""
    adapter_id = "codex"
    decoder = staticmethod(decode_capture)
    resume_supported = False

    def __init__(self, transport: Callable[[AgentRequest], Awaitable[CapturedRun]] | None = None, *, expected_artifacts: Mapping[str, bytes] | None = None):
        self.transport = transport
        self.expected_artifacts = FIXTURE_ARTIFACTS if expected_artifacts is None else expected_artifacts
        self._identity = ProviderIdentity(self.adapter_id, "unknown", ModelFamily.UNKNOWN, "not_connected")

    async def probe(self) -> ProviderIdentity:
        return self._identity

    async def run(self, request: AgentRequest):
        if request.identity.adapter != self.adapter_id:
            yield AgentEvent(request.task_id, request.attempt_id, 1, "provider.error", {"reason_code": "ADAPTER_REQUEST_MISMATCH"})
            return
        if self.transport is None:
            yield AgentEvent(request.task_id, request.attempt_id, 1, "provider.error", {"reason_code": "SUPPORTED_EXECUTOR_NOT_ENABLED"})
            return
        try:
            captured = await self.transport(request)
            decoded = self.decoder(request, captured, self.expected_artifacts)
        except Exception:
            self._identity = ProviderIdentity(self.adapter_id, "unknown", ModelFamily.UNKNOWN, "not_connected")
            yield AgentEvent(request.task_id, request.attempt_id, 1, "provider.error", {"reason_code": "PROVIDER_TRANSPORT_FAILED"})
            return
        self._identity = decoded.identity if decoded.success else ProviderIdentity(self.adapter_id, "unknown", ModelFamily.UNKNOWN, "not_connected")
        for event in decoded.events:
            yield event

    async def cancel(self, task_id: str, attempt_id: str) -> None:
        raise ValueError("CANCELLATION_NOT_VERIFIED")
