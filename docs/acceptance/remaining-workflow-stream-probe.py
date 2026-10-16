"""Cross-port workflow safety probes; external execution is a local fixture."""
import asyncio
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.providers.fake import FakeProvider
from app.contracts.events import AgentEvent
from app.runtime.workflow import Workflow
from app.usage.budgets import check_budget

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tests"))
sys.path.insert(0,str(ROOT/"tests/integration"))
from test_agent_workflow import prepare,validator,CASES

results = {}
postfix = "--postfix" in sys.argv
destination = ROOT/("docs/acceptance/remaining-workflow-stream-evidence-postfix.json" if postfix else "docs/acceptance/remaining-workflow-stream-evidence.json")
if destination.exists() and not postfix:
    raise FileExistsError("before evidence is preserved; use --postfix")
with tempfile.TemporaryDirectory(prefix="workflow-stream-review-") as directory:
    base = Path(directory)
    with TestClient(create_app(AppSettings(base/"claude-b","review-local-token","fake",False))) as client:
        client.headers["Authorization"] = "Bearer review-local-token"
        path,manager,workspace,contract = prepare(client)
        with closing(client.app.state.database.connect()) as connection:
            connection.execute("""INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,connection_version)
                VALUES('fake-claude','fake','fixture-claude','claude','fake-claude','unknown','test-only')""")
        b = FakeProvider(executions=CASES["pass"]["executions"])
        a = FakeProvider(reviews=CASES["pass"]["reviews"])
        workflow = Workflow(path,manager,b,validator,a,check_budget,estimated_tokens={"B.execution":64,"A.review":64},
                            profile_ids={"A":"fake-gpt","B":"fake-claude"})
        outcome = asyncio.run(workflow.run(contract))
        results["claude_b_original_context"] = {"state":outcome.state,"b_starts":len(b.starts),"reason_codes":outcome.reason_codes,
            "request_family":b.starts[0].identity.family.value if b.starts else None,
            "chinese_source_in_prompt":"实际来源字节" in Path(b.starts[0].prompt_path).read_text(encoding="utf-8") if b.starts else False}
    for terminate in (False,True):
        with TestClient(create_app(AppSettings(base/("terminal" if terminate else "unknown-remote"),"review-local-token","fake",False))) as client:
            client.headers["Authorization"] = "Bearer review-local-token"
            path,manager,workspace,contract = prepare(client)
            class StreamingFailure:
                test_only = True
                def __init__(self):
                    self.starts = []
                async def run(self,request):
                    self.starts.append(request)
                    yield AgentEvent(request.task_id,request.attempt_id,1,"provider.started",
                        {"external_request_id":"ongoing-request","external_execution_id":"ongoing-execution"})
                    yield AgentEvent(request.task_id,request.attempt_id,2,"provider.usage",
                        {"raw":{"input_tokens":10,"output_tokens":5},"source":"reported"})
                    if terminate:
                        with closing(client.app.state.database.connect()) as connection:
                            connection.execute("UPDATE task_runs SET state='FAILED' WHERE task_id=?",(request.task_id,))
                    raise ConnectionError("remote observation lost after request acceptance")
                async def cancel(self,task_id,attempt_id):
                    pass
            b = StreamingFailure()
            a = FakeProvider()
            workflow = Workflow(path,manager,b,validator,a,check_budget,estimated_tokens={"B.execution":64,"A.review":64})
            outcome = asyncio.run(workflow.run(contract))
            with closing(client.app.state.database.connect()) as connection:
                row = dict(connection.execute("SELECT * FROM task_runs WHERE task_id=?",(contract["task_id"],)).fetchone())
                steps = [dict(item) for item in connection.execute("SELECT * FROM steps ORDER BY created_at,id")]
            results["terminal_after_start" if terminate else "remote_unknown_after_start"] = {"state":outcome.state,"b_starts":len(b.starts),
                "reason_codes":outcome.reason_codes,"task_external_request_id":row["external_request_id"],
                "task_external_execution_id":row["external_execution_id"],"step_external_execution_ids":[item["external_execution_id"] for item in steps],
                "active_external_request":json.loads(row["checkpoint_json"]).get("active_external_request"),
                "step_remote_executions":[json.loads(item["checkpoint_json"]).get("remote_execution") for item in steps]}

if postfix:
    assert results["claude_b_original_context"]["b_starts"] == 0
    assert not results["claude_b_original_context"]["chinese_source_in_prompt"]
    assert results["remote_unknown_after_start"]["b_starts"] == 1
    assert results["remote_unknown_after_start"]["state"] == "BLOCKED"
    assert results["remote_unknown_after_start"]["step_external_execution_ids"] == ["ongoing-execution"]
    assert results["remote_unknown_after_start"]["active_external_request"] == results["remote_unknown_after_start"]["step_remote_executions"][0]
    assert results["terminal_after_start"]["b_starts"] == 1 and results["terminal_after_start"]["state"] == "FAILED"

names = ["services/orchestrator/app/runtime/workflow.py","services/orchestrator/app/runtime/repair.py","services/orchestrator/app/providers/fake.py"]
output = {"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"temporary local API/SQLite and synthetic external event stream",
    "command":"services/orchestrator/.venv/Scripts/python.exe docs/acceptance/remaining-workflow-stream-probe.py"+(" --postfix" if postfix else ""),
    "source_hashes":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names},"results":results}
destination.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(results))
