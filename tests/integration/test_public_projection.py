import json
from contextlib import closing
import pytest
from app.api.turns import append_event
from app.runtime.public_projection import project_event
from app.storage.database import transaction

@pytest.mark.parametrize('kind',['model.delta','tool.output','translation.block','validation.log','future.unknown','answer.published'])
def test_without_trusted_registry_no_internal_text_is_public(kind):
    assert project_event(dict(task_id='t',attempt_id='a',sequence=1,kind=kind,payload={'text':'INTERNAL_ENGLISH_CANARY','key':'SECRET_CANARY','visibility':'user'})) is None

def make_task(client):
    conversation=client.post('/v1/conversations',json={'title':'test'}).json()['id']
    turn=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'用户材料','provider_profile_id':'fake-gpt','client_request_id':'one'}).json()
    return conversation,turn['task_id']

def append(client,task,kind,payload):
    with closing(client.app.state.database.connect()) as connection,transaction(connection):
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
        append_event(connection,row['turn_id'],task,row['attempt_id'],kind,payload)

@pytest.mark.parametrize('kind',['model.delta','tool.output','translation.block','validation.log','future.unknown','answer.published','artifacts.published'])
def test_history_and_sse_share_default_deny(client,kind):
    conversation,task=make_task(client)
    append(client,task,kind,{'text':'INTERNAL_ENGLISH_CANARY','key':'SECRET_CANARY','visibility':'user','approval_id':'invented'})
    for suffix in ('messages','events?after_seq=0'):
        value=client.get(f'/v1/conversations/{conversation}/{suffix}')
        assert value.status_code==200
        assert 'CANARY' not in value.text and 'invented' not in value.text

def test_pending_and_error_are_fixed_public_templates(client):
    conversation,task=make_task(client)
    append(client,task,'response.pending',{'stage':'A','text':'INTERNAL_ENGLISH_CANARY'})
    append(client,task,'request.failed',{'error_code':'PROVIDER_UNAVAILABLE','stack':'SECRET_CANARY'})
    stream=client.get(f'/v1/conversations/{conversation}/events').text
    assert 'CANARY' not in stream and '"stage"' not in stream
    messages=client.get(f'/v1/conversations/{conversation}/messages').json()['items']
    assert messages[-1]['language']=='zh-CN'
    assert messages[-1]['text']=='模型连接暂不可用，请检查连接。'

def test_clarification_ignores_model_text(client):
    conversation,task=make_task(client)
    append(client,task,'input.required',{'prompt_code':'ambiguous_goal','text':'SECRET_CANARY'})
    messages=client.get(f'/v1/conversations/{conversation}/messages').json()['items']
    assert messages[-1]['text']=='请明确任务目标和验收要求。'
    append(client,task,'input.required',{'prompt_code':'SECRET_CANARY'})
    assert len(client.get(f'/v1/conversations/{conversation}/messages').json()['items'])==2

def test_forged_cancellation_and_late_answer_do_not_publish(client):
    conversation,task=make_task(client)
    append(client,task,'request.cancelled',{'text':'SECRET_CANARY'})
    assert len(client.get(f'/v1/conversations/{conversation}/messages').json()['items'])==1
    client.post(f'/v1/tasks/{task}/cancel')
    append(client,task,'answer.published',{'text':'SECRET_CANARY','approval_id':'fake'})
    stream=client.get(f'/v1/conversations/{conversation}/events').text
    assert 'SECRET_CANARY' not in stream and 'answer.published' not in stream

def test_schema_failure_is_closed():
    assert project_event({'task_id':'t','attempt_id':'a','sequence':True,'kind':'model.delta','payload':{},'debug':'secret'}) is None
