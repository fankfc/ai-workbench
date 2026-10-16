import asyncio
import hashlib
from contextlib import closing
from app.translation.glossary import GlossaryStore
from translation.fakes import service,claude_turn

def run(service,task,attempt,source='保留原文件。',**kwargs):
    return asyncio.run(service.translate(task_id=task,attempt_id=attempt,source=source,source_language='zh-CN',target_language='en',purpose='input',**kwargs))

def test_omitted_block_and_known_semantic_error_fail_after_three_candidates(client):
    _,task,attempt=claude_turn(client)
    translation=service(client,transform=lambda request:{})
    result=run(translation,task,attempt,'第一段。\n\n第二段。')
    assert result.status=='FAILED' and result.candidate_attempts==3
    assert len(translation.translator.calls)==len(translation.checker.calls)==3
    with closing(client.app.state.database.connect()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM translation_candidates WHERE job_id=?',(result.job_id,)).fetchone()[0]==3
    assert translation.translator.calls[-1].findings

def test_separate_semantic_findings_block_and_ambiguity_requests_input(client):
    _,task,attempt=claude_turn(client)
    def ambiguous(request):
        return [dict(block_id=request.blocks[0]['block_id'],code='AMBIGUITY',severity='major',message='Two business interpretations.',source_locator=request.blocks[0]['source_locator'])]
    translation=service(client,findings=ambiguous)
    result=run(translation,task,attempt)
    assert result.status=='NEEDS_INPUT' and result.candidate_attempts==1
    assert result.clarification and translation.checker.calls[0].high_impact_blocks==()

def test_cache_context_glossary_model_and_source_are_part_of_key(client):
    _,task,attempt=claude_turn(client)
    translation=service(client); same=hashlib.sha256(b'context-1').hexdigest()
    first=run(translation,task,attempt,context_sha256=same)
    hit=run(translation,task,attempt,context_sha256=same,explicit_retry=True)
    assert first.status==hit.status=='READY' and hit.cache_hit and len(translation.translator.calls)==1
    glossary=GlossaryStore(client.app.state.database.path)
    glossary.put(task,'2','finance',[{'source':'bank','target':'银行','sense':'financial institution'}],reason='finance context')
    changed=run(translation,task,attempt,context_sha256=same,glossary_version='2')
    context=run(translation,task,attempt,context_sha256=hashlib.sha256(b'context-2').hexdigest())
    assert changed.status==context.status=='READY' and not changed.cache_hit and not context.cache_hit
    assert len(translation.translator.calls)==3

def test_translation_and_checker_tokens_both_remain_in_usage(client):
    from app.usage.ledger import UsageLedger
    _,task,attempt=claude_turn(client); translation=service(client)
    run(translation,task,attempt)
    summary=UsageLedger(client.app.state.database.path).summary(task)
    assert summary['total_tokens']==13
    assert {r['function'] for r in summary['requests']}=={'translation'}
    assert {r['role'] for r in summary['requests']}=={'B'}

def test_ready_job_resumes_without_reissuing_external_requests(client):
    _,task,attempt=claude_turn(client); translation=service(client); result=run(translation,task,attempt)
    resumed=service(client)
    again=run(resumed,task,attempt,job_id=result.job_id)
    assert again.status=='READY' and not resumed.translator.calls and not resumed.checker.calls

def test_direct_gpt_never_constructs_forced_translation_job(client):
    with closing(client.app.state.database.connect()) as connection:
        connection.execute("UPDATE provider_profiles SET identity_status='verified',identity_source='fixture:fake' WHERE id='fake-gpt'")
    conversation=client.post('/v1/conversations',json={'title':'gpt'}).json()['id']
    task=client.post(f'/v1/conversations/{conversation}/turns',json={'text':'中文','provider_profile_id':'fake-gpt','client_request_id':'gpt'}).json()['task_id']
    with closing(client.app.state.database.connect()) as connection:
        attempt=connection.execute('SELECT attempt_id FROM task_runs WHERE task_id=?',(task,)).fetchone()[0]
    translation=service(client); result=run(translation,task,attempt,'中文')
    assert result.status=='NATIVE' and result.text=='中文' and not translation.translator.calls
    with closing(client.app.state.database.connect()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM translation_jobs WHERE task_id=?',(task,)).fetchone()[0]==0
