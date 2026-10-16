def test_handover_keeps_unproven_installation_and_optimization_open(probe):
    result = probe('final_handover', functional_complete=True, optimization_complete=False)
    assert not result['functional_complete']
    assert not result['overall_goal_complete']
    assert 'optimization_evidence' in result['open_items']

