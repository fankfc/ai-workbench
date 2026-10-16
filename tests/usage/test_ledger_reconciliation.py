from importlib import import_module
from pathlib import Path


def handler():
    assert Path('tests/support/scenarios/usage_reconciliation.py').exists(), 'usage evaluator missing'
    return import_module('support.scenarios.usage_reconciliation')


def test_duplicate_and_cumulative_samples_use_actual_ledger(tmp_path):
    result = handler().run(tmp_path, {})
    assert result['duplicate_total'] == 120 and result['duplicate_requests'] == 1
    assert result['cumulative_total'] == 250
    assert result['qualified_delivery_cost'] is None
    assert result['real_usage_verified'] is False
    assert result['optimization_eligible'] is False


def test_missing_usage_is_unknown_and_estimates_are_separate(tmp_path):
    result = handler().run(tmp_path, {'fault': 'missing_usage'})
    assert result['unknown_total'] is None and result['unknown_requests'] == 1
    assert result['estimated_source'] == 'estimated'
    assert set(result['counted_functions']) >= {'translation', 'takeover', 'review', 'execution'}


def test_cumulative_and_duplicate_usage_is_not_overcounted(probe):
    result=probe('usage_reconciliation',fault='cumulative_with_duplicate')
    assert result['a_tokens']==250 and result['duplicate_count']==1
    assert result['reported_complete'] is True
    assert result['source_kind']=='synthetic' and not result['real_usage_verified']
