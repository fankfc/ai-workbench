"""Synthetic codec/call schedules; no CLI, model, auth or OS-scope claim."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.providers.native_scope import (
    CONTROL_POLICY, CONTROL_POLICY_SHA256, OFFICIAL_ENTRY_SHA256,
    FixtureScopeSeal, NativePhaseBinding, NativeScopeEnforcer, NativeScopeError,
)


CONTROLS = {
    'features.shell_tool': False, 'features.view_image': False,
    'features.code_mode': False, 'features.code_mode_only': False,
    'features.code_mode_host.enabled': False,
    'features.code_mode_host.disable_in_process_fallback': False,
    'features.multi_agent': False, 'features.multi_agent_v2': False,
    'agents.enabled': False, 'features.apps': False, 'features.plugins': False,
    'features.tool_suggest': False, 'features.recommended_plugins': False,
    'features.memories': False, 'memories.use_memories': False,
    'cloud.skills.enabled': False, 'features.image_generation': False,
    'web_search': 'disabled', 'features.hooks': False, 'notify': [],
    'features.deferred_executor': False, 'features.request_permissions_tool': False,
}


def binding(tmp_path, **changes):
    text = '{"task":"inline approved content"}'
    return NativePhaseBinding(**dict(task_id='task1', attempt_id='attempt1', request_id='request1',
        phase='review', workspace=tmp_path, input_text=text,
        input_source_sha256=hashlib.sha256(text.encode()).hexdigest(), **changes))


def configuration():
    return {'controls': copy.deepcopy(CONTROLS), 'mcp_servers': {'private.example.name': {'enabled': False}},
        'configured_provider_id': 'workbench_scoped_chatgpt_http', 'configured_model_id': 'gpt-6.1-sol'}


def initialize(enforcer, context):
    enforcer.authorize_rpc('initialize', {'clientInfo': {'name': 'workbench_scoped_runtime',
        'title': 'Scoped native runtime', 'version': '0.1.0'}, 'capabilities': {'experimentalApi': True}}, context)
    enforcer.observe_rpc_response('initialize', {}, context)
    enforcer.authorize_rpc('initialized', {}, context)


def start_params(tmp_path):
    return {'cwd': str(tmp_path), 'model': 'gpt-6.1-sol', 'modelProvider': 'workbench_scoped_chatgpt_http',
        'allowProviderModelFallback': False, 'approvalPolicy': 'never', 'sandbox': 'read-only',
        'ephemeral': True, 'environments': [], 'dynamicTools': [], 'experimentalRawEvents': True}


def thread_result(ident='owned-thread'):
    return {'thread': {'id': ident, 'ephemeral': True, 'environments': []},
        'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly', 'networkAccess': False}}


def prepared(tmp_path):
    enforcer = NativeScopeEnforcer()
    context = enforcer.open_fixture_phase(binding(tmp_path))
    initialize(enforcer, context)
    enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
    enforcer.observe_rpc_response('config/read', configuration(), context)
    enforcer.authorize_rpc('thread/start', start_params(tmp_path), context)
    enforcer.observe_rpc_response('thread/start', thread_result(), context)
    enforcer.authorize_rpc('thread/read', {'threadId': 'owned-thread', 'includeTurns': False}, context)
    enforcer.observe_rpc_response('thread/read', thread_result(), context)
    return enforcer, context


def turn_params(tmp_path):
    return {'threadId': 'owned-thread', 'cwd': str(tmp_path), 'model': 'gpt-6.1-sol',
        'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False},
        'effort': 'low', 'environments': [], 'input': [{'type': 'text', 'text': binding(tmp_path).input_text, 'text_elements': []}],
        'outputSchema': {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'additionalProperties': False}}


@pytest.mark.parametrize('method', ['config/value/write', 'config/batchWrite', 'mcpServer/refresh',
    'account/login/start', 'plugin/install', 'environment/add', 'command/exec', 'process/exec',
    'thread/fork', 'item/tool/call', 'turn/steer', 'unknown/canary'])
def test_config_mutation_and_unsafe_methods_never_reach_transport(tmp_path, method):
    enforcer, context = prepared(tmp_path)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc(method, {}, context)


def test_fixture_codec_never_qualifies_production(tmp_path):
    enforcer, context = prepared(tmp_path)
    assert isinstance(enforcer.scope_seal(context), FixtureScopeSeal)
    with pytest.raises(NativeScopeError, match='FIXTURE'):
        enforcer.require_verified(OFFICIAL_ENTRY_SHA256, CONTROL_POLICY_SHA256)


@pytest.mark.parametrize('field', list(CONTROLS))
def test_every_actual_control_is_required_not_a_claim_boolean(tmp_path, field):
    enforcer = NativeScopeEnforcer()
    context = enforcer.open_fixture_phase(binding(tmp_path))
    initialize(enforcer, context)
    enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
    result = configuration()
    result['controls'].pop(field)
    result['controls_verified'] = True
    with pytest.raises(NativeScopeError):
        enforcer.observe_rpc_response('config/read', result, context)


@pytest.mark.parametrize('replacement', [True, 0, None, 'false'])
def test_mcp_enabled_requires_the_actual_false_boolean(tmp_path, replacement):
    enforcer = NativeScopeEnforcer()
    context = enforcer.open_fixture_phase(binding(tmp_path))
    initialize(enforcer, context)
    enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
    result = configuration()
    result['mcp_servers']['private.example.name']['enabled'] = replacement
    with pytest.raises(NativeScopeError):
        enforcer.observe_rpc_response('config/read', result, context)


@pytest.mark.parametrize('change', [dict(ephemeral=False), dict(environments=[{'id': 'foreign'}]),
    dict(dynamicTools=[{'name': 'file_read'}]), dict(sandbox='danger-full-access'),
    dict(approvalPolicy='on-request'), dict(allowProviderModelFallback=True), dict(extra='CANARY')])
def test_thread_cannot_expand_environment_permission_or_tools(tmp_path, change):
    enforcer = NativeScopeEnforcer()
    context = enforcer.open_fixture_phase(binding(tmp_path))
    initialize(enforcer, context)
    enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
    enforcer.observe_rpc_response('config/read', configuration(), context)
    params = start_params(tmp_path)
    params.update(change)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('thread/start', params, context)


@pytest.mark.parametrize('change', [dict(cwd='C:/outside'), dict(threadId='foreign'),
    dict(input=[{'type': 'localImage', 'path': 'C:/private.png'}]),
    dict(input=[{'type': 'text', 'text': 'changed', 'text_elements': []}]),
    dict(sandboxPolicy={'type': 'readOnly', 'networkAccess': True}), dict(environments=[{'id': 'foreign'}]),
    dict(dynamicTools=[]), dict(model='gpt-foreign')])
def test_turn_is_owned_sticky_readonly_and_exact_text_only(tmp_path, change):
    enforcer, context = prepared(tmp_path)
    params = turn_params(tmp_path)
    params.update(change)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', params, context)


def test_second_top_level_turn_cannot_start(tmp_path):
    enforcer, context = prepared(tmp_path)
    enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)
    enforcer.observe_rpc_response('turn/start', {'turn': {'id': 'owned-turn', 'status': 'inProgress'}}, context)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)


def test_foreign_context_and_json_receipt_cannot_mint_scope(tmp_path):
    first, context = prepared(tmp_path)
    second = NativeScopeEnforcer()
    with pytest.raises(NativeScopeError):
        second.authorize_rpc('turn/start', turn_params(tmp_path), context)
    with pytest.raises(NativeScopeError):
        first.authorize_rpc('turn/start', turn_params(tmp_path), {'prepared_receipt': {'verified': True}})


def test_unprepared_or_unsolicited_metadata_is_rejected(tmp_path):
    enforcer = NativeScopeEnforcer()
    context = enforcer.open_fixture_phase(binding(tmp_path))
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)
    with pytest.raises(NativeScopeError):
        enforcer.observe_rpc_response('thread/read', thread_result(), context)


def test_unknown_cleanup_revokes_an_existing_prepared_context(tmp_path):
    enforcer, context = prepared(tmp_path)
    enforcer.close(context, cleanup_complete=None)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)


def test_native_pipe_authority_is_not_a_transport_kind_or_bool(tmp_path):
    enforcer = NativeScopeEnforcer()
    with pytest.raises(NativeScopeError):
        enforcer.bind_native_phase({'transport_kind': 'native', 'job_verified': True},
            {'pid': 123, 'scope_enforced': True}, binding(tmp_path), Path('claimed.exe'))


@pytest.mark.parametrize('entry_hash,policy_hash', [('0' * 64, CONTROL_POLICY_SHA256),
    (OFFICIAL_ENTRY_SHA256, '0' * 64)])
def test_unpinned_source_or_entry_cannot_authorize(entry_hash, policy_hash):
    with pytest.raises(NativeScopeError):
        NativeScopeEnforcer().require_verified(entry_hash, policy_hash)


def test_control_policy_records_the_model_metadata_override_ceiling():
    assert CONTROL_POLICY.get('controls', {}).get('agents.enabled') is False


def test_forbidden_request_permanently_revokes_prepared_qualification(tmp_path):
    enforcer, context = prepared(tmp_path)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('config/value/write', {}, context)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)


def test_unsubscribe_cannot_be_followed_by_a_model_start(tmp_path):
    enforcer, context = prepared(tmp_path)
    enforcer.authorize_rpc('thread/unsubscribe', {'threadId': 'owned-thread'}, context)
    enforcer.observe_rpc_response('thread/unsubscribe', {}, context)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)


@pytest.mark.parametrize('changed', [dict(approvalPolicy='on-request'),
    dict(sandbox={'type': 'readOnly', 'networkAccess': True})])
def test_thread_read_cannot_discard_an_explicit_changed_policy(tmp_path, changed):
    enforcer, context = prepared(tmp_path)
    enforcer.authorize_rpc('thread/read', {'threadId': 'owned-thread', 'includeTurns': False}, context)
    result = thread_result()
    result.update(changed)
    with pytest.raises(NativeScopeError):
        enforcer.observe_rpc_response('thread/read', result, context)


def test_config_recheck_must_be_followed_by_thread_recheck_before_turn(tmp_path):
    enforcer, context = prepared(tmp_path)
    enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
    enforcer.observe_rpc_response('config/read', configuration(), context)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)


def test_successful_cleanup_permits_fresh_context_but_never_old_rpc(tmp_path):
    enforcer, context = prepared(tmp_path)
    enforcer.close(context, cleanup_complete=True)
    with pytest.raises(NativeScopeError):
        enforcer.authorize_rpc('turn/start', turn_params(tmp_path), context)
    fresh = enforcer.open_fixture_phase(binding(tmp_path), metadata_stage='baseline')
    assert fresh is not context
    initialize(enforcer, fresh)


@pytest.mark.parametrize('phase', ['preparation', 'finalization'])
def test_native_phase_supports_private_preparation_and_finalization(tmp_path, phase):
    text = '' if phase == 'preparation' else 'final approved bytes'
    value = NativePhaseBinding('task1', 'attempt1', 'request1', phase, tmp_path, text,
        hashlib.sha256(text.encode()).hexdigest())
    assert value.phase == phase


def test_arbitrary_managed_handle_cannot_claim_it_launched_the_pinned_worker(tmp_path, monkeypatch):
    from app.providers import native_scope
    from app.runtime.processes import ProcessHandle, ProcessManager
    manager = object.__new__(ProcessManager)
    handle = ProcessHandle('task1', 'attempt1', 123, None, tmp_path, tmp_path, object(), None)
    monkeypatch.setattr(native_scope, '_sha', lambda _: OFFICIAL_ENTRY_SHA256)
    monkeypatch.setattr(NativeScopeEnforcer, '_check_live_origin', lambda _: None)
    entry = tmp_path / 'foreign.exe'
    entry.write_bytes(b'not a model runtime')
    with pytest.raises(NativeScopeError, match='OWNED_LAUNCH'):
        NativeScopeEnforcer().bind_native_phase(manager, handle, binding(tmp_path), entry)


def test_baseline_then_restricted_requires_the_exact_mcp_key_set(tmp_path):
    enforcer = NativeScopeEnforcer()
    context = enforcer.open_fixture_phase(binding(tmp_path), metadata_stage='baseline')
    initialize(enforcer, context)
    enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
    baseline = configuration()
    baseline['mcp_servers']['private.example.name']['enabled'] = True
    enforcer.observe_rpc_response('config/read', baseline, context)
    initialize(enforcer, context)
    enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
    restricted = configuration()
    restricted['mcp_servers']['extra'] = {'enabled': False}
    with pytest.raises(NativeScopeError, match='KEY_SET_CHANGED'):
        enforcer.observe_rpc_response('config/read', restricted, context)


def test_exported_policy_mutation_does_not_change_authority(tmp_path):
    original = CONTROL_POLICY['controls']['agents.enabled']
    try:
        CONTROL_POLICY['controls']['agents.enabled'] = True
        enforcer = NativeScopeEnforcer()
        context = enforcer.open_fixture_phase(binding(tmp_path))
        initialize(enforcer, context)
        enforcer.authorize_rpc('config/read', {'cwd': str(tmp_path), 'includeLayers': False}, context)
        result = configuration()
        result['controls']['agents.enabled'] = True
        with pytest.raises(NativeScopeError):
            enforcer.observe_rpc_response('config/read', result, context)
    finally:
        CONTROL_POLICY['controls']['agents.enabled'] = original


def test_unknown_worker_source_is_rejected_before_any_process_launch(tmp_path, monkeypatch):
    from app.providers import native_scope
    from app.runtime.processes import ProcessHandle, ProcessManager
    manager = object.__new__(ProcessManager)
    handle = ProcessHandle('task1', 'attempt1', 123, None, tmp_path, tmp_path, object(), None)
    starts = []
    monkeypatch.setattr(ProcessManager, 'start', lambda *args, **kwargs: starts.append(args) or handle)
    monkeypatch.setattr(NativeScopeEnforcer, '_check_live_origin', lambda _: None)
    entry = tmp_path / 'official.exe'
    entry.write_bytes(b'synthetic fixed entry')
    monkeypatch.setattr(native_scope, '_sha', lambda path: OFFICIAL_ENTRY_SHA256
        if path == entry else '0' * 64)
    with pytest.raises(NativeScopeError, match='WORKER_SOURCE_PIN_MISMATCH'):
        NativeScopeEnforcer().start_native_phase(manager, binding(tmp_path), entry)
    assert starts == []


def test_other_configured_provider_alias_is_not_the_audited_route(tmp_path):
    text = 'private inline source'
    with pytest.raises(NativeScopeError):
        NativePhaseBinding('task1','attempt1','request1','review',tmp_path,text,
            hashlib.sha256(text.encode()).hexdigest(),provider_id='unknown-route')
