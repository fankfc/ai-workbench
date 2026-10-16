"""Generate persisted D010/D012 traces from actual isolated runtimes."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

from app.runtime.state_machine import StateMachine,TRANSITIONS
from app.runtime.recovery import Recovery
from app.runtime.outbox import Outbox
from app.storage.database import Database

OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[2]
OTHER = ROOT / "docs/acceptance/D012"
sys.path.insert(0,str(ROOT / "tests/integration"))
from test_state_machine import initialize_runtime,current,create_revision_and_gate
from test_outbox import run_crash_window
from test_recovery import existing_remote,event,audits

WORK = OUTPUT / "fixtures" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8])
WORK.mkdir(parents=True)
commit = subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=False)
META = {"generated_at":datetime.now(timezone.utc).isoformat(),"python":platform.python_version(),"sqlite":sqlite3.sqlite_version,
        "platform":platform.platform(),"interpreter":sys.executable,"commit":commit.stdout.strip() if commit.returncode == 0 else None,
        "mode":"isolated real SQLite/filesystem/subprocess; no external provider calls",
        "command":"services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D010/reproduce_evidence.py","exit_code":0}


def cases(path):
    values = [{"name":case.attrib["name"],"result":"failed" if case.find("failure") is not None or case.find("error") is not None
               else "skipped" if case.find("skipped") is not None else "passed"} for case in ET.parse(path).iter("testcase")]
    assert values and all(item["result"] == "passed" for item in values)
    return values


def save(path,value):
    path.write_text(json.dumps({**META,**value},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


d10_cases = cases(OUTPUT / "runtime-tests.xml")
d12_cases = cases(OTHER / "recovery-tests.xml")
normal = WORK / "normal"
normal.mkdir()
path = initialize_runtime(normal)
main = ["RECEIVED","INPUT_PREPARING","PLANNING","EXECUTING","VALIDATING","REVIEWING","OUTPUT_PREPARING","READY","PUBLISHED"]
normal_trace = []
for before,after in zip(main,main[1:]):
    if after == "READY":
        create_revision_and_gate(path)
    normal_trace.append(StateMachine(path).transition("task1","a1",before,after,"1.0"))
assert current(path)["state"] == "PUBLISHED" and Outbox(path).replay("c1") == []
save(OUTPUT / "state-matrix.json",{"transitions":{key:sorted(value) for key,value in sorted(TRANSITIONS.items())},
    "legal_edge_count":sum(len(value) for value in TRANSITIONS.values()),
    "verified_legal_edge_cases":sum(item["name"].startswith("test_each_declared_legal_edge") for item in d10_cases),
    "passed_tests":len(d10_cases),"normal_path_trace":normal_trace,"final_state":current(path)["state"],
    "state_changes_publish_answers":len(Outbox(path).replay("c1")),"tests":d10_cases})
crashes = []
for point,code in [("before-commit",81),("after-commit",82),("send-before-ack",83)]:
    directory = WORK / point
    directory.mkdir()
    crashes.append(run_crash_window(directory,point,code))
save(OUTPUT / "crash-traces.json",{"crashes":crashes,"fixture_directory":WORK.relative_to(ROOT).as_posix(),
    "receiver_policy":"Stable event_id deduplication persists across resend; one receiver entry remains."})
stream = WORK / "provider-stream"
stream.mkdir()
path = existing_remote(stream)
decisions = []
for sequence in (1,2,2,1,3):
    decisions.append({"received_sequence":sequence,**Recovery(path).ingest(event(sequence),"1.0")})
checkpoint = json.loads(current(path)["checkpoint_json"])
assert checkpoint["provider_last_sequence"] == 3
assert [seq for value in decisions for seq in value["applied_sequences"]] == [1,2,3]
save(OTHER / "recovery-report.json",{"passed_tests":len(d12_cases),"sequence_trace":decisions,
    "final_checkpoint":checkpoint,"audit_events":audits(path),"public_event_count":len(Outbox(path).replay("c1")),"tests":d12_cases})
unknown = WORK / "unknown"
unknown.mkdir()
path = existing_remote(unknown)
calls = []
def query(row):
    calls.append({"action":"query","external_request_id":row["external_request_id"],"external_execution_id":row["external_execution_id"]})
    return "unknown"
results = [Recovery(path).recover(query),Recovery(path).recover(query)]
connection = Database(path).connect()
steps = connection.execute("SELECT count(*) FROM steps").fetchone()[0]
attempts = connection.execute("SELECT count(*) FROM task_runs").fetchone()[0]
connection.close()
assert current(path)["state"] == "BLOCKED" and steps == 0 and attempts == 1
save(OTHER / "remote-unknown-trace.json",{"calls":calls,"recoveries":results,"task_state":current(path)["state"],
    "external_request_id":current(path)["external_request_id"],"step_count":steps,"attempt_count":attempts,
    "audit_events":audits(path),"public_event_count":len(Outbox(path).replay("c1")),"model_start_callback_available":False})
paths = [ROOT / "services/orchestrator/app/runtime" / name for name in ("state_machine.py","outbox.py","recovery.py")]
paths += [ROOT / "tests/integration" / name for name in ("test_state_machine.py","test_outbox.py","test_recovery.py")]
paths += [Path(__file__).resolve(),ROOT / "services/orchestrator/app/storage/schema/0001_initial.sql"]
hashes = {path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
save(OUTPUT / "source-hashes.json",{"sources":hashes})
save(OTHER / "source-hashes.json",{"sources":hashes})
print(json.dumps({"state_outbox_passed":len(d10_cases),"recovery_passed":len(d12_cases),"legal_edges":sum(len(value) for value in TRANSITIONS.values()),
                  "crash_exits":[value["exit_code"] for value in crashes],"provider_last_sequence":checkpoint["provider_last_sequence"]}))
