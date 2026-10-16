"""Private assembly regressions with local captures and immutable-byte checks."""
import asyncio
from contextlib import closing
from dataclasses import replace
import json

import pytest

from app.providers.fake import FakeProvider
from app.providers.phase_bridge import PhaseCapture
from app.runtime.native_executor import NativeTaskExecutor
from app.runtime.native_backend import build_native_backend
from app.runtime.native_validation import NativeRegistryValidator
from app.runtime.publication import NativePublisher, PublicationBlocked
from app.runtime.supervisor import SupervisorError, TaskSupervisor
from app.runtime.workflow import Workflow
from app.storage.database import transaction
from app.usage.budgets import check_budget
from test_native_supervisor import fixture_case, task_row


def assembled_case(tmp_path):
    app, task, runtime, _, old, _ = fixture_case(tmp_path)
    runtime.cancellations = []

    async def cancel_planning(task_id, attempt_id):
        runtime.cancellations.append((task_id, attempt_id))
    runtime.cancel = cancel_planning
    invoke = runtime.invoke_text

    async def mechanical_contract(text, **kwargs):
        async for event in invoke(text, **kwargs):
            if isinstance(event, PhaseCapture):
                contract = json.loads(event.final_text)
                contract['acceptance'][0].update(condition='C_METHOD:python_ast_parse', evidence_type='artifact')
                event = replace(event, final_text=json.dumps(contract))
            yield event
    runtime.invoke_text = mechanical_contract
    with closing(app.state.database.connect()) as connection, transaction(connection):
        connection.execute('UPDATE task_runs SET checkpoint_json=?', (json.dumps({'request_domain': 'code'}),))
    b = FakeProvider(executions=[dict(text='count = 3\ntotal = 6\nmean = 2\n',
        usage=dict(input_tokens=10, output_tokens=5))])
    a = FakeProvider(reviews=[dict(decision='PASS', criterion_results=dict(AC1=True, AC2=True),
        read_unit_ids=['USER-1'], usage=dict(input_tokens=10, output_tokens=5))])
    for port in (b, a):
        port.provider, port.classification = runtime.provider, 'fixture'
    workflow = Workflow(app.state.database.path, old.planner.workspaces, b,
        NativeRegistryValidator(app.state.database.path), a, check_budget,
        estimated_tokens={'B.execution': 24, 'A.review': 24}, profile_ids={'A': 'fake-gpt', 'B': 'fake-gpt'})
    executor = NativeTaskExecutor(workflow)
    held = {}
    execute = executor.execute

    async def capture(plan):
        held['plan'] = plan
        held['result'] = await execute(plan)
        return held['result']
    executor.execute = capture
    bindings = build_native_backend(old.planner, executor,
        provider_registry={'fake-gpt': runtime}, allow_fixture=True)
    return app, task, runtime, b, a, bindings, held, executor


def test_private_binding_cancels_planning_and_both_workflow_roles(tmp_path):
    app, task, runtime, b, a, bindings, _, _ = assembled_case(tmp_path)
    attempt = task_row(app, task)['attempt_id']
    asyncio.run(bindings.cancel(task, attempt))
    assert runtime.cancellations == [(task, attempt)]
    assert b.cancellations == a.cancellations == [(task, attempt)]
    row = task_row(app, task)
    assert row['external_stop_confirmed'] is None and row['cancel_pending_remote'] == 0
    assert runtime.starts == b.starts == a.starts == []


@pytest.mark.parametrize('failed_role', ['planning', 'B', 'A'])
def test_cleanup_failure_still_attempts_all_three_roles(tmp_path, failed_role):
    app, task, runtime, b, a, bindings, _, _ = assembled_case(tmp_path)
    attempt = task_row(app, task)['attempt_id']
    port = {'planning': runtime, 'B': b, 'A': a}[failed_role]

    async def failed(task_id, attempt_id):
        port.cancellations.append((task_id, attempt_id))
        raise RuntimeError('private fixture cleanup details')
    port.cancel = failed
    with pytest.raises(PublicationBlocked, match='^NATIVE_LOCAL_CLEANUP_UNCONFIRMED$'):
        asyncio.run(bindings.cancel(task, attempt))
    assert runtime.cancellations == b.cancellations == a.cancellations == [(task, attempt)]
    assert task_row(app, task)['external_stop_confirmed'] is None


def test_assembled_ready_interruption_resumes_only_publication(tmp_path, monkeypatch):
    app, task, runtime, b, a, bindings, held, _ = assembled_case(tmp_path)
    publish = NativePublisher.publish

    def interrupted(*_):
        raise RuntimeError('explicit fixture interruption after durable READY')
    monkeypatch.setattr(NativePublisher, 'publish', interrupted)
    supervisor = TaskSupervisor(app.state.database.path, bindings, provider_mode='fake')
    assert asyncio.run(supervisor.run_once()) is None
    row = task_row(app, task)
    assert row['state'] == 'READY'
    staged = json.loads(row['checkpoint_json'])
    assert staged['public_release']['revision_id'] == held['result'].current_revision_id
    assert staged['release_registry']['approval_id'] == staged['public_release']['approval_id']
    with closing(app.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='request.failed'").fetchone()[0] == 0
    monkeypatch.setattr(NativePublisher, 'publish', publish)
    assert asyncio.run(bindings.publish(held['plan'], held['result']))['state'] == 'PUBLISHED'
    assert asyncio.run(bindings.publish(held['plan'], held['result']))['state'] == 'PUBLISHED'
    assert len(runtime.starts) == len(b.starts) == len(a.starts) == 1
    with closing(app.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 1
        mechanical = json.loads(connection.execute("SELECT details_json FROM checks WHERE check_kind='C.criterion'").fetchone()[0])
    assert 'python_ast_parse' in json.dumps(mechanical)


@pytest.mark.parametrize('change', ['missing_gate', 'cancelled', 'failed', 'foreign_owner', 'new_attempt'])
def test_interrupted_publication_keeps_release_and_owner_fences(tmp_path, monkeypatch, change):
    app, task, _, _, _, bindings, held, _ = assembled_case(tmp_path)
    original = NativePublisher.publish

    def interrupted(*_):
        with closing(app.state.database.connect()) as connection, transaction(connection):
            row = connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone()
            if change == 'missing_gate':
                checkpoint = json.loads(row['checkpoint_json'])
                checkpoint.pop('release_registry')
                connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?', (json.dumps(checkpoint), task))
            elif change == 'cancelled':
                connection.execute("UPDATE task_runs SET state='CANCELLED',cancel_requested=1 WHERE task_id=?", (task,))
            elif change == 'failed':
                connection.execute("UPDATE task_runs SET state='FAILED' WHERE task_id=?", (task,))
            elif change == 'foreign_owner':
                connection.execute("UPDATE task_runs SET lease_owner='foreign-owner' WHERE task_id=?", (task,))
            else:
                connection.execute("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,attempt_number,route_snapshot_json) VALUES(?, 'new-attempt', ?, ?, 'RECEIVED',2,?)",
                    (task, row['turn_id'], row['provider_profile_id'], row['route_snapshot_json']))
        raise RuntimeError('explicit fixture fence change during publication')
    monkeypatch.setattr(NativePublisher, 'publish', interrupted)
    supervisor = TaskSupervisor(app.state.database.path, bindings, provider_mode='fake')
    assert asyncio.run(supervisor.run_once()) is None
    row = task_row(app, task)
    expected = {'missing_gate': 'BLOCKED', 'cancelled': 'CANCELLED', 'failed': 'FAILED',
        'foreign_owner': 'READY', 'new_attempt': 'READY'}[change]
    assert row['state'] == expected
    if change == 'foreign_owner':
        assert row['lease_owner'] == 'foreign-owner'
    monkeypatch.setattr(NativePublisher, 'publish', original)
    with pytest.raises(ValueError):
        asyncio.run(bindings.publish(held['plan'], held['result']))
    with closing(app.state.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0


@pytest.mark.parametrize('change', ['no_opt_in', 'no_registry', 'missing_cancel', 'database', 'profile', 'unrelated_registry'])
def test_builder_rejects_unbound_or_implicit_fixture_ports(tmp_path, change):
    from types import SimpleNamespace
    _, _, runtime, _, _, bindings, _, executor = assembled_case(tmp_path)
    registry = {'fake-gpt': runtime}
    allow_fixture = True
    if change == 'no_opt_in':
        allow_fixture = False
    elif change == 'no_registry':
        registry = None
    elif change == 'missing_cancel':
        del runtime.cancel
    elif change == 'database':
        executor.database_path = tmp_path / 'foreign.sqlite3'
    elif change == 'profile':
        executor.workflow.profile_ids['B'] = 'foreign-profile'
    else:
        registry = {'fake-gpt': SimpleNamespace(provider=runtime.provider)}
    with pytest.raises(SupervisorError):
        build_native_backend(bindings.planner, executor, provider_registry=registry, allow_fixture=allow_fixture)


def test_builder_construction_never_probes_or_runs_supplied_ports(tmp_path):
    _, _, runtime, b, a, bindings, _, executor = assembled_case(tmp_path)
    async def forbidden(*_, **__):
        pytest.fail('construction must not probe, authenticate, or invoke')
    for port in (runtime, b, a):
        port.probe = forbidden
    rebuilt = build_native_backend(bindings.planner, executor,
        provider_registry={'fake-gpt': runtime}, allow_fixture=True)
    assert rebuilt.classification == 'fixture'
    assert runtime.starts == b.starts == a.starts == []


@pytest.mark.parametrize('failed_role', ['planning', 'B', 'A'])
def test_false_cleanup_result_is_unconfirmed(tmp_path, failed_role):
    app, task, runtime, b, a, bindings, _, _ = assembled_case(tmp_path)
    port = {'planning': runtime, 'B': b, 'A': a}[failed_role]
    async def unconfirmed(task_id, attempt_id):
        port.cancellations.append((task_id, attempt_id))
        return False
    port.cancel = unconfirmed
    with pytest.raises(PublicationBlocked, match='^NATIVE_LOCAL_CLEANUP_UNCONFIRMED$'):
        asyncio.run(bindings.cancel(task, task_row(app, task)['attempt_id']))
    assert len(runtime.cancellations) == len(b.cancellations) == len(a.cancellations) == 1


def test_production_registry_is_derived_without_probing_supplied_runtime_records(tmp_path):
    from types import SimpleNamespace
    from app.contracts.providers import ProviderContract
    from app.providers.phase_bridge import PhaseBridge
    from app.runtime.planning import NativeTaskPlanner
    app, _, runtime, _, _, fixture, _, executor = assembled_case(tmp_path)
    expected = runtime.provider.model_dump()
    expected['identity'].update(adapter='codex', model_id='synthetic-qualified-record')
    provider = ProviderContract.model_validate(expected)
    calls = []
    class LocalCapability:
        verified = True
        def require_verified(self, selected):
            if not self.verified or selected != provider:
                raise ValueError('synthetic qualification mismatch')
        def authorize(self, *_):
            pytest.fail('builder must not authorize an execution')
    async def forbidden(*_, **__):
        calls.append('unexpected external operation')
        pytest.fail('builder must not probe or run')
    async def cancel(*_):
        calls.append('cleanup')
    port = SimpleNamespace(provider=provider, classification='production', scope_capability=LocalCapability(),
        probe=forbidden, invoke_text=forbidden, run=forbidden, cancel=cancel)
    planner = NativeTaskPlanner(app.state.database.path, fixture.planner.workspaces, port)
    executor.workflow.adapter = executor.workflow.reviewer = PhaseBridge(port, provider)
    bindings = build_native_backend(planner, executor)
    assert dict(bindings.provider_registry) == {'fake-gpt': port}
    assert bindings.classification == 'production' and calls == []
    asyncio.run(bindings.cancel('synthetic-task', 'synthetic-attempt'))
    assert calls == ['cleanup']
    port.scope_capability.verified = False
    with pytest.raises(SupervisorError, match='^NATIVE_PROVIDER_NOT_QUALIFIED$'):
        build_native_backend(planner, executor)
