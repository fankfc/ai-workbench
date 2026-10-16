"""Explicit external model fixtures through the actual private native pipeline."""
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import pytest

from app.contracts.providers import ProviderContract
from app.contracts.tasks import validate_contract
from app.providers.fake import FakeProvider
from app.providers.phase_bridge import PhaseStarted, PhaseCapture, UsageReceipt
from app.runtime.workflow import Workflow
from app.runtime.workspace import WorkspaceManager
from app.runtime.planning import NativeTaskPlanner
from app.runtime.native_executor import NativeTaskExecutor
from app.runtime.answer_publication import AnswerPublisher
from app.runtime.state_machine import StateMachine
from app.storage.database import transaction
from app.usage.budgets import check_budget
from support.contracts import make_contract
from translation.fakes import claude_turn, service, IDENTITY

CLAUDE = ProviderContract(schema_version='1.0', provider_id='fake-claude',
    identity=dict(adapter='fake', model_id='fixture-claude', family='claude', connection_id='fake-claude'),
    identity_status='verified', identity_source='fixture:fake', connection_version='1')

class FakeClaudePlanner:
    classification='fixture'
    provider=CLAUDE
    def __init__(self): self.starts=[]
    async def invoke_text(self, prompt, **kwargs):
        self.starts.append(json.loads(prompt)); fixed=self.starts[-1]['required_contract_fields']
        value=make_contract(fixed['task_id'],fixed['attempt_id'],fixed['route_snapshot_id'],'mixed','claude')
        value.update(fixed); value['budget']=dict(total_tokens=300000,reserved_a_tokens=60000)
        if self.starts[-1].get('task_profile'):
            value['acceptance'].extend(self.starts[-1]['task_profile']['acceptance'])
        request=kwargs['request_id']; yield PhaseStarted(request,request+'-response',request+'-execution')
        yield PhaseCapture(request,self.provider,json.dumps(value),request+'-response',request+'-execution',
            (UsageReceipt(request+'-receipt',1,{'total_tokens':15},'reported'),))
    async def cancel(self,*args): return True

def mechanical(candidate):
    # An actual content condition, with bytes supplied by the product workspace.
    assert candidate.artifact_path.read_bytes()==candidate.content
    from app.documents.parse import parse_document
    parsed=parse_document(candidate.content,'markdown',source_version_id=candidate.revision_id,language='en')
    observations=[]
    for item in candidate.contract.acceptance:
        if item.verifier!='C': continue
        details=dict(actual_sha256=hashlib.sha256(candidate.content).hexdigest(),parse_complete=parsed.complete)
        passed=b'Keep the original file.' in candidate.content and parsed.complete
        if item.condition=='requested_formats_and_layout':
            from app.documents.render import DocumentRenderer
            # The fixture replaces only model responses. These are actual
            # render bytes and renderer observations, before final bundle QA.
            rendered=[DocumentRenderer().render(parsed,format,evidence_dir=candidate.workspace.area('evidence')/('preview-'+candidate.revision_id))
                for format in ('markdown','pdf','docx')]
            details['render_qa']=[result.qa for result in rendered]
            passed=passed and all(result.qa.get('status')=='pass' for result in rendered)
        observations.append(dict(criterion_id=item.id,passed=passed,evidence=details))
    return observations

def assembly(client, task, attempt, **options):
    svc=service(client,**options); manager=WorkspaceManager(client.app.state.database.path.parent)
    b=FakeProvider(executions=[dict(text='Keep the original file.',language='en',usage={'total_tokens':7})])
    a=FakeProvider(takeovers=[dict(text='Keep the original file.',language='en',usage={'total_tokens':8})],
        reviews=[dict(decision='PASS',canonical_author='A',criterion_results={'AC2':True,'document.A1':True,'document.A2':True},
            read_unit_ids=['USER-1'],usage={'total_tokens':9})])
    b.provider=IDENTITY; a.provider=CLAUDE
    workflow=Workflow(svc.database_path,manager,b,mechanical,a,check_budget,
        estimated_tokens={'B.execution':24,'A.takeover':24,'A.review':24},
        profile_ids={'A':'fake-claude','B':'fake-glm'})
    workflow.translation_service=svc
    return svc,manager,b,a,workflow

def test_actual_workflow_generates_a_canonical_then_translates_and_publishes(client):
    _,task,attempt=claude_turn(client); svc,manager,b,a,workflow=assembly(client,task,attempt)
    workspace=manager.create(task,attempt); raw='保留原文件。'.encode(); workspace.ingest_source('request.md',raw)
    with closing(svc.database.connect()) as connection:
        route=json.loads(connection.execute('SELECT route_snapshot_json FROM task_runs WHERE task_id=?',(task,)).fetchone()[0])
    value=make_contract(task,attempt,route['id'],'mixed','claude')
    # Versioned role instructions are included in conservative request estimates.
    value['budget']['total_tokens']=30000
    value['inputs']=[dict(id='USER-1',ref='input/request.md',sha256=hashlib.sha256(raw).hexdigest())]
    value['source_unit_ids']=['USER-1']; value['full_read_required']=True
    result=asyncio.run(workflow.run(value))
    assert result.state=='OUTPUT_PREPARING', result.reason_codes
    assert len(b.starts)==1 and [json.loads(open(r.prompt_path,encoding='utf-8').read())['phase'] for r in a.starts]==['takeover','review']
    publisher=AnswerPublisher(svc.database_path,workspace.area('evidence'),svc)
    asyncio.run(publisher.stage(task,attempt,'1.0',result.current_revision_id,result.review_check_id))
    StateMachine(svc.database_path).transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
    publisher.publish(task,attempt,'1.0')
    with closing(svc.database.connect()) as connection:
        assert connection.execute('SELECT state FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]=='PUBLISHED'
        assert connection.execute("SELECT count(*) FROM checks WHERE check_kind='A.canonical'").fetchone()[0]==1
        from app.api.public_events import public_events
        event=connection.execute("SELECT * FROM outbox_events WHERE kind='answer.published'").fetchone()
        published=next(item for item in public_events(connection,svc.store,event['conversation_id']) if item['kind']=='answer.published')
        assert published['payload']['text']=='保留原文件。'

def test_actual_claude_planning_handoff_uses_verified_english_context(client):
    _,task,attempt=claude_turn(client); svc,manager,b,a,workflow=assembly(client,task,attempt)
    owner='fixture-planning-owner'
    with closing(svc.database.connect()) as connection,transaction(connection):
        connection.execute("UPDATE task_runs SET state='INPUT_PREPARING',lease_owner=?,lease_expires_at=? WHERE task_id=?",
            (owner,(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),task))
    runtime=FakeClaudePlanner(); planner=NativeTaskPlanner(svc.database_path,manager,runtime,allow_fixture=True,estimated_tokens=24)
    from app.translation.input_pipeline import InputPipeline
    planner.input_pipeline=InputPipeline(svc)
    plan=asyncio.run(planner.plan(task,attempt,owner))
    assert plan.contract.model_family=='claude'
    assert '保留原文件。' not in runtime.starts[0]['sources'][0]['content']
    executor=NativeTaskExecutor(workflow); result=asyncio.run(executor.execute(plan))
    assert result.state=='OUTPUT_PREPARING',result.reason_codes
    asyncio.run(executor.publish(plan,result))
    with closing(svc.database.connect()) as connection:
        assert connection.execute('SELECT state FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]=='PUBLISHED'

def test_private_supervisor_api_document_request_publishes_real_bilingual_files(client):
    from app.translation.input_pipeline import InputPipeline
    from app.runtime.native_backend import build_native_backend
    from app.runtime.supervisor import TaskSupervisor
    cid,previous,old_attempt=claude_turn(client)
    # This first accepted turn establishes a real selected, verified fixture
    # connection. The actual file request below is submitted through public API.
    accepted=client.post(f'/v1/conversations/{cid}/turns',json=dict(text='保留原文件。',
        domain='document',provider_profile_id='fake-claude',client_request_id='files',
        profile_inputs=dict(audience='Reader',purpose='Preserve the original file',
            source_refs=['input/user_request.txt'],formats=['markdown','pdf','docx']))).json()
    task=accepted['task_id']
    with closing(client.app.state.database.connect()) as connection:
        attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
        # The earlier request remains a history message rather than another
        # queued synthetic model job in this one-request assembly.
        connection.execute("UPDATE task_runs SET state='BLOCKED' WHERE task_id=?",(previous,))
    svc,manager,b,a,workflow=assembly(client,task,attempt)
    runtime=FakeClaudePlanner(); planner=NativeTaskPlanner(svc.database_path,manager,runtime,
        allow_fixture=True,estimated_tokens=24,input_pipeline=InputPipeline(svc))
    binding=build_native_backend(planner,NativeTaskExecutor(workflow),allow_fixture=True,
        provider_registry={'fake-claude':runtime,'fake-glm':b})
    from dataclasses import replace
    publication_errors=[]; actual_publish=binding.publish
    async def observed_publish(*args):
        try: return await actual_publish(*args)
        except Exception as error:
            publication_errors.append((type(error).__name__,str(error))); raise
    binding=replace(binding,publish=observed_publish,provider_registry=dict(binding.provider_registry))
    supervisor=TaskSupervisor(svc.database_path,binding,provider_mode='fake'); supervisor.register_profiles()
    card=asyncio.run(supervisor.run_once())
    with closing(svc.database.connect()) as connection:
        run=connection.execute('SELECT state,checkpoint_json FROM task_runs WHERE task_id=?',(task,)).fetchone()
    assert isinstance(card,dict), publication_errors or card or dict(run)
    assert len(card['artifacts'])==6
    public=client.get(f'/v1/conversations/{cid}/bundles').json()['items']
    assert len(public)==1 and len(public[0]['format_pairs'])==3
    for artifact in card['artifacts']:
        response=client.get(f'/v1/conversations/{cid}/bundles/{card["bundle_id"]}/artifacts/{artifact["artifact_id"]}/download')
        assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==artifact['sha256']

@pytest.mark.parametrize('case',['missing_input','missing_ready','identity_drift','late_cancel'])
def test_private_claude_pipeline_fences_prevent_any_publication(client,case):
    from app.translation.input_pipeline import InputPipeline
    from app.runtime.planning import PlanningBlocked
    from app.runtime.publication import PublicationBlocked
    _,task,attempt=claude_turn(client)
    svc,manager,b,a,workflow=assembly(client,task,attempt,
        transform=(lambda request:{}) if case=='missing_input' else None)
    owner='fixture-fence-owner'; runtime=FakeClaudePlanner()
    with closing(svc.database.connect()) as connection,transaction(connection):
        connection.execute("UPDATE task_runs SET state='INPUT_PREPARING',lease_owner=?,lease_expires_at=? WHERE task_id=?",
            (owner,(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),task))
    planner=NativeTaskPlanner(svc.database_path,manager,runtime,allow_fixture=True,
        estimated_tokens=24,input_pipeline=InputPipeline(svc))
    if case=='missing_input':
        with pytest.raises(PlanningBlocked): asyncio.run(planner.plan(task,attempt,owner))
        assert runtime.starts==b.starts==a.starts==[]
    else:
        plan=asyncio.run(planner.plan(task,attempt,owner)); executor=NativeTaskExecutor(workflow)
        if case=='missing_ready':
            with closing(svc.database.connect()) as connection:
                connection.execute("UPDATE translation_jobs SET status='STALE' WHERE task_id=?",(task,))
            with pytest.raises(PlanningBlocked): asyncio.run(executor.execute(plan))
            assert b.starts==a.starts==[]
        elif case=='identity_drift':
            a.provider=CLAUDE.model_copy(update={'connection_version':'changed-after-plan'})
            result=asyncio.run(executor.execute(plan))
            assert result.state=='PAUSED' and b.starts==a.starts==[]
            with closing(svc.database.connect()) as connection:
                assert connection.execute('SELECT count(*) FROM route_invalidations').fetchone()[0]==1
        else:
            result=asyncio.run(executor.execute(plan)); assert result.state=='OUTPUT_PREPARING'
            publisher=AnswerPublisher(svc.database_path,manager.create(task,attempt).area('evidence'),svc)
            asyncio.run(publisher.stage(task,attempt,'1.0',result.current_revision_id,result.review_check_id))
            StateMachine(svc.database_path).transition(task,attempt,'OUTPUT_PREPARING','READY','1.0')
            assert client.post(f'/v1/tasks/{task}/cancel').status_code==202
            with pytest.raises(PublicationBlocked): asyncio.run(executor.publish(plan,result))
    with closing(svc.database.connect()) as connection:
        assert connection.execute("SELECT count(*) FROM outbox_events WHERE kind IN ('answer.published','artifacts.published')").fetchone()[0]==0

def test_gpt_api_file_task_preserves_source_and_calls_no_translator(client):
    from app.translation.input_pipeline import InputPipeline
    from app.runtime.native_backend import build_native_backend
    from app.runtime.supervisor import TaskSupervisor
    cid=client.post('/v1/conversations',json={'title':'native GPT file task'}).json()['id']
    # Install the verified fixture before route locking, just as the private
    # registry does. A later identity upgrade cannot rewrite an accepted route.
    gpt=ProviderContract(schema_version='1.0',provider_id='fake-gpt',
        identity=dict(adapter='fake',model_id='fixture-gpt',family='gpt',connection_id='fake-gpt'),
        identity_status='verified',identity_source='fixture:fake',connection_version='test-only')
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("UPDATE provider_profiles SET identity_status='verified',identity_source=?,provider_json=? WHERE id='fake-gpt'",
            (gpt.identity_source,gpt.model_dump_json()))
    accepted=client.post(f'/v1/conversations/{cid}/turns',json=dict(text='Keep the original file.',
        domain='document',provider_profile_id='fake-gpt',client_request_id='gpt-files',
        profile_inputs=dict(audience='Reader',purpose='Preserve the original file',
            source_refs=['input/user_request.txt'],formats=['markdown']))).json()
    task=accepted['task_id']
    with closing(client.app.state.database.connect()) as connection:
        attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
    svc,manager,b,a,workflow=assembly(client,task,attempt)
    runtime=FakeClaudePlanner(); runtime.provider=gpt; a.provider=gpt; workflow.profile_ids['A']='fake-gpt'
    planner=NativeTaskPlanner(svc.database_path,manager,runtime,allow_fixture=True,estimated_tokens=24,
        input_pipeline=InputPipeline(svc))
    binding=build_native_backend(planner,NativeTaskExecutor(workflow),allow_fixture=True,
        provider_registry={'fake-gpt':runtime,'fake-glm':b})
    supervisor=TaskSupervisor(svc.database_path,binding,provider_mode='fake'); supervisor.register_profiles()
    card=asyncio.run(supervisor.run_once())
    assert isinstance(card,dict),card
    assert len(card['artifacts'])==1 and card['format_pairs']==[]
    assert svc.translator.calls==svc.checker.calls==[]
    with closing(svc.database.connect()) as connection:
        assert connection.execute('SELECT count(*) FROM translation_jobs WHERE task_id=?',(task,)).fetchone()[0]==0
