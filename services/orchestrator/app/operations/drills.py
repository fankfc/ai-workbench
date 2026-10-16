"""Deterministic, isolated probes of actual product cleanup and cancellation.

These results are local regression evidence, never desktop/user/model qualification.
The API owns business states. There is no independent operations state machine.
"""
import json
import os
from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.operations.feedback import build_feedback
from app.runtime.escalation import choose_escalation
from app.runtime.publication import NativePublisher, PublicationBlocked
from app.storage.cleanup import preview, cleanup
from app.translation.cache import cache_key
from app.translation.glossary import GlossaryStore
from app.operations.controller import OperationsController, assert_publication_allowed


def _task(client):
    conversation = client.post('/v1/conversations', json={'title': 'Operations isolated regression'}).json()['id']
    response = client.post(f'/v1/conversations/{conversation}/turns', json={'text': 'Preserve local operations evidence.', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'operations-probe'})
    response.raise_for_status()
    return conversation, response.json()['task_id']


def retention_glossary(root):
    app = create_app(AppSettings(root / 'product', 'operations-test-token', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer operations-test-token'
        conversation, task = _task(client)
        before = client.get(f'/v1/conversations/{conversation}/messages').json()
        store = app.state.blobs
        blob = store.put(b'active-evidence-canary')
        os.utime(store.path_for(blob.sha256), (1, 1))
        with app.state.database.connect() as connection:
            row = connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone()
            checkpoint = json.loads(row['checkpoint_json'])
            checkpoint['operations_evidence_ref'] = store.uri_for(blob.sha256)
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?', (json.dumps(checkpoint), task))
            view = preview(connection, store)
            try:
                cleanup(connection, store, view['version'], [blob.sha256])
            except ValueError:
                pass
            else:
                raise AssertionError('ACTIVE_EVIDENCE_WAS_CLEANABLE')
        glossary = GlossaryStore(app.state.database.path)
        controller = OperationsController(app.state.database.path)
        controller.change_glossary(task, 'ops-v1', 'engineering', [{'source': 'bank', 'target': '岸', 'sense': 'river edge'}], reason='fixture reviewer: initial term', reviewer='test-only-reviewer')
        old = glossary.snapshot(task, 'ops-v1')
        controller.change_glossary(task, 'ops-v2', 'engineering', [{'source': 'bank', 'target': '堤岸', 'sense': 'river edge'}], reason='fixture reviewer: revised term', reviewer='test-only-reviewer')
        new = glossary.snapshot(task, 'ops-v2')
        values = dict(task_id=task, source_sha256=blob.sha256, direction='en-zh', context_sha256=blob.sha256,
                      glossary_domain='engineering', policy_version='1', translator_model_version='fixture-GLM')
        old_key = cache_key(**values, glossary_version='ops-v1', glossary_content_sha256=old.content_sha256)
        new_key = cache_key(**values, glossary_version='ops-v2', glossary_content_sha256=new.content_sha256)
        after = client.get(f'/v1/conversations/{conversation}/messages').json()
        retained = glossary.snapshot(task, 'ops-v1') == old and before == after and store.read(blob.sha256) == b'active-evidence-canary'
    diagnostics = build_feedback(root / 'diagnostic-probe')
    return dict(deleted_active_evidence=not store.path_for(blob.sha256).is_file(), secret_leaks=diagnostics['secret_leaks'],
                cache_reused_after_glossary_change=old_key == new_key, history_preserved=retained,
                evidence_kind='deterministic_product_probe', cleanup_blocked=view['blocked'],
                blocked_reasons=['monthly_restore_and_real_bilingual_review_not_executed'])


def incident_rollback(root):
    app = create_app(AppSettings(root / 'product', 'incident-test-token', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer incident-test-token'
        _, task = _task(client)
        preserved = app.state.blobs.put(b'model-change-and-mistranslation-fixture')
        with app.state.database.connect() as connection:
            row = connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone()
            route = row['route_snapshot_json']
            attempt, version = row['attempt_id'], row['contract_version']
            checkpoint = json.loads(row['checkpoint_json'])
            checkpoint['incident_evidence_ref'] = app.state.blobs.uri_for(preserved.sha256)
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?', (json.dumps(checkpoint), task))
        plan = choose_escalation({'capability_missing': True, 'evidence_gap': True})
        controller = OperationsController(app.state.database.path)
        incident = controller.record_incident(domains=['paper'], qualification_keys=['fixture-old-model'], reason='test-only model-change plus mistranslation drill', evidence_blobs=[preserved.sha256], task_ids=[task])
        restarted = OperationsController(app.state.database.path)
        with app.state.database.connect() as connection:
            try:
                assert_publication_allowed(connection, row)
            except ValueError:
                persistent_fence = True
            else:
                persistent_fence = False
        cancelled = client.post(f'/v1/tasks/{task}/cancel')
        cancelled.raise_for_status()
        try:
            NativePublisher(app.state.database.path, root / 'product/evidence').publish(task, attempt, version)
        except PublicationBlocked:
            stopped = True
        else:
            stopped = False
        with app.state.database.connect() as connection:
            row = connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone()
            view = preview(connection, app.state.blobs)
            kept = app.state.blobs.read(preserved.sha256) == b'model-change-and-mistranslation-fixture' and not view['items']
            provider_switched = row['route_snapshot_json'] != route
    return dict(optimization_disabled=restarted.route_for('paper', 'fixture-old-model') == 'a_led', affected_publication_stopped=stopped and persistent_fence,
                provider_switched=provider_switched, evidence_preserved=kept,
                resume_requires_requalification=restarted.view()['incidents'][incident]['status'] == 'open',
                evidence_kind='deterministic_product_probe',
                blocked_reasons=['desktop_drill_signed_rollback_and_real_model_requalification_not_executed'])
