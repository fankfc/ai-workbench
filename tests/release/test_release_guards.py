"""Release gates consume byte-bound evidence, never caller success flags."""
import hashlib
import json
from pathlib import Path

import pytest


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def candidate(root):
    path = root / 'AIBroker-Setup.exe'
    path.write_bytes(b'test-only installer bytes; never install')
    return {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def test_missing_candidate_cannot_be_declared_functional(tmp_path):
    from app.release.audit import release_decision, final_handover
    decision = release_decision(tmp_path, {'functional_checks': True, 'optimization_eligible': True})
    assert decision['functional_release'] is False
    assert decision['optimization_goal_met'] is False
    assert 'candidate_missing' in decision['blocked_reasons']
    handover = final_handover(tmp_path, {'functional_complete': True, 'optimization_complete': True})
    assert not handover['overall_goal_complete']
    assert 'optimization_evidence' in handover['open_items']


def test_manifest_blocks_missing_sbom_and_skips(tmp_path):
    from app.release.audit import audit_manifest
    value = {'candidate': candidate(tmp_path), 'commit': 'a' * 40, 'evidence': {'security_boundary': {'status': 'skipped'}}}
    result = audit_manifest(tmp_path, value)
    assert not result['valid']
    assert 'sbom' in result['missing_evidence']
    assert 'security_boundary' in result['skipped_mandatory']


def test_fixture_cannot_qualify_candidate(tmp_path):
    from app.release.evidence import check_reference
    ref = write(tmp_path, 'fixture.json', {'source_kind': 'test_fixture', 'status': 'passed', 'candidate_sha256': 'b' * 64, 'commit': 'a' * 40})
    with pytest.raises(ValueError, match='NON_RELEASE_EVIDENCE'):
        check_reference(tmp_path, ref, candidate_sha256='b' * 64, commit='a' * 40)
    assert check_reference(tmp_path, ref, candidate_sha256='b' * 64, commit='a' * 40, allow_test_fixture=True)['status'] == 'passed'


def test_external_label_cannot_launder_explicit_fixture_raw_evidence(tmp_path):
    from app.release.evidence import observed_report
    raw = write(tmp_path, 'raw.json', {'source_kind':'test_fixture'})
    report = write(tmp_path, 'report.json', {'source_kind':'external', 'status':'passed', 'candidate_sha256':'b'*64,
        'commit':'a'*40, 'observer':'claimed observer', 'recorded_at':'2026-10-14T00:00:00Z', 'raw_evidence':[raw]})
    with pytest.raises(ValueError, match='NON_RELEASE_RAW_EVIDENCE'):
        observed_report(tmp_path, report, candidate_sha256='b'*64, commit='a'*40)


@pytest.mark.parametrize('attack', ['tamper', 'stale', 'escape', 'symlink', 'hardlink', 'ads', 'drive_relative'])
def test_evidence_reference_rejects_integrity_attacks(tmp_path, attack):
    from app.release.evidence import check_reference
    ref = write(tmp_path, 'report.json', {'source_kind': 'external', 'status': 'passed', 'candidate_sha256': 'b' * 64, 'commit': 'a' * 40})
    if attack == 'tamper':
        (tmp_path / ref['path']).write_text('{}')
    elif attack == 'stale':
        ref = write(tmp_path, 'report.json', {'source_kind': 'external', 'status': 'passed', 'candidate_sha256': 'c' * 64, 'commit': 'a' * 40})
    elif attack == 'escape':
        ref['path'] = '../report.json'
    elif attack == 'ads':
        ref['path'] = 'report.json:hidden'
    elif attack == 'drive_relative':
        ref['path'] = 'C:report.json'
    elif attack == 'hardlink':
        import os
        os.link(tmp_path / 'report.json', tmp_path / 'linked.json')
    else:
        (tmp_path / 'report.json').rename(tmp_path / 'actual.json')
        try:
            (tmp_path / 'report.json').symlink_to(tmp_path / 'actual.json')
        except OSError:
            pytest.skip('symlink creation unavailable on this machine')
    with pytest.raises(ValueError):
        check_reference(tmp_path, ref, candidate_sha256='b' * 64, commit='a' * 40)


def test_installer_legacy_fixture_flag_does_not_create_signature(tmp_path):
    from app.release.audit import windows_install
    result = windows_install(tmp_path, {'fixture': 'signed_candidate'})
    assert not result['publisher_valid'] and not result['install_ok']
    assert result['taskbar_windows'] == 0
    assert result['evidence_kind'] == 'audit'


def test_real_journey_requires_observed_real_provenance(tmp_path):
    from app.release.audit import real_journey_audit
    result = real_journey_audit(tmp_path, {'evidence_set': 'candidate'})
    assert result['domains_passed'] == []
    assert not result['model_identity_verified']
    assert not result['all_required_entries_tested']


def test_sbom_inventory_covers_both_locks_and_reports_tool_gaps(tmp_path):
    from app.release.sbom import inventory
    root = Path(__file__).resolve().parents[2]
    result = inventory(root)
    assert result['bomFormat'] == 'CycloneDX'
    assert {'npm', 'pypi'} <= {item['group'] for item in result['components']}
    assert all(item['version'] for item in result['components'])
    assert result['metadata']['properties']


@pytest.mark.parametrize('kind', ['security_boundary', 'translation_review', 'accessibility_review', 'performance', 'reliability_24h', 'backup_restore', 'windows_install', 'signed_update', 'real_journeys', 'beta_trial'])
def test_passed_label_and_arbitrary_raw_file_do_not_supply_observations(tmp_path, kind):
    from app.release.audit import mandatory_report_valid
    assert not mandatory_report_valid(tmp_path, {}, kind, {'status': 'passed', 'raw_evidence': [{'path': 'random.txt', 'sha256': 'a'*64}]})


def test_translation_one_sample_cannot_replace_registered_corpora(tmp_path):
    from app.release.audit import mandatory_report_valid
    assert not mandatory_report_valid(tmp_path, {}, 'translation_review', {'human_reviewers': ['one', 'two'], 'critical_translation_errors': 0, 'reviewed_samples': 1, 'corpus_sha256': 'a'*64})


def test_accessibility_flags_without_actual_ime_multiscreen_evidence_rejected(tmp_path):
    from app.release.audit import mandatory_report_valid
    assert not mandatory_report_valid(tmp_path, {}, 'accessibility_review', {'human_reviewers': ['one'], 'keyboard': True, 'screen_reader': True, 'contrast': True, 'focus': True})


@pytest.mark.parametrize('fault', ['one_input', 'one_cold_start', 'one_lifecycle', 'omitted_metric', 'misreported_p95'])
def test_performance_recomputes_required_p95_and_minimum_sample_counts(tmp_path, fault):
    from app.release.audit import PERFORMANCE_LIMITS, performance_report_valid
    samples = {'input_echo_samples_ms':[1]*200, 'ui_ack_samples_ms':[1], 'cancel_feedback_samples_ms':[1],
               'state_visible_samples_ms':[1], 'cold_start_samples_ms':[1]*30, 'lifecycle_cycles':100, 'orphan_pids':[]}
    metrics = {name:1 for name in PERFORMANCE_LIMITS}
    if fault == 'one_input': samples['input_echo_samples_ms'] = [1]
    elif fault == 'one_cold_start': samples['cold_start_samples_ms'] = [1]
    elif fault == 'one_lifecycle': samples['lifecycle_cycles'] = 1
    elif fault == 'omitted_metric': metrics.pop('cancel_feedback_p95_ms')
    else: metrics['input_echo_p95_ms'] = 0
    reference = write(tmp_path, 'samples.json', samples)
    report = {'thresholds_preregistered':True, 'all_thresholds_met':True, 'sample_count':1, 'registered_limits_ms':PERFORMANCE_LIMITS,
              'machine_profile':'test-only', 'metrics':metrics, 'samples_ref':reference}
    assert not performance_report_valid(tmp_path, report)

