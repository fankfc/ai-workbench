"""Independently check the partial phase-two freeze without invoking providers."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy
import sys
import xml.etree.ElementTree as ET
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FREEZE_REL = HERE.relative_to(ROOT).as_posix()
BOARD_REL = "docs/superpowers/plans/2026-10-13-execution/task-board.json"
DATA_REL = "docs/superpowers/plans/2026-10-13-execution/data/tasks-02.json"
RESULTS_REL = "docs/acceptance/part-two/task-results.json"
HISTORY_REL = "docs/acceptance/part-two/verification.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha(value: object) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))


def local_path(name: str) -> Path:
    if not isinstance(name, str) or "\\" in name:
        raise ValueError(f"invalid relative path: {name!r}")
    rel = PurePosixPath(name)
    if rel.is_absolute() or not rel.parts or any(p in ("..", ".") for p in rel.parts):
        raise ValueError(f"unsafe relative path: {name!r}")
    path = ROOT.joinpath(*rel.parts)
    if path.resolve().is_relative_to(ROOT) is False:
        raise ValueError(f"path escapes workspace: {name!r}")
    if any(ROOT.joinpath(*rel.parts[:n]).is_symlink() for n in range(1, len(rel.parts) + 1)):
        raise ValueError(f"symlink in snapshot path: {name!r}")
    return path


def read_json(name: str) -> object:
    return json.loads(local_path(name).read_text(encoding="utf-8-sig"))


def cards_in(tasks: list[dict], start: int, end: int) -> list[dict]:
    wanted = {f"D{i:03d}" for i in range(start, end + 1)}
    cards = [card for card in tasks if card.get("id") in wanted]
    ids = [card["id"] for card in cards]
    if len(ids) != len(wanted) or set(ids) != wanted:
        raise ValueError(f"task ids missing or duplicated in D{start:03d}-D{end:03d}")
    return cards


def verify() -> dict:
    errors: list[str] = []
    checks: dict[str, object] = {}

    def expect(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    freeze = read_json(f"{FREEZE_REL}/freeze.json")
    manifest = read_json(f"{FREEZE_REL}/archive-manifest.json")
    preserved = read_json(f"{FREEZE_REL}/preserved-state.json")
    unfinished = read_json(f"{FREEZE_REL}/unfinished-tasks.json")
    expect(freeze.get("schema_version") == "1.0", "freeze schema_version is not 1.0")
    expect(freeze.get("status") == "frozen_partial", "freeze status is not frozen_partial")
    expect(freeze.get("scope") == "D021-D040", "freeze scope differs from D021-D040")
    expect(bool(freeze.get("frozen_at")), "freeze timestamp missing")
    preserved_ref = freeze.get("preserved_state")
    expect(preserved_ref in ("preserved-state.json", f"{FREEZE_REL}/preserved-state.json"),
           "freeze preserved_state reference mismatch")

    files = manifest["files"]
    expect(isinstance(files, dict) and bool(files), "archive file manifest empty")
    manifest_rel = f"{FREEZE_REL}/archive-manifest.json"
    external_records = {f"{FREEZE_REL}/freeze.json", f"{FREEZE_REL}/verification.json"}
    expect(not (set(files) & (external_records | {manifest_rel})),
           "manifest includes a self-referential or external freeze record")
    archive_path = local_path(freeze["archive"]["path"])
    archive_hash = sha(archive_path.read_bytes())
    expect(archive_hash == freeze["archive"]["sha256"], "ZIP SHA256 mismatch")
    workspace_matches = 0
    archive_matches = 0
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        expect(len(names) == len(set(names)), "ZIP contains duplicate members")
        extra = set(names) - set(files)
        expect(extra in ({manifest_rel}, {"archive-manifest.json"}),
               "ZIP members do not exactly match manifest plus one manifest file")
        expect(set(files) <= set(names), "ZIP is missing manifest files")
        if extra in ({manifest_rel}, {"archive-manifest.json"}):
            member = next(iter(extra))
            expect(archive.read(member) == local_path(manifest_rel).read_bytes(),
                   "ZIP embedded manifest bytes mismatch")
        for name, record in files.items():
            path = local_path(name)
            parts = PurePosixPath(name).parts
            expect(not any(p in {".git", ".venv", "node_modules", "__pycache__"} for p in parts)
                   and not any(p == ".env" or p.startswith(".env.") for p in parts),
                   f"excluded environment/dependency path in ZIP: {name}")
            if not path.is_file():
                errors.append(f"workspace manifest file missing: {name}")
                continue
            current = path.read_bytes()
            current_ok = len(current) == record["bytes"] and sha(current) == record["sha256"]
            expect(current_ok, f"workspace bytes/hash mismatch: {name}")
            workspace_matches += int(current_ok)
            if name in set(names):
                zipped = archive.read(name)
                zipped_ok = len(zipped) == record["bytes"] and sha(zipped) == record["sha256"]
                expect(zipped_ok, f"ZIP bytes/hash mismatch: {name}")
                expect(zipped == current, f"ZIP differs from workspace: {name}")
                archive_matches += int(zipped_ok)
    checks["archive"] = {"sha256": archive_hash, "files": len(files),
                         "workspace_matches": workspace_matches, "zip_matches": archive_matches}

    source = read_json(freeze["source_reference"]["path"])
    source_rows = source["files"]
    source_hash = sha(json.dumps(source_rows, sort_keys=True).encode("utf-8"))
    expect(source_hash == source["source_sha256"] == freeze["source_reference"]["sha256"],
           "final source aggregate SHA256 mismatch")
    expect(len(source_rows) == 286, "final source manifest count differs from 286")
    source_matches = 0
    for name, digest in source_rows.items():
        path = local_path(name)
        matched = path.is_file() and sha(path.read_bytes()) == digest
        expect(matched, f"final verified source changed: {name}")
        expect(name in files, f"final verified source absent from archive: {name}")
        source_matches += int(matched)
    manifest_functions = runpy.run_path(str(ROOT / "scripts/phase_two_manifest.py"))
    selected = {path.relative_to(ROOT).as_posix()
                for path in manifest_functions["source_files"](source.get("scope", "all"))}
    expect(selected == set(source_rows), "current final-source file selection changed")
    checks["final_source"] = {"files": len(source_rows), "matched": source_matches,
                              "sha256": source_hash, "selection_unchanged": selected == set(source_rows)}

    first_files = preserved["first_part_files"]
    first_dir = ROOT / "docs/acceptance/part-one-freeze-20261014"
    current_first_files = {path.relative_to(ROOT).as_posix()
                           for path in first_dir.rglob("*") if path.is_file()}
    expect(set(first_files) == current_first_files, "first-part frozen file set changed")
    for name, digest in first_files.items():
        path = local_path(name)
        expect(path.is_file() and sha(path.read_bytes()) == digest,
               f"first-part frozen file changed: {name}")

    board = read_json(BOARD_REL)
    expect(board.get("development_status") == "part_two_frozen_partial",
           "task-board development_status not frozen_partial")
    first_cards = cards_in(board["tasks"], 1, 20)
    future_cards = cards_in(board["tasks"], 41, 60)
    expect(canonical_sha(first_cards) == preserved["task_groups"]["part_one"],
           "first-part task cards changed")
    expect(canonical_sha(future_cards) == preserved["task_groups"]["future"],
           "future task cards changed")
    expect(canonical_sha(board["execution_summary"]) == preserved["first_part_execution_summary"],
           "first-part execution_summary changed")
    expect(all(card.get("status") == "planned" for card in future_cards),
           "future cards no longer all planned")
    historical_hash = sha(local_path(HISTORY_REL).read_bytes())
    expect(historical_hash == preserved["historical_verification_sha256"],
           "historical phase-two verification changed")
    history = read_json(HISTORY_REL)
    expect(history.get("complete") is False and history.get("real_model_calls") == 0,
           "historical verification no longer records incomplete/zero real calls")
    checks["preserved"] = {"first_part_files": len(first_files), "first_part_tasks": 20,
                           "future_tasks": 20, "historical_verification_sha256": historical_hash}

    board_cards = cards_in(board["tasks"], 21, 40)
    data = read_json(DATA_REL)
    data_cards = cards_in(data if isinstance(data, list) else data["tasks"], 21, 40)
    result_cards = cards_in(read_json(RESULTS_REL)["cards"], 21, 40)
    frozen_cards = cards_in(unfinished["cards"], 21, 40)
    states = {card["id"]: card["status"] for card in board_cards}
    for label, cards in (("tasks-02", data_cards), ("task-results", result_cards),
                         ("unfinished snapshot", frozen_cards)):
        expect({card["id"]: card["status"] for card in cards} == states,
               f"{label} status mismatch")
    expect(Counter(states.values()) == Counter({"in_progress": 18, "blocked": 2}),
           "phase-two status counts differ from 18 in_progress/2 blocked")
    expect({name for name, state in states.items() if state == "blocked"} == {"D024", "D040"},
           "blocked card ids differ from D024/D040")
    expect({card["id"]: card for card in frozen_cards} == {card["id"]: card for card in board_cards},
           "unfinished snapshot differs from complete task-board cards")
    for label, cards in (("task-board", board_cards), ("tasks-02", data_cards),
                         ("unfinished snapshot", frozen_cards)):
        for card in cards:
            marker = card.get("freeze", {})
            expect(marker.get("status") == "frozen_partial"
                   and marker.get("frozen_at") == freeze["frozen_at"]
                   and marker.get("evidence") == f"{FREEZE_REL}/freeze.json",
                   f"{label} freeze marker mismatch: {card['id']}")
    checks["tasks"] = {"cards": 20, "states": dict(Counter(states.values())),
                       "done": sum(state == "done" for state in states.values())}

    junit_path = local_path("docs/acceptance/part-two/final-python.xml")
    junit = ET.parse(junit_path).getroot()
    suites = list(junit.iter("testsuite"))
    totals = {name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
              for name in ("tests", "failures", "errors", "skipped")}
    expect(totals == {"tests": 1318, "failures": 0, "errors": 0, "skipped": 0},
           "final Python JUnit totals mismatch")
    python_run = read_json("docs/acceptance/part-two/final-python.json")
    expect(python_run.get("exit_code") == 0, "final Python command exit_code not zero")
    checks["historical_tests"] = {"junit": totals, "python_exit_code": python_run.get("exit_code")}

    return {"schema_version": "1.0", "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if not errors else "FAIL", "complete": False,
            "freeze_integrity_verified": not errors, "product_acceptance_complete": False,
            "new_real_model_calls": 0, "full_product_regression_rerun": False,
            "checks": checks, "errors": errors}


if __name__ == "__main__":
    try:
        result = verify()
    except Exception as exc:
        result = {"schema_version": "1.0", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "status": "FAIL", "freeze_integrity_verified": False,
                  "product_acceptance_complete": False, "new_real_model_calls": 0,
                  "full_product_regression_rerun": False,
                  "errors": [f"{type(exc).__name__}: {exc}"]}
    (HERE / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "freeze_integrity_verified": result["freeze_integrity_verified"],
                      "errors": result["errors"],
                      "report": f"{FREEZE_REL}/verification.json"}, ensure_ascii=False))
    sys.exit(0 if result["freeze_integrity_verified"] else 1)
