"""Every pending SQL statement is a recoverable transactional boundary."""
from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.storage.database import Database
from app.storage.migrations import Migration, MigrationError, migrate, _statements


def chain():
    return [Migration(int(p.name.split('_')[0]), p.stem, p.read_text(encoding='utf-8'))
            for p in sorted((Path(__file__).parents[2] / 'services/orchestrator/app/storage/schema').glob('*.sql'))]


@pytest.mark.parametrize('failure_index', range(1, len(_statements(chain()[3].sql)) + 2))
def test_v3_to_v4_failure_rolls_back_every_statement(tmp_path, failure_index):
    database = Database(tmp_path / 'workbench.sqlite3')
    migrations = chain()
    statements = _statements(migrations[3].sql)
    # Include failure after the final statement, before history is committed.
    fault = min(failure_index - 1, len(statements))
    with closing(database.connect()) as c:
        migrate(c, migrations[:3])
        c.execute("INSERT INTO conversations(id,title) VALUES('c','旧版中文样本')")
        before = '\n'.join(c.iterdump())
        sql = '\n'.join(statements[:fault] + ['INSERT INTO missing_failure_injection VALUES(1);'] + statements[fault:])
        with pytest.raises(sqlite3.Error): migrate(c, migrations[:3] + [Migration(4, migrations[3].name, sql)])
        assert '\n'.join(c.iterdump()) == before
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert migrate(c) == 4


@pytest.mark.parametrize('boundary', ['history', 'commit'])
def test_history_and_commit_failure_preserve_v3(tmp_path, boundary):
    with closing(Database(tmp_path / 'workbench.sqlite3').connect()) as c:
        migrate(c, chain()[:3])
        before = '\n'.join(c.iterdump())
        def authorizer(action, first, second, database, trigger):
            rejected = ((boundary == 'history' and action == sqlite3.SQLITE_INSERT and first == 'schema_version') or
                        (boundary == 'commit' and action == sqlite3.SQLITE_TRANSACTION and first == 'COMMIT'))
            return sqlite3.SQLITE_DENY if rejected else sqlite3.SQLITE_OK
        c.set_authorizer(authorizer)
        with pytest.raises(sqlite3.Error): migrate(c)
        c.set_authorizer(None)
        assert '\n'.join(c.iterdump()) == before
        assert migrate(c) == 4


def test_old_program_rejects_new_schema_without_writing(tmp_path):
    with closing(Database(tmp_path / 'workbench.sqlite3').connect()) as c:
        migrate(c)
        before = '\n'.join(c.iterdump())
        with pytest.raises(MigrationError, match='NEWER_SCHEMA'): migrate(c, chain()[:3])
        assert '\n'.join(c.iterdump()) == before


def test_v3_backup_upgrade_and_matching_rollback(tmp_path):
    from app.storage.backup import create_backup, validate_backup
    from app.storage.restore import restore_backup
    old = tmp_path / 'v3中文'
    with closing(Database(old / 'workbench.sqlite3').connect()) as c:
        migrate(c, chain()[:3])
        c.execute("INSERT INTO conversations(id,title) VALUES('c','旧版保留')")
    bundle = create_backup(old, tmp_path / 'backups')
    assert validate_backup(bundle)['schema_version'] == 3
    report = restore_backup(bundle, old)
    import hashlib
    actual_database_hash = hashlib.sha256((Path(report['destination']) / 'workbench.sqlite3').read_bytes()).hexdigest()
    assert report['hashes']['workbench.sqlite3'] == actual_database_hash
    with closing(Database(Path(report['destination']) / 'workbench.sqlite3').connect()) as c:
        assert c.execute('SELECT MAX(version) FROM schema_version').fetchone()[0] == 4
        assert c.execute('SELECT title FROM conversations').fetchone()[0] == '旧版保留'
    # The original bundle and root retain schema 3 for the matching old program.
    with closing(Database(old / 'workbench.sqlite3').connect()) as c:
        assert migrate(c, chain()[:3]) == 3
