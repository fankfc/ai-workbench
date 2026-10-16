import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.config import AppSettings

def create(client):
    value = client.post('/v1/conversations', json={'title': '测试会话'})
    assert value.status_code == 201
    return value.json()['id']

def submit(client, conversation, key='request', text='检查样本'):
    return client.post(f'/v1/conversations/{conversation}/turns', json={'text': text, 'provider_profile_id': 'fake-gpt', 'client_request_id': key})

def test_create_list_submit_history_and_public_task(client):
    conversation = create(client)
    assert client.get('/v1/conversations').json()['items'][0]['id'] == conversation
    turn = submit(client, conversation)
    assert turn.status_code == 202
    task = client.get('/v1/tasks/' + turn.json()['task_id']).json()
    assert task['status'] == 'pending'
    assert task['cancel_requested'] is False
    messages = client.get(f'/v1/conversations/{conversation}/messages').json()['items']
    assert len(messages) == 1 and messages[0]['text'] == '检查样本'
    assert 'route_snapshot' not in json.dumps(task)

def test_idempotent_turn_and_conflicting_key(client):
    conversation = create(client)
    first = submit(client, conversation)
    second = submit(client, conversation)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert submit(client, conversation, text='不同请求').status_code == 409

def test_concurrent_idempotency(client):
    conversation = create(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(client, conversation), range(8)))
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()['task_id'] for r in responses}) == 1

@pytest.mark.parametrize('token', ['', 'Bearer wrong', 'qa-local-token'])
def test_wrong_auth_is_rejected(client, token):
    client.headers['Authorization'] = token
    assert client.get('/v1/conversations').status_code == 401
    assert client.get('/openapi.json').status_code == 401

def test_host_and_origin_rejected(client):
    assert client.get('/v1/conversations', headers={'Host': 'evil.example'}).status_code == 403
    assert client.get('/v1/conversations', headers={'Origin': 'https://evil.example'}).status_code == 403

def test_unknown_resources_and_no_arbitrary_paths(client):
    assert client.get('/v1/conversations/missing/messages').status_code == 404
    assert submit(client, 'missing').status_code == 404
    assert client.get('/v1/tasks/missing').status_code == 404
    conversation = create(client)
    assert client.post(f'/v1/conversations/{conversation}/turns', json={'text':'x','provider_profile_id':'fake-gpt','client_request_id':'x','workspace':'C:/','visibility':'internal'}).status_code == 422
    assert client.get(f'/v1/conversations/{conversation}/messages?visibility=internal').status_code == 400

def test_unverified_connection_not_executable(client):
    conversation = create(client)
    assert client.post(f'/v1/conversations/{conversation}/turns', json={'text':'x','provider_profile_id':'unverified','client_request_id':'x'}).status_code == 409

def test_sse_cursor_is_per_conversation_and_isolated(client):
    one, two = create(client), create(client)
    submit(client, one, 'a')
    submit(client, one, 'b')
    submit(client, two, 'c', text='OTHER_CONVERSATION_CANARY')
    stream = client.get(f'/v1/conversations/{one}/events?after_seq=0')
    assert stream.status_code == 200
    assert 'OTHER_CONVERSATION_CANARY' not in stream.text
    data = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith('data: ')]
    assert [e['sequence'] for e in data] == [1,2,3,4]
    replay = client.get(f'/v1/conversations/{one}/events?after_seq=2').text
    assert 'id: 1\n' not in replay and 'id: 2\n' not in replay
    assert 'id: 3\n' in replay

def test_cancel_idempotent_and_remote_stop_separate(client):
    conversation = create(client)
    task = submit(client, conversation).json()['task_id']
    first = client.post(f'/v1/tasks/{task}/cancel')
    assert first.status_code == 202
    assert first.json()['cancel_requested'] is True
    assert first.json()['external_stop_confirmed'] is None
    assert client.post(f'/v1/tasks/{task}/cancel').json() == first.json()
    assert 'raw_error' not in client.get(f'/v1/tasks/{task}').text

def test_settings_and_validation_error_do_not_echo_internal_input(client, tmp_path):
    with pytest.raises(ValueError):
        AppSettings(tmp_path, 'qa-local-token', 'invalid', False)
    with pytest.raises(TypeError):
        AppSettings(tmp_path, 'qa-local-token', 'fake', False, arbitrary_path='C:/')
    value = client.post('/v1/conversations', json={'title':'INTERNAL_CANARY','raw_content_ref':'SECRET_CANARY'})
    assert value.status_code == 422
    assert 'CANARY' not in value.text

def test_non_ascii_auth_is_a_normal_rejection(client):
    assert client.get('/v1/conversations',headers={b'Authorization':b'Bearer \xff'}).status_code==401

def test_startup_reconciles_existing_external_request_without_model_retry(client):
    from contextlib import closing
    from app.api.application import create_app
    conversation=create(client)
    task=submit(client,conversation).json()['task_id']
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("UPDATE task_runs SET state='EXECUTING',external_request_id='existing-request',external_execution_id='existing-execution' WHERE task_id=?",(task,))
    restored=create_app(AppSettings(client.app.state.settings.data_root,'qa-local-token','fake',True))
    with closing(restored.state.database.connect()) as connection:
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
    assert row['state']=='BLOCKED' and row['external_request_id']=='existing-request'
    assert restored.state.recovery_results[0]['decision']=='blocked_unknown'

def test_unstarted_turn_survives_restart_as_local_pending(client):
    from contextlib import closing
    from app.api.application import create_app
    conversation=create(client)
    task=submit(client,conversation).json()['task_id']
    restored=create_app(AppSettings(client.app.state.settings.data_root,'qa-local-token','fake',True))
    with closing(restored.state.database.connect()) as connection:
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
    assert row['state']=='RECEIVED'
    assert restored.state.recovery_results[0]['decision']=='local_pending'

@pytest.mark.parametrize('accepted',[True,False])
def test_cancel_retains_unknown_remote_acceptance_without_returned_ids(client,accepted):
    from contextlib import closing
    conversation=create(client)
    task=submit(client,conversation).json()['task_id']
    with closing(client.app.state.database.connect()) as connection:
        checkpoint={'active_external_request':{'accepted':accepted,'status':'unknown','external_request_id':None,'external_execution_id':None}}
        connection.execute("UPDATE task_runs SET state='EXECUTING',remote_status='unknown',checkpoint_json=? WHERE task_id=?",(json.dumps(checkpoint),task))
    response=client.post(f'/v1/tasks/{task}/cancel')
    assert response.status_code==202
    assert response.json()['cancel_pending_remote'] is accepted
    assert response.json()['external_stop_confirmed'] is None
    assert response.json()['status']==('cancel_pending_remote' if accepted else 'cancelled')
