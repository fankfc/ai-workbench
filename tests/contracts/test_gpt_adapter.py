"""Codex JSONL fixtures do not confer real provider enablement."""
import asyncio
import json

from app.contracts.providers import AgentRequest, ProviderIdentity
from app.providers.gpt import CapturedRun, GptAdapter, decode_capture


def request():
    return AgentRequest("t", "a", "A", ProviderIdentity("codex", "gpt-fixture", "gpt", "local"), "prompt.txt", "workspace", "1")


def capture(events=None, **kwargs):
    if events is None:
        events = [{"type": "thread.started", "thread_id": "thread-fixture"},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "完成"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}}]
    return CapturedRun(json.dumps(events[0]).encode() + b"\n" + b"\n".join(json.dumps(x).encode() for x in events[1:]) + b"\n", kwargs.pop("exit_code", 0), kwargs.pop("artifacts", {"result.txt": b"PROVIDER_BOUNDARY_OK\n"}), **kwargs)


def metadata(model="gpt-fixture"):
    return {"model_id": model, "source": "provider_response_metadata", "request_id": "request-fixture"}


def test_codex_jsonl_without_model_metadata_cannot_verify_identity():
    value = decode_capture(request(), capture())
    assert value.identity_status == "unknown"
    assert value.reason_code == "MODEL_IDENTITY_UNVERIFIED"
    assert not value.success


def test_codex_capture_requires_verified_identity_artifact_finish_and_exit():
    value = decode_capture(request(), capture(metadata=metadata()))
    assert value.success
    assert value.external_execution_id == "thread-fixture"
    assert value.usage["input_tokens"] == 10
    assert value.events[-1].kind == "provider.completed"


def test_codex_exit_zero_without_artifact_is_failure():
    value = decode_capture(request(), capture(metadata=metadata(), artifacts={}))
    assert value.reason_code == "ARTIFACT_MISSING"
    assert not value.success


def test_codex_unknown_usage_remains_null():
    value = decode_capture(request(), capture(events=[{"type": "thread.started", "thread_id": "thread-fixture"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "完成"}}, {"type": "turn.completed"}], metadata=metadata()))
    assert value.usage is None
    assert next(x for x in value.events if x.kind == "provider.usage").payload["status"] == "unknown"


def test_codex_missing_transport_never_starts_or_completes():
    adapter = GptAdapter()
    async def run():
        return [x async for x in adapter.run(request())]
    value = asyncio.run(run())
    assert value[-1].payload["reason_code"] == "SUPPORTED_EXECUTOR_NOT_ENABLED"
    assert asyncio.run(adapter.probe()).family == "unknown"


def test_codex_resume_is_not_supported_without_verified_runtime():
    assert GptAdapter().resume_supported is False
    import pytest
    with pytest.raises(ValueError, match="CANCELLATION_NOT_VERIFIED"):
        asyncio.run(GptAdapter().cancel("t", "a"))


def test_codex_missing_external_execution_id_is_failure():
    value = decode_capture(request(), capture([{"type": "item.completed", "item": {"type": "agent_message", "text": "完成"}}, {"type": "turn.completed"}], metadata=metadata()))
    assert value.reason_code == "EXTERNAL_EXECUTION_ID_MISSING"
    assert not value.success


def test_codex_failed_tool_status_blocks_successful_turn():
    value = decode_capture(request(), capture([{"type": "thread.started", "thread_id": "s"}, {"type": "item.completed", "item": {"type": "command_execution", "status": "failed", "exit_code": 1}}, {"type": "item.completed", "item": {"type": "agent_message", "text": "完成"}}, {"type": "turn.completed"}], metadata=metadata()))
    assert value.reason_code == "TOOL_EXECUTION_FAILED"
    assert not value.success


def test_codex_capture_limit_rejects_overflow_even_valid_json():
    value = decode_capture(request(), capture([{"type": "thread.started", "thread_id": "s"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "x" * 2_100_000}}, {"type": "turn.completed"}], metadata=metadata()))
    assert value.reason_code == "EVENT_STREAM_TOO_LARGE"
    assert not value.success


def test_codex_usage_keeps_counts_and_redacts_secret_fields():
    value = decode_capture(request(), capture([{"type": "thread.started", "thread_id": "s"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "完成"}}, {"type": "turn.completed", "usage": {"cache_creation_input_tokens": 5, "api_key": "sk-fixture-secret"}}], metadata=metadata()))
    assert value.usage["api_key"] == "[REDACTED]"
    usage_event = next(x for x in value.events if x.kind == "provider.usage")
    assert usage_event.payload["usage"]["cache_creation_input_tokens"] == 5


def test_codex_model_metadata_must_bind_to_the_current_thread():
    value = decode_capture(request(), capture(metadata={**metadata(), "external_execution_id": "different-thread"}))
    assert value.reason_code == "METADATA_EXECUTION_MISMATCH"
    assert not value.success


def test_codex_invalid_json_tail_never_completes():
    original = capture(metadata=metadata())
    value = decode_capture(request(), CapturedRun(original.stdout + b'{"type":', 0, original.artifacts, metadata=metadata()))
    assert value.reason_code == "EVENT_STREAM_TRUNCATED_OR_INVALID"
    assert not value.success


def test_codex_timeout_ignores_late_valid_finish():
    value = decode_capture(request(), capture(timed_out=True, metadata=metadata()))
    assert value.reason_code == "PROVIDER_TIMEOUT"
    assert not value.success


def test_codex_nonzero_exit_ignores_successful_finish():
    value = decode_capture(request(), capture(exit_code=1, metadata=metadata()))
    assert value.reason_code == "PROVIDER_EXIT_FAILED"
    assert not value.success


def test_codex_transport_errors_return_fixed_nonsecret_event():
    async def transport(_):
        raise RuntimeError("sk-fixture-secret provider failed")
    async def run():
        return [x async for x in GptAdapter(transport).run(request())]
    values = asyncio.run(run())
    assert values[-1].payload["reason_code"] == "PROVIDER_TRANSPORT_FAILED"
    assert "secret" not in str(values)


def test_codex_wrong_adapter_request_does_not_call_transport():
    starts = []
    async def transport(_):
        starts.append(1)
        return capture(metadata=metadata())
    selected = AgentRequest("t", "a", "B", ProviderIdentity("zcode", "glm-fixture", "glm", "local"), "prompt.txt", "workspace", "1")
    async def run():
        return [x async for x in GptAdapter(transport).run(selected)]
    values = asyncio.run(run())
    assert starts == []
    assert values[-1].payload["reason_code"] == "ADAPTER_REQUEST_MISMATCH"


def test_codex_fake_source_cannot_verify_profile_alias():
    value = decode_capture(request(), capture(metadata={"model_id": "gpt-fixture", "source": "profile", "request_id": "r"}))
    assert value.identity_status == "unknown"
    assert not value.success


def probe_script():
    from pathlib import Path
    import importlib.util
    spec = importlib.util.spec_from_file_location("bounded_provider_probe", Path(__file__).resolve().parents[2] / "scripts/probe_provider.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_fixed_probe_argv_uses_existing_permission_boundary(tmp_path):
    script = probe_script()
    argv = script.fixed_probe_argv("codex", tmp_path, "fixture", tmp_path / "codex.exe")
    assert argv[1:3] == ["exec", "--json"]
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert "--ignore-rules" not in argv
    assert "--ignore-user-config" not in argv


def test_disabled_local_capability_never_registers_executor(tmp_path):
    script = probe_script()
    assert script.build_registered_executors({"adapter": "codex", "profile_id": "untrusted", "executable": "C:/arbitrary/other.exe"}, tmp_path) == {}


def test_zcode_fixed_probe_argv_always_chooses_guarded(tmp_path):
    argv = probe_script().fixed_probe_argv("zcode", tmp_path, "fixture", tmp_path / "node.exe")
    assert argv[argv.index("--mode") + 1] == "guarded"
    assert "yolo" not in argv
    assert "--output-format" in argv


def test_probe_script_rejects_more_than_three_starts_without_launch(tmp_path, capsys):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"schema_version": "1.0", "profile_id": "probe", "adapter": "codex", "expected_family": "gpt"}), encoding="utf-8")
    assert probe_script().main(["--profile", str(profile), "--execute", "--max-runs", "4"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["reason_code"] == "BOUNDED_RUN_LIMIT_REQUIRED"
    assert report["model_starts"] == 0
