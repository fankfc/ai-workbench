from __future__ import annotations

import asyncio
import ast
import copy
from concurrent.futures import ThreadPoolExecutor
import threading
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from app.providers.fake import FakeProvider
from app.contracts.events import AgentEvent
from app.runtime.workflow import Workflow
from app.runtime.workspace import WorkspaceManager
from app.storage.database import Database
from app.contracts.artifacts import ArtifactDependency, ArtifactVersion
from app.storage.blobs import BlobStore, store_artifact
from app.storage.revisions import activate_revision, is_current_revision
from app.usage.budgets import check_budget
from app.usage.ledger import UsageLedger
from support.contracts import make_contract

CASES = json.loads((Path(__file__).parents[1] / "fixtures/workflow_cases.json").read_text(encoding="utf-8"))


def prepare(client):
    conversation = client.post("/v1/conversations", json={"title": "workflow fixture"}).json()["id"]
    created = client.post(f"/v1/conversations/{conversation}/turns", json={"text": "检查fixture", "provider_profile_id": "fake-gpt", "client_request_id": "workflow"}).json()
    database = client.app.state.database
    with closing(database.connect()) as connection:
        row = dict(connection.execute("SELECT * FROM task_runs WHERE task_id=?", (created["task_id"],)).fetchone())
    workspace_manager = WorkspaceManager(database.path.parent / "workspaces")
    workspace = workspace_manager.create(row["task_id"], row["attempt_id"])
    source = "实际来源字节".encode()
    workspace.ingest_source("source.txt", source)
    contract = make_contract(row["task_id"], row["attempt_id"], json.loads(row["route_snapshot_json"])["id"])
    contract["inputs"] = [{"id": "input", "ref": "input/source.txt", "sha256": hashlib.sha256(source).hexdigest()}]
    contract["acceptance"][0]["condition"] = "Actual immutable UTF-8 candidate parses with Python ast.parse"
    return database.path, workspace_manager, workspace, contract


def validator(candidate):
    assert candidate.artifact_path.read_bytes() == candidate.content
    try:
        ast.parse(candidate.content.decode("utf-8"))
        parsed, error = True, None
    except SyntaxError as exc:
        parsed, error = False, type(exc).__name__
    return [{"criterion_id": criterion.id, "passed": parsed,
             "evidence": {"actual_sha256": hashlib.sha256(candidate.content).hexdigest(),
                          "parser": "python-ast", "error": error}}
            for criterion in candidate.contract.acceptance if not criterion.semantic]


def execute(prepared, case="pass", *, budget=check_budget, validator_port=validator, on_start=None, override=None):
    path, manager, _, contract = prepared
    inputs = override or CASES[case]
    b = FakeProvider(executions=inputs.get("executions"), on_start=on_start)
    a = FakeProvider(reviews=inputs.get("reviews"), takeovers=inputs.get("takeovers"))
    workflow = Workflow(path, manager, b, validator_port, a, budget,
        estimated_tokens={"B.execution": 64, "A.review": 64, "A.takeover": 64})
    return asyncio.run(workflow.run(contract)), b, a


def test_candidates_checks_and_a_review_are_real_persisted_bound_bytes(client):
    prepared = prepare(client)
    result, b, a = execute(prepared)
    path, _, workspace, contract = prepared
    assert result.state == "OUTPUT_PREPARING" and result.current_revision_id and result.review_check_id
    with closing(Database(path).connect()) as connection:
        artifacts = connection.execute("SELECT * FROM artifact_revisions").fetchall()
        checks = connection.execute("SELECT * FROM checks WHERE check_kind='A.review'").fetchall()
        assert len(artifacts) == len(checks) == 1
        assert artifacts[0]["id"] == result.current_revision_id
        details = json.loads(checks[0]["details_json"])
        assert details["contract"] == contract and details["decision"]["decision"] == "PASS"
        assert checks[0]["artifact_version_id"] == result.current_revision_id
        assert connection.execute("SELECT COUNT(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0
    assert len(b.starts) == len(a.starts) == 1
    assert UsageLedger(path).summary(contract["task_id"])["total_tokens"] == 33


def test_a_review_receives_actual_hash_bound_mechanical_observations(client):
    result, _, a = execute(prepare(client))
    assert result.state == 'OUTPUT_PREPARING'
    package = json.loads(Path(a.starts[0].prompt_path).read_text(encoding='utf-8'))['evidence_package']
    reference = package['mechanical_evidence'][0]
    raw = (Path(result.evidence_root) / reference['ref']).read_bytes()
    observation = package['mechanical_observations'][0]
    assert observation['ref'] == reference['ref']
    assert observation['sha256'] == hashlib.sha256(raw).hexdigest() == reference['sha256']
    assert observation['content'] == raw.decode('utf-8')
    assert json.loads(observation['content'])['details']['parser'] == 'python-ast'
    with closing(Database(client.app.state.database.path).connect()) as connection:
        from app.api.public_events import public_events
        conversation = connection.execute('SELECT conversation_id FROM turns').fetchone()[0]
        assert 'python-ast' not in json.dumps(public_events(connection, client.app.state.blobs, conversation))


@pytest.mark.parametrize('change', ['missing', 'changed'])
def test_invalid_mechanical_proof_blocks_before_a_review(client, monkeypatch, change):
    original = Workflow._review

    async def invalidated(self, contract, workspace, lease, candidate, evidence, workflow):
        path = workspace.area('evidence') / evidence[0]['ref']
        if change == 'missing':
            path.unlink()
        else:
            path.write_bytes(b'{}')
        return await original(self, contract, workspace, lease, candidate, evidence, workflow)

    monkeypatch.setattr(Workflow, '_review', invalidated)
    result, _, a = execute(prepare(client))
    assert result.state == 'BLOCKED'
    assert a.starts == []
    with closing(Database(client.app.state.database.path).connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0


def test_claude_review_receives_verified_english_observations_with_original_proof_binding(client):
    from test_claude_native_pipeline import assembly, mechanical
    from translation.fakes import claude_turn

    _, task, attempt = claude_turn(client)
    service, manager, _, a, workflow = assembly(client, task, attempt)
    workspace = manager.create(task, attempt)
    raw = '保留原文件。'.encode()
    workspace.ingest_source('request.md', raw)
    with closing(service.database.connect()) as connection:
        route = json.loads(connection.execute('SELECT route_snapshot_json FROM task_runs WHERE task_id=?', (task,)).fetchone()[0])
    contract = make_contract(task, attempt, route['id'], 'mixed', 'claude')
    # Include loaded translator/checker role text in the fixed fixture budget.
    contract['budget']['total_tokens'] = 30000
    contract['inputs'] = [dict(id='USER-1', ref='input/request.md', sha256=hashlib.sha256(raw).hexdigest())]
    contract['source_unit_ids'] = ['USER-1']
    contract['full_read_required'] = True

    def observations(candidate):
        result = mechanical(candidate)
        for item in result:
            item['evidence'].update(note='禁止删除原始文件。', code='`print("中文界面")`', measured_value=-0.03)
        return result

    workflow.validator = observations
    result = asyncio.run(workflow.run(contract))
    assert result.state == 'OUTPUT_PREPARING', result.reason_codes
    review = next(json.loads(Path(request.prompt_path).read_text(encoding='utf-8')) for request in a.starts
        if json.loads(Path(request.prompt_path).read_text(encoding='utf-8'))['phase'] == 'review')
    observation = review['evidence_package']['mechanical_observations'][0]
    source = (workspace.area('evidence') / observation['ref']).read_bytes()
    assert '禁止删除原始文件。' in source.decode()
    assert 'Do not delete original files.' in observation['content']
    assert '禁止删除原始文件。' not in observation['content']
    details = json.loads(observation['content'])['details']
    assert details['code'] == '`print("中文界面")`' and details['measured_value'] == -0.03
    assert observation['sha256'] == hashlib.sha256(source).hexdigest()
    assert observation['content_ref'].startswith('translation/')
    assert workspace.read('A', observation['content_ref']).decode() == observation['content']
    with closing(service.database.connect()) as connection:
        job = connection.execute('SELECT * FROM translation_jobs WHERE id=?', (observation['translation_job_id'],)).fetchone()
        assert job['status'] == 'READY' and job['qa_id'] == observation['qa_id']
        assert job['source_sha256'] == observation['sha256']
        assert job['target_sha256'] == hashlib.sha256(observation['content'].encode()).hexdigest()


@pytest.mark.parametrize('total_tokens', [10000, 15000, 30000])
def test_claude_numeric_proof_keeps_translation_qa_and_fixed_budget_gate(client, total_tokens):
    from test_claude_native_pipeline import assembly, mechanical
    from translation.fakes import claude_turn
    from artifacts.helpers import external_translation_service

    _, task, attempt = claude_turn(client, 'Keep the original file.')
    _, manager, _, a, workflow = assembly(client, task, attempt)
    service = external_translation_service({'client': client})
    workflow.translation_service = service
    workspace = manager.create(task, attempt)
    raw = b'Keep the original file.'
    workspace.ingest_source('request.md', raw)
    with closing(service.database.connect()) as connection:
        route = json.loads(connection.execute('SELECT route_snapshot_json FROM task_runs WHERE task_id=?', (task,)).fetchone()[0])
    contract = make_contract(task, attempt, route['id'], 'mixed', 'claude')
    contract['inputs'] = [dict(id='USER-1', ref='input/request.md', sha256=hashlib.sha256(raw).hexdigest())]
    contract['source_unit_ids'] = ['USER-1']
    contract['full_read_required'] = True
    contract['budget']['total_tokens'] = total_tokens

    def observations(candidate):
        values = mechanical(candidate)
        for item in values:
            item['evidence'].update(monthly_totals={f'2026-{index:02d}': str(index * 10) for index in range(1, 25)},
                note='Computed and independently reproduced all monthly totals.')
        return values

    workflow.validator = observations
    result = asyncio.run(workflow.run(contract))
    with closing(service.database.connect()) as connection:
        translation_failures = [row[0] for row in connection.execute(
            "SELECT clarification FROM translation_jobs WHERE json_extract(job_json,'$.purpose')='review-evidence'")]
    if total_tokens == 10000:
        assert result.state == 'BLOCKED'
        assert result.reason_codes == ('CLAUDE_INPUT_TRANSLATION_NOT_READY',)
        assert translation_failures == [] and a.starts == []
        with closing(service.database.connect()) as connection:
            assert [row[0] for row in connection.execute(
                "SELECT clarification FROM translation_jobs WHERE status='FAILED'")] == ['TRANSLATION_BUDGET_EXHAUSTED']
        return
    if total_tokens == 15000:
        assert result.state == 'BLOCKED'
        assert result.reason_codes == ('CLAUDE_REVIEW_EVIDENCE_TRANSLATION_NOT_READY',)
        assert translation_failures == ['TRANSLATION_BUDGET_EXHAUSTED']
        assert len(a.starts) == 1  # Finalization occurred; review never started.
        return
    assert result.state == 'OUTPUT_PREPARING', (result.reason_codes, translation_failures)
    prompt = json.loads(Path(a.starts[-1].prompt_path).read_text(encoding='utf-8'))
    observation = prompt['evidence_package']['mechanical_observations'][0]
    source = (workspace.area('evidence') / observation['ref']).read_bytes()
    assert observation['content'].encode() == source
    assert observation['content_sha256'] == observation['sha256'] == hashlib.sha256(source).hexdigest()
    assert workspace.read('A', observation['content_ref']) == source
    with closing(service.database.connect()) as connection:
        job = connection.execute('SELECT * FROM translation_jobs WHERE id=?', (observation['translation_job_id'],)).fetchone()
        assert job['status'] == 'READY' and job['source_sha256'] == observation['sha256']
        assert job['qa_id'] == observation['qa_id']
        assert {row[0] for row in connection.execute('SELECT phase FROM translation_calls WHERE job_id=? AND status=?',
            (job['id'], 'completed'))} == {'translate', 'check'}


def test_b_completion_without_candidate_never_passes(client):
    prepared = prepare(client)
    case = {"executions": [{"reported_complete": True, "usage": {"input_tokens": 1, "output_tokens": 1}}]}
    result, _, a = execute(prepared, override=case)
    assert result.state == "BLOCKED" and "CANDIDATE_MISSING" in result.reason_codes
    assert a.starts == []


def test_failed_mechanical_check_cannot_be_overruled_by_unbound_a_pass(client):
    prepared = prepare(client)
    case = {"executions": [{"text": "FAIL 假称完美", "usage": {"input_tokens": 1, "output_tokens": 1}}],
            "reviews": [{"decision": "PASS", "criterion_results": {"AC1": True, "AC2": True}, "usage": {"input_tokens": 1, "output_tokens": 1}}]}
    result, _, _ = execute(prepared, override=case)
    assert result.state == "BLOCKED" and "MANDATORY_EVIDENCE_MISSING" in result.reason_codes


def test_targeted_repair_creates_new_version_and_revalidates(client):
    prepared = prepare(client)
    validated = []
    def observed(candidate):
        validated.append(candidate.revision_id)
        return validator(candidate)
    result, b, a = execute(prepared, "repair", validator_port=observed)
    assert result.state == "OUTPUT_PREPARING" and result.quality_repairs == 1
    assert len(set(validated)) == 2 and len(b.starts) == len(a.starts) == 2
    with closing(Database(prepared[0]).connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_revisions").fetchone()[0] == 2


def test_same_defect_in_changed_report_escalates_to_a_with_real_lease_handoff(client):
    prepared = prepare(client)
    result, b, a = execute(prepared, "no_progress")
    assert result.state == "OUTPUT_PREPARING" and len(b.starts) == 2
    assert len(a.starts) == 4  # two reviews, takeover request, final review
    with closing(Database(prepared[0]).connect()) as connection:
        checkpoint = json.loads(connection.execute("SELECT checkpoint_json FROM task_runs").fetchone()[0])
    history = checkpoint["workflow"]["takeover_leases"]
    assert history[0]["before"]["b"]["role"] == "B" and history[0]["during"]["b"]["role"] == "A"
    assert history[0]["after"]["b"]["role"] == "B"
    assert history[0]["during"]["b"]["epoch"] > history[0]["before"]["b"]["epoch"]


@pytest.mark.parametrize("decision,state", [("NEED_EVIDENCE", "NEEDS_INPUT"), ("BLOCKED", "BLOCKED")])
def test_a_nonpass_decisions_have_distinct_stopping_states(client, decision, state):
    prepared = prepare(client)
    inputs = {**CASES["pass"], "reviews": [{"decision": decision, "issues": ["fixture issue"], "usage": {"input_tokens": 1, "output_tokens": 1}}]}
    result, _, _ = execute(prepared, override=inputs)
    assert result.state == state and result.review_check_id


def test_missing_budget_and_estimate_block_before_model_start(client):
    prepared = prepare(client)
    result, b, a = execute(prepared, budget=None)
    assert result.state == "BLOCKED" and "BUDGET_PORT_MISSING" in result.reason_codes
    assert b.starts == a.starts == []


def test_unknown_usage_blocks_next_request_instead_of_inventing_zero(client):
    prepared = prepare(client)
    inputs = {"executions": [{"text": "候选", "usage": None}], "reviews": CASES["pass"]["reviews"]}
    result, b, a = execute(prepared, override=inputs)
    assert result.state == "BLOCKED" and "UNKNOWN_USAGE" in result.reason_codes
    assert len(b.starts) == 1 and a.starts == []
    assert UsageLedger(prepared[0]).summary(prepared[3]["task_id"])["total_tokens"] is None


def test_native_session_cumulative_meter_is_not_summed_as_request_totals(client):
    prepared = prepare(client)

    class ScopedReviewer(FakeProvider):
        def __init__(self):
            super().__init__(reviews=CASES['repair']['reviews'])
            self.meter_sequence = 0

        async def run(self, request):
            self.meter_sequence += 1
            async for event in super().run(request):
                if event.kind == 'provider.usage':
                    yield AgentEvent(event.task_id, event.attempt_id, event.sequence, event.kind,
                        {'raw': {'total_tokens': 30 if self.meter_sequence == 1 else 50},
                         'source': 'reported', 'mode': 'cumulative',
                         'cumulative_scope': 'fixture-review-session',
                         'receipt_sequence': self.meter_sequence})
                else:
                    yield event

    path, manager, _, contract = prepared
    b = FakeProvider(executions=CASES['repair']['executions'])
    a = ScopedReviewer()
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={'B.execution': 64, 'A.review': 64, 'A.takeover': 64})
    result = asyncio.run(workflow.run(contract))
    assert result.state == 'OUTPUT_PREPARING' and len(a.starts) == 2
    requests = UsageLedger(path).summary(contract['task_id'])['requests']
    reviews = [entry for entry in requests if entry['role'] == 'A']
    assert sum(entry['total_tokens'] for entry in reviews) == 50
    assert sorted(entry['total_tokens'] for entry in reviews) == [20, 30]


@pytest.mark.parametrize('receipt_sequence', [None, True, 0, -1])
def test_scoped_meter_missing_valid_global_sequence_blocks_next_model(client, receipt_sequence):
    prepared = prepare(client)

    class BadScopedMeter(FakeProvider):
        async def run(self, request):
            async for event in super().run(request):
                if event.kind == 'provider.usage':
                    yield AgentEvent(event.task_id, event.attempt_id, event.sequence, event.kind,
                        {'raw': {'total_tokens': 30}, 'source': 'reported', 'mode': 'cumulative',
                         'cumulative_scope': 'fixture-session', 'receipt_sequence': receipt_sequence})
                else:
                    yield event

    path, manager, _, contract = prepared
    b = BadScopedMeter(executions=CASES['pass']['executions'])
    a = FakeProvider(reviews=CASES['pass']['reviews'])
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={'B.execution': 64, 'A.review': 64})
    result = asyncio.run(workflow.run(contract))
    assert result.state == 'BLOCKED' and len(b.starts) == 1 and a.starts == []
    assert UsageLedger(path).summary(contract['task_id'])['total_tokens'] is None


def test_cancel_during_provider_response_blocks_late_candidate_and_a_start(client):
    prepared = prepare(client)
    def cancel(request):
        assert client.post(f"/v1/tasks/{request.task_id}/cancel").status_code == 202
    result, b, a = execute(prepared, on_start=cancel)
    assert result.state == "CANCELLED" and len(b.starts) == 1 and a.starts == []
    with closing(Database(prepared[0]).connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_revisions").fetchone()[0] == 0
    assert UsageLedger(prepared[0]).summary(prepared[3]["task_id"])["requests"][0]["status"] == "cancelled"


def test_claude_formal_missing_gates_block_explicitly(client):
    prepared = prepare(client)
    prepared[3]["model_family"] = "claude"
    result, b, a = execute(prepared)
    assert result.state == "BLOCKED" and "CLAUDE_LANGUAGE_AND_PUBLICATION_GATES_MISSING" in result.reason_codes
    assert b.starts == a.starts == []


def test_request_missing_estimate_is_explicit_block(client):
    path, manager, _, contract = prepare(client)
    b, a = FakeProvider(executions=CASES["pass"]["executions"]), FakeProvider(reviews=CASES["pass"]["reviews"])
    result = asyncio.run(Workflow(path, manager, b, validator, a, check_budget).run(contract))
    assert result.state == "BLOCKED" and "ESTIMATE_REQUIRED" in result.reason_codes
    assert b.starts == a.starts == []


def test_repeated_run_does_not_replace_history_or_restart_provider(client):
    path, manager, _, contract = prepare(client)
    b, a = FakeProvider(executions=CASES["pass"]["executions"]), FakeProvider(reviews=CASES["pass"]["reviews"])
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    first = asyncio.run(workflow.run(contract))
    second = asyncio.run(workflow.run(contract))
    assert second.current_revision_id == first.current_revision_id
    assert second.review_check_id == first.review_check_id
    assert len(b.starts) == len(a.starts) == 1
    with closing(Database(path).connect()) as connection:
        checkpoint = json.loads(connection.execute("SELECT checkpoint_json FROM task_runs").fetchone()[0])
        assert len(checkpoint["workflow"]["candidate_history"]) == 1


def test_scope_input_and_validator_failure_stop_with_saved_checkpoint(client):
    prepared = prepare(client)
    prepared[3]["inputs"][0]["ref"] = "../secret.txt"
    result, b, a = execute(prepared)
    assert result.state == "BLOCKED" and b.starts == a.starts == []


def test_a_family_mismatch_blocks_before_wrong_model_receives_prompt(client):
    prepared = prepare(client)
    with closing(Database(prepared[0]).connect()) as connection:
        connection.execute("UPDATE provider_profiles SET family='claude' WHERE id='fake-gpt'")
    result, b, a = execute(prepared)
    assert result.state == "BLOCKED" and "A_MODEL_FAMILY_MISMATCH" in result.reason_codes
    assert len(b.starts) == 1 and a.starts == []


def test_reported_old_revision_cannot_be_rebound_into_a_approval(client):
    prepared = prepare(client)
    case = {**CASES["pass"], "reviews": [{**CASES["pass"]["reviews"][0], "revision_id": "old-candidate"}]}
    result, _, _ = execute(prepared, override=case)
    assert result.state == "BLOCKED" and "A_REVIEW_BINDING_MISMATCH" in result.reason_codes


def test_connection_retry_preserves_failed_usage_and_quality_counter(client):
    prepared = prepare(client)
    case = {"executions": [{"connection_error": True, "usage": {"input_tokens": 1, "output_tokens": 0}},
        CASES["pass"]["executions"][0]], "reviews": CASES["pass"]["reviews"]}
    result, b, _ = execute(prepared, override=case)
    assert result.state == "OUTPUT_PREPARING" and result.connection_retries == 1 and result.quality_repairs == 0
    requests = UsageLedger(prepared[0]).summary(prepared[3]["task_id"])["requests"]
    assert len(b.starts) == 2 and any(request["status"] == "failed" for request in requests)


def test_b_cannot_spend_a_reserved_budget(client):
    prepared = prepare(client)
    prepared[3]["budget"] = {"total_tokens": 100, "reserved_a_tokens": 50}
    result, b, a = execute(prepared)
    assert result.state == "BLOCKED" and "BUDGET_EXHAUSTED" in result.reason_codes
    assert b.starts == a.starts == []


def test_independent_repair_counters_and_three_b_round_bound():
    from app.runtime.repair import RepairTracker
    tracker = RepairTracker()
    for index in range(3):
        tracker.observe([f"defect-{index}"], f"r{index}", str(index))
        assert tracker.next_action() == "repair"
    tracker.connection_failure()
    tracker.translation_failure()
    assert tracker.next_action() == "takeover"
    assert tracker.snapshot()["quality_repairs"] == 3
    assert tracker.snapshot()["connection_retries"] == tracker.snapshot()["translation_retries"] == 1


@pytest.mark.parametrize("language,expected", [(None, "und"), ("en", "en"), ("zh-CN", "zh-CN")])
def test_candidate_language_metadata_is_explicit_and_never_inferred(client, language, expected):
    prepared = prepare(client)
    response = {"text": "print('hello')", "usage": {"input_tokens": 1, "output_tokens": 1}}
    if language is not None:
        response["language"] = language
    result, _, _ = execute(prepared, override={"executions": [response], "reviews": CASES["pass"]["reviews"]})
    assert result.state == "OUTPUT_PREPARING"
    with closing(Database(prepared[0]).connect()) as connection:
        assert connection.execute("SELECT language FROM artifact_revisions").fetchone()[0] == expected


def test_unknown_language_label_does_not_create_artifact(client):
    prepared = prepare(client)
    result, _, _ = execute(prepared, override={"executions": [{"text": "print('hello')", "language": "made-up", "usage": {"input_tokens": 1, "output_tokens": 1}}]})
    assert result.state == "BLOCKED" and "CANDIDATE_LANGUAGE_INVALID" in result.reason_codes
    with closing(Database(prepared[0]).connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_revisions").fetchone()[0] == 0


def test_changed_contract_cannot_reuse_old_approval_or_modify_checkpoint(client):
    prepared = prepare(client)
    first, _, _ = execute(prepared)
    with closing(Database(prepared[0]).connect()) as connection:
        before = connection.execute("SELECT checkpoint_json FROM task_runs").fetchone()[0]
    changed = copy.deepcopy(prepared[3])
    changed["objective"] = "Different requirements at the same version"
    b, a = FakeProvider(executions=CASES["pass"]["executions"]), FakeProvider(reviews=CASES["pass"]["reviews"])
    workflow = Workflow(prepared[0], prepared[1], b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    with pytest.raises(ValueError, match="WORKFLOW_CONTRACT_DIGEST_MISMATCH"):
        asyncio.run(workflow.run(changed))
    with closing(Database(prepared[0]).connect()) as connection:
        assert connection.execute("SELECT checkpoint_json FROM task_runs").fetchone()[0] == before
    assert b.starts == a.starts == []


def test_competing_workflow_instance_cannot_clobber_owner_initialization(client, monkeypatch):
    path, manager, workspace, contract = prepare(client)
    entered, release = threading.Event(), threading.Event()
    original_read = workspace.read
    def blocked_read(role, relative_path):
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=8)
        return original_read(role, relative_path)
    monkeypatch.setattr(workspace, "read", blocked_read)
    b = FakeProvider(executions=CASES["pass"]["executions"])
    a = FakeProvider(reviews=CASES["pass"]["reviews"])
    owner = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    loser_b, loser_a = FakeProvider(), FakeProvider()
    loser = Workflow(path, manager, loser_b, validator, loser_a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: asyncio.run(owner.run(contract)))
        try:
            assert entered.wait(timeout=5)
            with closing(Database(path).connect()) as connection:
                before = dict(connection.execute("SELECT state,checkpoint_json,lease_owner FROM task_runs").fetchone())
            with pytest.raises(RuntimeError, match="WORKFLOW_BUSY"):
                asyncio.run(loser.run(contract))
            with closing(Database(path).connect()) as connection:
                assert dict(connection.execute("SELECT state,checkpoint_json,lease_owner FROM task_runs").fetchone()) == before
            assert loser_b.starts == loser_a.starts == []
        finally:
            release.set()
        assert future.result(timeout=12).state == "OUTPUT_PREPARING"
    with closing(Database(path).connect()) as connection:
        assert connection.execute("SELECT lease_owner FROM task_runs").fetchone()[0] is None


@pytest.mark.parametrize("decision,expected_text", [("NEED_EVIDENCE", "请补充任务需要的材料。"), ("BLOCKED", "结果未通过检查，请补充材料或重试。")])
def test_stopped_workflow_emits_one_safe_chinese_feedback(client, decision, expected_text):
    prepared = prepare(client)
    inputs = {**CASES["pass"], "reviews": [{"decision": decision, "issues": ["INTERNAL_ENGLISH_CANARY"],
        "usage": {"input_tokens": 1, "output_tokens": 1}}]}
    result, _, _ = execute(prepared, override=inputs)
    with closing(Database(prepared[0]).connect()) as connection:
        conversation = connection.execute("SELECT conversation_id FROM turns").fetchone()[0]
    messages = client.get(f"/v1/conversations/{conversation}/messages").json()["items"]
    text = json.dumps(messages, ensure_ascii=False)
    assert expected_text in text and "INTERNAL_ENGLISH_CANARY" not in text
    repeat, _, _ = execute(prepared, override=inputs)
    assert repeat.state == result.state
    with closing(Database(prepared[0]).connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM outbox_events WHERE kind IN ('input.required','request.failed')").fetchone()[0] == 1


def seed_dependency(prepared, logical_id, revision_id, content, upstream=None):
    path, _, _, contract = prepared
    store = BlobStore(path.parent / "blobs")
    digest = hashlib.sha256(content).hexdigest()
    upstream = upstream or {}
    artifact = ArtifactVersion(id=revision_id, task_id=contract["task_id"], artifact_kind="data", language="und",
        immutable_uri=store.uri_for(digest), byte_sha256=digest, canonical_content_sha256=digest,
        source_version_id=None, origin_authors=["fixture-source"], canonical_issued_by="fixture-source",
        reviewed_by=[], rendered_by="service", a_response_ref=None,
        dependencies=[ArtifactDependency(artifact_version_id=value, relationship="source") for value in upstream.values()])
    with closing(Database(path).connect()) as connection:
        store_artifact(connection, store, content, artifact, attempt_id=contract["attempt_id"], provenance={"test_only": True})
        activate_revision(connection, store, contract["task_id"], contract["attempt_id"], logical_id, revision_id, upstream)


@pytest.mark.parametrize("stale", [False, True])
def test_missing_or_stale_contract_dependencies_block_before_b_start(client, stale):
    prepared = prepare(client)
    if stale:
        seed_dependency(prepared, "data", "data-old", b"old")
        seed_dependency(prepared, "data", "data-new", b"new")
    prepared[3]["dependencies"] = ["data-old" if stale else "missing-revision"]
    result, b, a = execute(prepared)
    assert result.state == "BLOCKED" and b.starts == a.starts == []
    assert any("DEPENDENCY" in reason for reason in result.reason_codes)


def test_actual_dependency_chain_binds_answer_and_invalidates_when_upstream_changes(client):
    prepared = prepare(client)
    seed_dependency(prepared, "data", "data-1", b"1,2,3")
    seed_dependency(prepared, "result", "result-1", b"sum=6", {"data": "data-1"})
    seed_dependency(prepared, "figure", "figure-1", b"<svg>6</svg>", {"result": "result-1"})
    prepared[3]["dependencies"] = ["result-1", "figure-1"]
    result, _, _ = execute(prepared)
    assert result.state == "OUTPUT_PREPARING"
    with closing(Database(prepared[0]).connect()) as connection:
        artifact = connection.execute("SELECT dependencies_json FROM artifact_revisions WHERE id=?", (result.current_revision_id,)).fetchone()
        assert {entry["artifact_version_id"] for entry in json.loads(artifact[0])} == {"result-1", "figure-1"}
        checkpoint = json.loads(connection.execute("SELECT checkpoint_json FROM task_runs").fetchone()[0])
        assert checkpoint["dependency_graph"]["nodes"]["answer"]["dependencies"] == {"result": "result-1", "figure": "figure-1"}
        assert is_current_revision(connection, prepared[3]["task_id"], prepared[3]["attempt_id"], result.current_revision_id)
    seed_dependency(prepared, "data", "data-2", b"2,3,4")
    with closing(Database(prepared[0]).connect()) as connection:
        assert not is_current_revision(connection, prepared[3]["task_id"], prepared[3]["attempt_id"], result.current_revision_id)


def test_request_has_durable_unknown_usage_before_external_response(client):
    prepared = prepare(client)
    observed = []
    def on_start(request):
        summary = UsageLedger(prepared[0]).summary(request.task_id)
        observed.append(summary)
        assert summary["unknown_requests"] == 1 and summary["total_tokens"] is None
        assert any(row["status"] == "running" and row["source"] == "unknown" for row in summary["requests"])
    result, _, _ = execute(prepared, on_start=on_start)
    assert result.state == "OUTPUT_PREPARING" and len(observed) == 1
    final = UsageLedger(prepared[0]).summary(prepared[3]["task_id"])
    assert final["unknown_requests"] == 0 and final["total_tokens"] == 33


@pytest.mark.parametrize("field,value", [("model_id", "other-gpt"), ("adapter", "other-adapter"),
    ("connection_version", "changed-version"), ("identity_source", "different-source")])
def test_a_live_profile_change_cannot_drift_from_frozen_route(client, field, value):
    prepared = prepare(client)
    with closing(Database(prepared[0]).connect()) as connection:
        connection.execute(f"UPDATE provider_profiles SET {field}=? WHERE id='fake-gpt'", (value,))
    result, b, a = execute(prepared)
    assert result.state == "BLOCKED" and "A_MODEL_ROUTE_MISMATCH" in result.reason_codes
    assert len(b.starts) == 1 and a.starts == []


def test_a_cannot_select_different_profile_of_same_family(client):
    path, manager, _, contract = prepare(client)
    with closing(Database(path).connect()) as connection:
        connection.execute("""INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,
            identity_source,connection_version) VALUES('other-gpt','fake','fixture-gpt','gpt','other-gpt','unknown',NULL,'test-only')""")
    b, a = FakeProvider(executions=CASES["pass"]["executions"]), FakeProvider(reviews=CASES["pass"]["reviews"])
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64}, profile_ids={"A": "other-gpt", "B": "fake-glm"})
    result = asyncio.run(workflow.run(contract))
    assert result.state == "BLOCKED" and "A_MODEL_ROUTE_MISMATCH" in result.reason_codes
    assert len(b.starts) == 1 and a.starts == []


def test_each_request_blocks_claude_before_original_context_is_written(client):
    path, manager, workspace, contract = prepare(client)
    with closing(Database(path).connect()) as connection:
        connection.execute("""INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,
            identity_status,connection_version) VALUES('fake-claude','fake','fixture-claude','claude',
            'fake-claude','unknown','test-only')""")
    b = FakeProvider(executions=CASES["pass"]["executions"])
    a = FakeProvider(reviews=CASES["pass"]["reviews"])
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64},
        profile_ids={"A": "fake-gpt", "B": "fake-claude"})
    result = asyncio.run(workflow.run(contract))
    assert result.state == "BLOCKED" and "CLAUDE_REQUEST_CONTEXT_GATE_MISSING" in result.reason_codes
    assert b.starts == a.starts == []
    assert not list(workspace.area("b").rglob("prompts/*.json"))
    with closing(Database(path).connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 0


class AcceptedStreamFailure:
    test_only = True

    def __init__(self, database_path, *, accepted=True, terminal_state=None):
        self.database_path = database_path
        self.accepted = accepted
        self.terminal_state = terminal_state
        self.starts = []
        self.observed_after_started = []

    async def run(self, request):
        self.starts.append(request)
        sequence = 1
        if self.accepted:
            yield AgentEvent(request.task_id, request.attempt_id, sequence, "provider.started",
                {"external_request_id": "ongoing-request", "external_execution_id": "ongoing-execution"})
            sequence += 1
            with closing(Database(self.database_path).connect()) as connection:
                task = dict(connection.execute("SELECT * FROM task_runs WHERE task_id=?", (request.task_id,)).fetchone())
                step = dict(connection.execute("SELECT * FROM steps WHERE task_id=? ORDER BY created_at DESC,id DESC", (request.task_id,)).fetchone())
            self.observed_after_started.append({"task": task, "step": step})
        yield AgentEvent(request.task_id, request.attempt_id, sequence, "provider.usage",
            {"raw": {"input_tokens": 10, "output_tokens": 5}, "source": "reported"})
        if self.terminal_state:
            with closing(Database(self.database_path).connect()) as connection:
                connection.execute("UPDATE task_runs SET state=? WHERE task_id=?",
                    (self.terminal_state, request.task_id))
        raise ConnectionError("fixture observation lost after request acceptance")

    async def cancel(self, task_id, attempt_id):
        pass


def test_accepted_remote_request_is_durable_before_stream_disconnect_and_never_retried(client):
    path, manager, _, contract = prepare(client)
    b, a = AcceptedStreamFailure(path), FakeProvider()
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    result = asyncio.run(workflow.run(contract))
    assert result.state == "BLOCKED" and "UNKNOWN_REMOTE" in result.reason_codes
    assert len(b.starts) == 1 and a.starts == [] and result.connection_retries == 0
    observed = b.observed_after_started[0]
    assert observed["task"]["external_request_id"] == "ongoing-request"
    assert observed["task"]["external_execution_id"] == observed["step"]["external_execution_id"] == "ongoing-execution"
    assert json.loads(observed["step"]["checkpoint_json"])["remote_execution"]["external_request_id"] == "ongoing-request"
    with closing(Database(path).connect()) as connection:
        task = dict(connection.execute("SELECT * FROM task_runs WHERE task_id=?", (contract["task_id"],)).fetchone())
        steps = [dict(row) for row in connection.execute("SELECT * FROM steps")]
    assert task["remote_status"] == "unknown" and task["external_stop_confirmed"] is None
    assert len(steps) == 1 and steps[0]["state"] == "UNKNOWN_REMOTE"
    assert json.loads(task["checkpoint_json"])["active_external_request"]["external_request_id"] == "ongoing-request"
    assert asyncio.run(workflow.run(contract)).state == "BLOCKED" and len(b.starts) == 1


@pytest.mark.parametrize("terminal_state", ["FAILED", "PUBLISHED"])
@pytest.mark.parametrize("accepted", [False, True])
def test_terminal_state_during_stream_failure_preserves_terminal_and_blocks_all_retries(client, terminal_state, accepted):
    path, manager, _, contract = prepare(client)
    b, a = AcceptedStreamFailure(path, accepted=accepted, terminal_state=terminal_state), FakeProvider()
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    result = asyncio.run(workflow.run(contract))
    assert result.state == terminal_state and "TERMINAL_STATE_FENCE" in result.reason_codes
    assert len(b.starts) == 1 and a.starts == [] and result.connection_retries == 0
    with closing(Database(path).connect()) as connection:
        assert connection.execute("SELECT state FROM task_runs").fetchone()[0] == terminal_state
        assert connection.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM artifact_revisions").fetchone()[0] == 0


@pytest.mark.parametrize("case", ["no_completion", "completed_then_disconnect", "error_then_completion",
    "missing_started_ids", "started_after_completion", "provider_completed_then_disconnect",
    "provider_error_then_completion", "provider_started_after_completion"])
def test_accepted_stream_boundaries_never_authorize_a_duplicate_request(client, case):
    path, manager, _, contract = prepare(client)
    completion_kind = "provider.completed" if case.startswith("provider_") else "model.completed"
    case = case.removeprefix("provider_")
    class BoundaryStream:
        test_only = True
        def __init__(self):
            self.starts = []
        async def run(self, request):
            self.starts.append(request)
            sequence = 1
            if case == "started_after_completion":
                yield AgentEvent(request.task_id, request.attempt_id, sequence, completion_kind, {})
                sequence += 1
            yield AgentEvent(request.task_id, request.attempt_id, sequence, "provider.started",
                {} if case == "missing_started_ids" else
                {"external_request_id": "boundary-request", "external_execution_id": "boundary-execution"})
            sequence += 1
            yield AgentEvent(request.task_id, request.attempt_id, sequence, "provider.usage",
                {"raw": {"input_tokens": 10, "output_tokens": 5}, "source": "reported"})
            sequence += 1
            if case == "error_then_completion":
                yield AgentEvent(request.task_id, request.attempt_id, sequence, "provider.error", {"message": "private fixture error"})
                sequence += 1
            if case in {"completed_then_disconnect", "error_then_completion"}:
                yield AgentEvent(request.task_id, request.attempt_id, sequence, completion_kind, {})
            if case == "completed_then_disconnect":
                raise ConnectionError("fixture disconnect after completion claim")
        async def cancel(self, task_id, attempt_id):
            pass
    b, a = BoundaryStream(), FakeProvider()
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    result = asyncio.run(workflow.run(contract))
    assert result.state == "BLOCKED" and "UNKNOWN_REMOTE" in result.reason_codes
    assert len(b.starts) == 1 and a.starts == [] and result.connection_retries == 0
    with closing(Database(path).connect()) as connection:
        step = dict(connection.execute("SELECT * FROM steps").fetchone())
        task = dict(connection.execute("SELECT * FROM task_runs").fetchone())
        public = [json.loads(row[0]) for row in connection.execute("SELECT internal_payload_json FROM outbox_events WHERE kind='request.failed'")]
    assert step["state"] == "UNKNOWN_REMOTE" and task["remote_status"] == "unknown"
    assert json.loads(step["checkpoint_json"])["remote_execution"]["accepted"] is True
    assert public == [{"error_code": "PROVIDER_UNAVAILABLE"}]


@pytest.mark.parametrize("completion_kind", ["model.completed", "provider.completed"])
def test_successive_accepted_steps_preserve_actual_current_remote_reference(client, completion_kind):
    path, manager, _, contract = prepare(client)
    class StartedFake(FakeProvider):
        async def run(self, request):
            invocation = Path(request.prompt_path).stem
            yield AgentEvent(request.task_id, request.attempt_id, 1, "provider.started",
                {"external_request_id": "remote-request-" + invocation,
                 "external_execution_id": "remote-execution-" + invocation})
            async for event in super().run(request):
                yield AgentEvent(event.task_id, event.attempt_id, event.sequence + 1,
                    completion_kind if event.kind == "model.completed" else event.kind,
                    {"reason_code": "CAPTURE_VERIFIED", "exit_code": 0}
                    if event.kind == "model.completed" and completion_kind == "provider.completed" else event.payload)
    b = StartedFake(executions=CASES["pass"]["executions"])
    a = StartedFake(reviews=CASES["pass"]["reviews"])
    workflow = Workflow(path, manager, b, validator, a, check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    result = asyncio.run(workflow.run(contract))
    assert result.state == "OUTPUT_PREPARING" and len(b.starts) == len(a.starts) == 1
    with closing(Database(path).connect()) as connection:
        task = dict(connection.execute("SELECT * FROM task_runs").fetchone())
        steps = [dict(row) for row in connection.execute("SELECT * FROM steps")]
    active = json.loads(task["checkpoint_json"])["active_external_request"]
    current = next(step for step in steps if step["id"] == active["step_id"])
    earlier = next(step for step in steps if step["role"] == "B")
    assert active == json.loads(current["checkpoint_json"])["remote_execution"]
    assert active["provider_profile_id"] == "fake-gpt" and active["role"] == "A" and active["status"] == "completed"
    assert task["external_execution_id"] == active["external_execution_id"]
    assert task["external_request_id"] == json.loads(earlier["checkpoint_json"])["remote_execution"]["external_request_id"]
    assert task["external_request_id"] != active["external_request_id"]
    assert UsageLedger(path).summary(contract["task_id"])["total_tokens"] == 33


@pytest.mark.parametrize("cancel_during_observation", [True, False, "pending_flag"])
def test_accepted_request_without_remote_ids_keeps_cancellation_pending(client, monkeypatch, cancel_during_observation):
    path, manager, _, contract = prepare(client)
    class MissingIds:
        test_only = True
        def __init__(self):
            self.starts = []
        async def run(self, request):
            self.starts.append(request)
            yield AgentEvent(request.task_id, request.attempt_id, 1, "provider.started", {})
        async def cancel(self, task_id, attempt_id):
            pass
    b = MissingIds()
    workflow = Workflow(path, manager, b, validator, FakeProvider(), check_budget,
        estimated_tokens={"B.execution": 64, "A.review": 64})
    if cancel_during_observation:
        original = workflow._remote_started
        def cancel_after_durable_started(*arguments):
            remote = original(*arguments)
            if cancel_during_observation == "pending_flag":
                with closing(Database(path).connect()) as connection:
                    connection.execute("UPDATE task_runs SET cancel_requested=1 WHERE task_id=?", (contract["task_id"],))
            else:
                assert client.post(f"/v1/tasks/{contract['task_id']}/cancel").status_code == 202
            return remote
        monkeypatch.setattr(workflow, "_remote_started", cancel_after_durable_started)
    outcome = asyncio.run(workflow.run(contract))
    if not cancel_during_observation:
        assert outcome.state == "BLOCKED" and "UNKNOWN_REMOTE" in outcome.reason_codes
        assert client.post(f"/v1/tasks/{contract['task_id']}/cancel").status_code == 202
    else:
        assert outcome.state == "CANCELLED"
    with closing(Database(path).connect()) as connection:
        task = dict(connection.execute("SELECT * FROM task_runs").fetchone())
    assert task["state"] == "CANCELLED" and task["cancel_pending_remote"] == 1
    assert task["external_stop_confirmed"] is None and task["remote_status"] == "unknown"
    assert task["external_request_id"] is task["external_execution_id"] is None
    assert len(b.starts) == 1
