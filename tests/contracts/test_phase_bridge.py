"""Explicit in-memory runtime receipts; these tests make no real scope claim."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from app.contracts.providers import AgentRequest, ProviderContract, ProviderIdentity
from app.contracts.tasks import contract_digest, validate_contract
from app.providers.phase_bridge import PhaseBridge, PhaseCapture, PhaseStarted, UsageReceipt
from app.usage.normalization import normalize_usage


def sha(data):
    return hashlib.sha256(data).hexdigest()


def provider(family='glm', status='verified'):
    return ProviderContract.model_validate(dict(schema_version='1.0', provider_id='memory-'+family,
        identity=dict(adapter='zcode' if family=='glm' else 'codex', model_id=family+'-memory',
                      family=family, connection_id='memory-connection'), identity_status=status,
        identity_source='synthetic_memory_response' if status=='verified' else None,
        connection_version='memory-v1'))


class MemoryCapability:
    """A verifier for a runtime which only yields supplied in-memory records."""
    def __init__(self):
        self.authorizations = []

    def require_verified(self, selected):
        selected.require_executable()
        if selected.identity_source != 'synthetic_memory_response':
            raise ValueError('MEMORY_CAPABILITY_PROFILE_MISMATCH')

    def authorize(self, request, binding):
        self.authorizations.append((request.role, binding.request_id))
        assert Path(request.prompt_path).resolve().is_relative_to(Path(request.workspace).resolve())


class MemoryRuntime:
    def __init__(self, records):
        self.records = records
        self.starts = []
        self.scope_capability = MemoryCapability()
        self.cancelled = []

    async def run(self, request, binding):
        self.starts.append(request)
        for record in self.records:
            yield record

    async def cancel(self, task, attempt):
        self.cancelled.append((task, attempt))


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path/'task'/'attempt'
    (root/'b'/'prompts').mkdir(parents=True)
    (root/'a'/'prompts').mkdir(parents=True)
    (root/'evidence').mkdir()
    selected = provider()
    value = dict(task_id='task',attempt_id='attempt',contract_version='1.0',domain='document',
        model_family='gpt',route_snapshot_id='route',objective='Return the known arithmetic result',
        method='Check the supplied source',inputs=[dict(id='source',ref='input/source.txt',sha256=sha(b'2+3=5'))],
        constraints=[dict(id='C1',text='Only the approved result',mandatory=True)],
        deliverables=[dict(id='answer',kind='document',write_scope='b/result.txt',require_a_canonical=False)],
        acceptance=[dict(id='C',mandatory=True,verifier='C',evidence_type='artifact',condition='actual content',semantic=False),
                    dict(id='A',mandatory=True,verifier='A',evidence_type='review',condition='arithmetic correctness',semantic=True)],
        dependencies=[],budget=dict(total_tokens=100,reserved_a_tokens=20),b_write_scopes=['b'],
        a_responsibilities=['problem_modeling','core_reasoning','method_choice','evidence_judgment','final_review'],
        guidance_depth='ordinary',full_read_required=True,source_unit_ids=['source-unit'])
    contract = validate_contract(value)
    prompt_path = root/'b'/'prompts'/'local-request.json'
    prompt_path.write_text(json.dumps(dict(phase='execution',contract=value,evidence_package={})),encoding='utf-8')
    request = AgentRequest('task','attempt','B',ProviderIdentity(**selected.identity.model_dump()),
                           str(prompt_path),str(root/'b'),'1.0')
    response = dict(schema_version='1.0',phase='execution',request_id='local-request',task_id='task',
        attempt_id='attempt',contract_version='1.0',contract_sha256=contract_digest(contract),
        deliverable_id='answer',language='zh-CN',content='结果为 5。')
    receipts = (UsageReceipt('receipt1',1,dict(input_tokens=10,output_tokens=2)),)
    capture = PhaseCapture('local-request',selected,json.dumps(response,ensure_ascii=False),
        'remote-request','remote-execution',receipts)
    return root,selected,contract,request,response,capture


def run(prepared, *, response=None, capture=None, selected=None, runtime=None):
    _, current, _, request, original, original_capture = prepared
    if capture is None:
        capture = replace(original_capture,final_text=json.dumps(response or original,ensure_ascii=False))
    runtime = runtime or MemoryRuntime([PhaseStarted('local-request','remote-request','remote-execution'),capture])
    bridge = PhaseBridge(runtime,selected or current)
    async def collect():
        return [event async for event in bridge.run(request)]
    return asyncio.run(collect()),runtime,bridge


def error(events):
    values=[event.payload['reason_code'] for event in events if event.kind=='provider.error']
    assert len(values)==1
    assert not any(event.kind in ('artifact.candidate','review.decision','provider.completed') for event in events)
    return values[0]


def test_actual_final_content_becomes_candidate_and_usage_is_workflow_compatible(prepared):
    events,runtime,bridge=run(prepared)
    assert bridge.scope_enforced is True
    assert len(runtime.starts)==1
    candidate=next(event for event in events if event.kind=='artifact.candidate')
    assert candidate.payload['text']=='结果为 5。'
    assert candidate.payload['byte_sha256']==sha('结果为 5。'.encode())
    assert events[-1].kind=='provider.completed'
    usage=next(event.payload for event in events if event.kind=='provider.usage')
    assert normalize_usage('glm',usage['raw'],usage['source'])['total_tokens']==12
    assert 'final_text' not in repr(prepared[-1]) and '结果' not in repr(prepared[-1])


@pytest.mark.parametrize('field',['task_id','attempt_id','contract_version','contract_sha256','request_id','deliverable_id','content'])
def test_candidate_missing_required_binding_is_rejected(prepared,field):
    response=dict(prepared[4]); response.pop(field)
    events,_,_=run(prepared,response=response)
    assert error(events)=='PHASE_RESPONSE_INVALID'


@pytest.mark.parametrize('field,value',[('attempt_id','old-attempt'),('contract_sha256','0'*64),
                                      ('request_id','old-request'),('deliverable_id','other')])
def test_candidate_cannot_rebind_to_other_request_contract_or_target(prepared,field,value):
    response={**prepared[4],field:value}
    events,_,_=run(prepared,response=response)
    assert error(events)=='PHASE_RESPONSE_BINDING_MISMATCH'


def test_model_supplied_pass_or_extra_attributes_are_rejected(prepared):
    events,_,_=run(prepared,response={**prepared[4],'decision':'PASS'})
    assert error(events)=='PHASE_RESPONSE_INVALID'


def test_claimed_candidate_hash_must_equal_actual_bytes(prepared):
    events,_,_=run(prepared,response={**prepared[4],'byte_sha256':'0'*64})
    assert error(events)=='CANDIDATE_HASH_MISMATCH'


def test_file_candidate_uses_independent_captured_bytes(prepared):
    response=dict(prepared[4]); response.pop('content')
    data='受控实际产物'.encode()
    response.update(artifact_ref='b/result.txt',byte_sha256=sha(data))
    capture=replace(prepared[-1],final_text=json.dumps(response),actual_artifacts={'b/result.txt':data})
    events,_,_=run(prepared,capture=capture)
    assert next(e.payload['text'] for e in events if e.kind=='artifact.candidate')==data.decode()


def test_file_candidate_cannot_claim_other_bytes_or_missing_file(prepared):
    response=dict(prepared[4]); response.pop('content')
    response.update(artifact_ref='b/result.txt',byte_sha256=sha(b'claimed'))
    capture=replace(prepared[-1],final_text=json.dumps(response),actual_artifacts={'b/result.txt':b'actual'})
    events,_,_=run(prepared,capture=capture)
    assert error(events)=='CANDIDATE_HASH_MISMATCH'


def test_no_final_text_never_uses_delta_or_completion_as_content(prepared):
    events,_,_=run(prepared,capture=replace(prepared[-1],final_text=None))
    assert error(events)=='FINAL_TEXT_REQUIRED'


def test_full_private_content_is_preserved_without_public_delta(prepared):
    content='用户给定字面量 sk-fixture-private-token 完整保留'
    events,_,_=run(prepared,response={**prepared[4],'content':content})
    assert next(e.payload['text'] for e in events if e.kind=='artifact.candidate')==content
    assert not any(e.kind in ('model.delta','answer.published') for e in events)


def test_unknown_identity_is_rejected_before_runtime_start(prepared):
    events,runtime,bridge=run(prepared,selected=provider(status='unknown'))
    assert error(events)=='PROVIDER_IDENTITY_UNVERIFIED'
    assert runtime.starts==[] and bridge.scope_enforced is False


def test_scope_boolean_cannot_replace_verifiable_capability(prepared):
    runtime=MemoryRuntime([]); runtime.scope_capability=None; runtime.scope_enforced=True
    events,runtime,bridge=run(prepared,runtime=runtime)
    assert error(events)=='SCOPE_CAPABILITY_UNVERIFIED'
    assert runtime.starts==[] and bridge.scope_enforced is False


def test_scope_verifier_returning_a_boolean_is_not_proof(prepared):
    runtime=MemoryRuntime([])
    runtime.scope_capability.require_verified=lambda _: True
    events,runtime,bridge=run(prepared,runtime=runtime)
    assert error(events)=='SCOPE_CAPABILITY_UNVERIFIED'
    assert runtime.starts==[] and bridge.scope_enforced is False


def test_gpt_profile_cannot_be_substituted_for_zcode_b_before_start(prepared):
    selected=provider('gpt')
    current=list(prepared)
    current[1]=selected
    current[3]=replace(prepared[3],identity=ProviderIdentity(**selected.identity.model_dump()))
    events,runtime,_=run(tuple(current))
    assert error(events)=='PROVIDER_ROLE_MISMATCH'
    assert runtime.starts==[]


def test_duplicate_usage_receipts_do_not_double_count(prepared):
    receipt=prepared[-1].usage_receipts[0]
    events,_,_=run(prepared,capture=replace(prepared[-1],usage_receipts=(receipt,receipt,replace(receipt,event_id='new-receipt'))))
    usages=[e for e in events if e.kind=='provider.usage']
    assert len(usages)==1 and usages[0].payload['raw']['input_tokens']==10


def test_conflicting_same_sequence_usage_never_finishes(prepared):
    receipt=prepared[-1].usage_receipts[0]
    events,_,_=run(prepared,capture=replace(prepared[-1],usage_receipts=(receipt,replace(receipt,event_id='conflict',raw={'input_tokens':20,'output_tokens':2}))))
    assert error(events)=='USAGE_RECEIPT_CONFLICT'


def test_capture_observed_identity_must_match_pinned_connection(prepared):
    altered=provider().model_copy(update={'connection_version':'changed'})
    events,_,_=run(prepared,capture=replace(prepared[-1],observed_provider=altered))
    assert error(events)=='CAPTURE_IDENTITY_MISMATCH'


def review_prepared(prepared):
    root,_,contract,request,_,capture=prepared
    selected=provider('gpt')
    proof=dict(criterion_id='C',revision_id='actual-revision',byte_sha256=sha(b'candidate'),
               passed=True,verifier='C',details={})
    proof_bytes=json.dumps(proof).encode()
    (root/'evidence'/'proof.json').write_bytes(proof_bytes)
    evidence=dict(criterion_id='C',revision_id='actual-revision',ref='proof.json',
                  sha256=sha(proof_bytes),verifier='C',passed=True)
    package=dict(revision_id='actual-revision',byte_sha256=sha(b'candidate'),candidate_content='candidate',
                 mechanical_evidence=[evidence],sources=[dict(ref='input/source.txt',sha256=sha(b'2+3=5'),content='2+3=5')])
    candidate_path=root/'candidate.txt'
    candidate_path.write_bytes(b'candidate')
    package['artifact_path']=str(candidate_path)
    path=root/'a'/'prompts'/'local-request.json'
    path.write_text(json.dumps(dict(phase='review',contract=contract.model_dump(mode='json'),evidence_package=package)))
    request=replace(request,role='A',identity=ProviderIdentity(**selected.identity.model_dump()),prompt_path=str(path),workspace=str(root/'a'))
    response=dict(schema_version='1.0',phase='review',request_id='local-request',task_id='task',attempt_id='attempt',
        contract_version='1.0',contract_sha256=contract_digest(contract),revision_id='actual-revision',
        byte_sha256=sha(b'candidate'),decision='PASS',criterion_results={'A':True},
        read_unit_ids=['source-unit'],source_refs=['input/source.txt'],evidence_refs=['proof.json'],issues=[],sampling_note=None)
    return root,selected,contract,request,response,replace(capture,observed_provider=selected,final_text=json.dumps(response))


def test_review_is_bound_to_actual_revision_sources_and_mechanical_evidence(prepared):
    events,_,_=run(review_prepared(prepared))
    review=next(e.payload for e in events if e.kind=='review.decision')
    assert review['decision']=='PASS' and review['revision_id']=='actual-revision'
    assert review['criterion_results']=={'A':True}
    assert 'canonical_author' not in review and not any(e.kind=='answer.published' for e in events)

@pytest.mark.parametrize('clarification',[None,'Do not delete the original files. Should I use only 2 source files?'])
def test_review_native_capture_retains_complete_question_and_legacy_shape(prepared,clarification):
    current=review_prepared(prepared); response={**current[4],'decision':'NEED_EVIDENCE','issues':['private evidence diagnostic']}
    if clarification is not None: response['clarification_text']=clarification
    capture=replace(current[-1],final_text=json.dumps(response,ensure_ascii=False))
    events,runtime,_=run(current,capture=capture)
    review=next(event.payload for event in events if event.kind=='review.decision')
    assert review.get('clarification_text')==clarification
    assert review['raw_response_sha256']==sha(capture.final_text.encode())
    assert len(runtime.starts)==1 and events[-1].kind=='provider.completed'
    assert not any(event.kind in ('input.required','answer.published') for event in events)


@pytest.mark.parametrize('field,value',[('revision_id','old-revision'),('byte_sha256','0'*64),
                                      ('evidence_refs',[]),('source_refs',['other']),('criterion_results',{'C':True})])
def test_review_cannot_rebind_or_self_score_mechanical_checks(prepared,field,value):
    current=review_prepared(prepared)
    events,_,_=run(current,response={**current[4],field:value})
    assert error(events)=='REVIEW_BINDING_MISMATCH'


def test_review_changed_evidence_bytes_are_rejected(prepared):
    current=review_prepared(prepared)
    (current[0]/'evidence'/'proof.json').write_bytes(b'{}')
    events,_,_=run(current)
    assert error(events)=='REVIEW_EVIDENCE_INVALID'


def test_native_review_preserves_structured_scope_and_repair_details(prepared):
    current = review_prepared(prepared)
    finding = dict(id='DEF-1', requirement_id='A', location='candidate:1',
        impact='Unsupported arithmetic conclusion', required_change='Use the source arithmetic.',
        pass_condition='The conclusion matches the complete source.')
    response = {**current[4], 'decision': 'REPAIR', 'review_scope': ['candidate:1'], 'findings': [finding]}
    events, _, _ = run(current, response=response)
    result = next(event.payload for event in events if event.kind == 'review.decision')
    assert result['findings'] == [finding] and result['review_scope'] == ['candidate:1']
    assert not any(event.kind == 'answer.published' for event in events)


@pytest.mark.parametrize('mutation', ['open_pass', 'foreign_requirement', 'duplicate_id'])
def test_native_review_rejects_open_pass_or_invalid_defect_identity(prepared, mutation):
    current = review_prepared(prepared)
    finding = dict(id='DEF-1', requirement_id='A', location='candidate:1',
        impact='Unsupported conclusion', required_change='Correct it.', pass_condition='Matches source.')
    response = {**current[4], 'decision': 'REPAIR', 'findings': [finding]}
    if mutation == 'open_pass':
        response['decision'] = 'PASS'
    elif mutation == 'foreign_requirement':
        finding['requirement_id'] = 'FOREIGN'
    else:
        response['findings'].append(dict(finding))
    events, _, _ = run(current, response=response)
    assert error(events) == 'REVIEW_BINDING_MISMATCH'


def test_accepted_without_any_remote_ref_cannot_emit_a_candidate(prepared):
    capture=replace(prepared[-1],external_request_id=None,external_execution_id=None)
    runtime=MemoryRuntime([PhaseStarted('local-request',None,None),capture])
    events,_,_=run(prepared,runtime=runtime)
    assert error(events)=='REMOTE_REFERENCE_REQUIRED'
    assert events[0].kind=='provider.started' and events[0].payload['accepted'] is True


def test_repeated_final_capture_is_rejected_before_any_candidate_is_emitted(prepared):
    runtime=MemoryRuntime([PhaseStarted('local-request','remote-request','remote-execution'),prepared[-1],prepared[-1]])
    events,_,_=run(prepared,runtime=runtime)
    assert error(events)=='CAPTURE_REQUEST_BINDING_MISMATCH'


def test_prompt_changed_while_runtime_runs_cannot_rebind_the_original_request(prepared):
    class ChangingRuntime(MemoryRuntime):
        async def run(self,request,binding):
            self.starts.append(request)
            yield self.records[0]
            body=json.loads(Path(request.prompt_path).read_text())
            body['contract']['objective']='changed while native work runs'
            Path(request.prompt_path).write_text(json.dumps(body))
            yield self.records[1]
    runtime=ChangingRuntime([PhaseStarted('local-request','remote-request','remote-execution'),prepared[-1]])
    events,_,_=run(prepared,runtime=runtime)
    assert error(events)=='PHASE_REQUEST_CHANGED'


def test_scope_revoked_while_runtime_runs_cannot_emit_content(prepared):
    class RevokedRuntime(MemoryRuntime):
        async def run(self,request,binding):
            self.starts.append(request)
            yield self.records[0]
            self.scope_capability=None
            yield self.records[1]
    runtime=RevokedRuntime([PhaseStarted('local-request','remote-request','remote-execution'),prepared[-1]])
    events,_,bridge=run(prepared,runtime=runtime)
    assert error(events)=='SCOPE_CAPABILITY_UNVERIFIED'
    assert bridge.scope_enforced is False


def test_account_cumulative_scope_keeps_global_receipt_sequence_for_the_ledger(prepared):
    receipt=replace(prepared[-1].usage_receipts[0],sequence=101,mode='cumulative',cumulative_scope='account-session')
    events,_,_=run(prepared,capture=replace(prepared[-1],usage_receipts=(receipt,)))
    usage=next(e.payload for e in events if e.kind=='provider.usage')
    assert usage['mode']=='cumulative' and usage['cumulative_scope']=='account-session'
    assert usage['receipt_sequence']==101


@pytest.mark.parametrize('change',[{'finished':False},{'exit_code':1},{'exit_code':True}])
def test_incomplete_or_failed_native_capture_never_yields_completion(prepared,change):
    events,_,_=run(prepared,capture=replace(prepared[-1],**change))
    assert error(events)=='CAPTURE_NOT_COMPLETED'


def test_absent_real_usage_stays_unknown(prepared):
    events,_,_=run(prepared,capture=replace(prepared[-1],usage_receipts=()))
    usage=next(e.payload for e in events if e.kind=='provider.usage')
    assert usage['source']=='unknown'
    assert normalize_usage('glm',usage['raw'],usage['source'])['total_tokens'] is None


def test_duplicate_json_keys_are_rejected(prepared):
    final=prepared[-1].final_text[:-1]+',"attempt_id":"old-attempt"}'
    events,_,_=run(prepared,capture=replace(prepared[-1],final_text=final))
    assert error(events)=='PHASE_RESPONSE_INVALID'


def test_review_cannot_accept_damaged_actual_candidate_bytes(prepared):
    current=review_prepared(prepared)
    (current[0]/'candidate.txt').write_bytes(b'changed')
    events,_,_=run(current)
    assert error(events)=='REVIEW_ARTIFACT_INVALID'


def test_review_rechecks_evidence_after_the_terminal_native_iterator_closes(prepared):
    current=review_prepared(prepared)
    class DamagingRuntime(MemoryRuntime):
        async def run(self,request,binding):
            self.starts.append(request)
            yield self.records[0]
            yield self.records[1]
            (current[0]/'evidence'/'proof.json').write_bytes(b'{}')
    runtime=DamagingRuntime([PhaseStarted('local-request','remote-request','remote-execution'),current[-1]])
    events,_,_=run(current,runtime=runtime)
    assert error(events)=='REVIEW_EVIDENCE_INVALID'
