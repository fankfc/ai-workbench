import asyncio
import hashlib
import json
from contextlib import closing
import pytest

from app.contracts.artifacts import ArtifactVersion
from app.runtime.publication import NativePublisher
from app.runtime.state_machine import StateMachine
from app.storage.blobs import store_artifact
from app.storage.database import transaction
from app.storage.revisions import activate_revision
from support.contracts import make_contract, make_decision


@pytest.fixture
def claude_answer(client):
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("INSERT OR IGNORE INTO provider_profiles(id,adapter,model_id,family,connection_id,identity_status,identity_source,connection_version) VALUES ('fake-claude','fake','fixture-claude','claude','fake-claude','verified','fixture:fake','1')")
    conversation = client.post('/v1/conversations', json={'title':'translation fixture'}).json()['id']
    accepted = client.post(f'/v1/conversations/{conversation}/turns', json={'text':'保留原文件。','provider_profile_id':'fake-claude','client_request_id':'translation-one'}).json()
    task = accepted['task_id']
    root = client.app.state.settings.data_root/'evidence'
    with closing(client.app.state.database.connect()) as connection:
        row = connection.execute('SELECT * FROM task_runs WHERE task_id=?', (task,)).fetchone()
        attempt = row['attempt_id']; route = json.loads(row['route_snapshot_json'])
        content = b'Keep the original file. INTERNAL_ENGLISH_CANARY'
        sha = hashlib.sha256(content).hexdigest()
        artifact = ArtifactVersion(id='en-answer',task_id=task,artifact_kind='answer',language='en',immutable_uri=client.app.state.blobs.uri_for(sha),byte_sha256=sha,canonical_content_sha256=sha,source_version_id=None,origin_authors=['A'],canonical_issued_by='A',reviewed_by=['A'],rendered_by='none',a_response_ref=client.app.state.blobs.uri_for(sha),dependencies=[])
        store_artifact(connection,client.app.state.blobs,content,artifact,attempt_id=attempt,provenance={'test_only':True,'complete':True})
        request=dict(task_id=task,attempt_id=attempt,role='A',identity=dict(adapter=route['adapter_id'],model_id=route['model_id'],family='claude',connection_id='fake-claude'),prompt_path='fixture-only',workspace='fixture-only',policy_version='1.0')
        with transaction(connection):
            connection.execute("INSERT INTO steps(id,task_id,attempt_id,step_key,role,state,provider_profile_id,request_json) VALUES ('fixture-a-body',?,?,?,'A','COMPLETED','fake-claude',?)",(task,attempt,'fixture-canonical',json.dumps(request)))
            from app.runtime.outbox import enqueue_event
            for sequence,kind,payload in [(1,'artifact.candidate',{'text':content.decode(),'language':'en'}),(2,'model.completed',{'reported_complete':True})]:
                enqueue_event(connection,task,attempt,'workflow.provider_event',dict(step_id='fixture-a-body',provider_sequence=sequence,kind=kind,payload=payload),deduplication_key=f'fixture-body:{task}:{sequence}')
        from app.documents.canonical import CanonicalCapture
        CanonicalCapture(client.app.state.database.path).capture(task,attempt,'fixture-a-body',language='en',logical_id='answer',revision_id='en-answer')
        contract = make_contract(task,attempt,route['id'],model_family=route['model_family'])
        decision = make_decision(contract,'en-answer',root)
        from app.contracts.tasks import contract_digest
        with transaction(connection):
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps({'current_revision_id':'en-answer','task_contract':contract,'workflow':{'contract_sha256':contract_digest(contract)}}),task))
            activate_revision(connection,client.app.state.blobs,task,attempt,'answer','en-answer',{})
            connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES ('translation-review',?,?,?,'A.review','pass','1.0',?)",(task,attempt,'en-answer',json.dumps({'contract':contract,'decision':decision})))
    machine = StateMachine(client.app.state.database.path); before = 'RECEIVED'
    for state in ('INPUT_PREPARING','PLANNING','EXECUTING','VALIDATING','REVIEWING','OUTPUT_PREPARING'):
        machine.transition(task,attempt,before,state,'1.0'); before=state
    return client,conversation,task,attempt,root,route,machine


def test_approved_claude_answer_can_reach_a_chinese_release_gate(claude_answer):
    client,conversation,task,attempt,root,route,machine = claude_answer
    from app.runtime.answer_publication import AnswerPublisher
    from translation.fakes import service
    publisher = AnswerPublisher(client.app.state.database.path, root,service(client))
    approval = asyncio.run(publisher.stage(task,attempt,'1.0','en-answer','translation-review'))
    assert approval
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    publisher.publish(task,attempt,'1.0')
    with closing(client.app.state.database.connect()) as connection:
        event=connection.execute("SELECT * FROM outbox_events WHERE task_id=? AND kind='answer.published'",(task,)).fetchone()
        payload=json.loads(event['public_event_json'])['payload']
    assert payload['text']=='保留原文件。' and payload['language']=='zh-CN'
    assert 'INTERNAL_ENGLISH_CANARY' not in event['public_event_json']

def test_three_failed_output_candidates_keep_english_internal_without_success(claude_answer):
    from app.runtime.answer_publication import AnswerPublisher
    from app.runtime.publication import PublicationBlocked
    from translation.fakes import service
    client,conversation,task,attempt,root,route,machine=claude_answer
    translation=service(client,transform=lambda request:{})
    publisher=AnswerPublisher(client.app.state.database.path,root,translation)
    with pytest.raises(PublicationBlocked,match='TRANSLATION_FAILED'):
        asyncio.run(publisher.stage(task,attempt,'1.0','en-answer','translation-review'))
    assert len(translation.translator.calls)==3
    with closing(client.app.state.database.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM outbox_events WHERE task_id=? AND kind='answer.published'",(task,)).fetchone()[0]==0
        assert connection.execute("SELECT COUNT(*) FROM bilingual_history WHERE task_id=? AND visibility='internal'",(task,)).fetchone()[0]==1

def test_cancelled_task_cannot_publish_late_translation(claude_answer):
    from app.runtime.answer_publication import AnswerPublisher
    from translation.fakes import service
    client,conversation,task,attempt,root,route,machine=claude_answer
    publisher=AnswerPublisher(client.app.state.database.path,root,service(client))
    asyncio.run(publisher.stage(task,attempt,'1.0','en-answer','translation-review'))
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    client.post(f'/v1/tasks/{task}/cancel')
    with pytest.raises(ValueError): publisher.publish(task,attempt,'1.0')

def test_frozen_translation_history_survives_staleness_but_cannot_publish_again(claude_answer):
    from app.runtime.answer_publication import AnswerPublisher,validate_translation_release
    from translation.fakes import service
    client,conversation,task,attempt,root,route,machine=claude_answer
    publisher=AnswerPublisher(client.app.state.database.path,root,service(client))
    asyncio.run(publisher.stage(task,attempt,'1.0','en-answer','translation-review'))
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0'); publisher.publish(task,attempt,'1.0')
    with closing(client.app.state.database.connect()) as connection:
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone(); release=json.loads(row['checkpoint_json'])['public_release']
        connection.execute("UPDATE translation_jobs SET status='STALE' WHERE id=?",(release['translation_job_id'],))
        connection.execute("UPDATE checks SET details_json=json_set(details_json,'$.stale',json('true')) WHERE id=?",(release['qa_id'],))
        with pytest.raises(ValueError): validate_translation_release(connection,client.app.state.blobs,row,release)
        assert validate_translation_release(connection,client.app.state.blobs,row,release,historical=True).decode()=='保留原文件。'

def test_published_assistant_message_has_full_original_english_history_mapping(claude_answer):
    from app.runtime.answer_publication import AnswerPublisher
    from app.translation.history import BilingualHistory
    from translation.fakes import service
    client,conversation,task,attempt,root,route,machine=claude_answer
    translation=service(client); publisher=AnswerPublisher(client.app.state.database.path,root,translation)
    asyncio.run(publisher.stage(task,attempt,'1.0','en-answer','translation-review'))
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0'); publisher.publish(task,attempt,'1.0')
    history=BilingualHistory(client.app.state.database.path).conversation(translation.router.lock(task,attempt),english=True)
    assert any(m['role']=='assistant' and 'INTERNAL_ENGLISH_CANARY' in m['content'] for m in history)
