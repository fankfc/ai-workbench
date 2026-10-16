"""Collect D002 tool versions and hashes without provider or credential access."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import FormatChecker


ROOT = Path(__file__).resolve().parents[3]


def command_version(command: list[str]) -> str:
    result = subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


node = shutil.which("node.exe")
npm = shutil.which("npm.cmd")
assert node is not None and npm is not None
head = subprocess.run(
    ["git", "rev-parse", "--verify", "HEAD"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
direct_python = [
    "fastapi", "pydantic", "uvicorn", "pytest", "httpx", "jsonschema", "rfc3339-validator"
]
direct_node = ["electron", "react", "react-dom", "typescript", "@playwright/test"]
node_packages = {}
for name in direct_node:
    manifest = json.loads((ROOT / "node_modules" / name / "package.json").read_text("utf-8"))
    node_packages[name] = manifest["version"]
requirements_path = ROOT / "docs/decisions/requirements-v1.json"
requirements = json.loads(requirements_path.read_text("utf-8-sig"))
report = {
    "schema_version": "1.0",
    "task_id": "D002",
    "recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    "repository_root": ROOT.as_posix(),
    "branch": command_version(["git", "branch", "--show-current"]),
    "commit": head.stdout.strip() if head.returncode == 0 else None,
    "commit_status": "available" if head.returncode == 0 else "unborn_repository",
    "platform": platform.platform(),
    "machine": platform.machine(),
    "python": {
        "actual": platform.python_version(),
        "executable": sys.executable,
        "development_pin": (ROOT / ".python-version").read_text("utf-8").strip(),
        "supported_package_range": ">=3.13,<3.14",
        "patch_versions_other_than_3_13_0": "not_tested",
    },
    "node": command_version([node, "--version"]),
    "npm": command_version([npm, "--version"]),
    "uv": command_version([str(ROOT / ".tools/uv/Scripts/uv.exe"), "--version"]),
    "python_packages": {name: importlib.metadata.version(name) for name in direct_python},
    "jsonschema_date_time": {
        "registered": "date-time" in FormatChecker().checkers,
        "dependency_group": "test",
        "verification_script": "docs/acceptance/D002/verify-date-time.py",
        "root_verification_log": "docs/acceptance/D002/date-time-green.log",
        "snapshot_verification_log": "docs/acceptance/D002/snapshot-date-time.log",
        "production_requirement": "runtime input validation must not depend on this test-only library",
    },
    "node_packages": node_packages,
    "build_backend": {
        "name": "setuptools",
        "pinned": "84.0.0",
        "metadata_source": "https://pypi.org/pypi/setuptools/json",
        "verification": "PyPI metadata lookup and successful isolated editable build",
    },
    "dependency_selection": {
        "method": "exact direct versions checked against upstream registries, then installed",
        "python_sources": [f"https://pypi.org/pypi/{name}/{importlib.metadata.version(name)}/json" for name in direct_python],
        "node_sources": [f"https://registry.npmjs.org/{name}/{version}" for name, version in node_packages.items()],
        "scope": "D002 development baseline; product, GUI and provider compatibility still require their own validation",
    },
    "locks": {
        "services/orchestrator/uv.lock": sha256(ROOT / "services/orchestrator/uv.lock"),
        "package-lock.json": sha256(ROOT / "package-lock.json"),
    },
    "requirements_baseline": {
        "path": requirements_path.relative_to(ROOT).as_posix(),
        "sha256": sha256(requirements_path),
        "version": requirements["requirements_version"],
        "status": requirements["status"],
        "product_acceptance_status": requirements["product_acceptance_status"],
        "requirement_count": len(requirements["requirements"]),
    },
    "real_provider_calls": 0,
    "credential_reads": 0,
    "gui_end_to_end": "not_implemented_or_executed",
    "snapshot": json.loads((ROOT / "docs/acceptance/D002/snapshot-manifest.json").read_text("utf-8-sig")),
}
(ROOT / "docs/acceptance/D002/runtime-versions.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps({"task_id": "D002", "recorded_at": report["recorded_at"], "locks": report["locks"]}))
