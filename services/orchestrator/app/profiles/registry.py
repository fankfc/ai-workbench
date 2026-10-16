import hashlib
import json
from pathlib import Path
from app.contracts.tasks import safe_relative_scope, validate_contract


def get_profile(domain):
    if domain not in {'code', 'paper', 'document', 'mixed'}:
        raise ValueError('TASK_PROFILE_UNAVAILABLE')
    raw = (Path(__file__).parent / (domain + '.yaml')).read_bytes()
    profile = json.loads(raw)  # JSON is the intentionally limited YAML subset.
    return {**profile, 'version': hashlib.sha256(raw).hexdigest()}


def preflight(domain, inputs, family):
    if family not in {'claude', 'gpt'}:
        raise ValueError('UNVERIFIED_MODEL_IDENTITY')
    profile = get_profile(domain)
    if not isinstance(inputs, dict):
        raise ValueError('PROFILE_INPUTS_REQUIRED')
    for key in ('workspace_ref', 'evidence_refs', 'data_refs', 'source_refs'):
        value = inputs.get(key)
        for ref in value if isinstance(value, list) else [value] if value else []:
            if not isinstance(ref, str) or not str(safe_relative_scope(ref)).startswith('input/'):
                raise ValueError('PROFILE_SOURCE_SCOPE_INVALID')
    if 'formats' in inputs and (not isinstance(inputs['formats'], list) or not inputs['formats'] or
            any(item not in {'pdf', 'docx', 'markdown'} for item in inputs['formats'])):
        raise ValueError('PROFILE_FORMAT_UNSUPPORTED')
    missing = [key for key in profile['required_inputs'] if not inputs.get(key)]
    return dict(status='NEEDS_INPUT' if missing else 'READY_FOR_A_CONTRACT', domain=domain,
        profile_version=profile['version'], missing_inputs=missing, model_started=False,
        language_policy='claude_en_bridge' if family == 'claude' else 'native',
        require_a_canonical=domain in {'paper', 'document', 'mixed'} and family == 'claude',
        require_bilingual_pair=family == 'claude' and bool(inputs.get('formats')),
        require_a_confirmation=True, eligible_for_publication=False)


def validate_profile_contract(contract, *, profile_version, inputs):
    contract = validate_contract(contract)
    profile = get_profile(contract.domain)
    if profile['version'] != profile_version or preflight(contract.domain, inputs, contract.model_family)['missing_inputs']:
        raise ValueError('PROFILE_CHANGED_OR_INPUTS_MISSING')
    required = {item['id']: item for item in profile['acceptance']}
    actual = {item.id: item for item in contract.acceptance}
    for identity, expected in required.items():
        criterion = actual.get(identity)
        if (criterion is None or not criterion.mandatory or criterion.verifier != expected['verifier']
                or criterion.semantic != expected['semantic'] or criterion.condition != expected['condition']
                or criterion.evidence_type != expected['evidence_type']):
            raise ValueError('PROFILE_ACCEPTANCE_MISSING')
    return contract
