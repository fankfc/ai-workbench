"""Replay the actual service workflow. Only the external provider is fake."""
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
from app.storage.database import Database
from app.usage.ledger import UsageLedger

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("d014_fixtures", ROOT / "tests/integration/test_agent_workflow.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def run():
    metadata = {"at_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "python": sys.version, "provider_mode": "fake external responses only", "real_model_calls": 0,
        "mechanical_check": "actual ast.parse of immutable candidate bytes; not a mocked result",
        "command": "services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D014/verify.py",
        "source_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [ROOT / "services/orchestrator/app/runtime/workflow.py",
                         ROOT / "services/orchestrator/app/runtime/repair.py",
                         ROOT / "services/orchestrator/app/providers/fake.py",
                         ROOT / "tests/integration/test_agent_workflow.py", ROOT / "tests/fixtures/workflow_cases.json"]}}
    traces = {**metadata, "scenarios": []}
    repairs = {**metadata, "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="D014-acceptance-") as directory:
        base = Path(directory)
        scenarios = [
            ("pass", "pass", None, "OUTPUT_PREPARING"),
            ("repair", "repair", None, "OUTPUT_PREPARING"),
            ("no_progress_takeover", "no_progress", None, "OUTPUT_PREPARING"),
            ("missing_candidate", "pass", {"executions": [{"reported_complete": True, "usage": {"input_tokens": 1, "output_tokens": 1}}]}, "BLOCKED"),
            ("mechanical_fail_a_claims_pass", "pass", {"executions": [{"text": "FAIL 假称完美", "usage": {"input_tokens": 1, "output_tokens": 1}}], "reviews": [{"decision": "PASS", "criterion_results": {"AC1": True, "AC2": True}, "usage": {"input_tokens": 1, "output_tokens": 1}}]}, "BLOCKED"),
            ("need_evidence", "pass", {**helpers.CASES["pass"], "reviews": [{"decision": "NEED_EVIDENCE", "issues": ["evidence gap"], "usage": {"input_tokens": 1, "output_tokens": 1}}]}, "NEEDS_INPUT"),
            ("a_blocked", "pass", {**helpers.CASES["pass"], "reviews": [{"decision": "BLOCKED", "issues": ["missing capability"], "usage": {"input_tokens": 1, "output_tokens": 1}}]}, "BLOCKED"),
            ("unknown_usage", "pass", {"executions": [{"text": "候选", "usage": None}], "reviews": helpers.CASES["pass"]["reviews"]}, "BLOCKED"),
            ("budget_missing", "pass", None, "BLOCKED"),
            ("cancel_late", "pass", None, "CANCELLED"),
            ("claude_formal_gates_missing", "pass", None, "BLOCKED"),
            ("connection_retry", "pass", {"executions": [{"connection_error": True, "usage": {"input_tokens": 1, "output_tokens": 0}}, helpers.CASES["pass"]["executions"][0]], "reviews": helpers.CASES["pass"]["reviews"]}, "OUTPUT_PREPARING"),
        ]
        for name, case, override, state in scenarios:
            with TestClient(create_app(AppSettings(base / name, "fixture-local-token", "fake", False))) as client:
                client.headers["Authorization"] = "Bearer fixture-local-token"
                prepared = helpers.prepare(client)
                if name == "claude_formal_gates_missing":
                    prepared[3]["model_family"] = "claude"
                on_start = (lambda request: client.post(f"/v1/tasks/{request.task_id}/cancel")) if name == "cancel_late" else None
                parameters = {"override": override, "on_start": on_start}
                if name == "budget_missing":
                    parameters["budget"] = None
                result, b, a = helpers.execute(prepared, case, **parameters)
                assert result.state == state
                with closing(Database(prepared[0]).connect()) as connection:
                    task = dict(connection.execute("SELECT * FROM task_runs").fetchone())
                    checkpoint = json.loads(task["checkpoint_json"])
                    candidates = [dict(row) for row in connection.execute("SELECT * FROM artifact_revisions")]
                    checks = [dict(row) for row in connection.execute("SELECT * FROM checks")]
                    steps = [dict(row) for row in connection.execute("SELECT * FROM steps")]
                    published = connection.execute("SELECT COUNT(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0]
                    assert published == 0
                trace = {"name": name, "result": asdict(result), "B_model_starts": len(b.starts),
                    "A_model_starts": len(a.starts), "candidate_revisions": candidates,
                    "checks": checks, "steps": steps, "task_checkpoint": checkpoint,
                    "usage": UsageLedger(prepared[0]).summary(prepared[3]["task_id"]),
                    "public_answer_events": published, "final_lease_snapshot": prepared[2].lease_snapshot()}
                traces["scenarios"].append(trace)
                if checkpoint.get("workflow", {}).get("repair", {}).get("history") or result.connection_retries:
                    repairs["scenarios"].append({"name": name, "result": asdict(result),
                        "repair": checkpoint["workflow"]["repair"], "takeover_leases": checkpoint["workflow"]["takeover_leases"],
                        "candidate_history": checkpoint["workflow"]["candidate_history"]})
    traces["exit_code"] = repairs["exit_code"] = 0
    for filename, value in [("workflow-traces.json", traces), ("repair-evidence.json", repairs)]:
        (OUTPUT / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"workflow_scenarios": len(traces["scenarios"]), "repair_scenarios": len(repairs["scenarios"]), "exit_code": 0}))


if __name__ == "__main__":
    run()
