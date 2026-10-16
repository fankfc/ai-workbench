from datetime import datetime, timezone
import json
import os
import pytest
from integration.test_native_publication import prepared


def test_incident_freeze_and_blob_pin_survive_restart(client):
    from app.operations.controller import OperationsController, assert_publication_allowed
    database = client.app.state.database.path
    blob = client.app.state.blobs.put(b'incident-evidence')
    controller = OperationsController(database)
    incident = controller.record_incident(domains=['paper'], qualification_keys=['old-key'], reason='model version changed plus critical mistranslation', evidence_blobs=[blob.sha256])
    restarted = OperationsController(database)
    assert restarted.route_for('paper', 'old-key') == 'a_led'
    assert restarted.route_for('code', 'unrelated-key') == 'qualified_collaboration'
    with client.app.state.database.connect() as connection:
        assert blob.sha256 in json.dumps(json.loads(connection.execute('SELECT preferences_json FROM desktop_settings').fetchone()[0])['operations'])
        from app.storage.cleanup import preview, cleanup
        plan = preview(connection, client.app.state.blobs)
        assert blob.sha256 not in {row['sha256'] for row in plan['items']}
        with pytest.raises(ValueError, match='CLEANUP_REFERENCE_CHANGED'):
            cleanup(connection, client.app.state.blobs, plan['version'], [blob.sha256])
        with pytest.raises(ValueError, match='INCIDENT_PUBLICATION_FROZEN'):
            assert_publication_allowed(connection, {'task_id': 'paper-task', 'checkpoint_json': '{"task_contract":{"domain":"paper"}}'})
        assert_publication_allowed(connection, {'task_id': 'code-task', 'checkpoint_json': '{"task_contract":{"domain":"code"}}'})
    assert restarted.view()['incidents'][incident]['status'] == 'open'


def test_incident_cannot_resume_from_success_flags_or_stale_evidence(client):
    from app.operations.controller import OperationsController
    controller = OperationsController(client.app.state.database.path)
    incident = controller.record_incident(domains=['paper'], qualification_keys=['old-key'], reason='model change', evidence_blobs=[])
    with pytest.raises(ValueError, match='REQUALIFICATION'):
        controller.requalify(incident, {}, {'eligible': True, 'observed_at': '2000-01-01T00:00:00Z'}, {'domain': 'paper'})
    assert OperationsController(client.app.state.database.path).route_for('paper', 'old-key') == 'a_led'


def test_retention_uses_age_and_pins_and_refuses_stale_plan(client):
    from app.operations.controller import OperationsController
    controller = OperationsController(client.app.state.database.path)
    root = client.app.state.database.path.parent
    directory = root / 'diagnostics/diagnostic_logs'
    directory.mkdir(parents=True)
    old = directory / 'old.json'; protected = directory / 'incident.json'
    old.write_text('{}'); protected.write_text('{}')
    os.utime(old, (1, 1)); os.utime(protected, (1, 1))
    controller.pin_diagnostic('diagnostics/diagnostic_logs/incident.json')
    plan = controller.retention_preview(datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert [row['path'] for row in plan['items']] == ['diagnostics/diagnostic_logs/old.json']
    old.write_text('{"changed":true}')
    with pytest.raises(ValueError, match='RETENTION_SNAPSHOT_STALE'):
        controller.apply_retention(plan, confirmed=True, now=datetime(2026, 10, 14, tzinfo=timezone.utc))
    os.utime(old, (1, 1))
    plan = controller.retention_preview(datetime(2026, 10, 14, tzinfo=timezone.utc))
    result = controller.apply_retention(plan, confirmed=True, now=datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert len(result['removed']) == 1 and protected.exists()


def test_glossary_change_invalidates_real_cache_rows_preserves_history(client):
    from app.operations.controller import OperationsController
    from translation.fakes import claude_turn, service
    import asyncio
    _, task, attempt = claude_turn(client)
    translation = service(client)
    before = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source='保留原文件。', source_language='zh-CN', target_language='en', purpose='input'))
    assert before.status == 'READY'
    with client.app.state.database.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM translation_cache WHERE valid=1').fetchone()[0] == 1
    controller = OperationsController(client.app.state.database.path)
    result = controller.change_glossary(task, 'ops-v1', 'engineering', [{'source':'bank','target':'岸','sense':'river'}], reason='initial term', reviewer='test-only-reviewer')
    assert result['history_preserved']
    with client.app.state.database.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM translation_cache WHERE valid=1').fetchone()[0] == 0
        assert connection.execute('SELECT status FROM translation_jobs WHERE id=?', (before.job_id,)).fetchone()[0] == 'READY'
    revised = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source='保留原文件。', source_language='zh-CN', target_language='en', purpose='input', glossary_version='ops-v1', explicit_retry=True))
    assert revised.status == 'READY' and not revised.cache_hit and revised.job_id != before.job_id
    after = OperationsController(client.app.state.database.path).view()['glossary_changes']
    assert after[-1]['version'] == 'ops-v1' and after[-1]['reviewer'] == 'test-only-reviewer'


def test_publication_freeze_survives_restart_and_unrelated_domain_can_publish(prepared):
    from app.operations.controller import OperationsController
    client, _, task, attempt, _, publisher, _ = prepared
    controller = OperationsController(client.app.state.database.path)
    controller.record_incident(domains=['paper'], qualification_keys=['paper-model-old'], reason='test-only unrelated paper incident', evidence_blobs=[])
    # make_contract in the actual publication fixture selects code.
    approval = publisher.stage(task, attempt, '1.0', 'rev1', 'a-review')
    assert approval
    controller.record_incident(domains=['code'], qualification_keys=['code-model-old'], reason='test-only critical code incident', evidence_blobs=[], task_ids=[task])
    with pytest.raises(ValueError, match='INCIDENT_PUBLICATION_FROZEN'):
        publisher.stage(task, attempt, '1.0', 'rev1', 'a-review')


def test_one_easy_scope_never_thaws_hard_or_unmatched_tasks(client):
    from app.operations.controller import OperationsController, assert_publication_allowed
    from app.quality.eligibility import configuration_key
    controller = OperationsController(client.app.state.database.path)
    incident = controller.record_incident(domains=['code'], qualification_keys=['old-key'], reason='test-only scope regression', evidence_blobs=[])
    easy = {'a_version':'fixture-A', 'b_version':'fixture-B', 'domain':'code', 'difficulty':'easy', 'task_profile':'fixture-profile', 'translation_policy':'fixture-policy', 'glossary_version':'fixture-v1', 'scheduling_policy':'fixture-scheduling', 'protocol_hash':'fixture-protocol'}
    hard = {**easy, 'difficulty':'hard'}
    easy_key, hard_key = configuration_key(easy), configuration_key(hard)
    # Private temporary fixture only: public requalify cannot accept this data.
    controller._edit(lambda connection, value: value['incidents'][incident]['requalified_scopes'].update({easy_key:{'configuration':easy, 'source_kind':'test_fixture'}}))
    restarted = OperationsController(client.app.state.database.path)
    assert restarted.route_for('code',easy_key) == 'qualified_collaboration'
    assert restarted.route_for('code',hard_key) == 'a_led'
    with client.app.state.database.connect() as connection:
        task = {'task_id':'test-only', 'checkpoint_json':json.dumps({'task_contract':{'domain':'code'}, 'optimization_configuration':easy, 'optimization_qualification_key':easy_key})}
        assert_publication_allowed(connection, task)
        task['checkpoint_json'] = json.dumps({'task_contract':{'domain':'code'}, 'optimization_configuration':hard, 'optimization_qualification_key':hard_key})
        with pytest.raises(ValueError, match='INCIDENT_PUBLICATION_FROZEN'):
            assert_publication_allowed(connection, task)
    assert restarted.view()['incidents'][incident]['status'] == 'open'


def test_retention_defaults_are_configurable_and_survive_restart(client):
    from app.operations.controller import OperationsController
    controller = OperationsController(client.app.state.database.path)
    policy = {'diagnostic_logs':30, 'runtime_events':180, 'usage_summaries':365}
    controller.set_retention(policy)
    assert OperationsController(client.app.state.database.path).retention_preview()['retention_days'] == policy
    with pytest.raises(ValueError, match='RETENTION_POLICY_INVALID'):
        controller.set_retention({**policy, 'conversations':1})
    with pytest.raises(ValueError, match='RETENTION_POLICY_INVALID'):
        controller.set_retention({**policy, 'diagnostic_logs':True})
