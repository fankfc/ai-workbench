import hashlib
import json
from contextlib import closing
import pytest

from app.contracts.artifacts import ArtifactVersion
from app.storage.blobs import store_artifact
from app.storage.database import transaction
from app.storage.revisions import activate_revision
from app.runtime.publication import NativePublisher,PublicationBlocked
from app.runtime.state_machine import StateMachine
from support.contracts import make_contract,make_decision

@pytest.fixture
def prepared(client):
    conversation=client.post('/v1/conversations',json={'title':'native'}).json()['id']
    task=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'工作','provider_profile_id':'fake-gpt','client_request_id':'one'}).json()['task_id']
    root=client.app.state.settings.data_root/'evidence'
    with closing(client.app.state.database.connect()) as connection:
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
        attempt=row['attempt_id']
        route=json.loads(row['route_snapshot_json'])
        content='批准后的最终回答。'.encode('utf-8')
        sha=hashlib.sha256(content).hexdigest()
        artifact=ArtifactVersion(id='rev1',task_id=task,artifact_kind='answer',language='zh-CN',immutable_uri=client.app.state.blobs.uri_for(sha),byte_sha256=sha,canonical_content_sha256=sha,source_version_id=None,origin_authors=['B'],canonical_issued_by='B',reviewed_by=['A'],rendered_by='none',a_response_ref=None,dependencies=[])
        store_artifact(connection,client.app.state.blobs,content,artifact,attempt_id=attempt,provenance={'test_only':True})
        contract=make_contract(task,attempt,route['id'])
        decision=make_decision(contract,'rev1',root)
        with transaction(connection):
            from app.contracts.tasks import contract_digest
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps({'current_revision_id':'rev1','task_contract':contract,'workflow':{'contract_sha256':contract_digest(contract)}}),task))
            activate_revision(connection,client.app.state.blobs,task,attempt,'answer','rev1',{})
            connection.execute("INSERT INTO checks(id,task_id,attempt_id,artifact_version_id,check_kind,result,check_version,details_json) VALUES ('a-review',?,?,?,'A.review','pass','1.0',?)",(task,attempt,'rev1',json.dumps({'contract':contract,'decision':decision})))
    machine=StateMachine(client.app.state.database.path)
    before='RECEIVED'
    for state in ('INPUT_PREPARING','PLANNING','EXECUTING','VALIDATING','REVIEWING','OUTPUT_PREPARING'):
        machine.transition(task,attempt,before,state,'1.0')
        before=state
    return client,conversation,task,attempt,root,NativePublisher(client.app.state.database.path,root),machine

def test_native_release_reads_approved_bytes_and_is_idempotent(prepared):
    client,conversation,task,attempt,root,publisher,machine=prepared
    publisher.stage(task,attempt,'1.0','rev1','a-review')
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    publisher.publish(task,attempt,'1.0')
    publisher.publish(task,attempt,'1.0')
    messages=client.get(f'/v1/conversations/{conversation}/messages').json()['items']
    assert messages[-1]['text']=='批准后的最终回答。'
    assert sum(m['kind']=='answer.published' for m in messages)==1
    from app.usage.ledger import UsageLedger
    assert UsageLedger(client.app.state.database.path).summary(task)['qualified_deliveries']==1

def test_current_a_evidence_is_required(prepared):
    client,_,task,attempt,root,publisher,_=prepared
    (root/'rev1-AC1.json').write_text('changed',encoding='utf-8')
    with pytest.raises(PublicationBlocked):
        publisher.stage(task,attempt,'1.0','rev1','a-review')

def test_changed_evidence_after_stage_blocks_publish(prepared):
    client,_,task,attempt,root,publisher,machine=prepared
    publisher.stage(task,attempt,'1.0','rev1','a-review')
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    (root/'rev1-AC1.json').write_text('changed',encoding='utf-8')
    with pytest.raises(PublicationBlocked):
        publisher.publish(task,attempt,'1.0')

def test_cancel_and_old_revision_block_staged_answer(prepared):
    client,conversation,task,attempt,root,publisher,machine=prepared
    publisher.stage(task,attempt,'1.0','rev1','a-review')
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    client.post(f'/v1/tasks/{task}/cancel')
    with pytest.raises(PublicationBlocked):
        publisher.publish(task,attempt,'1.0')
    assert 'answer.published' not in client.get(f'/v1/conversations/{conversation}/events').text

def test_forged_earlier_answer_does_not_gain_authority_after_actual_publish(prepared):
    from app.api.turns import append_event
    client,conversation,task,attempt,root,publisher,machine=prepared
    publisher.stage(task,attempt,'1.0','rev1','a-review')
    with closing(client.app.state.database.connect()) as connection,transaction(connection):
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
        append_event(connection,row['turn_id'],task,attempt,'answer.published',{'release_id':'invented'})
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    publisher.publish(task,attempt,'1.0')
    messages=client.get(f'/v1/conversations/{conversation}/messages').json()['items']
    assert sum(m['kind']=='answer.published' for m in messages)==1

def test_required_a_canonical_cannot_be_satisfied_by_b_blob_and_a_pass(prepared):
    client,_,task,attempt,root,publisher,_=prepared
    with closing(client.app.state.database.connect()) as connection:
        check=connection.execute("SELECT * FROM checks WHERE id='a-review'").fetchone()
        details=json.loads(check['details_json'])
        details['contract']['deliverables'][0]['require_a_canonical']=True
        details['decision']=make_decision(details['contract'],'rev1',root)
        connection.execute("UPDATE checks SET details_json=? WHERE id='a-review'",(json.dumps(details),))
        row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
        checkpoint=json.loads(row['checkpoint_json'])
        from app.contracts.tasks import contract_digest
        checkpoint['task_contract']=details['contract']
        checkpoint['workflow']['contract_sha256']=contract_digest(details['contract'])
        connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),task))
    with pytest.raises(PublicationBlocked,match='A_CANONICAL'):
        publisher.stage(task,attempt,'1.0','rev1','a-review')

def test_genuine_published_history_remains_visible_after_new_attempt(prepared):
    client,conversation,task,attempt,root,publisher,machine=prepared
    publisher.stage(task,attempt,'1.0','rev1','a-review')
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    publisher.publish(task,attempt,'1.0')
    with closing(client.app.state.database.connect()) as connection:
        old=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
        route=json.loads(old['route_snapshot_json'])
        route.update(id='new-route',attempt_id='new-attempt')
        connection.execute("INSERT INTO task_runs(task_id,attempt_id,turn_id,provider_profile_id,state,attempt_number,route_snapshot_json) VALUES (?,?,?,?,'RECEIVED',2,?)",(task,'new-attempt',old['turn_id'],old['provider_profile_id'],json.dumps(route)))
    messages=client.get(f'/v1/conversations/{conversation}/messages').json()['items']
    answers=[m for m in messages if m['kind']=='answer.published']
    assert len(answers)==1
    assert answers[0]['historical'] is True and answers[0]['content_version_id']=='rev1'

@pytest.mark.parametrize('change',['revision','task','route','canonical','budget','pinned_contract'])
def test_changed_review_or_pinned_contract_after_stage_never_publishes(prepared,change):
    client,_,task,attempt,root,publisher,machine=prepared
    publisher.stage(task,attempt,'1.0','rev1','a-review')
    machine.transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    with closing(client.app.state.database.connect()) as connection:
        if change=='pinned_contract':
            row=connection.execute('SELECT * FROM task_runs WHERE task_id=?',(task,)).fetchone()
            checkpoint=json.loads(row['checkpoint_json'])
            checkpoint['task_contract']['budget']['total_tokens']=1
            checkpoint['task_contract']['budget']['reserved_a_tokens']=0
            connection.execute('UPDATE task_runs SET checkpoint_json=? WHERE task_id=?',(json.dumps(checkpoint),task))
        else:
            check=connection.execute("SELECT * FROM checks WHERE id='a-review'").fetchone()
            details=json.loads(check['details_json'])
            contract=details['contract']
            if change=='task': contract['task_id']='different-task'
            elif change=='route': contract['route_snapshot_id']='different-route'
            elif change=='canonical': contract['deliverables'][0]['require_a_canonical']=True
            elif change=='budget': contract['budget']=dict(total_tokens=1,reserved_a_tokens=0)
            details['decision']=make_decision(contract,'rev2' if change=='revision' else 'rev1',root)
            connection.execute("UPDATE checks SET details_json=? WHERE id='a-review'",(json.dumps(details),))
    with pytest.raises(PublicationBlocked):
        publisher.publish(task,attempt,'1.0')
    with closing(client.app.state.database.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM outbox_events WHERE kind='answer.published'").fetchone()[0]==0
