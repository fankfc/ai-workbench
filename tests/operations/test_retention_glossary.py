def test_operations_protect_product_references_and_version_cache(tmp_path):
    from app.operations.drills import retention_glossary
    result = retention_glossary(tmp_path)
    assert result['deleted_active_evidence'] is False
    assert result['secret_leaks'] == []
    assert result['cache_reused_after_glossary_change'] is False
    assert result['history_preserved'] is True
    assert result['evidence_kind'] == 'deterministic_product_probe'

