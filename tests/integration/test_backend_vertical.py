from pathlib import Path
import pytest

@pytest.mark.parametrize('domain',['code','paper','document','mixed'])
def test_four_domains_integrate_actual_storage_validators_usage_and_publication(probe,domain):
    result=probe('backend_normal',provider_mode='fake',domain=domain)
    assert result['task_state']=='PUBLISHED'
    assert result['public_answer_count']==1
    assert result['model_starts']>=2 and result['total_tokens']>0
    assert result['forced_translation_starts']==0
    assert result['mechanical_check_count']>=1
    assert Path(result['database_path']).is_file()
    assert Path(result['artifact_path']).is_file()
    assert result['provider_boundary']=='fake' and result['real_provider_verified'] is False

def test_cancel_blocks_late_answer_and_new_requests(probe):
    result=probe('backend_cancel_late',provider_mode='fake')
    assert result['task_state']=='CANCELLED'
    assert result['public_answer_count']==0
    assert result['model_starts_after_cancel']==0

def test_repair_rechecks_new_revision(probe):
    result=probe('backend_repair',provider_mode='fake')
    assert result['task_state']=='PUBLISHED'
    assert result['quality_repairs']==1
    assert result['candidate_count']==2 and result['mechanical_check_count']>=2

def test_missing_evidence_never_delivers(probe):
    result=probe('backend_need_evidence',provider_mode='fake')
    assert result['task_state'] in ('NEEDS_INPUT','BLOCKED')
    assert result['public_answer_count']==0
    assert any(m['kind']=='input.required' and m['language']=='zh-CN' for m in result['public_messages'])

def test_unknown_remote_restart_does_not_retry(probe):
    result=probe('backend_restart',provider_mode='fake')
    assert result['task_state']=='BLOCKED'
    assert result['recovery_decision']=='blocked_unknown'
    assert result['model_starts_after_restart']==0
    assert result['candidate_count']>=1 and result['request_count']==2
    assert result['unknown_requests']==1
    state=result['restart_conservation']
    assert state['request_count_before']==state['request_count_after']==2
    assert state['artifact_sha256_before']==state['artifact_sha256_after']

def test_old_pass_rejected_after_version_change(probe):
    result=probe('backend_old_approval',provider_mode='fake')
    assert result['public_answer_count']==0 and result['publication_rejected'] is True

def test_duplicate_api_and_usage_are_idempotent(probe):
    result=probe('backend_duplicate',provider_mode='fake')
    assert result['turn_count']==1 and result['request_count']==result['model_starts']
    assert result['public_answer_count']==1

def test_budget_stops_actual_provider_starts(probe):
    result=probe('backend_budget',provider_mode='fake')
    assert result['task_state']=='BLOCKED'
    assert result['model_starts']==0 and result['public_answer_count']==0
    assert any(m['kind']=='request.failed' and m['language']=='zh-CN' for m in result['public_messages'])

def test_connection_failure_is_bounded_and_counted(probe):
    result=probe('backend_connection_failure',provider_mode='fake')
    assert result['task_state'] in ('FAILED','BLOCKED')
    assert result['model_starts']<=3 and result['public_answer_count']==0
    assert result['request_count']==result['model_starts']

def test_claude_chinese_missing_gateway_blocks_before_start(probe):
    result=probe('backend_language_gate',provider_mode='fake')
    assert result['task_state']=='BLOCKED'
    assert result['model_starts']==0 and result['public_answer_count']==0
    assert any(m['kind']=='request.failed' and m['language']=='zh-CN' for m in result['public_messages'])

def test_vertical_suite_exports_all_four_domains(probe):
    result=probe('backend_vertical',provider_mode='fake')
    assert set(result['domains'])=={'code','paper','document','mixed'}
    assert result['all_local_cases_passed'] is True
    assert result['real_handoff_complete'] is False
    assert len(result['domains']['mixed']['dependency_graph']['nodes'])==5
    assert all(result['fault_expectations'].values())

def test_budget_after_repair_preserves_spend_and_stops_new_start(probe):
    result=probe('backend_budget_after_repair',provider_mode='fake')
    assert result['task_state']=='BLOCKED' and result['quality_repairs']==1
    assert result['candidate_count']==2 and result['model_starts']==3
    assert result['request_count']==3 and result['total_tokens']==45
    assert result['public_answer_count']==0

def test_upstream_data_change_invalidates_the_actual_composite_chain(probe):
    result=probe('backend_upstream_change',provider_mode='fake')
    assert result['publication_rejected'] is True and result['public_answer_count']==0
    assert len(result['dependency_graph']['nodes'])==5
    assert result['dependency_graph']['nodes']['analysis']['stale'] is True
    assert result['dependency_graph']['nodes']['result']['stale'] is True
    assert result['dependency_graph']['nodes']['figure']['stale'] is True
    assert result['dependency_graph']['nodes']['answer']['stale'] is True

@pytest.mark.real_provider
def test_required_real_provider_handoff_is_not_claimed_from_fake_cases():
    import json
    values=[json.loads(Path(f'docs/acceptance/{card}/supported-entry.json').read_text(encoding='utf-8')) for card in ('D004','D005')]
    if not all(value.get('production_enabled') is True for value in values):
        pytest.skip('Required native execution identity, supported ZCode account bridge, and scope capabilities remain unverified; fixtures cannot satisfy real handoff')
    pytest.fail('Real handoff requires independent fresh real integration evidence; local fake cases cannot satisfy it')
