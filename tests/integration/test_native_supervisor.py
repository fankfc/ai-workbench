"""Real API/SQLite/planner fixture ports; no CLI, auth or model invocation."""
import asyncio
from contextlib import closing
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.application import create_app
from app.config import AppSettings
from app.runtime.planning import NativeTaskPlanner
from app.runtime.supervisor import NativeBackendBindings, SupervisorError, TaskSupervisor
from app.runtime.workspace import WorkspaceManager
from app.storage.database import transaction
from test_native_planning import FixturePlannerRuntime


class FixtureSupervisorRuntime(FixturePlannerRuntime):
    async def invoke_text(self, text, **kwargs):
        from app.providers.phase_bridge import PhaseStarted, PhaseCapture
        async for event in super().invoke_text(text, **kwargs):
            if isinstance(event, (PhaseStarted, PhaseCapture)):
                event = replace(event, external_request_id='fixture-response-' + kwargs['request_id'],
                    external_execution_id='fixture-turn-' + kwargs['request_id'])
            yield event


def fixture_case(tmp_path, case='normal'):
    settings = AppSettings(tmp_path, 'fixture-supervisor-token', 'fake', False)
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + settings.api_token
        conversation = client.post('/v1/conversations', json={'title': 'durable supervisor fixture'}).json()['id']
        accepted = client.post(f'/v1/conversations/{conversation}/turns', json=dict(text='Compute [1,2,3]',
            domain='mixed', provider_profile_id='fake-gpt', client_request_id='same-request')).json()
    runtime = FixtureSupervisorRuntime(case)
    planner = NativeTaskPlanner(app.state.database.path, WorkspaceManager(tmp_path), runtime,
        allow_fixture=True, estimated_tokens=24)
    calls = {'execute': [], 'publish': [], 'cancel': []}

    async def execute(plan):
        calls['execute'].append(plan)
        with closing(app.state.database.connect()) as connection, transaction(connection):
            connection.execute("UPDATE task_runs SET state='OUTPUT_PREPARING' WHERE task_id=?", (plan.contract.task_id,))
        return SimpleNamespace(state='OUTPUT_PREPARING')

    async def publish(plan, result):
        calls['publish'].append(plan)
        with closing(app.state.database.connect()) as connection, transaction(connection):
            connection.execute("UPDATE task_runs SET state='PUBLISHED' WHERE task_id=?", (plan.contract.task_id,))
        return SimpleNamespace(state='PUBLISHED')

    async def cancel(task, attempt):
        calls['cancel'].append((task, attempt))

    port = SimpleNamespace(provider=runtime.provider, scope_capability=SimpleNamespace(require_verified=lambda _: None))
    bindings = NativeBackendBindings({'fake-gpt': port}, planner, execute, publish, cancel, 'fixture')
    supervisor = TaskSupervisor(app.state.database.path, bindings, provider_mode='fake')
    return app, accepted['task_id'], runtime, calls, bindings, supervisor


def task_row(app, task):
    with closing(app.state.database.connect()) as connection:
        return dict(connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone())


def test_atomic_claim_is_durable_and_distinct_supervisors_cannot_reclaim(tmp_path):
    app, task, _, _, bindings, supervisor = fixture_case(tmp_path)
    claimed = supervisor.claim()
    assert claimed['task_id'] == task
    row = task_row(app, task)
    assert row['state'] == 'INPUT_PREPARING' and row['lease_owner'] == claimed['owner_token']
    assert json.loads(row['checkpoint_json'])['supervisor']['owner_token'] == claimed['owner_token']
    assert TaskSupervisor(app.state.database.path, bindings, provider_mode='fake').claim() is None
    with closing(app.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='task.state_changed'").fetchone()[0] == 1


def test_dispatch_uses_real_a_planning_then_handoff_and_never_runs_twice(tmp_path):
    app, task, runtime, calls, bindings, supervisor = fixture_case(tmp_path)
    asyncio.run(supervisor.run_once())
    assert len(runtime.starts) == len(calls['execute']) == len(calls['publish']) == 1
    assert task_row(app, task)['state'] == 'PUBLISHED'
    asyncio.run(TaskSupervisor(app.state.database.path, bindings, provider_mode='fake').run_once())
    assert len(runtime.starts) == 1


@pytest.mark.parametrize('case', ['cancelled', 'unknown', 'old_attempt', 'leased'])
def test_queue_fences_prevent_any_start(tmp_path, case):
    app, task, runtime, calls, _, supervisor = fixture_case(tmp_path)
    with closing(app.state.database.connect()) as connection, transaction(connection):
        if case == 'cancelled':
            connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1")
        elif case == 'unknown':
            connection.execute("UPDATE task_runs SET remote_status='unknown',external_execution_id='old-remote'")
        elif case == 'leased':
            connection.execute("UPDATE task_runs SET lease_owner='old-worker',lease_expires_at='2000-01-01T00:00:00+00:00'")
        else:
            row = task_row(app, task)
            connection.execute("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,attempt_number,route_snapshot_json) VALUES(?, 'new-attempt', ?, 'fake-gpt','BLOCKED',2,?)",
                (task, row['turn_id'], row['route_snapshot_json']))
    asyncio.run(supervisor.run_once())
    assert runtime.starts == [] and calls['execute'] == calls['publish'] == []


def test_disconnect_retains_unknown_remote_and_does_not_restart_on_new_supervisor(tmp_path):
    app, task, runtime, calls, bindings, supervisor = fixture_case(tmp_path, 'disconnect')
    asyncio.run(supervisor.run_once())
    row = task_row(app, task)
    assert row['state'] == 'BLOCKED' and row['remote_status'] == 'unknown'
    assert len(runtime.starts) == 1 and calls['execute'] == calls['publish'] == []
    asyncio.run(TaskSupervisor(app.state.database.path, bindings, provider_mode='fake').run_once())
    assert len(runtime.starts) == 1


def test_fixture_registry_cannot_enter_real_application(tmp_path):
    app, _, _, _, bindings, _ = fixture_case(tmp_path)
    with pytest.raises(SupervisorError):
        TaskSupervisor(app.state.database.path, bindings, provider_mode='real')


def test_unqualified_port_is_not_a_registry_boolean(tmp_path):
    app, _, _, _, bindings, _ = fixture_case(tmp_path)
    value = NativeBackendBindings({'fake-gpt': {'scope_enforced': True}}, bindings.planner,
        bindings.execute, bindings.publish, bindings.cancel, 'production')
    with pytest.raises(SupervisorError):
        TaskSupervisor(app.state.database.path, value, provider_mode='real')


def test_planner_return_is_revalidated_before_execute(tmp_path):
    app, task, runtime, calls, bindings, _ = fixture_case(tmp_path)
    original = bindings.planner.plan
    async def cancelled_after_plan(*args):
        plan = await original(*args)
        with closing(app.state.database.connect()) as connection, transaction(connection):
            connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1,lease_owner=NULL")
        return plan
    bindings.planner.plan = cancelled_after_plan
    supervisor = TaskSupervisor(app.state.database.path, bindings, provider_mode='fake')
    asyncio.run(supervisor.run_once())
    assert len(runtime.starts) == 1 and calls['execute'] == calls['publish'] == []
    assert task_row(app, task)['state'] == 'CANCELLED'


def test_api_without_factory_keeps_empty_registry_and_does_not_dispatch(tmp_path):
    app, task, runtime, _, _, _ = fixture_case(tmp_path)
    assert app.state.provider_registry == {}
    assert task_row(app, task)['state'] == 'RECEIVED' and runtime.starts == []


def test_api_lifespan_injects_explicit_fixture_backend_and_stops_cleanly(tmp_path):
    import time
    app, _, runtime, calls, bindings, _ = fixture_case(tmp_path)
    connected = create_app(app.state.settings, backend_factory=lambda _: bindings)
    with TestClient(connected) as client:
        client.headers['Authorization'] = 'Bearer ' + app.state.settings.api_token
        conversation = client.post('/v1/conversations', json={'title': 'lifespan fixture'}).json()['id']
        accepted = client.post(f'/v1/conversations/{conversation}/turns', json=dict(text='Compute [1,2,3]',
            domain='mixed', provider_profile_id='fake-gpt', client_request_id='lifespan')).json()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and task_row(connected, accepted['task_id'])['state'] != 'PUBLISHED':
            time.sleep(.01)
        assert task_row(connected, accepted['task_id'])['state'] == 'PUBLISHED'
        assert connected.state.provider_registry['fake-gpt'].provider == runtime.provider
    assert connected.state.supervisor_task.done()


def test_cancellation_during_planning_signals_the_actual_backend_and_never_executes(tmp_path):
    app, task, _, calls, bindings, supervisor = fixture_case(tmp_path)
    entered, released = asyncio.Event(), asyncio.Event()
    original = bindings.planner.plan
    async def waiting(*args):
        entered.set()
        await released.wait()
        return await original(*args)
    bindings.planner.plan = waiting
    original_cancel = bindings.cancel
    async def cancel_and_release(*args):
        await original_cancel(*args)
        released.set()
    replacement = NativeBackendBindings(dict(bindings.provider_registry), bindings.planner,
        bindings.execute, bindings.publish, cancel_and_release, 'fixture')
    supervisor = TaskSupervisor(app.state.database.path, replacement, provider_mode='fake')
    async def exercise():
        task_run = asyncio.create_task(supervisor.run_once())
        await entered.wait()
        with closing(app.state.database.connect()) as connection, transaction(connection):
            connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1,lease_owner=NULL")
        await asyncio.wait_for(task_run, 1)
    asyncio.run(exercise())
    assert len(calls['cancel']) == 1 and calls['execute'] == calls['publish'] == []
    assert task_row(app, task)['state'] == 'CANCELLED'


@pytest.mark.parametrize('cleanup', ['returned', 'failed'])
def test_cancel_ends_unresponsive_local_wait_and_allows_next_task_without_remote_restart(tmp_path, cleanup):
    app, task, runtime, calls, bindings, _ = fixture_case(tmp_path)
    entered, interrupted = asyncio.Event(), asyncio.Event()
    original = bindings.planner.plan
    async def waiting(task_id, *args):
        if task_id != task:
            return await original(task_id, *args)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            interrupted.set()
    bindings.planner.plan = waiting
    async def cancel(task_id, attempt_id):
        calls['cancel'].append((task_id, attempt_id))
        if cleanup == 'failed':
            raise RuntimeError('fixture local cleanup failed')
    replacement = NativeBackendBindings(dict(bindings.provider_registry), bindings.planner,
        bindings.execute, bindings.publish, cancel, 'fixture')
    supervisor = TaskSupervisor(app.state.database.path, replacement, provider_mode='fake')
    async def exercise():
        running = asyncio.create_task(supervisor.run_once())
        try:
            await entered.wait()
            with TestClient(app) as client:
                client.headers['Authorization'] = 'Bearer ' + app.state.settings.api_token
                with closing(app.state.database.connect()) as connection, transaction(connection):
                    connection.execute("UPDATE task_runs SET external_request_id='accepted-remote',remote_status='unknown' WHERE task_id=?", (task,))
                    conversation = connection.execute('SELECT conversation_id FROM turns WHERE task_id=?', (task,)).fetchone()[0]
                cancelled = client.post(f'/v1/tasks/{task}/cancel').json()
                assert cancelled['cancel_pending_remote'] is True
                next_task = client.post(f'/v1/conversations/{conversation}/turns', json=dict(text='Compute [4,5,6]',
                    domain='mixed', provider_profile_id='fake-gpt', client_request_id='next-request')).json()['task_id']
            finished, _ = await asyncio.wait({running}, timeout=.5)
            assert running in finished, 'cancel left the local planner wait holding the dispatcher'
            assert await running is None
            assert interrupted.is_set() and not supervisor._operation.locked()
            row = task_row(app, task)
            assert row['state'] == 'CANCELLED' and row['cancel_pending_remote'] == 1
            assert row['external_stop_confirmed'] is None and row['remote_status'] == 'unknown'
            assert len(calls['cancel']) == 1 and not runtime.starts
            await supervisor.run_once()
            assert task_row(app, next_task)['state'] == 'PUBLISHED'
            assert len(runtime.starts) == len(calls['execute']) == len(calls['publish']) == 1
            assert len(calls['cancel']) == 1
        finally:
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)
    asyncio.run(exercise())


def test_shutdown_interrupts_local_wait_without_requeueing_the_claim(tmp_path):
    app, task, _, calls, bindings, supervisor = fixture_case(tmp_path)
    entered = asyncio.Event()
    async def waiting(*_):
        entered.set()
        await asyncio.Event().wait()
    bindings.planner.plan = waiting
    async def exercise():
        task_run = asyncio.create_task(supervisor.run_once())
        await entered.wait()
        await supervisor.shutdown()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task_run, .25)
    asyncio.run(exercise())
    assert len(calls['cancel']) == 1
    row = task_row(app, task)
    assert row['state'] == 'BLOCKED' and row['lease_owner'] is None


@pytest.mark.parametrize('cleanup_result', ['returned', 'failed'])
def test_shutdown_waits_for_inflight_user_cancel_cleanup_without_interrupting_it(tmp_path, cleanup_result):
    app, task, _, calls, bindings, _ = fixture_case(tmp_path)
    entered, cleanup_entered, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleanup_done, cleanup_aborted = asyncio.Event(), asyncio.Event()
    async def waiting(*_):
        entered.set()
        await asyncio.Event().wait()
    bindings.planner.plan = waiting
    async def cancel(task_id, attempt_id):
        calls['cancel'].append((task_id, attempt_id))
        cleanup_entered.set()
        try:
            await release_cleanup.wait()
            cleanup_done.set()
            if cleanup_result == 'failed':
                raise RuntimeError('fixture cleanup failure after release')
        except asyncio.CancelledError:
            cleanup_aborted.set()
            raise
    replacement = NativeBackendBindings(dict(bindings.provider_registry), bindings.planner,
        bindings.execute, bindings.publish, cancel, 'fixture')
    supervisor = TaskSupervisor(app.state.database.path, replacement, provider_mode='fake')
    async def exercise():
        running = asyncio.create_task(supervisor.run_once())
        stopping = None
        try:
            await entered.wait()
            with closing(app.state.database.connect()) as connection, transaction(connection):
                connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1,cancel_pending_remote=1,remote_status='unknown',lease_owner=NULL WHERE task_id=?", (task,))
            await cleanup_entered.wait()
            stopping = asyncio.create_task(supervisor.shutdown())
            finished, _ = await asyncio.wait({stopping}, timeout=.05)
            assert stopping not in finished, 'shutdown skipped cleanup that was still in progress'
            assert len(calls['cancel']) == 1
            release_cleanup.set()
            await asyncio.wait_for(stopping, 1)
            await asyncio.gather(running, return_exceptions=True)
            assert cleanup_done.is_set() and not cleanup_aborted.is_set()
            assert len(calls['cancel']) == 1 and not supervisor._operation.locked()
            expected = ['NATIVE_LOCAL_CLEANUP_UNCONFIRMED'] if cleanup_result == 'failed' else []
            assert supervisor.diagnostics == expected
            row = task_row(app, task)
            assert row['state'] == 'CANCELLED' and row['cancel_pending_remote'] == 1
            assert row['remote_status'] == 'unknown' and row['external_stop_confirmed'] is None
        finally:
            release_cleanup.set()
            if stopping is not None:
                await asyncio.gather(stopping, return_exceptions=True)
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)
    asyncio.run(exercise())


def test_foreign_owner_after_plan_is_not_clobbered_by_old_dispatcher(tmp_path):
    app, task, _, calls, bindings, supervisor = fixture_case(tmp_path)
    original = bindings.planner.plan
    async def replaced(*args):
        plan = await original(*args)
        with closing(app.state.database.connect()) as connection, transaction(connection):
            connection.execute("UPDATE task_runs SET lease_owner='new-private-owner'")
        return plan
    bindings.planner.plan = replaced
    asyncio.run(supervisor.run_once())
    assert calls['execute'] == calls['publish'] == []
    row = task_row(app, task)
    assert row['state'] == 'PLANNING' and row['lease_owner'] == 'new-private-owner'


def test_qualification_revoked_after_startup_blocks_queue_and_registry(tmp_path):
    from app.contracts.providers import ProviderContract
    app, task, runtime, calls, bindings, supervisor = fixture_case(tmp_path)
    old = runtime.provider.model_dump()
    old.update(identity_status='unknown', identity_source=None)
    bindings.provider_registry['fake-gpt'].provider = ProviderContract.model_validate(old)
    asyncio.run(supervisor.run_once())
    assert runtime.starts == [] and calls['execute'] == []
    assert task_row(app, task)['state'] == 'BLOCKED'
    assert 'fake-gpt' not in supervisor.provider_registry


def test_planning_failure_emits_fixed_public_error_once(tmp_path):
    from app.runtime.outbox import Outbox
    app, task, _, _, bindings, supervisor = fixture_case(tmp_path, 'disconnect')
    asyncio.run(supervisor.run_once())
    asyncio.run(TaskSupervisor(app.state.database.path, bindings, provider_mode='fake').run_once())
    with closing(app.state.database.connect()) as connection:
        conversation = connection.execute('SELECT conversation_id FROM turns WHERE task_id=?',(task,)).fetchone()[0]
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE task_id=? AND kind='request.failed'",(task,)).fetchone()[0] == 1
    projected = Outbox(app.state.database.path).replay(conversation)
    public = [value for value in projected if value['kind'] == 'request.failed']
    assert len(public) == 1 and 'private fixture disconnect' not in json.dumps(public[0])
