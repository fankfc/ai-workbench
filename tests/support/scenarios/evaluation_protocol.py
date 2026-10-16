import copy
import json
from pathlib import Path

from app.quality.eligibility import audit_registration, registration_hash
from support.manifest import write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'fault': dict(enum=['tuning_in_holdout', 'pilot_reused_in_holdout', 'registration_changed'])})
RESULT_SCHEMA = dict(type='object', required=['frozen', 'issues', 'registration_hash_valid'])
REPO = Path(__file__).resolve().parents[3]


def run(root, options):
    registration = json.loads((REPO / 'quality/evaluation-registration.json').read_text(encoding='utf-8'))
    registration = copy.deepcopy(registration)
    fault = options.get('fault')
    if fault in ('tuning_in_holdout','pilot_reused_in_holdout'):
        # Explicit contamination canary, not a genuine evaluation task.
        registration['tuning_ids'].append('synthetic-contamination-canary')
        registration['holdout_ids'].append('synthetic-contamination-canary')
        registration['registration_sha256'] = registration_hash(registration)
    elif fault == 'registration_changed':
        registration['failure_policy'] = 'discard_failures'
    elif fault:
        raise ValueError('UNKNOWN_PROTOCOL_FAULT')
    result = audit_registration(registration)
    result.update(registration_valid=result['frozen'], reason_codes=result['issues'],test_set_disjoint='HOLDOUT_CONTAMINATED' not in result['issues'],blind_labels_valid=False)
    result.update(provider_boundary='none', real_provider_verified=False)
    write_json(Path(root) / 'freeze-audit.json', result)
    write_json(Path(root) / 'registration-under-audit.json', registration)
    return result
