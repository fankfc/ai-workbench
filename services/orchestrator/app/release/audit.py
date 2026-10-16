"""Fail-closed candidate audits; missing observations remain blocked."""
from pathlib import Path
import subprocess
import json
import math
from .evidence import COMMIT, HEX, load_json, observed_report, safe_path, verify_file


MANDATORY = ('security_boundary', 'translation_review', 'accessibility_review', 'performance',
             'reliability_24h', 'backup_restore', 'windows_install', 'signed_update', 'real_journeys', 'beta_trial')
REQUIRED_FILES = ('release/beta-guide.md', 'release/known-limitations.md', 'release/update-rollback-runbook.md',
                  'release/backup-restore-runbook.md', 'ops/operations-runbook.md', 'ops/incident-runbook.md',
                  'ops/maintenance-calendar.md', 'release/customer-acceptance-record.md')
INSTALL_FIELDS = ('clean_windows_11_x64', 'non_admin', 'unicode_space_path', 'backend_started', 'exit_children_clean',
                  'user_files_preserved', 'unconnected_providers_pending', 'upgrade_uninstall_tested')
UPDATE_FIELDS = ('invalid_signature_rejected', 'unknown_publisher_rejected', 'tamper_rejected', 'replay_rejected',
                 'downgrade_rejected', 'consistent_backup_verified', 'checkpoints_saved', 'all_interruptions_tested',
                 'health_failure_rollback', 'compatible_schema_restored')
PERFORMANCE_LIMITS = {'input_echo_p95_ms': 100, 'ui_ack_p95_ms': 200, 'cancel_feedback_p95_ms': 500,
                      'state_visible_p95_ms': 1000, 'cold_start_p95_ms': 3000}


def performance_report_valid(base, report):
    if report.get('thresholds_preregistered') is not True or report.get('registered_limits_ms') != PERFORMANCE_LIMITS or not report.get('machine_profile'):
        return False
    try:
        samples = load_json(verify_file(base, report['samples_ref']))
        if (type(samples.get('lifecycle_cycles')) is not int or samples['lifecycle_cycles'] < 100
                or samples.get('orphan_pids') != []):
            return False
        metrics = report.get('metrics', {})
        if set(metrics) != set(PERFORMANCE_LIMITS):
            return False
        for name, limit in PERFORMANCE_LIMITS.items():
            observed = samples.get(name.replace('_p95_ms', '_samples_ms'))
            minimum = 200 if name == 'input_echo_p95_ms' else 30 if name == 'cold_start_p95_ms' else 1
            if (not isinstance(observed, list) or len(observed) < minimum
                    or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in observed)):
                return False
            measured = sorted(observed)[math.ceil(len(observed) * .95) - 1]
            if type(metrics[name]) not in (int, float) or metrics[name] != measured or measured > limit:
                return False
        return True
    except (KeyError, TypeError, ValueError, OSError):
        return False


def mandatory_report_valid(base, manifest, kind, report):
    """Check domain observations in addition to a report's passed label."""
    if kind == 'security_boundary':
        return (type(report.get('mandatory_cases_total')) is int and report['mandatory_cases_total'] > 0
                and report.get('mandatory_cases_passed') == report['mandatory_cases_total']
                and report.get('skipped') == [] and report.get('critical_findings') == [])
    if kind == 'translation_review':
        reviewers = report.get('human_reviewers', [])
        return (isinstance(reviewers, list) and all(isinstance(name, str) and name.strip() for name in reviewers)
                and len(set(reviewers)) >= 2 and report.get('critical_translation_errors') == 0
                and type(report.get('golden_samples')) is int and report['golden_samples'] >= 60
                and type(report.get('holdout_samples')) is int and report['holdout_samples'] >= 60
                and report.get('holdout_critical_errors') == 0 and report.get('holdout_independent') is True
                and report.get('reviewers_blinded') is True and report.get('high_impact_adjudicated') is True
                and isinstance(report.get('adjudicator'), str) and bool(report['adjudicator'].strip())
                and report['adjudicator'] not in reviewers
                and HEX.fullmatch(report.get('corpus_sha256', '') or '') is not None
                and HEX.fullmatch(report.get('holdout_sha256', '') or '') is not None)
    if kind == 'accessibility_review':
        manual = report.get('manual_evidence', {})
        if not bool(report.get('human_reviewers')) or not all(report.get(key) is True for key in ('keyboard', 'screen_reader', 'contrast', 'focus', 'actual_windows_ime', 'actual_multiscreen')):
            return False
        if set(manual) != {'ime', 'narrator', 'multiscreen'}:
            return False
        try:
            for ref in manual.values():
                verify_file(base, ref)
        except (ValueError, OSError, TypeError):
            return False
        return True
    if kind == 'performance':
        return performance_report_valid(base, report)
    if kind == 'reliability_24h':
        return (type(report.get('duration_seconds')) in (int, float) and report['duration_seconds'] >= 86400
                and report.get('completed') is True and report.get('critical_failures') == 0 and report.get('checkpoints_verified') is True)
    if kind == 'backup_restore':
        return all(report.get(key) is True for key in ('live_backup_consistent', 'isolated_restore_verified', 'corruption_rejected', 'newer_schema_rejected', 'source_preserved'))
    if kind == 'windows_install':
        return all(report.get(key) is True for key in INSTALL_FIELDS) and type(report.get('taskbar_windows')) is int and report['taskbar_windows'] == 1
    if kind == 'signed_update':
        return (all(report.get(key) is True for key in UPDATE_FIELDS)
                and report.get('restored_schema') == report.get('expected_schema')
                and type(report.get('expected_schema')) is int and report['expected_schema'] > 0)
    if kind == 'beta_trial':
        return (type(report.get('observed_workdays')) is int and report['observed_workdays'] >= 5
                and type(report.get('real_user_count')) is int and report['real_user_count'] > 0
                and report.get('open_p0_p1') == 0 and report.get('outputs_verified') is True and report.get('fixes_retested') is True)
    if kind == 'real_journeys':
        rows = report.get('journeys', [])
        if {row.get('domain') for row in rows if isinstance(row, dict)} != {'code', 'paper', 'document', 'composite'}:
            return False
        fields = ('real_provider', 'identity_verified', 'usage_complete', 'human_reviewed', 'source_material_verified',
                  'correction_verified', 'provenance_verified', 'bilingual_pairs_verified', 'cancel_recovery_verified', 'translation_failure_blocked')
        for row in rows:
            if (not all(row.get(key) is True for key in fields) or row.get('a_canonical_author') != 'A'
                    or row.get('provider_mode') != 'real' or row.get('providers') != ['claude_code', 'zcode_glm']
                    or not row.get('artifact_refs') or not row.get('provider_event_refs')):
                return False
            try:
                for ref in row['artifact_refs']:
                    verify_file(base, ref)
                events = [load_json(verify_file(base, ref)) for ref in row['provider_event_refs']]
                if {event.get('provider') for event in events} != {'claude_code', 'zcode_glm'}:
                    return False
                for event in events:
                    if (event.get('provider_mode') != 'real' or event.get('identity_source') != 'native_connection'
                            or event.get('identity_status') != 'verified' or not event.get('external_request_id')
                            or not event.get('model_version') or event.get('candidate_sha256') != manifest['candidate']['sha256']
                            or event.get('commit') != manifest['commit'] or event.get('usage_source') != 'reported'
                            or type(event.get('total_tokens')) is not int or event['total_tokens'] < 0):
                        return False
                    verify_file(base, event['raw_response_ref'])
            except (ValueError, OSError, TypeError, KeyError):
                return False
        declared = set(report.get('declared_available_entries', []))
        tested = set(entry for row in rows for entry in row.get('tested_entries', []))
        return bool(declared) and declared <= tested and ('gpt' not in declared or report.get('gpt_no_forced_translation_verified') is True)
    return False


def _manifest(base, options):
    name = options.get('evidence_manifest', 'release/candidate-evidence.json')
    path = safe_path(base, name)
    return load_json(path) if path.is_file() else {}


def _identity(base, manifest):
    reasons = []
    candidate = manifest.get('candidate') or {}
    digest = candidate.get('sha256')
    try:
        verify_file(base, candidate)
    except (ValueError, OSError):
        reasons.append('candidate_missing' if not candidate else 'candidate_integrity')
    commit = manifest.get('commit')
    if not COMMIT.fullmatch(commit or ''):
        reasons.append('source_commit_missing')
    if not HEX.fullmatch(digest or ''):
        digest = None
    return digest, commit, reasons


def _report(base, manifest, kind, *, allow_test_fixture=False):
    digest, commit, reasons = _identity(base, manifest)
    record = manifest.get('evidence', {}).get(kind)
    if not isinstance(record, dict) or record.get('status') != 'passed':
        reasons.append(kind + ('_skipped' if isinstance(record, dict) and record.get('status') == 'skipped' else '_missing'))
    if reasons:
        return None, reasons
    try:
        report = observed_report(base, record.get('report'), candidate_sha256=digest, commit=commit,
                                 allow_test_fixture=allow_test_fixture)
        if report.get('check') != kind:
            raise ValueError('EVIDENCE_CHECK_MISMATCH')
        return report, []
    except (ValueError, OSError, TypeError) as error:
        return None, [kind + ':' + str(error)]


def audit_manifest(base, manifest, *, allow_test_fixture=False):
    digest, commit, reasons = _identity(base, manifest)
    missing, skipped = list(reasons), []
    if not allow_test_fixture:
        observed = subprocess.run(['git', '-C', str(base), 'rev-parse', 'HEAD'], capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
        changes = subprocess.run(['git', '-C', str(base), 'status', '--porcelain', '--untracked-files=normal'], capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
        if observed.returncode != 0 or observed.stdout.strip() != commit:
            missing.append('source_commit_not_verified')
        if changes.returncode != 0 or changes.stdout.strip():
            missing.append('source_tree_not_frozen')
    if not isinstance(manifest.get('schema_version'), str) or manifest.get('schema_version') != '1.0':
        missing.append('manifest_schema')
    locks = manifest.get('dependency_locks', {})
    for required in ('package-lock.json', 'services/orchestrator/uv.lock'):
        try:
            ref = locks[required]
            if ref['path'] != required:
                raise ValueError('LOCK_PATH_MISMATCH')
            verify_file(base, ref)
        except (KeyError, TypeError, ValueError, OSError):
            missing.append('dependency_lock:' + required)
    try:
        sbom = load_json(verify_file(base, manifest['sbom']))
        if sbom.get('bomFormat') != 'CycloneDX' or not sbom.get('components'):
            raise ValueError('SBOM_EMPTY')
        properties = {row['name']: row['value'] for row in sbom['metadata']['properties']}
        if properties.get('inventory:status') != 'complete_verified_package':
            raise ValueError('SBOM_PACKAGE_AND_LICENSES_UNVERIFIED')
        for name, ref in locks.items():
            if properties.get('lock:' + name) != ref['sha256']:
                raise ValueError('SBOM_LOCK_MISMATCH')
    except (KeyError, TypeError, ValueError, OSError) as error:
        missing.append('sbom')
    for kind in MANDATORY:
        item = manifest.get('evidence', {}).get(kind)
        if isinstance(item, dict) and item.get('status') == 'skipped':
            skipped.append(kind)
        report, problems = _report(base, manifest, kind, allow_test_fixture=allow_test_fixture)
        if report is None:
            missing.extend(problems)
        elif not mandatory_report_valid(base, manifest, kind, report):
            missing.append(kind + '_observations_incomplete')
    # A native Authenticode observation is separate from installation assertions.
    signature, signature_errors = _report(base, manifest, 'authenticode', allow_test_fixture=allow_test_fixture)
    missing.extend(signature_errors)
    if signature and not signature_valid(base, signature):
        missing.append('authenticode_identity_or_chain')
    if signature and not allow_test_fixture and not native_signature_valid(base, manifest):
        missing.append('native_authenticode_verification')
    if type(manifest.get('compatible_schema')) is not int or manifest['compatible_schema'] < 1:
        missing.append('compatible_schema')
    return dict(valid=not missing and not skipped, missing_evidence=sorted(set(missing)),
                skipped_mandatory=skipped, artifact_hash_matches=not any(x.startswith('candidate_') for x in reasons),
                evidence_kind='audit', blocked_reasons=sorted(set(missing)))


def signature_valid(base, report):
    pins_path = Path(base) / 'release/publisher-allowlist.json'
    pins = load_json(pins_path).get('thumbprints', []) if pins_path.is_file() else []
    return (report.get('authenticode_status') == 'Valid' and report.get('chain_valid') is True
            and report.get('timestamp_valid') is True and report.get('is_test_certificate') is False
            and isinstance(report.get('publisher_thumbprint'), str)
            and report['publisher_thumbprint'].upper() in {item.upper() for item in pins})


def native_signature_valid(base, manifest):
    """Re-observe final candidate bytes with Windows trust; JSON is insufficient."""
    script = Path(base) / 'release/verify-installer.ps1'
    pins = Path(base) / 'release/publisher-allowlist.json'
    candidate = manifest.get('candidate') or {}
    if not script.is_file() or not pins.is_file() or not load_json(pins).get('thumbprints'):
        return False
    try:
        path = verify_file(base, candidate)
        result = subprocess.run(['pwsh.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script),
                                 '-Installer', str(path), '-Allowlist', str(pins), '-Commit', manifest.get('commit', '')],
                                capture_output=True, text=True, encoding='utf-8', timeout=45, check=False)
        report = json.loads(result.stdout)
        return (result.returncode == 0 and report.get('candidate_sha256') == candidate['sha256']
                and signature_valid(base, report))
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return False


def windows_install(base, options):
    manifest = _manifest(base, options)
    installation, reasons = _report(base, manifest, 'windows_install')
    signature, errors = _report(base, manifest, 'authenticode')
    reasons.extend(errors)
    publisher = bool(signature and signature_valid(base, signature) and native_signature_valid(base, manifest))
    if not publisher:
        reasons.append('trusted_signature_missing')
    tested = bool(installation and all(installation.get(key) is True for key in INSTALL_FIELDS)
                  and type(installation.get('taskbar_windows')) is int and installation['taskbar_windows'] == 1)
    if installation and not tested:
        reasons.append('installation_observations_incomplete')
    return dict(install_ok=publisher and tested, publisher_valid=publisher,
                backend_started=bool(installation and installation.get('backend_started') is True),
                user_files_preserved=bool(installation and installation.get('user_files_preserved') is True),
                taskbar_windows=installation.get('taskbar_windows', 0) if installation else 0,
                evidence_kind='audit', blocked_reasons=sorted(set(reasons)))


def signed_update(base, options):
    manifest = _manifest(base, options)
    report, reasons = _report(base, manifest, 'signed_update')
    valid = bool(report and mandatory_report_valid(base, manifest, 'signed_update', report))
    if report and not valid:
        reasons.append('update_matrix_incomplete')
    return dict(update_state='VERIFIED' if valid else 'BLOCKED', active_version=report.get('active_version', 'unknown') if report else 'unknown',
                previous_version=report.get('previous_version', 'unknown') if report else 'unknown',
                restored_schema=report.get('restored_schema', 0) if report else 0,
                expected_schema=report.get('expected_schema', 0) if report else 0,
                evidence_kind='audit', blocked_reasons=reasons)


def real_journey_audit(base, options):
    manifest = _manifest(base, options)
    report, reasons = _report(base, manifest, 'real_journeys')
    passed = []
    provenance = pairs = identity = entries = False
    if report:
        journeys = report.get('journeys', [])
        declared = set(report.get('declared_available_entries', []))
        tested_entries = set()
        for row in journeys:
            if not isinstance(row, dict):
                continue
            fields = ('real_provider', 'identity_verified', 'usage_complete', 'human_reviewed', 'source_material_verified',
                      'correction_verified', 'provenance_verified', 'bilingual_pairs_verified', 'cancel_recovery_verified', 'translation_failure_blocked')
            if (row.get('domain') in ('code', 'paper', 'document', 'composite') and all(row.get(key) is True for key in fields)
                    and row.get('a_canonical_author') == 'A' and row.get('provider_mode') == 'real'
                    and row.get('providers') == ['claude_code', 'zcode_glm'] and row.get('artifact_refs')
                    and row.get('provider_event_refs')):
                try:
                    for ref in row['artifact_refs']:
                        verify_file(base, ref)
                    events = [load_json(verify_file(base, ref)) for ref in row['provider_event_refs']]
                    identities = {event.get('provider') for event in events if
                                  event.get('provider_mode') == 'real' and event.get('identity_source') == 'native_connection'
                                  and event.get('identity_status') == 'verified' and event.get('external_request_id')
                                  and event.get('model_version') and event.get('candidate_sha256') == manifest['candidate']['sha256']
                                  and event.get('commit') == manifest['commit'] and event.get('usage_source') == 'reported'
                                  and type(event.get('total_tokens')) is int and event['total_tokens'] >= 0
                                  and event.get('raw_response_ref')}
                    if identities != {'claude_code', 'zcode_glm'}:
                        raise ValueError('REAL_PROVIDER_OBSERVATIONS_REQUIRED')
                    for event in events:
                        verify_file(base, event['raw_response_ref'])
                    passed.append(row['domain'])
                    tested_entries.update(row.get('tested_entries', []))
                except (ValueError, OSError, TypeError, KeyError):
                    reasons.append('journey_artifact_integrity')
        complete = set(passed) == {'code', 'paper', 'document', 'composite'}
        provenance = pairs = identity = complete
        entries = complete and bool(declared) and declared <= tested_entries
        if 'gpt' in declared and report.get('gpt_no_forced_translation_verified') is not True:
            entries = False
        if not (complete and entries):
            reasons.append('real_journeys_incomplete')
    return dict(domains_passed=sorted(set(passed)), provenance_valid=provenance, pairs_valid=pairs,
                model_identity_verified=identity, all_required_entries_tested=entries,
                evidence_kind='audit', blocked_reasons=sorted(set(reasons)))


def release_decision(base, options, *, allow_test_fixture=False):
    manifest = _manifest(base, options)
    audit = audit_manifest(base, manifest, allow_test_fixture=allow_test_fixture)
    reasons = list(audit['missing_evidence'])
    if not allow_test_fixture:
        for evaluator in (windows_install, signed_update, real_journey_audit):
            result = evaluator(base, options)
            reasons.extend(result['blocked_reasons'])
    approvals, errors = _report(base, manifest, 'release_approval', allow_test_fixture=allow_test_fixture)
    reasons.extend(errors)
    if approvals:
        required = {'product', 'qa', 'release'}
        rows = approvals.get('approvals', [])
        if ({row.get('role') for row in rows if row.get('decision') == 'go'} != required
                or len({row.get('reviewer') for row in rows}) != 3
                or approvals.get('open_p0_p1') != 0
                or set(approvals.get('functional_requirements_passed', [])) != {f'R{i:02d}' for i in range(3, 16)}
                or set(approvals.get('optimization_requirements_reviewed', {})) != {'R01', 'R02'}
                or any(value.get('status') not in {'unverified', 'failed', 'passed'} or not value.get('reason')
                       for value in approvals.get('optimization_requirements_reviewed', {}).values())):
            reasons.append('independent_release_approval_incomplete')
    optimization, errors = _report(base, manifest, 'optimization_qualification', allow_test_fixture=allow_test_fixture)
    qualified = []
    optimization_errors = list(errors)
    if optimization:
        try:
            from app.quality.eligibility import evaluate_eligibility
            qualification = evaluate_eligibility(optimization['registration'], optimization['evidence'], optimization['configuration'])
            if qualification['eligible'] and qualification['optimization_goal_met']:
                scopes = qualification.get('qualified_scope', [])
                if isinstance(scopes, list) and scopes and all(isinstance(scope, dict) and scope == optimization['configuration'] for scope in scopes):
                    qualified = [scope['domain'] + '/' + scope['difficulty'] + '@' + qualification['qualification_key'] for scope in scopes]
        except (ImportError, KeyError, TypeError, ValueError):
            optimization_errors.append('optimization_evaluator_or_evidence_invalid')
    functional = not reasons
    optimization_met = functional and bool(qualified)
    if not qualified:
        reasons.extend(optimization_errors or ['optimization_evidence'])
    return dict(functional_release=functional, optimization_goal_met=optimization_met,
                blocked_reasons=sorted(set(reasons)), qualified_scope=qualified if optimization_met else [], evidence_kind='audit')


def final_handover(base, options):
    decision = release_decision(base, options)
    missing_files = [name for name in REQUIRED_FILES if not (Path(base) / name).is_file()]
    manifest = _manifest(base, options)
    report, reasons = _report(base, manifest, 'final_handover')
    handover_valid = bool(report and report.get('independent_clean_machine_acceptance') is True
                          and report.get('user_signature') and report.get('functional_signature')
                          and report.get('offline_hash_index_verified') is True)
    open_items = list(decision['blocked_reasons']) + missing_files + reasons
    if not decision['optimization_goal_met']:
        open_items.append('optimization_evidence')
    if not handover_valid:
        open_items.append('independent_handover_acceptance')
    functional = decision['functional_release'] and handover_valid and not missing_files
    return dict(files_complete=not missing_files, evidence_valid=handover_valid and decision['functional_release'],
                functional_complete=functional, optimization_complete=decision['optimization_goal_met'],
                overall_goal_complete=functional and decision['optimization_goal_met'],
                open_items=sorted(set(open_items)), blocked_reasons=sorted(set(open_items)), evidence_kind='audit')
