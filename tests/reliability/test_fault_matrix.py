import pytest


def test_cancel_then_thousand_late_successes_never_publish(probe):
    r = probe('fault_matrix', fault='cancel_then_1000_duplicate_successes')
    assert r['task_state'] == 'CANCELLED'
    assert r['published_versions'] == []
    assert r['external_starts'] == 1
    assert not any(event['applied_sequences'] for event in r['event_rejections'])


def test_unknown_remote_restart_preserves_request(probe):
    r = probe('fault_matrix', fault='unknown_remote_after_restart')
    assert r['task_state'] == 'BLOCKED'
    assert r['recovery_decision'] == 'blocked_unknown'
    assert r['published_versions'] == []


@pytest.mark.parametrize('fault', ['old_approval', 'upstream_change'])
def test_stale_approval_or_upstream_change_cannot_publish(probe, fault):
    assert probe('fault_matrix', fault=fault)['published_versions'] == []
