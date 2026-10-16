def test_missing_candidate_journeys_are_explicitly_unverified(probe):
    result = probe('real_journey_audit', evidence_set='candidate')
    assert result['domains_passed'] == []
    assert not result['model_identity_verified']
    assert not result['all_required_entries_tested']

