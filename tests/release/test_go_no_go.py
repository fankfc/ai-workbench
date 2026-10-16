def test_boolean_options_cannot_replace_candidate_evidence(probe):
    result = probe('release_decision', functional_checks=True, optimization_eligible=True)
    assert not result['functional_release']
    assert not result['optimization_goal_met']
    assert result['qualified_scope'] == []


def test_sealed_test_only_functional_gate_is_independent_from_optimization(tmp_path):
    from app.release.audit import release_decision
    from release.sealed_fixture import make
    make(tmp_path)
    simulated = release_decision(tmp_path, {}, allow_test_fixture=True)
    assert simulated['functional_release'] is True
    assert simulated['optimization_goal_met'] is False
    assert simulated['qualified_scope'] == []
    candidate_audit = release_decision(tmp_path, {})
    assert candidate_audit['functional_release'] is False
    assert any('NON_RELEASE_EVIDENCE' in reason for reason in candidate_audit['blocked_reasons'])


