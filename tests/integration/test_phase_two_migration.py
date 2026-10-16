from contextlib import closing
from pathlib import Path

from app.storage.database import Database
from app.storage.migrations import Migration, migrate


def test_upgrade_keeps_frozen_turn_route_and_user_text(tmp_path):
    schema = Path(__file__).parents[2] / 'services/orchestrator/app/storage/schema/0001_initial.sql'
    database = Database(tmp_path / 'workbench.sqlite3')
    with closing(database.connect()) as connection:
        migrate(connection, [Migration(1, schema.stem, schema.read_text(encoding='utf-8'))])
        connection.execute("INSERT INTO conversations(id,title) VALUES('c','原会话')")
        connection.execute("INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,connection_version) VALUES('p','fake','fixture-gpt','gpt','p','unknown','old')")
        route = '{"id":"original","unknown":true}'
        connection.execute("INSERT INTO turns(id,conversation_id,task_id,provider_profile_id,client_request_id,user_text,route_snapshot_json) VALUES('t','c','task','p','request','不能删除',?)", (route,))
        before = tuple(connection.execute('SELECT * FROM turns').fetchone())
        assert migrate(connection) == 4
        assert tuple(connection.execute('SELECT * FROM turns').fetchone()) == before
        assert connection.execute('SELECT pinned,archived FROM conversations').fetchone()[:] == (0, 0)
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert migrate(connection) == 4
