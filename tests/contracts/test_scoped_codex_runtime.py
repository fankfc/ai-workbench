"""Local protocol peers exercise real owned Jobs; no external model is invoked."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

from app.contracts.providers import ProviderContract
from app.providers.phase_bridge import PhaseCapture, PhaseStarted
from app.providers.scoped_codex_runtime import ScopedCodexError, ScopedCodexRuntime, NativePrivateProcess
from app.providers import scoped_codex_worker as worker


def selected():
    return ProviderContract.model_validate(dict(schema_version='1.0', provider_id='private-fixture',
        identity=dict(adapter='codex', model_id='gpt-fixture', family='gpt', connection_id='fixture-connection'),
        identity_status='verified', identity_source='synthetic_protocol_fixture', connection_version='fixture-v1'))


SCHEMA = {'type': 'object', 'properties': {key: {'type': 'number'} for key in ('count', 'sum', 'mean')},
          'required': ['count', 'sum', 'mean'], 'additionalProperties': False}


PEER = r'''
import json,sys,time,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import scoped_codex_worker as w
scenario=sys.argv[2]
def emit(v): print(json.dumps(v),flush=True)
def trace(kind, rid='resp_fixture', model='gpt-fixture'):
    response={'id':rid,'object':'response','status':'completed'}
    if model is not None: response['model']=model
    data={'type':kind,'response':response}
    print(json.dumps({'target':'codex_api::sse::responses','level':'TRACE','fields':{'message':'SSE event: '+json.dumps(data)}}),file=sys.stderr,flush=True)
def config():
    result={'mcp_servers':{'fixture.private':{'enabled':False}},'model_provider':w.ROUTE,'model':'gpt-fixture'}
    for path,value in w.CONTROLS.items():
        node=result
        bits=path.split('.')
        for bit in bits[:-1]: node=node.setdefault(bit,{})
        node[bits[-1]]=value
    if scenario=='agents_enabled': result['agents']['enabled']=True
    if scenario=='missing_control': del result['notify']
    return result
def thread(): return {'id':'thread_fixture','ephemeral':True,'environments':[], 'turns':[]}
for line in sys.stdin:
    frame=json.loads(line); method=frame.get('method'); ident=frame.get('id')
    if method=='initialized': continue
    result={}
    if method=='config/read': result={'config':config()}
    elif method=='thread/start': result={'thread':thread(),'approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False}}
    elif method=='thread/read':
        result={'thread':thread()}
        if scenario=='nonempty_environment': result['thread']['environments']=[{'id':'host'}]
    elif method=='turn/start':
        Path('fixture-turns.txt').open('a').write('1\n')
        emit({'id':ident,'result':{'turn':{'id':'turn_fixture','status':'inProgress'}}})
        if scenario=='accepted_disconnect': sys.exit(0)
        if scenario=='hang': time.sleep(30); continue
        if scenario=='callback': emit({'id':900,'method':'item/commandExecution/requestApproval','params':{'private':'sk-canary'}}); continue
        if scenario=='foreign': emit({'method':'turn/started','params':{'threadId':'foreign','turn':{'id':'turn_fixture'}}}); continue
        if scenario=='tool': emit({'method':'item/started','params':{'threadId':'thread_fixture','turnId':'turn_fixture','item':{'id':'tool1','type':'commandExecution','command':'PRIVATE_CANARY'}}}); continue
        if scenario=='environment_change': emit({'method':'thread/permissions/updated','params':{'threadId':'thread_fixture'}}); continue
        emit({'method':'turn/started','params':{'threadId':'thread_fixture','turn':{'id':'turn_fixture'}}})
        trace('response.created')
        if scenario=='overflow': print('x'*3000000,file=sys.stderr,flush=True); time.sleep(1); continue
        model=None if scenario in ('missing_model','request_echo') else 'wrong-model' if scenario=='wrong_model' else 'gpt-fixture'
        if scenario=='request_echo':
            print(json.dumps({'target':'codex_api::sse::responses','level':'TRACE','fields':{'message':'SSE event: '+json.dumps({'type':'response.completed','request':{'model':'gpt-fixture'},'response':{'id':'resp_fixture','status':'completed'}})}}),file=sys.stderr,flush=True)
        else: trace('response.completed',model=model)
        if scenario=='multiple_response': trace('response.completed',rid='resp_second')
        emit({'method':'rawResponse/completed','params':{'threadId':'thread_fixture','turnId':'turn_fixture','responseId':'resp_fixture','usage':{'inputTokens':30,'outputTokens':3,'totalTokens':33,'reasoningOutputTokens':1}}})
        if scenario=='multiple_receipt': emit({'method':'rawResponse/completed','params':{'threadId':'thread_fixture','turnId':'turn_fixture','responseId':'resp_fixture','usage':{'inputTokens':30,'outputTokens':3}}})
        emit({'method':'thread/tokenUsage/updated','params':{'threadId':'thread_fixture','turnId':'turn_fixture','tokenUsage':{'total':{'inputTokens':300,'outputTokens':30,'totalTokens':330}}}})
        answer='not valid JSON' if scenario=='invalid_json' else '{"count":"three","sum":6,"mean":2}' if scenario=='invalid_schema' else '{"count":3,"sum":6,"mean":2}'
        emit({'method':'item/completed','params':{'threadId':'thread_fixture','turnId':'turn_fixture','item':{'id':'answer1','type':'agentMessage','text':answer}}})
        emit({'method':'turn/completed','params':{'threadId':'thread_fixture','turn':{'id':'turn_fixture','status':'completed','error':None}}})
        continue
    elif method=='turn/interrupt': result={}
    elif method=='thread/unsubscribe':
        emit({'id':ident,'result':{}})
        if scenario=='trailing_error': emit({'method':'error','params':{'message':'PRIVATE_CANARY'}})
        continue
    emit({'id':ident,'result':result})
'''


@pytest.fixture
def factory(tmp_path):
    path = tmp_path/'local_peer.py'
    path.write_text(PEER, encoding='utf-8')
    def create(scenario='pass', **options):
        return ScopedCodexRuntime(selected(), ledger_path=tmp_path/'leases.sqlite3',
            workspace_root=tmp_path, entry_manifest=tmp_path/'never-read-native-manifest.json',
            worker_factory=lambda: [sys._base_executable, str(path), str(Path(worker.__file__).parent), scenario],
            **options)
    return create


async def invoke(runtime):
    return [event async for event in runtime.invoke_text('Return JSON arithmetic for 1,2,3.',
        task_id='task', attempt_id='attempt', request_id='local_request', phase='planning',
        workspace=runtime.workspace_root, output_schema=SCHEMA)]


def test_canonical_v2_includes_real_agent_override():
    assert len(worker.CONTROLS) == 22
    assert worker.CONTROLS['agents.enabled'] is False


def test_fixture_preparation_does_not_issue_production_capability(factory):
    runtime = factory()
    try:
        preparation = asyncio.run(runtime.prepare())
        assert preparation.controls_verified and preparation.control_count == 22
        assert preparation.transport_kind == 'fixture'
        assert not preparation.production_qualified
        with pytest.raises(ScopedCodexError, match='FIXTURE_SCOPE_NOT_PRODUCTION'):
            runtime.scope_capability.require_verified(selected())
    finally:
        runtime.close()
    assert runtime.last_cleanup.cleanup_complete


def test_real_local_peer_start_capture_hash_usage_and_cleanup(factory):
    runtime = factory()
    events = asyncio.run(invoke(runtime))
    assert len(events) == 2 and isinstance(events[0], PhaseStarted) and isinstance(events[1], PhaseCapture)
    assert (events[0].external_request_id, events[0].external_execution_id) == ('resp_fixture', 'turn_fixture')
    assert json.loads(events[1].final_text) == {'count':3,'sum':6,'mean':2}
    assert events[1].observed_provider == selected()
    assert len(events[1].usage_receipts) == 1
    assert events[1].usage_receipts[0].raw['total_tokens'] == 33
    assert events[1].usage_receipts[0].mode == 'request_total'
    assert runtime.last_capture_sha256 == hashlib.sha256(events[1].final_text.encode()).hexdigest()
    assert runtime.last_cleanup.cleanup_complete and runtime.last_cleanup.open_handles == 0
    assert runtime.last_cleanup.remote_state == 'unknown'
    runtime.close()


@pytest.mark.parametrize('scenario', ['agents_enabled','missing_control','nonempty_environment'])
def test_scope_counterexamples_stop_before_model_submission(factory, scenario):
    runtime = factory(scenario)
    with pytest.raises(ScopedCodexError): asyncio.run(invoke(runtime))
    assert runtime.diagnostics['submitted_model_turns'] == 0
    assert not (runtime.workspace_root/'fixture-turns.txt').exists()
    assert runtime.last_cleanup.cleanup_complete
    runtime.close()


@pytest.mark.parametrize('scenario', ['missing_model','request_echo','wrong_model','multiple_response',
    'multiple_receipt','foreign','tool','callback','environment_change','trailing_error'])
def test_untrusted_or_ambiguous_capture_never_yields_final(factory, scenario):
    runtime = factory(scenario)
    captured=[]
    async def collect():
        async for event in runtime.invoke_text('fixed',task_id='task',attempt_id='attempt',request_id='local_request',
            phase='planning',workspace=runtime.workspace_root,output_schema=SCHEMA): captured.append(event)
    with pytest.raises(ScopedCodexError): asyncio.run(collect())
    assert not any(isinstance(item,PhaseCapture) for item in captured)
    assert runtime.last_cleanup.cleanup_complete
    assert 'PRIVATE_CANARY' not in repr(runtime.diagnostics)
    runtime.close()


def test_accepted_disconnect_is_observed_once_and_never_retried(factory):
    runtime=factory('accepted_disconnect'); events=[]
    async def collect():
        async for event in runtime.invoke_text('fixed',task_id='task',attempt_id='attempt',request_id='local_request',
            phase='planning',workspace=runtime.workspace_root,output_schema=SCHEMA): events.append(event)
    with pytest.raises(ScopedCodexError,match='UNKNOWN_REMOTE'): asyncio.run(collect())
    assert events == [PhaseStarted('local_request',None,'turn_fixture')]
    assert runtime.diagnostics['submitted_model_turns']==1
    with pytest.raises(ScopedCodexError,match='REQUEST_ALREADY_USED'): asyncio.run(invoke(runtime))
    assert (runtime.workspace_root/'fixture-turns.txt').read_text().splitlines()==['1']
    runtime.close()


def test_inflight_cancel_is_timely_owned_local_cleanup(factory):
    runtime=factory('hang',timeout_seconds=15)
    async def run():
        task=asyncio.create_task(invoke(runtime))
        deadline=time.monotonic()+6
        while runtime.diagnostics['submitted_model_turns']==0 and time.monotonic()<deadline: await asyncio.sleep(.01)
        started=time.monotonic(); cleanup=await runtime.cancel('task','attempt')
        assert time.monotonic()-started<3
        assert cleanup.cleanup_complete and cleanup.remote_state=='unknown' and cleanup.open_handles==0
        with pytest.raises(ScopedCodexError): await task
        assert (await runtime.cancel('task','attempt'))==cleanup
    asyncio.run(run()); runtime.close()


def test_output_overflow_and_timeout_are_bounded(factory):
    runtime=factory('overflow',max_output_bytes=32768,timeout_seconds=12)
    started=time.monotonic()
    with pytest.raises(ScopedCodexError,match='OUTPUT_LIMIT'): asyncio.run(invoke(runtime))
    assert time.monotonic()-started<4
    assert runtime.last_cleanup.cleanup_complete
    runtime.close()
    runtime=factory('hang',timeout_seconds=.7)
    with pytest.raises(ScopedCodexError): asyncio.run(invoke(runtime))
    assert runtime.last_cleanup.cleanup_complete
    runtime.close()


def test_missing_native_lifetime_blocks_without_reading_manifest_or_starting(tmp_path):
    runtime=ScopedCodexRuntime(selected(),ledger_path=tmp_path/'leases.sqlite3',workspace_root=tmp_path,
        entry_manifest=tmp_path/'absent.json')
    with pytest.raises(ScopedCodexError,match='LIFETIME_ENFORCER_MISSING'): asyncio.run(invoke(runtime))
    assert runtime.diagnostics['submitted_model_turns']==0 and not runtime.ledger_path.exists()
    assert runtime.last_cleanup.local_state=='not_started'
    with pytest.raises(ScopedCodexError,match='EXECUTED_MODEL_IDENTITY_UNKNOWN'): asyncio.run(runtime.probe())
    runtime.close()


def test_completed_steps_can_follow_but_unknown_remote_blocks_new_request_across_restart(factory):
    runtime=factory()
    asyncio.run(invoke(runtime))
    async def second(current):
        return [event async for event in current.invoke_text('fixed',task_id='task',attempt_id='attempt',request_id='second',
            phase='finalization',workspace=current.workspace_root,output_schema=SCHEMA)]
    assert isinstance(asyncio.run(second(runtime))[-1],PhaseCapture)
    runtime.close()
    runtime=factory('accepted_disconnect')
    with pytest.raises(ScopedCodexError,match='UNKNOWN_REMOTE'):
        asyncio.run(runtime_run(runtime,'third'))
    runtime.close()
    runtime=factory()
    with pytest.raises(ScopedCodexError,match='UNKNOWN_REMOTE_UNRESOLVED'):
        asyncio.run(runtime_run(runtime,'fourth'))
    assert (runtime.workspace_root/'fixture-turns.txt').read_text().splitlines()==['1','1','1']
    runtime.close()


async def runtime_run(runtime,request_id):
    return [event async for event in runtime.invoke_text('fixed',task_id='task',attempt_id='attempt',request_id=request_id,
        phase='planning',workspace=runtime.workspace_root,output_schema=SCHEMA)]


def test_external_schema_reference_is_rejected_before_peer_start(factory):
    runtime=factory()
    async def collect():
        return [event async for event in runtime.invoke_text('fixed',task_id='task',attempt_id='attempt',request_id='invalid',
            phase='planning',workspace=runtime.workspace_root,output_schema={'$ref':'https://example.invalid/private'})]
    with pytest.raises(ScopedCodexError,match='OUTPUT_SCHEMA_INVALID'): asyncio.run(collect())
    assert runtime.diagnostics['submitted_model_turns']==0 and not runtime.ledger_path.exists()
    runtime.close()


def test_workspace_symlink_inside_scope_is_rejected_before_start(factory):
    runtime=factory()
    actual=runtime.workspace_root/'actual'; actual.mkdir()
    alias=runtime.workspace_root/'alias'
    try: alias.symlink_to(actual,target_is_directory=True)
    except OSError: pytest.skip('Windows symlink creation unavailable')
    async def collect():
        return [event async for event in runtime.invoke_text('fixed',task_id='task',attempt_id='attempt',request_id='linked',
            phase='planning',workspace=alias,output_schema=SCHEMA)]
    with pytest.raises(ScopedCodexError,match='WORKSPACE_REPARSE_FORBIDDEN'): asyncio.run(collect())
    assert runtime.diagnostics['submitted_model_turns']==0
    runtime.close()


def test_shared_private_process_uses_anonymous_stdin_native_argv_and_owned_cleanup(tmp_path):
    program=tmp_path/'echo.py'
    program.write_text("import json,sys\nx=json.loads(sys.stdin.readline())\nprint(json.dumps({'argv':sys.argv[1:],'input':x}),flush=True)\n",encoding='utf-8')
    args=['space argument','& echo PRIVATE_COMMAND > injected.txt','$(whoami)','a;b']
    process=NativePrivateProcess(tmp_path/'lease.sqlite3')
    process.start('task','attempt',[sys._base_executable,str(program),*args],tmp_path,step_id='pipe')
    process.write_json({'private':'test-value'})
    deadline=time.monotonic()+4
    while process.poll() is None and time.monotonic()<deadline: time.sleep(.01)
    assert json.loads(process.stdout)=={'argv':args,'input':{'private':'test-value'}}
    assert not (tmp_path/'injected.txt').exists()
    cleanup=process.close()
    assert cleanup.cleanup_complete and cleanup.open_handles==0 and cleanup.remote_state=='unknown'
    assert process.close()==cleanup
    with pytest.raises(ScopedCodexError,match='PRIVATE_PROCESS_ALREADY_STARTED'):
        process.start('task','attempt',[sys._base_executable,str(program)],tmp_path,step_id='other')


def test_real_enforcer_consumes_actual_fixture_controls_but_never_grants_production(factory):
    from app.providers.native_scope import NativeScopeEnforcer,FixtureScopeSeal
    enforcer=NativeScopeEnforcer()
    runtime=factory(lifetime_enforcer=enforcer)
    preparation=asyncio.run(runtime.prepare())
    assert preparation.controls_verified and not preparation.production_qualified
    assert isinstance(enforcer._seal,FixtureScopeSeal)
    assert runtime.last_cleanup.cleanup_complete
    with pytest.raises(ScopedCodexError,match='FIXTURE_SCOPE_NOT_PRODUCTION'):
        runtime.scope_capability.require_verified(selected())
    assert isinstance(asyncio.run(invoke(runtime))[-1],PhaseCapture)
    assert runtime.last_cleanup.cleanup_complete
    assert runtime.classification=='fixture'
    runtime.close()


@pytest.mark.parametrize('scenario',['invalid_json','invalid_schema'])
def test_authenticated_completion_retains_actual_usage_before_business_validation(factory,scenario):
    runtime=factory(scenario)
    events=asyncio.run(invoke(runtime))
    assert isinstance(events[-1],PhaseCapture)
    assert events[-1].usage_receipts[0].raw['total_tokens']==33
    assert events[-1].final_text==('not valid JSON' if scenario=='invalid_json' else '{"count":"three","sum":6,"mean":2}')
    assert runtime.last_cleanup.cleanup_complete
    runtime.close()
