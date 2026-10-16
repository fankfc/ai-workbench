def test_candidate_name_does_not_forge_installation(probe):
    result = probe('windows_install', fixture='signed_candidate')
    assert not result['install_ok'] and not result['publisher_valid']
    assert 'trusted_signature_missing' in result['blocked_reasons']

