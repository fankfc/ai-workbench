"""Phase-five handoffs use actual revisions and stable defect identities."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path

from app.storage.database import Database
from test_agent_workflow import prepare, execute


def finding(description='Invalid Python result'):
    return dict(id='DEF-001', requirement_id='AC1', location='b/result:1',
        impact=description, required_change='Return parseable Python.',
        pass_condition='The immutable candidate passes the actual Python parser.')


def responses(reviews):
    usage = dict(input_tokens=10, output_tokens=5)
    return dict(executions=[dict(text='FAIL invalid syntax', usage=usage), dict(text='fixed = 1', usage=usage)],
        reviews=[dict(**item, usage=usage) for item in reviews], takeovers=[dict(text='taken_over = 1', usage=usage)])


def approved():
    return dict(decision='PASS', criterion_results={'AC2': True})


def test_repair_request_contains_current_candidate_failure_proof_and_bounded_scope(client):
    prepared = prepare(client)
    result, b, _ = execute(prepared, override=responses([
        dict(decision='REPAIR', findings=[finding()], review_scope=['b/result', 'AC1']), approved()]))
    assert result.state == 'OUTPUT_PREPARING', result.reason_codes
    assert result.quality_repairs == 1 and len(b.starts) == 2
    package = json.loads(Path(b.starts[1].prompt_path).read_text(encoding='utf-8'))['evidence_package']
    order = package['repair_work_order']
    assert order['findings'] == [finding()]
    assert order['allowed_write_scopes'] == prepared[3]['b_write_scopes']
    assert order['review_scope'] == ['b/result', 'AC1']
    assert order['candidate_content'] == 'FAIL invalid syntax'
    assert order['byte_sha256'] == hashlib.sha256(order['candidate_content'].encode()).hexdigest()
    assert [x['id'] for x in order['rerun_checks']] == ['AC1', 'AC2']
    assert order['requires_reproduction'] is True
    assert order['contract_version'] == prepared[3]['contract_version']
    assert order['revision_id'] != result.current_revision_id
    actual = order['mechanical_observations'][0]
    proof = (Path(result.evidence_root) / actual['ref']).read_bytes()
    assert hashlib.sha256(proof).hexdigest() == actual['sha256']
    assert json.loads(actual['content'])['passed'] is False
    with closing(Database(prepared[0]).connect()) as connection:
        details = json.loads(connection.execute('SELECT details_json FROM checks WHERE id=?',
            (order['review_check_id'],)).fetchone()[0])
        assert details['decision']['findings'] == [finding()]
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0] == 0


def test_stable_defect_id_triggers_takeover_despite_changed_description(client):
    case = responses([dict(decision='REPAIR', findings=[finding('First description')]),
        dict(decision='REPAIR', findings=[finding('Same defect, rewritten description')]), approved()])
    case['executions'][1]['text'] = 'FAIL still invalid syntax'
    result, b, a = execute(prepare(client), override=case)
    assert result.state == 'OUTPUT_PREPARING', result.reason_codes
    assert len(b.starts) == 2 and len(a.starts) == 4
    takeover = next(json.loads(Path(r.prompt_path).read_text(encoding='utf-8')) for r in a.starts
        if json.loads(Path(r.prompt_path).read_text(encoding='utf-8'))['phase'] == 'takeover')
    assert takeover['evidence_package']['repair_work_order']['findings'][0]['id'] == 'DEF-001'
    assert takeover['evidence_package']['repair']['defect_streaks']['DEF-001'] == 2
    assert takeover['evidence_package']['sources']


def test_open_structured_finding_prevents_pass_even_without_legacy_issues(client):
    case = responses([dict(**approved(), findings=[finding()])])
    case['executions'][0]['text'] = 'valid = 1'
    result, b, _ = execute(prepare(client), override=case)
    assert result.state == 'BLOCKED'
    assert 'OPEN_REVIEW_ISSUES' in result.reason_codes
    assert len(b.starts) == 1


def test_foreign_or_duplicate_findings_block_before_another_execution(client):
    for mutation in ('foreign', 'duplicate'):
        prepared = prepare(client)
        items = [finding()]
        if mutation == 'foreign':
            items[0]['requirement_id'] = 'UNRELATED-AC'
        else:
            items.append(copy.deepcopy(items[0]))
        result, b, _ = execute(prepared, override=responses([dict(decision='REPAIR', findings=items)]))
        assert result.state == 'BLOCKED'
        assert len(b.starts) == 1


def test_legacy_issue_handoff_preserves_unknown_details_and_real_evidence(client):
    result, b, _ = execute(prepare(client), 'repair')
    assert result.state == 'OUTPUT_PREPARING'
    order = json.loads(Path(b.starts[1].prompt_path).read_text(encoding='utf-8'))['evidence_package']['repair_work_order']
    assert order['legacy_issues'] == ['mechanical-fail']
    assert order['findings'] == []
    assert order['details_complete'] is False
    assert order['mechanical_observations']


def test_saved_repair_handoff_rejects_changed_scope_version_candidate_or_evidence(client):
    from app.contracts.tasks import validate_contract
    from app.runtime.review_handoff import require_repair_work_order
    from app.storage.blobs import BlobStore
    import pytest

    prepared = prepare(client)
    result, b, _ = execute(prepared, 'repair')
    order = json.loads(Path(b.starts[1].prompt_path).read_text(encoding='utf-8'))['evidence_package']['repair_work_order']
    contract = validate_contract(prepared[3])
    store = BlobStore(Path(prepared[0]).parent / 'blobs')
    for field, changed in [('allowed_write_scopes', ['a']), ('contract_version', 'stale'),
            ('candidate_content', 'invented'), ('revision_id', 'stale')]:
        invalid = copy.deepcopy(order)
        invalid[field] = changed
        with pytest.raises(ValueError):
            require_repair_work_order(contract, invalid, store, result.evidence_root,
                order['revision_id'], order['review_check_id'])
    path = Path(result.evidence_root) / order['mechanical_observations'][0]['ref']
    path.write_bytes(b'{}')
    with pytest.raises(ValueError):
        require_repair_work_order(contract, order, store, result.evidence_root,
            order['revision_id'], order['review_check_id'])


def test_semantic_failure_proof_bytes_are_rechecked_before_repair(client):
    from app.contracts.tasks import validate_contract
    from app.runtime.review_handoff import require_repair_work_order
    from app.storage.blobs import BlobStore
    import pytest

    prepared = prepare(client)
    issue = finding()
    issue['requirement_id'] = 'AC2'
    result, b, _ = execute(prepared, override=responses([
        dict(decision='REPAIR', criterion_results={'AC2': False}, findings=[issue]), approved()]))
    assert result.state == 'OUTPUT_PREPARING'
    order = json.loads(Path(b.starts[1].prompt_path).read_text(encoding='utf-8'))['evidence_package']['repair_work_order']
    semantic = next(item for item in order['review_record']['evidence'] if item['verifier'] == 'A')
    (Path(result.evidence_root) / semantic['ref']).write_bytes(b'{}')
    with pytest.raises(ValueError):
        require_repair_work_order(validate_contract(prepared[3]), order,
            BlobStore(Path(prepared[0]).parent / 'blobs'), result.evidence_root,
            order['revision_id'], order['review_check_id'])


def test_claude_repair_takeover_reuses_verified_english_proof_views(client):
    import asyncio
    from test_claude_native_pipeline import assembly, mechanical
    from translation.fakes import claude_turn
    from support.contracts import make_contract

    _, task, attempt = claude_turn(client)
    service, manager, b, a, workflow = assembly(client, task, attempt)
    workspace = manager.create(task, attempt)
    source = '保留原文件。'.encode()
    workspace.ingest_source('request.md', source)
    with closing(service.database.connect()) as connection:
        route = json.loads(connection.execute('SELECT route_snapshot_json FROM task_runs WHERE task_id=?', (task,)).fetchone()[0])
    contract = make_contract(task, attempt, route['id'], 'mixed', 'claude')
    contract['budget']['total_tokens'] = 300000
    contract['inputs'] = [dict(id='USER-1', ref='input/request.md', sha256=hashlib.sha256(source).hexdigest())]
    contract['source_unit_ids'] = ['USER-1']
    usage = {'total_tokens': 10}
    body = dict(text='Keep the original file.', language='en', usage=usage)
    b.executions = [dict(body), dict(body)]
    a.takeovers = [dict(body), dict(body), dict(body)]
    defect = finding()
    defect['requirement_id'] = 'AC2'
    a.reviews = [dict(decision='REPAIR', findings=[defect], criterion_results={'AC2': False}, usage=usage),
        dict(decision='REPAIR', findings=[defect], criterion_results={'AC2': False}, usage=usage),
        dict(**approved(), canonical_author='A', usage=usage)]

    def observed(candidate):
        values = mechanical(candidate)
        for item in values:
            item['evidence']['note'] = '禁止删除原始文件。'
        return values

    workflow.validator = observed
    result = asyncio.run(workflow.run(contract))
    assert result.state == 'OUTPUT_PREPARING', result.reason_codes
    takeover = next(json.loads(Path(request.prompt_path).read_text(encoding='utf-8')) for request in a.starts
        if 'repair_work_order' in json.loads(Path(request.prompt_path).read_text(encoding='utf-8'))['evidence_package'])
    order = takeover['evidence_package']['repair_work_order']
    observation = order['mechanical_observations'][0]
    assert '禁止删除原始文件。' not in observation['content']
    assert 'Do not delete original files.' in observation['content']
    assert observation['language'] == 'en'
    assert workspace.read('A', observation['content_ref']).decode() == observation['content']
    raw = (Path(result.evidence_root) / observation['ref']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == observation['sha256']
    assert '禁止删除原始文件。' in raw.decode()

