"""Run current local regressions and bind exact observations to the runtime SOP.

No external report import, provider request or acceptance promotion is supported.
The fixed reviewed map is checked against source definitions and current SOP bytes.
"""
import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from uuid import uuid4
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests'))
from support.manifest import create_manifest, source_build_id, verification_source_id, write_json
from app.runtime.workspace import _reject_reparse

MAP_PATH = REPO / 'quality/runtime-sop.json'
SOP_PATH = 'docs/superpowers/plans/2026-10-13-execution/04-runtime-sop.md'
# A changed map needs another source review and an explicit verifier update.
APPROVED_MAP_SHA256 = '47e74ebdc52378b7ebd5e4d059ce5cb8b5baf31aa91b19977999c47548e856f9'
REQUIRED_IDS = tuple(f'S{i:02d}' for i in range(1, 41)) + tuple(f'SEC{i:02d}' for i in range(5, 13))
RUNNERS = frozenset(('pytest', 'vitest', 'playwright'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_mapping(path=MAP_PATH):
    if digest(path) != APPROVED_MAP_SHA256:
        raise ValueError('MAPPING_DIGEST_UNREVIEWED')
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    issues = validate_mapping(value)
    if issues:
        raise ValueError('MAPPING_INVALID: ' + '; '.join(issues))
    return value


def validate_mapping(value, *, repo=REPO):
    """Structural/source checks supplement the reviewed byte digest."""
    issues = []
    top = {'schema_version', 'sop_path', 'sop_sha256', 'coverage_scope', 'items'}
    if not isinstance(value, dict) or set(value) != top:
        return ['MAPPING_FIELDS_INVALID']
    if value.get('schema_version') != '1.0' or value.get('sop_path') != SOP_PATH:
        issues.append('MAPPING_PROTOCOL_INVALID')
    try:
        _reject_reparse(Path(repo) / SOP_PATH)
        if digest(Path(repo) / SOP_PATH) != value.get('sop_sha256'):
            issues.append('SOP_BYTES_CHANGED')
    except (OSError, ValueError):
        issues.append('SOP_UNREADABLE')
    if not isinstance(value.get('coverage_scope'), str) or not value['coverage_scope'].strip():
        issues.append('COVERAGE_SCOPE_MISSING')
    rows = value.get('items')
    if not isinstance(rows, list):
        return issues + ['MAPPING_ITEMS_INVALID']
    if [row.get('id') if isinstance(row, dict) else None for row in rows] != list(REQUIRED_IDS):
        issues.append('MAPPING_IDS_MISSING_DUPLICATE_OR_UNORDERED')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'title', 'tests', 'external_requirements'}:
            issues.append('MAPPING_ITEM_FIELDS_INVALID')
            continue
        item = str(row['id'])
        if not isinstance(row['title'], str) or not row['title'].strip():
            issues.append(item + ':TITLE_MISSING')
        if (not isinstance(row['external_requirements'], list) or not row['external_requirements']
                or any(not isinstance(x, str) or not x.strip() for x in row['external_requirements'])):
            issues.append(item + ':EXTERNAL_REQUIREMENTS_MISSING')
        if not isinstance(row['tests'], list) or not row['tests']:
            issues.append(item + ':TESTS_MISSING')
            continue
        seen = set()
        for reference in row['tests']:
            try:
                if not isinstance(reference, dict) or set(reference) != {'runner', 'id'}:
                    raise ValueError('TEST_REFERENCE_INVALID')
                runner, identity = reference['runner'], reference['id']
                if runner not in RUNNERS or not isinstance(identity, str) or identity.count('::') != 1:
                    raise ValueError('TEST_ID_INVALID')
                key = (runner, identity)
                if key in seen:
                    raise ValueError('TEST_REFERENCE_DUPLICATE')
                seen.add(key)
                relative, name = identity.split('::')
                path = PurePosixPath(relative)
                prefix, suffix = {'pytest': ('tests/', '.py'), 'vitest': ('tests/desktop/', '.test.ts'),
                                  'playwright': ('tests/e2e/', '.spec.ts')}[runner]
                if (not relative.startswith(prefix) or not relative.endswith(suffix) or '..' in path.parts
                        or path.is_absolute() or '\\' in relative or ':' in relative or not name):
                    raise ValueError('TEST_PATH_OUTSIDE_SOURCE')
                source_path = Path(repo) / relative
                _reject_reparse(source_path)
                if not source_path.resolve().is_relative_to(Path(repo).resolve()):
                    raise ValueError('TEST_PATH_OUTSIDE_SOURCE')
                source = source_path.read_text(encoding='utf-8-sig')
                if runner == 'pytest':
                    # Exact simple parameter IDs are checked against literal decorator values.
                    base = name.split('[', 1)[0]
                    functions = [node for node in ast.parse(source).body
                                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == base]
                    if len(functions) != 1:
                        raise ValueError('EXACT_TEST_DEFINITION_MISSING')
                    decorators = [d for d in functions[0].decorator_list if 'parametrize' in ast.unparse(d)]
                    expected_names = {base}
                    for decorator in decorators:
                        values = ast.literal_eval(decorator.args[1])
                        if len(decorators) != 1 or not all(isinstance(v, (str, int)) for v in values):
                            raise ValueError('UNSUPPORTED_PARAMETER_ID_REQUIRES_REVIEW')
                        expected_names = {base + '[' + str(v) + ']' for v in values}
                    if name not in expected_names:
                        raise ValueError('EXACT_PARAMETER_ID_MISSING')
                else:
                    literals = re.findall(r"\b(?:test|it)\(\s*(['\"])(.*?)\1", source)
                    if not any(name == title or runner == 'vitest' and name.endswith(' ' + title)
                               for _, title in literals):
                        raise ValueError('EXACT_TEST_DEFINITION_MISSING')
            except (OSError, ValueError, TypeError, SyntaxError, KeyError) as error:
                issues.append(item + ':' + str(error))
    return issues


def _observation():
    return {'tests': {}, 'issues': [], 'counts': {}}


def _append(report, identity, status):
    if not isinstance(identity, str) or not identity or status not in {'passed', 'failed', 'skipped', 'invalid'}:
        raise ValueError('TEST_OBSERVATION_INVALID')
    report['tests'].setdefault(identity, []).append(status)


def _finish(report):
    counts = Counter(status for values in report['tests'].values() for status in values)
    report['counts'] = dict(total=sum(counts.values()), **{key: counts[key] for key in ('passed', 'failed', 'skipped', 'invalid')})
    if not counts:
        report['issues'].append('NO_EXECUTED_TESTS')
    if any(len(values) != 1 for values in report['tests'].values()):
        report['issues'].append('DUPLICATE_TEST_ID')
    if any(key != 'passed' and count for key, count in counts.items()):
        report['issues'].append('NONPASS_TEST_RESULT')
    return report


def parse_pytest(path):
    report = _observation()
    try:
        root = ET.parse(path).getroot()
        suites = list(root.iter('testsuite'))
        if root.tag not in {'testsuites', 'testsuite'} or not suites:
            raise ValueError('JUNIT_ROOT_INVALID')
        for suite in suites:
            nodes = suite.findall('testcase')
            # Only leaf suite counters describe the corresponding testcase list.
            if not suite.findall('testsuite'):
                expected = {'tests': len(nodes), 'failures': sum(n.find('failure') is not None for n in nodes),
                            'errors': sum(n.find('error') is not None for n in nodes),
                            'skipped': sum(n.find('skipped') is not None for n in nodes)}
                if any(int(suite.attrib[key]) != count for key, count in expected.items()):
                    report['issues'].append('JUNIT_COUNTS_MISMATCH')
            for node in nodes:
                module = node.attrib['classname']
                name = node.attrib['name']
                if not module.startswith('tests.') or not name.startswith('test_'):
                    raise ValueError('JUNIT_ID_INVALID')
                status = ('failed' if node.find('failure') is not None or node.find('error') is not None else
                          'skipped' if node.find('skipped') is not None else 'passed')
                _append(report, module.replace('.', '/') + '.py::' + name, status)
        report['report_sha256'] = digest(path)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        report['issues'].append('PYTEST_REPORT_INVALID:' + type(error).__name__)
    return _finish(report)


def _relative_source(name, prefix):
    value = str(name).replace('\\', '/')
    path = Path(value)
    if path.is_absolute():
        value = path.resolve().relative_to(REPO.resolve()).as_posix()
    elif not value.startswith('tests/'):
        value = prefix + value
    if '..' in PurePosixPath(value).parts or not value.startswith(prefix):
        raise ValueError('REPORT_TEST_PATH_INVALID')
    return value


def _require_counters(data, fields):
    if not isinstance(data, dict) or any(type(data.get(key)) is not int or data[key] < 0 for key in fields):
        raise ValueError('REPORT_COUNTERS_INVALID')


def parse_vitest(path):
    report = _observation()
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        _require_counters(data, ('numTotalTests', 'numPassedTests', 'numFailedTests', 'numPendingTests'))
        for suite in data['testResults']:
            file = _relative_source(suite['name'], 'tests/')
            for assertion in suite['assertionResults']:
                status = assertion['status']
                _append(report, file + '::' + assertion['fullName'],
                        'passed' if status == 'passed' else 'skipped' if status in {'pending', 'todo', 'skipped'} else 'failed')
        _finish(report)
        if (data.get('success') is not True or data['numTotalTests'] != report['counts']['total']
                or data['numPassedTests'] != report['counts']['passed']
                or data['numFailedTests'] != report['counts']['failed']
                or data['numPendingTests'] != report['counts']['skipped']):
            report['issues'].append('VITEST_COUNTS_OR_SUCCESS_INVALID')
        report['report_sha256'] = digest(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        report['issues'].append('VITEST_REPORT_INVALID:' + type(error).__name__)
    return report if report['counts'] else _finish(report)


def parse_playwright(path):
    report = _observation()
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        def visit(suites):
            for suite in suites:
                for spec in suite.get('specs', []):
                    file = _relative_source(spec['file'], 'tests/e2e/')
                    for test in spec['tests']:
                        results = test['results']
                        status = 'invalid'
                        if (test['expectedStatus'] == 'passed' and len(results) == 1
                                and type(results[0].get('retry')) is int and results[0]['retry'] == 0):
                            actual = results[0]['status']
                            status = 'passed' if actual == 'passed' else 'skipped' if actual == 'skipped' else 'failed'
                        _append(report, file + '::' + spec['title'], status)
                visit(suite.get('suites', []))
        visit(data['suites'])
        _finish(report)
        stats = data['stats']
        _require_counters(stats, ('expected', 'unexpected', 'flaky', 'skipped'))
        if (data.get('errors') or sum(stats[key] for key in ('expected', 'unexpected', 'flaky', 'skipped')) != report['counts']['total']
                or stats['expected'] != report['counts']['passed'] or stats['unexpected'] or stats['flaky'] or stats['skipped']):
            report['issues'].append('PLAYWRIGHT_COUNTS_OR_ERRORS_INVALID')
        report['report_sha256'] = digest(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        report['issues'].append('PLAYWRIGHT_REPORT_INVALID:' + type(error).__name__)
    return report if report['counts'] else _finish(report)


def resolve_test(reference, observations, selected):
    runner, identity = reference['runner'], reference['id']
    if runner not in selected:
        return {**reference, 'status': 'not_run'}
    report = observations.get(runner)
    if report is None:
        status = 'missing'
    elif report['issues']:
        status = 'invalid_report'
    else:
        values = report['tests'].get(identity, [])
        status = 'missing' if not values else 'duplicate' if len(values) != 1 else values[0]
    return {**reference, 'status': status}


def build_coverage(mapping, observations, selected):
    rows = []
    for item in mapping['items']:
        tests = [resolve_test(test, observations, selected) for test in item['tests']]
        statuses = {test['status'] for test in tests}
        status = ('passed' if statuses == {'passed'} else 'not_run' if statuses == {'not_run'} else
                  'partial' if statuses <= {'passed', 'not_run'} else 'failed')
        rows.append(dict(id=item['id'], title=item['title'], local_status=status, tests=tests,
                         local_scope='selected_local_mechanical_checks', full_step_accepted=False,
                         manual_status='not_verified',
                         external_status='not_verified', optimization_status='not_verified',
                         external_requirements=item['external_requirements']))
    return rows


def reserve_output(path, *, repo=REPO):
    root, output = Path(repo).resolve(), Path(path).absolute()
    _reject_reparse(output)
    if not output.resolve().is_relative_to(root) or output.resolve() == root:
        raise ValueError('OUTPUT_OUTSIDE_REPOSITORY')
    if output.exists():
        raise ValueError('OUTPUT_EXISTS_REFUSING_OVERWRITE')
    output.mkdir(parents=True, exist_ok=False)
    return output


def reserve_pytest_temp(*, repo=REPO, short_id=None):
    """Reserve a fresh short root before pytest can perform basetemp cleanup.

    The case fixtures already reserve path budget for task/attempt/proof names;
    nesting them below a timestamped report folder exceeds Windows MAX_PATH.
    """
    short_id = uuid4().hex[:8] if short_id is None else short_id
    if not isinstance(short_id, str) or re.fullmatch(r'[0-9a-f]{8}', short_id) is None:
        raise ValueError('PYTEST_TEMP_ID_INVALID')
    root = Path(repo).resolve()
    approved = root / '.omx/qa/p4'
    target = approved / short_id
    _reject_reparse(approved)
    _reject_reparse(target)
    if (not approved.resolve().is_relative_to(root) or target.resolve().parent != approved.resolve()
            or not target.resolve().is_relative_to(root)):
        raise ValueError('PYTEST_TEMP_OUTSIDE_APPROVED_ROOT')
    # Leave at least 195 characters for existing pytest/scenario/task paths.
    if os.name == 'nt' and len(str(target.resolve())) > 64:
        raise ValueError('PYTEST_TEMP_PATH_BUDGET_EXCEEDED')
    return reserve_output(target, repo=root)


def snapshot():
    return dict(build_id=source_build_id(), qa_source_id=verification_source_id(),
                mapping_sha256=digest(MAP_PATH), sop_sha256=digest(REPO / SOP_PATH))


def execute(name, command, output, environment):
    started = datetime.now(timezone.utc).isoformat()
    log = output / (name + '.log')
    error = None
    try:
        with log.open('x', encoding='utf-8') as stream:
            completed = subprocess.run(command, cwd=REPO, env=environment, stdout=stream, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', check=False)
        code = completed.returncode
    except OSError as failure:
        code, error = 127, type(failure).__name__
    record = dict(name=name, command=command, cwd=str(REPO), started_at=started,
                  ended_at=datetime.now(timezone.utc).isoformat(), exit_code=code,
                  log=log.relative_to(REPO).as_posix(), launch_error=error)
    write_json(output / (name + '.json'), record)
    print(json.dumps(dict(name=name, exit_code=code, log=record['log'])), flush=True)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', action='store_true', help='Run the full default local Python regression')
    parser.add_argument('--desktop', action='store_true', help='Run types, Vitest, both builds and actual Electron')
    parser.add_argument('--output', type=Path, help='A new directory inside this repository; existing paths are rejected')
    args = parser.parse_args(argv)
    try:
        mapping = load_mapping()
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
        output = reserve_output(args.output or REPO / 'docs/acceptance/part-four' / run_id)
        raw_pytest_root = reserve_pytest_temp() if args.python else None
    except (OSError, ValueError) as error:
        parser.error(str(error))
    before = snapshot()
    write_json(output / 'source-before.json', before)
    # Save the exact reviewed definitions alongside each run, without modifying history.
    (output / 'runtime-sop.json').write_bytes(MAP_PATH.read_bytes())
    (output / 'runtime-sop.md').write_bytes((REPO / SOP_PATH).read_bytes())
    env = dict(os.environ, PYTHONIOENCODING='utf-8', WORKBENCH_QA_BUILD_ID=before['build_id'],
               PYTEST_ADDOPTS='', CI='1')
    checks, observations, selected = [], {}, set()
    if args.python or args.desktop:
        checks.append(execute('contracts', [sys.executable, 'scripts/check_contracts.py', '--strict'], output, env))
    if args.python:
        selected.add('pytest')
        path = output / 'python.xml'
        _reject_reparse(raw_pytest_root)
        check = execute('python', [sys.executable, '-m', 'pytest', '-q', '-m', 'not real_provider',
                        '--junitxml=' + str(path), '--basetemp=' + str(raw_pytest_root)], output, env)
        checks.append(check)
        observations['pytest'] = parse_pytest(path)
        if check['exit_code'] != 0:
            observations['pytest']['issues'].append('PYTHON_PROCESS_FAILED')
    if args.desktop:
        selected.update(('vitest', 'playwright'))
        node = shutil.which('node') or 'node'
        npm = ['cmd.exe', '/d', '/c', 'npm'] if os.name == 'nt' else ['npm']
        path = output / 'desktop-unit-report.json'
        checks.append(execute('desktop-typecheck', [*npm, 'run', 'typecheck:desktop'], output, env))
        check = execute('desktop-unit', [node, 'node_modules/vitest/vitest.mjs', 'run', 'tests/desktop', 'tests/release',
                                        '--reporter=json', '--outputFile=' + str(path)], output, env)
        checks.append(check)
        observations['vitest'] = parse_vitest(path)
        if check['exit_code'] != 0:
            observations['vitest']['issues'].append('VITEST_PROCESS_FAILED')
        for name, script in [('desktop-build', 'build:desktop'), ('desktop-test-build', 'build:desktop:test')]:
            checks.append(execute(name, [*npm, 'run', script], output, env))
        path = output / 'desktop-e2e-report.json'
        env['PLAYWRIGHT_JSON_OUTPUT_FILE'] = str(path)
        check = execute('desktop-e2e', [node, 'node_modules/@playwright/test/cli.js', 'test', '--reporter=json',
                                       '--output=' + str(output / 'electron-results')], output, env)
        checks.append(check)
        observations['playwright'] = parse_playwright(path)
        if check['exit_code'] != 0:
            observations['playwright']['issues'].append('PLAYWRIGHT_PROCESS_FAILED')
    after = snapshot()
    write_json(output / 'source-after.json', after)
    source_unchanged = before == after
    coverage = build_coverage(mapping, observations, selected)
    mapping_only = not selected
    checks_passed = bool(checks) and all(row['exit_code'] == 0 for row in checks) and source_unchanged
    local_passed = checks_passed and all(row['local_status'] == 'passed' for row in coverage)
    for runner, observation in observations.items():
        write_json(output / (runner + '-observations.json'), observation)
    report = dict(schema_version='1.0', run_id=run_id, mode='mapping_only' if mapping_only else 'local_regression',
        environment=dict(python=sys.version, executable=sys.executable, platform=sys.platform),
        provider_boundary='fake', real_model_calls=0, source_before=before, source_after=after,
        source_unchanged=source_unchanged, checks=checks, counts={key: val['counts'] for key, val in observations.items()},
        report_issues={key: val['issues'] for key, val in observations.items()}, coverage=coverage,
        mapping_valid=True, coverage_scope=mapping['coverage_scope'], all_executed_checks_passed=checks_passed,
        evidence_manifest_scope='Command logs/reports, source/map/SOP snapshots and Electron results. '
            'Raw pytest DB/proof/artifact files in the separate short .omx/qa/p4 directory are retained but excluded from the sealed manifest; '
            'this is not an independently hashed archive of every workflow artifact.',
        raw_pytest_artifacts=dict(path=raw_pytest_root.relative_to(REPO.resolve()).as_posix() if raw_pytest_root else None,
                                  exists=raw_pytest_root.is_dir() if raw_pytest_root else False, included_in_manifest=False),
        local_sop_passed=local_passed, full_sop_accepted=False, functional_release=False,
        real_provider_accepted=False, manual_acceptance=False, optimization_goal_met=False,
        note='Only exact tests executed once without skip/retry in this new run count as local coverage. '
             'Real providers, human reviews and optimization remain unverified. Partial lane selection cannot pass the complete SOP.')
    write_json(output / 'verification.json', report)
    files = [path for path in output.rglob('*') if path.is_file()
             and 'pytest-temp' not in path.relative_to(output).parts]
    manifest = create_manifest(output, files, build_id=before['build_id'], run_id=run_id)
    write_json(output / 'evidence-manifest.json', manifest)
    print(json.dumps(dict(output=output.relative_to(REPO).as_posix(), mode=report['mode'],
                          local_sop_passed=local_passed, full_sop_accepted=False, source_unchanged=source_unchanged)), flush=True)
    return 0 if source_unchanged and (mapping_only or local_passed) else 1


if __name__ == '__main__':
    raise SystemExit(main())
