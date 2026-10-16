import json
import subprocess
import sys
from pathlib import Path
import pytest

@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.application import create_app
    from app.config import AppSettings
    with TestClient(create_app(AppSettings(tmp_path, "qa-local-token", "fake", False))) as value:
        value.headers["Authorization"] = "Bearer qa-local-token"
        yield value

@pytest.fixture
def probe(tmp_path):
    roots = []
    def run(name, **options):
        run_root = tmp_path / f'case-{len(roots):03d}'
        run_root.mkdir()
        roots.append(run_root)
        result = subprocess.run([sys.executable, "tests/support/scenario_driver.py", name, "--root", str(run_root), "--options", json.dumps(options)], check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if result.returncode:
            raise AssertionError(f"Scenario exited {result.returncode}: {result.stderr[-6000:]}")
        return json.loads(result.stdout)
    return run
