import importlib
import math
from pathlib import Path

import pytest


def evaluator():
    assert Path('services/orchestrator/app/quality/eligibility.py').exists(), 'eligibility evaluator missing'
    return importlib.import_module('app.quality.eligibility')


def test_absent_evidence_defaults_to_a_led():
    result = evaluator().evaluate_eligibility({}, {}, {})
    assert not result['eligible'] and not result['optimization_goal_met']
    assert result['route'] == 'a_led'
    assert result['blocked_reasons']


def test_bonferroni_accounts_for_all_layers_and_dimensions():
    module = evaluator()
    loose = module.lower_bound([.5] * 100, lower=-1, upper=1, alpha=.05, comparisons=1)
    strict = module.lower_bound([.5] * 100, lower=-1, upper=1, alpha=.05, comparisons=84)
    assert strict < loose < .5
    assert strict == pytest.approx(.5 - 2 * math.sqrt(math.log(84 / .05) / 200))


@pytest.mark.parametrize('values', [[float('nan')], [float('inf')], [2], [True], []])
def test_bounds_reject_invalid_scores(values):
    with pytest.raises(ValueError):
        evaluator().lower_bound(values, lower=-1, upper=1, alpha=.05, comparisons=84)


def test_configuration_key_expires_on_model_or_policy_change():
    module = evaluator()
    config = dict(a_version='actual-A:1', b_version='actual-B:1', domain='paper', difficulty='hard', task_profile='paper:1', translation_policy='1', glossary_version='1', scheduling_policy='1', protocol_hash='a' * 64)
    key = module.configuration_key(config)
    assert key != module.configuration_key({**config, 'a_version': 'actual-A:2'})
    assert key != module.configuration_key({**config, 'glossary_version': '2'})


def test_test_samples_never_grant_real_qualification(tmp_path):
    assert Path('tests/support/scenarios/optimization_gate.py').exists()
    module = importlib.import_module('support.scenarios.optimization_gate')
    result = module.run(tmp_path, {'fixture': 'quality_loss_saves_90_percent'})
    assert not result['optimization_goal_met'] and result['route'] == 'a_led'
    assert result['quality_noninferior'] is False


def test_good_quality_without_token_reduction_keeps_goal_open(tmp_path):
    assert Path('tests/support/scenarios/optimization_gate.py').exists()
    module = importlib.import_module('support.scenarios.optimization_gate')
    result = module.run(tmp_path, {'fixture': 'quality_ok_no_token_saving'})
    assert not result['optimization_goal_met'] and result['route'] == 'a_led'
    assert result['token_savings_lower_bound'] <= 0


def test_real_claim_with_only_truthy_provenance_is_rejected(tmp_path):
    module = evaluator()
    claims = dict(source_kind='external', evidence_kind='real_evaluation', candidate_sha256='f'*64,
        commit='a'*40, observed_at='2026-10-14T12:00:00Z', identity_reports=['verified'],
        review_reports=['approved'], usage_reports=['complete'])
    result = module.evaluate_eligibility({}, claims, {})
    assert not result['eligible']
    assert 'CANDIDATE_OR_SOURCE_IDENTITY_INVALID' in result['blocked_reasons']
    assert 'HASHED_IDENTITY_REPORTS_INVALID' in result['blocked_reasons']
    assert 'HASHED_REVIEW_REPORTS_INVALID' in result['blocked_reasons']
    assert 'HASHED_USAGE_REPORTS_INVALID' in result['blocked_reasons']


def test_hashed_proof_rejects_parent_path_escape(tmp_path):
    module = evaluator()
    with pytest.raises(ValueError, match='PROOF_PATH_INVALID'):
        module.read_proof(tmp_path, {'path':'../outside.json', 'sha256':'a'*64,'size':1})


def test_hashed_proof_rejects_changed_bytes(tmp_path):
    module = evaluator()
    (tmp_path/'proof.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='PROOF_HASH_MISMATCH'):
        module.read_proof(tmp_path, {'path':'proof.json','sha256':'a'*64,'size':2})


def test_saving_never_compensates_quality_loss(probe):
    result=probe('optimization_gate',quality_lower_bound=-.2,saving_lower_bound=.9,usage_complete=True)
    assert not result['eligible'] and result['route_mode']=='a_led'
    assert result['product_goal_complete'] is False


@pytest.mark.parametrize('a_adapter,a_family,b_adapter,b_family,wire_family',[
    ('zcode','glm','codex','gpt',None),
    ('codex','glm','zcode','glm',None),
    ('claude_code','claude','zcode','gpt',None),
    ('claude_code','claude','zcode','glm','glm'),
])
def test_hashed_identity_reports_reject_role_or_family_swap(tmp_path,a_adapter,a_family,b_adapter,b_family,wire_family):
    import hashlib
    import json
    module=evaluator()
    def save(name,value):
        data=json.dumps(value).encode('utf-8')
        (tmp_path/name).write_bytes(data)
        return dict(path=name,size=len(data),sha256=hashlib.sha256(data).hexdigest())
    metadata=dict(source_kind='external',candidate_sha256='c'*64,commit='d'*40,observed_at='2026-10-14T12:00:00Z')
    identities=[]
    for role,adapter,family,version in [('A',a_adapter,a_family,'A-actual-version'),('B',b_adapter,b_family,'B-actual-version')]:
        wire=save(role+'-wire.json',dict(source_kind='external',model_version=version,adapter=adapter,
            family=wire_family if role=='A' and wire_family else family,request_id=role+'-request',identity_source='native_connection',identity_status='verified'))
        identities.append(save(role+'-identity.json',dict(**metadata,role=role,adapter=adapter,family=family,
            actual_version=version,identity_status='verified',identity_source='native_connection',wire_receipt=wire)))
    evidence=dict(**metadata,evidence_root=str(tmp_path),identity_reports=identities,review_reports=[],usage_reports=[])
    config=dict(a_version='A-actual-version',b_version='B-actual-version')
    reasons=module._verify_real_provenance({},evidence,config,[])
    assert 'HASHED_IDENTITY_REPORTS_INVALID' in reasons


def test_hashed_identity_receipt_requires_native_connection_source(tmp_path):
    import hashlib
    import json
    module=evaluator()
    def save(name,value):
        data=json.dumps(value).encode()
        (tmp_path/name).write_bytes(data)
        return dict(path=name,size=len(data),sha256=hashlib.sha256(data).hexdigest())
    metadata=dict(source_kind='external',candidate_sha256='c'*64,commit='d'*40,observed_at='2026-10-14T12:00:00Z')
    refs=[]
    for role,adapter,family in [('A','codex','gpt'),('B','zcode','glm')]:
        wire=save(role+'-wire.json',dict(source_kind='external',model_version=role+'-v1',adapter=adapter,family=family,request_id=role+'-request',identity_source='user_claim',identity_status='verified'))
        refs.append(save(role+'-identity.json',dict(**metadata,role=role,adapter=adapter,family=family,
            actual_version=role+'-v1',identity_status='verified',identity_source='native_connection',wire_receipt=wire)))
    reasons=module._verify_real_provenance({},dict(**metadata,evidence_root=str(tmp_path),identity_reports=refs,review_reports=[],usage_reports=[]),dict(a_version='A-v1',b_version='B-v1'),[])
    assert 'HASHED_IDENTITY_REPORTS_INVALID' in reasons
