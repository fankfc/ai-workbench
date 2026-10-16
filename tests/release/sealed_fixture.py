"""Temporary test-only evidence for decision logic. Never candidate evidence."""
import hashlib
import json
from app.release.audit import MANDATORY, INSTALL_FIELDS, UPDATE_FIELDS, PERFORMANCE_LIMITS


def make(root):
    def write(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    commit = 'a' * 40
    candidate = write('TEST_ONLY_AIBroker-Setup.exe', {'source_kind': 'test_fixture', 'installable': False})
    raw = write('TEST_ONLY_raw.json', {'source_kind': 'test_fixture', 'observed': False})
    performance_samples = write('TEST_ONLY_performance_samples.json', {'source_kind':'test_fixture',
        'input_echo_samples_ms':[1]*200, 'ui_ack_samples_ms':[1], 'cancel_feedback_samples_ms':[1],
        'state_visible_samples_ms':[1], 'cold_start_samples_ms':[1]*30, 'lifecycle_cycles':100, 'orphan_pids':[]})
    locks = {name: write(name, {'source_kind': 'test_fixture'}) for name in ('package-lock.json', 'services/orchestrator/uv.lock')}
    sbom = write('TEST_ONLY_sbom.json', {'bomFormat': 'CycloneDX', 'components': [{'name': 'TEST_ONLY'}], 'metadata': {'properties':
         [{'name': 'inventory:status', 'value': 'complete_verified_package'}] + [{'name': 'lock:' + name, 'value': ref['sha256']} for name, ref in locks.items()]}})
    write('release/publisher-allowlist.json', {'thumbprints': ['A' * 40], 'source_kind': 'test_fixture'})
    values = {
        'security_boundary': {'mandatory_cases_total': 4, 'mandatory_cases_passed': 4, 'skipped': [], 'critical_findings': []},
        'translation_review': {'human_reviewers': ['fixture-reviewer-1', 'fixture-reviewer-2'], 'critical_translation_errors': 0, 'golden_samples': 60, 'holdout_samples': 60, 'holdout_critical_errors': 0, 'holdout_independent': True, 'reviewers_blinded': True, 'high_impact_adjudicated': True, 'adjudicator': 'fixture-adjudicator', 'corpus_sha256': raw['sha256'], 'holdout_sha256': raw['sha256']},
        'accessibility_review': {'human_reviewers': ['fixture-reviewer-1'], 'keyboard': True, 'screen_reader': True, 'contrast': True, 'focus': True, 'actual_windows_ime': True, 'actual_multiscreen': True, 'manual_evidence': {name: raw for name in ('ime', 'narrator', 'multiscreen')}},
        'performance': {'thresholds_preregistered': True, 'registered_limits_ms':PERFORMANCE_LIMITS, 'machine_profile': 'TEST_ONLY', 'samples_ref':performance_samples, 'metrics': {name:1 for name in PERFORMANCE_LIMITS}},
        'reliability_24h': {'duration_seconds': 86400, 'completed': True, 'critical_failures': 0, 'checkpoints_verified': True},
        'backup_restore': {key: True for key in ('live_backup_consistent', 'isolated_restore_verified', 'corruption_rejected', 'newer_schema_rejected', 'source_preserved')},
        'windows_install': {**{key: True for key in INSTALL_FIELDS}, 'taskbar_windows': 1},
        'signed_update': {**{key: True for key in UPDATE_FIELDS}, 'restored_schema': 4, 'expected_schema': 4},
        'beta_trial': {'observed_workdays': 5, 'real_user_count': 1, 'open_p0_p1': 0, 'outputs_verified': True, 'fixes_retested': True},
        'authenticode': {'authenticode_status': 'Valid', 'chain_valid': True, 'timestamp_valid': True, 'is_test_certificate': False, 'publisher_thumbprint': 'A' * 40},
        'release_approval': {'approvals': [{'role': role, 'reviewer': 'fixture-' + role, 'decision': 'go'} for role in ('product', 'qa', 'release')],
                             'open_p0_p1': 0, 'functional_requirements_passed': [f'R{i:02d}' for i in range(3, 16)],
                             'optimization_requirements_reviewed': {key: {'status': 'unverified', 'reason': 'no optimization evidence in test fixture'} for key in ('R01', 'R02')}}
    }
    events = []
    for provider in ('claude_code', 'zcode_glm'):
        events.append(write('TEST_ONLY_' + provider + '.json', {'source_kind': 'test_fixture', 'provider': provider, 'provider_mode': 'real',
            'identity_source': 'native_connection', 'identity_status': 'verified', 'external_request_id': 'TEST_ONLY', 'model_version': 'TEST_ONLY',
            'candidate_sha256': candidate['sha256'], 'commit': commit, 'usage_source': 'reported', 'total_tokens': 1, 'raw_response_ref': raw}))
    fields = ('real_provider', 'identity_verified', 'usage_complete', 'human_reviewed', 'source_material_verified',
              'correction_verified', 'provenance_verified', 'bilingual_pairs_verified', 'cancel_recovery_verified', 'translation_failure_blocked')
    values['real_journeys'] = {'declared_available_entries': ['claude_code', 'zcode_glm'], 'journeys': [
        {**{key: True for key in fields}, 'domain': domain, 'provider_mode': 'real', 'a_canonical_author': 'A',
         'providers': ['claude_code', 'zcode_glm'], 'tested_entries': ['claude_code', 'zcode_glm'], 'artifact_refs': [raw], 'provider_event_refs': events}
        for domain in ('code', 'paper', 'document', 'composite')]}
    evidence = {}
    for name, value in values.items():
        reference = write('TEST_ONLY_reports/' + name + '.json', {'source_kind': 'test_fixture', 'status': 'passed', 'check': name,
             'candidate_sha256': candidate['sha256'], 'commit': commit, 'observer': 'fixture observer; no actual observation',
             'recorded_at': '2026-10-14T00:00:00Z', 'raw_evidence': [raw], **value})
        evidence[name] = {'status': 'passed', 'report': reference}
    manifest = {'schema_version': '1.0', 'candidate': candidate, 'commit': commit, 'dependency_locks': locks,
                'sbom': sbom, 'compatible_schema': 4, 'evidence': evidence}
    write('release/candidate-evidence.json', manifest)
    return manifest

