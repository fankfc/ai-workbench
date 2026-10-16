"""D011 private ledger; does not depend on or mutate the D008 schema."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LeaseStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(process_leases)")}
            if columns and "step_id" not in columns:
                connection.execute("ALTER TABLE process_leases RENAME TO process_leases_legacy")
            connection.execute("""CREATE TABLE IF NOT EXISTS process_leases (
                task_id TEXT NOT NULL, attempt_id TEXT NOT NULL, step_id TEXT NOT NULL, pid INTEGER NOT NULL,
                owner_pid INTEGER NOT NULL, remote_id TEXT, cwd TEXT NOT NULL,
                temp_dir TEXT NOT NULL, local_state TEXT NOT NULL,
                remote_state TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, result_json TEXT,
                PRIMARY KEY (task_id, attempt_id, step_id))""")
            if columns and "step_id" not in columns:
                connection.execute("""INSERT INTO process_leases
                    SELECT task_id,attempt_id,'default',pid,owner_pid,remote_id,cwd,temp_dir,
                           local_state,remote_state,started_at,finished_at,result_json
                    FROM process_leases_legacy""")
                connection.execute("DROP TABLE process_leases_legacy")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=FULL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def contains(self, task_id: str, attempt_id: str, step_id: str = "default") -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1 FROM process_leases WHERE task_id=? AND attempt_id=? AND step_id=?",
                                      (task_id, attempt_id, step_id)).fetchone() is not None

    def unresolved_cancel(self, task_id: str, attempt_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute("""SELECT 1 FROM process_leases WHERE task_id=? AND attempt_id=?
                AND remote_state='unknown'""",
                (task_id, attempt_id)).fetchone() is not None

    def confirm_remote_stop(self, task_id: str, attempt_id: str, step_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM process_leases WHERE task_id=? AND attempt_id=? AND step_id=?",
                                     (task_id, attempt_id, step_id)).fetchone()
            if row is None or not row["remote_id"]:
                raise ValueError("REMOTE_EXECUTION_ID_REQUIRED")
            detail = json.loads(row["result_json"]) if row["result_json"] else {}
            detail.update(remote_state="stopped", remote_stop_confirmed_at=_now())
            connection.execute("UPDATE process_leases SET remote_state='stopped',result_json=? WHERE task_id=? AND attempt_id=? AND step_id=?",
                (json.dumps(detail), task_id, attempt_id, step_id))
            return {**dict(row), "remote_state": "stopped", "result_json": json.dumps(detail)}

    def failure(self, task_id: str, attempt_id: str, step_id: str, details: dict) -> None:
        with self._connect() as connection:
            row = connection.execute("SELECT remote_state FROM process_leases WHERE task_id=? AND attempt_id=? AND step_id=?",
                                     (task_id, attempt_id, step_id)).fetchone()
            if row is None:
                raise ValueError("PROCESS_LEASE_MISSING")
            audit = {**details, "local_state": "cleanup_failed", "remote_state": row["remote_state"]}
            connection.execute("UPDATE process_leases SET local_state='cleanup_failed',finished_at=?,result_json=? WHERE task_id=? AND attempt_id=? AND step_id=?",
                (_now(), json.dumps(audit), task_id, attempt_id, step_id))

    def start(self, *, task_id: str, attempt_id: str, pid: int, owner_pid: int,
              remote_id: str | None, cwd: Path, temp_dir: Path, step_id: str = "default") -> None:
        with self._connect() as connection:
            connection.execute("""INSERT INTO process_leases
                (task_id,attempt_id,step_id,pid,owner_pid,remote_id,cwd,temp_dir,local_state,remote_state,started_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (task_id, attempt_id, step_id, pid, owner_pid, remote_id,
                str(cwd), str(temp_dir), "running", "unknown" if remote_id else "not_applicable", _now()))

    def finish(self, task_id: str, attempt_id: str, result: dict, step_id: str = "default") -> None:
        with self._connect() as connection:
            connection.execute("""UPDATE process_leases SET local_state=?,remote_state=?,
                finished_at=?,result_json=? WHERE task_id=? AND attempt_id=? AND step_id=?""",
                (result["local_state"], result["remote_state"], _now(),
                 json.dumps(result, ensure_ascii=False), task_id, attempt_id, step_id))

    def records(self) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM process_leases ORDER BY rowid")]
