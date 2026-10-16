"""Synthetic statistical negatives plus the actual unqualified registration."""
import json
from pathlib import Path

from app.quality.eligibility import DIMENSIONS, evaluate_eligibility, lower_bound
from support.manifest import write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'fixture': dict(enum=['quality_loss_saves_90_percent', 'quality_ok_no_token_saving', 'candidate']),
    'quality_delta': dict(type='number'), 'token_saving': dict(type='number'),
    'quality_lower_bound': dict(type='number'), 'saving_lower_bound': dict(type='number'), 'usage_complete': dict(type='boolean')})
RESULT_SCHEMA = dict(type='object', required=['optimization_goal_met', 'route', 'quality_noninferior', 'token_savings_lower_bound'])
REPO = Path(__file__).resolve().parents[3]


def run(root, options):
    registration = json.loads((REPO / 'quality/evaluation-registration.json').read_text(encoding='utf-8'))
    configuration = dict(a_version='unverified-claude', b_version='unverified-glm', domain='code',
        difficulty='easy', task_profile='code:1', translation_policy='1', glossary_version='1',
        scheduling_policy='1', protocol_hash=registration['registration_sha256'])
    fixture = options.get('fixture', 'candidate')
    if fixture not in {'candidate', 'quality_loss_saves_90_percent', 'quality_ok_no_token_saving'}:
        raise ValueError('UNKNOWN_OPTIMIZATION_FIXTURE')
    # Fixed adversarial inputs exercise the numerical evaluator; no synthetic
    # score is ever presented to the production qualifier as real evidence.
    quality_delta = -.1 if fixture == 'quality_loss_saves_90_percent' else .5
    token_delta = .9 if fixture == 'quality_loss_saves_90_percent' else 0
    if 'quality_delta' in options or 'token_saving' in options:
        quality_delta = options.get('quality_delta', quality_delta)
        token_delta = options.get('token_saving', token_delta)
    if 'quality_lower_bound' in options or 'saving_lower_bound' in options:
        # Legacy representative options are adversarial numerical fixture
        # inputs only; they are never treated as actual precomputed bounds.
        quality_delta=options.get('quality_lower_bound',quality_delta)
        token_delta=options.get('saving_lower_bound',token_delta)
    bounds = {d: lower_bound([quality_delta] * 1000, lower=-1, upper=1, alpha=.05, comparisons=84) for d in DIMENSIONS}
    token_bound = lower_bound([token_delta] * 1000, lower=-1, upper=1, alpha=.05, comparisons=84)
    result = evaluate_eligibility(registration, {'source_kind': 'synthetic'}, configuration)
    result.update(quality_noninferior=all(v >= 0 for v in bounds.values()),
        token_savings_lower_bound=token_bound, synthetic_quality_bounds=bounds,
        statistical_fixture='synthetic_only', functional_release=False,
        provider_boundary='none', real_provider_verified=False)
    result.update(reason_codes=result['blocked_reasons'],route_mode=result['route'],product_goal_complete=False)
    write_json(Path(root) / 'joint-gate-report.json', result)
    return result
