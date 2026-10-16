"""Replay accepted-stream safety with actual local API/SQLite and external fixtures."""
import asyncio
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys
import tempfile

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.contracts.events import AgentEvent
from app.providers.fake import FakeProvider
from app.runtime.workflow import Workflow
from app.storage.database import Database
from app.usage.budgets import check_budget
from app.usage.ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("stream_fixture", ROOT / "tests/integration/test_agent_workflow.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


class NoIds:
    test_only = True
    def __init__(self):
        self.starts = []
    async def run(self, request):
        self.starts.append(request)
        yield AgentEvent(request.task_id, request.attempt_id, 1, "provider.started", {})
    async def cancel(self, task_id, attempt_id):
        pass


class CompletedFixture(FakeProvider):
    async def run(self, request):
        invocation = Path(request.prompt_path).stem
        yield AgentEvent(request.task_id, request.attempt_id, 1, "provider.started",
            {"external_request_id": "remote-request-" + invocation,
             "external_execution_id": "remote-execution-" + invocation})
        async for event in super().run(request):
            yield AgentEvent(event.task_id, event.attempt_id, event.sequence + 1,
                "provider.completed" if event.kind == "model.completed" else event.kind,
                {"reason_code": "CAPTURE_VERIFIED", "exit_code": 0}
                if event.kind == "model.completed" else event.payload)


def run():
    sources = ["services/orchestrator/app/runtime/workflow.py", "tests/integration/test_agent_workflow.py",
        "services/orchestrator/app/providers/fake.py", "docs/acceptance/D014/verify-stream.py"]
    evidence = {"at_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "python": sys.version, "mode": "actual local API/SQLite, synthetic external event streams",
        "real_model_calls": 0, "command": "services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D014/verify-stream.py",
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}, "scenarios": []}
    cases = [("accepted_disconnect", None), ("terminal_failed", "FAILED"), ("terminal_published", "PUBLISHED"),
        ("claude_b_original_context", None), ("missing_ids_cancel", None), ("provider_completed_success", None)]
    with tempfile.TemporaryDirectory(prefix="D014-stream-acceptance-") as temporary:
        for name, terminal in cases:
            with TestClient(create_app(AppSettings(Path(temporary) / name, "fixture-local-token", "fake", False))) as client:
                client.headers["Authorization"] = "Bearer fixture-local-token"
                path, manager, workspace, contract = helpers.prepare(client)
                profiles = {"A": "fake-gpt", "B": "fake-glm"}
                a = FakeProvider()
                if name == "claude_b_original_context":
                    with closing(Database(path).connect()) as connection:
                        connection.execute("""INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,
                            identity_status,connection_version) VALUES('fake-claude','fake','fixture-claude','claude',
                            'fake-claude','unknown','test-only')""")
                    profiles["B"] = "fake-claude"
                    b = FakeProvider(executions=helpers.CASES["pass"]["executions"])
                elif name == "missing_ids_cancel":
                    b = NoIds()
                elif name == "provider_completed_success":
                    b = CompletedFixture(executions=helpers.CASES["pass"]["executions"])
                    a = CompletedFixture(reviews=helpers.CASES["pass"]["reviews"])
                else:
                    b = helpers.AcceptedStreamFailure(path, terminal_state=terminal)
                workflow = Workflow(path, manager, b, helpers.validator, a, check_budget,
                    estimated_tokens={"B.execution": 64, "A.review": 64}, profile_ids=profiles)
                result = asyncio.run(workflow.run(contract))
                if terminal:
                    assert result.state == terminal and result.connection_retries == 0 and len(b.starts) == 1
                elif name == "provider_completed_success":
                    assert result.state == "OUTPUT_PREPARING" and len(b.starts) == len(a.starts) == 1
                else:
                    assert result.state == "BLOCKED" and result.connection_retries == 0 and a.starts == []
                if name == "claude_b_original_context":
                    assert b.starts == [] and not list(workspace.area("b").rglob("prompts/*.json"))
                elif name == "missing_ids_cancel":
                    assert client.post(f"/v1/tasks/{contract['task_id']}/cancel").status_code == 202
                elif name != "provider_completed_success":
                    assert len(b.starts) == 1
                with closing(Database(path).connect()) as connection:
                    task = dict(connection.execute("SELECT * FROM task_runs").fetchone())
                    steps = [dict(row) for row in connection.execute("SELECT * FROM steps")]
                    artifacts = [dict(row) for row in connection.execute("SELECT * FROM artifact_revisions")]
                    checks = [dict(row) for row in connection.execute("SELECT * FROM checks")]
                if name == "missing_ids_cancel":
                    assert task["cancel_pending_remote"] == 1 and task["external_stop_confirmed"] is None
                    assert task["external_request_id"] is task["external_execution_id"] is None
                evidence["scenarios"].append({"name": name, "result": asdict(result), "task": task,
                    "steps": steps, "artifacts": artifacts, "checks": checks, "B_starts": len(b.starts), "A_starts": len(a.starts),
                    "observed_before_disconnect": getattr(b, "observed_after_started", []),
                    "usage": UsageLedger(path).summary(contract["task_id"])})
    evidence["exit_code"] = 0
    (OUTPUT / "stream-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stream_scenarios": len(cases), "exit_code": 0}))


if __name__ == "__main__":
    run()
