"""Final publisher integrity review; only disposable databases change."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.contracts.tasks import contract_digest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tests"))
sys.path.insert(0,str(ROOT/"tests/integration"))
from test_native_publication import prepared
from support.contracts import make_decision

results = {}
postfix = "--postfix" in sys.argv
destination = ROOT/("docs/acceptance/remaining-final-publisher-evidence-postfix.json" if postfix else "docs/acceptance/remaining-final-publisher-evidence.json")
if destination.exists() and not postfix:
    raise FileExistsError("before evidence remains preserved; use --postfix")
with tempfile.TemporaryDirectory(prefix="final-publisher-review-") as directory:
    base = Path(directory)
    for change in ("decision-revision","task-binding","route-binding","canonical-required","pinned-contract-budget"):
        with TestClient(create_app(AppSettings(base/change,"review-local-token","fake",False))) as client:
            client.headers["Authorization"] = "Bearer review-local-token"
            _,conversation,task,attempt,evidence,publisher,machine = prepared.__wrapped__(client)
            with closing(client.app.state.database.connect()) as connection:
                proof = json.loads(connection.execute("SELECT details_json FROM checks WHERE id='a-review'").fetchone()[0])
                checkpoint = json.loads(connection.execute("SELECT checkpoint_json FROM task_runs WHERE task_id=?",(task,)).fetchone()[0])
                checkpoint["task_contract"] = deepcopy(proof["contract"])
                checkpoint["workflow"] = {"contract_sha256":contract_digest(proof["contract"])}
                connection.execute("UPDATE task_runs SET checkpoint_json=? WHERE task_id=?",(json.dumps(checkpoint),task))
            publisher.stage(task,attempt,"1.0","rev1","a-review")
            machine.transition(task,attempt,"OUTPUT_PREPARING","READY","1.0")
            revision = "rev2" if change == "decision-revision" else "rev1"
            if change == "task-binding":
                proof["contract"]["task_id"] = "different-task"
            elif change == "route-binding":
                proof["contract"]["route_snapshot_id"] = "different-route"
            elif change == "canonical-required":
                proof["contract"]["deliverables"][0]["require_a_canonical"] = True
            elif change == "pinned-contract-budget":
                proof["contract"]["budget"] = {"total_tokens":1,"reserved_a_tokens":0}
            proof["decision"] = make_decision(proof["contract"],revision,evidence)
            with closing(client.app.state.database.connect()) as connection:
                connection.execute("UPDATE checks SET details_json=? WHERE id='a-review'",(json.dumps(proof),))
            reason = None
            try:
                publisher.publish(task,attempt,"1.0")
            except ValueError as error:
                reason = str(error)
            messages = client.get(f"/v1/conversations/{conversation}/messages").json()["items"]
            results[change] = {"blocked_reason":reason,"published_answers":sum(item["kind"] == "answer.published" for item in messages),
                              "changed_decision_revision":proof["decision"]["revision_id"],"staged_revision":"rev1"}

names = ["services/orchestrator/app/runtime/publication.py","services/orchestrator/app/runtime/public_projection.py",
         "services/orchestrator/app/contracts/tasks.py","services/orchestrator/app/runtime/workflow.py"]
output = {"generated_at":datetime.now(timezone.utc).isoformat(),"command":"services/orchestrator/.venv/Scripts/python.exe docs/acceptance/remaining-final-publisher-probe.py",
    "mode":"isolated local API/SQLite/evidence; no provider calls","source_hashes":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names},"results":results}
if postfix:
    output["command"] += " --postfix"
    assert all(value["blocked_reason"] and value["published_answers"] == 0 for value in results.values())
destination.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(results))
