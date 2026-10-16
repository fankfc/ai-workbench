"""Actual A provenance and translated clarification publication gates."""
import asyncio
from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib
import json

import pytest
from app.api.public_events import public_events
from app.contracts.providers import ProviderContract
from app.providers.phase_bridge import PhaseStarted,PhaseCapture,UsageReceipt
from app.runtime.planning import NativeTaskPlanner
from app.storage.database import transaction
from app.translation.input_pipeline import InputPipeline
from support.contracts import make_contract
from translation.fakes import claude_turn
from test_claude_native_pipeline import assembly,FakeClaudePlanner,CLAUDE

QUESTION='Do not delete the original files. Should I use only 2 source files, or wait for the missing appendix?'
CHINESE='不得删除原始文件。应当只使用 2 个源文件，还是等待缺失的附录？'

def translated(request):
    output={}
    for block in request.blocks:
        text=block['source']
        if request.target_language=='en': text=text.replace('保留原文件。','Keep the original file.')
        else:
            text=text.replace('Do not delete the original files. Should I use only ','不得删除原始文件。应当只使用 ')
            text=text.replace(' source files, or wait for the missing appendix?',' 个源文件，还是等待缺失的附录？')
        output[block['block_id']]=text
    return output

def review_case(client,**options):
    cid,task,attempt=claude_turn(client); svc,manager,b,a,workflow=assembly(client,task,attempt,transform=translated,**options)
    a.reviews=[dict(decision='NEED_EVIDENCE',clarification_text=QUESTION,issues=[QUESTION],
        read_unit_ids=['USER-1'],usage={'total_tokens':9})]
    workspace=manager.create(task,attempt); raw='保留原文件。'.encode(); workspace.ingest_source('request.md',raw)
    with closing(svc.database.connect()) as connection:
        route=json.loads(connection.execute('SELECT route_snapshot_json FROM task_runs WHERE task_id=?',(task,)).fetchone()[0])
    value=make_contract(task,attempt,route['id'],'mixed','claude')
    value['inputs']=[dict(id='USER-1',ref='input/request.md',sha256=hashlib.sha256(raw).hexdigest())]
    value['source_unit_ids']=['USER-1']; value['full_read_required']=True
    return cid,task,attempt,svc,b,a,workflow,value

def test_actual_a_review_clarification_is_completely_translated_and_public(client):
    cid,task,attempt,svc,b,a,workflow,value=review_case(client)
    result=asyncio.run(workflow.run(value)); assert result.state=='NEEDS_INPUT'
    with closing(svc.database.connect()) as connection:
        questions=[event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required']
        assert len(questions)==1 and questions[0]['payload']['text']==CHINESE
        assert QUESTION not in json.dumps(questions)
        publication=connection.execute("SELECT * FROM checks WHERE check_kind='clarification.publication'").fetchone()
        assert publication is not None and publication['result']=='pass'
        jobs=connection.execute("SELECT * FROM translation_jobs WHERE task_id=? AND json_extract(job_json,'$.purpose')='clarification'",(task,)).fetchall()
        assert len(jobs)==1 and jobs[0]['status']=='READY'
    assert any(call.phase=='check' for call in svc.checker.calls)

class FakeClarifyingPlanner(FakeClaudePlanner):
    async def invoke_text(self,prompt,**kwargs):
        self.starts.append(json.loads(prompt)); fixed=self.starts[-1]['required_contract_fields']; request=kwargs['request_id']
        response=dict(decision='NEED_EVIDENCE',clarification_text=QUESTION,task_id=fixed['task_id'],
            attempt_id=fixed['attempt_id'],route_snapshot_id=fixed['route_snapshot_id'])
        yield PhaseStarted(request,request+'-response',request+'-execution')
        yield PhaseCapture(request,self.provider,json.dumps(response),request+'-response',request+'-execution',
            (UsageReceipt(request+'-receipt',1,{'total_tokens':15},'reported'),))

def test_actual_a_planning_clarification_stops_before_b_and_preserves_capture(client):
    cid,task,attempt=claude_turn(client); svc,manager,b,a,workflow=assembly(client,task,attempt,transform=translated)
    owner='fixture-clarifying-plan'
    with closing(svc.database.connect()) as connection,transaction(connection):
        connection.execute("UPDATE task_runs SET state='INPUT_PREPARING',lease_owner=?,lease_expires_at=? WHERE task_id=?",
            (owner,(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),task))
    runtime=FakeClarifyingPlanner(); planner=NativeTaskPlanner(svc.database_path,manager,runtime,
        allow_fixture=True,estimated_tokens=24,input_pipeline=InputPipeline(svc))
    result=asyncio.run(planner.plan(task,attempt,owner))
    assert result.state=='NEEDS_INPUT' and b.starts==a.starts==[]
    with closing(svc.database.connect()) as connection:
        questions=[event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required']
        assert len(questions)==1 and questions[0]['payload']['text']==CHINESE
        assert connection.execute("SELECT count(*) FROM steps WHERE role='A' AND state='COMPLETED'").fetchone()[0]==1

@pytest.mark.parametrize('failure',['echo','partial_echo','negation','cancel','identity'])
def test_clarification_failure_or_late_fence_never_exposes_english_or_template(client,failure):
    cid,task,attempt,svc,b,a,workflow,value=review_case(client)
    original=svc.translator.transform
    def transform(request):
        clarification=request.target_language=='zh-CN' and any('Do not delete' in block['source'] for block in request.blocks)
        if clarification:
            if failure=='cancel': client.post(f'/v1/tasks/{task}/cancel')
            if failure=='identity': svc.router.check_identity(task,attempt,CLAUDE.model_copy(update={'connection_version':'drift'}))
            if failure=='echo': return {block['block_id']:block['source'] for block in request.blocks}
            if failure=='partial_echo': return {block['block_id']:'请确认。'+block['source'] for block in request.blocks}
        return original(request)
    svc.translator.transform=transform
    if failure=='negation':
        svc.checker.findings=lambda request:[dict(block_id=request.blocks[0]['block_id'],code='NEGATION_CHANGED',
            severity='major',message='Negation removed',source_locator=request.blocks[0]['source_locator'])] if request.target_language=='zh-CN' else []
    result=asyncio.run(workflow.run(value))
    assert result.state=={'cancel':'CANCELLED','identity':'PAUSED'}.get(failure,'BLOCKED')
    with closing(svc.database.connect()) as connection:
        visible=public_events(connection,svc.store,cid)
        assert not [event for event in visible if event['kind'] in ('input.required','answer.published','artifacts.published')]
        assert QUESTION not in json.dumps(visible)
        if failure in ('cancel','identity'):
            call=connection.execute("SELECT * FROM translation_calls WHERE phase='translate' ORDER BY rowid DESC LIMIT 1").fetchone()
            assert call['status']!='pending' and call['usage_json'] is not None

def test_b_step_or_forged_input_required_cannot_publish_a_clarification(client):
    from app.translation.clarification import ClarificationPublisher
    from app.runtime.outbox import enqueue_event
    cid,task,attempt,svc,b,a,workflow,value=review_case(client)
    asyncio.run(workflow.run(value))
    with closing(svc.database.connect()) as connection:
        b_step=connection.execute("SELECT id FROM steps WHERE role='B'").fetchone()[0]
    with pytest.raises(ValueError,match='A_CLARIFICATION_STEP_REQUIRED'):
        asyncio.run(ClarificationPublisher(svc.database_path,svc).publish(task,attempt,b_step,origin='workflow_review'))
    with closing(svc.database.connect()) as connection,transaction(connection):
        enqueue_event(connection,task,attempt,'input.required',{'clarification_release_id':'forged-B-release'},
            deduplication_key='forged-B-clarification',public_payload=dict(prompt_id='forged-B',text=QUESTION,language='en'))
    with closing(svc.database.connect()) as connection:
        visible=[event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required']
        assert len(visible)==1 and visible[0]['payload']['text']==CHINESE

def test_frozen_question_remains_visible_but_corrupt_source_or_qa_is_hidden(client):
    cid,task,attempt,svc,b,a,workflow,value=review_case(client); asyncio.run(workflow.run(value))
    svc.router.check_identity(task,attempt,CLAUDE.model_copy(update={'connection_version':'changed'}))
    with closing(svc.database.connect()) as connection:
        assert len([event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required'])==1
        frozen=json.loads(connection.execute("SELECT details_json FROM checks WHERE check_kind='clarification.publication'").fetchone()[0])
    svc.store.path_for(frozen['source']['source_sha256']).write_bytes(b'changed question')
    with closing(svc.database.connect()) as connection:
        assert not [event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required']

def test_gpt_english_planning_question_is_native_and_calls_translator_zero(client):
    from app.runtime.planning import require_planning_clarification
    from translation.fakes import service
    from app.runtime.workspace import WorkspaceManager
    gpt=ProviderContract(schema_version='1.0',provider_id='fake-gpt',identity=dict(adapter='fake',model_id='fixture-gpt',family='gpt',connection_id='fake-gpt'),
        identity_status='verified',identity_source='fixture:fake',connection_version='test-only')
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("UPDATE provider_profiles SET identity_status='verified',identity_source=?,provider_json=? WHERE id='fake-gpt'",(gpt.identity_source,gpt.model_dump_json()))
    cid=client.post('/v1/conversations',json={'title':'native question'}).json()['id']
    accepted=client.post(f'/v1/conversations/{cid}/turns',json=dict(text='Keep the original file.',provider_profile_id='fake-gpt',client_request_id='gpt-question')).json()
    task=accepted['task_id']; svc=service(client); manager=WorkspaceManager(svc.database_path.parent)
    with closing(svc.database.connect()) as connection,transaction(connection):
        attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
        connection.execute("UPDATE task_runs SET state='INPUT_PREPARING',lease_owner='question-owner',lease_expires_at=? WHERE task_id=?",((datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),task))
    runtime=FakeClarifyingPlanner(); runtime.provider=gpt
    planner=NativeTaskPlanner(svc.database_path,manager,runtime,allow_fixture=True,estimated_tokens=24,input_pipeline=InputPipeline(svc))
    result=asyncio.run(planner.plan(task,attempt,'question-owner'))
    require_planning_clarification(svc.database_path,result)
    assert svc.translator.calls==svc.checker.calls==[]
    with closing(svc.database.connect()) as connection:
        visible=[event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required']
        assert visible[0]['payload']['text']==QUESTION and visible[0]['payload']['language']=='en'
        assert connection.execute('SELECT count(*) FROM translation_jobs').fetchone()[0]==0

def test_approved_clarification_keeps_original_english_in_followup_history(client):
    cid,task,attempt,svc,b,a,workflow,value=review_case(client); asyncio.run(workflow.run(value))
    _,next_task,next_attempt=claude_turn(client,conversation=cid,key='followup')
    context=asyncio.run(InputPipeline(svc).prepare(next_task,next_attempt,workflow.workspaces.create(next_task,next_attempt)))
    assert context.status=='READY' and QUESTION in context.text and CHINESE not in context.text

def test_actual_supervisor_planning_question_never_hands_off_to_b(client):
    from app.runtime.native_backend import build_native_backend
    from app.runtime.native_executor import NativeTaskExecutor
    from app.runtime.supervisor import TaskSupervisor
    cid,task,attempt=claude_turn(client); svc,manager,b,a,workflow=assembly(client,task,attempt,transform=translated)
    runtime=FakeClarifyingPlanner(); planner=NativeTaskPlanner(svc.database_path,manager,runtime,
        allow_fixture=True,estimated_tokens=24,input_pipeline=InputPipeline(svc))
    bindings=build_native_backend(planner,NativeTaskExecutor(workflow),allow_fixture=True,
        provider_registry={'fake-claude':runtime,'fake-glm':b})
    supervisor=TaskSupervisor(svc.database_path,bindings,provider_mode='fake'); supervisor.register_profiles()
    result=asyncio.run(supervisor.run_once())
    assert result and result.state=='NEEDS_INPUT' and b.starts==a.starts==[]
    with closing(svc.database.connect()) as connection:
        assert len([event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required'])==1
        assert connection.execute("SELECT count(*) FROM steps WHERE role='B'").fetchone()[0]==0

def test_clarification_qa_byte_binding_cannot_be_replaced_by_generic_pass(client):
    cid,task,attempt,svc,b,a,workflow,value=review_case(client); asyncio.run(workflow.run(value))
    with closing(svc.database.connect()) as connection:
        frozen=json.loads(connection.execute("SELECT details_json FROM checks WHERE check_kind='clarification.publication'").fetchone()[0])
        connection.execute("UPDATE translation_jobs SET qa_id='unbound-generic-pass' WHERE id=?",(frozen['job_id'],))
        assert not [event for event in public_events(connection,svc.store,cid) if event['kind']=='input.required']
