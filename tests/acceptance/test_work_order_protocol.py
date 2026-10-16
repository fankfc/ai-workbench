"""Stage-five coverage consumes a fresh child run and seals its final evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'scripts/phase_five_verify.py'


def test_phase_five_current_run_entry_exists():
    assert SCRIPT.is_file(), 'Stage-five has no current-run verification entry'


@pytest.fixture
def verifier():
    assert SCRIPT.is_file(), 'Stage-five has no current-run verification entry'
    spec = importlib.util.spec_from_file_location('phase_five_verify', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reviewed_map_covers_exactly_ten_manual_sections(verifier):
    mapping = verifier.load_mapping()
    assert [row['id'] for row in mapping['items']] == [f'SEC{i:02d}' for i in range(1, 11)]
    assert mapping['spec_path'].endswith('/05-work-orders-and-prompts.md')
    assert all(row['tests'] and row['external_requirements'] for row in mapping['items'])
    assert verifier.validate_mapping(mapping) == []


@pytest.mark.parametrize('damage', ['missing_section', 'duplicate_section', 'empty_tests', 'duplicate_test',
    'invented_test', 'outside_test', 'invented_parameter', 'unknown_field', 'no_limit', 'changed_spec'])
def test_invalid_or_invented_protocol_map_fails_closed(verifier, damage):
    value = copy.deepcopy(verifier.load_mapping())
    row = value['items'][0]
    if damage == 'missing_section': value['items'].pop()
    elif damage == 'duplicate_section': value['items'].append(copy.deepcopy(row))
    elif damage == 'empty_tests': row['tests'] = []
    elif damage == 'duplicate_test': row['tests'].append(copy.deepcopy(row['tests'][0]))
    elif damage == 'invented_test': row['tests'][0]['id'] = 'tests/contracts/test_work_orders.py::test_invented'
    elif damage == 'outside_test': row['tests'][0]['id'] = '../escape.py::test_anything'
    elif damage == 'invented_parameter': row['tests'][0]['id'] += '[invented]'
    elif damage == 'unknown_field': row['local_status'] = 'passed'
    elif damage == 'no_limit': row['external_requirements'] = []
    else: value['spec_sha256'] = '0' * 64
    assert verifier.validate_mapping(value)


def test_valid_json_edit_requires_mapping_reapproval(verifier, tmp_path):
    value = verifier.load_mapping()
    value['items'][0]['title'] += ' unsupported claim'
    path = tmp_path / 'changed.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='MAPPING_DIGEST_UNREVIEWED'):
        verifier.load_mapping(path)


@pytest.mark.parametrize('status', ['missing', 'skipped', 'failed', 'duplicate'])
def test_protocol_coverage_never_accepts_missing_skipped_failed_or_duplicate(verifier, status):
    mapping = verifier.load_mapping()
    observations = {}
    for section in mapping['items']:
        for test in section['tests']:
            observations.setdefault(test['runner'], {'tests': {}, 'issues': [], 'counts': {}})['tests'][test['id']] = ['passed']
    target = mapping['items'][0]['tests'][0]
    cases = observations[target['runner']]['tests']
    if status == 'missing': del cases[target['id']]
    else: cases[target['id']] = ['passed', 'passed'] if status == 'duplicate' else [status]
    coverage = verifier.build_coverage(mapping, observations, set(observations))
    assert coverage[0]['local_status'] != 'passed'
    assert all(row['full_step_accepted'] is False for row in coverage)


def test_role_resource_bytes_are_part_of_source_snapshot(verifier):
    snapshot = verifier.snapshot()
    resources = snapshot['role_assets']
    assert len(resources) >= 10
    assert any(item['path'].endswith('/a_planner.v1.md') for item in resources)
    assert any(item['path'].endswith('/semantic_checker.txt') for item in resources)
    assert all(verifier.digest(REPO / item['path']) == item['sha256'] for item in resources)
    assert len(snapshot['role_assets_sha256']) == 64


def write_junit(path, ids):
    root = ET.Element('testsuite', tests=str(len(ids)), failures='0', errors='0', skipped='0')
    for identity in ids:
        file, name = identity.split('::')
        ET.SubElement(root, 'testcase', classname=file[:-3].replace('/', '.'), name=name)
    ET.ElementTree(root).write(path, encoding='unicode')


def child_run(verifier, monkeypatch, tmp_path, damage=None):
    """Supply bounded actual report files; never run a regression within its tests."""
    mapping = verifier.load_mapping()
    snapshot = dict(build_id='fixture-build', qa_source_id='fixture-qa', mapping_sha256='fixture-map',
        spec_sha256='fixture-spec', role_assets_sha256='fixture-roles', role_assets=[])
    monkeypatch.setattr(verifier, 'REPO', tmp_path)
    monkeypatch.setattr(verifier, 'snapshot', lambda: copy.deepcopy(snapshot))
    calls = []

    def run(argv):
        calls.append(argv)
        directory = Path(argv[argv.index('--output') + 1])
        directory.mkdir()
        selected = set()
        if '--python' in argv: selected.add('pytest')
        if '--desktop' in argv: selected.update(('vitest', 'playwright'))
        names = ['contracts'] if selected else []
        if 'pytest' in selected:
            names.append('python')
            ids = sorted({test['id'] for row in mapping['items'] for test in row['tests'] if test['runner'] == 'pytest'})
            write_junit(directory / 'python.xml', ids[1:] if damage == 'missing_test' else ids)
        if 'vitest' in selected:
            names.extend(['desktop-typecheck', 'desktop-unit', 'desktop-build', 'desktop-test-build', 'desktop-e2e'])
            tests = {}
            for row in mapping['items']:
                for test in row['tests']:
                    if test['runner'] == 'vitest':
                        file, title = test['id'].split('::')
                        tests.setdefault(file, {})[title] = {'fullName': title, 'status': 'passed'}
            assertions = [dict(name=str(REPO / file), assertionResults=list(rows.values())) for file, rows in tests.items()]
            total = sum(len(rows) for rows in tests.values())
            verifier.write_json(directory / 'desktop-unit-report.json', dict(numTotalTests=total, numPassedTests=total,
                numFailedTests=0, numPendingTests=0, success=True, testResults=assertions))
            specs = []
            for identity in sorted({test['id'] for row in mapping['items'] for test in row['tests'] if test['runner'] == 'playwright'}):
                file, title = identity.split('::')
                specs.append(dict(file=file, title=title, tests=[dict(expectedStatus='passed', results=[dict(status='passed', retry=0)])]))
            verifier.write_json(directory / 'desktop-e2e-report.json', dict(suites=[dict(specs=specs)], errors=[],
                stats=dict(expected=len(specs), unexpected=0, flaky=0, skipped=0)))
        source = dict(build_id=snapshot['build_id'], qa_source_id=snapshot['qa_source_id'])
        if damage == 'foreign_source': source['build_id'] = 'historical-build'
        verifier.write_json(directory / 'source-before.json', source)
        verifier.write_json(directory / 'source-after.json', source)
        checks = [dict(name=name, exit_code=0) for name in names]
        report = dict(mode='local_regression' if selected else 'mapping_only', source_before=source, source_after=source,
            source_unchanged=True, checks=checks, all_executed_checks_passed=bool(selected))
        verifier.write_json(directory / 'verification.json', report)
        files = [path for path in directory.rglob('*') if path.is_file()]
        manifest = verifier.create_manifest(directory, files, build_id=source['build_id'], run_id='fixture-child')
        if damage == 'omitted_manifest_file': manifest['files'] = [entry for entry in manifest['files'] if entry['path'] != 'verification.json']
        verifier.write_json(directory / 'evidence-manifest.json', manifest)
        if damage == 'changed_child': (directory / 'verification.json').write_text('{}', encoding='utf-8')
        if damage == 'missing_report': (directory / 'python.xml').unlink()
        return 0

    monkeypatch.setattr(verifier.regression, 'main', run)
    return calls


def test_wrapper_uses_only_its_fresh_child_and_seals_final_summary(verifier, monkeypatch, tmp_path):
    calls = child_run(verifier, monkeypatch, tmp_path)
    output = tmp_path / 'fresh'
    assert verifier.main(['--python', '--desktop', '--output', str(output)]) == 0
    assert len(calls) == 1 and Path(calls[0][calls[0].index('--output') + 1]) == output / 'regression'
    report = json.loads((output / 'verification.json').read_text())
    assert report['phase_five_local_verified'] is True
    assert all(row['local_status'] == 'passed' for row in report['coverage'])
    assert report['real_provider_accepted'] is False and report['full_product_accepted'] is False
    assert report['optimization_goal_met'] is False and report['real_model_calls'] == 0
    manifest = json.loads((output / 'evidence-manifest.json').read_text())
    assert verifier.validate_manifest(output, manifest)['valid'] is True
    assert {'summary.md', 'verification.json', 'regression/evidence-manifest.json'} <= {entry['path'] for entry in manifest['files']}
    child_manifest = json.loads((output / 'regression/evidence-manifest.json').read_text())
    assert verifier.validate_manifest(output / 'regression', child_manifest)['valid'] is True
    with pytest.raises(ValueError, match='OUTPUT_EXISTS'):
        verifier.main(['--output', str(output)])


@pytest.mark.parametrize('damage', ['missing_test', 'foreign_source', 'changed_child', 'missing_report', 'omitted_manifest_file'])
def test_child_zero_exit_never_hides_absent_stale_or_damaged_evidence(verifier, monkeypatch, tmp_path, damage):
    child_run(verifier, monkeypatch, tmp_path, damage)
    output = tmp_path / 'rejected'
    assert verifier.main(['--python', '--desktop', '--output', str(output)]) == 1
    report = json.loads((output / 'verification.json').read_text())
    assert report['phase_five_local_verified'] is False


def test_mapping_only_never_claims_execution_or_local_completion(verifier, monkeypatch, tmp_path):
    calls = child_run(verifier, monkeypatch, tmp_path)
    output = tmp_path / 'mapping'
    assert verifier.main(['--output', str(output)]) == 0
    assert len(calls) == 1 and '--python' not in calls[0] and '--desktop' not in calls[0]
    report = json.loads((output / 'verification.json').read_text())
    assert report['mode'] == 'mapping_only' and report['phase_five_local_verified'] is False
    assert report['checks'] == [] and all(row['local_status'] == 'not_run' for row in report['coverage'])


def test_single_lane_cannot_complete_full_protocol(verifier, monkeypatch, tmp_path):
    child_run(verifier, monkeypatch, tmp_path)
    output = tmp_path / 'python-only'
    assert verifier.main(['--python', '--output', str(output)]) == 1
    assert json.loads((output / 'verification.json').read_text())['phase_five_local_verified'] is False


def test_mapping_only_detects_source_changes_during_child_run(verifier, monkeypatch, tmp_path):
    child_run(verifier, monkeypatch, tmp_path)
    counter = 0
    def changed():
        nonlocal counter
        counter += 1
        return dict(build_id=str(counter), qa_source_id='qa', role_assets=[])
    monkeypatch.setattr(verifier, 'snapshot', changed)
    output = tmp_path / 'changed'
    assert verifier.main(['--output', str(output)]) == 1
    report = json.loads((output / 'verification.json').read_text())
    assert report['source_unchanged'] is False and report['phase_five_local_verified'] is False
