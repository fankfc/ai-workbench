"""The SOP verifier must fail closed on absent, skipped or invented evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'scripts/phase_four_verify.py'


def test_current_run_verification_entry_exists():
    assert SCRIPT.is_file(), 'SOP has no current-run verification entry'


@pytest.fixture
def verifier():
    assert SCRIPT.is_file(), 'The phase-four current-run verification entry is missing'
    spec = importlib.util.spec_from_file_location('phase_four_verify', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def junit(path, rows):
    import xml.etree.ElementTree as ET
    suite = ET.Element('testsuite', tests=str(len(rows)), failures=str(sum(s == 'failed' for _, s in rows)),
                       errors='0', skipped=str(sum(s == 'skipped' for _, s in rows)))
    for nodeid, status in rows:
        file, name = nodeid.split('::')
        node = ET.SubElement(suite, 'testcase', classname=file[:-3].replace('/', '.'), name=name)
        if status != 'passed':
            ET.SubElement(node, 'failure' if status == 'failed' else 'skipped')
    ET.ElementTree(suite).write(path, encoding='unicode')


def test_verifier_and_reviewed_mapping_cover_all_forty_steps_and_eight_sections(verifier):
    mapping = verifier.load_mapping()
    assert {row['id'] for row in mapping['items']} == {f'S{i:02d}' for i in range(1, 41)} | {f'SEC{i:02d}' for i in range(5, 13)}
    assert all(row['tests'] and row['external_requirements'] for row in mapping['items'])
    assert len({tuple(row['external_requirements']) for row in mapping['items']}) == 48
    assert verifier.validate_mapping(mapping) == []


@pytest.mark.parametrize('damage', ['missing_item', 'duplicate_item', 'unknown_item', 'empty_tests',
    'duplicate_test', 'invented_test', 'outside_test', 'unknown_field', 'no_external', 'sop_changed'])
def test_bad_or_forged_mapping_cannot_validate(verifier, damage):
    value = copy.deepcopy(verifier.load_mapping())
    row = value['items'][0]
    if damage == 'missing_item': value['items'].pop()
    elif damage == 'duplicate_item': value['items'].append(copy.deepcopy(row))
    elif damage == 'unknown_item': row['id'] = 'S41'
    elif damage == 'empty_tests': row['tests'] = []
    elif damage == 'duplicate_test': row['tests'].append(copy.deepcopy(row['tests'][0]))
    elif damage == 'invented_test': row['tests'][0]['id'] = 'tests/integration/test_conversation_api.py::test_invented_success'
    elif damage == 'outside_test': row['tests'][0]['id'] = '../private.py::test_anything'
    elif damage == 'unknown_field': row['local_status'] = 'passed'
    elif damage == 'no_external': row['external_requirements'] = []
    else: value['sop_sha256'] = '0' * 64
    assert verifier.validate_mapping(value)


def test_mapping_byte_tampering_is_rejected_even_when_json_remains_valid(verifier, tmp_path):
    value = verifier.load_mapping()
    value['items'][0]['title'] += ' invented claim'
    path = tmp_path / 'map.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='MAPPING_DIGEST'):
        verifier.load_mapping(path)


@pytest.mark.parametrize('status', ['missing', 'skipped', 'failed', 'duplicate'])
def test_missing_skipped_failed_or_duplicate_pytest_result_never_passes(verifier, tmp_path, status):
    nodeid = 'tests/integration/test_conversation_api.py::test_idempotent_turn_and_conflicting_key'
    rows = [] if status == 'missing' else [(nodeid, 'passed' if status == 'duplicate' else status)]
    if status == 'duplicate': rows *= 2
    path = tmp_path / 'python.xml'
    junit(path, rows)
    observation = verifier.parse_pytest(path)
    result = verifier.resolve_test({'runner': 'pytest', 'id': nodeid}, {'pytest': observation}, {'pytest'})
    assert result['status'] != 'passed'


def test_exact_current_pytest_nodeid_passes_but_similar_name_does_not(verifier, tmp_path):
    nodeid = 'tests/integration/test_conversation_api.py::test_idempotent_turn_and_conflicting_key'
    path = tmp_path / 'python.xml'
    junit(path, [(nodeid, 'passed')])
    report = verifier.parse_pytest(path)
    assert verifier.resolve_test({'runner': 'pytest', 'id': nodeid}, {'pytest': report}, {'pytest'})['status'] == 'passed'
    assert verifier.resolve_test({'runner': 'pytest', 'id': nodeid + '_extra'}, {'pytest': report}, {'pytest'})['status'] == 'missing'
    assert verifier.resolve_test({'runner': 'pytest', 'id': nodeid}, {'pytest': report}, set())['status'] == 'not_run'


def test_junit_declared_counts_cannot_hide_absent_testcases(verifier, tmp_path):
    path = tmp_path / 'python.xml'
    path.write_text('<testsuite tests="10" failures="0" errors="0" skipped="0"><testcase classname="tests.x" name="test_a"/></testsuite>', encoding='utf-8')
    assert verifier.parse_pytest(path)['issues']


def playwright_report(status='passed', retry=0):
    return {'suites': [{'specs': [{'file': 'host.spec.ts', 'title': 'actual isolated Electron exposes only a business bridge',
        'tests': [{'expectedStatus': 'passed', 'results': [{'status': status, 'retry': retry}]}]}]}],
        'errors': [], 'stats': {'expected': int(status == 'passed'), 'unexpected': int(status != 'passed'), 'flaky': 0, 'skipped': 0}}


@pytest.mark.parametrize('damage', ['retry', 'skip', 'failure', 'duplicate', 'empty', 'global_error'])
def test_playwright_noncurrent_or_incomplete_success_cannot_pass(verifier, tmp_path, damage):
    value = playwright_report()
    spec = value['suites'][0]['specs'][0]
    if damage == 'retry': spec['tests'][0]['results'][0]['retry'] = 1
    elif damage == 'skip': spec['tests'][0]['results'][0]['status'] = 'skipped'
    elif damage == 'failure': spec['tests'][0]['results'][0]['status'] = 'failed'
    elif damage == 'duplicate': spec['tests'].append(copy.deepcopy(spec['tests'][0]))
    elif damage == 'empty': spec['tests'][0]['results'] = []
    else: value['errors'] = [{'message': 'worker failed after tests'}]
    path = tmp_path / 'desktop.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    report = verifier.parse_playwright(path)
    nodeid = 'tests/e2e/host.spec.ts::actual isolated Electron exposes only a business bridge'
    resolved = verifier.resolve_test({'runner': 'playwright', 'id': nodeid}, {'playwright': report}, {'playwright'})
    assert resolved['status'] != 'passed'


def test_vitest_counts_and_duplicate_assertions_are_checked(verifier, tmp_path):
    path = tmp_path / 'vitest.json'
    assertion = {'fullName': 'startup identity fence does not accept old occupied port or wrong process identity', 'status': 'passed'}
    value = {'numTotalTests': 1, 'numPassedTests': 1, 'numFailedTests': 0, 'numPendingTests': 0,
        'success': True, 'testResults': [{'name': str(REPO / 'tests/desktop/backend.test.ts'), 'assertionResults': [assertion]}]}
    path.write_text(json.dumps(value), encoding='utf-8')
    good = verifier.parse_vitest(path)
    assert not good['issues']
    value['testResults'][0]['assertionResults'].append(copy.deepcopy(assertion))
    path.write_text(json.dumps(value), encoding='utf-8')
    assert verifier.parse_vitest(path)['issues']


def test_local_coverage_never_grants_real_manual_or_optimization_acceptance(verifier):
    mapping = verifier.load_mapping()
    observations = {}
    for row in mapping['items']:
        for test in row['tests']:
            observation = observations.setdefault(test['runner'], {'tests': {}, 'issues': [], 'counts': {}})
            observation['tests'][test['id']] = ['passed']
    coverage = verifier.build_coverage(mapping, observations, set(observations))
    assert all(row['local_status'] == 'passed' for row in coverage)
    assert all(row['external_status'] == 'not_verified' for row in coverage)
    assert all(row['optimization_status'] == 'not_verified' for row in coverage)
    assert all(row['manual_status'] == 'not_verified' and row['full_step_accepted'] is False for row in coverage)
    assert all(row['local_scope'] == 'selected_local_mechanical_checks' for row in coverage)


def test_output_is_new_scoped_directory_and_never_reuses_prior_run(verifier, tmp_path):
    output = verifier.reserve_output(tmp_path / 'acceptance/new', repo=tmp_path)
    assert output.is_dir()
    with pytest.raises(ValueError, match='OUTPUT_EXISTS'):
        verifier.reserve_output(output, repo=tmp_path)
    with pytest.raises(ValueError, match='OUTPUT_OUTSIDE'):
        verifier.reserve_output(tmp_path.parent / 'elsewhere', repo=tmp_path)


def test_short_pytest_root_is_scoped_and_never_overwrites_prior_run(verifier):
    import uuid
    short_id = uuid.uuid4().hex[:8]
    root = verifier.reserve_pytest_temp(short_id=short_id)
    assert root.is_absolute() and root == REPO.resolve() / '.omx/qa/p4' / short_id
    assert root.is_dir()
    marker = root / 'existing-proof.json'
    try:
        marker.write_text('preserve', encoding='utf-8')
        with pytest.raises(ValueError, match='OUTPUT_EXISTS'):
            verifier.reserve_pytest_temp(short_id=short_id)
        assert marker.read_text() == 'preserve'
        with pytest.raises(ValueError, match='PYTEST_TEMP_ID'):
            verifier.reserve_pytest_temp(short_id='../escape')
    finally:
        assert root.resolve().is_relative_to(REPO.resolve() / '.omx/qa/p4')
        marker.unlink(missing_ok=True)
        root.rmdir()


def test_short_root_refuses_a_linked_ancestor_before_pytest_can_remove_it(verifier, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    project = tmp_path / 'project'
    project.mkdir()
    junction = project / '.omx'
    if sys.platform == 'win32':
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(outside)],
            capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
    else:
        junction.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises((ValueError, PermissionError)):
            verifier.reserve_pytest_temp(repo=project, short_id='a1234567')
        assert list(outside.iterdir()) == []
    finally:
        if sys.platform == 'win32': junction.rmdir()
        else: junction.unlink()


def test_python_cli_uses_short_absolute_basetemp_and_reports_its_real_location(verifier, monkeypatch):
    import uuid
    import shutil
    output = REPO / 'docs/acceptance/part-four' / ('path-budget-selftest-' + uuid.uuid4().hex)
    commands = []
    def capture(name, command, output, environment):
        commands.append((name, command))
        return {'name': name, 'exit_code': 0}
    monkeypatch.setattr(verifier, 'execute', capture)
    raw_root = None
    try:
        assert verifier.main(['--python', '--output', str(output)]) == 1  # Mocked processes supply no evidence.
        python = next(command for name, command in commands if name == 'python')
        raw_root = Path(next(arg.split('=', 1)[1] for arg in python if arg.startswith('--basetemp=')))
        assert raw_root.is_absolute()
        assert raw_root.parent == REPO.resolve() / '.omx/qa/p4'
        # This representative existing scenario suffix includes pytest's 30-char
        # case directory, isolated service root and durable task/attempt IDs.
        suffix = '/'.join(['t' * 31, 'case-000', 'r' + 'a' * 8, 'workspaces',
                            'task_' + 'a' * 32, 'attempt_' + 'b' * 32, 'evidence', 'c' * 32 + '.json'])
        assert len(str(raw_root / suffix)) < 260
        assert len(str(output / 'pytest-temp' / suffix)) >= 260
        report = json.loads((output / 'verification.json').read_text(encoding='utf-8'))
        assert (REPO / report['raw_pytest_artifacts']['path']).resolve() == raw_root.resolve()
        assert report['raw_pytest_artifacts']['included_in_manifest'] is False
        manifest = json.loads((output / 'evidence-manifest.json').read_text(encoding='utf-8'))
        assert all(not item['path'].startswith('.omx/') for item in manifest['files'])
    finally:
        if raw_root and raw_root.exists() and raw_root.resolve().is_relative_to(REPO.resolve() / '.omx/qa/p4'):
            raw_root.rmdir()
        if output.exists() and output.resolve().is_relative_to(REPO.resolve() / 'docs/acceptance/part-four'):
            shutil.rmtree(output)


def test_missing_or_malformed_report_is_failure_without_traceback_success(verifier, tmp_path):
    for parser in (verifier.parse_pytest, verifier.parse_vitest, verifier.parse_playwright):
        assert parser(tmp_path / 'missing')['issues']
        path = tmp_path / 'bad-report'
        path.write_text('not a report', encoding='utf-8')
        assert parser(path)['issues']


@pytest.mark.parametrize('payload', [None, [], True, {'suites': None}, {'suites': [None]}, {'testResults': [None]},
    {'suites': [{'specs': [None]}]}, {'suites': [], 'stats': []}])
def test_valid_json_with_invalid_report_shape_fails_closed(verifier, tmp_path, payload):
    path = tmp_path / 'bad-shape.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert verifier.parse_vitest(path)['issues']
    assert verifier.parse_playwright(path)['issues']


def test_boolean_report_counters_are_not_real_test_counts(verifier, tmp_path):
    value = playwright_report()
    value['stats']['expected'] = True
    path = tmp_path / 'boolean-count.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    assert verifier.parse_playwright(path)['issues']


def test_mapping_only_still_checks_current_source_not_historical_logs(verifier, tmp_path, monkeypatch):
    import uuid
    output = REPO / 'docs/acceptance/part-four' / ('changed-selftest-' + uuid.uuid4().hex)
    calls = 0
    def changed():
        nonlocal calls
        calls += 1
        return {'build_id': str(calls), 'qa_source_id': 'qa', 'mapping_sha256': 'map', 'sop_sha256': 'sop'}
    monkeypatch.setattr(verifier, 'snapshot', changed)
    try:
        assert verifier.main(['--output', str(output)]) == 1
        report = json.loads((output / 'verification.json').read_text(encoding='utf-8'))
        assert report['source_unchanged'] is False
        assert report['local_sop_passed'] is False
    finally:
        import shutil
        if output.exists(): shutil.rmtree(output)


def test_zero_exit_without_mapped_test_evidence_has_nonzero_cli_result(verifier, monkeypatch):
    import uuid
    output = REPO / 'docs/acceptance/part-four' / ('missing-selftest-' + uuid.uuid4().hex)
    monkeypatch.setattr(verifier, 'execute', lambda name, command, output, environment: {'name': name, 'exit_code': 0})
    try:
        assert verifier.main(['--python', '--output', str(output)]) == 1
        report = json.loads((output / 'verification.json').read_text(encoding='utf-8'))
        assert report['local_sop_passed'] is False
        assert report['report_issues']['pytest']
    finally:
        import shutil
        if output.exists(): shutil.rmtree(output)


def test_no_lane_is_explicit_mapping_only_and_not_completed(verifier, tmp_path):
    # A new directory inside the repository is required by the actual CLI.
    import uuid
    output = REPO / 'docs/acceptance/part-four' / ('mapping-selftest-' + uuid.uuid4().hex)
    result = subprocess.run([sys.executable, str(SCRIPT), '--output', str(output)], cwd=REPO,
        capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
    try:
        assert result.returncode == 0, result.stderr
        report = json.loads((output / 'verification.json').read_text(encoding='utf-8'))
        assert report['mode'] == 'mapping_only'
        assert report['checks'] == []
        assert report['local_sop_passed'] is False
        assert report['full_sop_accepted'] is False
        assert report['real_model_calls'] == 0
        assert all(row['local_status'] == 'not_run' for row in report['coverage'])
    finally:
        import shutil
        if output.exists():
            shutil.rmtree(output)
