import jsonschema
import pytest

from support.scenarios.backup_restore import OPTIONS_SCHEMA, RESULT_SCHEMA, run


@pytest.mark.parametrize('fault', ['none', 'missing_chinese_artifact', 'corrupt_database', 'hash_mismatch', 'disk_full', 'mixed_pair'])
def test_bilingual_v3_backup_restore_scenario(tmp_path, fault):
    options = {'fault': fault}
    jsonschema.validate(options, OPTIONS_SCHEMA)
    result = run(tmp_path, options)
    jsonschema.validate(result, RESULT_SCHEMA)
    assert result['source_untouched'] is True and result['credential_restored'] is False
    assert result['source_versions'] >= 2 and result['paused_tasks'] == 1
    assert result['bilingual_formats'] == ['markdown', 'pdf']
    if fault == 'none':
        assert result['restore_state'] == 'RESTORED'
        assert result['original_hashes'] == result['restored_hashes']
        assert result['schema_before'] == 3 and result['schema_after'] == 4
    else:
        assert result['restore_state'] == 'REJECTED' and result['restored_hashes'] == {}
