"""Inspect actual service-created prompts; external model responses are fixtures."""
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from app.runtime.planning import NativeTaskPlanner
from app.storage.database import transaction
from integration.test_agent_workflow import execute, prepare
from integration.test_native_planning import FixturePlannerRuntime, unplanned_case
from integration.test_claude_native_pipeline import FakeClaudePlanner, assembly
from translation.fakes import claude_turn


def assert_role(prompt, phase):
    assert prompt['phase'] == phase
    role = prompt['evidence_package'].get('role_prompt')
    assert role, f'{phase} must carry service-loaded role instructions'
    assert role['version'] == '1.0'
    assert role['phase'] == phase
    assert role['sha256'] == hashlib.sha256(role['instruction'].encode()).hexdigest()
    instruction = role['instruction']
    assert 'untrusted data' in instruction
    assert 'publication' in instruction and 'permissions' in instruction
    return role


@pytest.mark.parametrize('case,phases', [('pass', {'execution', 'review'}),
    ('no_progress', {'execution', 'review', 'takeover'})], ids=['pass', 'no_progress'])
def test_runtime_requests_include_versioned_roles_without_changing_contract(client, case, phases):
    prepared = prepare(client)
    result, worker, reviewer = execute(prepared, case=case)
    assert result.state == 'OUTPUT_PREPARING', result.reason_codes
    observed = set()
    for request in [*worker.starts, *reviewer.starts]:
        prompt = json.loads(Path(request.prompt_path).read_text(encoding='utf-8'))
        role = assert_role(prompt, prompt['phase'])
        assert role['language_policy'] == 'native'
        assert 'original user language' in role['instruction']
        assert prompt['contract'] == prepared[3]
        observed.add(prompt['phase'])
    assert observed == phases
    with closing(client.app.state.database.connect()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM translation_jobs').fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0


def test_native_planning_loads_role_and_maps_concepts_to_existing_contract(tmp_path):
    app, manager, task, attempt, owner = unplanned_case(tmp_path)

    class CapturingPlanner(FixturePlannerRuntime):
        async def invoke_text(self, text, **kwargs):
            self.prompt = json.loads(text)
            async for event in super().invoke_text(text, **kwargs):
                yield event

    runtime = CapturingPlanner()
    planner = NativeTaskPlanner(app.state.database.path, manager, runtime, allow_fixture=True, estimated_tokens=24)
    plan = asyncio.run(planner.plan(task, attempt, owner))
    prompt = runtime.prompt
    role = prompt.get('role_prompt')
    assert role, 'planning must attach the loaded role and version'
    assert role['instruction'] in prompt['instruction']
    assert role['contract_semantics']['key_decisions'] == ['method', 'a_responsibilities']
    assert role['contract_semantics']['worker_autonomy'] == ['b_write_scopes', 'constraints']
    assert role['contract_semantics']['escalation_triggers'] == ['runner_fixed_escalation_triggers', 'guidance_depth']
    assert role['language_policy'] == 'native'
    assert prompt['language_instruction'] == 'Preserve the original user language.'
    assert 'key_decisions' not in plan.contract.model_dump()
    assert all(item.id and item.condition for item in plan.contract.acceptance)


def test_claude_planning_execution_review_and_takeover_have_english_roles(client):
    _, task, attempt = claude_turn(client)
    service, manager, worker, reviewer, workflow = assembly(client, task, attempt)
    owner = 'role-prompt-planning-owner'
    with closing(service.database.connect()) as connection, transaction(connection):
        connection.execute("UPDATE task_runs SET state='INPUT_PREPARING',lease_owner=?,lease_expires_at=? WHERE task_id=?",
            (owner, (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(), task))
    from app.translation.input_pipeline import InputPipeline
    from app.runtime.native_executor import NativeTaskExecutor
    runtime = FakeClaudePlanner()
    planner = NativeTaskPlanner(service.database_path, manager, runtime, allow_fixture=True,
        estimated_tokens=24, input_pipeline=InputPipeline(service))
    plan = asyncio.run(planner.plan(task, attempt, owner))
    role = runtime.starts[0].get('role_prompt')
    assert role, 'Claude planning must carry its role instruction'
    assert role['language_policy'] == 'english'
    assert role['instruction'].isascii()
    result = asyncio.run(NativeTaskExecutor(workflow).execute(plan))
    assert result.state == 'OUTPUT_PREPARING', result.reason_codes
    for request in [*worker.starts, *reviewer.starts]:
        prompt = json.loads(Path(request.prompt_path).read_text(encoding='utf-8'))
        role = assert_role(prompt, prompt['phase'])
        assert role['language_policy'] == 'english'
        assert role['instruction'].isascii()
        assert 'Use English' in role['instruction']

