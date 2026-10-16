"""D011/D017 review probes using owned temporary workers and directories."""
import ctypes
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from app.runtime.processes import ProcessManager
from app.runtime.workspace import WorkspaceManager,ScopeError
from app.runtime.context_gateway import ContextGateway,ValidatedEnglishView,ProtectedSpan,ContextBlocked

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "tests/integration"))
from test_process_lifecycle import command,alive

results = {}
postfix = "--postfix" in sys.argv
destination = ROOT / ("docs/acceptance/remaining-process-scope-evidence-postfix.json" if postfix
                      else "docs/acceptance/remaining-process-scope-evidence.json")
if destination.exists() and not postfix:
    raise FileExistsError("before evidence is preserved; use --postfix for the author-fix recheck")
def wait_not_alive(pid):
    deadline = time.monotonic()+5
    while alive(pid) and time.monotonic()<deadline:
        time.sleep(0.025)
    assert not alive(pid), "owned test worker remained alive"

with tempfile.TemporaryDirectory(prefix="process-scope-review-") as directory:
    base = Path(directory).resolve()
    normal = base/"normal-unknown"
    normal.mkdir()
    with ProcessManager(normal/"leases.sqlite3") as manager:
        first = manager.start("task1","a1",command(normal,"--exit-code","0"),normal,remote_id="existing-remote",step_id="B.execute")
        previous = manager.wait(first,timeout=8)
        allowed = False
        second_result = None
        reason = None
        try:
            second = manager.start("task1","a1",command(normal,"--exit-code","0"),normal,remote_id="new-remote",step_id="B.retry")
            second_result = asdict(manager.wait(second,timeout=8))
            allowed = True
        except RuntimeError as error:
            reason = str(error)
        results["new_step_after_unknown_normal_exit"] = {"prior":asdict(previous),"new_step_started":allowed,"new_step":second_result,"blocked_reason":reason}
    crash = base/"crashed-service"
    crash.mkdir()
    script = """
import json,os,sys,time
from pathlib import Path
from app.runtime.processes import ProcessManager
root=Path(sys.argv[1])
manager=ProcessManager(root/'leases.sqlite3')
command=[sys.argv[2],sys.argv[3],'--root',str(root),'--ignore-cancel']
handle=manager.start('task2','a1',command,root,remote_id='existing-remote',step_id='B.execute')
(root/'service.json').write_text(json.dumps({'worker_pid':handle.pid,'service_pid':os.getpid()}))
deadline=time.monotonic()+3
while not list(root.glob('worker-*.json')) and time.monotonic()<deadline:
    time.sleep(.02)
os._exit(84)
"""
    environment = {key:value for key,value in os.environ.items() if key.upper() in ProcessManager.ENVIRONMENT_KEYS}
    environment["PYTHONPATH"] = str(ROOT/"services/orchestrator")
    service = subprocess.run([str(Path(sys._base_executable).resolve()),"-c",script,str(crash),str(Path(sys._base_executable).resolve()),
                              str(ROOT/"tests/fixtures/process_worker.py")],cwd=crash,env=environment,capture_output=True,text=True,timeout=8,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    assert service.returncode == 84, service.stderr
    info = json.loads((crash/"service.json").read_text())
    wait_not_alive(info["worker_pid"])
    with ProcessManager(crash/"leases.sqlite3") as manager:
        old = manager.leases.records()[0]
        allowed = False
        reason = None
        try:
            next_step = manager.start("task2","a1",command(crash,"--exit-code","0"),crash,remote_id="new-remote",step_id="B.retry")
            manager.wait(next_step,timeout=8)
            allowed = True
        except RuntimeError as error:
            reason = str(error)
        results["new_step_after_service_crash"] = {"service_exit":service.returncode,"old_worker_alive":alive(info["worker_pid"]),
            "old_local_state":old["local_state"],"old_remote_state":old["remote_state"],"new_step_started":allowed,"blocked_reason":reason}
    failure = base/"monitor-failure"
    failure.mkdir()
    with ProcessManager(failure/"leases.sqlite3") as manager:
        def fail_query(job):
            raise OSError("injected monitor query failure")
        manager._windows.active_processes = fail_query
        handle = manager.start("task3","a1",command(failure,"--exit-code","0"),failure)
        reason = None
        try:
            manager.wait(handle,timeout=8)
        except RuntimeError as error:
            reason = str(error)
        wait_not_alive(handle.pid)
        results["monitor_error_cleanup"] = {"wait_error":reason,"temp_exists":handle.temp_dir.exists(),
            "reported_resources":manager.resource_snapshot(),"ledger_local_state":manager.leases.records()[0]["local_state"]}
    # Cleanup only the precise directory owned by this probe after recording.
    if handle.temp_dir.exists():
        assert handle.temp_dir.resolve().is_relative_to(base)
        shutil.rmtree(handle.temp_dir)
    workspace = WorkspaceManager(base/"workspace").create("task","attempt")
    source = "请保留中文自然语言。".encode("utf-8")
    workspace.ingest_source("source.txt",source)
    workspace.write("service","translation/view.txt",source)
    mutable_spans = []
    digest = hashlib.sha256(source).hexdigest()
    proof = ValidatedEnglishView("input/source.txt",digest,"translation/view.txt",digest,"registered-proof",
        coverage_passed=True,protected_spans_passed=True,numeric_entities_passed=True,protected_spans=mutable_spans)
    gateway = ContextGateway(workspace,{proof.source_ref:proof})
    before = None
    try:
        gateway.read("claude",proof.source_ref)
    except ContextBlocked as error:
        before = str(error)
    mutable_spans.append(ProtectedSpan(0,len(source),0,len(source)))
    after_reason = None
    transmitted = None
    try:
        transmitted = gateway.read("claude",proof.source_ref)
    except ContextBlocked as error:
        after_reason = str(error)
    results["mutable_registered_english_proof"] = {"before_reason":before,
        "after_content":transmitted.content.decode("utf-8") if transmitted is not None else None,
        "after_language":transmitted.language if transmitted is not None else None,"after_reason":after_reason,
        "same_registered_validation_id":proof.validation_id,"protected_spans_runtime_type":type(proof.protected_spans).__name__}

if postfix:
    assert results["new_step_after_unknown_normal_exit"]["new_step_started"] is False
    assert results["new_step_after_unknown_normal_exit"]["blocked_reason"] == "REMOTE_EXECUTION_UNCONFIRMED"
    assert results["new_step_after_service_crash"]["new_step_started"] is False
    assert results["new_step_after_service_crash"]["blocked_reason"] == "REMOTE_EXECUTION_UNCONFIRMED"
    assert results["monitor_error_cleanup"]["temp_exists"] is False
    assert results["monitor_error_cleanup"]["ledger_local_state"] == "cleanup_failed"
    assert results["monitor_error_cleanup"]["reported_resources"]["failed_cleanups"] == 1
    assert results["monitor_error_cleanup"]["reported_resources"]["open_handles"] == 0
    assert results["mutable_registered_english_proof"]["protected_spans_runtime_type"] == "tuple"
    assert results["mutable_registered_english_proof"]["after_content"] is None
    assert results["mutable_registered_english_proof"]["after_reason"] == "NON_ENGLISH_NATURAL_LANGUAGE"

names = ["processes.py","resources.py","leases.py","workspace.py","context_gateway.py"]
output = {"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"isolated local workers/SQLite/files; no provider calls",
    "python":platform.python_version(),"platform":platform.platform(),"interpreter":sys.executable,
    "command":"services/orchestrator/.venv/Scripts/python.exe docs/acceptance/remaining-process-scope-probe.py"+(" --postfix" if postfix else ""),
    "source_hashes":{"services/orchestrator/app/runtime/"+name:hashlib.sha256((ROOT/"services/orchestrator/app/runtime"/name).read_bytes()).hexdigest() for name in names},"results":results}
destination.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(results,ensure_ascii=False))
