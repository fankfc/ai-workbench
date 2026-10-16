"""Explicitly bounded probes through fixed supported local CLI entry points.

Production profiles are never enabled here. A reviewed supported-entry manifest
must separately permit an experiment, and --execute plus --max-runs are required.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CARDS = {"claude_code": "D004", "zcode": "D005", "codex": "D006"}
PROFILE_IDS = {"claude_code": "local-claude-code-probe", "zcode": "local-zcode-probe", "codex": "local-codex-probe"}


def fixed_probe_argv(adapter, workspace, prompt, executable):
    """Arguments are application code, never profile-supplied shell commands."""
    if adapter == "codex":
        return [str(executable), "exec", "--json", "--sandbox", "workspace-write", "--ephemeral", "--skip-git-repo-check", "-C", str(workspace), "-"]
    if adapter == "zcode":
        return [str(executable), "D:/zcode/resources/glm/zcode.cjs", "--prompt", prompt, "--cwd", str(workspace), "--mode", "guarded", "--output-format", "stream-json", "--no-color", "--workflow-mode", "disabled"]
    if adapter == "claude_code":
        return [str(executable), "--print", prompt, "--output-format", "stream-json", "--verbose", "--max-turns", "3", "--permission-mode", "default", "--no-session-persistence"]
    raise ValueError("SUPPORTED_ENTRY_REQUIRED")


def _entry_manifest(adapter, repository_root):
    if adapter not in CARDS:
        return None
    path = repository_root / "docs/acceptance" / CARDS[adapter] / "supported-entry.json"
    try:
        if path.stat().st_size > 64000:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return (path, data) if isinstance(data, dict) and data.get("adapter") == adapter else None
    except (OSError, ValueError):
        return None


def _stop_owned_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdin=subprocess.DEVNULL, capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        process.kill()
    process.wait(timeout=15)


def _capture_cli(adapter, executable, workspace, prompt):
    from app.providers.gpt import CapturedRun
    argv = fixed_probe_argv(adapter, workspace, prompt, executable)
    # Credentials remain in the provider's own supported credential store.
    # Key/token-bearing environment variables are neither read nor forwarded.
    env = {key: value for key, value in os.environ.items() if not any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    if adapter == "claude_code":
        env.update(DISABLE_UPDATES="1", DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
    if adapter == "zcode":
        env["ZCODE_BUILTIN_PROVIDER_CONFIG_FILE"] = "D:/zcode/resources/config/provider/zcode-builtin.json"
    timed_out = overflow = False
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(argv, cwd=workspace, shell=False, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, env=env, creationflags=flags)
        try:
            if adapter == "codex":
                process.stdin.write(prompt.encode("utf-8"))
            process.stdin.close()
            deadline = time.monotonic() + 120
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    _stop_owned_process(process)
                    break
                if os.fstat(stdout.fileno()).st_size > 2_000_000 or os.fstat(stderr.fileno()).st_size > 200_000:
                    overflow = True
                    _stop_owned_process(process)
                    break
                time.sleep(0.05)
        finally:
            _stop_owned_process(process)
        stdout.seek(0)
        stderr.seek(0)
        raw_stdout = stdout.read(2_000_001)
        raw_stderr = stderr.read(200_001)
    artifact = workspace / "result.txt"
    artifacts = {"result.txt": artifact.read_bytes()} if artifact.is_file() and not artifact.is_symlink() and artifact.stat().st_size <= 64000 else {}
    return CapturedRun(raw_stdout, process.returncode, artifacts, raw_stderr, timed_out), {"argv": argv, "pid": process.pid, "local_process_alive": process.poll() is None, "remote_stop_confirmed": None, "output_overflow": overflow}


def _run_bounded_capture(profile, index, executable, evidence_root):
    from app.contracts.providers import AgentRequest, ProviderIdentity
    from app.providers.gpt import FIXTURE_ARTIFACTS, _read_events, _safe_payload, redact_text
    from app.providers.claude_code import decode_capture as claude_decode
    from app.providers.gpt import decode_capture as gpt_decode
    from app.providers.zcode import decode_capture as zcode_decode
    if index >= 3:
        raise ValueError("BOUNDED_RUN_LIMIT_REACHED")
    adapter = profile["adapter"]
    evidence_root.mkdir(parents=True, exist_ok=True)
    workspace = REPOSITORY_ROOT / ".tools/provider-probes" / adapter / uuid.uuid4().hex
    workspace.mkdir(parents=True)
    (workspace / "input.txt").write_bytes(b"PROVIDER_BOUNDARY_FIXTURE_20261013\n")
    prompt = "Read input.txt. Write result.txt with exactly PROVIDER_BOUNDARY_OK and one LF newline in UTF-8. Only work in this directory. Do not use network, install anything, spawn subagents, or inspect other files/accounts. If permission is required, report it and stop."
    if adapter == "codex":
        prompt = "请读取当前目录input.txt，只在当前目录创建result.txt，UTF-8内容恰为PROVIDER_BOUNDARY_OK和一个LF换行。用中文列出结果文件名。不要联网、安装、启动子代理或查看其他文件/账户；需要权限则停止并报告。"
    (workspace / "prompt.txt").write_text(prompt, encoding="utf-8")
    capture, process_facts = _capture_cli(adapter, executable, workspace, prompt)
    observed_model = None
    if adapter == "claude_code":
        try:
            for event in _read_events(capture):
                if event.get("type") == "assistant" and isinstance(event.get("message"), dict) and isinstance(event["message"].get("model"), str):
                    observed_model = event["message"]["model"]
        except ValueError:
            pass
    identity = ProviderIdentity(adapter, profile.get("model_id", observed_model or "unknown"), profile["expected_family"], profile.get("connection_id", profile["profile_id"]))
    request = AgentRequest(f"probe-{index}", f"attempt-{index}", "B" if adapter == "zcode" else "A", identity, str(workspace / "prompt.txt"), str(workspace), "1")
    decoded = {"claude_code": claude_decode, "zcode": zcode_decode, "codex": gpt_decode}[adapter](request, capture, FIXTURE_ARTIFACTS)
    # Preserve JSONL structure where possible while redacting recursively.
    lines = []
    for line in capture.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            lines.append(json.dumps(_safe_payload(json.loads(line)), ensure_ascii=False))
        except ValueError:
            lines.append(redact_text(line))
    (evidence_root / f"attempt-{index}.stdout.redacted.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (evidence_root / f"attempt-{index}.stderr.redacted.txt").write_text(redact_text(capture.stderr.decode("utf-8", errors="replace")), encoding="utf-8")
    evidence = {"adapter": adapter, "observed_family": decoded.identity.family.value, "response_model_id": decoded.identity.model_id, "request_id": decoded.external_execution_id or "unknown", "connection_id": identity.connection_id,
                "artifact_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in capture.artifacts.items()}, "finish_exit_artifact_consistent": decoded.success, "usage": decoded.usage, "failure_reason_code": decoded.reason_code, "workspace": str(workspace), **process_facts}
    path = evidence_root / f"attempt-{index}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**evidence, "expected_family": profile["expected_family"], "identity_verified": decoded.success, "identity_source": "provider_response_metadata" if decoded.success else None,
            "evidence_ref": str(path), "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build_registered_executors(profile, repository_root=REPOSITORY_ROOT, *, evidence_root=None):
    """Only canonical local entries with reviewed manifest permission register."""
    from app.providers.probe import RegisteredExecutor
    adapter = profile.get("adapter")
    manifest = _entry_manifest(adapter, repository_root)
    if manifest is None or profile.get("profile_id") != PROFILE_IDS.get(adapter):
        return {}
    path, data = manifest
    if data.get("bounded_probe_enabled") is not True:
        return {}
    fixed_paths = {"claude_code": REPOSITORY_ROOT / ".tools/claude/node_modules/@anthropic-ai/claude-code-win32-x64/claude.exe", "zcode": Path("C:/Program Files/nodejs/node.exe"), "codex": Path("C:/Users/asd15/AppData/Local/OpenAI/Codex/bin/f544b3844e0f14e9/codex.exe")}
    executable = fixed_paths[adapter].resolve()
    if profile.get("executable") != str(executable) or data.get("executable") != str(executable) or not executable.is_file():
        return {}
    if hashlib.sha256(executable.read_bytes()).hexdigest() != data.get("executable_sha256"):
        return {}
    if adapter == "zcode":
        entrypoint = Path("D:/zcode/resources/glm/zcode.cjs")
        if not entrypoint.is_file() or hashlib.sha256(entrypoint.read_bytes()).hexdigest() != data.get("entrypoint_sha256"):
            return {}
    destination = evidence_root or repository_root / ".tools/provider-probes/evidence" / adapter
    def run(selected, index):
        return _run_bounded_capture(selected, index, executable, destination)
    return {adapter: RegisteredExecutor(adapter, run, ("non_interactive", "isolated_workdir"), str(path), hashlib.sha256(path.read_bytes()).hexdigest())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args(argv)
    try:
        from app.providers.probe import ProbeError, read_profile, run_profile
    except ImportError:
        print(json.dumps({"status": "blocked", "reason_code": "PROJECT_ENVIRONMENT_REQUIRED", "model_starts": 0}))
        return 2
    try:
        profile = read_profile(options.profile)
        if options.execute and (type(options.max_runs) is not int or not 1 <= options.max_runs <= 3 or profile.get("requested_runs", 1) > 3):
            report = {"status": "blocked", "reason_code": "BOUNDED_RUN_LIMIT_REQUIRED", "model_starts": 0}
        else:
            evidence_root = options.output if options.output and options.output.suffix.lower() != ".json" else options.output.parent if options.output else None
            registrations = build_registered_executors(profile, evidence_root=evidence_root) if options.execute else {}
            report = run_profile(profile, execute=options.execute, max_runs=options.max_runs, executors=registrations)
            if options.execute and not registrations:
                manifest = _entry_manifest(profile["adapter"], REPOSITORY_ROOT)
                if manifest and manifest[1].get("block_reason_code"):
                    report["unavailable_reason_code"] = manifest[1]["block_reason_code"]
    except ProbeError as error:
        report = {"status": "blocked", "reason_code": str(error), "model_starts": 0}
    print(json.dumps(report, ensure_ascii=True))
    if options.output:
        # Historical plans use a directory; a .json path remains supported.
        destination = options.output if options.output.suffix.lower() == ".json" else options.output / "probe-report.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
