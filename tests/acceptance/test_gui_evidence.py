import pytest
from support.scenarios.gui_evidence import automatic_checks_passed


@pytest.mark.parametrize('changes', [{'english_leaks': ['CANARY']}, {'focus_lost': True},
    {'composition_submits': 1}, {'composition_submits': False}, {'english_leaks': None}])
def test_failed_current_electron_observations_cannot_pass(changes):
    observations = dict(actual_electron=True, english_leaks=[], focus_lost=False, composition_submits=0)
    observations.update(changes)
    assert not automatic_checks_passed(observations)


def test_missing_electron_observation_fields_cannot_pass():
    assert not automatic_checks_passed(dict(actual_electron=True))


def test_gui_audit_keeps_manual_checks_open(probe):
    result = probe('gui_evidence', fault='composition_and_internal_replay')
    assert {'real_windows_ime', 'narrator', 'multiple_monitor_scaling'} <= set(result['unmet_checks'])
    if result['automatic_checks_passed']:
        assert result['composition_submits'] == 0
        assert result['english_leaks'] == []
        assert result['focus_lost'] is False
    else:
        assert result['composition_submits'] is None
        assert 'current_electron_evidence' in result['unmet_checks']


def test_missing_gui_evidence_is_not_success(probe):
    result = probe('gui_evidence', evidence='artifacts/qa/D049/missing.json')
    assert result['automatic_checks_passed'] is False
    assert result['english_leaks'] is None
