"""Restart publishes only already staged local releases, without another model call."""
import asyncio
from contextlib import closing
import json
import time

import pytest

from app.api.application import create_app
from app.config import AppSettings
from app.runtime.publication import NativePublisher
from app.runtime.supervisor import TaskSupervisor
from app.storage.database import transaction
from test_native_backend_bindings import assembled_case
from test_native_supervisor import task_row
from test_output_translation import claude_answer


def staged_native(tmp_path, monkeypatch):
    app, task, runtime, b, a, bindings, held, _ = assembled_case(tmp_path)
    publish = NativePublisher.publish

    def interrupted(*_):
        raise RuntimeError('fixture interruption after local READY')

    monkeypatch.setattr(NativePublisher, 'publish', interrupted)
    asyncio.run(TaskSupervisor(app.state.database.path, bindings, provider_mode='fake').run_once())
    assert task_row(app, task)['state'] == 'READY'
    monkeypatch.setattr(NativePublisher, 'publish', publish)
    return app, task, runtime, b, a, held


def restart(app):
    return create_app(AppSettings(app.state.settings.data_root, 'restart-fixture-token', 'fake', True))


def test_restart_finishes_staged_native_publication_without_models(tmp_path, monkeypatch):
    app, task, runtime, b, a, _ = staged_native(tmp_path, monkeypatch)
    restored = restart(app)
    assert task_row(restored, task)['state'] == 'PUBLISHED'
    assert restored.state.recovery_results[0]['decision'] == 'local_publication_resumed'
    assert len(runtime.starts) == len(b.starts) == len(a.starts) == 1
    restarted = restart(restored)
    assert task_row(restarted, task)['state'] == 'PUBLISHED'
    with closing(restarted.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM turns').fetchone()[0] == 1


def test_real_startup_cannot_publish_a_fixture_staged_release(tmp_path, monkeypatch):
    app, task, _, _, _, _ = staged_native(tmp_path, monkeypatch)
    restored = create_app(AppSettings(app.state.settings.data_root, 'r' * 40, 'real', True))
    assert task_row(restored, task)['state'] == 'BLOCKED'
    with closing(restored.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0
@pytest.mark.parametrize('damage', ['missing_gate', 'review_changed', 'proof_changed', 'bytes_changed', 'cancelled', 'incident', 'foreign_owner', 'unconfirmed_remote', 'new_attempt', 'malformed_handoff_list', 'malformed_handoff_null', 'invalid_checkpoint'])
def test_restart_never_publishes_damaged_or_cancelled_staged_release(tmp_path, monkeypatch, damage):
    app, task, _, _, _, held = staged_native(tmp_path, monkeypatch)
    with closing(app.state.database.connect()) as connection, transaction(connection):
        row = connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone()
        checkpoint = json.loads(row['checkpoint_json'])
        if damage == 'missing_gate':
            checkpoint.pop('release_registry')
        elif damage == 'review_changed':
            check = connection.execute('SELECT * FROM checks WHERE id=?', (held['result'].review_check_id,)).fetchone()
            details = json.loads(check['details_json'])
            details['decision']['decision'] = 'BLOCKED'
            connection.execute('UPDATE checks SET details_json=? WHERE id=?', (json.dumps(details), check['id']))
        elif damage == 'proof_changed':
            from pathlib import Path
            proof = Path(connection.execute("SELECT evidence_ref FROM checks WHERE check_kind='C.criterion'").fetchone()[0])
            proof.write_text('changed', encoding='utf-8')
        elif damage == 'bytes_changed':
            artifact = connection.execute('SELECT byte_sha256 FROM artifact_revisions WHERE id=?',
                (held['result'].current_revision_id,)).fetchone()
            app.state.blobs.path_for(artifact[0]).write_bytes(b'changed')
        elif damage == 'cancelled':
            connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1 WHERE task_id=?", (task,))
        elif damage == 'foreign_owner':
            connection.execute("UPDATE task_runs SET lease_owner='foreign-owner' WHERE task_id=?", (task,))
        elif damage.startswith('malformed_handoff_'):
            checkpoint['planning_handoff'] = [] if damage.endswith('list') else None
            connection.execute("UPDATE task_runs SET lease_owner='old-owner' WHERE task_id=?", (task,))
        elif damage == 'invalid_checkpoint':
            checkpoint = []
        elif damage == 'unconfirmed_remote':
            checkpoint['active_external_request']['status'] = 'unknown'
        elif damage == 'new_attempt':
            connection.execute("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,attempt_number,route_snapshot_json) VALUES(?,'new-attempt',?,?,'RECEIVED',2,?)",
                (task, row['turn_id'], row['provider_profile_id'], row['route_snapshot_json']))
        else:
            checkpoint['publication_blocked'] = True
        connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?', (json.dumps(checkpoint), task))
    restored = restart(app)
    assert task_row(restored, task)['state'] != 'PUBLISHED'
    with closing(restored.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0
    if damage == 'invalid_checkpoint':
        restored = restart(restored)
        assert task_row(restored, task)['state'] == 'BLOCKED'
        with closing(restored.state.database.connect()) as connection:
            assert connection.execute('SELECT checkpoint_json FROM task_runs WHERE task_id=?', (task,)).fetchone()[0] == '[]'


def test_restart_finishes_staged_claude_answer_without_translation_or_english_leak(claude_answer):
    from app.runtime.answer_publication import AnswerPublisher
    from translation.fakes import service
    client, cid, task, attempt, root, _, machine = claude_answer
    translation = service(client)
    with closing(client.app.state.database.connect()) as connection:
        details = json.loads(connection.execute("SELECT details_json FROM checks WHERE id='translation-review'").fetchone()[0])
        details['evidence_root'] = str(root)
        connection.execute("UPDATE checks SET details_json=? WHERE id='translation-review'", (json.dumps(details),))
    publisher = AnswerPublisher(client.app.state.database.path, root, translation)
    asyncio.run(publisher.stage(task, attempt, '1.0', 'en-answer', 'translation-review'))
    machine.transition(task, attempt, 'OUTPUT_PREPARING', 'READY', '1.0')
    calls = len(translation.translator.calls)
    assert calls > 0
    restored = restart(client.app)
    assert task_row(restored, task)['state'] == 'PUBLISHED'
    assert len(translation.translator.calls) == calls
    from fastapi.testclient import TestClient
    with TestClient(restored, headers={'Authorization': 'Bearer restart-fixture-token'}) as reader:
        messages = reader.get(f'/v1/conversations/{cid}/messages').json()['items']
        assert [item['text'] for item in messages if item['kind'] == 'answer.published'] == ['保留原文件。']
        assert 'INTERNAL_ENGLISH_CANARY' not in json.dumps(messages)


@pytest.mark.parametrize('damaged_published_bundle', [False, True])
def test_restart_atomically_finishes_staged_file_bundle(tmp_path, monkeypatch, damaged_published_bundle):
    from fastapi.testclient import TestClient
    from app.documents.publish import BundlePublisher
    from app.runtime.demo_backend import build_demo_backend
    app = create_app(AppSettings(tmp_path, 'fixture-demo-token', 'fake', False), backend_factory=build_demo_backend)
    original = BundlePublisher.publish

    def interrupted(*_, **__):
        raise RuntimeError('fixture interruption after complete staged files')

    monkeypatch.setattr(BundlePublisher, 'publish', interrupted)
    with TestClient(app, headers={'Authorization': 'Bearer fixture-demo-token'}) as client:
        cid = client.post('/v1/conversations', json={'title': 'Restart file delivery'}).json()['id']
        accepted = client.post(f'/v1/conversations/{cid}/turns', json=dict(text='Keep amount 30.', domain='document',
            provider_profile_id='fake-gpt', client_request_id='staged-file', profile_inputs=dict(audience='Reader',
            purpose='Preserve source', source_refs=['input/user_request.txt'], formats=['markdown']))).json()
        task = accepted['task_id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and task_row(app, task)['state'] != 'READY':
            time.sleep(.02)
        assert task_row(app, task)['state'] == 'READY'
        assert client.get(f'/v1/conversations/{cid}/bundles').json()['items'] == []
    monkeypatch.setattr(BundlePublisher, 'publish', original)
    if damaged_published_bundle:
        row = task_row(app, task)
        checkpoint = json.loads(row['checkpoint_json'])
        with closing(app.state.database.connect()) as connection:
            details = json.loads(connection.execute('SELECT details_json FROM checks WHERE id=?',
                (checkpoint['public_release']['review_check_id'],)).fetchone()[0])
        publisher = NativePublisher(app.state.database.path, details['evidence_root'])
        BundlePublisher(app.state.database.path, details['evidence_root']).publish(
            checkpoint['native_document']['bundle_id'], answer_releaser=publisher.publish_in_transaction)
        # Model a mismatched recovery record: a committed bundle must not be
        # treated as evidence that this still-READY task was just published.
        with closing(app.state.database.connect()) as connection:
            connection.execute("UPDATE task_runs SET state='READY' WHERE task_id=?", (task,))
    restored = restart(app)
    if damaged_published_bundle:
        assert task_row(restored, task)['state'] == 'BLOCKED'
        assert restored.state.recovery_results[0]['decision'] == 'blocked_local_publication'
        return
    assert task_row(restored, task)['state'] == 'PUBLISHED'
    with closing(restored.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='artifacts.published'").fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM translation_jobs').fetchone()[0] == 0
    with TestClient(restored, headers={'Authorization': 'Bearer restart-fixture-token'}) as reader:
        card = reader.get(f'/v1/conversations/{cid}/bundles').json()['items'][0]
        assert len(card['artifacts']) == 1 and card['format_pairs'] == []
        artifact = card['artifacts'][0]
        downloaded = reader.get(f'/v1/conversations/{cid}/bundles/{card["bundle_id"]}/artifacts/{artifact["artifact_id"]}/download')
        import hashlib
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact['sha256']
