def test_signature_failure_options_do_not_forge_rollback(probe):
    result = probe('signed_update', fault='invalid_publisher')
    assert result['update_state'] == 'BLOCKED'
    assert result['active_version'] == 'unknown'
    assert result['restored_schema'] == 0

