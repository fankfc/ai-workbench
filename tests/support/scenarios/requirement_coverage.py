"""Audit the frozen matrix and case inventory; coverage is not a pass result."""
import json
import re
from pathlib import Path

from app.quality.eligibility import canonical_hash, read_proof
from support.manifest import write_json,source_build_id

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={'remove_case': dict(type='string')})
RESULT_SCHEMA = dict(type='object', required=['missing_requirements', 'unresolved_mandatory', 'release_complete'])
REPO = Path(__file__).resolve().parents[3]


def _verified_case(case):
    if case.get('acceptance_status') != 'verified' or not case.get('evidence'):
        return False
    try:
        reports=[read_proof(REPO,ref) for ref in case['evidence']]
        for report in reports:
            if (report.get('case_id') != case['case_id'] or report.get('build_id') != source_build_id()
                    or report.get('status') != 'passed' or not report.get('raw_evidence')):
                return False
            for raw in report['raw_evidence']:
                read_proof(REPO,raw,binary=True)
            if case['kind']=='automatic':
                if report.get('source_kind')!='local_automated' or report.get('exit_code')!=0 or report.get('skipped')!=0 or report.get('xfail')!=0:
                    return False
            elif report.get('source_kind')!='external' or not report.get('observer') or not report.get('observed_at'):
                return False
        return True
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return False


def run(root, options):
    matrix = json.loads((REPO / 'quality/requirements-matrix.json').read_text(encoding='utf-8'))
    manifest = json.loads((REPO / 'quality/regression-manifest.json').read_text(encoding='utf-8'))
    valid_hash = manifest['sha256'] == canonical_hash({k: v for k, v in manifest.items() if k != 'sha256'})
    valid_hash = valid_hash and manifest['requirements_matrix_sha256']==canonical_hash(matrix)
    cases = manifest['cases']
    remove = options.get('remove_case')
    if remove and remove not in {c['case_id'] for c in cases}:
        raise ValueError('UNKNOWN_CASE')
    cases = [c for c in cases if c['case_id'] != remove]
    records = matrix['requirements']
    missing = sorted({f'R{i:02}' for i in range(1, 16)} - {r['id'] for r in records})
    unresolved = set(missing)
    details = []
    indexed = {c['case_id']: c for c in cases}
    for requirement in records:
        issues = []
        if not requirement['mandatory_cases']:
            issues.append('MANDATORY_CASES_EMPTY')
        for case_id in requirement['mandatory_cases']:
            case = indexed.get(case_id)
            if case is None:
                issues.append('CASE_MISSING:' + case_id)
                continue
            if case['kind'] == 'automatic' and not (REPO / case['path']).is_file():
                issues.append('TEST_FILE_MISSING:' + case_id)
            # Inventory entries never stand in for a test run, human signature,
            # or real-provider receipt. Evidence must be imported separately.
            if not _verified_case(case):
                issues.append('ACCEPTANCE_EVIDENCE_MISSING:' + case_id)
        if not valid_hash:
            issues.append('REGRESSION_HASH_MISMATCH')
        if issues:
            unresolved.add(requirement['id'])
        details.append(dict(requirement=requirement['id'], gate=requirement['gate'], issues=issues))
    functional = {r['id'] for r in records if r['gate'] == 'functional'}
    optimization = {r['id'] for r in records if r['gate'] == 'optimization'}
    result = dict(missing_requirements=missing, unresolved_mandatory=sorted(unresolved),
        release_complete=not bool(functional.intersection(unresolved)),
        optimization_goal_met=not bool(optimization.intersection(unresolved)),
        mapped_requirements=len(records), translation_cases=sum(bool(re.fullmatch(r'T\d{2}',c['case_id'])) for c in cases),
        regression_hash_valid=valid_hash, per_requirement=details, provider_boundary='none',
        real_provider_verified=False)
    write_json(Path(root) / 'coverage-report.json', result)
    return result
