"""Explicit fixtures verify lease handoff; no model or host-code execution."""
import asyncio
from contextlib import closing
import json

import pytest

from app.providers.fake import FakeProvider
from app.runtime.planning import NativeTaskPlanner, PlanningBlocked
from app.runtime.workflow import Workflow
from app.runtime.native_executor import NativeTaskExecutor
from app.runtime.publication import PublicationBlocked
from app.storage.database import transaction
from app.usage.budgets import check_budget
from test_native_planning import FixturePlannerRuntime, unplanned_case


def case(tmp_path):
    app, manager, task, attempt, owner = unplanned_case(tmp_path)
    runtime = FixturePlannerRuntime()
    plan = asyncio.run(NativeTaskPlanner(app.state.database.path, manager, runtime,
        allow_fixture=True, estimated_tokens=24).plan(task, attempt, owner))
    b = FakeProvider(executions=[dict(text='Verified result: count=3 sum=6 mean=2',
        usage=dict(input_tokens=10, output_tokens=5))])
    a = FakeProvider(reviews=[dict(decision='PASS', criterion_results=dict(AC1=True, AC2=True),
        read_unit_ids=['USER-1'],
        usage=dict(input_tokens=10, output_tokens=5))])
    def validator(candidate):
        return [dict(criterion_id='AC1', passed=True,
            evidence=dict(actual_sha256=candidate.byte_sha256, fixed_fixture=True))]
    workflow = Workflow(app.state.database.path, manager, b, validator, a, check_budget,
        estimated_tokens={'B.execution': 24, 'A.review': 24})
    return app, plan, workflow, b, a, runtime


def test_planning_lease_is_transferred_once_without_resetting_task(tmp_path):
    app, plan, workflow, b, a, runtime = case(tmp_path)
    result = asyncio.run(workflow.run_prepared(plan))
    assert result.state == 'OUTPUT_PREPARING'
    assert len(runtime.starts) == len(b.starts) == len(a.starts) == 1
    with closing(app.state.database.connect()) as connection:
        row = connection.execute('SELECT * FROM task_runs').fetchone()
        checkpoint = json.loads(row['checkpoint_json'])
        assert row['lease_owner'] is None
        assert checkpoint['a_planning']['step_id'] == plan.planning_step_id
        assert connection.execute('SELECT count(*) FROM steps').fetchone()[0] == 3
        states = [json.loads(item[0])['new_state'] for item in connection.execute(
            "SELECT internal_payload_json FROM outbox_events WHERE kind='task.state_changed' ORDER BY rowid")]
    assert states.count('PLANNING') == 1 and 'RECEIVED' not in states
    assert states[-1] == 'OUTPUT_PREPARING'
    with pytest.raises(PlanningBlocked):
        asyncio.run(workflow.run_prepared(plan))
    assert len(b.starts) == len(a.starts) == 1


@pytest.mark.parametrize('change', ['cancel', 'owner', 'expired', 'step'])
def test_invalid_prepared_handoff_never_starts_b(tmp_path, change):
    app, plan, workflow, b, a, _ = case(tmp_path)
    with closing(app.state.database.connect()) as connection, transaction(connection):
        if change == 'cancel':
            connection.execute('UPDATE task_runs SET cancel_requested=1')
        elif change == 'owner':
            connection.execute("UPDATE task_runs SET lease_owner='another-owner'")
        elif change == 'expired':
            connection.execute("UPDATE task_runs SET lease_expires_at='2000-01-01T00:00:00Z'")
        else:
            connection.execute("UPDATE steps SET state='UNKNOWN_REMOTE'")
    with pytest.raises(PlanningBlocked):
        asyncio.run(workflow.run_prepared(plan))
    assert b.starts == a.starts == []


def test_native_executor_publishes_only_reviewed_current_bytes_once(tmp_path):
    app, plan, workflow, b, a, _ = case(tmp_path)
    executor = NativeTaskExecutor(workflow)
    result = asyncio.run(executor.execute(plan))
    release = asyncio.run(executor.publish(plan, result))
    assert release['state'] == 'PUBLISHED'
    assert asyncio.run(executor.publish(plan, result))['state'] == 'PUBLISHED'
    with closing(app.state.database.connect()) as connection:
        public = connection.execute("SELECT public_event_json FROM outbox_events WHERE kind='answer.published'").fetchall()
    assert len(public) == 1
    assert json.loads(public[0][0])['payload']['text'] == 'Verified result: count=3 sum=6 mean=2'
    assert len(b.starts) == len(a.starts) == 1


@pytest.mark.parametrize('change', ['cancel', 'revision', 'planning_owner'])
def test_executor_refuses_stale_or_cancelled_approved_result(tmp_path, change):
    app, plan, workflow, _, _, _ = case(tmp_path)
    executor = NativeTaskExecutor(workflow)
    result = asyncio.run(executor.execute(plan))
    with closing(app.state.database.connect()) as connection, transaction(connection):
        checkpoint = json.loads(connection.execute('SELECT checkpoint_json FROM task_runs').fetchone()[0])
        if change == 'cancel':
            connection.execute('UPDATE task_runs SET cancel_requested=1')
        elif change == 'revision':
            checkpoint['workflow']['current_revision_id'] = 'foreign-revision'
        else:
            checkpoint['planning_handoff']['previous_owner'] = 'foreign-owner'
        connection.execute('UPDATE task_runs SET checkpoint_json=?', (json.dumps(checkpoint),))
    with pytest.raises(PublicationBlocked):
        asyncio.run(executor.publish(plan, result))
    with closing(app.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0


def test_staged_ready_release_can_resume_without_another_model_call(tmp_path, monkeypatch):
    from app.runtime.publication import NativePublisher
    app, plan, workflow, b, a, runtime = case(tmp_path)
    executor = NativeTaskExecutor(workflow)
    result = asyncio.run(executor.execute(plan))
    original = NativePublisher.publish
    def interrupted(*args):
        raise RuntimeError('explicit fixture interruption after durable READY')
    monkeypatch.setattr(NativePublisher, 'publish', interrupted)
    with pytest.raises(RuntimeError):
        asyncio.run(executor.publish(plan, result))
    with closing(app.state.database.connect()) as connection:
        assert connection.execute('SELECT state FROM task_runs').fetchone()[0] == 'READY'
    monkeypatch.setattr(NativePublisher, 'publish', original)
    assert asyncio.run(executor.publish(plan, result))['state'] == 'PUBLISHED'
    assert len(runtime.starts) == len(b.starts) == len(a.starts) == 1
