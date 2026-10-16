from importlib import import_module
from pathlib import Path


def handler():
    assert Path('tests/support/scenarios/requirement_coverage.py').exists(), 'coverage evaluator missing'
    return import_module('support.scenarios.requirement_coverage')


def test_missing_mandatory_case_blocks_completion(tmp_path):
    result = handler().run(tmp_path, {'remove_case': 'T13'})
    assert 'R09' in result['unresolved_mandatory']
    assert result['release_complete'] is False


def test_matrix_retains_all_requirements_without_claiming_evidence(tmp_path):
    result = handler().run(tmp_path, {})
    assert result['missing_requirements'] == []
    assert result['mapped_requirements'] == 15
    assert result['translation_cases'] == 20
    assert not result['release_complete'] and not result['optimization_goal_met']
    assert set(result['unresolved_mandatory']) >= {'R03', 'R04', 'R13', 'R15'}


def test_unknown_removed_case_is_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError, match='UNKNOWN_CASE'):
        handler().run(tmp_path, {'remove_case': 'invented'})


def test_coverage_driver_rejects_removed_a_provenance_case(probe):
    result=probe('requirement_coverage',remove_case='T13')
    assert 'R09' in result['unresolved_mandatory']
    assert result['release_complete'] is False
