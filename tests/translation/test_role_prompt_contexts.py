"""Translation and comparison receive separate, task-free role contexts."""
import asyncio
import hashlib
import json
from dataclasses import replace
from contextlib import closing

import pytest

from translation.fakes import claude_turn, service


@pytest.mark.parametrize('purpose,source,target_language', [
    ('input', '保留原文件。', 'en'),
    ('output', 'Keep the original file.', 'zh-CN'),
    ('clarification', 'Keep the original file.', 'zh-CN'),
], ids=['input', 'output', 'clarification'])
def test_translation_calls_attach_distinct_loaded_roles(client, purpose, source, target_language):
    _, task, attempt = claude_turn(client)
    translation = service(client)
    result = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source=source,
        source_language='zh-CN' if target_language=='en' else 'en',
        target_language=target_language, purpose=purpose))
    assert result.status == 'READY'
    translator = translation.translator.calls[0]
    checker = translation.checker.calls[0]
    for request, phase in ((translator, 'translate'), (checker, 'check')):
        role = getattr(request, 'role_prompt', None)
        assert role, f'{phase} request must attach loaded instructions'
        assert role['version'] == '1.0' and role['phase'] == phase
        assert role['sha256'] == hashlib.sha256(role['instruction'].encode()).hexdigest()
        assert 'untrusted data' in role['instruction']
        assert 'permissions' in role['instruction'] and 'publication' in role['instruction']
    assert translator.role_prompt['id'] != checker.role_prompt['id']
    assert 'faithful translator' in translator.role_prompt['instruction']
    assert 'Compare the source and candidate' in checker.role_prompt['instruction']
    assert translator.role_prompt is not checker.role_prompt
    assert translator.previous == {} and translator.findings == ()
    assert checker.previous == translation.translator.responses[translator.request_id].blocks
    assert checker.findings == ()
    context = json.dumps([translator.__dict__, checker.__dict__])
    assert 'task_contract' not in context and 'conversation_history' not in context


def test_checker_does_not_receive_prior_candidate_findings(client):
    _, task, attempt = claude_turn(client)
    def first_bad(request):
        return {} if request.candidate == 1 else {block['block_id']: 'Keep the original file.' for block in request.blocks}
    translation = service(client, transform=first_bad)
    result = asyncio.run(translation.translate(task_id=task, attempt_id=attempt,
        source='保留原文件。', source_language='zh-CN', target_language='en', purpose='input'))
    assert result.status == 'READY' and len(translation.translator.calls) == 2
    assert translation.translator.calls[1].findings, 'translator needs the bounded repair issues'
    assert translation.checker.calls[1].findings == (), 'checker must compare independently of old QA findings'


def test_changed_role_instructions_invalidate_ready_jobs_and_cached_qa(client, monkeypatch):
    from app.translation import service as service_module
    from contextlib import closing
    _, task, attempt = claude_turn(client)
    translation = service(client)
    options = dict(task_id=task, attempt_id=attempt, source='保留原文件。',
        source_language='zh-CN', target_language='en', purpose='input')
    first = asyncio.run(translation.translate(**options))
    original = service_module.load_role_prompt
    def revised(phase, family, **kwargs):
        role = original(phase, family, **kwargs)
        if phase == 'check':
            role['instruction'] += '\nRevised semantic comparison policy.'
            role['sha256'] = hashlib.sha256(role['instruction'].encode()).hexdigest()
        return role
    monkeypatch.setattr(service_module, 'load_role_prompt', revised)
    changed = asyncio.run(translation.translate(**options))
    cached = asyncio.run(translation.translate(**options, explicit_retry=True))
    assert first.status == changed.status == cached.status == 'READY'
    assert first.job_id != changed.job_id, 'old READY jobs cannot bypass the changed role policy'
    assert not changed.cache_hit and cached.cache_hit
    assert len(translation.translator.calls) == len(translation.checker.calls) == 2
    with closing(translation.database.connect()) as connection:
        policies = [row[0] for row in connection.execute('SELECT DISTINCT policy_version FROM translation_jobs')]
    assert len(policies) == 2 and all(':roles:' in policy for policy in policies)


@pytest.mark.parametrize('field', ['provider_id', 'model_id', 'connection_version'])
def test_changed_checker_identity_invalidates_cached_semantic_qa(client, field):
    _, task, attempt = claude_turn(client)
    translation = service(client)
    options = dict(task_id=task, attempt_id=attempt, source='保留原文件。',
        source_language='zh-CN', target_language='en', purpose='input')
    first = asyncio.run(translation.translate(**options))
    identity = translation.checker.identity
    if field == 'model_id':
        identity = identity.model_copy(update={'identity': identity.identity.model_copy(update={'model_id': 'changed-checker'})})
    else:
        identity = identity.model_copy(update={field: 'changed-checker'})
    if field == 'provider_id':
        from contextlib import closing
        with closing(translation.database.connect()) as connection:
            connection.execute('''INSERT INTO provider_profiles(id,adapter,model_id,family,connection_id,
                identity_status,identity_source,connection_version)
                SELECT ?,adapter,model_id,family,connection_id,identity_status,identity_source,connection_version
                FROM provider_profiles WHERE id=?''', (identity.provider_id, translation.checker.identity.provider_id))
    translation.checker.identity = identity
    changed = asyncio.run(translation.translate(**options))
    assert first.status == changed.status == 'READY'
    assert changed.job_id != first.job_id and not changed.cache_hit
    assert len(translation.checker.calls) == len(translation.translator.calls) == 2


@pytest.mark.parametrize('code', ['AMBIGUITY', 'OCR_AMBIGUITY', 'MISSING_SOURCE'])
def test_translator_reported_source_issue_requires_input_even_when_checker_finds_none(client, code):
    _, task, attempt = claude_turn(client)
    translation = service(client)
    original = translation.translator.invoke
    async def issue(request):
        response = await original(request)
        finding = dict(block_id=request.blocks[0]['block_id'], code=code, severity='major',
            message='Source content cannot be translated reliably.', source_locator=request.blocks[0]['source_locator'])
        return replace(response, findings=(finding,))
    translation.translator.invoke = issue
    result = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source='保留原文件。',
        source_language='zh-CN', target_language='en', purpose='input'))
    assert result.status == 'NEEDS_INPUT' and result.candidate_attempts == 1
    assert translation.checker.calls[0].findings == ()
    with closing(translation.database.connect()) as connection:
        qa = json.loads(connection.execute('SELECT qa_json FROM translation_candidates WHERE job_id=?', (result.job_id,)).fetchone()[0])
    assert code in [finding['code'] for finding in qa['semantic_findings']]


def test_incomplete_translator_report_cannot_become_ready(client):
    _, task, attempt = claude_turn(client)
    translation = service(client)
    original = translation.translator.invoke
    async def incomplete(request):
        return replace(await original(request), complete=False)
    translation.translator.invoke = incomplete
    result = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source='保留原文件。',
        source_language='zh-CN', target_language='en', purpose='input'))
    assert result.status == 'FAILED' and result.candidate_attempts == 3


@pytest.mark.parametrize('malformed', ['missing_fields', 'foreign_block', 'wrong_locator', 'invalid_container'])
def test_malformed_translator_findings_fail_closed(client, malformed):
    _, task, attempt = claude_turn(client)
    translation = service(client)
    original = translation.translator.invoke
    async def invalid(request):
        response = await original(request)
        finding = dict(block_id=request.blocks[0]['block_id'], code='AMBIGUITY', severity='major',
            message='Source issue.', source_locator=request.blocks[0]['source_locator'])
        if malformed == 'missing_fields': finding.pop('severity')
        if malformed == 'foreign_block': finding['block_id'] = 'foreign-block'
        if malformed == 'wrong_locator': finding['source_locator'] = 'other/source'
        return replace(response, findings=None if malformed == 'invalid_container' else (finding,))
    translation.translator.invoke = invalid
    result = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source='保留原文件。',
        source_language='zh-CN', target_language='en', purpose='input'))
    assert result.status == 'FAILED' and result.clarification == 'B_TRANSLATION_FINDINGS_INVALID'


def test_current_translator_and_checker_findings_both_reach_qa(client):
    _, task, attempt = claude_turn(client)
    def checker_issue(request):
        return [dict(block_id=request.blocks[0]['block_id'], code='NUMBER_CHANGED', severity='major',
            message='Checker discrepancy.', source_locator=request.blocks[0]['source_locator'])]
    translation = service(client, findings=checker_issue)
    original = translation.translator.invoke
    async def translator_issue(request):
        response = await original(request)
        finding = dict(block_id=request.blocks[0]['block_id'], code='NEGATION_CHANGED', severity='major',
            message='Translator discrepancy.', source_locator=request.blocks[0]['source_locator'])
        return replace(response, findings=(finding,))
    translation.translator.invoke = translator_issue
    result = asyncio.run(translation.translate(task_id=task, attempt_id=attempt, source='保留原文件。',
        source_language='zh-CN', target_language='en', purpose='input'))
    assert result.status == 'FAILED' and result.candidate_attempts == 3
    assert all(request.findings == () for request in translation.checker.calls)
    with closing(translation.database.connect()) as connection:
        reports = [json.loads(row[0]) for row in connection.execute('SELECT qa_json FROM translation_candidates WHERE job_id=?', (result.job_id,))]
    assert all({'NEGATION_CHANGED', 'NUMBER_CHANGED'} <= {finding['code'] for finding in qa['semantic_findings']} for qa in reports)

