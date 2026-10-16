"""Bind ten work-order protocol sections to one fresh local regression.

The stage-four executor runs the commands. This wrapper adds only the reviewed
stage-five map, role-resource snapshots and a sealed current-run summary.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import phase_four_verify as regression
from support.manifest import create_manifest, source_build_id, validate_manifest, verification_source_id, write_json
from app.runtime.workspace import _reject_reparse

MAP_PATH = REPO / 'quality/work-orders.json'
SPEC_PATH = 'docs/superpowers/plans/2026-10-13-execution/05-work-orders-and-prompts.md'
SPEC_FILE = REPO / SPEC_PATH
# A changed map needs source review and an explicit verifier update.
APPROVED_MAP_SHA256 = '68a418544c0460e4d7a57c657dba74ec5bf441a08560bdd6980e7fe548bdd2ab'
REQUIRED_IDS = tuple(f'SEC{i:02d}' for i in range(1, 11))
build_coverage = regression.build_coverage
digest = regression.digest


def _test_reference(reference, repo):
    if not isinstance(reference, dict) or set(reference) != {'runner', 'id'}:
        raise ValueError('TEST_REFERENCE_INVALID')
    runner, identity = reference['runner'], reference['id']
    if runner not in regression.RUNNERS or not isinstance(identity, str) or identity.count('::') != 1:
        raise ValueError('TEST_ID_INVALID')
    relative, name = identity.split('::')
    prefix, suffix = {'pytest': ('tests/', '.py'), 'vitest': ('tests/desktop/', '.test.ts'),
                      'playwright': ('tests/e2e/', '.spec.ts')}[runner]
    path = PurePosixPath(relative)
    if (not relative.startswith(prefix) or not relative.endswith(suffix) or '..' in path.parts
            or path.is_absolute() or '\\' in relative or ':' in relative or not name):
        raise ValueError('TEST_PATH_OUTSIDE_SOURCE')
    source_path = Path(repo) / relative
    _reject_reparse(source_path)
    if not source_path.resolve().is_relative_to(Path(repo).resolve()):
        raise ValueError('TEST_PATH_OUTSIDE_SOURCE')
    source = source_path.read_text(encoding='utf-8-sig')
    if runner != 'pytest':
        literals = re.findall(r"\b(?:test|it)\(\s*(['\"])(.*?)\1", source)
        if not any(name == title or runner == 'vitest' and name.endswith(' ' + title) for _, title in literals):
            raise ValueError('EXACT_TEST_DEFINITION_MISSING')
        return
    base = name.split('[', 1)[0]
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == base]
    if len(functions) != 1:
        raise ValueError('EXACT_TEST_DEFINITION_MISSING')
    decorators = [node for node in functions[0].decorator_list if 'parametrize' in ast.unparse(node)]
    expected = {base}
    if decorators:
        if len(decorators) != 1:
            raise ValueError('PARAMETER_IDS_REQUIRE_REVIEW')
        decorator = decorators[0]
        explicit = next((node.value for node in decorator.keywords if node.arg == 'ids'), None)
        values = ast.literal_eval(explicit if explicit is not None else decorator.args[1])
        if (not isinstance(values, (tuple, list)) or not values
                or not all(type(value) in (str, int) for value in values)
                or len({str(value) for value in values}) != len(values)):
            raise ValueError('PARAMETER_IDS_REQUIRE_REVIEW')
        expected = {base + '[' + str(value) + ']' for value in values}
    if name not in expected:
        raise ValueError('EXACT_PARAMETER_ID_MISSING')


def validate_mapping(value, *, repo=REPO):
    fields = {'schema_version', 'spec_path', 'spec_sha256', 'coverage_scope', 'items'}
    if not isinstance(value, dict) or set(value) != fields:
        return ['MAPPING_FIELDS_INVALID']
    issues = []
    if value['schema_version'] != '1.0' or value['spec_path'] != SPEC_PATH:
        issues.append('MAPPING_PROTOCOL_INVALID')
    try:
        _reject_reparse(Path(repo) / SPEC_PATH)
        if digest(Path(repo) / SPEC_PATH) != value['spec_sha256']:
            issues.append('SPEC_BYTES_CHANGED')
    except (OSError, ValueError):
        issues.append('SPEC_UNREADABLE')
    if not isinstance(value['coverage_scope'], str) or not value['coverage_scope'].strip():
        issues.append('COVERAGE_SCOPE_MISSING')
    rows = value['items']
    if not isinstance(rows, list):
        return issues + ['MAPPING_ITEMS_INVALID']
    if [row.get('id') if isinstance(row, dict) else None for row in rows] != list(REQUIRED_IDS):
        issues.append('MAPPING_IDS_MISSING_DUPLICATE_OR_UNORDERED')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'title', 'tests', 'external_requirements'}:
            issues.append('MAPPING_ITEM_FIELDS_INVALID')
            continue
        if not isinstance(row['title'], str) or not row['title'].strip():
            issues.append(str(row['id']) + ':TITLE_MISSING')
        limits = row['external_requirements']
        if not isinstance(limits, list) or not limits or any(not isinstance(x, str) or not x.strip() for x in limits):
            issues.append(str(row['id']) + ':EXTERNAL_REQUIREMENTS_MISSING')
        tests = row['tests']
        if not isinstance(tests, list) or not tests:
            issues.append(str(row['id']) + ':TESTS_MISSING')
            continue
        seen = set()
        for reference in tests:
            try:
                _test_reference(reference, repo)
                key = (reference['runner'], reference['id'])
                if key in seen:
                    raise ValueError('TEST_REFERENCE_DUPLICATE')
                seen.add(key)
            except (OSError, ValueError, TypeError, SyntaxError, KeyError, AttributeError, IndexError) as error:
                issues.append(str(row['id']) + ':' + str(error))
    return issues


def load_mapping(path=MAP_PATH):
    _reject_reparse(Path(path))
    if digest(path) != APPROVED_MAP_SHA256:
        raise ValueError('MAPPING_DIGEST_UNREVIEWED')
    mapping = json.loads(Path(path).read_text(encoding='utf-8'))
    issues = validate_mapping(mapping)
    if issues:
        raise ValueError('MAPPING_INVALID: ' + '; '.join(issues))
    return mapping


def snapshot():
    resources = []
    for relative in ('services/orchestrator/app/prompts/roles', 'services/orchestrator/app/translation/prompts'):
        directory = REPO / relative
        _reject_reparse(directory)
        files = sorted(path for path in directory.rglob('*') if path.is_file() and path.suffix in ('.md', '.txt'))
        if not files:
            raise ValueError('ROLE_RESOURCES_MISSING')
        for path in files:
            _reject_reparse(path)
            resources.append(dict(path=path.relative_to(REPO).as_posix(), sha256=digest(path)))
    return dict(build_id=source_build_id(), qa_source_id=verification_source_id(), mapping_sha256=digest(MAP_PATH),
        spec_sha256=digest(SPEC_FILE), role_assets=resources,
        role_assets_sha256=hashlib.sha256(json.dumps(resources, sort_keys=True).encode()).hexdigest())


def read_regression(directory, selected, source):
    """Validate the child seal and parse only files in this invocation's new root."""
    issues, report, observations = [], {}, {}
    try:
        manifest = json.loads((directory / 'evidence-manifest.json').read_text(encoding='utf-8'))
        integrity = validate_manifest(directory, manifest)
        if not integrity['valid']:
            issues.append('REGRESSION_MANIFEST_INVALID')
        actual = {path.relative_to(directory).as_posix() for path in directory.rglob('*')
                  if path.is_file() and path != directory / 'evidence-manifest.json'}
        if actual != {entry['path'] for entry in manifest['files']}:
            issues.append('REGRESSION_MANIFEST_INCOMPLETE')
        report = json.loads((directory / 'verification.json').read_text(encoding='utf-8'))
        if not isinstance(report, dict):
            raise ValueError('REGRESSION_REPORT_INVALID')
        for name in ('source-before.json', 'source-after.json'):
            recorded = json.loads((directory / name).read_text(encoding='utf-8'))
            if recorded != report['source_before' if 'before' in name else 'source_after']:
                issues.append('REGRESSION_SOURCE_RECORD_CHANGED')
            if any(recorded.get(key) != source.get(key) for key in ('build_id', 'qa_source_id')):
                issues.append('REGRESSION_SOURCE_MISMATCH')
        if report.get('source_unchanged') is not True or report['source_before'] != report['source_after']:
            issues.append('REGRESSION_SOURCE_CHANGED')
        if report.get('mode') != ('local_regression' if selected else 'mapping_only'):
            issues.append('REGRESSION_MODE_MISMATCH')
        expected = {'contracts'} if selected else set()
        if 'pytest' in selected: expected.add('python')
        if 'vitest' in selected: expected.update(('desktop-typecheck', 'desktop-unit', 'desktop-build', 'desktop-test-build', 'desktop-e2e'))
        checks = report.get('checks')
        if (not isinstance(checks, list) or len(checks) != len(expected)
                or {row['name'] for row in checks} != expected
                or any(type(row['exit_code']) is not int or row['exit_code'] != 0 for row in checks)):
            issues.append('REGRESSION_COMMANDS_INCOMPLETE_OR_FAILED')
        if selected and report.get('all_executed_checks_passed') is not True:
            issues.append('REGRESSION_CHECKS_NOT_PASSED')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        issues.append('REGRESSION_EVIDENCE_INVALID:' + type(error).__name__)
    parsers = {'pytest': (regression.parse_pytest, 'python.xml'),
        'vitest': (regression.parse_vitest, 'desktop-unit-report.json'),
        'playwright': (regression.parse_playwright, 'desktop-e2e-report.json')}
    for runner in sorted(selected):
        parse, name = parsers[runner]
        observations[runner] = parse(directory / name)
    return report, observations, issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', action='store_true', help='Run the complete default local Python regression')
    parser.add_argument('--desktop', action='store_true', help='Run typechecks, desktop unit tests, builds and Electron')
    parser.add_argument('--output', type=Path, help='A fresh directory inside this repository')
    args = parser.parse_args(argv)
    mapping = load_mapping()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
    output = regression.reserve_output(args.output or REPO / 'docs/acceptance/part-five' / run_id, repo=REPO)
    before = snapshot()
    write_json(output / 'source-before.json', before)
    (output / 'work-orders.json').write_bytes(MAP_PATH.read_bytes())
    (output / 'work-orders-and-prompts.md').write_bytes(SPEC_FILE.read_bytes())
    selected, flags = set(), []
    if args.python: selected.add('pytest'); flags.append('--python')
    if args.desktop: selected.update(('vitest', 'playwright')); flags.append('--desktop')
    child_directory = output / 'regression'
    try:
        child_exit = regression.main([*flags, '--output', str(child_directory)])
    except (OSError, ValueError, SystemExit) as error:
        child_exit = 2
        write_json(output / 'regression-error.json', dict(error_type=type(error).__name__))
    child, observations, issues = read_regression(child_directory, selected, before)
    if type(child_exit) is not int or child_exit != 0:
        issues.append('REGRESSION_EXIT_FAILED')
    after = snapshot()
    write_json(output / 'source-after.json', after)
    unchanged = before == after
    coverage = build_coverage(mapping, observations, selected)
    checked = bool(selected) and not issues and unchanged and all(not value['issues'] for value in observations.values())
    verified = checked and selected == regression.RUNNERS and all(row['local_status'] == 'passed' for row in coverage)
    for runner, observation in observations.items():
        write_json(output / (runner + '-observations.json'), observation)
    report = dict(schema_version='1.0', run_id=run_id, mode='local_regression' if selected else 'mapping_only',
        mapping_valid=True, coverage_scope=mapping['coverage_scope'], source_before=before, source_after=after,
        source_unchanged=unchanged, provider_boundary='fake', real_model_calls=0,
        regression=dict(path='regression', exit_code=child_exit, issues=issues, manifest_verified=not any('MANIFEST' in item or 'EVIDENCE_INVALID' in item for item in issues)),
        checks=child.get('checks', []), counts={runner: value['counts'] for runner, value in observations.items()},
        report_issues={runner: value['issues'] for runner, value in observations.items()}, coverage=coverage,
        all_executed_checks_passed=checked, phase_five_local_verified=verified,
        full_product_accepted=False, functional_release=False, real_provider_accepted=False,
        manual_acceptance=False, optimization_goal_met=False,
        evidence_manifest_scope='This wrapper and unchanged nested regression command/report evidence. '
            'The child records raw pytest artifacts separately outside its sealed manifest; this is not a complete workflow artifact archive.',
        note='Only exact tests from this newly invoked regression count. Mapping-only and partial lanes cannot complete stage five. '
            'Local verification does not grant real-provider, human, release or optimization acceptance.')
    write_json(output / 'verification.json', report)
    summary = ['# 阶段五本地协议验证', '', f"运行模式：{report['mode']}。",
        f"所选本地检查通过：{sum(row['local_status'] == 'passed' for row in coverage)}/{len(coverage)}。",
        f"阶段五本地验证：{str(verified).lower()}；源码保持一致：{str(unchanged).lower()}。", '',
        '真实提供方、人工、完整产品、正式发布和优化目标均保持未验收。',
        '本批仅采用新建 regression 目录中的实际报告；仅检查映射不代表执行或完成。', '']
    (output / 'summary.md').write_text('\n'.join(summary), encoding='utf-8')
    files = [path for path in output.rglob('*') if path.is_file()]
    manifest = create_manifest(output, files, build_id=before['build_id'], run_id=run_id)
    write_json(output / 'evidence-manifest.json', manifest)
    sealed = validate_manifest(output, manifest)['valid']
    print(json.dumps(dict(output=output.relative_to(REPO).as_posix(), mode=report['mode'],
        phase_five_local_verified=verified, source_unchanged=unchanged, evidence_manifest_valid=sealed)), flush=True)
    return 0 if sealed and unchanged and not issues and (not selected or verified) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
