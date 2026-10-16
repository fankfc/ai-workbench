import hashlib
import json
from contextlib import closing
from dataclasses import asdict
from uuid import uuid4

import pytest

from app.contracts.providers import AgentRequest, ProviderIdentity
from app.runtime.outbox import enqueue_event
from app.storage.database import transaction


@pytest.fixture
def document_task(client, request):
    family = getattr(request, 'param', 'gpt')
    profile = 'fake-' + family
    with closing(client.app.state.database.connect()) as c:
        c.execute("UPDATE provider_profiles SET identity_status='verified',identity_source='fixture-response' WHERE id='fake-gpt'")
        if family == 'claude':
            c.execute("INSERT OR IGNORE INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,identity_source,connection_version) VALUES ('fake-claude','fake','fixture-claude','claude','fake-claude','verified','fixture-response','test-only')")
    cid = client.post('/v1/conversations', json={'title': 'Report'}).json()['id']
    task = client.post(f'/v1/conversations/{cid}/turns', json={
        'text': 'Deliver the report', 'provider_profile_id': profile, 'client_request_id': 'documents'
    }).json()['task_id']
    with closing(client.app.state.database.connect()) as c:
        row = dict(c.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone())
    return dict(client=client, cid=cid, task=task, attempt=row['attempt_id'],
        turn=row['turn_id'], route=json.loads(row['route_snapshot_json']))


def record_a_response(ctx, text, *, role='A', completed=True, manifest=None, chunks=None):
    """Only replace external model output; persist actual request/event products."""
    client, task, attempt = ctx['client'], ctx['task'], ctx['attempt']
    route = ctx['route']
    identity = ProviderIdentity(route['adapter_id'], route['model_id'], route['model_family'], route['provider_id'])
    request = AgentRequest(task, attempt, role, identity, 'a/prompt.json', 'a', '1.0')
    sid = 'step-' + uuid4().hex
    parts = chunks if chunks is not None else [text]
    events = []
    for index, part in enumerate(parts, 1):
        events.append({'provider_sequence': index, 'kind': 'model.delta', 'payload': {'text': part}})
    if completed:
        payload = {'text': text, 'finish_reason': 'stop'}
        if manifest is not None:
            payload['document_manifest'] = manifest
        events.append({'provider_sequence': len(events)+1, 'kind': 'model.completed', 'payload': payload})
    with closing(client.app.state.database.connect()) as c, transaction(c):
        c.execute("INSERT INTO steps(id,task_id,attempt_id,step_key,role,state,contract_version,provider_profile_id,external_request_id,request_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, task, attempt, sid, role, 'COMPLETED' if completed else 'FAILED', '1.0', route['provider_id'], sid, json.dumps(asdict(request))))
        for event in events:
            enqueue_event(c, task, attempt, 'workflow.provider_event', {'step_id': sid, **event},
                deduplication_key=f'{sid}:{event["provider_sequence"]}')
    return sid


def capture(ctx, text, **kwargs):
    from app.documents.canonical import CanonicalCapture
    logical_id=kwargs.pop('logical_id','report')
    sid = record_a_response(ctx, text, **kwargs)
    return CanonicalCapture(ctx['client'].app.state.database.path).capture(
        ctx['task'], ctx['attempt'], sid, language='en',logical_id=logical_id)
