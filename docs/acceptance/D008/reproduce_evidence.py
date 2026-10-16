"""Reproduce a v1->v2 fixture upgrade and derive reports from pytest JUnit."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

from app.storage.database import Database
from app.storage.migrations import Migration, migrate
from app.storage.blobs import read_artifact


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[2]
TIME = datetime.now(timezone.utc).isoformat()
WORK = OUTPUT / "fixtures" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
WORK.mkdir(parents=True)
spec = importlib.util.spec_from_file_location("storage_acceptance_fixture", ROOT / "tests/integration/test_storage.py")
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)
fixture = suite.storage.__wrapped__(WORK)
connection, store = next(fixture)
artifact = suite.populate_domain_tables(connection, store)
names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='schema_version' ORDER BY name")]
columns = {name: [row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')] for name in names}


def snapshot(connection):
    result = {}
    for name in names:
        selection = ",".join('"' + column + '"' for column in columns[name])
        rows = [list(row) for row in connection.execute(f'SELECT {selection} FROM "{name}" ORDER BY 1')]
        result[name] = {"row_count": len(rows), "original_columns_sha256": hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()}
    return result


before = snapshot(connection)
old_copy = sqlite3.connect(WORK / "metadata-v1.sqlite3")
connection.backup(old_copy)
old_copy.close()
fixture.close()
connection = Database(WORK / "metadata.sqlite3").connect()
initial_path = ROOT / "services/orchestrator/app/storage/schema/0001_initial.sql"
initial = Migration(1, initial_path.stem, initial_path.read_text(encoding="utf-8"))
additive = Migration(2, "additive-fixture", "ALTER TABLE conversations ADD COLUMN archive_note TEXT;")
version = migrate(connection, [initial, additive])
after = snapshot(connection)
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
foreign_keys = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
actual_hash = hashlib.sha256(read_artifact(connection, store, artifact.id)).hexdigest()
history = [dict(row) for row in connection.execute("SELECT * FROM schema_version ORDER BY version")]
connection.close()
assert before == after and integrity == "ok" and foreign_keys == [] and actual_hash == artifact.byte_sha256
commit_result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False)
metadata = {"generated_at": TIME, "commit": commit_result.stdout.strip() if commit_result.returncode == 0 else None,
            "python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "platform": platform.platform(),
            "interpreter": sys.executable, "mode": "isolated real SQLite/filesystem; no external provider calls",
            "command": "services/orchestrator/.venv/Scripts/python.exe docs/acceptance/D008/reproduce_evidence.py"}
report = {**metadata, "exit_code": 0, "fixture_directory": WORK.relative_to(ROOT).as_posix(),
          "old_schema_version": 1, "new_schema_version": version, "before": before, "after": after,
          "schema_history": history, "integrity_check": integrity, "foreign_key_check": foreign_keys,
          "blob": {"artifact_id": artifact.id, "expected_sha256": artifact.byte_sha256,
                   "actual_sha256": actual_hash, "size_bytes": store.verify(actual_hash).size_bytes},
          "upgrade": "Actual v1 database closed and reopened; version 2 adds a nullable field, preserving all original columns."}
(OUTPUT / "migration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
junit = ET.parse(OUTPUT / "storage-tests.xml")
cases = [{"name": case.attrib["name"], "duration_seconds": float(case.attrib.get("time", 0)),
          "result": "failed" if case.find("failure") is not None or case.find("error") is not None
          else "skipped" if case.find("skipped") is not None else "passed"}
         for case in junit.iter("testcase")]
assert cases and all(case["result"] == "passed" for case in cases)
fault_terms = ("failure", "interruption", "interrupt", "lock", "missing", "corrupt", "reject", "rollback", "rolls_back", "exit", "duplicate", "mismatch", "replaced", "changing", "simultaneous")
faults = {**metadata, "pytest_command": "services/orchestrator/.venv/Scripts/python.exe -m pytest tests/integration/test_storage.py -q --junitxml=docs/acceptance/D008/storage-tests.xml",
          "pytest_exit_code": 0, "passed": len(cases), "failed": 0,
          "fault_injection": "ENOSPC/EIO/KeyboardInterrupt injected at filesystem operations; SQLite lock and subprocess exit use real local resources.",
          "cases": [case for case in cases if any(term in case["name"] for term in fault_terms)],
          "crash_boundary": "Real child exits 78 after artifact INSERT and before SQLite COMMIT: no visible revision, complete unreferenced blob remains safe.",
          "not_exercised": ["physical disk exhaustion", "machine power loss", "full product backup/restore"]}
(OUTPUT / "storage-faults.json").write_text(json.dumps(faults, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
sources = [ROOT / "services/orchestrator/app/storage" / name for name in ("__init__.py", "database.py", "migrations.py", "blobs.py", "schema/0001_initial.sql")]
sources += [ROOT / "tests/integration/test_storage.py", Path(__file__).resolve()]
sources += sorted((ROOT / "services/orchestrator/app/contracts").glob("*.py"))
(OUTPUT / "source-hashes.json").write_text(json.dumps({**metadata, "sources": {
    path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"version": version, "preserved_tables": len(names), "blob_sha256": actual_hash,
                  "passed_tests": len(cases), "fixture_directory": WORK.relative_to(ROOT).as_posix()}))
