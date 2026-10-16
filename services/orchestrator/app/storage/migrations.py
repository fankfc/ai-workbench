"""Sequential SQL migration entry point."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Sequence

from .database import transaction


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


class MigrationError(ValueError):
    pass


def migrate(connection: sqlite3.Connection, migrations: Sequence[Migration] | None = None) -> int:
    """Upgrade all pending versions atomically, preserving applied SQL hashes."""
    chain = list(migrations) if migrations is not None else [
        Migration(int(path.name.split("_", 1)[0]), path.stem, path.read_text(encoding="utf-8"))
        for path in sorted((Path(__file__).parent / "schema").glob("[0-9]*_*.sql"))
    ]
    if not chain or any(type(item.version) is not int or item.version != index
                        or not item.name.strip() for index, item in enumerate(chain, 1)):
        raise MigrationError("MIGRATIONS_NOT_CONTIGUOUS")
    statements = [_statements(item.sql) for item in chain]
    hashes = [hashlib.sha256(item.sql.encode("utf-8")).hexdigest() for item in chain]
    with transaction(connection):
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        if tables and "schema_version" not in tables:
            raise MigrationError("UNVERSIONED_DATABASE")
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY CHECK(version > 0),
            name TEXT NOT NULL, sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )""")
        rows = connection.execute("SELECT version,name,sha256 FROM schema_version ORDER BY version").fetchall()
        if rows and rows[-1][0] > len(chain):
            raise MigrationError("NEWER_SCHEMA")
        if [row[0] for row in rows] != list(range(1, len(rows) + 1)):
            raise MigrationError("SCHEMA_HISTORY_NOT_CONTIGUOUS")
        for row, item, digest in zip(rows, chain, hashes):
            if row[1] != item.name or row[2] != digest:
                raise MigrationError("MIGRATION_CHANGED")
        for item, sql_statements, digest in zip(chain[len(rows):], statements[len(rows):], hashes[len(rows):]):
            for statement in sql_statements:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_version(version,name,sha256) VALUES (?,?,?)",
                               (item.version, item.name, digest))
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationError("FOREIGN_KEY_CHECK_FAILED")
    return len(chain)


def _statements(sql: str) -> list[str]:
    """SQLite itself identifies complete trigger/string statements."""
    result = []
    pending = ""
    for character in sql:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            result.append(pending)
            pending = ""
    if _without_comments(pending).strip():
        if not sqlite3.complete_statement(pending + ";"):
            raise MigrationError("INCOMPLETE_MIGRATION_SQL")
        result.append(pending)
    for statement in result:
        token = _without_comments(statement).lstrip().split(None, 1)[0].rstrip(";").upper()
        if token in {"BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE",
                     "PRAGMA", "VACUUM", "ATTACH", "DETACH"}:
            raise MigrationError("MIGRATION_TRANSACTION_CONTROL_FORBIDDEN")
    return result


def _without_comments(sql: str) -> str:
    return re.sub(r"/\*.*?\*/|--[^\r\n]*", "", sql, flags=re.DOTALL)
