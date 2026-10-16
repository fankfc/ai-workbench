"""Re-run phase-three and earlier regressions with actual logs and source IDs."""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests'))
from support.manifest import source_build_id, verification_source_id, write_json


def execute(name, command, output, environment):
    started = datetime.now(timezone.utc)
    log = output / (name + '.log')
    with log.open('w', encoding='utf-8') as stream:
        completed = subprocess.run(command, cwd=REPO, env=environment, stdout=stream, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', check=False)
    record = dict(name=name, command=command, started_at=started.isoformat(),
        ended_at=datetime.now(timezone.utc).isoformat(), exit_code=completed.returncode,
        log=log.relative_to(REPO).as_posix())
    write_json(output / (name + '.json'), record)
    print(json.dumps(record), flush=True)
    return record


def extract_observations(report):
    def walk(node):
        if isinstance(node, list):
            for item in node:
                yield from walk(item)
        elif isinstance(node, dict):
            if 'status' in node and 'attachments' in node and node['status'] == 'passed':
                for item in node['attachments']:
                    if item.get('name') in {'gui-observations', 'renderer-latency', 'desktop-lifecycle'}:
                        data = base64.b64decode(item['body']) if 'body' in item else Path(item['path']).read_bytes()
                        yield item['name'], json.loads(data.decode('utf-8'))
            for key in ('suites', 'specs', 'tests', 'results'):
                yield from walk(node.get(key, []))
    for name, observation in walk(report):
        card = 'D049' if name == 'gui-observations' else 'D050'
        write_json(REPO / 'artifacts/qa' / card / (name + '.json'), observation)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', action='store_true')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--output', type=Path, default=REPO / 'docs/acceptance/part-three')
    args = parser.parse_args()
    output = args.output.absolute()
    if not output.resolve().is_relative_to(REPO):
        parser.error('output must stay in repository')
    output.mkdir(parents=True, exist_ok=True)
    before = source_build_id()
    qa_before = verification_source_id()
    write_json(output / 'source-before.json', dict(build_id=before, qa_source_id=qa_before, time=datetime.now(timezone.utc).isoformat()))
    env = dict(os.environ, PYTHONIOENCODING='utf-8', WORKBENCH_QA_BUILD_ID=before)
    records = []
    records.append(execute('contracts', [sys.executable, 'scripts/check_contracts.py', '--strict'], output, env))
    if args.python:
        junit = output / 'python.xml'
        records.append(execute('python', [sys.executable, '-m', 'pytest', '-q', '-x', '--junitxml=' + str(junit)], output, env))
        if junit.is_file():
            nodes = ET.parse(junit).getroot().findall('testsuite')
            write_json(output / 'python-counts.json', {key: sum(int(node.attrib.get(key, 0)) for node in nodes) for key in ('tests', 'failures', 'errors', 'skipped')})
    if args.desktop:
        for name, script in [('desktop-typecheck', 'typecheck:desktop'), ('desktop-unit', 'test:desktop'),
                             ('desktop-build', 'build:desktop'), ('desktop-test-build', 'build:desktop:test')]:
            command = (['node', 'node_modules/vitest/vitest.mjs', 'run', 'tests/desktop', 'tests/release']
                       if name == 'desktop-unit' else ['cmd.exe', '/d', '/c', 'npm', 'run', script])
            records.append(execute(name, command, output, env))
        report = output / 'desktop-e2e-report.json'
        env['PLAYWRIGHT_JSON_OUTPUT_FILE'] = str(report)
        records.append(execute('desktop-e2e', ['node', 'node_modules/@playwright/test/cli.js', 'test', '--reporter=json'], output, env))
        if report.is_file():
            data = json.loads(report.read_text(encoding='utf-8'))
            write_json(output / 'desktop-e2e-counts.json', data.get('stats', {}))
            extract_observations(data)
    after = source_build_id()
    qa_after = verification_source_id()
    write_json(output / 'source-after.json', dict(build_id=after, qa_source_id=qa_after, time=datetime.now(timezone.utc).isoformat()))
    result = dict(build_id=before, qa_source_id=qa_before, source_unchanged=before == after and qa_before == qa_after, checks=records,
        all_executed_checks_passed=all(row['exit_code'] == 0 for row in records) and before == after and qa_before == qa_after,
        real_model_calls=0, functional_release=False, optimization_goal_met=False,
        note='Local mechanical regressions only; external and manual gates remain separate.')
    write_json(output / 'verification.json', result)
    print(json.dumps(result))
    return 0 if result['all_executed_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
