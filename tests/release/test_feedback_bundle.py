import io
import json
import zipfile


def test_feedback_has_allowlisted_diagnostics_and_no_content(tmp_path):
    from app.operations.feedback import build_feedback
    result = build_feedback(tmp_path, include_content=False)
    assert result['secret_leaks'] == []
    assert not result['contains_user_content']
    assert not result['explicit_content_opt_in']
    assert result['reproducible_case']
    with zipfile.ZipFile(tmp_path / 'feedback-diagnostics.zip') as archive:
        report = json.loads(archive.read('diagnostics.json'))
    assert report['raw_materials_included'] is False


def test_content_flag_requires_this_feedback_opt_in(tmp_path):
    from app.operations.feedback import build_feedback
    result = build_feedback(tmp_path, include_content=True)
    assert not result['contains_user_content']
    assert not result['explicit_content_opt_in']
    assert 'content_opt_in_required' in result['blocked_reasons']

