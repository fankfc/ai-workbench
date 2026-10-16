import asyncio
from contextlib import closing
import json
import pytest
from app.translation.service import TranslationService
from app.translation.ports import TranslationResponse
from translation.fakes import service,claude_turn,FakeTranslationPort

def translate(translation,task,attempt,source='保留原文件。',**options):
    return asyncio.run(translation.translate(task_id=task,attempt_id=attempt,source=source,source_language='zh-CN',target_language='en',purpose='input',**options))

@pytest.mark.parametrize('issue',['NEGATION_CHANGED','UNCERTAINTY_CHANGED','NUMBER_CHANGED'])
def test_known_major_semantic_finding_never_earns_ready(client,issue):
    _,task,attempt=claude_turn(client)
    def findings(request): return [dict(block_id=request.blocks[0]['block_id'],code=issue,severity='major',message='Known golden error.',source_locator=request.blocks[0]['source_locator'])]
    translation=service(client,findings=findings)
    result=translate(translation,task,attempt)
    assert result.status=='FAILED' and result.candidate_attempts==3
    with closing(client.app.state.database.connect()) as connection:
        rows=connection.execute('SELECT qa_json FROM translation_candidates WHERE job_id=?',(result.job_id,)).fetchall()
        assert all(issue in [f['code'] for f in json.loads(row[0])['semantic_findings']] for row in rows)

def test_connection_retries_are_three_calls_but_one_candidate_and_all_usage_survives(client):
    _,task,attempt=claude_turn(client)
    class FailedPort(FakeTranslationPort):
        async def invoke(self,request): self.calls.append(request); raise OSError('fake connection unavailable')
        async def request_status(self,request_id): return 'failed'
    translator=FailedPort('translate'); checker=FakeTranslationPort('check')
    translation=TranslationService(client.app.state.database.path,translator,checker)
    result=translate(translation,task,attempt)
    assert result.status=='FAILED' and result.candidate_attempts==1 and len(translator.calls)==3 and not checker.calls
    from app.usage.ledger import UsageLedger
    assert UsageLedger(client.app.state.database.path).summary(task)['unknown_requests']==3

def test_unconfirmed_connection_is_never_reissued_automatically(client):
    _,task,attempt=claude_turn(client)
    class UnknownPort(FakeTranslationPort):
        async def invoke(self,request): self.calls.append(request); raise TimeoutError('fake result unknown')
        async def request_status(self,request_id): return 'unknown'
    translator=UnknownPort('translate'); checker=FakeTranslationPort('check')
    translation=TranslationService(client.app.state.database.path,translator,checker)
    result=translate(translation,task,attempt)
    assert result.status=='FAILED' and result.candidate_attempts==1 and len(translator.calls)==1
    again=translate(translation,task,attempt,job_id=result.job_id)
    assert again.status=='FAILED' and len(translator.calls)==1

def test_crash_after_external_completion_recovers_response_without_duplicate_execution(client):
    _,task,attempt=claude_turn(client)
    class SimulatedProcessCrash(BaseException): pass
    class CrashPort(FakeTranslationPort):
        async def invoke(self,request):
            await super().invoke(request)
            raise SimulatedProcessCrash()
    translator=CrashPort('translate'); checker=FakeTranslationPort('check')
    translation=TranslationService(client.app.state.database.path,translator,checker)
    with pytest.raises(SimulatedProcessCrash): translate(translation,task,attempt)
    resumed=TranslationService(client.app.state.database.path,translator,checker)
    result=translate(resumed,task,attempt)
    assert result.status=='READY' and len(translator.calls)==1 and len(checker.calls)==1

def test_source_change_and_model_version_change_never_reuse_cache(client):
    from dataclasses import replace
    _,task,attempt=claude_turn(client); translation=service(client)
    first=translate(translation,task,attempt)
    changed=translate(translation,task,attempt,'禁止删除原始文件。')
    identity=translation.translator.identity.model_copy(update={'connection_version':'2'})
    translation.translator.identity=identity
    different_model=translate(translation,task,attempt)
    assert first.status==changed.status==different_model.status=='READY'
    assert not changed.cache_hit and not different_model.cache_hit and len(translation.translator.calls)==3

def test_untranslated_chinese_candidate_cannot_be_ready_for_english_context(client):
    _,task,attempt=claude_turn(client)
    translation=service(client,transform=lambda request:{b['block_id']:b['source'] for b in request.blocks})
    result=translate(translation,task,attempt)
    assert result.status=='FAILED'

def test_unknown_usage_blocks_next_translation_budgeted_call(client):
    _,task,attempt=claude_turn(client)
    class UnknownUsage(FakeTranslationPort):
        async def invoke(self,request):
            from dataclasses import replace
            response=await super().invoke(request)
            return replace(response,usage=None)
    translator=UnknownUsage('translate'); checker=FakeTranslationPort('check')
    translation=TranslationService(client.app.state.database.path,translator,checker,max_b_tokens=10000)
    result=translate(translation,task,attempt)
    assert result.status=='FAILED' and len(translator.calls)==1 and not checker.calls

def test_insufficient_translation_budget_blocks_before_external_call(client):
    _,task,attempt=claude_turn(client); translation=service(client,max_b_tokens=1)
    result=translate(translation,task,attempt)
    assert result.status=='FAILED' and not translation.translator.calls and not translation.checker.calls
