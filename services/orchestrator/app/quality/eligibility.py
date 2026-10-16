"""Joint qualification with pre-registered, simultaneous one-sided bounds.

The finite-sample Hoeffding bound needs independent held-out pairs and known
score/token ranges. Bonferroni covers six quality dimensions plus A token
saving across all twelve domain/difficulty layers. Synthetic checks cannot
qualify a product configuration. An evidence importer must verify provenance;
this evaluator additionally checks the raw sample bytes and registered scope.
"""
import hashlib
import json
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path

DIMENSIONS = ('correctness', 'completeness', 'reasoning', 'evidence', 'consistency', 'usability')
DOMAINS = ('code', 'paper', 'document', 'composite')
DIFFICULTIES = ('easy', 'medium', 'hard')
CONFIG_FIELDS = ('a_version', 'b_version', 'domain', 'difficulty', 'task_profile',
                 'translation_policy', 'glossary_version', 'scheduling_policy', 'protocol_hash')


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def registration_hash(registration):
    return canonical_hash({k: v for k, v in registration.items() if k != 'registration_sha256'})


def configuration_key(configuration):
    if any(not isinstance(configuration.get(k), str) or not configuration[k].strip() for k in CONFIG_FIELDS):
        raise ValueError('QUALIFICATION_CONFIGURATION_INCOMPLETE')
    if configuration['domain'] not in DOMAINS or configuration['difficulty'] not in DIFFICULTIES:
        raise ValueError('QUALIFICATION_SCOPE_INVALID')
    return canonical_hash({k: configuration[k] for k in CONFIG_FIELDS})


def lower_bound(values, *, lower, upper, alpha, comparisons):
    """One-sided distribution-free bound; values must fit registered bounds."""
    if (not values or not 0 < alpha < 1 or type(comparisons) is not int or comparisons < 1
            or not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper):
        raise ValueError('INVALID_CONFIDENCE_INPUT')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not lower <= v <= upper for v in values):
        raise ValueError('INVALID_BOUNDED_OBSERVATION')
    return math.fsum(values) / len(values) - (upper - lower) * math.sqrt(math.log(comparisons / alpha) / (2 * len(values)))


def _utc(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            return None
        return result
    except (AttributeError, ValueError, TypeError):
        return None


def audit_registration(registration):
    issues = []
    try:
        valid_hash = registration.get('registration_sha256') == registration_hash(registration)
    except (TypeError, ValueError):
        valid_hash = False
    if not valid_hash:
        issues.append('REGISTRATION_HASH_MISMATCH')
    if registration.get('status') != 'frozen' or _utc(registration.get('frozen_at')) is None:
        issues.append('PROTOCOL_NOT_FROZEN')
    method = registration.get('statistics', {})
    if (method.get('method') != 'paired_hoeffding_bonferroni' or method.get('alpha') != .05
            or method.get('family_comparisons') != 84 or method.get('quality_lower_bound_min') != 0
            or method.get('token_saving_lower_bound_strict_min') != 0
            or tuple(method.get('dimensions', ())) != DIMENSIONS):
        issues.append('STATISTICAL_PROTOCOL_INVALID')
    scopes = registration.get('scopes', [])
    if {(s.get('domain'), s.get('difficulty')) for s in scopes} != {(d, level) for d in DOMAINS for level in DIFFICULTIES} or len(scopes) != 12:
        issues.append('TWELVE_LAYER_REGISTRATION_INCOMPLETE')
    if any(type(s.get('formal_sample_size')) is not int or s['formal_sample_size'] < 2 for s in scopes) or not scopes:
        issues.append('FORMAL_SAMPLE_SIZE_UNREGISTERED')
    if any(type(s.get('max_a_tokens')) is not int or s['max_a_tokens'] <= 0 for s in scopes):
        issues.append('A_TOKEN_BOUND_UNREGISTERED')
    pilots = registration.get('pilots', [])
    if len(pilots) != 60 or len({p.get('id') for p in pilots}) != 60 or any(p.get('source_kind') != 'external' or not p.get('sha256') for p in pilots):
        issues.append('PILOT_EVIDENCE_MISSING')
    elif any(sum(p.get('domain') == s.get('domain') and p.get('difficulty') == s.get('difficulty') for p in pilots) != 5 for s in scopes):
        issues.append('PILOT_STRATA_INCOMPLETE')
    if not registration.get('power_analysis') or _utc(registration.get('analysis_at')) is None or not registration.get('stopping_rule'):
        issues.append('POWER_OR_STOPPING_RULE_MISSING')
    reviewers = registration.get('reviewers', [])
    if len({r.get('id') for r in reviewers if r.get('independent') is True}) < 2:
        issues.append('INDEPENDENT_REVIEWERS_MISSING')
    if not registration.get('adjudicator') or len(registration.get('signatures', [])) < 3:
        issues.append('FREEZE_SIGNATURES_MISSING')
    if registration.get('failure_policy') != 'include_all_attempts_zero_failed_quality':
        issues.append('FAILURE_ACCOUNTING_UNREGISTERED')
    holdout = registration.get('holdout_ids', [])
    reserved = set(registration.get('tuning_ids', [])) | {p.get('id') for p in pilots}
    if not holdout or len(holdout) != len(set(holdout)):
        issues.append('INDEPENDENT_HOLDOUT_MISSING')
    if reserved.intersection(holdout):
        issues.append('HOLDOUT_CONTAMINATED')
    if registration.get('equal_materials_tools_deliverables') is not True or registration.get('a_canonical_required') is not True:
        issues.append('COMPARISON_CONTRACT_INCOMPLETE')
    return dict(frozen=not issues, issues=sorted(set(issues)), registration_hash_valid=valid_hash)


def _sample_file(evidence):
    root = Path(evidence['evidence_root'])
    records = read_proof(root, dict(path=evidence['samples_path'],sha256=evidence['samples_sha256'],size=evidence['samples_size']))
    if not isinstance(records, list) or records != evidence.get('samples'):
        raise ValueError('RAW_SAMPLES_CONTENT_MISMATCH')
    return records


def read_proof(root, reference, *, binary=False):
    root = Path(root).resolve(strict=True)
    relative = reference['path']
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
            or '..' in Path(relative).parts or Path(relative).is_absolute()):
        raise ValueError('PROOF_PATH_INVALID')
    path = root / relative
    from app.runtime.workspace import _reject_reparse
    _reject_reparse(path)
    if not path.resolve(strict=True).is_relative_to(root) or path.stat().st_nlink > 1:
        raise ValueError('PROOF_PATH_INVALID')
    data = path.read_bytes()
    if type(reference.get('size')) is not int or len(data) != reference['size'] or hashlib.sha256(data).hexdigest() != reference['sha256']:
        raise ValueError('PROOF_HASH_MISMATCH')
    return data if binary else json.loads(data.decode('utf-8'))


def _bound_reports(evidence, name):
    refs = evidence[name]
    if not isinstance(refs, list) or not refs:
        raise ValueError('PROOF_REPORTS_MISSING')
    reports = []
    for ref in refs:
        report = read_proof(evidence['evidence_root'], ref)
        if (not isinstance(report, dict) or report.get('source_kind') != 'external'
                or report.get('candidate_sha256') != evidence.get('candidate_sha256')
                or report.get('commit') != evidence.get('commit')
                or _utc(report.get('observed_at')) is None):
            raise ValueError('PROOF_BINDING_INVALID')
        reports.append(report)
    return reports


def _verify_real_provenance(registration, evidence, configuration, samples):
    reasons = []
    try:
        candidate = read_proof(evidence['evidence_root'],dict(path=evidence['candidate_path'],sha256=evidence['candidate_sha256'],size=evidence['candidate_size']),binary=True)
        if not candidate or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',evidence['commit']):
            raise ValueError('CANDIDATE_IDENTITY_INVALID')
        source_root = Path(evidence['source_root']).resolve(strict=True)
        if source_root != Path(__file__).resolve().parents[4]:
            raise ValueError('SOURCE_ROOT_MISMATCH')
        current = subprocess.run(['git','-C',str(source_root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=10,check=False)
        clean = subprocess.run(['git','-C',str(source_root),'status','--porcelain'],capture_output=True,text=True,timeout=10,check=False)
        if current.returncode or clean.returncode or current.stdout.strip() != evidence['commit'] or clean.stdout.strip():
            raise ValueError('SOURCE_IDENTITY_INVALID')
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        reasons.append('CANDIDATE_OR_SOURCE_IDENTITY_INVALID')
    try:
        identities = _bound_reports(evidence,'identity_reports')
        by_role = {r['role']:r for r in identities}
        if set(by_role) != {'A','B'} or len(identities) != 2:
            raise ValueError('IDENTITY_ROLES_INVALID')
        for role,field in [('A','a_version'),('B','b_version')]:
            report = by_role[role]
            wire = read_proof(evidence['evidence_root'], report['wire_receipt'])
            permitted = {'claude_code':'claude','claude-code':'claude','codex':'gpt','gpt':'gpt'} if role=='A' else {'zcode':'glm'}
            expected_family = permitted.get(report.get('adapter'))
            if (report.get('actual_version') != configuration[field] or report.get('identity_status') != 'verified'
                    or expected_family is None or report.get('family') != expected_family
                    or report.get('identity_source') != 'native_connection'
                    or wire.get('source_kind') != 'external' or wire.get('model_version') != configuration[field]
                    or wire.get('family') != expected_family or wire.get('identity_source') != 'native_connection'
                    or wire.get('identity_status') != 'verified'
                    or not wire.get('request_id') or wire.get('adapter') != report.get('adapter')):
                raise ValueError('IDENTITY_RECEIPT_INVALID')
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        reasons.append('HASHED_IDENTITY_REPORTS_INVALID')
    try:
        reviews = _bound_reports(evidence,'review_reports')
        by_sample = {r['sample_id']:r for r in reviews}
        if len(by_sample) != len(samples) or len(reviews) != len(samples):
            raise ValueError('REVIEW_COVERAGE_INVALID')
        registered = {r['id'] for r in registration.get('reviewers',[]) if r.get('independent') is True}
        for sample in samples:
            report = by_sample[sample['id']]
            reviewed = report['reviews']
            if (len(reviewed) < 2 or len({r['reviewer_id'] for r in reviewed}) != len(reviewed)
                    or not all(r['reviewer_id'] in registered and r.get('independent') is True and r.get('blind') is True for r in reviewed)
                    or len(set(report['blind_labels'].values())) != 2
                    or any(configuration[f] in label for label in report['blind_labels'].values() for f in ('a_version','b_version'))):
                raise ValueError('BLIND_REVIEW_INVALID')
            # Domain adjudicator approves the aggregate and records all named
            # independent scores. No model-created PASS can substitute for it.
            if report.get('adjudicator') != registration.get('adjudicator') or report.get('adjudicated') is not True:
                raise ValueError('REVIEW_ADJUDICATION_MISSING')
            for arm in ('baseline','collaborative'):
                if report[arm+'_scores'] != sample[arm+'_scores'] or report[arm+'_critical_defects'] != sample[arm+'_critical_defects']:
                    raise ValueError('REVIEW_SCORE_MISMATCH')
                for review in reviewed:
                    scores = review[arm+'_scores']
                    if set(scores) != set(DIMENSIONS) or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in scores.values()):
                        raise ValueError('REVIEW_SCORES_INVALID')
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        reasons.append('HASHED_REVIEW_REPORTS_INVALID')
    try:
        usage = _bound_reports(evidence,'usage_reports')
        by_sample = {r['sample_id']:r for r in usage}
        if len(by_sample) != len(samples) or len(usage) != len(samples):
            raise ValueError('USAGE_COVERAGE_INVALID')
        from app.usage.normalization import normalize_usage
        for sample in samples:
            report = by_sample[sample['id']]
            for arm in ('baseline','collaborative'):
                record = report[arm]
                requests = record['requests']
                submitted = set(record['submitted_request_ids'])
                unique = {}
                total_a = 0
                for request in requests:
                    rid = request['request_id']
                    if rid in unique:
                        if unique[rid] != request:
                            raise ValueError('USAGE_REQUEST_CONFLICT')
                        continue
                    unique[rid] = request
                    raw = read_proof(evidence['evidence_root'], request['wire_receipt'])
                    if (raw.get('source_kind') != 'external' or raw.get('request_id') != rid
                            or request.get('source') != 'reported' or request.get('status') not in ('completed','failed','cancelled')
                            or request.get('function') not in ('planning','translation','execution','review','takeover')
                            or request.get('role') not in ('A','B')):
                        raise ValueError('RAW_USAGE_RECEIPT_INVALID')
                    normalized = normalize_usage(request['provider'],raw['usage'],source='reported')
                    if normalized['total_tokens'] is None:
                        raise ValueError('RAW_USAGE_UNKNOWN')
                    if request['role'] == 'A':
                        total_a += normalized['total_tokens']
                # The hashed product submission log is checked against every
                # receipt, including failed/cancelled/translation attempts.
                trace = read_proof(evidence['evidence_root'],record['submission_log'])
                if (set(unique) != submitted or set(trace['submitted_request_ids']) != submitted
                        or trace.get('source_kind') != 'external' or trace.get('sample_id') != sample['id']
                        or trace.get('arm') != arm or record.get('all_attempts_included') is not True
                        or sample[arm+'_a_tokens'] != total_a):
                    raise ValueError('ALL_ATTEMPT_USAGE_MISMATCH')
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        reasons.append('HASHED_USAGE_REPORTS_INVALID')
    return reasons


def evaluate_eligibility(registration, evidence, configuration):
    if not all(isinstance(v,dict) for v in (registration,evidence,configuration)):
        return dict(eligible=False,optimization_goal_met=False,route='a_led',blocked_reasons=['EVIDENCE_STRUCTURE_INVALID'],
                    qualification_key=None,quality_bounds={},token_savings_lower_bound=None,qualified_scope=[],sample_count=0)
    try:
        audit = audit_registration(registration)
    except (ValueError,TypeError,KeyError,AttributeError):
        audit = dict(frozen=False,issues=['REGISTRATION_STRUCTURE_INVALID'])
    reasons = list(audit['issues'])
    try:
        key = configuration_key(configuration)
    except (ValueError, TypeError):
        key = None
        reasons.append('QUALIFICATION_CONFIGURATION_INCOMPLETE')
    if configuration.get('protocol_hash') != registration.get('registration_sha256'):
        reasons.append('PROTOCOL_VERSION_MISMATCH')
    if evidence.get('source_kind') != 'external' or evidence.get('evidence_kind') != 'real_evaluation':
        reasons.append('REAL_EVALUATION_EVIDENCE_MISSING')
    if evidence.get('configuration') != configuration or evidence.get('protocol_hash') != registration.get('registration_sha256'):
        reasons.append('EVIDENCE_CONFIGURATION_MISMATCH')
    if (not evidence.get('candidate_sha256') or not evidence.get('commit')
            or _utc(evidence.get('observed_at')) is None or not evidence.get('identity_reports')
            or not evidence.get('review_reports') or not evidence.get('usage_reports')):
        reasons.append('REAL_PROVENANCE_REVIEW_OR_USAGE_MISSING')
    frozen_at = _utc(registration.get('frozen_at'))
    observed_at = _utc(evidence.get('observed_at'))
    if frozen_at and observed_at and observed_at < frozen_at:
        reasons.append('EVIDENCE_PREDATES_FREEZE')
    try:
        samples = _sample_file(evidence)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        samples = []
        reasons.append('HASHED_RAW_SAMPLES_MISSING_OR_INVALID')
    reasons.extend(_verify_real_provenance(registration,evidence,configuration,samples))
    scopes = registration.get('scopes', [])
    if not isinstance(scopes,list):
        scopes=[]
    scope = next((s for s in scopes if isinstance(s,dict) and s.get('domain') == configuration.get('domain') and s.get('difficulty') == configuration.get('difficulty')), None)
    if not scope or scope.get('configuration') != {k:v for k,v in configuration.items() if k!='protocol_hash'}:
        reasons.append('CONFIGURATION_NOT_REGISTERED')
    if not scope or type(scope.get('formal_sample_size')) is not int or len(samples) != scope.get('formal_sample_size'):
        reasons.append('FORMAL_SAMPLE_COUNT_MISMATCH')
    quality = {dimension: [] for dimension in DIMENSIONS}
    savings = []
    sample_ids = set()
    for sample in samples:
        try:
            sid = sample['id']
            if sid in sample_ids or sid not in registration.get('holdout_ids', []):
                raise ValueError('HOLDOUT_PAIR_INVALID')
            sample_ids.add(sid)
            if sample.get('source_kind') != 'external' or sample.get('configuration') != configuration or sample.get('blind_review_complete') is not True or sample.get('randomized_order') is not True:
                raise ValueError('PAIR_PROVENANCE_OR_BLIND_REVIEW_INVALID')
            if (type(sample.get('baseline_critical_defects')) is not int or type(sample.get('collaborative_critical_defects')) is not int
                    or sample['baseline_critical_defects']<0 or sample['collaborative_critical_defects']<0
                    or sample['collaborative_critical_defects'] > sample['baseline_critical_defects']):
                raise ValueError('NEW_CRITICAL_DEFECT')
            for arm in ('baseline', 'collaborative'):
                if type(sample.get(arm+'_qualified_delivery')) is not bool:
                    raise ValueError('DELIVERY_STATUS_MISSING')
                if sample.get(arm + '_usage_complete') is not True or sample.get(arm + '_usage_source') != 'reported' or sample.get(arm + '_all_attempts_included') is not True:
                    raise ValueError('PAIR_USAGE_INCOMPLETE')
                for dimension in DIMENSIONS:
                    score = sample[arm + '_scores'][dimension]
                    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError('QUALITY_SCORE_INVALID')
                    if sample.get(arm + '_qualified_delivery') is False and score != 0:
                        raise ValueError('FAILED_DELIVERY_NOT_SCORED_ZERO')
                tokens = sample[arm + '_a_tokens']
                if type(tokens) is not int or not 0 <= tokens <= scope['max_a_tokens']:
                    raise ValueError('A_TOKEN_COUNT_OR_BOUND_INVALID')
            for dimension in DIMENSIONS:
                quality[dimension].append(sample['collaborative_scores'][dimension] - sample['baseline_scores'][dimension])
            savings.append(sample['baseline_a_tokens'] - sample['collaborative_a_tokens'])
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            reasons.append(str(error))
    bounds = {}
    token_bound = None
    if samples and len(savings) == len(samples) and scope and type(scope.get('max_a_tokens')) is int and scope['max_a_tokens'] > 0:
        bounds = {dimension: lower_bound(values, lower=-1, upper=1, alpha=.05, comparisons=84) for dimension, values in quality.items()}
        token_bound = lower_bound(savings, lower=-scope['max_a_tokens'], upper=scope['max_a_tokens'], alpha=.05, comparisons=84)
        if any(bound < 0 for bound in bounds.values()):
            reasons.append('QUALITY_NONINFERIORITY_UNPROVEN')
        if token_bound <= 0:
            reasons.append('POSITIVE_A_TOKEN_SAVING_UNPROVEN')
    else:
        reasons.append('PAIRED_STATISTICAL_EVIDENCE_INCOMPLETE')
    reasons = sorted(set(reasons))
    eligible = not reasons
    return dict(eligible=eligible, optimization_goal_met=eligible,
        route='qualified_collaboration' if eligible else 'a_led', blocked_reasons=reasons,
        route_mode='qualified_collaboration' if eligible else 'a_led',reason_codes=reasons,product_goal_complete=eligible,
        qualification_key=key, quality_bounds=bounds, token_savings_lower_bound=token_bound,
        qualified_scope=[configuration] if eligible else [], sample_count=len(samples),
        confidence_method='paired_hoeffding_bonferroni', family_comparisons=84)
