def test_service_scope_and_diagnostics_are_private(probe):
    r = probe('security_boundary', fault='malicious_attachment_and_cross_task_path')
    assert r['unauthorized_reads'] == []
    assert r['secret_leaks'] == []
    assert r['internal_public_events'] == []
    assert r['process_cleaned'] is True
    assert 'electron_script_execution' in r['unmet_checks']
    assert r['executed_payloads'] is None
