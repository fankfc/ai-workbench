"""Read-only installation evidence and an opt-in, bounded provider probe gate.

No provider request executor is registered by this module. Installation facts,
help mentions, and profile aliases never establish a connected model identity.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


class ProbeError(ValueError):
    """A fixed, non-secret diagnostic for an unsafe probe request."""


FAMILIES = frozenset({"claude", "gpt", "glm"})
ADAPTER_FAMILIES = {"claude_code": "claude", "zcode": "glm", "codex": "gpt"}
READONLY_COMMANDS = {
    "python": (frozenset({("--version",)}), {"python.exe", "python3.exe"}),
    "node": (frozenset({("--version",)}), {"node.exe"}),
    "codex": (frozenset({("--version",), ("--help",)}), {"codex.exe"}),
    "claude_code": (frozenset({("--version",), ("--help",)}), {"claude.exe"}),
    "pandoc": (frozenset({("--version",)}), {"pandoc.exe"}),
    "tesseract": (frozenset({("--version",)}), {"tesseract.exe"}),
}
PROFILE_FIELDS = {"schema_version", "profile_id", "adapter", "expected_family", "requested_runs", "executable", "model_id", "connection_id"}
HELP_PATTERNS = {
    "non_interactive": r"^\s*exec\s|--print\b|--non-interactive\b",
    "working_directory": r"--cd\b|--cwd\b|--directory\b",
    "resume": r"^\s*resume\s|--resume\b",
    "model_selection": r"--model\b",
    "structured_output": r"--json\b|--output-format\b|--output-schema\b",
    "cancellation": r"^\s*cancel\s|Ctrl[+-]C",
    "usage": r"^\s*(?:--usage\b|usage\s+(?!:)|token[-_ ]usage\b)",
}


def _verified_evidence(ref: object, digest: object) -> dict | None:
    if not isinstance(ref, str) or not ref or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        return None
    try:
        path = Path(ref)
        if not path.is_file() or path.stat().st_size > 1_000_000:
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            return None
        evidence = json.loads(data)
        return evidence if isinstance(evidence, dict) else None
    except (OSError, ValueError):
        return None


def classify_probe(report: dict) -> str:
    """Classify adapter-produced evidence, never user profile identity claims.

The trusted adapter is responsible for acquiring response metadata or verifying
the source. The file/hash binding proves integrity, not provider authenticity.
"""
    if not isinstance(report, dict) or report.get("identity_verified") is not True:
        return "unknown"
    if not isinstance(report.get("identity_source"), str) or report["identity_source"] not in {"provider_response_metadata", "verified_source"}:
        return "unknown"
    if any(not isinstance(report.get(key), str) or report[key] not in FAMILIES for key in ("observed_family", "expected_family")):
        return "unknown"
    fields = ("observed_family", "response_model_id", "request_id", "connection_id", "adapter")
    if not all(isinstance(report.get(key), str) and report[key] for key in fields):
        return "unknown"
    evidence = _verified_evidence(report.get("evidence_ref"), report.get("evidence_sha256"))
    if evidence is None or any(evidence.get(key) != report[key] for key in fields):
        return "unknown"
    return "verified" if report["observed_family"] == report["expected_family"] else "mismatch"


def _redact(text: str) -> str:
    text = re.sub(r"(?i)\bsk-(?:proj-)?[\w-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", text)
    return re.sub(r"(?i)(\b[\w-]*(?:key|token|secret|password|authorization)[\w-]*\s*[:=]\s*)[^\r\n]+", r"\1[REDACTED]", text)


def run_readonly_command(tool: str, executable: Path, args: list[str], *, runner: Callable | None = None) -> dict:
    """Run only a fixed native version/help command. Profiles cannot use this.

The caller discovers the installed path; executable names are a safety check,
not proof of publisher, provider, model, or account identity.
"""
    policy = READONLY_COMMANDS.get(tool)
    if policy is None or tuple(args) not in policy[0]:
        raise ProbeError("COMMAND_NOT_IN_READONLY_ALLOWLIST")
    path = Path(executable).resolve()
    if path.name.lower() not in policy[1] or not path.is_file():
        raise ProbeError("NATIVE_EXECUTABLE_REQUIRED")
    argv = [str(path), *args]
    # Keep only variables needed by native runtimes. Provider credentials and
    # arbitrary application environment variables are not forwarded.
    env_names = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "COMSPEC", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "APPDATA", "USERPROFILE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in env_names}
    result = {"command": argv, "shell": False, "status": "unknown", "version": None, "help_summary": [], "exit_code": None}
    try:
        completed = (runner or subprocess.run)(argv, shell=False, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return {**result, "reason_code": "READONLY_TIMEOUT"}
    except OSError:
        return {**result, "reason_code": "READONLY_LAUNCH_FAILED"}
    result["exit_code"] = completed.returncode
    if completed.returncode != 0:
        return {**result, "reason_code": "READONLY_COMMAND_FAILED"}
    clean = _redact(completed.stdout[:64_000])
    if args == ["--version"]:
        match = re.search(r"(?<![\w.])v?(\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.]+)?)(?![\w.])", clean)
        result["version"] = match.group(1) if match else None
    else:
        for capability, pattern in HELP_PATTERNS.items():
            line = next((line for line in clean.splitlines() if re.search(pattern, line, re.I) and "[REDACTED]" not in line), None)
            if line:
                result["help_summary"].append({"capability": capability, "excerpt": line.strip()[:240]})
    result["status"] = "observed"
    result["reason_code"] = "READONLY_COMMAND_OBSERVED"
    return result


def validate_profile(profile: object) -> dict:
    if not isinstance(profile, dict) or set(profile) - PROFILE_FIELDS:
        raise ProbeError("PROFILE_FIELDS_INVALID")
    if profile.get("schema_version") != "1.0" or not isinstance(profile.get("profile_id"), str) or not profile["profile_id"]:
        raise ProbeError("PROFILE_SCHEMA_INVALID")
    adapter = profile.get("adapter")
    if not isinstance(adapter, str) or adapter not in ADAPTER_FAMILIES or profile.get("expected_family") != ADAPTER_FAMILIES[adapter]:
        raise ProbeError("PROFILE_ADAPTER_FAMILY_INVALID")
    runs = profile.get("requested_runs", 1)
    if type(runs) is not int or runs < 1:
        raise ProbeError("PROFILE_RUN_COUNT_INVALID")
    if any(key in profile and (not isinstance(profile[key], str) or not profile[key]) for key in ("executable", "model_id", "connection_id")):
        raise ProbeError("PROFILE_METADATA_INVALID")
    return dict(profile)


def read_profile(path: Path) -> dict:
    try:
        if Path(path).stat().st_size > 64_000:
            raise ProbeError("PROFILE_TOO_LARGE")
        return validate_profile(json.loads(Path(path).read_text(encoding="utf-8-sig")))
    except ProbeError:
        raise
    except (OSError, ValueError):
        raise ProbeError("PROFILE_UNREADABLE") from None


@dataclass(frozen=True)
class RegisteredExecutor:
    """Trusted future adapter hook: one call starts at most one model request.

Registrations come from application code, never from a JSON profile. Future
adapters must send retries through this gate; no adapter is enabled in D003.
"""
    adapter: str
    run: Callable[[dict, int], dict]
    capabilities: tuple[str, ...]
    evidence_ref: str
    evidence_sha256: str = ""


def run_profile(profile: dict, *, execute: bool = False, max_runs: int | None = None, executors: Mapping[str, RegisteredExecutor] | None = None) -> dict:
    profile = validate_profile(profile)
    result = {"profile_id": profile["profile_id"], "adapter": profile["adapter"], "status": "not_connected", "identity_status": "unknown", "model_starts": 0, "max_runs": max_runs}
    if not execute:
        return {**result, "reason_code": "READ_ONLY_NO_CONNECTION_TEST"}
    if type(max_runs) is not int or max_runs < 1:
        return {**result, "status": "blocked", "reason_code": "EXPLICIT_RUN_LIMIT_REQUIRED"}
    registration = (executors or {}).get(profile["adapter"])
    if registration is None:
        return {**result, "reason_code": "SUPPORTED_EXECUTOR_NOT_ENABLED"}
    evidence = _verified_evidence(registration.evidence_ref, registration.evidence_sha256)
    required = {"non_interactive", "isolated_workdir"}
    if not callable(registration.run) or registration.adapter != profile["adapter"] or not required <= set(registration.capabilities) or evidence is None or evidence.get("adapter") != registration.adapter or not required <= set(evidence.get("capabilities", [])):
        return {**result, "status": "blocked", "reason_code": "EXECUTOR_CAPABILITIES_UNVERIFIED"}
    for index in range(profile.get("requested_runs", 1)):
        if result["model_starts"] >= max_runs:
            return {**result, "status": "blocked", "reason_code": "RUN_LIMIT_REACHED"}
        # Consume the start allowance before calling the adapter, including a
        # failed/timeout attempt. Its status is not a reason to reset the limit.
        result["model_starts"] += 1
        try:
            observed = registration.run(dict(profile), index)
        except Exception:
            return {**result, "status": "blocked", "reason_code": "EXECUTOR_ATTEMPT_FAILED"}
        result["identity_status"] = classify_probe(observed)
        if isinstance(observed, dict) and result["identity_status"] != "unknown":
            bindings = {"expected_family": profile["expected_family"], "observed_family": profile["expected_family"], "adapter": registration.adapter}
            if "connection_id" in profile:
                bindings["connection_id"] = profile["connection_id"]
            if "model_id" in profile:
                bindings["response_model_id"] = profile["model_id"]
            if any(observed.get(key) != value for key, value in bindings.items()):
                return {**result, "status": "blocked", "identity_status": "mismatch", "reason_code": "PROFILE_IDENTITY_MISMATCH"}
        if result["identity_status"] != "verified":
            return {**result, "status": "blocked", "reason_code": "MODEL_IDENTITY_UNVERIFIED"}
    return {**result, "status": "verified", "reason_code": "REGISTERED_PROBE_VERIFIED"}


def _pe_version(path: Path) -> str | None:
    """Read Windows version resources without launching a GUI executable."""
    if os.name != "nt":
        return None
    try:
        dll = ctypes.WinDLL("version", use_last_error=True)
        dll.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
        dll.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
        dll.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        dll.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
        size = dll.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not dll.GetFileVersionInfoW(str(path), 0, size, buffer):
            return None
        pointer, length = ctypes.c_void_p(), ctypes.c_uint()
        if not dll.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None
        words = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
        if words[0] != 0xFEEF04BD:
            return None
        return ".".join(str(value) for value in (words[2] >> 16, words[2] & 0xFFFF, words[3] >> 16, words[3] & 0xFFFF))
    except (OSError, ValueError):
        return None


def _uninstall_entries() -> list[dict]:
    """Read only relevant uninstall display name, location and version fields."""
    if os.name != "nt":
        return []
    import winreg
    entries = []
    suffix = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive, label in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, suffix, 0, winreg.KEY_READ | view) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        name = winreg.EnumKey(root, index)
                        try:
                            with winreg.OpenKey(root, name) as key:
                                display_name = winreg.QueryValueEx(key, "DisplayName")[0]
                                if not isinstance(display_name, str) or not re.search(r"Claude|ZCode|Codex|Pandoc|LibreOffice|Tesseract|Node\.js|Python", display_name, re.I):
                                    continue
                                item = {"DisplayName": display_name, "registry_source": f"{label}/{suffix}/{name}"}
                                for field in ("InstallLocation", "DisplayVersion"):
                                    try:
                                        value = winreg.QueryValueEx(key, field)[0]
                                        item[field] = value if isinstance(value, str) else None
                                    except OSError:
                                        item[field] = None
                                if item not in entries:
                                    entries.append(item)
                        except OSError:
                            continue
            except OSError:
                continue
    return entries


def _installed_paths(entries: list[dict]) -> dict[str, Path | None]:
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    home = Path.home()
    programs = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    paths = {"python": Path(sys.executable).resolve()}
    for tool, name in (("node", "node.exe"), ("codex", "codex.exe"), ("claude_code", "claude.exe"), ("pandoc", "pandoc.exe"), ("tesseract", "tesseract.exe"), ("pdftotext", "pdftotext.exe"), ("libreoffice", "soffice.exe"), ("zcode_gui", "zcode.exe")):
        found = shutil.which(name)
        paths[tool] = Path(found).resolve() if found else None
    candidates = {
        "claude_code": [home / ".local/bin/claude.exe"],
        "claude_gui": [local / "Programs/Claude/Claude.exe", local / "AnthropicClaude/Claude.exe", local / "Claude/Claude.exe"],
        "zcode_gui": [local / "Programs/ZCode/ZCode.exe", local / "ZCode/ZCode.exe", programs / "ZCode/ZCode.exe"],
        "pandoc": [local / "Pandoc/pandoc.exe", programs / "Pandoc/pandoc.exe"],
        "tesseract": [programs / "Tesseract-OCR/tesseract.exe"],
        "libreoffice": [programs / "LibreOffice/program/soffice.exe"],
    }
    for entry in entries:
        location = entry.get("InstallLocation")
        if not location:
            continue
        if re.search("ZCode", entry["DisplayName"], re.I):
            candidates["zcode_gui"].append(Path(location) / "ZCode.exe")
        if re.search("Claude", entry["DisplayName"], re.I):
            candidates["claude_gui"].append(Path(location) / "Claude.exe")
    for tool, options in candidates.items():
        paths.setdefault(tool, None)
        if paths[tool] is None:
            paths[tool] = next((path.resolve() for path in options if path.is_file()), None)
    return paths


def collect_local_capabilities(output: Path, *, discover: bool = True, known_gui_paths: Mapping[str, Path] | None = None) -> dict:
    """Write explicit report artifacts; never enumerate account/provider config."""
    output = Path(output).resolve()
    evidence_dir = output.parent / "D003"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    trace_path = evidence_dir / "probe-trace.json"
    installed = _uninstall_entries() if discover else []
    paths = _installed_paths(installed) if discover else {}
    for tool, supplied_path in (known_gui_paths or {}).items():
        if tool not in {"zcode_gui", "claude_gui"}:
            raise ProbeError("GUI_METADATA_PATH_INVALID")
        supplied_path = Path(supplied_path).resolve()
        if supplied_path.is_file():
            paths[tool] = supplied_path
    commands, records = [], []

    def record(tool, path, version, capability, status, help_source=None, kind="fact"):
        records.append({"tool": tool, "path": str(path) if path else None, "version": version, "help_source": help_source, "capability": capability, "status": status, "evidence_ref": str(trace_path), "evidence_kind": kind})

    for tool in ("python", "node", "codex", "claude_code", "zcode_gui", "claude_gui", "pandoc", "libreoffice", "tesseract", "pdftotext"):
        path = paths.get(tool)
        version = _pe_version(path) if path else None
        version_source = "PE version resource" if version else None
        help_result = None
        if path and tool in READONLY_COMMANDS:
            result = run_readonly_command(tool, path, ["--version"])
            commands.append(result)
            if result.get("version"):
                version = result["version"]
                version_source = str(trace_path) + "#commands"
            if tool in {"codex", "claude_code"}:
                help_result = run_readonly_command(tool, path, ["--help"])
                commands.append(help_result)
        record(tool, path, version, "installed", "available" if path else "unavailable", version_source)
        if tool in {"codex", "claude_code", "zcode_gui"}:
            by_help = {item["capability"] for item in (help_result or {}).get("help_summary", [])}
            for capability in ("launch", "non_interactive", "working_directory", "cancellation", "resume", "model_selection", "usage"):
                record(tool, path, version, capability, "documented" if capability in by_help else "unknown", str(trace_path) + "#help_summary" if help_result else None, "inference" if capability in by_help else "unknown")
            record(tool, path, version, "actual_model_identity", "unknown", kind="unknown")
        if tool in {"pandoc", "libreoffice", "tesseract", "pdftotext"}:
            record(tool, path, version, "format_execution", "unknown" if path else "unavailable", kind="unknown" if path else "fact")

    npm_version, npm_path = None, None
    node_path = paths.get("node")
    if node_path:
        package = node_path.parent / "node_modules/npm/package.json"
        if package.is_file():
            try:
                npm_version = json.loads(package.read_text(encoding="utf-8"))["version"]
                npm_path = package
            except (OSError, ValueError, KeyError):
                pass
    record("npm", npm_path, npm_version, "installed", "available" if npm_version else "unavailable", "installed npm package metadata" if npm_path else None)
    for capability in ("desktop_cli_session_shared", "desktop_cli_login_shared", "desktop_cli_quota_shared"):
        record("provider_connections", None, None, capability, "unknown", kind="unknown")
    report = {
        "schema_version": "1.0", "task_id": "D003", "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only", "model_calls_made": False, "user_configuration_modified": False,
        "capabilities": records, "facts": [item for item in records if item["evidence_kind"] == "fact"],
        "inferences": [item for item in records if item["evidence_kind"] == "inference"],
        "unknowns": [item for item in records if item["evidence_kind"] == "unknown"],
        "limitations": ["Version/help and PE metadata prove installation observations only.", "Help mentions are not execution, authentication, quota, or model verification.", "GUI executables and MiKTeX pdftotext are never launched.", "No real provider executor is enabled; D004-D006 require supported adapter evidence and explicit bounded execution."],
    }
    trace = {"task_id": "D003", "generated_at": report["generated_at"], "commands": commands, "installed_apps": installed, "discovered_paths": {key: str(value) if value else None for key, value in paths.items()}, "known_gui_paths": {key: str(Path(value).resolve()) for key, value in (known_gui_paths or {}).items()}, "gui_metadata_method": "Windows PE version resources; no GUI process launch", "registry_fields_read": ["DisplayName", "InstallLocation", "DisplayVersion"], "model_starts": 0, "gui_processes_started": 0, "configuration_files_read": [], "user_configuration_modified": False}
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only local capability evidence; no model requests.")
    parser.add_argument("--read-only", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zcode-gui", type=Path, help="Known installed GUI file: PE metadata only; never launched.")
    parser.add_argument("--claude-gui", type=Path, help="Known installed GUI file: PE metadata only; never launched.")
    options = parser.parse_args(argv)
    known = {key: value for key, value in (("zcode_gui", options.zcode_gui), ("claude_gui", options.claude_gui)) if value is not None}
    report = collect_local_capabilities(options.output, known_gui_paths=known)
    print(json.dumps({"mode": report["mode"], "output": str(options.output), "capabilities": len(report["capabilities"]), "model_calls_made": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
