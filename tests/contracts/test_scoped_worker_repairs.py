"""Worker repair schedules use local Python peers; no native CLI or model starts."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.providers import scoped_codex_worker as worker
from app.providers.native_scope import NativeScopeEnforcer
from app.providers.phase_bridge import PhaseCapture, PhaseStarted, PhaseUsage
from app.providers.scoped_codex_runtime import ScopedCodexError, ScopedCodexRuntime


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('worker_repair_peer_support',
    Path(__file__).with_name('test_scoped_codex_runtime.py'))
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)


def peer_source():
    source = SUPPORT.PEER.replace(
        "elif method=='thread/start': result={'thread':thread(),'approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False}}",
        "elif method=='thread/start':\n"
        "        result={'thread':thread(),'approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False},'model':'gpt-fixture','modelProvider':w.ROUTE}\n"
        "        if scenario=='changed_thread_model': result['model']='gpt-foreign'\n"
        "        if scenario=='changed_thread_provider': result['modelProvider']='foreign-route'\n"
        "        if scenario=='unsafe_thread_model': result['model']='sk-PRIVATE_CANARY'\n"
        "        if scenario=='unsafe_thread_provider': result['modelProvider']='Bearer PRIVATE_CANARY'")
    source = source.replace(
        "emit({'method':'turn/completed','params':{'threadId':'thread_fixture','turn':{'id':'turn_fixture','status':'completed','error':None}}})",
        "if scenario in ('error_before_turn_completed','delayed_failure_identity'):\n"
        "            emit({'method':'error','params':{'threadId':'thread_fixture','turnId':'turn_fixture','message':'PRIVATE_CANARY'}})\n"
        "            continue\n"
        "        emit({'method':'turn/completed','params':{'threadId':'thread_fixture','turn':{'id':'turn_fixture','status':'completed','error':None}}})")
    source = source.replace(
        "if scenario=='trailing_error': emit({'method':'error','params':{'message':'PRIVATE_CANARY'}})",
        "if scenario=='trailing_duplicate_sse': trace('response.completed')\n"
        "        if scenario=='trailing_bad_sse': trace('response.completed',model='sk-PRIVATE_CANARY')\n"
        "        if scenario=='trailing_duplicate_receipt': emit({'method':'rawResponse/completed','params':{'threadId':'thread_fixture','turnId':'turn_fixture','responseId':'resp_fixture','usage':{'inputTokens':30,'outputTokens':3}}})\n"
        "        if scenario in ('trailing_error','trailing_duplicate_sse','trailing_bad_sse','trailing_duplicate_receipt'): emit({'method':'error','params':{'message':'PRIVATE_CANARY'}})")
    source = source.replace("trace('response.created')", "if scenario!='delayed_failure_identity': trace('response.created')")
    source = source.replace("else: trace('response.completed',model=model)",
        "elif scenario!='delayed_failure_identity': trace('response.completed',model=model)")
    source = source.replace("elif method=='turn/interrupt': result={}",
        "elif method=='turn/interrupt':\n"
        "        result={}\n"
        "        if scenario=='delayed_failure_identity':\n"
        "            trace('response.created')\n"
        "            trace('response.completed')")
    return source


def local_peer(tmp_path, scenario):
    path = tmp_path/'repair_peer.py'
    path.write_text(peer_source(), encoding='utf-8')
    return [sys._base_executable, str(path), str(Path(worker.__file__).parent), scenario]


def worker_frames(tmp_path, scenario):
    """Run the actual worker, serving its private allow/observed handshake."""
    command = local_peer(tmp_path, scenario)
    text = 'Return JSON arithmetic for 1,2,3.'
    nonce = 'repair_fixture_nonce'
    boot = dict(action='invoke',nonce=nonce,workspace=str(tmp_path),task_id='task',attempt_id='attempt',
        request_id='repair_request',phase='planning',text=text,input_source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        output_schema=SUPPORT.SCHEMA,expected_model='gpt-fixture',transport_kind='fixture',
        timeout_seconds=6,max_output_bytes=2_000_000,fixture_command=command)
    packets = []
    process = subprocess.Popen([sys._base_executable,str(Path(worker.__file__))],cwd=tmp_path,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        def send(frame):
            process.stdin.write(json.dumps(frame).encode()+b'\n')
            process.stdin.flush()
        send(boot)
        for line in process.stdout:
            packet = json.loads(line)
            assert packet['nonce'] == nonce
            packets.append(packet)
            if packet['kind']=='rpc.authorize': send({'nonce':nonce,'allow':True})
            elif packet['kind']=='rpc.observed': send({'nonce':nonce,'observed':True})
        code = process.wait(timeout=4)
        assert process.stderr.read() == b''
        return packets, code
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=4)
        for stream in (process.stdin,process.stdout,process.stderr): stream.close()


@pytest.mark.parametrize('field,value', [('model','gpt-foreign'),('modelProvider','foreign-route')])
def test_thread_projection_preserves_explicit_bounded_model_and_route(field,value):
    result = {'thread':{'id':'thread_fixture','ephemeral':True,'environments':[],'turns':[]},field:value}
    assert worker.thread_projection(result).get(field) == value


@pytest.mark.parametrize('field,value', [('model','sk-PRIVATE_CANARY'),('modelProvider','Bearer PRIVATE_CANARY'),
    ('model',True),('modelProvider','x'*181)])
def test_thread_projection_preserves_invalid_field_presence_without_exporting_private_value(field,value):
    result = {'thread':{'id':'thread_fixture','ephemeral':True,'environments':[]},field:value}
    projected = worker.thread_projection(result)
    assert field in projected and projected[field] is None
    assert 'PRIVATE_CANARY' not in repr(projected)


def test_official_thread_start_schema_requires_top_level_model_and_route():
    schema = json.loads((ROOT/'.tools/gpt-metadata-probe/schemas/v2/ThreadStartResponse.json').read_text())
    assert {'model','modelProvider'} <= set(schema['required'])
    assert all(schema['properties'][field]['type']=='string' for field in ('model','modelProvider'))


@pytest.mark.parametrize('missing', ['model','modelProvider'])
def test_native_thread_start_requires_actual_official_route_fields(missing):
    result = {'thread':{'id':'thread_fixture','ephemeral':True,'environments':[]},
        'model':'gpt-fixture','modelProvider':worker.ROUTE}
    result.pop(missing)
    with pytest.raises(worker.WorkerError,match='THREAD_CONFIGURED_ROUTE_MISSING'):
        worker.thread_projection(result,require_route=True)


@pytest.mark.parametrize('scenario', ['changed_thread_model','changed_thread_provider','unsafe_thread_model','unsafe_thread_provider'])
def test_actual_worker_projection_allows_enforcer_to_deny_route_change_before_submission(tmp_path,scenario):
    runtime = ScopedCodexRuntime(SUPPORT.selected(),ledger_path=tmp_path/'lease.sqlite3',workspace_root=tmp_path,
        entry_manifest=tmp_path/'never-read-manifest.json',worker_factory=lambda:local_peer(tmp_path,scenario),
        lifetime_enforcer=NativeScopeEnforcer())
    captured = []
    async def collect():
        async for event in runtime.invoke_text('fixed',task_id='task',attempt_id='attempt',request_id='repair_request',
            phase='planning',workspace=tmp_path,output_schema=SUPPORT.SCHEMA): captured.append(event)
    try:
        with pytest.raises(ScopedCodexError,match='SCOPE_OBSERVATION_REJECTED'): asyncio.run(collect())
        assert runtime.diagnostics['submitted_model_turns'] == 0
        assert not (tmp_path/'fixture-turns.txt').exists()
        assert not any(isinstance(event,PhaseCapture) for event in captured)
        assert runtime.last_cleanup.cleanup_complete
    finally:
        runtime.close()


@pytest.mark.parametrize('scenario', ['trailing_error','error_before_turn_completed','delayed_failure_identity'])
def test_failure_retains_genuine_bound_usage_without_business_capture(tmp_path,scenario):
    frames, code = worker_frames(tmp_path,scenario)
    assert code == 1
    usages = [frame for frame in frames if frame['kind']=='usage']
    assert len(usages) == 1
    evidence = usages[0]
    assert set(evidence) == {'kind','nonce','external_request_id','external_execution_id','actual_model_id',
        'identity_source','thread_id','usage'}
    assert (evidence['external_request_id'],evidence['external_execution_id'],evidence['thread_id']) == (
        'resp_fixture','turn_fixture','thread_fixture')
    assert evidence['actual_model_id'] == 'gpt-fixture'
    assert evidence['identity_source'] == 'official_response_completed_model'
    assert evidence['usage'] == {'input_tokens':30,'output_tokens':3,'total_tokens':33,'reasoning_output_tokens':1}
    assert not any(frame['kind']=='capture' for frame in frames)
    assert any(frame['kind']=='error' for frame in frames)
    assert 'PRIVATE_CANARY' not in repr(frames)
    assert (tmp_path/'fixture-turns.txt').read_text().splitlines() == ['1']


def test_runtime_retains_late_failure_identity_with_one_stable_start_and_bound_usage(tmp_path):
    runtime = ScopedCodexRuntime(SUPPORT.selected(), ledger_path=tmp_path/'lease.sqlite3', workspace_root=tmp_path,
        entry_manifest=tmp_path/'never-read-manifest.json', worker_factory=lambda:local_peer(tmp_path,'delayed_failure_identity'),
        lifetime_enforcer=NativeScopeEnforcer())
    events = []
    async def collect():
        async for event in runtime.invoke_text('fixed', task_id='task', attempt_id='attempt', request_id='repair_request',
            phase='planning', workspace=tmp_path, output_schema=SUPPORT.SCHEMA):
            events.append(event)
    try:
        with pytest.raises(ScopedCodexError, match='UNSUPPORTED_EXECUTION_NOTIFICATION'):
            asyncio.run(collect())
        starts = [event for event in events if isinstance(event, PhaseStarted)]
        usages = [event for event in events if isinstance(event, PhaseUsage)]
        assert len(starts) == len(usages) == 1
        assert starts[0].external_request_id == usages[0].external_request_id == 'resp_fixture'
        assert starts[0].external_execution_id == usages[0].external_execution_id == 'turn_fixture'
        assert usages[0].usage_receipts[0].raw['total_tokens'] == 33
        assert not any(isinstance(event, PhaseCapture) for event in events)
        assert runtime.diagnostics['submitted_model_turns'] == 1 and runtime.last_cleanup.cleanup_complete
    finally:
        runtime.close()


@pytest.mark.parametrize('damage', [None, 'duplicate_sse', 'duplicate_receipt', 'foreign_receipt',
    'wrong_model', 'missing_created', 'missing_completion', 'output_limit', 'readers_pending'])
def test_failure_drain_binds_delayed_identity_without_accepting_ambiguous_usage(tmp_path, damage):
    """The stdout error can arrive before the independent stderr reader runs."""
    value = worker.Worker(dict(action='invoke', timeout_seconds=6, max_output_bytes=2_000_000,
        nonce='delayed_identity_fixture', expected_model='gpt-fixture'))
    packets = []
    value.emit = lambda kind, **fields: packets.append(dict(kind=kind, **fields))
    peer = worker.PipePeer([], tmp_path, time.monotonic()+6, 2_000_000, lambda *_: None, 'restricted')
    value.peer = peer
    peer.notifications = value.notification
    value.thread_id, value.turn_id = 'thread_fixture', 'turn_fixture'
    value.submitted = value.accepted = True
    receipt = dict(method='rawResponse/completed', params=dict(threadId=value.thread_id,
        turnId=value.turn_id, responseId='resp_fixture', usage=dict(inputTokens=30, outputTokens=3,
            totalTokens=33, reasoningOutputTokens=1)))
    value.notification(receipt['method'], receipt['params'])
    def trace(kind, model='gpt-fixture'):
        event = dict(type=kind, response=dict(id='resp_fixture', object='response', status='completed', model=model))
        return json.dumps(dict(target='codex_api::sse::responses', level='TRACE',
            fields=dict(message='SSE event: '+json.dumps(event)))).encode()
    delayed = []
    if damage != 'missing_created':
        delayed.append(('stderr', trace('response.created')))
    if damage != 'missing_completion':
        delayed.append(('stderr', trace('response.completed', 'foreign-model' if damage=='wrong_model' else 'gpt-fixture')))
    if damage == 'duplicate_sse':
        delayed.append(('stderr', trace('response.completed')))
    if damage in ('duplicate_receipt', 'foreign_receipt'):
        if damage == 'foreign_receipt':
            receipt['params']['threadId'] = 'foreign_thread'
        delayed.append(('stdout', json.dumps(receipt).encode()))
    if damage == 'output_limit':
        delayed.append(('error', 'OUTPUT_LIMIT'))
    if damage == 'readers_pending':
        peer.readers.append(SimpleNamespace(is_alive=lambda: True))
    def finish_readers():
        while delayed:
            peer.frames.put(delayed.pop(0))
    peer.close = finish_readers
    peer.call = lambda *_: {}
    value.observed = lambda *_: None
    value.prepare = lambda: []
    value.invoke = lambda _: peer.pump(wait=0)
    peer.frames.put(('stdout', json.dumps(dict(method='error', params=dict(threadId=value.thread_id,
        turnId=value.turn_id, message='PRIVATE_CANARY'))).encode()))
    assert value.run() == 1
    usages = [packet for packet in packets if packet['kind']=='usage']
    assert len(usages) == (1 if damage is None else 0)
    if usages:
        starts = [packet for packet in packets if packet['kind']=='started']
        assert len(starts) == 1
        assert starts[0]['external_request_id'] == usages[0]['external_request_id'] == 'resp_fixture'
        assert starts[0]['external_execution_id'] == usages[0]['external_execution_id'] == 'turn_fixture'
        assert usages[0]['actual_model_id'] == 'gpt-fixture'
        assert usages[0]['usage']['total_tokens'] == 33
    assert not any(packet['kind']=='capture' for packet in packets)
    assert 'PRIVATE_CANARY' not in repr(packets)


@pytest.mark.parametrize('scenario', ['missing_model','request_echo','wrong_model','multiple_response','multiple_receipt',
    'accepted_disconnect','foreign','trailing_duplicate_sse','trailing_bad_sse','trailing_duplicate_receipt'])
def test_failure_with_missing_or_ambiguous_identity_or_receipt_emits_no_usage(tmp_path,scenario):
    frames, code = worker_frames(tmp_path,scenario)
    assert code == 1
    assert not any(frame['kind'] in ('usage','capture') for frame in frames)
    assert 'PRIVATE_CANARY' not in repr(frames)


def test_normal_success_has_one_capture_receipt_and_no_separate_usage(tmp_path):
    frames, code = worker_frames(tmp_path,'pass')
    assert code == 0
    assert not any(frame['kind']=='usage' for frame in frames)
    captures = [frame for frame in frames if frame['kind']=='capture']
    assert len(captures) == 1 and captures[0]['usage']['total_tokens'] == 33


def test_final_worker_source_matches_the_fixed_enforcer_pin():
    from app.providers import native_scope
    actual = hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest()
    assert native_scope.WORKER_SOURCE_SHA256 == actual
    assert native_scope.SOURCE_POLICY_MANIFEST['worker_source_sha256'] == actual
