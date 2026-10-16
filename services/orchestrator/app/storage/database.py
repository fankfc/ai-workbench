"""Connection and transaction boundary."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int = 5000):
        self.path = Path(path)
        if type(busy_timeout_ms) is not int or busy_timeout_ms < 0:
            raise ValueError("INVALID_BUSY_TIMEOUT")
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path, isolation_level=None, timeout=self.busy_timeout_ms / 1000,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            connection.execute("PRAGMA foreign_keys=ON")
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode != "wal":
                raise sqlite3.OperationalError("WAL_REQUIRED")
            connection.execute("PRAGMA synchronous=FULL")
            return connection
        except BaseException:
            connection.close()
            raise


@contextmanager
def transaction(connection: sqlite3.Connection):
    """One writer owns the boundary; callers cannot accidentally nest commits."""
    if connection.in_transaction:
        raise ValueError("TRANSACTION_ALREADY_ACTIVE")
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
