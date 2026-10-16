import io
import json
import zipfile

from app.usage.ledger import UsageLedger


def test_diagnostics_excludes_body_credentials_and_raw_usage(client):
    cid = client.post('/v1/conversations', json={'title': 'PRIVATE_TITLE_CANARY'}).json()['id']
    submitted = client.post(f'/v1/conversations/{cid}/turns', json={'text': 'PRIVATE_BODY_CANARY', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'req'}).json()
    with client.app.state.database.connect() as connection:
        attempt = connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?', (submitted['task_id'],)).fetchone()[0]
    UsageLedger(client.app.state.database.path).record(task_id=submitted['task_id'], attempt_id=attempt,
        provider_profile_id='fake-gpt', external_request_id='r', event_id='e', provider='gpt',
        raw={'total_tokens': 17, 'secret': 'RAW_SECRET_CANARY'}, source='reported', mode='request_total',
        sequence=1, role='A', function='execution', domain='mixed', status='failed')
    response = client.post('/v1/diagnostics/export')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        text = '\n'.join(archive.read(name).decode() for name in archive.namelist())
    assert all(canary not in text for canary in ('PRIVATE_TITLE_CANARY', 'PRIVATE_BODY_CANARY', 'RAW_SECRET_CANARY', 'qa-local-token'))
    assert 'reported' in text
    assert '17' in text


def test_usage_preserves_unknown_and_includes_failed_requests(client):
    cid = client.post('/v1/conversations', json={'title': '用量'}).json()['id']
    submitted = client.post(f'/v1/conversations/{cid}/turns', json={'text': '任务', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'req'}).json()
    with client.app.state.database.connect() as connection:
        attempt = connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?', (submitted['task_id'],)).fetchone()[0]
    ledger = UsageLedger(client.app.state.database.path)
    for request_id, raw in [('failed', {'total_tokens': 19}), ('unknown', {})]:
        ledger.record(task_id=submitted['task_id'], attempt_id=attempt, provider_profile_id='fake-gpt',
            external_request_id=request_id, event_id=request_id, provider='gpt', raw=raw,
            source='reported' if raw else 'unknown', mode='request_total', sequence=1,
            role='A', function='review', domain='mixed', status='failed')
    response = client.get('/v1/usage')
    assert response.status_code == 200
    result = response.json()
    assert len(result['items']) == 2
    assert result['summary']['total_tokens'] is None
    assert result['summary']['known_lower_bound'] == 19
    assert result['summary']['a_tokens'] is None
    assert result['summary']['tokens_per_delivery'] is None
    assert result['summary']['savings'] is None
    assert 'events' not in response.text and 'raw' not in response.text
    assert len(client.get('/v1/usage', params={'limit': 1}).json()['items']) == 1
    assert client.get('/v1/usage', params={'role': 'B'}).json()['items'] == []


def test_usage_keeps_provider_cache_components_and_missing_values(client):
    cid = client.post('/v1/conversations', json={'title': '口径'}).json()['id']
    task = client.post(f'/v1/conversations/{cid}/turns', json={'text': '任务', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'components'}).json()['task_id']
    with client.app.state.database.connect() as connection:
        attempt = connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?', (task,)).fetchone()[0]
    ledger = UsageLedger(client.app.state.database.path)
    for identity, provider, raw in [
        ('subset', 'gpt', {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15, 'input_tokens_details': {'cached_tokens': 4}}),
        ('exclusive', 'glm', {'wire_protocol': 'anthropic', 'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 4, 'cache_creation_input_tokens': 2}),
        ('missing', 'gpt', {'total_tokens': 3}),
    ]:
        ledger.record(task_id=task, attempt_id=attempt, provider_profile_id='fake-gpt', external_request_id=identity,
            event_id=identity, provider=provider, raw=raw, source='reported', mode='request_total', sequence=1,
            role='B', function='translation', domain='mixed', status='completed')
    items = {item['external_request_id']: item for item in client.get('/v1/usage').json()['items']}
    assert items['subset']['components']['cached_tokens'] == 4
    assert items['subset']['component_semantics'] == 'cache_is_input_subset'
    assert items['subset']['total_tokens'] == 15
    assert items['exclusive']['components']['cache_creation_input_tokens'] == 2
    assert items['exclusive']['component_semantics'] == 'cache_is_additional_input'
    assert items['exclusive']['total_tokens'] == 21
    assert items['missing']['components']['input_tokens'] is None
    assert items['missing']['components']['output_tokens'] is None


def test_usage_date_boundaries_compare_instants_and_include_final_millisecond(client):
    cid=client.post('/v1/conversations',json={'title':'Date boundaries'}).json()['id']
    task=client.post(f'/v1/conversations/{cid}/turns',json={'text':'Task','provider_profile_id':'fake-gpt','client_request_id':'dates'}).json()['task_id']
    with client.app.state.database.connect() as connection:
        attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
    ledger=UsageLedger(client.app.state.database.path)
    for request_id, timestamp in [('start','2026-10-13T16:00:00.000Z'),
                                  ('last','2026-10-14T15:59:59.999Z'),
                                  ('next','2026-10-14T16:00:00.000Z')]:
        ledger.record(task_id=task,attempt_id=attempt,provider_profile_id='fake-gpt',external_request_id=request_id,
                      event_id=request_id,provider='gpt',raw={'total_tokens':1},source='reported',
                      mode='request_total',sequence=1,role='A',function='review',domain='mixed',status='completed')
        with client.app.state.database.connect() as connection:
            connection.execute('UPDATE usage_entries SET created_at=? WHERE external_request_id=?',(timestamp,request_id))
    result=client.get('/v1/usage',params={'date_from':'2026-10-14T00:00:00+08:00',
                                        'date_to':'2026-10-14T23:59:59.999+08:00'})
    assert result.status_code==200
    assert {item['external_request_id'] for item in result.json()['items']}=={'start','last'}
    assert client.get('/v1/usage',params={'date_from':'invalid'}).status_code==422
    assert client.get('/v1/usage',params={'date_from':'2026-10-15T00:00:00Z','date_to':'2026-10-14T00:00:00Z'}).status_code==422
