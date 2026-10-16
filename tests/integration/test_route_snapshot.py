from contextlib import closing
import json
import sqlite3
import pytest
from app.contracts.providers import ProviderContract
from app.translation.router import LanguageRouter
from translation.fakes import claude_turn

def test_route_snapshot_is_persisted_immutable_and_identity_change_pauses(client):
    _,task,attempt=claude_turn(client)
    router=LanguageRouter(client.app.state.database.path); route=router.lock(task,attempt)
    assert router.lock(task,attempt)==route
    with closing(client.app.state.database.connect()) as connection:
        before=connection.execute('SELECT snapshot_json FROM route_snapshots WHERE id=?',(route.id,)).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError,match='IMMUTABLE'):
            connection.execute('UPDATE route_snapshots SET snapshot_json=? WHERE id=?',('{}',route.id))
    changed=ProviderContract(schema_version='1.0',provider_id='fake-claude',identity=dict(adapter='fake',model_id='fallback-gpt',family='gpt',connection_id='fake-claude'),identity_status='verified',identity_source='fixture:fake',connection_version='2')
    assert router.check_identity(task,attempt,changed) is False
    with closing(client.app.state.database.connect()) as connection:
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
        assert row['state']=='PAUSED' and json.loads(row['checkpoint_json'])['publication_blocked']
        assert connection.execute('SELECT snapshot_json FROM route_snapshots WHERE id=?',(route.id,)).fetchone()[0]==before

def test_restart_reads_same_route_snapshot_bytes(client):
    _,task,attempt=claude_turn(client)
    assert LanguageRouter(client.app.state.database.path).lock(task,attempt)==LanguageRouter(client.app.state.database.path).lock(task,attempt)
