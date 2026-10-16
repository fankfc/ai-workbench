"""Independent frozen D020 test execution and actual artifact verification."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / 'services/orchestrator/.venv/Scripts/python.exe'
SOURCES = [
    'tests/support/scenario_driver.py', 'tests/support/mixed_pipeline.py',
    'tests/integration/test_backend_vertical.py', 'tests/integration/test_mixed_pipeline.py',
    'services/orchestrator/app/runtime/workflow.py',
    'services/orchestrator/app/runtime/publication.py',
    'services/orchestrator/app/runtime/public_projection.py',
    'services/orchestrator/app/storage/revisions.py',
    'services/orchestrator/app/runtime/dependencies.py',
    'services/orchestrator/app/usage/ledger.py',
]


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def main():
    run_root = ROOT / '.tools' / ('id20-' + uuid.uuid4().hex[:8])
    run_root.mkdir(parents=True)
    output = ROOT / 'docs/acceptance'
    manifest = output / 'remaining-final-d20-evidence.json'
    if manifest.exists():
        raise RuntimeError('PRESERVE_EXISTING_INDEPENDENT_EVIDENCE')
    log_path = output / 'remaining-final-d20-tests.log'
    junit_path = run_root / 'tests.xml'
    command = [str(PYTHON), '-m', 'pytest', 'tests/integration/test_mixed_pipeline.py',
               'tests/integration/test_backend_vertical.py', '-q', '-k',
               'mixed or upstream or budget_after_repair',
               '--basetemp', str(run_root / 'pytest'), '--junitxml', str(junit_path)]
    before = hashes()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', timeout=600)
    log_path.write_text('command=' + json.dumps(command) + '\n' + result.stdout +
                        result.stderr + '\nexit_code=' + str(result.returncode) + '\n', encoding='utf-8')
    after = hashes()
    suites = ET.parse(junit_path).getroot()
    cases = list(suites.iter('testcase'))
    counts = dict(tests=len(cases), failures=sum(c.find('failure') is not None for c in cases),
                  errors=sum(c.find('error') is not None for c in cases),
                  skipped=sum(c.find('skipped') is not None for c in cases))
    sys.path.insert(0, str(ROOT / 'services/orchestrator'))
    from app.storage.blobs import BlobStore, read_artifact
    observations = []
    for source in sorted(run_root.rglob('scenario-result.json')):
        value = json.loads(source.read_text(encoding='utf-8'))
        database_path = Path(value['database_path'])
        with sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True) as connection:
            connection.row_factory = sqlite3.Row
            actual_candidates = connection.execute(
                "SELECT count(*) FROM artifact_revisions WHERE task_id=? AND id LIKE 'candidate-%'",
                (value['task_id'],)).fetchone()[0]
            actual_turns = connection.execute('SELECT count(*) FROM turns').fetchone()[0]
            actual_requests = connection.execute(
                'SELECT count(DISTINCT provider_profile_id || char(0) || external_request_id) '
                "FROM usage_entries WHERE task_id=? AND metric='request'", (value['task_id'],)).fetchone()[0]
            if actual_candidates != value['candidate_count'] or actual_turns != value['turn_count'] or actual_requests != value['request_count']:
                raise AssertionError('SCENARIO_COUNTER_NOT_DATABASE_DERIVED')
            chain = {}
            if value['domain'] == 'mixed':
                graph = value['dependency_graph']['nodes']
                if set(graph) != {'data', 'analysis', 'result', 'figure', 'answer'}:
                    raise AssertionError('MIXED_CHAIN_REQUIRED')
                store = BlobStore(database_path.parent / 'blobs')
                for logical, node in graph.items():
                    row = connection.execute('SELECT * FROM artifact_revisions WHERE id=?', (node['revision_id'],)).fetchone()
                    content = read_artifact(connection, store, node['revision_id'])
                    references = [item['artifact_version_id'] for item in json.loads(row['dependencies_json'])]
                    if set(references) != set(node['dependencies'].values()):
                        raise AssertionError('ACTUAL_DEPENDENCY_BINDING_MISMATCH')
                    chain[logical] = dict(revision_id=row['id'], byte_sha256=hashlib.sha256(content).hexdigest(),
                                          dependencies=references, stale=node['stale'])
                if value['case'] == 'backend_normal':
                    data = read_artifact(connection, store, graph['data']['revision_id'])
                    derived = json.loads(read_artifact(connection, store, graph['result']['revision_id']))
                    svg = ET.fromstring(read_artifact(connection, store, graph['figure']['revision_id']))
                    metadata = json.loads(svg.find('{http://www.w3.org/2000/svg}metadata').text)
                    if data != b'value\n1\n2\n3\n' or derived['sum'] != 6 or derived['source_sha256'] != chain['data']['byte_sha256']:
                        raise AssertionError('MIXED_NUMERIC_SOURCE_REQUIRED')
                    if metadata['result_sha256'] != chain['result']['byte_sha256'] or len(svg.findall('{http://www.w3.org/2000/svg}rect')) != 3:
                        raise AssertionError('MIXED_FIGURE_BINDING_REQUIRED')
                    if any(item['stale'] for item in chain.values()):
                        raise AssertionError('NORMAL_CHAIN_MUST_BE_CURRENT')
                else:
                    if not all(chain[item]['stale'] for item in ('analysis', 'result', 'figure', 'answer')):
                        raise AssertionError('CHANGED_SOURCE_MUST_INVALIDATE_DESCENDANTS')
            if value['provider_boundary'] != 'fake' or value['real_provider_verified'] is not False:
                raise AssertionError('REAL_CAPABILITY_CLAIM_FROM_FIXTURE')
            sse = (database_path.parent / 'public-events.sse').read_text(encoding='utf-8')
            if 'INTERNAL_LATE_CANARY' in sse:
                raise AssertionError('INTERNAL_CANARY_LEAK')
            observations.append(dict(case=value['case'], domain=value['domain'], task_state=value['task_state'],
                                     database_path=str(database_path), candidate_count=actual_candidates,
                                     request_count=actual_requests, model_starts=value['model_starts'],
                                     public_answer_count=value['public_answer_count'], total_tokens=value['total_tokens'],
                                     provider_boundary=value['provider_boundary'], chain=chain))
    payload = dict(generated_at=datetime.now(timezone.utc).isoformat(), command=command,
                   exit_code=result.returncode, source_hashes_before=before, source_hashes_after=after,
                   source_unchanged=before == after, junit_counts=counts, junit_path=str(junit_path),
                   scope='Independent local fake-provider integration and actual read-only SQLite/blob inspection',
                   real_handoff_complete=False, observed_scenarios=observations)
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if result.returncode or before != after or counts['failures'] or counts['errors'] or not observations:
        raise AssertionError('FROZEN_INDEPENDENT_VERIFICATION_FAILED')
    print(json.dumps(dict(exit_code=result.returncode, source_unchanged=before == after,
                          junit=counts, actual_scenarios=len(observations), evidence=str(manifest))))


if __name__ == '__main__':
    main()
