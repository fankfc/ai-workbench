"""Local work orders bind real evidence without changing the frozen task board."""
import copy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


@pytest.fixture
def work_orders():
    if importlib.util.find_spec("app.contracts.work_orders") is None:
        class MissingImplementation:
            def __getattr__(self, name):
                raise AssertionError("work-order implementation is required")
        return MissingImplementation()
    return importlib.import_module("app.contracts.work_orders")


def put(root, ref, content):
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    plan = "docs/superpowers/plans/2026-10-13-execution"
    dependency = {"id": "D001", "status": "blocked", "requires": ["D999"],
                  "deliverables": ["inputs/direct.txt", "inputs/missing.txt"], "evidence": []}
    task = {"id": "D028", "title": "Translate input", "status": "in_progress",
            "requires": ["D001"], "requirements": ["R07"], "guide": "guide.md",
            "deliverables": ["src/allowed.py"], "evidence": ["qa/result.txt"],
            "test_commands": ["never execute this source string"], "freeze": {"status": "frozen_partial"}}
    put(tmp_path, plan + "/task-board.json", json.dumps({"schema_version": "1.0", "tasks": [dependency, task]}))
    put(tmp_path, plan + "/data/tasks-02.json", json.dumps([dependency, task]))
    put(tmp_path, plan + "/guide.md", "### D028: Translate input\n- [ ] Preserve all text\n- [ ] Run negative case\n### D029: unrelated secret\nDo not include me\n")
    put(tmp_path, "inputs/direct.txt", "direct dependency")
    put(tmp_path, "src/allowed.py", "before\n")
    put(tmp_path, "src/unrelated.py", "unrelated\n")
    return tmp_path


def draft(work_orders, repo):
    return work_orders.draft_work_order(repo, "D028", "1", ["src/allowed.py"], "out/draft")


def record(work_orders, repo, order, rc=0):
    put(repo, "qa/result.txt", "measured result")
    return work_orders.record_command(repo, "out/draft/work-order.json",
        [sys.executable, "-c", f"print('actual execution'); raise SystemExit({rc})"],
        ["qa/result.txt"], "out/run")


def handoff(work_orders, repo, rc=0):
    order = draft(work_orders, repo)
    put(repo, "src/allowed.py", "after\n")
    record(work_orders, repo, order, rc)
    value = work_orders.create_handoff(repo, "out/draft/work-order.json", ["out/run/record.json"],
        ["src/allowed.py"], "out/handoff")
    return value


def test_exact_card_full_actions_and_only_direct_artifact_context(work_orders, repo):
    before = (repo / work_orders.BOARD_REF).read_bytes()
    value = draft(work_orders, repo)
    assert value["task_id"] == "D028" and value["contract_version"] == "1"
    assert value["card"]["freeze"] == {"status": "frozen_partial"}
    assert value["data_card"]["test_commands"] == ["never execute this source string"]
    assert "Preserve all text" in value["card_actions"] and "D029" not in value["card_actions"]
    assert [item["task_id"] for item in value["dependencies"]] == ["D001"]
    artifact = value["dependencies"][0]["artifacts"][0]
    assert artifact["sha256"] == hashlib.sha256(b"direct dependency").hexdigest()
    assert {item["code"] for item in value["blockers"]} >= {"DEPENDENCY_NOT_DONE", "DEPENDENCY_ARTIFACT_MISSING"}
    assert "D999" not in json.dumps(value)
    assert (repo / work_orders.BOARD_REF).read_bytes() == before


@pytest.mark.parametrize("task_id", ["D02", "D999", "D028;whoami"])
def test_task_id_must_match_exactly(work_orders, repo, task_id):
    with pytest.raises(ValueError):
        work_orders.draft_work_order(repo, task_id, "1", ["src/allowed.py"], "out/order")


@pytest.mark.parametrize("ref", ["../escape", "/absolute", "C:/escape", "src/../unrelated.py", "src/allowed.py:stream", "src/%2e%2e"])
def test_traversal_and_ambiguous_scopes_are_rejected(work_orders, repo, ref):
    with pytest.raises((ValueError, PermissionError)):
        work_orders.draft_work_order(repo, "D028", "1", [ref], "out/order")


def test_fresh_output_never_overwrites(work_orders, repo):
    draft(work_orders, repo)
    with pytest.raises(FileExistsError):
        draft(work_orders, repo)


def test_record_measures_real_process_exit_and_does_not_parse_shell(work_orders, repo):
    order = draft(work_orders, repo)
    value = record(work_orders, repo, order, rc=7)
    assert value["exit_code"] == 7 and value["result_source"] == "actual_process_exit_and_test_report"
    assert "actual execution" in (repo / value["log_ref"]).read_text(encoding="utf-8")
    assert value["evidence"][0]["sha256"] == hashlib.sha256(b"measured result").hexdigest()
    literal = work_orders.record_command(repo, "out/draft/work-order.json",
        [sys.executable, "-c", "import sys; print(sys.argv[1])", "$(echo injected); & whoami"], [], "out/literal")
    assert (repo / literal["log_ref"]).read_text(encoding="utf-8").strip() == "$(echo injected); & whoami"


def test_handoff_accepts_measured_local_checks_without_finishing_task(work_orders, repo):
    value = handoff(work_orders, repo)
    result = work_orders.validate_handoff(repo, "out/draft/work-order.json", "out/handoff/handoff.json")
    assert result["local_handoff_accepted"] is True and result["task_completion_changed"] is False
    assert value["status"] == "in_review" and value["review_requested"] is True
    assert result["dependency_blockers"]
    assert json.loads((repo / work_orders.BOARD_REF).read_text())["tasks"][1]["status"] == "in_progress"


@pytest.mark.parametrize("change", ["task", "version", "scope", "evidence", "missing_evidence", "log", "record", "revision", "fabricated_pass"])
def test_handoff_rejects_wrong_binding_missing_stale_or_fabricated_evidence(work_orders, repo, change):
    value = handoff(work_orders, repo)
    if change in {"task", "version", "scope", "fabricated_pass"}:
        if change == "task": value["task_id"] = "D029"
        if change == "version": value["contract_version"] = "2"
        if change == "scope": value["changed_files"] = ["src/unrelated.py"]
        if change == "fabricated_pass": value["verification"] = [{"command": "imaginary", "result": "PASS"}]
        put(repo, "out/handoff/handoff.json", json.dumps(value))
    elif change == "evidence": put(repo, "qa/result.txt", "changed after run")
    elif change == "missing_evidence": (repo / "qa/result.txt").unlink()
    elif change == "log": put(repo, "out/run/process.log", "PASS")
    elif change == "record":
        record_value = json.loads((repo / "out/run/record.json").read_text())
        record_value["exit_code"] = 0
        record_value["argv"] = ["fake"]
        put(repo, "out/run/record.json", json.dumps(record_value))
    elif change == "revision": put(repo, "src/allowed.py", "not the revision tested")
    with pytest.raises((ValueError, PermissionError, FileNotFoundError)):
        work_orders.validate_handoff(repo, "out/draft/work-order.json", "out/handoff/handoff.json")


def test_real_nonzero_exit_never_becomes_accepted_handoff(work_orders, repo):
    handoff(work_orders, repo, rc=9)
    with pytest.raises(ValueError, match="CHECK_FAILED"):
        work_orders.validate_handoff(repo, "out/draft/work-order.json", "out/handoff/handoff.json")


def test_handoff_declared_files_must_match_observed_allowlist_changes(work_orders, repo):
    order = draft(work_orders, repo)
    put(repo, "src/allowed.py", "modified")
    record(work_orders, repo, order)
    with pytest.raises(ValueError, match="CHANGED_FILES_MISMATCH"):
        work_orders.create_handoff(repo, "out/draft/work-order.json", ["out/run/record.json"], [], "out/handoff")


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_linked_repository_artifacts_are_denied(work_orders, repo, kind):
    target = repo / "src/alias.py"
    try:
        os.symlink(repo / "src/allowed.py", target) if kind == "symlink" else os.link(repo / "src/allowed.py", target)
    except OSError:
        pytest.skip("host cannot create this link")
    with pytest.raises(PermissionError):
        work_orders.draft_work_order(repo, "D028", "1", ["src/alias.py"], "out/order")


def test_source_data_cannot_expand_trusted_allowlist(work_orders, repo):
    value = draft(work_orders, repo)
    value["allowed_files"].append("src/unrelated.py")
    put(repo, "out/draft/work-order.json", json.dumps(value))
    with pytest.raises(ValueError, match="AUTHENTICATION"):
        record(work_orders, repo, value)


@pytest.mark.skipif(os.name != "nt", reason="Windows file identity is case insensitive")
@pytest.mark.parametrize("protected", ["board", "key", "data"])
def test_windows_case_aliases_cannot_authorize_protected_files(work_orders, repo, protected):
    ref = {"board": work_orders.BOARD_REF, "key": work_orders.KEY_REF,
           "data": work_orders.PLAN_REF + "/data/tasks-02.json"}[protected]
    with pytest.raises(ValueError, match="EXACT_IMPLEMENTATION_FILE_SCOPE_REQUIRED"):
        work_orders.draft_work_order(repo, "D028", "1", [ref.upper()], "out/draft")


@pytest.mark.skipif(os.name != "nt", reason="Windows file identity is case insensitive")
def test_windows_scope_aliases_are_one_file_identity(work_orders, repo):
    with pytest.raises(ValueError, match="DUPLICATE_FILE_SCOPE"):
        work_orders.draft_work_order(repo, "D028", "1", ["src/allowed.py", "SRC/ALLOWED.PY"], "out/draft")


@pytest.mark.skipif(os.name != "nt", reason="Windows file identity is case insensitive")
def test_windows_handoff_scope_comparison_uses_actual_file_identity(work_orders, repo):
    order = draft(work_orders, repo)
    put(repo, "src/allowed.py", "changed")
    record(work_orders, repo, order)
    value = work_orders.create_handoff(repo, "out/draft/work-order.json", ["out/run/record.json"],
        ["SRC/ALLOWED.PY"], "out/handoff")
    assert value["changed_files"] == ["src/allowed.py"]
    assert work_orders.validate_handoff(repo, "out/draft/work-order.json", "out/handoff/handoff.json")["local_handoff_accepted"]


@pytest.mark.skipif(os.name != "nt", reason="Windows file identity is case insensitive")
def test_windows_record_aliases_cannot_count_one_execution_twice(work_orders, repo):
    order = draft(work_orders, repo)
    record(work_orders, repo, order)
    with pytest.raises(ValueError, match="UNIQUE_MEASURED_COMMAND_RECORDS_REQUIRED"):
        work_orders.create_handoff(repo, "out/draft/work-order.json", ["out/run/record.json", "OUT/RUN/RECORD.JSON"],
            [], "out/handoff")


@pytest.mark.skipif(os.name != "nt", reason="Windows file identity is case insensitive")
def test_windows_repair_subset_uses_actual_file_identity(work_orders, repo):
    draft(work_orders, repo)
    value = work_orders.create_report(repo, "out/draft/work-order.json", "repair", {
        "artifact_version": "current", "defects": [{"defect_id": "DEF-1", "requirement_id": "R07",
            "location": "src/allowed.py", "impact": "Missing text", "failure_evidence": ["inputs/direct.txt"],
            "allowed_files": ["SRC/ALLOWED.PY"], "pass_condition": "Preserve source",
            "rerun_checks": [[sys.executable, "-c", "print('check')"]]}]}, "out/report")
    assert value["revision"][0]["ref"] == "src/allowed.py"


@pytest.mark.parametrize("change", ["status", "deliverables", "evidence"])
def test_direct_dependency_card_drift_requires_fresh_work_order(work_orders, repo, change):
    handoff(work_orders, repo)
    board = json.loads((repo / work_orders.BOARD_REF).read_text())
    dependency = board["tasks"][0]
    dependency[change] = "done" if change == "status" else ["src/unrelated.py"]
    put(repo, work_orders.BOARD_REF, json.dumps(board))
    with pytest.raises(ValueError, match="DEPENDENCY_CARD_CHANGED"):
        work_orders.validate_handoff(repo, "out/draft/work-order.json", "out/handoff/handoff.json")


@pytest.mark.parametrize("kind,payload", [
    ("repair", {"defects": [{"defect_id": "DEF-1", "requirement_id": "R07", "location": "src/allowed.py",
        "impact": "Missing translated block", "failure_evidence": ["inputs/direct.txt"],
        "allowed_files": ["src/allowed.py"], "pass_condition": "All source blocks have translations",
        "rerun_checks": [["python", "-m", "pytest", "tests/integration/test_input_translation.py"]]}], "artifact_version": "rev-1"}),
    ("blocked", {"cannot_complete": "Real acceptance", "direct_evidence": ["inputs/direct.txt"],
        "attempted_actions": ["Checked dependency files"], "external_conditions": ["Approved human review"],
        "independent_tasks": ["D029"], "artifact_version": "rev-1"}),
], ids=["repair", "blocked"])
def test_repair_and_blocked_reports_require_retrievable_evidence(work_orders, repo, kind, payload):
    draft(work_orders, repo)
    put(repo, "src/allowed.py", "current report revision\n")
    value = work_orders.create_report(repo, "out/draft/work-order.json", kind, payload, "out/report")
    assert value["task_id"] == "D028" and value["contract_version"] == "1"
    assert value["evidence_index"][0]["sha256"] == hashlib.sha256(b"direct dependency").hexdigest()
    assert value["revision"] == [{"ref": "src/allowed.py", "kind": "file", "sha256": hashlib.sha256((repo / "src/allowed.py").read_bytes()).hexdigest()}]
    assert len(value["revision_sha256"]) == 64
    invalid = copy.deepcopy(payload)
    invalid.pop("artifact_version")
    with pytest.raises(ValueError):
        work_orders.create_report(repo, "out/draft/work-order.json", kind, invalid, "out/bad")
