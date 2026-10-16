"""Read-only review probes: mutate only disposable fixture databases."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.storage.database import transaction
from app.api.turns import append_event
from app.contracts.tasks import contract_digest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT / "tests"))
sys.path.insert(0,str(ROOT / "tests/integration"))
sys.path.insert(0,str(ROOT / "tests/unit"))
from test_native_publication import prepared
from test_usage_ledger import ledger,record

results = {}
with tempfile.TemporaryDirectory(prefix="root-scope-review-") as directory:
    base = Path(directory)
    def client_for(name):
        return TestClient(create_app(AppSettings(base/name,"review-local-token","fake",False)))
    with client_for("usage") as client:
        client.headers["Authorization"] = "Bearer review-local-token"
        book,task,attempt = ledger.__wrapped__(client)
        record(book,task,attempt,mode="delta",raw={"total_tokens":30},sequence=1,event_id="first")
        record(book,task,attempt,mode="delta",raw={"total_tokens":30},sequence=1,event_id="same-sequence-new-receipt")
        results["duplicate_delta_sequence"] = {"expected_tokens":30,"actual_tokens":book.summary(task)["total_tokens"]}
    with client_for("canonical") as client:
        client.headers["Authorization"] = "Bearer review-local-token"
        _,conversation,task,attempt,evidence,publisher,machine = prepared.__wrapped__(client)
        connection = client.app.state.database.connect()
        proof = json.loads(connection.execute("SELECT details_json FROM checks WHERE id='a-review'").fetchone()[0])
        proof["contract"]["deliverables"][0]["require_a_canonical"] = True
        proof["decision"]["contract_sha256"] = contract_digest(proof["contract"])
        connection.execute("UPDATE checks SET details_json=? WHERE id='a-review'", (json.dumps(proof),))
        actual_author = connection.execute("SELECT canonical_issued_by FROM artifact_revisions WHERE id='rev1'").fetchone()[0]
        connection.close()
        blocked_reason = None
        try:
            publisher.stage(task,attempt,"1.0","rev1","a-review")
            machine.transition(task,attempt,"OUTPUT_PREPARING","READY","1.0")
            publisher.publish(task,attempt,"1.0")
        except ValueError as error:
            blocked_reason = str(error)
        messages = client.get(f"/v1/conversations/{conversation}/messages").json()["items"]
        results["canonical_claim_vs_artifact"] = {"requires_a_canonical":True,"decision_author":proof["decision"]["canonical_author"],
            "artifact_author":actual_author,"published_answers":sum(item["kind"] == "answer.published" for item in messages),"blocked_reason":blocked_reason}
    with client_for("duplicate-answer") as client:
        client.headers["Authorization"] = "Bearer review-local-token"
        _,conversation,task,attempt,evidence,publisher,machine = prepared.__wrapped__(client)
        publisher.stage(task,attempt,"1.0","rev1","a-review")
        machine.transition(task,attempt,"OUTPUT_PREPARING","READY","1.0")
        connection = client.app.state.database.connect()
        row = connection.execute("SELECT * FROM task_runs WHERE task_id=?", (task,)).fetchone()
        with transaction(connection):
            append_event(connection,row["turn_id"],task,attempt,"answer.published",{"text":"FORGED","approval_id":"invented"})
        connection.close()
        before = client.get(f"/v1/conversations/{conversation}/messages").json()["items"]
        publisher.publish(task,attempt,"1.0")
        after = client.get(f"/v1/conversations/{conversation}/messages").json()["items"]
        results["forged_event_later_authorized"] = {"before_answer_count":sum(item["kind"] == "answer.published" for item in before),
            "after_answer_count":sum(item["kind"] == "answer.published" for item in after),
            "after_answer_ids":[item["id"] for item in after if item["kind"] == "answer.published"],
            "forged_text_leaked":any("FORGED" in item["text"] for item in after)}
    with client_for("historical") as client:
        client.headers["Authorization"] = "Bearer review-local-token"
        _,conversation,task,attempt,evidence,publisher,machine = prepared.__wrapped__(client)
        publisher.stage(task,attempt,"1.0","rev1","a-review")
        machine.transition(task,attempt,"OUTPUT_PREPARING","READY","1.0")
        publisher.publish(task,attempt,"1.0")
        before = client.get(f"/v1/conversations/{conversation}/messages").json()["items"]
        connection = client.app.state.database.connect()
        row = connection.execute("SELECT * FROM task_runs WHERE task_id=?", (task,)).fetchone()
        connection.execute("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,attempt_number) VALUES(?,?,?,?,?,2)",
                           (task,"new-attempt",row["turn_id"],row["provider_profile_id"],"RECEIVED"))
        connection.close()
        after = client.get(f"/v1/conversations/{conversation}/messages").json()["items"]
        results["historical_answer_after_new_attempt"] = {"before_answer_count":sum(item["kind"] == "answer.published" for item in before),
            "after_answer_count":sum(item["kind"] == "answer.published" for item in after)}
sources = ["services/orchestrator/app/runtime/publication.py","services/orchestrator/app/runtime/public_projection.py",
           "services/orchestrator/app/usage/ledger.py","services/orchestrator/app/contracts/tasks.py"]
output = {"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"isolated local probes; production files read-only",
          "command":"services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D012/review_root_scope.py",
          "source_hashes":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources},"results":results}
assert results["duplicate_delta_sequence"]["actual_tokens"] == 30
assert results["canonical_claim_vs_artifact"]["published_answers"] == 0 and results["canonical_claim_vs_artifact"]["blocked_reason"]
assert results["forged_event_later_authorized"]["after_answer_count"] == 1
assert results["historical_answer_after_new_attempt"]["after_answer_count"] == 1
(ROOT/"docs/acceptance/remaining-review-runtime-evidence-fixed.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(results,ensure_ascii=False))
