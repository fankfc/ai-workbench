"""Synthetic A captures exercise real storage/leases; no native model launches."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.application import create_app
from app.config import AppSettings
from app.contracts.tasks import contract_digest, validate_contract
from app.runtime.planning import PreparedPlan, PlanningBlocked, validate_prepared_plan, NativeTaskPlanner
from app.providers.phase_bridge import PhaseStarted, PhaseCapture, PhaseUsage, UsageReceipt
from app.contracts.providers import ProviderContract
from app.runtime.workspace import WorkspaceManager
from app.storage.database import transaction
from support.contracts import make_contract


def prepared_case(tmp_path):
    app = create_app(AppSettings(tmp_path, 'fixture-planning-api-token', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer fixture-planning-api-token'
        conversation = client.post('/v1/conversations', json={'title': 'explicit planning fixture'}).json()['id']
        accepted = client.post(f'/v1/conversations/{conversation}/turns', json={
            'text': 'Input fixture: [1,2,3]', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'same-request'}).json()
    database, manager = app.state.database, WorkspaceManager(tmp_path)
    with closing(database.connect()) as connection:
        row = dict(connection.execute('SELECT * FROM task_runs WHERE task_id=?', (accepted['task_id'],)).fetchone())
    task, attempt = row['task_id'], row['attempt_id']
    workspace = manager.create(task, attempt)
    data = b'Input fixture: [1,2,3]'
    path = workspace.ingest_source('user_request.txt', data)
    value = make_contract(task, attempt, json.loads(row['route_snapshot_json'])['id'], 'mixed')
    value['inputs'] = [dict(id='USER-1', ref='input/user_request.txt', sha256=hashlib.sha256(data).hexdigest())]
    value['source_unit_ids'] = ['USER-1']
    value['deliverables'][0]['require_a_canonical'] = False
    contract = validate_contract(value)
    raw = json.dumps(value, sort_keys=True).encode()
    digest, step, owner = hashlib.sha256(raw).hexdigest(), uuid4().hex, 'planning:' + uuid4().hex
    app.state.blobs.put(raw)
    plan = PreparedPlan(contract, owner, step, digest, 'blob:sha256:' + digest,
        {item.ref: item.sha256 for item in contract.inputs}, 'fixture')
    planning = dict(status='completed', owner_token=owner, step_id=step,
        contract_sha256=contract_digest(contract), capture_sha256=digest,
        raw_response_ref=plan.raw_response_ref, source_hashes=dict(plan.source_hashes),
        classification='fixture', model_identity_observed=True, usage_observed=True)
    with closing(database.connect()) as connection, transaction(connection):
        connection.execute("INSERT INTO steps(id,task_id,attempt_id,step_key,role,state,contract_version,provider_profile_id,external_request_id,checkpoint_json,completed_at) VALUES(?,?,?,?,'A','COMPLETED','1.0','fake-gpt',?,?,?)",
            (step, task, attempt, step, step, json.dumps({'a_planning': planning}), datetime.now(timezone.utc).isoformat()))
        connection.execute("UPDATE task_runs SET state='PLANNING',lease_owner=?,lease_expires_at=?,checkpoint_json=? WHERE task_id=? AND attempt_id=?",
            (owner, (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
             json.dumps({'a_planning': planning, 'task_contract': value}), task, attempt))
    return app, manager, plan, path


def test_verified_prepared_plan_preserves_planning_lease(tmp_path):
    app, manager, plan, _ = prepared_case(tmp_path)
    checked = validate_prepared_plan(app.state.database.path, manager, plan)
    assert checked.contract == plan.contract
    with closing(app.state.database.connect()) as connection:
        row = connection.execute('SELECT state,lease_owner FROM task_runs WHERE task_id=?', (plan.contract.task_id,)).fetchone()
    assert tuple(row) == ('PLANNING', plan.owner_token)


@pytest.mark.parametrize('case', ['owner', 'cancel', 'expired', 'state', 'step', 'hash', 'source', 'fixture_escape'])
def test_tampered_planning_handoff_cannot_start_b(tmp_path, case):
    app, manager, plan, path = prepared_case(tmp_path)
    with closing(app.state.database.connect()) as connection, transaction(connection):
        if case == 'owner':
            connection.execute("UPDATE task_runs SET lease_owner='another-owner'")
        elif case == 'cancel':
            connection.execute('UPDATE task_runs SET cancel_requested=1')
        elif case == 'expired':
            connection.execute("UPDATE task_runs SET lease_expires_at='2000-01-01T00:00:00+00:00'")
        elif case == 'state':
            connection.execute("UPDATE task_runs SET state='FAILED'")
        elif case == 'step':
            connection.execute("UPDATE steps SET state='UNKNOWN_REMOTE'")
        elif case == 'hash':
            checkpoint = json.loads(connection.execute('SELECT checkpoint_json FROM task_runs').fetchone()[0])
            checkpoint['a_planning']['capture_sha256'] = '0' * 64
            connection.execute('UPDATE task_runs SET checkpoint_json=?', (json.dumps(checkpoint),))
    if case == 'fixture_escape':
        plan = replace(plan, classification='production')
    if case == 'source':
        path.chmod(0o600)
        path.write_bytes(b'changed input')
    with pytest.raises(PlanningBlocked):
        validate_prepared_plan(app.state.database.path, manager, plan)


def test_handoff_source_map_is_immutable(tmp_path):
    _, _, plan, _ = prepared_case(tmp_path)
    with pytest.raises(TypeError):
        plan.source_hashes['input/user_request.txt'] = '0' * 64


def test_api_request_domain_is_durable_and_idempotent(tmp_path):
    app = create_app(AppSettings(tmp_path, 'fixture-planning-api-token', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer fixture-planning-api-token'
        conversation = client.post('/v1/conversations', json={'title': 'domain context fixture'}).json()['id']
        endpoint = f'/v1/conversations/{conversation}/turns'
        body = dict(text='Compute [1,2,3]', provider_profile_id='fake-gpt', client_request_id='domain-1', domain='code')
        first = client.post(endpoint, json=body)
        assert first.status_code == 202
        assert client.post(endpoint, json=body).json() == first.json()
        assert client.post(endpoint, json={**body, 'domain': 'paper'}).status_code == 409
        assert client.post(endpoint, json={**body, 'client_request_id': 'invalid', 'domain': 'unknown'}).status_code == 422
    with closing(app.state.database.connect()) as connection:
        checkpoint = json.loads(connection.execute('SELECT checkpoint_json FROM task_runs').fetchone()[0])
        assert connection.execute('SELECT count(*) FROM task_runs').fetchone()[0] == 1
    assert checkpoint['request_domain'] == 'code'


class FixturePlannerRuntime:
    classification = 'fixture'
    provider = ProviderContract.model_validate(dict(schema_version='1.0', provider_id='fake-gpt',
        identity=dict(adapter='fake', model_id='fixture-gpt', family='gpt', connection_id='fake-gpt'),
        identity_status='verified', identity_source='explicit synthetic planning fixture', connection_version='test-only'))

    def __init__(self, case='normal'):
        self.case, self.starts = case, []

    async def invoke_text(self, text, **kwargs):
        self.starts.append(kwargs)
        context = json.loads(text)
        fixed = context['required_contract_fields']
        value = make_contract(fixed['task_id'], fixed['attempt_id'], fixed['route_snapshot_id'], fixed['domain'])
        value.update(fixed)
        value['budget'] = dict(total_tokens=300000, reserved_a_tokens=60000)
        value['deliverables'][0]['require_a_canonical'] = False
        if self.case == 'source_lie':
            value['inputs'][0]['sha256'] = '0' * 64
        if self.case == 'wrong_route':
            value['route_snapshot_id'] = 'foreign-route'
        request_id = kwargs['request_id']
        if self.case == 'disconnect_before_refs':
            raise ConnectionError('explicit submission outcome unknown fixture')
        yield PhaseStarted(request_id, 'fixture-server-response', 'fixture-native-turn')
        if self.case == 'disconnect':
            raise ConnectionError('private fixture disconnect text must not leak')
        receipts = () if self.case == 'unknown_usage' else (
            UsageReceipt('fixture-receipt', 1, dict(input_tokens=10, output_tokens=5), 'reported'),)
        if self.case == 'billable_failure':
            yield PhaseUsage(request_id, self.provider, 'fixture-server-response', 'fixture-native-turn', receipts)
            raise ConnectionError('explicit fixture trailing failure')
        yield PhaseCapture(request_id, self.provider, json.dumps(value),
            'fixture-server-response', 'fixture-native-turn', receipts)


def unplanned_case(tmp_path):
    app = create_app(AppSettings(tmp_path, 'fixture-planning-api-token', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer fixture-planning-api-token'
        conversation = client.post('/v1/conversations', json={'title': 'native planner fixture'}).json()['id']
        response = client.post(f'/v1/conversations/{conversation}/turns', json=dict(
            text='Compute [1,2,3]', domain='mixed', provider_profile_id='fake-gpt', client_request_id='plan-1')).json()
    owner = 'planning:' + uuid4().hex
    with closing(app.state.database.connect()) as connection, transaction(connection):
        row = dict(connection.execute('SELECT * FROM task_runs WHERE task_id=?', (response['task_id'],)).fetchone())
        connection.execute("UPDATE task_runs SET state='INPUT_PREPARING',lease_owner=?,lease_expires_at=? WHERE task_id=?",
            (owner, (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(), row['task_id']))
    return app, WorkspaceManager(tmp_path), row['task_id'], row['attempt_id'], owner


def test_actual_fixture_a_planning_is_durable_and_metered(tmp_path):
    import asyncio
    app, manager, task, attempt, owner = unplanned_case(tmp_path)
    runtime = FixturePlannerRuntime()
    planner = NativeTaskPlanner(app.state.database.path, manager, runtime, allow_fixture=True, estimated_tokens=24)
    plan = asyncio.run(planner.plan(task, attempt, owner))
    assert validate_prepared_plan(app.state.database.path, manager, plan) == plan
    assert len(runtime.starts) == 1
    with closing(app.state.database.connect()) as connection:
        row = connection.execute('SELECT state,lease_owner FROM task_runs WHERE task_id=?', (task,)).fetchone()
        steps = connection.execute('SELECT role,state FROM steps WHERE task_id=?', (task,)).fetchall()
        entries = connection.execute('SELECT details_json FROM usage_entries WHERE task_id=?', (task,)).fetchall()
    assert tuple(row) == ('PLANNING', owner)
    assert [tuple(step) for step in steps] == [('A', 'COMPLETED')]
    assert len(entries) == 1 and json.loads(entries[0][0])['total_tokens'] == 15


@pytest.mark.parametrize('case', ['source_lie', 'wrong_route', 'unknown_usage', 'disconnect'])
def test_failed_native_a_planning_retains_intent_and_never_hands_off(tmp_path, case):
    import asyncio
    app, manager, task, attempt, owner = unplanned_case(tmp_path)
    runtime = FixturePlannerRuntime(case)
    planner = NativeTaskPlanner(app.state.database.path, manager, runtime, allow_fixture=True, estimated_tokens=24)
    with pytest.raises(PlanningBlocked):
        asyncio.run(planner.plan(task, attempt, owner))
    assert len(runtime.starts) == 1
    with closing(app.state.database.connect()) as connection:
        row = dict(connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone())
        assert connection.execute('SELECT count(*) FROM steps WHERE task_id=?', (task,)).fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM usage_entries WHERE task_id=?', (task,)).fetchone()[0] == 1
    assert row['state'] == 'BLOCKED'
    assert json.loads(row['checkpoint_json']).get('a_planning', {}).get('status') != 'completed'


def test_fixture_cannot_enter_real_planning_lane(tmp_path):
    import asyncio
    app, manager, task, attempt, owner = unplanned_case(tmp_path)
    runtime = FixturePlannerRuntime()
    planner = NativeTaskPlanner(app.state.database.path, manager, runtime)
    with pytest.raises(PlanningBlocked):
        asyncio.run(planner.plan(task, attempt, owner))
    assert runtime.starts == []


def test_planning_disconnect_without_refs_retains_possible_remote_submission(tmp_path):
    import asyncio
    app, manager, task, attempt, owner = unplanned_case(tmp_path)
    runtime = FixturePlannerRuntime('disconnect_before_refs')
    planner = NativeTaskPlanner(app.state.database.path, manager, runtime, allow_fixture=True, estimated_tokens=24)
    with pytest.raises(PlanningBlocked):
        asyncio.run(planner.plan(task, attempt, owner))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer fixture-planning-api-token'
        response = client.post(f'/v1/tasks/{task}/cancel')
        assert response.status_code == 202
        assert response.json()['cancel_pending_remote'] is True
        assert response.json()['external_stop_confirmed'] is None
    with closing(app.state.database.connect()) as connection:
        row = connection.execute('SELECT * FROM task_runs').fetchone()
    possible = json.loads(row['checkpoint_json'])['active_external_request']
    assert possible['submission_possible'] is True and possible['accepted'] is False
    assert possible['external_request_id'] is None and possible['external_execution_id'] is None


def test_planning_failed_transport_keeps_authenticated_reported_billing(tmp_path):
    import asyncio
    app, manager, task, attempt, owner = unplanned_case(tmp_path)
    planner = NativeTaskPlanner(app.state.database.path, manager, FixturePlannerRuntime('billable_failure'),
        allow_fixture=True, estimated_tokens=24)
    with pytest.raises(PlanningBlocked):
        asyncio.run(planner.plan(task, attempt, owner))
    with closing(app.state.database.connect()) as connection:
        usage = json.loads(connection.execute('SELECT details_json FROM usage_entries').fetchone()[0])
        state = connection.execute('SELECT state FROM task_runs').fetchone()[0]
    assert state == 'BLOCKED'
    assert usage['total_tokens'] == 15 and usage['source'] == 'reported' and usage['status'] == 'failed'
