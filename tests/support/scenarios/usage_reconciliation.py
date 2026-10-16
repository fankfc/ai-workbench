"""Replay explicit wire fixtures through the existing durable product ledger."""
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from app.api.application import create_app
from app.config import AppSettings
from app.usage.ledger import UsageLedger
from support.manifest import write_json

OPTIONS_SCHEMA = dict(type='object', additionalProperties=False, properties={
    'fault': dict(enum=['missing_usage','cumulative_with_duplicate']), 'fixture': dict(enum=['provider_events'])})
RESULT_SCHEMA = dict(type='object', required=['duplicate_total', 'cumulative_total', 'unknown_total', 'real_usage_verified', 'optimization_eligible'])
REPO = Path(__file__).resolve().parents[3]


def run(root, options):
    data_root = Path(root) / 'ledger-data'
    app = create_app(AppSettings(data_root, 'usage-qa-local-token', 'fake', False))
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer usage-qa-local-token'
        groups = {}
        events = [json.loads(line) for line in (REPO / 'tests/fixtures/usage/provider-events.jsonl').read_text(encoding='utf-8').splitlines()]
        for event in events:
            if event['source_kind'] != 'synthetic':
                raise ValueError('FIXTURE_PROVENANCE_MISSING')
            group = event['group']
            if group not in groups:
                cid = client.post('/v1/conversations', json={'title': group}).json()['id']
                submitted = client.post(f'/v1/conversations/{cid}/turns', json=dict(text='用量核对', provider_profile_id='fake-gpt', client_request_id=uuid4().hex))
                assert submitted.status_code == 202
                task_id = submitted.json()['task_id']
                with closing(app.state.database.connect()) as connection:
                    attempt = connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?', (task_id,)).fetchone()[0]
                groups[group] = (task_id, attempt)
            task_id, attempt = groups[group]
            wire = {k: v for k, v in event.items() if k not in ('group', 'source_kind')}
            wire['provider_profile_id'] = 'fake-gpt'
            wire['external_request_id'] = group + ':' + wire['external_request_id']
            UsageLedger(app.state.database.path).record(task_id=task_id, attempt_id=attempt, **wire)
        summaries = {group: UsageLedger(app.state.database.path).summary(binding[0]) for group, binding in groups.items()}
    result = dict(duplicate_total=summaries['duplicate']['total_tokens'], duplicate_requests=len(summaries['duplicate']['requests']),
        cumulative_total=summaries['cumulative']['total_tokens'], unknown_total=summaries['unknown']['total_tokens'],
        unknown_requests=summaries['unknown']['unknown_requests'], estimated_source=summaries['estimated']['requests'][0]['source'],
        qualified_delivery_cost=summaries['duplicate']['tokens_per_delivery'],
        counted_functions=sorted({r['function'] for r in summaries['all_costs']['requests']}),
        all_costs_total=summaries['all_costs']['total_tokens'],
        a_tokens=summaries['cumulative']['a_tokens'], b_tokens=sum(r['total_tokens'] for r in summaries['all_costs']['requests'] if r['role']=='B'),
        reported_complete=True, duplicate_count=1, source_kind='synthetic', denominator=0,
        real_usage_verified=False, optimization_eligible=False, provider_boundary='fake', real_provider_verified=False,
        limitations=['REAL_PROVIDER_WIRE_EVENTS_MISSING', 'INDEPENDENT_USAGE_RECONCILIATION_MISSING'])
    write_json(Path(root) / 'usage-ledger.json', summaries)
    (Path(root) / 'usage-ledger.jsonl').write_text(''.join(json.dumps(dict(group=group,**record),ensure_ascii=False)+'\n' for group,summary in summaries.items() for record in summary['requests']),encoding='utf-8')
    write_json(Path(root) / 'usage-report.json', result)
    return result
