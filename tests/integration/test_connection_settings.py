import json


def test_settings_never_claims_identity_from_configuration(client):
    response = client.get('/v1/settings')
    assert response.status_code == 200
    connections = response.json()['connections']
    assert all(item['provider_mode'] == 'fake' for item in connections if item['available'])
    assert not any(item['identity_status'] == 'verified' for item in connections)
    assert not any(item['available'] for item in connections)
    assert 'api_token' not in response.text


def test_preferences_are_versioned_and_persistent(client):
    initial = client.get('/v1/settings').json()
    body = {'expected_version': initial['version'], 'preferences': {'theme': 'dark', 'font_size': 22}}
    changed = client.patch('/v1/settings', json=body)
    assert changed.status_code == 200
    assert changed.json()['preferences']['theme'] == 'dark'
    assert client.get('/v1/settings').json()['preferences']['font_size'] == 22
    assert client.patch('/v1/settings', json=body).status_code == 409
    assert client.patch('/v1/settings', json={'expected_version': changed.json()['version'], 'preferences': {'font_size': 23}}).status_code == 422


def test_probe_cannot_promote_unverified_connection(client):
    response = client.post('/v1/settings/connections/fake-gpt/probe')
    assert response.status_code == 200
    assert response.json()['identity_status'] == 'unknown'
    assert response.json()['provider_mode'] == 'fake'
    assert client.post('/v1/settings/connections/missing/probe').status_code == 404


def test_connection_version_is_checked_at_submission(client):
    conversation = client.post('/v1/conversations', json={'title': '版本'}).json()['id']
    body = {'text': '你好', 'provider_profile_id': 'fake-gpt', 'client_request_id': 'x', 'connection_version': 'obsolete'}
    assert client.post(f'/v1/conversations/{conversation}/turns', json=body).status_code == 409
    body['connection_version'] = 'test-only'
    response = client.post(f'/v1/conversations/{conversation}/turns', json=body)
    assert response.status_code == 202
    with client.app.state.database.connect() as connection:
        route = json.loads(connection.execute('SELECT route_snapshot_json FROM turns WHERE id=?', (response.json()['turn_id'],)).fetchone()[0])
    assert route['connection_version'] == 'test-only'


def test_conversation_archive_is_reversible_and_search_is_literal(client):
    first = client.post('/v1/conversations', json={'title': '报告_100%'}).json()['id']
    client.post('/v1/conversations', json={'title': '报告X100x'})
    assert client.patch('/v1/conversations/' + first, json={'title': '报告_100%', 'pinned': True, 'archived': True}).status_code == 200
    assert first not in [x['id'] for x in client.get('/v1/conversations').json()['items']]
    archived = client.get('/v1/conversations', params={'archived': True, 'query': '_100%'}).json()['items']
    assert [x['id'] for x in archived] == [first]
    assert client.patch('/v1/conversations/' + first, json={'archived': False}).status_code == 200
    assert first in [x['id'] for x in client.get('/v1/conversations').json()['items']]


def test_authenticated_handshake_and_checkpoint(client):
    health = client.get('/v1/health')
    assert health.status_code == 200
    assert health.json()['protocol_version'] == '1.0'
    assert health.json()['pid'] > 0
    assert 'token' not in health.text
    assert client.post('/v1/checkpoint').json()['saved'] is True
    assert client.get('/v1/health', headers={'Authorization': 'Bearer invalid'}).status_code == 401
