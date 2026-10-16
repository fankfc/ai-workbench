import hashlib
import json
from pathlib import Path

import pytest

from app.contracts.tasks import contract_digest, validate_contract
from app.providers.phase_bridge import PhaseBinding, PhaseBridgeError, phase_prompt_text
from support.contracts import make_contract


def binding(phase='execution'):
    contract = validate_contract(make_contract('task', 'attempt', 'route'))
    package = {'sources': [{'content': 'source text', 'trust': 'untrusted_material'}]}
    original = json.dumps(dict(phase=phase, contract=contract.model_dump(mode='json'), evidence_package=package))
    return PhaseBinding('actual-local-request', phase, contract, package, Path('evidence'),
        hashlib.sha256(original.encode()).hexdigest()), original


def test_text_only_model_receives_service_computed_exact_envelope_binding():
    context, original = binding()
    value = json.loads(phase_prompt_text(context, original))
    assert value['fixed_envelope_fields'] == dict(schema_version='1.0', phase='execution',
        request_id='actual-local-request', task_id='task', attempt_id='attempt', contract_version='1.0',
        contract_sha256=contract_digest(context.contract))
    assert value['work'] == json.loads(original)


def test_source_changed_before_prompt_preparation_is_rejected():
    context, original = binding()
    with pytest.raises(PhaseBridgeError):
        phase_prompt_text(context, original + ' ')


def test_native_text_bridge_explicitly_rejects_unimplemented_claude_route():
    context, _ = binding()
    value = context.contract.model_dump(mode='json')
    value.update(model_family='claude')
    contract = validate_contract(value)
    original = json.dumps(dict(phase=context.phase, contract=contract.model_dump(mode='json'),
        evidence_package=dict(context.evidence_package)))
    context = PhaseBinding(context.request_id, context.phase, contract, context.evidence_package,
        context.evidence_root, hashlib.sha256(original.encode()).hexdigest())
    with pytest.raises(PhaseBridgeError, match='^PHASE_BRIDGE_GPT_ROUTE_REQUIRED$'):
        phase_prompt_text(context, original)


def review_binding(tmp_path):
    context, original = binding('review')
    package = json.loads(original)['evidence_package']
    proof = dict(criterion_id='AC1', revision_id='candidate-v1', byte_sha256=hashlib.sha256(b'candidate').hexdigest(),
        verifier='C', passed=True, details=dict(parser='python-ast', actual_output='count=3 mean=2'))
    data = json.dumps(proof).encode()
    (tmp_path / 'proof.json').write_bytes(data)
    package.update(revision_id='candidate-v1', byte_sha256=proof['byte_sha256'], mechanical_evidence=[dict(
        criterion_id='AC1', revision_id='candidate-v1', verifier='C', passed=True,
        ref='proof.json', sha256=hashlib.sha256(data).hexdigest())])
    original = json.dumps(dict(phase='review', contract=context.contract.model_dump(mode='json'), evidence_package=package))
    return PhaseBinding(context.request_id, 'review', context.contract, package, tmp_path,
        hashlib.sha256(original.encode()).hexdigest()), original, data


def test_review_prompt_carries_original_source_and_mechanical_evidence_without_granting_pass(tmp_path):
    context, original, data = review_binding(tmp_path)
    value = json.loads(phase_prompt_text(context, original))
    assert value['fixed_envelope_fields']['phase'] == 'review'
    assert 'independently' in value['instruction']
    assert value['work']['evidence_package']['sources'][0]['trust'] == 'untrusted_material'
    observation = value['work']['evidence_package']['mechanical_observations'][0]
    assert observation['content'] == data.decode()
    assert observation['sha256'] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize('change', ['missing', 'changed', 'wrong_revision', 'wrong_candidate', 'false_pass'])
def test_review_prompt_rejects_invalid_actual_proof_before_model_request(tmp_path, change):
    context, original, data = review_binding(tmp_path)
    path = tmp_path / 'proof.json'
    if change == 'missing':
        path.unlink()
    elif change == 'changed':
        path.write_bytes(b'{}')
    else:
        proof = json.loads(data)
        proof[{'wrong_revision': 'revision_id', 'wrong_candidate': 'byte_sha256', 'false_pass': 'passed'}[change]] = False if change == 'false_pass' else 'foreign-value'
        changed = json.dumps(proof).encode()
        path.write_bytes(changed)
        package = json.loads(original)['evidence_package']
        package['mechanical_evidence'][0]['sha256'] = hashlib.sha256(changed).hexdigest()
        original = json.dumps(dict(phase='review', contract=context.contract.model_dump(mode='json'), evidence_package=package))
        context = PhaseBinding(context.request_id, 'review', context.contract, package, tmp_path,
            hashlib.sha256(original.encode()).hexdigest())
    with pytest.raises(PhaseBridgeError, match='^REVIEW_EVIDENCE_INVALID$'):
        phase_prompt_text(context, original)
