def test_missing_real_mandatory_evidence_is_blocked(probe):
    result = probe('release_manifest', fault='skipped_security_test')
    assert result['valid'] is False
    assert result['missing_evidence']

