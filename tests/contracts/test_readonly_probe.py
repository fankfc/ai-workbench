"""D003 safety contracts. External processes are replaced only at the boundary."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.providers.probe import (
    ProbeError,
    RegisteredExecutor,
    classify_probe,
    collect_local_capabilities,
    read_profile,
    run_profile,
    run_readonly_command,
)


def identity_report(tmp_path, **changes):
    result = {
        "expected_family": "claude",
        "observed_family": "claude",
        "response_model_id": "claude-test-model",
        "identity_source": "provider_response_metadata",
        "identity_verified": True,
        "request_id": "test-request",
        "connection_id": "test-connection",
        "adapter": "test-adapter",
    }
    result.update(changes)
    metadata = {name: result[name] for name in ("observed_family", "response_model_id", "request_id", "connection_id", "adapter")}
    evidence = tmp_path / "response-metadata.json"
    evidence.write_text(json.dumps(metadata), encoding="utf-8")
    result.setdefault("evidence_ref", str(evidence))
    result["evidence_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    return result


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"identity_source": None, "app_name": "Claude Code", "model_alias": "Claude"}, "unknown"),
        ({"observed_family": "claude", "identity_source": None}, "unknown"),
        ({"identity_verified": False}, "unknown"),
        ({"identity_source": "configuration_alias"}, "unknown"),
        ({"evidence_ref": ""}, "unknown"),
        ({"response_model_id": ""}, "unknown"),
        ({}, "verified"),
        ({"observed_family": "gpt", "response_model_id": "gpt-test"}, "mismatch"),
        ({"observed_family": "other"}, "unknown"),
        ({"identity_source": ["provider_response_metadata"]}, "unknown"),
        ({"identity_source": {"source": "provider_response_metadata"}}, "unknown"),
        ({"observed_family": ["claude"]}, "unknown"),
        ({"expected_family": {"family": "claude"}}, "unknown"),
    ],
)
def test_only_verified_identity_evidence_can_classify_model(tmp_path, changes, expected):
    assert classify_probe(identity_report(tmp_path, **changes)) == expected


def test_application_label_alone_is_unknown():
    assert classify_probe({"app_name": "Claude Code", "model_alias": "Claude", "identity_source": None, "observed_family": None}) == "unknown"


@pytest.mark.parametrize("fault", ["missing", "changed_bytes", "wrong_request", "wrong_connection", "wrong_model"])
def test_identity_evidence_must_exist_match_hash_and_bind_request(tmp_path, fault):
    report = identity_report(tmp_path)
    evidence = Path(report["evidence_ref"])
    if fault == "missing":
        evidence.unlink()
    elif fault == "changed_bytes":
        evidence.write_text("changed", encoding="utf-8")
    elif fault == "wrong_request":
        report["request_id"] = "other-request"
    elif fault == "wrong_connection":
        report["connection_id"] = "other-connection"
    else:
        report["response_model_id"] = "other-model"
    assert classify_probe(report) == "unknown"


@pytest.fixture
def fake_cli(tmp_path):
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"fake-native-executable-for-boundary-test")
    config = tmp_path / "user-config.json"
    config.write_text('{"keep":"original"}', encoding="utf-8")
    secret = tmp_path / "credentials.json"
    secret.write_text('{"api_key":"PRIVATE_FILE_CANARY"}', encoding="utf-8")
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    calls = []
    model_starts = []

    def command(args, **kwargs):
        calls.append((args, kwargs))
        if args[1:] not in (["--version"], ["--help"]):
            model_starts.append(args)
            config.write_text("modified", encoding="utf-8")
        return subprocess.CompletedProcess(
            args, 0,
            "codex-cli 1.2.3\nOPENAI_API_KEY=HELP_SECRET_CANARY\n"
            "Usage: codex [OPTIONS] [COMMAND]\n"
            "exec Run Codex non-interactively\nresume Resume a saved session\n"
            "--model Select a model\n--cd Set working directory\n",
            "Authorization: Bearer STDERR_SECRET_CANARY",
        )

    return executable, config, secret, config_sha, calls, model_starts, command


def test_readonly_help_has_no_model_config_or_secret_side_effect(fake_cli, monkeypatch):
    executable, config, secret, config_sha, calls, starts, command = fake_cli
    monkeypatch.setenv("OPENAI_API_KEY", "ENV_SECRET_CANARY")
    result = run_readonly_command("codex", executable, ["--help"], runner=command)
    assert result.get("status") == "observed"
    assert len(calls) == 1
    assert calls[0][0] == [str(executable.resolve()), "--help"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] <= 15
    assert "OPENAI_API_KEY" not in calls[0][1]["env"]
    assert starts == []
    assert hashlib.sha256(config.read_bytes()).hexdigest() == config_sha
    assert secret.read_text(encoding="utf-8") == '{"api_key":"PRIVATE_FILE_CANARY"}'
    assert "SECRET_CANARY" not in json.dumps(result)
    assert "PRIVATE_FILE_CANARY" not in json.dumps(result)
    assert result.get("help_summary")


@pytest.mark.parametrize("tool,args", [("unknown", ["--help"]), ("codex", ["exec", "prompt"]), ("codex", ["--help", "--login"]), ("zcode", ["--version"])])
def test_unknown_or_non_readonly_command_is_rejected_before_launch(fake_cli, tool, args):
    executable, _, _, _, calls, starts, command = fake_cli
    with pytest.raises(ProbeError):
        run_readonly_command(tool, executable, args, runner=command)
    assert calls == []
    assert starts == []


def test_script_shim_is_not_executed_as_a_native_cli(tmp_path):
    calls = []
    shim = tmp_path / "codex.cmd"
    shim.write_text("echo unsafe", encoding="utf-8")
    with pytest.raises(ProbeError):
        run_readonly_command("codex", shim, ["--help"], runner=lambda *a, **k: calls.append(a))
    assert calls == []


def test_readonly_timeout_is_not_a_success(fake_cli):
    executable = fake_cli[0]
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"], output="sk-proj-SECRET_TIMEOUT_CANARY")
    result = run_readonly_command("codex", executable, ["--version"], runner=timeout)
    assert result.get("status") == "unknown"
    assert result.get("reason_code") == "READONLY_TIMEOUT"
    assert "SECRET_TIMEOUT_CANARY" not in json.dumps(result)


def test_node_version_keeps_the_major_component_after_v_prefix(tmp_path):
    executable = tmp_path / "node.exe"
    executable.touch()
    result = run_readonly_command("node", executable, ["--version"], runner=lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "v24.19.0\n", ""))
    assert result.get("version") == "24.19.0"


def test_usage_help_heading_is_not_token_measurement_evidence(fake_cli):
    result = run_readonly_command("codex", fake_cli[0], ["--help"], runner=fake_cli[-1])
    assert "usage" not in {item["capability"] for item in result.get("help_summary", [])}


def profile(**changes):
    result = {"schema_version": "1.0", "profile_id": "future-codex", "adapter": "codex", "expected_family": "gpt", "requested_runs": 1}
    result.update(changes)
    return result


def registered_executor(tmp_path, run):
    evidence = tmp_path / "verified-help.json"
    evidence.write_text(json.dumps({"adapter": "codex", "capabilities": ["non_interactive", "isolated_workdir"]}), encoding="utf-8")
    return RegisteredExecutor("codex", run, ("non_interactive", "isolated_workdir"), str(evidence), hashlib.sha256(evidence.read_bytes()).hexdigest())


def test_profile_defaults_to_readonly_and_does_not_call_executor(tmp_path):
    starts = []
    registration = RegisteredExecutor("codex", lambda p, i: starts.append(i), ("non_interactive", "isolated_workdir"), "verified-help.json")
    result = run_profile(profile(), executors={"codex": registration})
    assert result.get("status") == "not_connected"
    assert result.get("model_starts") == 0
    assert result.get("identity_status") == "unknown"
    assert starts == []


@pytest.mark.parametrize("limit", [None, 0, -1, True])
def test_real_execution_requires_an_explicit_positive_limit(limit):
    result = run_profile(profile(), execute=True, max_runs=limit)
    assert result.get("status") == "blocked"
    assert result.get("reason_code") == "EXPLICIT_RUN_LIMIT_REQUIRED"
    assert result.get("model_starts") == 0


def test_unimplemented_adapter_cannot_execute_arbitrary_profile_command():
    result = run_profile(profile(executable="C:/fake/codex.exe"), execute=True, max_runs=3)
    assert result.get("status") == "not_connected"
    assert result.get("reason_code") == "SUPPORTED_EXECUTOR_NOT_ENABLED"
    assert result.get("model_starts") == 0


def test_max_runs_caps_actual_registered_executor_starts(tmp_path):
    starts = []
    def execute(p, index):
        starts.append(index)
        return identity_report(tmp_path, expected_family="gpt", observed_family="gpt", response_model_id="gpt-test", adapter="codex")
    registration = registered_executor(tmp_path, execute)
    result = run_profile(profile(requested_runs=8), execute=True, max_runs=3, executors={"codex": registration})
    assert starts == [0, 1, 2]
    assert result.get("model_starts") == 3
    assert result.get("status") == "blocked"
    assert result.get("reason_code") == "RUN_LIMIT_REACHED"


@pytest.mark.parametrize("field,value", [("expected_family", "claude"), ("adapter", "claude_code"), ("connection_id", "other-connection"), ("response_model_id", "other-model")])
def test_executor_identity_must_bind_to_selected_profile(tmp_path, field, value):
    starts = []
    selected = profile(requested_runs=3, connection_id="test-connection", model_id="gpt-test")
    def execute(p, index):
        starts.append(index)
        changes = {"expected_family": "gpt", "observed_family": "gpt", "response_model_id": "gpt-test", "adapter": "codex", field: value}
        if field == "expected_family":
            changes["observed_family"] = value
        return identity_report(tmp_path, **changes)
    result = run_profile(selected, execute=True, max_runs=3, executors={"codex": registered_executor(tmp_path, execute)})
    assert result.get("status") == "blocked"
    assert result.get("identity_status") == "mismatch"
    assert result.get("reason_code") == "PROFILE_IDENTITY_MISMATCH"
    assert starts == [0]


def test_missing_executor_capability_evidence_blocks_all_starts():
    starts = []
    registration = RegisteredExecutor("codex", lambda p, i: starts.append(i), (), "")
    result = run_profile(profile(), execute=True, max_runs=1, executors={"codex": registration})
    assert result.get("reason_code") == "EXECUTOR_CAPABILITIES_UNVERIFIED"
    assert starts == []


@pytest.mark.parametrize("changes", [{"api_key": "sk-proj-PROFILE_SECRET_CANARY"}, {"command": ["powershell", "-Command", "unsafe"]}, {"environment": {"TOKEN": "SECRET"}}, {"identity_status": "verified"}, {"adapter": "unknown"}, {"adapter": ["codex"]}, {"adapter": {"name": "codex"}}, {"expected_family": "claude"}, {"requested_runs": "3"}])
def test_profile_rejects_secrets_arbitrary_commands_and_untrusted_identity(tmp_path, changes):
    path = tmp_path / "probe-profile.json"
    path.write_text(json.dumps(profile(**changes)), encoding="utf-8")
    with pytest.raises(ProbeError) as error:
        read_profile(path)
    assert "PROFILE_SECRET_CANARY" not in str(error.value)


def test_profile_reader_accepts_only_declared_metadata(tmp_path):
    path = tmp_path / "probe-profile.json"
    expected = profile(executable="C:/tools/codex.exe", model_id="gpt-expected")
    path.write_text(json.dumps(expected), encoding="utf-8")
    assert read_profile(path) == expected


def test_local_report_contains_evidence_for_each_capability(tmp_path):
    result = collect_local_capabilities(tmp_path / "local-capabilities.json", discover=False)
    records = result.get("capabilities", [])
    assert records
    assert all({"path", "version", "help_source", "capability", "status", "evidence_ref"} <= record.keys() for record in records)
    assert result.get("model_calls_made") is False
    assert result.get("user_configuration_modified") is False
    assert {"desktop_cli_session_shared", "desktop_cli_login_shared", "desktop_cli_quota_shared"} <= {item["capability"] for item in records}
    assert all(item["status"] == "unknown" for item in records if item["capability"].startswith("desktop_cli_"))
    assert (tmp_path / "local-capabilities.json").is_file()
    assert all(Path(item["evidence_ref"]).is_file() for item in records)


def test_known_gui_path_is_read_as_file_metadata_and_never_launched(tmp_path, monkeypatch):
    executable = tmp_path / "ZCode.exe"
    executable.write_bytes(b"not-a-native-test-process")
    def forbidden_launch(*args, **kwargs):
        raise AssertionError("GUI executable must never be launched")
    monkeypatch.setattr("app.providers.probe.run_readonly_command", forbidden_launch)
    report = collect_local_capabilities(tmp_path / "local-capabilities.json", discover=False, known_gui_paths={"zcode_gui": executable})
    installed = next(item for item in report.get("capabilities", []) if item["tool"] == "zcode_gui" and item["capability"] == "installed")
    assert installed["path"] == str(executable.resolve())
    assert installed["status"] == "available"
    assert next(item for item in report["capabilities"] if item["tool"] == "zcode_gui" and item["capability"] == "actual_model_identity")["status"] == "unknown"


def test_script_default_and_disabled_execute_are_nonzero_without_models(tmp_path):
    profile_path = tmp_path / "probe-profile.json"
    profile_path.write_text(json.dumps(profile()), encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "probe_provider.py"
    for suffix, reason in [([], "READ_ONLY_NO_CONNECTION_TEST"), (["--execute", "--max-runs", "3"], "SUPPORTED_EXECUTOR_NOT_ENABLED")]:
        result = subprocess.run([sys.executable, str(script), "--profile", str(profile_path), *suffix], capture_output=True, text=True, encoding="utf-8", shell=False)
        assert result.returncode != 0
        report = json.loads(result.stdout)
        assert report["reason_code"] == reason
        assert report["model_starts"] == 0

